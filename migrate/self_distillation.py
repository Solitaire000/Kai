"""
migrate/self_distillation.py
==============================
"继承旧 base_model 全部内容"这件事，光靠被动积累的聊天记录是不够的——
很多知识、推理习惯、说话风格从来没被聊到过，换 base model 时会悄无声息地丢掉。

这个脚本在你要更换 base_model / 更换某个 provider 之前，主动用
data/probes/probe_set.yaml 里的题库系统性地"问一遍"旧大脑，把回答存成
训练语料，作为"旧大脑快照"。之后不管旧 adapter / 旧 provider 是否还在用，
这份快照都能被拿来训练新 base model，尽量还原旧大脑的知识、推理方式和风格。

两种目标模式：

1. --provider 模式（轻量，推荐日常用）：
   通过 core/model_router.py 现有的路由，强制指定一个 provider（在线服务商的
   name，或 "local" 指当前配置的本地离线模型），把它当"旧大脑"来探测。
   适合场景：你打算把"日常主要依赖的 provider"从 A 换成 B，想在切换前把
   A 的知识/风格蒸馏下来。

2. --adapter-path 模式（重量级，用于"彻底告别一个旧 LoRA adapter"场景）：
   直接用 transformers + peft 在本地加载某个旧 adapter + 它对应的旧 base model
   做推理，把这套具体的权重组合的行为快照下来。适合场景：train_lora.py
   训出来的某个旧版本 adapter，即将因为换 base model 被彻底弃用，想在
   丢弃前把它"审问"一遍，尽量把它学到的东西转成文本继承下去。

产出：
    memory/knowledge/self_distillation.jsonl
    （追加写入，每条记录一个 snapshot_id + probe_id，可重复运行，
     旧记录不会被覆盖；train/corpus_builder.py 训练时会读取这个文件）

用法：
    # 轻量模式：探测当前路由到 openrouter_qwen 的行为
    python migrate/self_distillation.py --provider openrouter_qwen --label before_switch_2026q3

    # 轻量模式：探测当前本地离线模型
    python migrate/self_distillation.py --provider local --label old_local_v3

    # 重量级模式：直接加载某个具体的旧 adapter + base 做快照
    python migrate/self_distillation.py --adapter-path data/adapters/Qwen2.5-3B-Instruct/v4 \\
        --base-model Qwen/Qwen2.5-3B-Instruct --label retiring_qwen_v4

    # 只跑某几个分类，不跑全部题库（省时间/省token）
    python migrate/self_distillation.py --provider local --label quick_check --categories reasoning,coding_and_tools

    # 【子agent共同进化】除了用Kai主人格探测一遍，额外把每个子agent自己
    # probe_categories 里声明的分类，再用子agent自己的人设探测一遍，
    # 保证换 base model 前，子agent的知识/语气也和Kai一起被完整快照下来：
    python migrate/self_distillation.py --provider local --label before_switch_2026q3 --include-subagents

    # 只想探测其中一部分子agent（而不是全部），用 --subagents 精确指定：
    python migrate/self_distillation.py --provider local --label quick_check --subagents research,work

    # 查看当前有哪些子agent可选（不会真的探测，看完就退出）：
    python migrate/self_distillation.py --list-agents
"""
import argparse
import json
import os
import sys
import time

import yaml

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)


def load_config():
    config_path = os.path.join(BASE_DIR, "config", "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_probe_set(path: str, categories_filter=None) -> list:
    full_path = os.path.join(BASE_DIR, path)
    with open(full_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    probes = []
    for cat in data.get("categories", []):
        cat_name = cat.get("category", "uncategorized")
        if categories_filter and cat_name not in categories_filter:
            continue
        for item in cat.get("items", []):
            probes.append({
                "id": item["id"],
                "category": cat_name,
                "prompt": item["prompt"],
                "system_prompt": item.get("system_prompt"),
            })
    return probes


def default_system_prompt(agent_name: str) -> str:
    return f"你是{agent_name}，一个专属于用户的私人助理agent。"


def run_via_router(cfg, probes, provider, agent_name, subagent=None):
    """
    轻量模式：复用 core/model_router.py 的现有路由逻辑。
    subagent 不填=用Kai主人格探测；填了=用这个子agent自己的system_prompt探测，
    产出的记录会打上 "agent": subagent.name，供 corpus_builder.py 统计"子agent
    这次一起成长了多少"。
    """
    from core.model_router import ModelRouter
    router = ModelRouter(cfg, BASE_DIR)

    results = []
    for p in probes:
        sys_prompt = p["system_prompt"] or (subagent.system_prompt if subagent else default_system_prompt(agent_name))
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": p["prompt"]},
        ]
        complex_task = bool(subagent and getattr(subagent, "model_complex", False))
        resp = router.chat(messages, force_provider=provider, complex=complex_task, max_tokens=600)
        text = resp.get("text", "").strip()
        if not text:
            print(f"[self_distillation] 跳过 {p['id']}：没有拿到有效回答 "
                  f"(errors={resp.get('errors')})")
            continue
        if resp.get("degraded"):
            print(f"[self_distillation] 警告: {p['id']} 触发了离线降级，"
                  f"这条回答不是目标 provider 本身的输出，已跳过")
            continue
        results.append({
            "probe_id": p["id"],
            "category": p["category"],
            "agent": subagent.name if subagent else "kai",
            "system_prompt": sys_prompt,
            "user_input": p["prompt"],
            "assistant_output": text,
            "source_desc": f"router:{resp.get('source', provider)}",
        })
        tag = f"[{subagent.name}]" if subagent else "[kai]"
        print(f"[self_distillation] ✓ {tag} {p['id']} ({p['category']})")
    return results


def run_via_local_adapter(probes, adapter_path, base_model, agent_name, max_new_tokens=400):
    """
    重量级模式：直接加载一个具体的旧 adapter + base model 做推理。
    只在你要彻底弃用某个 adapter、想在丢弃前把它的行为存下来时才需要用。
    依赖 train/requirements-train.txt 里的 transformers/peft/torch/bitsandbytes。
    """
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel

    print(f"[self_distillation] 加载 base model: {base_model}")
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        base_model, quantization_config=bnb_config, device_map="auto", trust_remote_code=True,
    )
    print(f"[self_distillation] 加载 adapter: {adapter_path}")
    model = PeftModel.from_pretrained(model, os.path.join(BASE_DIR, adapter_path))
    model.eval()
    device = next(model.parameters()).device

    results = []
    for p in probes:
        sys_prompt = p["system_prompt"] or default_system_prompt(agent_name)
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": p["prompt"]},
        ]
        text_in = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(text_in, return_tensors="pt").to(device)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        reply = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        if not reply:
            continue
        results.append({
            "probe_id": p["id"],
            "category": p["category"],
            "agent": "kai",
            "system_prompt": sys_prompt,
            "user_input": p["prompt"],
            "assistant_output": reply,
            "source_desc": f"local_adapter:{adapter_path}",
        })
        print(f"[self_distillation] ✓ {p['id']} ({p['category']})")
    return results


def main():
    parser = argparse.ArgumentParser(description="主动探测式蒸馏：换 base model 前给旧大脑做一次快照")
    parser.add_argument("--label", required=False,
                         help="这次快照的标签，比如 before_switch_2026q3，会写进每条记录的 snapshot_id"
                              "（--list-agents 模式下不需要）")
    parser.add_argument("--provider", default=None,
                         help="轻量模式：core/model_router.py 里的 provider name，或 'local'")
    parser.add_argument("--adapter-path", default=None, help="重量级模式：旧 adapter 目录路径")
    parser.add_argument("--base-model", default=None, help="重量级模式：adapter 对应的 base model")
    parser.add_argument("--probe-set", default="data/probes/probe_set.yaml")
    parser.add_argument("--categories", default=None,
                         help="逗号分隔，只跑指定分类，不填=跑全部题库")
    parser.add_argument("--include-subagents", action="store_true",
                         help="除了用Kai主人格探测一遍，额外对每个子agent自己"
                              "probe_categories声明的分类，用子agent自己的人设"
                              "再探测一遍（只有 --provider 轻量模式支持这个选项）")
    parser.add_argument("--subagents", default=None,
                         help="逗号分隔的子agent名单，只额外探测这几个子agent"
                              "（隐含 --include-subagents，不需要再单独加该flag）。"
                              "不填 --subagents 但加了 --include-subagents = 探测全部子agent。"
                              "用 --list-agents 查看有哪些子agent可选")
    parser.add_argument("--list-agents", action="store_true",
                         help="列出所有已注册的子agent（name/description/probe_categories）后退出，"
                              "不执行任何探测")
    parser.add_argument("--out", default="memory/knowledge/self_distillation.jsonl")
    args = parser.parse_args()

    if args.list_agents:
        from agents.specialized_agents import ALL_AGENTS
        print(f"[self_distillation] 已注册的子agent（共 {len(ALL_AGENTS)} 个）：")
        for sub in ALL_AGENTS:
            cats = ", ".join(sub.probe_categories) if sub.probe_categories else "(未声明probe_categories，--include-subagents不会探测到它)"
            print(f"  - {sub.name}: {sub.description}")
            print(f"      probe_categories: {cats}")
        sys.exit(0)

    if not args.label:
        print("[ERROR] --label 是必填项（--list-agents 模式除外）")
        sys.exit(1)
    if not args.provider and not (args.adapter_path and args.base_model):
        print("[ERROR] 必须指定 --provider（轻量模式）或者 --adapter-path + --base-model（重量级模式）之一")
        sys.exit(1)
    if (args.include_subagents or args.subagents) and not args.provider:
        print("[ERROR] --include-subagents / --subagents 目前只支持 --provider 轻量模式")
        sys.exit(1)

    selected_subagent_names = None
    if args.subagents:
        selected_subagent_names = {s.strip() for s in args.subagents.split(",") if s.strip()}
        args.include_subagents = True  # --subagents 隐含 --include-subagents
        # 提前校验子agent名字是否存在，避免跑完一整轮（可能很耗时/耗token的）
        # 主人格探测之后，才在最后发现 --subagents 拼错了字
        from agents.specialized_agents import ALL_AGENTS as _ALL_AGENTS
        valid_names = {a.name for a in _ALL_AGENTS}
        unknown = selected_subagent_names - valid_names
        if unknown:
            print(f"[ERROR] --subagents 里有未注册的子agent名: {sorted(unknown)}，"
                  f"可用: {sorted(valid_names)}（用 --list-agents 查看详情）")
            sys.exit(1)

    cfg = load_config()
    agent_name = cfg.get("agent", {}).get("name", "小K")
    categories_filter = set(args.categories.split(",")) if args.categories else None
    probes_by_category = {}
    for p in load_probe_set(args.probe_set, categories_filter):
        probes_by_category.setdefault(p["category"], []).append(p)
    all_probes = [p for plist in probes_by_category.values() for p in plist]
    print(f"[self_distillation] 加载题库: {len(all_probes)} 条探测题")

    if args.provider:
        raw_results = run_via_router(cfg, all_probes, args.provider, agent_name)
    else:
        raw_results = run_via_local_adapter(all_probes, args.adapter_path, args.base_model, agent_name)

    if args.include_subagents:
        from agents.specialized_agents import ALL_AGENTS
        target_agents = ALL_AGENTS
        if selected_subagent_names is not None:
            # 名字合法性已在 main() 前面提前校验过，这里只需要过滤
            target_agents = [a for a in ALL_AGENTS if a.name in selected_subagent_names]
        for sub in target_agents:
            sub_probes = [p for cat in sub.probe_categories for p in probes_by_category.get(cat, [])]
            if not sub_probes:
                continue
            print(f"\n[self_distillation] === 额外用子agent「{sub.name}」的人设，"
                  f"再探测 {len(sub_probes)} 条（分类: {sub.probe_categories}）===")
            raw_results += run_via_router(cfg, sub_probes, args.provider, agent_name, subagent=sub)

    ts = time.time()
    out_path = os.path.join(BASE_DIR, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "a", encoding="utf-8") as f:
        for r in raw_results:
            record = {
                "snapshot_id": args.label,
                "probe_id": r["probe_id"],
                "category": r["category"],
                "agent": r.get("agent", "kai"),
                "system_prompt": r["system_prompt"],
                "user_input": r["user_input"],
                "assistant_output": r["assistant_output"],
                "source_desc": r["source_desc"],
                "captured_at": ts,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    by_agent = {}
    for r in raw_results:
        a = r.get("agent", "kai")
        by_agent[a] = by_agent.get(a, 0) + 1
    print(f"\n[self_distillation] ✅ 完成，写入 {len(raw_results)} 条到 {out_path}")
    print(f"[self_distillation] 按agent分布: {by_agent}")
    print("[self_distillation] 建议：跑完之后打开这个文件人工扫一眼，"
          "删掉明显质量差/答非所问的条目，再进入训练环节。")
    print("[self_distillation] 下一步：python train/train_lora.py --include-used "
          "（新语料会被 core/corpus_builder.py 自动纳入，不需要额外操作）")


if __name__ == "__main__":
    main()
