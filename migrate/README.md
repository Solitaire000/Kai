# migrate/ —— 换 base model 的工具链

这个目录放的是"换 base model / 换 provider 之前，怎么把旧大脑的知识、语气、
能力尽量继承下去"这一整套工具。日常聊天、日常攒训练样本不需要碰这个目录，
只有你打算：

- 把当前依赖的在线 provider 从 A 换成 B，或者
- 把训练用的 base model 换掉（比如 `Qwen2.5-3B-Instruct` 换成别的模型）

的时候才需要用到。

## 目录下的四个脚本

| 脚本 | 作用 | 一般不需要单独手动跑 |
|---|---|---|
| `self_distillation.py` | 主动探测式蒸馏：用 `data/probes/probe_set.yaml` 题库系统性地"问一遍"旧大脑，把回答存成训练语料 | ✅ 由 `migrate_base_model.py --step distill-old` 自动调用 |
| `distill_training_corpus.py` | 把 `training_samples.db` 里积累的原始问答流水账提炼成结构化知识点，去重/去过时 | ✅ 由 `migrate_base_model.py --step train-and-check` 自动调用（可跳过） |
| `regression_score.py` | 训练完之后的硬性回归检查：身份认知没丢、安全边界没被蒸馏数据带偏 | ✅ 由 `migrate_base_model.py --step train-and-check` 自动调用 |
| `migrate_base_model.py` | 编排脚本，按正确顺序把上面三个脚本 + `train/train_lora.py` 串起来跑，在需要人工确认的地方停下来等你 | —（这个就是你要手动跑的入口） |

**正常情况下你只需要直接跑 `migrate_base_model.py`**，不需要单独调用另外三个脚本——
它们是编排脚本内部按需调用的实现细节，只有你想更细粒度控制每一步、或者调试某一步
本身的时候，才需要单独跑。完整流程说明见 [`train/README_INHERITANCE.md`](../train/README_INHERITANCE.md)。

## 快速上手

```bash
# 1. 先看看当前有哪些子agent（决定要不要用 --subagents 只挑一部分）
python migrate_base_model.py --list-agents

# 2. 给旧大脑做快照（换config.yaml的base_model之前跑，探测的才是"旧"大脑）
python migrate_base_model.py --step distill-old --label before_switch_2026q3 --provider local

#    默认会把全部子agent的知识/语气一起快照下来；也可以只挑一部分：
python migrate_base_model.py --step distill-old --label before_switch_2026q3 --provider local --subagents research,work

#    或者完全不快照子agent，只快照Kai主人格：
python migrate_base_model.py --step distill-old --label before_switch_2026q3 --provider local --no-subagents

# 3. 手动编辑 config/config.yaml -> training.lora.base_model 指向新模型

# 4. 提炼(可选) + 全量重训 + 自动回归检查，一次跑完
python migrate_base_model.py --step train-and-check

# 或者第1-4步一次串联（第2步跑完会暂停，等你确认改好config.yaml再继续）：
python migrate_base_model.py --step all --label before_switch_2026q3 --provider local
```

## 运行环境说明

这几个脚本不依赖项目日常使用的那个虚拟环境（`venv/`），用哪个 Python 版本/环境跑
根据你实际情况自行决定即可——`self_distillation.py --provider` 轻量模式只需要
`requirements.txt` 里已有的依赖；`--adapter-path` 重量级模式和 `regression_score.py`
需要 `train/requirements-train.txt`（transformers/peft/torch），建议在装了这些依赖的
训练环境里跑。

## 常见问题

**Q: `--include-subagents` 需要我手动单独跑吗？**
不需要。`migrate_base_model.py --step distill-old` 默认就会带上它（对全部子agent），
除非你加 `--no-subagents`，或者用 `--subagents` 只挑一部分。

**Q: 怎么知道现在有哪些子agent可以选？**
`python migrate_base_model.py --list-agents`，或者 `python self_distillation.py --list-agents`。
