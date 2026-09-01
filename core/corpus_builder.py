"""
core/corpus_builder.py
========================
把"能够被继承的一切"统一组装成一份训练语料，供 train/train_lora.py 使用。

不再局限于原来的"身份锚定 + 蒸馏问答对"两块，扩展成六个来源
（按下面的优先级顺序合并）：

1. identity_anchors   —— 手写身份/边界锚定语料（人格与红线）。
                          任何一次训练，不管是日常追加还是换 base model 重新出发，
                          都强制混入，不依赖"蒸馏数据里恰好聊到过"这种运气。

2. subagent_identity   —— memory/identity/subagents/<name>.jsonl，每个子agent
                          专属的身份/边界锚定语料，防止子agent的人设被主人格的
                          海量样本稀释掉。优先级仅次于主identity_anchors。

3. profile_samples    —— 由 core/memory.py 里的"画像记忆"+"长期摘要"实时生成的
                          自我认知问答对。这一层不落盘，每次组装语料时现算现用，
                          永远反映画像的最新状态。让"关于用户的了解"除了走检索注入
                          system prompt，也沉淀进权重里做二次保险——换 base model
                          时哪怕检索层的 prompt 格式和新模型习惯没完全对上，
                          这块信息依然不会丢。

4. refined_corpus     —— migrate/distill_training_corpus.py 定期把原始问答流水账
                          提炼成的结构化知识点/常见模式。数据量大了之后，这一层
                          的价值应该高于原始样本（去重、去过时、去重复表达）。

5. self_distillation  —— migrate/self_distillation.py 在换 base model /
                          换 provider 之前，对"旧大脑"（旧 adapter+旧 base，或者
                          当前实际在跑的某个 provider）做主动探测式问答采集产出的
                          语料。被动聊天记录天然有覆盖盲区（很多领域从没聊到过），
                          主动探测是"继承旧 base model 里没被聊到过、但确实具备的
                          能力/风格/推理方式"的关键手段，覆盖面远比被动日志更完整。

6. raw_samples        —— 原来就有的 training_samples.db 原始问答对流水账
                          （在线教师模型产生的、未被点踩的对话样本）。

六个来源按上面的优先级顺序合并，再按 (user_input, assistant_output) 去重
（保留先出现的一份）——身份锚定类语料权重最高，不会被同义但表达略有差异的
原始流水账"稀释掉"。这六个来源加上 core/memory.py 的运行时三层记忆，共同
构成了整个项目的"记忆资产"，完整分层说明见 docs/MEMORY_MODEL.md。
"""
import json
import os


def _load_jsonl(path: str) -> list:
    if not path or not os.path.exists(path):
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def load_identity_anchors(base_dir: str, rel_path: str) -> list:
    records = _load_jsonl(os.path.join(base_dir, rel_path))
    for r in records:
        r.setdefault("_origin", "identity_anchor")
    return records


def load_subagent_identity_anchors(base_dir: str, rel_dir: str = "memory/identity/subagents") -> list:
    """
    子agent的专属身份锚定语料（每个子agent一个 <name>.jsonl，见 agents/base_agent.py
    的 get_identity_anchors_path()）。和主人格的 identity_anchors 一样，每次训练
    强制混入——这是"子agent不会被主人格/其它子agent的海量样本稀释掉"的关键：
    不管子agent这段时间被咨询了多少次、产生了多少原始问答，它的身份/边界锚定
    永远会被完整混入这一轮训练，而不是被采样比例稀释。
    """
    full_dir = os.path.join(base_dir, rel_dir)
    if not os.path.isdir(full_dir):
        return []
    records = []
    for fname in sorted(os.listdir(full_dir)):
        if not fname.endswith(".jsonl"):
            continue
        agent_name = fname[:-len(".jsonl")]
        for r in _load_jsonl(os.path.join(full_dir, fname)):
            r.setdefault("_origin", "subagent_identity_anchor")
            r.setdefault("_agent", agent_name)
            records.append(r)
    return records


def load_refined_corpus(base_dir: str, rel_path: str) -> list:
    records = _load_jsonl(os.path.join(base_dir, rel_path))
    for r in records:
        r.setdefault("_origin", "refined_corpus")
    return records


def load_self_distillation(base_dir: str, rel_path: str) -> list:
    records = _load_jsonl(os.path.join(base_dir, rel_path))
    for r in records:
        r.setdefault("_origin", "self_distillation")
    return records


def profile_to_samples(memory_store, agent_display_name: str = "小K") -> list:
    """
    把画像记忆 + 长期摘要实时转成一批"自我认知"问答对，不落盘，每次现算。
    """
    if memory_store is None:
        return []
    samples = []
    sys_prompt = f"你是{agent_display_name}，一个专属于用户的私人助理agent。"

    profile = memory_store.get_all_profile()
    for key, value in profile.items():
        if not str(value).strip():
            continue
        samples.append({
            "system_prompt": sys_prompt,
            "user_input": f"我的{key}是什么，你还记得吗？",
            "assistant_output": f"记得，你的{key}是：{value}。",
            "_origin": "profile_sample",
        })

    summary_text = memory_store.profile_summary_text()
    if summary_text and "暂无画像记忆" not in summary_text:
        samples.append({
            "system_prompt": sys_prompt,
            "user_input": "总结一下，你目前对我的了解都有哪些？",
            "assistant_output": f"目前我记住的关于你的信息：\n{summary_text}",
            "_origin": "profile_sample",
        })

    long_summary = memory_store.long_term_summary()
    if long_summary and long_summary.strip():
        samples.append({
            "system_prompt": sys_prompt,
            "user_input": "到目前为止，我们都聊过什么，你还记得多少？",
            "assistant_output": long_summary.strip(),
            "_origin": "profile_sample",
        })
    return samples


def _dedupe_keep_first(records: list) -> list:
    seen = set()
    out = []
    for r in records:
        key = (str(r.get("user_input", "")).strip(), str(r.get("assistant_output", "")).strip())
        if not key[0] or not key[1]:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def assemble_training_corpus(base_dir: str, lora_cfg: dict, raw_samples: list,
                              memory_store=None, agent_display_name: str = "小K") -> tuple:
    """
    返回 (all_records, composition)。
    all_records 里每条记录至少包含 system_prompt / user_input / assistant_output，
    可以直接喂给 train_lora.py 里的 build_chat_text。
    composition 记录每个来源各贡献了多少条，写进 eval_report.json / registry.json
    方便日后追溯"这一版模型的能力具体是从哪些数据来的"。
    """
    identity = load_identity_anchors(base_dir, lora_cfg.get(
        "identity_anchors_path", "memory/identity/identity_anchors.jsonl"))
    subagent_identity = load_subagent_identity_anchors(base_dir, lora_cfg.get(
        "subagent_identity_anchors_dir", "memory/identity/subagents"))
    profile_samples = profile_to_samples(memory_store, agent_display_name)
    refined = load_refined_corpus(base_dir, lora_cfg.get(
        "refined_corpus_path", "memory/knowledge/refined_corpus.jsonl"))
    self_distill = load_self_distillation(base_dir, lora_cfg.get(
        "self_distillation_path", "memory/knowledge/self_distillation.jsonl"))

    raw_samples = list(raw_samples or [])
    for r in raw_samples:
        r.setdefault("_origin", "raw_sample")

    # 身份锚定(主+子agent) > 画像 > 精炼语料 > 主动探测 > 原始流水账
    merged = identity + subagent_identity + profile_samples + refined + self_distill + raw_samples
    deduped = _dedupe_keep_first(merged)

    # 按子agent统计各来源各贡献了多少条，方便追溯"这一版训练里，
    # 每个子agent到底跟着一起成长了多少"——train_lora.py会把这个写进
    # eval_report.json / registry.json，migrate_base_model.py会打印出来
    by_agent = {}
    for r in raw_samples + self_distill:
        name = r.get("agent") or r.get("_agent") or r.get("category") or "kai"
        by_agent[name] = by_agent.get(name, 0) + 1
    for r in subagent_identity:
        name = r.get("_agent", "unknown")
        by_agent.setdefault(name, 0)  # 保证即使这次没有新样本，子agent也出现在统计里

    composition = {
        "identity_anchors": len(identity),
        "subagent_identity_anchors": len(subagent_identity),
        "profile_samples": len(profile_samples),
        "refined_corpus": len(refined),
        "self_distillation": len(self_distill),
        "raw_samples": len(raw_samples),
        "total_before_dedup": len(merged),
        "total_after_dedup": len(deduped),
        "by_agent": by_agent,
    }
    return deduped, composition
