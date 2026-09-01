"""
adapter 版本对照工具
====================
换 base model 重新训练后，最实际的问题是："新版本是不是真的没丢东西？"
这个脚本把 registry.json 里任意两代 adapter 在同一份 eval_set.jsonl 上的输出
（存在各自的 eval_report.json -> eval_after 里）并排打印，肉眼过一遍最直接。

python 版本：
- python默认
- E:\Kai\kai_agent\venv\Scripts\python

用法：
    python compare_adapter_versions.py                  # 默认对比最近两代
    python compare_adapter_versions.py --a v3 --b v1    # 指定对比哪两代（version字段）
"""
import argparse
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_registry(adapter_dir: str) -> dict:
    reg_path = os.path.join(adapter_dir, "registry.json")
    if not os.path.exists(reg_path):
        return {"lineage": []}
    with open(reg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_entry(lineage: list, version: str):
    for e in lineage:
        if e["version"] == version:
            return e
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", help="较旧的版本号，比如 v1；不填默认取倒数第二代")
    parser.add_argument("--b", help="较新的版本号，比如 v2；不填默认取最新一代")
    args = parser.parse_args()

    import yaml
    with open(os.path.join(BASE_DIR, "config", "config.yaml"), "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    adapter_root = os.path.join(BASE_DIR, cfg["training"]["lora"]["adapter_dir"])
    registry = load_registry(adapter_root)
    lineage = registry.get("lineage", [])

    if len(lineage) < 2 and not (args.a and args.b):
        print("[compare] registry.json 里少于两代记录，没什么好对比的。先多训练几次。")
        return

    entry_b = find_entry(lineage, args.b) if args.b else lineage[-1]
    entry_a = find_entry(lineage, args.a) if args.a else lineage[-2]
    if not entry_a or not entry_b:
        print("[compare] 没找到指定的版本号，先看看 registry.json 里实际有哪些 version。")
        return

    print(f"[compare] 旧: {entry_a['version']} ({entry_a['base_model']}, "
          f"{entry_a['num_distilled_samples']}条蒸馏数据)")
    print(f"[compare] 新: {entry_b['version']} ({entry_b['base_model']}, "
          f"{entry_b['num_distilled_samples']}条蒸馏数据)")
    if entry_b.get("base_model_changed_from_prev"):
        print("[compare] ⚠ 这次对比跨了 base model，adapter权重本身不连续，"
              "重点看输出内容是否延续了知识/身份，而不是权重是否相似。")
    print("=" * 70)

    def read_eval_after(entry):
        report_path = os.path.join(BASE_DIR, entry["path"], "eval_report.json")
        if not os.path.exists(report_path):
            return []
        with open(report_path, "r", encoding="utf-8") as f:
            return json.load(f).get("eval_after", [])

    outputs_a = {r["prompt"]: r["output"] for r in read_eval_after(entry_a)}
    outputs_b = {r["prompt"]: r["output"] for r in read_eval_after(entry_b)}

    for prompt in outputs_a.keys() | outputs_b.keys():
        print(f"\n【问题】{prompt}")
        print(f"  旧({entry_a['version']}): {outputs_a.get(prompt, '(无记录)')}")
        print(f"  新({entry_b['version']}): {outputs_b.get(prompt, '(无记录)')}")


if __name__ == "__main__":
    main()
