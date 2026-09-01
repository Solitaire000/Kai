"""
core/subagent_manager.py
===========================
把 agents/specialized_agents.py 里定义的子agent，注册成 Kai 主循环能调用的
一个 tool：consult_subagent。设计目标有两条，缺一不可：

1. 【总览】用户全程只跟 Kai（agents.specialized_agents.KAI_CORE_PERSONA）对话。
   子agent从不直接面对用户——Kai 调用 consult_subagent 拿到子agent的产出后，
   自己判断怎么组织、要不要采纳、要不要结合多个子agent的意见，再回复用户。
   这是 core/agent.py 里 _run_tool_loop 现有的通用tool-calling循环的一种tool，
   不是另起一套编排逻辑。

2. 【共同进化】子agent不是"调用一次就丢"的临时工具——每次调用产生的问答，
   只要满足"来自在线教师模型、非降级"这两个条件（和主人格的蒸馏规则完全一致，
   见 training_logger.py），就会打上 agent=<子agent名> 标签写进
   training_samples.db。train/corpus_builder.py 组装训练语料时，
   子agent的身份锚定(memory/identity/subagents/*.jsonl)也会被强制混入。
   于是每次 train_lora.py 全量重训，Kai的核心人格和所有子agent的问答/身份锚定
   都被喂进*同一个* LoRA adapter——子agent不是独立训练出来的，它们的能力和
   Kai共享同一套权重、同一个版本号，随着Kai一起变强，也随着Kai一起换底座模型、
   一起被 self_distillation.py 探测、一起接受 regression_score.py 的回归检查。
   这就是"子agent跟着Kai主人格一起迭代进化"在工程上的落地方式。
"""
import json

from agents.specialized_agents import ALL_AGENTS, suggest_subagents


class SubAgentManager:
    def __init__(self, router, memory, training_logger, non_teacher_sources: set):
        self.router = router
        self.memory = memory
        self.training_logger = training_logger
        self._non_teacher_sources = non_teacher_sources
        self.agents = {a.name: a for a in ALL_AGENTS}

    # ---------------- 给 Kai 的 system prompt 用：软提示，不是硬路由 ----------------
    def build_hint(self, user_input: str) -> str:
        """
        关键词命中时生成一句"建议咨询XX"的提示，塞进Kai的system prompt。
        只是提示，决策权在模型自己：命中了不代表一定要调用，没命中也不代表不能调用
        （比如用户直接问"帮我问问研究agent怎么看"，模型也应该能调用）。

        注意：这段文字本身不再包含"这是不是一个技能/工具"的框架性说明——那部分
        统一由 core/agent.py::_build_tools_explainer() 负责，这里只负责"这次对话
        该不该建议咨询、建议咨询谁"这个具体判断，避免两处各写一套话术、互相矛盾
        （历史上这里曾经自己加过一段【子agent】框架说明，和 skills 那段各说各话，
        模型不容易看出二者其实是同一层"工具"概念下的两个类别，已经在
        core/agent.py 里统一整合，见 docs/TOOLS_VS_SKILLS.md）。
        """
        hits = suggest_subagents(user_input)
        catalog = "、".join(f"{a.name}({a.description})" for a in ALL_AGENTS)
        if hits:
            names = "、".join(a.name for a in hits)
            return (f"这句话涉及的内容和 {names} 子agent比较相关，可以考虑咨询它（不强制）。"
                    f"全部可选子agent：{catalog}")
        return f"全部可选子agent：{catalog}"

    # ---------------- 给 UI 用：和 SkillsManager.list_skills() 保持同样的字段结构，
    # 方便 core/agent.py 把两者合并成一份统一的"当前能调用的一切"列表（见
    # KaiAgent.list_tools()，以及 docs/TOOLS_VS_SKILLS.md 里的说明） ----------------
    def list_for_ui(self) -> list:
        return [{
            "name": "consult_subagent",
            "description": "把子任务委派给某个专精子agent处理，可选: "
                            + "、".join(f"{a.name}({a.description})" for a in ALL_AGENTS),
            "dangerous": False,  # 子agent本身不直接操作用户电脑/文件，不走确认流程
            "category": "subagent",
        }]

    # ---------------- 注册为 openai-style tool ----------------
    def to_openai_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "consult_subagent",
                "description": (
                    "把一个具体的子任务委派给一个专精子agent处理，拿到它的分析/回答后，"
                    "你自己判断怎么整理、要不要采纳，再用你自己的话回复用户——用户看不到"
                    "子agent的原始回复，只看到你最终说了什么。可选子agent: "
                    + ", ".join(f"{a.name}（{a.description}）" for a in ALL_AGENTS)
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "enum": list(self.agents.keys()),
                            "description": "要咨询哪个子agent",
                        },
                        "task": {
                            "type": "string",
                            "description": "交给子agent的具体任务描述，尽量具体、自包含",
                        },
                    },
                    "required": ["agent_name", "task"],
                },
            },
        }

    # ---------------- 通用工具注册表接口（和 SkillsManager / hardware_manager.py
    # 保持同样的方法签名，core/agent.py 用一份统一的 {tool_name: manager} 注册表
    # 分发调用，不需要为每种工具来源各写一个 if 分支，见 docs/TOOLS_VS_SKILLS.md） ---
    def tool_names(self) -> set:
        return {"consult_subagent"}

    def is_dangerous(self, name: str) -> bool:
        return False  # 子agent本身不直接操作用户电脑/文件，不走确认流程

    def auto_confirm_enabled(self) -> bool:
        return True  # 反正 is_dangerous 永远 False，这个值实际不会被用到

    def preview(self, name: str, params: dict) -> str:
        return f"咨询子agent「{params.get('agent_name', '')}」：{params.get('task', '')}"

    # ---------------- 真正执行 ----------------
    def execute(self, name: str, params: dict) -> dict:
        """
        统一接口签名 execute(name, params)，和 SkillsManager/HardwareManager 对齐。
        name 恒为 "consult_subagent"（tool_names() 只声明了这一个），实际要咨询
        哪个子agent、任务是什么，从 params 里的 agent_name/task 取。

        返回 {"ok": bool, "result": str, "agent": str} 或 {"ok": False, "error": str}。
        执行逻辑刻意和 KaiAgent.chat() 里对主人格的处理保持一致：
        - 用子agent自己的 build_system_prompt（同样注入画像/长期摘要/语义检索，
          子agent一样"记得住"，不是失忆的临时工）
        - model_complex 决定是否路由到更强模型（复用 router，不绑定固定模型名）
        - 只有"在线教师模型 + 非降级"的产出才会被记进训练语料
        """
        agent_name = params.get("agent_name", "")
        task = params.get("task", "")
        sub = self.agents.get(agent_name)
        if sub is None:
            return {"ok": False, "error": f"子agent {agent_name} 不存在"}

        profile_summary = self.memory.profile_summary_text()
        recalled = self.memory.search_semantic(task)
        recalled_text = "\n".join(f"- {r['text']} (相关度{r['score']:.2f})" for r in recalled)
        long_term_summary = self.memory.long_term_summary()

        system_prompt = sub.build_system_prompt(profile_summary, recalled_text, long_term_summary)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]
        resp = self.router.chat(messages, complex=sub.model_complex, max_tokens=900)
        text = (resp.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": f"{agent_name} 没有给出有效回答",
                    "errors": resp.get("errors")}

        # 和主人格完全一致的蒸馏规则：只收在线教师模型、非降级的产出
        sample_id = None
        if (self.training_logger is not None
                and not resp.get("degraded")
                and resp.get("source") not in self._non_teacher_sources):
            sample_id = self.training_logger.log_sample(
                agent=agent_name,
                source=resp.get("source"),
                system_prompt=system_prompt,
                user_input=task,
                assistant_output=text,
            )

        return {
            "ok": True,
            "agent": agent_name,
            "result": text,
            "source": resp.get("source"),
            "degraded": resp.get("degraded", False),
            "sample_id": sample_id,
        }
