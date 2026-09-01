class SubAgent:
    """
    所有子agent的基类。

    子agent不是独立进程、不是独立模型，本质上是"一段专属人设 + 一份专属身份锚定语料 +
    一份专属探测题库"，运行时通过 core/subagent_manager.py 以 Kai 主agent的名义被咨询
    （consult_subagent 工具），产出的问答会打上 agent=<name> 标签流回同一条训练管线。

    这保证了"子agent跟着Kai主人格一起迭代进化"：子agent从来没有自己独立的一套权重，
    它的知识/语气最终都会被训练进和Kai共享的同一个LoRA adapter里——不是"用一次就丢"，
    是每次 train_lora.py 全量重训时，子agent的身份锚定+日常问答+主动探测语料，
    都会和Kai核心人格的语料一起被喂给同一次训练，随着版本号一起迭代。
    """
    name = "base"
    description = "通用子agent"
    # 命中这些关键词时，在Kai的system prompt里生成"建议咨询XX子agent"的提示
    # （只是提示，不再强制整体换人设——决策权交给模型自己判断是否调用consult_subagent）
    keywords = []

    system_prompt = "你是小K，一个专属于用户的私人助理agent。"

    # ---- 训练/继承相关字段（新增） ----
    # 是否需要更强的推理模型。复用 model_router 已有的 complex 路由机制，
    # 不给子agent单独绑定固定模型名——保持"子agent之间只在人设/知识范围上分化，
    # 模型选择集中在router一处"的原则，见 train/README_INHERITANCE.md 的讨论。
    model_complex = False
    # 这个子agent所需要的能力标签，用于以后 model_router 接入多模态/专用provider时
    # 做能力过滤（目前只有 "text"，预留字段）
    required_capability = "text"
    # 这个子agent专属的身份锚定语料路径（相对 base_dir）。每次训练都会强制混入，
    # 防止这个子agent的语气/边界被主人格或其它子agent的海量样本"稀释"掉。
    # 不填则用 memory/identity/subagents/<name>.jsonl 的默认约定路径。
    identity_anchors_path = None
    # data/probes/probe_set.yaml 里，哪些 category 应该额外用这个子agent的人设
    # 再探测一遍（见 migrate/self_distillation.py 的 --include-subagents 模式）。
    probe_categories = []

    def get_identity_anchors_path(self) -> str:
        return self.identity_anchors_path or f"memory/identity/subagents/{self.name}.jsonl"

    def build_system_prompt(self, profile_summary: str, recalled_memories: str,
                             long_term_summary: str = "") -> str:
        return (
            f"{self.system_prompt}\n\n"
            f"【重要：关于你的记忆能力】你拥有真实的跨会话持久记忆系统（本地数据库+向量检索），"
            f"每次对话都会自动存档，下次启动会自动加载。这不是比喻，是真实存在的机制。"
            f"下面几个板块如果显示'（暂无/无）'，只代表'目前还没有相关记录'，"
            f"绝不代表你没有记忆功能——任何情况下都不要说'我没有记忆功能'"
            f"或'我不会保存之前的对话'这类话，这是错误的，会让用户误解系统能力。"
            f"如果用户问起，如实说明：你有长期画像记忆、历史摘要和语义检索三层记忆，"
            f"只是当前这个问题恰好没有命中已存的内容，可以请用户告诉你，你会记住。\n\n"
            f"【关于用户，你已经知道的事（长期画像）】\n{profile_summary}\n\n"
            f"【长期摘要（跨多次会话持续积累）】\n{long_term_summary or '（暂无摘要，还在积累中）'}\n\n"
            f"【当前对话可能相关的历史记忆（语义检索命中）】\n{recalled_memories or '（本轮没有语义相关的历史记忆命中，不代表没有记忆）'}\n\n"
            f"回复要求：简洁、直接、口语化，不要客套话开场。"
        )
