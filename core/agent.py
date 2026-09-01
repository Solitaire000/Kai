"""
小K 主控 agent
==============
职责：
1. 接收用户输入
2. 从记忆系统里取画像 + 检索相关历史记忆 + 最近的硬件观测（如果有硬件接入）
3. 全程用Kai自己稳定的核心人格起手（不再整体切换人设）；如果任务和某个
   子agent更相关，会在system prompt里生成一句软提示，但要不要真的调用
   consult_subagent工具去咨询子agent，决策权在模型自己
4. 判断任务是否"复杂"（决定是否值得用premium模型）
5. 调用 model_router 拿到回复；如果模型想调用某个工具——技能(skill)、
   咨询子agent(consult_subagent)、或者操作硬件设备(hardware)——统一通过
   _tool_registry() 分发（见下），按权限决定是直接执行还是先向用户要确认，
   拿到工具结果后再让模型给出最终回复
6. 把这轮对话写回记忆系统；子agent被咨询产生的问答也会打上agent标签，
   流入和Kai共享的同一条训练管线（core/subagent_manager.py），保证子agent
   跟着Kai主人格一起被后续的LoRA训练迭代，而不是"用一次就丢"

硬件相关的完整架构说明见 docs/HARDWARE_ARCHITECTURE.md；Tool/Skill/子agent/
硬件这几个概念怎么区分见 docs/TOOLS_VS_SKILLS.md。
"""
import sys
import os
import json
import time
import uuid

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.specialized_agents import KAI_CORE_PERSONA
from core.skills_manager import SkillsManager
from core.subagent_manager import SubAgentManager
from core.hardware_manager import HardwareManager
from core.training_logger import TrainingLogger


class KaiAgent:
    def __init__(self, router, memory, config: dict, base_dir: str):
        self.router = router
        self.memory = memory
        self.cfg = config["agent"]
        # 训练数据采集：只在总开关打开时启用，不影响任何现有行为
        self.training_cfg = config.get("training") or {}
        self.training_logger = (
            TrainingLogger(config, base_dir) if self.training_cfg.get("enabled", True) else None
        )
        # 哪些 provider 算"教师"（值得蒸馏），local_gguf/none 永远排除
        self._non_teacher_sources = {"local_gguf", "none", None}
        # 子agent：只能被 consult_subagent 工具咨询，不再整体接管一轮对话（见 core/subagent_manager.py）
        self.subagents = SubAgentManager(
            self.router, self.memory, self.training_logger, self._non_teacher_sources
        )
        # 硬件设备：非阻塞启动（见 core/hardware_manager.py），on_event 回调把
        # "观测到的事实"写进记忆，不在这里做任何"该不该提醒"的判断
        self.hardware = HardwareManager(config, base_dir, on_event=self._on_hardware_event)
        # skills/ 目录下的技能名不能和 subagent/硬件工具名撞车，构造时把两者的
        # 工具名并集当保留名单传进去，撞名的技能会被跳过并报警告，而不是
        # 静默生效后被内置工具永久屏蔽（见 docs/TOOLS_VS_SKILLS.md）
        reserved = self.subagents.tool_names() | self.hardware.tool_names()
        self.skills = SkillsManager(config, base_dir, reserved_names=reserved)
        self.max_tool_iterations = (config.get("skills") or {}).get("max_tool_iterations", 4)
        self.turn_count = 0
        # 记忆巩固：每隔 N 轮，把最近的原始对话提炼成结构化画像 + 滚动长期摘要，
        # 写回 memory，让"重启后没记忆"的根因（只有最近6条原始对话+语义检索，
        # 二者都可能命中率不高）得到修复：长期摘要不依赖检索命中，每轮都会被注入。
        self.profile_update_every_n_turns = (config.get("memory") or {}).get(
            "profile_update_every_n_turns", 6
        )
        # 网页版这种"一来一回是两个独立HTTP请求"的场景，需要在两次请求之间
        # 暂存"模型想执行一个危险操作，等用户点确认"的状态。CLI是单进程同步循环，
        # 用不上这个（当场问当场答），但接口保持一致，两边都能复用同一套逻辑。
        self._pending = {}

    def _is_complex(self, user_input: str) -> bool:
        """
        简单启发式：输入较长、或包含"帮我分析/设计/推导/审阅"这类词，
        判断为复杂任务，值得切到premium模型。可以后续换成更聪明的判断逻辑。
        """
        complex_markers = ["分析", "设计", "推导", "审阅", "深入", "论文", "架构", "对比"]
        return len(user_input) > self.cfg["simple_task_max_len"] or any(
            m in user_input for m in complex_markers
        )

    # ---------------- 统一工具注册表 ----------------
    def _tool_registry(self) -> dict:
        """
        {tool_name: manager} 的统一注册表。manager 需要实现同一套接口——
        tool_names() / is_dangerous(name) / auto_confirm_enabled() /
        preview(name, params) / execute(name, params)——SkillsManager /
        SubAgentManager / HardwareManager 三者都实现了这套接口。
        _run_tool_loop() 用这份注册表统一分发调用，不需要为每种工具来源各写
        一个 if 分支：这是接入硬件层时刻意补上的通用化，避免以后每加一类新
        工具就要在 _run_tool_loop 里再加一个分支，具体原则见
        docs/TOOLS_VS_SKILLS.md 第五节。

        每次调用都重新构建：开销很小（只是遍历几个小dict/set），换来的好处是
        硬件设备中途插拔（比如对话过程中才把USB插上）也能在下一轮工具调用里
        立刻生效，不需要重启小K。
        """
        registry = {}
        for name in self.skills.tool_names():
            registry[name] = self.skills
        for name in self.subagents.tool_names():
            registry[name] = self.subagents
        for name in self.hardware.tool_names():
            registry[name] = self.hardware
        return registry

    def _on_hardware_event(self, text: str):
        """
        硬件驱动的后台线程观测到"值得记一笔"的事实时调用（比如有人进入/离开
        传感器检测范围）。这里只做一件事：把这句话当成一条"事件记忆"存下来，
        role 用 "event" 而不是 "user"/"assistant"，这样 _build_messages() 在
        回放最近对话轮次时会自动跳过它（不会被误当成Kai自己说过的话），但
        它仍然会被单独取出来、作为"最近的硬件观测"注入 system prompt（见
        _build_messages），供模型自己判断要不要提、怎么提。

        刻意不在这里做任何阈值判断/主动推送逻辑——这正是需求里"体现agent的
        智能性而不是简单条件判断"的核心落地方式，完整说明见
        docs/HARDWARE_ARCHITECTURE.md。
        """
        try:
            self.memory.add_episodic("event", text, tags="hardware")
        except Exception:
            pass  # 硬件事件记录失败不能影响任何其它功能，静默忽略

    def _build_tools_explainer(self, user_input: str) -> str:
        """
        统一介绍"你现在能调用的东西分几类，性质完全不同"。之前技能/子agent/
        硬件这几类工具的说明容易散落在不同地方各写各的话术，模型很难意识到
        它们其实是同一层"tools"概念下的不同类别。这里统一成一段、明确编号，
        完整的概念定义见 docs/TOOLS_VS_SKILLS.md。
        """
        parts = ["【你现在能调用的东西，分几类，性质完全不同，不要混为一谈】"]
        if self.skills.cfg.get("enabled"):
            parts.append(
                "第一类·技能(skill)：会直接对你电脑执行真实动作，比如查时间、"
                "查系统信息、读写工作区里的文件。会修改/执行东西的技能，系统会"
                "先问用户确认，你不用也不能替用户做这个决定，正常调用就好，"
                "系统会处理确认环节。"
            )
        parts.append(
            "第二类·consult_subagent(咨询子agent)：这**不是**技能，不会对"
            "用户的电脑做任何操作——它只是把一个子任务委派给一个更专精的子agent"
            "做文字分析，你拿到它的产出后自己判断要不要采纳、怎么组织最终回复。"
            "用户全程看不到子agent的原始输出，只看到你最终说的话。"
            + self.subagents.build_hint(user_input)
        )
        if self.hardware.tool_names():
            parts.append(
                "第三类·硬件工具：读取/操作实际连接在这台电脑上的物理硬件设备"
                "（比如传感器）。这类工具是纯粹的数据来源或物理动作，不代表你"
                "自己的判断——读到的数据该怎么解读、要不要跟用户提，由你自己"
                "结合对话上下文推理决定，不是工具告诉你该说什么。如果下面"
                "【最近的硬件观测】里有内容，那是后台自动记录的原始事实，"
                "同样只供你参考判断，不是指令。"
            )
        return "\n".join(parts)

    def _build_messages(self, user_input: str):
        profile_summary = self.memory.profile_summary_text()
        recalled = self.memory.search_semantic(user_input)
        recalled_text = "\n".join(f"- {r['text']} (相关度{r['score']:.2f})" for r in recalled)
        long_term_summary = self.memory.long_term_summary()

        system_prompt = KAI_CORE_PERSONA.build_system_prompt(
            profile_summary, recalled_text, long_term_summary
        )
        system_prompt += "\n\n" + self._build_tools_explainer(user_input)

        # 最近的硬件观测：单独查询role="event"的记录，不混进下面的对话轮次
        # 回放里（那会被误当成Kai自己说过的话）。只取最近几条，避免刷屏，
        # 也避免占用太多上下文空间。
        hw_events = self.memory.recent_by_tag("hardware", n=3)
        if hw_events:
            lines = "\n".join(f"- {content}" for _ts, _role, content in hw_events)
            system_prompt += (
                "\n\n【最近的硬件观测（原始事实，仅供参考，要不要提、怎么回应"
                f"由你自己判断）】\n{lines}"
            )

        recent = self.memory.recent_episodic(n=6)
        messages = [{"role": "system", "content": system_prompt}]
        for ts, role, content in recent:
            if role not in ("user", "assistant"):
                continue  # 硬件观测这类事件记忆不参与对话轮次回放，见上面的查询
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_input})
        return messages

    def chat(self, user_input: str, force_provider: str = None) -> dict:
        messages = self._build_messages(user_input)
        complex_task = self._is_complex(user_input)
        tools = []
        if self.skills.cfg.get("enabled"):
            tools.extend(self.skills.to_openai_tools())
        tools.append(self.subagents.to_openai_tool())
        tools.extend(self.hardware.to_openai_tools())

        result = self._run_tool_loop(messages, complex_task, force_provider, tools)

        if result.get("needs_confirmation"):
            result["agent"] = "kai"
            return result

        consulted = result.pop("consulted_agents", [])
        tag = ",".join(["kai"] + consulted)
        self.memory.add_episodic("user", user_input, tags=tag)
        self.memory.add_episodic("assistant", result["text"], tags=tag)
        self.turn_count += 1
        result["agent"] = "kai"
        result["consulted_agents"] = consulted

        if self.turn_count % self.profile_update_every_n_turns == 0:
            self._consolidate_memory()

        # 蒸馏采集：只记录"教师"模型（在线且非降级）的问答对，见 training_logger.py 里的原则
        result["sample_id"] = None
        if (self.training_logger is not None
                and not result.get("degraded")
                and result.get("source") not in self._non_teacher_sources):
            system_prompt = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
            result["sample_id"] = self.training_logger.log_sample(
                agent="kai",
                source=result.get("source"),
                system_prompt=system_prompt,
                user_input=user_input,
                assistant_output=result["text"],
            )
        return result

    def _consolidate_memory(self):
        """
        记忆巩固：把自上次巩固以来的新对话，提炼成
        1) 画像事实（长期稳定的"关于用户"的key-value，比如身份/项目/偏好）
        2) 一段更新后的长期摘要（滚动覆盖，不是无限追加，控制在短短几百字）
        用一次性、成本很低的模型调用完成，失败了也绝不影响正常聊天（吞掉异常）。
        这一步是"重启后没记忆"问题的关键修复：画像和长期摘要都是无条件注入
        system prompt的，不依赖语义检索是否命中，比单纯堆"最近6条原始对话"
        或"语义检索"更稳，能保证跨很多次会话之后依然有连贯的、压缩过的记忆。
        """
        try:
            since_id = int(self.memory.get_meta("summary_watermark_id", "0") or "0")
            rows = self.memory.episodic_since_id(since_id)
            if not rows:
                return
            transcript = "\n".join(f"{role}: {content}" for _id, ts, role, content in rows)
            old_summary = self.memory.long_term_summary()
            old_profile = self.memory.profile_summary_text()

            prompt = (
                "你是记忆整理模块。下面是【已有长期摘要】【已有画像】和【一段新的原始对话】，"
                "请提炼更新，只输出一个JSON对象，不要有其它任何文字，格式：\n"
                '{"facts": {"key": "value", ...}, "summary": "更新后的长期摘要（150字以内，'
                '融合旧摘要里仍然有效的内容和新对话里值得长期记住的信息，过时/无意义的细节可以丢弃）"}\n'
                "facts只放长期稳定、值得跨会话记住的事实（比如身份、正在做的项目、习惯偏好），"
                "临时性的操作细节（比如某次打开了什么文件）不要放进facts。\n"
                "如果新对话里没有任何值得长期记住的新信息，facts给空对象{}，summary保持和旧摘要基本一致即可。\n\n"
                f"【已有长期摘要】\n{old_summary or '（无）'}\n\n"
                f"【已有画像】\n{old_profile}\n\n"
                f"【新的原始对话】\n{transcript}\n"
            )
            result = self.router.chat(
                [{"role": "system", "content": "你只输出JSON，不输出任何其它文字。"},
                 {"role": "user", "content": prompt}],
                complex=False,
            )
            text = (result.get("text") or "").strip()
            # 有些模型会习惯性套 ```json ... ``` 代码块，剥掉再解析
            if text.startswith("```"):
                text = text.strip("`")
                text = text[4:] if text.lower().startswith("json") else text
            data = json.loads(text)

            for k, v in (data.get("facts") or {}).items():
                if k and v:
                    self.memory.set_profile(str(k), str(v))
            new_summary = data.get("summary")
            if new_summary:
                self.memory.set_meta("long_term_summary", new_summary)

            last_id = rows[-1][0]
            self.memory.set_meta("summary_watermark_id", str(last_id))
        except Exception:
            # 记忆巩固是锦上添花，绝不能因为JSON解析失败/模型抽风而打断正常对话
            pass

    def rate_last_sample(self, sample_id: int, rating: int):
        """
        用户对某条回复点赞/点踩时调用（web_app.py /api/feedback，或 CLI /good /bad）。
        rating: 1=赞, -1=踩。踩的样本默认不会进入下一轮 LoRA 训练。
        """
        if self.training_logger is not None and sample_id:
            self.training_logger.set_rating(sample_id, rating)

    # ---------------- 工具调用编排 ----------------
    def _run_tool_loop(self, messages: list, complex_task: bool, force_provider: str, tools: list) -> dict:
        errors_acc = []
        consulted_agents = []
        registry = self._tool_registry()
        for _ in range(self.max_tool_iterations):
            result = self.router.chat(
                messages, complex=complex_task, force_provider=force_provider, tools=tools
            )
            if result.get("errors"):
                errors_acc.extend(result["errors"])

            if "tool_calls" not in result:
                if errors_acc:
                    result["errors"] = errors_acc
                result["consulted_agents"] = consulted_agents
                if not (result.get("text") or "").strip():
                    # 双保险：即使 model_router.py 里的 provider 分支以后又漏掉了
                    # 空内容检查，这里也兜底一次，绝不让空文本传到前端渲染出
                    # 一个空气泡。真正的根因修复在 core/model_router.py。
                    result["text"] = "[小K提示] 这次没有获取到有效回复，可以换个说法再问一次。"
                    result["degraded"] = True
                return result

            messages.append(result["assistant_message"])

            for call in result["tool_calls"]:
                try:
                    args = json.loads(call["arguments"]) if call["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}

                manager = registry.get(call["name"])
                if manager is None:
                    exec_result = {"ok": False, "error": f"未知工具: {call['name']}"}
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(exec_result, ensure_ascii=False),
                    })
                    continue

                if manager.is_dangerous(call["name"]) and not manager.auto_confirm_enabled():
                    token = uuid.uuid4().hex
                    self._pending[token] = {
                        "messages": messages,
                        "tool_call": call,
                        "args": args,
                        "complex_task": complex_task,
                        "force_provider": force_provider,
                        "tools": tools,
                        "created_at": time.time(),
                    }
                    return {
                        "needs_confirmation": True,
                        "token": token,
                        "tool_name": call["name"],
                        "preview": manager.preview(call["name"], args),
                        "text": f"小K想执行一个操作，需要你确认：{manager.preview(call['name'], args)}",
                        "source": result.get("source", "none"),
                        "degraded": result.get("degraded", False),
                        "consulted_agents": consulted_agents,
                    }

                exec_result = manager.execute(call["name"], args)
                # consult_subagent 执行成功时，把被咨询的子agent名字记下来，
                # 最终写进 episodic 记忆的 tags 里（见 chat() 末尾），方便回溯
                # "这轮对话到底问过哪些子agent"
                if manager is self.subagents and exec_result.get("ok"):
                    consulted_agents.append(exec_result["agent"])
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(exec_result, ensure_ascii=False),
                })

        # 超过最大工具调用轮数还没拿到最终文字回复，兜底返回一个提示，避免死循环
        return {
            "text": "[小K提示] 这轮任务调用工具的次数太多了，先停下来。可以换个更具体的说法重新试试。",
            "source": "none", "degraded": True, "errors": errors_acc,
            "consulted_agents": consulted_agents,
        }

    def confirm_pending(self, token: str, approve: bool) -> dict:
        """网页版用：用户对一个'需要确认'的操作点了同意/拒绝之后，继续完成这轮对话"""
        pending = self._pending.pop(token, None)
        if not pending:
            return {"text": "[小K提示] 这个待确认的操作已经过期或不存在了，请重新发起对话。",
                    "source": "none", "degraded": True, "agent": "general"}

        messages = pending["messages"]
        call = pending["tool_call"]

        if approve:
            manager = self._tool_registry().get(call["name"])
            exec_result = (
                manager.execute(call["name"], pending["args"]) if manager is not None
                else {"ok": False, "error": f"未知工具: {call['name']}"}
            )
        else:
            exec_result = {"ok": False, "error": "用户拒绝了这个操作"}

        messages.append({
            "role": "tool",
            "tool_call_id": call["id"],
            "content": json.dumps(exec_result, ensure_ascii=False),
        })

        result = self._run_tool_loop(
            messages, pending["complex_task"], pending["force_provider"], pending["tools"]
        )
        result["agent"] = "kai"
        if not result.get("needs_confirmation"):
            self.memory.add_episodic("assistant", result.get("text", ""), tags="kai")
        return result

    def remember(self, key: str, value: str):
        """显式让小K记住一件事，比如 /remember 专业=RF探针检测"""
        self.memory.set_profile(key, value)

    def list_tools(self) -> list:
        """
        当前Kai实际能调用的一切工具（会被塞进 chat() 里传给模型的那份 tools 列表）
        的统一展示视图，供 CLI /skills、网页版 /api/skills 使用。

        技能(skill)、子agent咨询(consult_subagent)、硬件设备工具三者是完全不同
        的实现路径，各自的产出通过 kind 字段区分（"skill"/"subagent"/"hardware"），
        概念说明见 docs/TOOLS_VS_SKILLS.md，硬件架构见 docs/HARDWARE_ARCHITECTURE.md。
        """
        tools = [dict(s, kind="skill") for s in self.skills.list_skills()]
        tools += [dict(s, kind="subagent") for s in self.subagents.list_for_ui()]
        tools += [dict(s, kind="hardware") for s in self.hardware.list_for_ui()]
        return tools

    def training_stats(self) -> dict:
        if self.training_logger is None:
            return {"enabled": False}
        stats = self.training_logger.stats()
        stats["enabled"] = True
        return stats

    def close(self):
        if self.training_logger is not None:
            self.training_logger.close()
        self.hardware.close()

