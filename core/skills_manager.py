"""
Skills 系统（让小K能在一定权限下操作电脑）
==========================================
设计目标：
1. 可扩展接口——加一个新技能不用改这个文件，也不用改 agent.py/model_router.py，
   只要在 skills/ 下新建一个文件夹，放 skill.yaml（元数据+参数schema）+ handler.py
   （一个 run(params, ctx) 函数）即可，启动时自动被发现、自动出现在模型的可用工具列表里。
2. 权限分级——每个技能在 skill.yaml 里标 dangerous: true/false。
   非危险技能（只读，比如读文件、查时间、查系统信息）模型可以直接调用，不用打断用户。
   危险技能（会修改/执行东西，比如写文件、跑命令、打开程序）默认需要用户在CLI/网页上
   显式点确认才会真正执行——模型只能"提议"，不能replace用户做决定。
3. 沙盒——文件类技能默认只能碰 workspace_root（data/workspace/）目录内的文件，
   不能读写这个目录之外的任意路径，除非 config.yaml 里显式打开 allow_full_disk_access。
4. run_command 这个最危险的技能默认整个关闭，需要用户自己去 config.yaml 手动打开，
   打开后依然会做正则白名单校验+超时限制+需要确认。

这套设计参照了本项目其他地方已经在用的"约定优于配置"模式（比如 agents/ 下子agent
的写法），保持风格一致。
"""
import os
import sys
import json
import time
import shlex
import platform
import subprocess
import importlib.util
import logging

import yaml

logger = logging.getLogger("kai.skills")

# 默认保留名（向后兼容：如果调用方没有显式传 reserved_names，就用这份默认值）。
# 正式使用中，core/agent.py 会把 SubAgentManager.tool_names() 和
# HardwareManager.tool_names() 的并集一起传进来，覆盖掉这个默认值——
# 保留名单需要能反映"当前实际启用了哪些内置工具"，不能是一个写死不变的常量，
# 否则以后新增硬件工具时这里会漏掉。完整设计说明见 docs/TOOLS_VS_SKILLS.md。
DEFAULT_RESERVED_TOOL_NAMES = {"consult_subagent"}


class SkillPermissionError(Exception):
    pass


class SkillContext:
    """传给每个技能 handler.run() 的上下文对象，负责路径沙盒等公共逻辑"""

    def __init__(self, base_dir: str, skills_cfg: dict):
        self.base_dir = base_dir
        self.cfg = skills_cfg
        self.workspace_root = os.path.abspath(
            os.path.join(base_dir, skills_cfg.get("workspace_root", "data/workspace"))
        )
        os.makedirs(self.workspace_root, exist_ok=True)

    def resolve_path(self, user_path: str) -> str:
        """
        把技能收到的相对路径解析成真实绝对路径，并做沙盒检查。
        默认只允许落在 workspace_root 内；allow_full_disk_access=true 时放开限制
        （不建议，只有你完全信任当前用的模型/场景时才开）。
        """
        if os.path.isabs(user_path):
            candidate = os.path.abspath(user_path)
        else:
            candidate = os.path.abspath(os.path.join(self.workspace_root, user_path))

        if self.cfg.get("allow_full_disk_access"):
            return candidate

        if not candidate.startswith(self.workspace_root + os.sep) and candidate != self.workspace_root:
            raise SkillPermissionError(
                f"路径 {user_path} 超出了允许的工作区范围 ({self.workspace_root})。"
                f"如果确实需要访问工作区外的路径，去 config.yaml 把 "
                f"skills.allow_full_disk_access 改成 true（有风险，谨慎开启）。"
            )
        return candidate


class SkillsManager:
    def __init__(self, config: dict, base_dir: str, reserved_names: set = None):
        self.base_dir = base_dir
        self.cfg = config.get("skills", {}) or {}
        self.skills_dir = os.path.join(base_dir, "skills")
        self.ctx = SkillContext(base_dir, self.cfg)
        self._skills = {}  # name -> metadata dict (含 handler 模块引用)
        # 保留名单：不能被 skills/ 目录下的技能占用（见上面 DEFAULT_RESERVED_TOOL_NAMES
        # 的说明）。core/agent.py 构造时会传入 subagent + hardware 工具名的并集；
        # 单独实例化/测试时不传也有默认值兜底。
        self.reserved_names = set(reserved_names) if reserved_names is not None \
            else set(DEFAULT_RESERVED_TOOL_NAMES)
        if self.cfg.get("enabled", False):
            self._discover()

    # ---------------- 发现 & 加载 ----------------
    def _discover(self):
        if not os.path.isdir(self.skills_dir):
            return
        enabled_list = self.cfg.get("enabled_skills")  # None = 全部启用

        for entry in sorted(os.listdir(self.skills_dir)):
            folder = os.path.join(self.skills_dir, entry)
            meta_path = os.path.join(folder, "skill.yaml")
            handler_path = os.path.join(folder, "handler.py")
            if not (os.path.isfile(meta_path) and os.path.isfile(handler_path)):
                continue

            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = yaml.safe_load(f) or {}
                name = meta.get("name", entry)

                if name in self.reserved_names:
                    logger.warning(
                        f"技能 {entry} 的 name 是「{name}」，和内置工具名冲突"
                        f"（保留名单: {sorted(self.reserved_names)}），已跳过加载。"
                        f"请在 skill.yaml 里把 name 改成别的，否则这个技能永远"
                        f"调用不到——见 docs/TOOLS_VS_SKILLS.md。"
                    )
                    continue

                if enabled_list is not None and name not in enabled_list:
                    continue
                # run_command 这类技能自身还有一层独立开关（skills.run_command.enabled）
                sub_cfg = self.cfg.get(name, {})
                if isinstance(sub_cfg, dict) and sub_cfg.get("enabled") is False:
                    continue

                spec = importlib.util.spec_from_file_location(f"kai_skill_{name}", handler_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                if not hasattr(module, "run"):
                    logger.warning(f"技能 {name} 的 handler.py 里没有 run() 函数，跳过")
                    continue

                meta["_module"] = module
                meta["_sub_cfg"] = sub_cfg
                self._skills[name] = meta
            except Exception as e:
                logger.warning(f"加载技能 {entry} 失败: {e}")

    # ---------------- 给 UI / 模型用 ----------------
    def list_skills(self) -> list:
        return [
            {
                "name": s["name"],
                "description": s.get("description", ""),
                "dangerous": bool(s.get("dangerous", False)),
                "category": s.get("category", "general"),
            }
            for s in self._skills.values()
        ]

    def to_openai_tools(self) -> list:
        """转换成 OpenAI function-calling 的 tools schema"""
        tools = []
        for s in self._skills.values():
            tools.append({
                "type": "function",
                "function": {
                    "name": s["name"],
                    "description": s.get("description", ""),
                    "parameters": s.get("parameters", {"type": "object", "properties": {}}),
                },
            })
        return tools

    # ---------------- 通用工具注册表接口（core/agent.py 用，和 subagent_manager.py /
    # hardware_manager.py 保持同样的方法签名，这样 _run_tool_loop 不需要为每种
    # 工具来源各写一个 if 分支，见 docs/TOOLS_VS_SKILLS.md 第五节） ----------------
    def tool_names(self) -> set:
        return set(self._skills.keys())

    def auto_confirm_enabled(self) -> bool:
        return bool(self.cfg.get("auto_confirm"))

    def is_dangerous(self, name: str) -> bool:
        s = self._skills.get(name)
        return bool(s and s.get("dangerous", False))

    def preview(self, name: str, params: dict) -> str:
        """给用户看的"即将执行什么"的一句话描述，用于确认弹窗"""
        s = self._skills.get(name)
        if not s:
            return f"未知技能: {name}"
        template = s.get("preview_template")
        if template:
            try:
                return template.format(**params)
            except Exception:
                pass
        return f"{s.get('description', name)}  参数: {json.dumps(params, ensure_ascii=False)}"

    # ---------------- 执行 ----------------
    def execute(self, name: str, params: dict) -> dict:
        """真正执行一个技能，返回 {"ok": True, "result": ...} 或 {"ok": False, "error": ...}"""
        s = self._skills.get(name)
        if not s:
            return {"ok": False, "error": f"技能 {name} 不存在或未启用"}
        try:
            result = s["_module"].run(params or {}, self.ctx)
            return {"ok": True, "result": result}
        except SkillPermissionError as e:
            return {"ok": False, "error": f"权限拒绝: {e}"}
        except Exception as e:
            logger.exception(f"技能 {name} 执行出错")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
