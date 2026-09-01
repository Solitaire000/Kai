"""
模型路由层 (Model Router)
=========================
这是整个系统"可以随便换模型"的核心。上层 agent 代码永远只调用
router.chat(messages, complex=False)，不需要知道背后到底是哪个模型在跑。

v2 改动说明（修复"在线模型无法加载"问题）：
1. 不再用 is_online() 的结果"一票否决"是否尝试在线服务商。
   旧版逻辑：先探测 baidu.com/aliyun.com 能不能通 -> 通不了就直接走本地模型，
   根本不会去尝试 siliconflow/openrouter/anthropic。
   问题：很多用户用代理/VPN访问 openrouter、anthropic 这类境外服务时，
   代理经常会让 baidu.com 这类境内站点变得不可达（全局代理）或反过来
   （分流代理只代理境外站点，baidu本身没走代理但企业网络限制了直连），
   导致 is_online() 判断错误，即使 OpenRouter 实际是可以连通的，也被
   提前拦截，永远走本地模型 -> 本地模型文件又没下载 -> 完全无法对话。
   新逻辑：直接尝试每个已启用且配置了key的在线服务商，用真实请求的
   异常类型来判断是"网络问题"还是"服务本身问题"（key错误/欠费/限流等），
   is_online() 只作为 /status 展示和"本地模型是否值得懒加载"的参考，不再
   拦截在线请求。
2. 每次调用都加了显式超时(connect/read)，避免网络不通时卡住几分钟才报错
   （旧版用 openai SDK 默认超时，网络异常时经常要等很久才会失败）。
3. 失败原因不再吞掉：每个 provider 失败的具体异常信息会收集起来，
   返回给上层，可以显示在 UI / status 里，方便定位到底是"没配key"
   "key错误""模型名不存在"还是"网络不通"。
4. 支持强制指定某个 provider 或 local（UI 里手动选择模型时用），
   不强制走"cheap优先，complex才试premium"的自动策略。
5. 新增 list_models()，给 UI 生成模型下拉列表用。
"""
import os
import logging
from openai import OpenAI, APIConnectionError, APITimeoutError

from .network import NetworkChecker

logger = logging.getLogger("kai.model_router")

# 一眼假的占位符 key 的特征，用于在 status/模型列表里提示"这个其实没配置"
_PLACEHOLDER_MARKERS = ("xxxx", "your_key", "sk-xxxxxxxxxxxxxxxx")


class LocalModelUnavailable(Exception):
    pass


def _looks_like_placeholder(key: str) -> bool:
    if not key:
        return True
    lowered = key.lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


class ModelRouter:
    def __init__(self, config: dict, base_dir: str):
        self.cfg = config["model"]
        self.base_dir = base_dir
        net_cfg = config["network"]
        self.network = NetworkChecker(
            net_cfg["check_urls"], net_cfg["timeout_seconds"], net_cfg["cache_seconds"]
        )
        self._local_llm = None  # 懒加载，避免每次启动都占内存/加载时间
        self._request_timeout = net_cfg.get("request_timeout_seconds", 20)

    # ---------------- 对外唯一接口 ----------------
    def chat(self, messages: list, complex: bool = False, max_tokens: int = 800,
              force_provider: str = None, tools: list = None) -> dict:
        """
        messages: 标准 OpenAI 格式 [{"role": "user"/"system"/"assistant", "content": "..."}]
        force_provider: None=自动路由；"local"=强制本地；provider的name=强制某个在线服务商
        tools: OpenAI function-calling 格式的工具schema列表（来自 SkillsManager），为None则不启用工具调用
        返回: {"text"/"tool_calls": ..., "source": ..., "degraded": bool, "errors": [失败详情...]}
        """
        errors = []

        if force_provider == "local":
            return self._chat_local(messages, max_tokens, degraded=False, tools=tools)

        if force_provider and force_provider != "auto":
            result, err = self._call_provider_by_name(force_provider, messages, max_tokens, tools)
            if result is not None:
                return result
            errors.append(err)
            logger.warning(f"强制指定的服务商 {force_provider} 调用失败: {err}")
            local = self._chat_local(messages, max_tokens, degraded=True, tools=tools)
            local["errors"] = errors
            return local

        # 自动路由：直接尝试在线服务商（不再被 is_online() 提前拦截）
        result, errors = self._try_online_providers(messages, complex, max_tokens, tools)
        if result is not None:
            return result

        if errors:
            logger.warning(f"所有在线服务商均失败，降级到本地离线模型。原因: {errors}")
        else:
            logger.info("没有可用的在线服务商（未启用或未配置key），使用本地离线模型")

        local = self._chat_local(messages, max_tokens, degraded=True, tools=tools)
        local["errors"] = errors
        return local

    # ---------------- 在线服务商 ----------------
    def _build_client(self, provider: dict) -> OpenAI:
        return OpenAI(
            api_key=os.environ.get(provider["api_key_env"]),
            base_url=provider["base_url"],
            timeout=self._request_timeout,
            max_retries=1,
        )

    def _call_one_provider(self, provider: dict, messages: list, max_tokens: int, tools: list = None):
        """返回 (result_dict_or_None, error_string_or_None)"""
        api_key = os.environ.get(provider["api_key_env"])
        if not api_key:
            return None, f"{provider['name']}: 未设置环境变量 {provider['api_key_env']}（secrets.yaml里没填）"
        if _looks_like_placeholder(api_key):
            return None, f"{provider['name']}: 配置的是占位符 key（还没换成真实key）"

        kwargs = dict(
            model=provider["model"],
            messages=messages,
            max_tokens=max_tokens,
            temperature=provider.get("temperature", 0.7),
            # 免费/廉价模型很容易在长回复里陷入"查询天气查询天气查询天气..."
            # 这种复读循环，加一点 frequency_penalty 能明显缓解
            frequency_penalty=provider.get("frequency_penalty", 0.3),
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            client = self._build_client(provider)
            resp = client.chat.completions.create(**kwargs)
            msg = resp.choices[0].message
            if getattr(msg, "tool_calls", None):
                calls = [
                    {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
                    for tc in msg.tool_calls
                ]
                return {
                    "tool_calls": calls,
                    "assistant_message": {
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": [
                            {"id": tc.id, "type": "function",
                             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                            for tc in msg.tool_calls
                        ],
                    },
                    "source": provider["name"], "degraded": False,
                }, None
            text = (msg.content or "").strip()
            if not text:
                # 有些服务商/模型偶尔会返回一个"成功"的响应，但content是空字符串/None
                # （比如免费模型池里某个模型这次抽风了）。之前这里直接把空文本当成
                # 正常结果返回，会导致：1) 不会尝试下一个服务商/降级到本地模型，
                # 2) 网页版收到 text:null 渲染出一个空的对话框，3) 这条空回复
                # 因为"非降级"还会被误当成训练样本记下来。改成当失败处理，
                # 让上层继续尝试下一个provider / 最终降级到本地模型。
                return None, f"{provider['name']}: 返回了空内容（模型这次没有生成任何文字），已跳过"
            return {"text": msg.content, "source": provider["name"], "degraded": False}, None
        except (APIConnectionError, APITimeoutError) as e:
            return None, f"{provider['name']}: 网络无法连接/超时 ({e})"
        except Exception as e:
            # 常见: 401(key错误) / 404(model名不存在) / 429(限流/欠费) / 不支持tools参数
            if tools:
                # 有些OpenAI兼容服务商不支持function calling，报错时自动降级成不带tools重试一次
                logger.info(f"{provider['name']} 带tools调用失败({e})，尝试不带tools重试")
                return self._call_one_provider(provider, messages, max_tokens, tools=None)
            return None, f"{provider['name']}: {type(e).__name__}: {e}"

    def _try_online_providers(self, messages, complex, max_tokens, tools=None):
        providers = self.cfg["online_providers"]
        ordered = [p for p in providers if p.get("enabled") and p["tier"] == "cheap"]
        if complex:
            ordered += [p for p in providers if p.get("enabled") and p["tier"] == "premium"]

        errors = []
        for provider in ordered:
            result, err = self._call_one_provider(provider, messages, max_tokens, tools)
            if result is not None:
                return result, errors
            errors.append(err)
            logger.info(err)
        return None, errors

    def _call_provider_by_name(self, name: str, messages: list, max_tokens: int, tools: list = None):
        for provider in self.cfg["online_providers"]:
            if provider["name"] == name:
                return self._call_one_provider(provider, messages, max_tokens, tools)
        return None, f"未找到名为 {name} 的服务商配置"

    # ---------------- 本地离线模型 ----------------
    def _load_local_model(self):
        if self._local_llm is not None:
            return self._local_llm

        try:
            from llama_cpp import Llama  # 延迟导入，没装这个库也不影响在线功能
        except ImportError:
            raise LocalModelUnavailable(
                "未安装 llama-cpp-python。运行 pip install llama-cpp-python 后再试"
                "（或用便携环境自带的安装脚本）"
            )

        local_cfg = self.cfg["local_fallback"]
        model_path = os.path.join(self.base_dir, local_cfg["model_path"])
        if not os.path.exists(model_path):
            raise LocalModelUnavailable(
                f"本地模型文件不存在: {model_path}\n"
                f"请先下载 GGUF 模型放到这个路径（见 README 部署说明）"
            )

        logger.info(f"正在加载本地离线模型: {model_path} （首次加载可能需要几十秒）")
        self._local_llm = Llama(
            model_path=model_path,
            n_ctx=local_cfg["n_ctx"],
            n_threads=local_cfg["n_threads"] or None,
            n_gpu_layers=local_cfg["n_gpu_layers"],
            verbose=False,
        )
        return self._local_llm

    def _chat_local(self, messages, max_tokens, degraded=True, tools=None):
        if not self.cfg["local_fallback"]["enabled"]:
            return {
                "text": "[小K提示] 本地离线模型未启用（config.yaml 里 local_fallback.enabled=false），"
                        "且没有可用的在线服务商。",
                "source": "none",
                "degraded": True,
            }
        try:
            llm = self._load_local_model()
        except LocalModelUnavailable as e:
            return {
                "text": f"[小K离线提示] 当前在线服务不可用，本地模型也没配置好：{e}",
                "source": "none",
                "degraded": True,
            }

        local_cfg = self.cfg["local_fallback"]
        kwargs = dict(
            messages=messages,
            max_tokens=max_tokens or local_cfg["max_tokens"],
            temperature=0.7,
            repeat_penalty=1.15,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            result = llm.create_chat_completion(**kwargs)
        except TypeError:
            # 装的 llama-cpp-python 版本较老，不支持 tools 参数，去掉再试一次
            logger.info("本地模型不支持 function calling 参数，降级为普通对话")
            kwargs.pop("tools", None)
            kwargs.pop("tool_choice", None)
            result = llm.create_chat_completion(**kwargs)

        msg = result["choices"][0]["message"]
        if msg.get("tool_calls"):
            calls = [
                {"id": tc["id"], "name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}
                for tc in msg["tool_calls"]
            ]
            return {
                "tool_calls": calls,
                "assistant_message": {"role": "assistant", "content": msg.get("content") or "",
                                       "tool_calls": msg["tool_calls"]},
                "source": "local_gguf", "degraded": degraded,
            }
        text = (msg.get("content") or "").strip()
        if not text:
            # 本地模型是最后一道保险，没有再下一个provider可以退了。
            # 给一句明确的兜底文案，而不是让空字符串一路传到网页端渲染成空气泡
            # （见 _call_one_provider 里同类问题的说明）。
            return {
                "text": "[小K提示] 本地模型这次没有生成任何内容，可以换个说法再问一次试试。",
                "source": "local_gguf", "degraded": degraded,
            }
        return {"text": msg["content"], "source": "local_gguf", "degraded": degraded}

    # ---------------- 给 UI 用：列出所有可选模型 ----------------
    def list_models(self) -> list:
        """
        返回可供 UI 下拉选择的模型列表：
        [{"id": "auto", "label": "...", "type": "auto", "ready": True}, ...]
        ready=False 表示选了它也大概率会失败（没key/占位符key/模型文件不存在），
        UI 应该置灰或者加提示，而不是直接隐藏（隐藏了用户永远不知道要去配它）。
        """
        models = [{"id": "auto", "label": "自动（推荐：先试便宜的在线模型，失败自动降级）",
                   "type": "auto", "ready": True, "detail": ""}]

        for p in self.cfg["online_providers"]:
            key = os.environ.get(p["api_key_env"])
            if not p.get("enabled"):
                ready, detail = False, "未在 config.yaml 中启用"
            elif not key:
                ready, detail = False, f"未配置 {p['api_key_env']}"
            elif _looks_like_placeholder(key):
                ready, detail = False, "还是占位符 key，需要换成真实key"
            else:
                ready, detail = True, f"{p['tier']} 层级"
            models.append({
                "id": p["name"],
                "label": f"{p['name']} · {p['model']}",
                "type": "online",
                "ready": ready,
                "detail": detail,
            })

        local_cfg = self.cfg["local_fallback"]
        model_path = os.path.join(self.base_dir, local_cfg["model_path"])
        local_ready = local_cfg["enabled"] and os.path.exists(model_path)
        if not local_cfg["enabled"]:
            local_detail = "未在 config.yaml 中启用"
        elif not os.path.exists(model_path):
            local_detail = "模型文件未下载，见 README"
        else:
            local_detail = "就绪"
        models.append({
            "id": "local", "label": "本地离线模型 (GGUF)", "type": "local",
            "ready": local_ready, "detail": local_detail,
        })
        return models

    def status(self) -> str:
        """给用户看的状态摘要，比如 /status 命令时调用"""
        online = self.network.is_online()
        lines = [f"通用联网探测: {'在线' if online else '离线'}（此项仅供参考，"
                 f"不再决定是否尝试在线模型——避免代理环境下误判）"]
        for p in self.cfg["online_providers"]:
            key = os.environ.get(p["api_key_env"])
            if not p.get("enabled"):
                status_str = "未启用"
            elif not key:
                status_str = "未配置key"
            elif _looks_like_placeholder(key):
                status_str = "占位符key（未替换）"
            else:
                status_str = "已配置"
            lines.append(f"  - {p['name']} ({p['tier']}, {p['model']}): {status_str}")
        local_cfg = self.cfg["local_fallback"]
        model_path = os.path.join(self.base_dir, local_cfg["model_path"])
        lines.append(
            f"本地离线模型: {'已启用' if local_cfg['enabled'] else '未启用'}, "
            f"{'文件存在' if os.path.exists(model_path) else '文件不存在，需下载'}"
        )
        return "\n".join(lines)
