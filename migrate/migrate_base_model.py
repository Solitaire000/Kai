"""
migrate/migrate_base_model.py
================================
换 base model 时要做的事情分散在好几个脚本里（self_distillation / train_lora /
regression_score），容易漏步骤。这个脚本不重新实现逻辑，只是按正确顺序
把它们串起来跑，并在需要你手动确认/编辑配置的地方停下来等你。

完整流程（对应 train/README_TRAINING.md 第六节 + 本次新增的扩展）：

    0. [手动] 确认 config.yaml -> training.lora.base_model 还没改成新模型
       （第1步要用旧配置探测"旧大脑"，顺序反了会探测到新模型自己）
    1. [自动] self_distillation.py：主动探测旧大脑，产出旧大脑快照
    2. [手动] 编辑 config.yaml -> training.lora.base_model 指向新模型
    3. [自动] （可选）distill_training_corpus.py：如果原始语料积累很多了，先提炼一遍
    4. [自动] train_lora.py --include-used：全量重训（身份锚定+画像+精炼语料+
              旧大脑快照+原始语料，全部由 core/corpus_builder.py 自动组装）
    5. [自动] regression_score.py：硬性门槛检查（身份没丢、安全边界没松）
    6. [手动] 人工核对 eval_report.json，确认专业问题回答质量提升
    7. [手动] merge_and_unload 合并 adapter + 转 GGUF + 切换 local_fallback
       （这一步依赖你本地 llama.cpp 版本，train_lora.py 文件末尾注释里有参考命令，
        这里不自动化，避免不同环境命令不一致导致失败）

用法：
    # 第一次跑：只做第1步（探测旧大脑），跑完你自己去编辑config.yaml
    python migrate/migrate_base_model.py --step distill-old --label before_switch_2026q3 --provider local

    # 改完config.yaml后，跑第3-5步
    python migrate/migrate_base_model.py --step train-and-check

    # 或者全部自动串联（第1步跑完会暂停，等你确认已经编辑好config.yaml再继续）
    python migrate/migrate_base_model.py --step all --label before_switch_2026q3 --provider local
"""
import argparse
import subprocess
import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# self_distillation.py / distill_training_corpus.py / regression_score.py 和本文件
# 都在 migrate/ 目录下，用本文件所在目录动态拼路径调用它们，而不是硬编码固定字符串，
# 这样以后不管从哪个工作目录运行本文件，或者这几个脚本一起被挪到别的目录，都不会因为
# 相对路径找不到文件而 FileNotFoundError。
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
# list_agents() 需要 `import agents.specialized_agents`；本文件可能从任意工作目录被
# 直接执行（不一定是项目根目录），所以要把项目根目录加进 sys.path。
sys.path.append(BASE_DIR)


def script_path(filename: str) -> str:
    return os.path.join(SCRIPT_DIR, filename)


def run(cmd: list, allow_fail: bool = False) -> int:
    print(f"\n{'='*70}\n[migrate_base_model] 执行: {' '.join(cmd)}\n{'='*70}")
    result = subprocess.run(cmd, cwd=BASE_DIR)
    if result.returncode != 0 and not allow_fail:
        print(f"[migrate_base_model] ❌ 步骤失败 (exit={result.returncode})，流程中止。")
        sys.exit(result.returncode)
    return result.returncode


def step_distill_old(args):
    cmd = [PY, script_path("self_distillation.py"), "--label", args.label]
    if args.provider:
        cmd += ["--provider", args.provider]
        if args.subagents:
            # 只快照指定的子agent（隐含 include-subagents，self_distillation.py 内部处理）
            cmd += ["--subagents", args.subagents]
        elif not args.no_subagents:
            # 换base model前，默认把子agent的知识/语气也一起快照下来，
            # 保证它们跟着Kai一起继承到新base model，而不是被落下
            cmd += ["--include-subagents"]
    if args.adapter_path and args.base_model_old:
        cmd += ["--adapter-path", args.adapter_path, "--base-model", args.base_model_old]
    run(cmd)
    print("\n[migrate_base_model] ✅ 旧大脑快照已完成。")
    print("[migrate_base_model] 下一步（手动）：编辑 config/config.yaml，把")
    print("    training.lora.base_model")
    print("  改成你要换的新模型，保存后再继续跑：")
    print(f"    python migrate_base_model.py --step train-and-check")


def step_refine(args):
    cmd = [PY, script_path("distill_training_corpus.py")]
    run(cmd, allow_fail=True)  # 提炼质量不理想不应该中止整个迁移流程


def step_train_and_check(args):
    if not args.skip_refine:
        step_refine(args)

    run([PY, "train/train_lora.py", "--include-used"])

    # 从 registry.json 里取最新版本号，喂给 regression_score.py
    import json
    with open(os.path.join(BASE_DIR, "config", "config.yaml"), "r", encoding="utf-8") as f:
        import yaml
        cfg = yaml.safe_load(f)
    adapter_dir = cfg["training"]["lora"]["adapter_dir"]
    registry_path = os.path.join(BASE_DIR, adapter_dir, "registry.json")
    with open(registry_path, "r", encoding="utf-8") as f:
        registry = json.load(f)
    if not registry["lineage"]:
        print("[migrate_base_model] registry.json 是空的，train_lora.py 可能没有实际训练（样本不够？）")
        sys.exit(1)
    latest = registry["lineage"][-1]
    version = latest["version"]
    print(f"\n[migrate_base_model] 最新训练版本: {version}（base_model={latest['base_model']}）")
    comp = latest.get("corpus_composition", {})
    if comp.get("by_agent"):
        print(f"[migrate_base_model] 本次训练里，Kai主人格+各子agent的语料贡献: {comp['by_agent']}")
        print("[migrate_base_model] 这份分布值得留意：如果某个子agent持续是0，"
              "说明它一直没被咨询过，权重里关于它的知识只靠身份锚定撑着，"
              "该考虑要不要往 data/probes/probe_set.yaml 里给它多加几条探测题。")

    rc = run([PY, script_path("regression_score.py"), "--version", version], allow_fail=True)

    print("\n" + "=" * 70)
    if rc == 0:
        print("[migrate_base_model] ✅ 自动化检查通过。接下来请你人工过一遍：")
    else:
        print("[migrate_base_model] ⚠️ 自动化硬性检查未通过，强烈建议先看 regression_report.json "
              "再决定要不要继续，而不是直接采用这个版本。")
    print(f"  1. 打开 {latest['path']}/eval_report.json，人工确认：")
    print("     - 身份认知没丢（还知道自己是小K）")
    print("     - 安全边界没有被蒸馏数据带偏")
    print("     - 专业问题回答质量确实比训练前更好")
    print("  2. 确认无误后，手动合并adapter+转GGUF+切换local_fallback")
    print("     （具体命令见 train/train_lora.py 文件末尾注释）")
    print("=" * 70)


def list_agents():
    """
    列出所有已注册的子agent（agents/specialized_agents.py::ALL_AGENTS），
    方便在跑 --step distill-old 之前决定要不要用 --subagents 只挑一部分。
    """
    from agents.specialized_agents import ALL_AGENTS, FALLBACK_AGENT
    print(f"[migrate_base_model] Kai主人格（常驻，不算子agent）: {FALLBACK_AGENT.name} - {FALLBACK_AGENT.description}")
    print(f"[migrate_base_model] 已注册的子agent（共 {len(ALL_AGENTS)} 个）：")
    for sub in ALL_AGENTS:
        cats = ", ".join(sub.probe_categories) if sub.probe_categories else "(未声明probe_categories，探测时会被跳过)"
        model = "premium/复杂模型" if sub.model_complex else "默认路由"
        print(f"  - {sub.name}: {sub.description}")
        print(f"      probe_categories: {cats}")
        print(f"      model_complex: {model}")
    print("\n[migrate_base_model] 用法示例：")
    print("  只快照 research 和 work 两个子agent：")
    print("    python migrate_base_model.py --step distill-old --label xxx --provider local --subagents research,work")
    print("  跳过全部子agent，只快照Kai主人格：")
    print("    python migrate_base_model.py --step distill-old --label xxx --provider local --no-subagents")


def main():
    parser = argparse.ArgumentParser(description="换 base model 的标准流程编排")
    parser.add_argument("--step", choices=["distill-old", "refine", "train-and-check", "all"],
                         required=False, help="除 --list-agents 外的所有用法都需要提供")
    parser.add_argument("--label", default=None, help="distill-old 步骤需要，快照标签")
    parser.add_argument("--provider", default=None, help="distill-old 轻量模式：provider name 或 'local'")
    parser.add_argument("--adapter-path", default=None, help="distill-old 重量级模式")
    parser.add_argument("--base-model-old", default=None, help="distill-old 重量级模式：旧base model")
    parser.add_argument("--skip-refine", action="store_true", help="train-and-check 时跳过语料提炼步骤")
    parser.add_argument("--no-subagents", action="store_true",
                         help="distill-old 步骤默认会顺带探测全部子agent，加这个flag跳过（只探测Kai主人格）。"
                              "和 --subagents 互斥")
    parser.add_argument("--subagents", default=None,
                         help="逗号分隔的子agent名单，distill-old 步骤只额外快照这几个子agent"
                              "（不填=快照全部子agent，除非加了 --no-subagents）。"
                              "用 --list-agents 查看有哪些子agent可选")
    parser.add_argument("--list-agents", action="store_true",
                         help="列出所有已注册子agent的信息后退出，不执行任何迁移步骤")
    args = parser.parse_args()

    if args.list_agents:
        list_agents()
        sys.exit(0)

    if args.subagents and args.no_subagents:
        print("[ERROR] --subagents 和 --no-subagents 互斥，只能选一个")
        sys.exit(1)

    if not args.step:
        print("[ERROR] 必须指定 --step（或者单独用 --list-agents 查看子agent列表）")
        sys.exit(1)

    if args.step in ("distill-old", "all"):
        if not args.label:
            print("[ERROR] --step distill-old / all 需要提供 --label")
            sys.exit(1)
        step_distill_old(args)
        if args.step == "all":
            input("\n>>> 请现在手动编辑 config/config.yaml 里的 training.lora.base_model 为新模型，"
                  "\n>>> 编辑并保存后按回车继续（Ctrl+C 可以先退出，改完再单独跑 --step train-and-check）...")

    if args.step in ("refine",):
        step_refine(args)

    if args.step in ("train-and-check", "all"):
        step_train_and_check(args)


if __name__ == "__main__":
    main()
