"""
migrate/distill_training_corpus.py
=====================================
training_samples.db 里的原始问答对是"流水账"：攒得越久，重复/过时内容越多，
换 base model 全量重放时效率会越来越低，质量也参差不齐。

这个脚本定期（比如样本攒够几百条时）把某个 agent 下积累的一批原始问答对，
交给一个教师模型做"提炼"：抽取出结构化的知识点/常见问题模式，
产出一份小得多、质量更高的精炼语料，和原始语料并行保留
（原始语料不会被删除，只是训练时优先级更低）。

产出：
    memory/knowledge/refined_corpus.jsonl
    （追加写入；train/corpus_builder.py 训练时会读取这个文件）

用法：
    python migrate/distill_training_corpus.py                     # 处理全部agent，每批20条
    python migrate/distill_training_corpus.py --agent research    # 只处理某个agent
    python migrate/distill_training_corpus.py --dry-run           # 只看看会分几批、不实际调用模型
    python migrate/distill_training_corpus.py --provider siliconflow   # 强制用指定教师模型
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict

import yaml

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.training_logger import TrainingLogger  # noqa: E402

DISTILL_SYSTEM_PROMPT = """你是一个语料提炼助手。下面会给你一批"用户问-助理答"的历史问答对（都来自同一个私人助理agent的真实对话历史）。
请你把这批问答对提炼成一份更精炼的知识/行为模式清单，去掉重复表达、寒暄、过时或低信息量的内容，只保留有沉淀价值的部分。

严格按下面的JSON数组格式输出，不要输出任何多余文字、不要用markdown代码块包裹：
[
  {"user_input": "一个有代表性的问法（可以是你归纳后的通用问法，不必逐字照抄原文）", "assistant_output": "对应的精炼后回答，保留关键信息和这个agent一贯的语气风格"},
  ...
]

要求：
1. 同一个知识点/模式只保留一条，别重复。
2. 优先保留：专业领域知识、稳定的处理套路/思维方式、用户明确的个人偏好。不要保留：单次的、跟长期无关的琐事。
3. 数量控制在输入问答对数量的 30%-60% 左右，做的是"提炼压缩"，不是"逐条改写"。
"""


def load_config():
    with open(os.path.join(BASE_DIR, "config", "config.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def call_teacher(router, batch, agent_name):
    user_content = "问答对列表：\n" + json.dumps(
        [{"user_input": s["user_input"], "assistant_output": s["assistant_output"]} for s in batch],
        ensure_ascii=False, indent=2,
    )
    messages = [
        {"role": "system", "content": DISTILL_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    resp = router.chat(messages, complex=True, max_tokens=1800)
    text = resp.get("text", "").strip()
    if resp.get("degraded"):
        print("[distill_training_corpus] 警告: 这批调用降级到了本地模型，"
              "本地小模型提炼质量可能不够好，建议稍后网络恢复了重跑这批")
    # 容错：模型有时会不听话包一层 ```json ... ```
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("不是一个JSON数组")
        return parsed
    except Exception as e:
        print(f"[distill_training_corpus] 警告: 本批解析失败 ({e})，原始输出前200字: {text[:200]!r}")
        return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default=None, help="只处理某个 agent（不填=全部）")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--provider", default=None, help="强制指定教师模型provider，不填=自动路由(complex=True)")
    parser.add_argument("--out", default="memory/knowledge/refined_corpus.jsonl")
    args = parser.parse_args()

    cfg = load_config()
    agent_name = cfg.get("agent", {}).get("name", "小K")
    logger = TrainingLogger(cfg, BASE_DIR)

    samples = logger.export_all(exclude_disliked=True)
    if args.agent:
        samples = [s for s in samples if s.get("agent") == args.agent]

    by_agent = defaultdict(list)
    for s in samples:
        by_agent[s.get("agent", "general")].append(s)

    print(f"[distill_training_corpus] 待提炼样本总数: {len(samples)}，按agent分组: "
          f"{ {k: len(v) for k, v in by_agent.items()} }")

    if args.dry_run:
        for agent, items in by_agent.items():
            n_batches = (len(items) + args.batch_size - 1) // args.batch_size
            print(f"  - {agent}: {len(items)} 条 -> {n_batches} 批（每批{args.batch_size}条）")
        print("[distill_training_corpus] --dry-run 模式，没有实际调用模型。")
        logger.close()
        return

    from core.model_router import ModelRouter
    router = ModelRouter(cfg, BASE_DIR)

    out_path = os.path.join(BASE_DIR, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    total_written = 0
    ts = time.time()
    with open(out_path, "a", encoding="utf-8") as f:
        for agent, items in by_agent.items():
            print(f"\n[distill_training_corpus] === agent: {agent}，{len(items)} 条，"
                  f"分 {(len(items) + args.batch_size - 1)//args.batch_size} 批 ===")
            for batch_idx, batch in enumerate(chunked(items, args.batch_size)):
                print(f"[distill_training_corpus] 处理第 {batch_idx+1} 批（{len(batch)}条）...")
                refined = call_teacher(router, batch, agent_name)
                for r in refined:
                    if not r.get("user_input") or not r.get("assistant_output"):
                        continue
                    record = {
                        "system_prompt": f"你是{agent_name}，一个专属于用户的私人助理agent。",
                        "user_input": r["user_input"],
                        "assistant_output": r["assistant_output"],
                        "distilled_from_agent": agent,
                        "distilled_from_count": len(batch),
                        "distilled_at": ts,
                    }
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    total_written += 1
                print(f"[distill_training_corpus]   -> 提炼出 {len(refined)} 条精炼语料 "
                      f"(压缩比 {len(refined)}/{len(batch)})")

    logger.close()
    print(f"\n[distill_training_corpus] ✅ 完成，累计写入 {total_written} 条精炼语料到 {out_path}")
    print("[distill_training_corpus] 注意：原始 training_samples.db 里的数据不会被删除或标记已用，"
          "两者会并行存在，train_lora.py 训练时都会读取（refined_corpus 优先级更高，去重时会保留）。")


if __name__ == "__main__":
    main()
