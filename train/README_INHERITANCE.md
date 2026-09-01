# 记忆/思维/知识的完整继承方案（扩展版）

对应 `README_TRAINING.md` 第六节，把"能继承的东西"从"记忆+身份+蒸馏问答"
扩展到不受限的六个来源，并补上"换 base model 时怎么保证真的继承完整"的
完整工具链。概念性的总览（两类记忆怎么分、六个来源怎么排优先级）见
[`docs/MEMORY_MODEL.md`](../docs/MEMORY_MODEL.md)，这份文档只讲**具体怎么操作**。

---

## 一、六个可继承的资产来源

| 来源 | 落地文件 | 产出方式 | 特点 |
|---|---|---|---|
| ① 身份/边界锚定 | `memory/identity/identity_anchors.jsonl` | 手写 | 最高优先级，每次训练强制混入 |
| ② 子agent身份锚定 | `memory/identity/subagents/<name>.jsonl` | 手写 | 每个子agent专属，防止被主人格样本稀释 |
| ③ 画像记忆 | `memory/memory.db`（现算现用，不落训练语料盘） | 自动，实时 | 反映画像最新状态，不用维护 |
| ④ 精炼知识语料 | `memory/knowledge/refined_corpus.jsonl` | `migrate/distill_training_corpus.py` 定期跑 | 原始问答的"沉淀版"，去重复/去过时 |
| ⑤ 旧大脑主动探测快照 | `memory/knowledge/self_distillation.jsonl` | `migrate/self_distillation.py`，换模型前跑 | 覆盖"从没被聊到过、但确实具备"的能力 |
| ⑥ 原始蒸馏问答 | `memory/training_samples.db` | 日常对话自动积累（原有机制） | 流水账，最基础的一层 |

六者由新增的 `core/corpus_builder.py` 在每次 `train/train_lora.py` 跑的时候
自动组装、去重（①>②>③>④>⑤>⑥ 优先级），不需要你手动合并文件。

---

## 二、为什么"知识不局限于这三点"这件事，被动聊天记录做不到

蒸馏语料只能覆盖"你恰好和它聊过的话题"。如果你的日常使用高度集中在
几类任务上（比如日程管理、代码），那模型在**其它领域**的知识、推理习惯、
说话风格，即使旧 base model 本身具备，也从来没有被记录下来——换新 base
model 重训时，这部分会**悄无声息地丢失**，因为根本没有语料能体现它。

`migrate/self_distillation.py` + `data/probes/probe_set.yaml` 就是为了解决
这个盲区：换 base model 之前，主动、系统性地"问一遍"旧大脑，覆盖身份、
推理、代码、说话风格、任务处理套路、领域知识、通用知识广度等多个维度，
把回答存下来当训练语料。这是目前这套方案里，"继承旧 base_model 全部内容"
最关键的一步——不做这一步，蒸馏语料本质上只是"日常问过的那些问题"的子集。

`data/probes/probe_set.yaml` 是可以持续扩充的，尤其建议把你自己领域
（比如 GSG 探针检测相关）的典型问题加进 `domain_expertise` 分类。

---

## 三、日常怎么用

**平时完全不用管**，和原来一样正常聊天、正常攒 `training_samples.db`。

**数据量大了之后**（比如某个 agent 攒了几百条），跑一次提炼，把流水账
压缩成精炼语料，长期看能让每次重训更高效、质量更高：

```bash
python migrate/distill_training_corpus.py --dry-run   # 先看看会分几批
python migrate/distill_training_corpus.py              # 实际跑
```

---

## 四、换 base model 的完整流程

### 方式A：用编排脚本（推荐）

```bash
# 0.（可选）先看看当前有哪些子agent
python migrate/migrate_base_model.py --list-agents

# 第1步：先给旧大脑做快照（还没改config.yaml之前跑，探测的才是"旧"大脑）
python migrate/migrate_base_model.py --step distill-old \
    --label before_switch_2026q3 --provider local
# provider 填 core/model_router.py 里 online_providers 的 name，或 "local"
# 默认会把全部子agent一起快照；只想快照一部分用 --subagents research,work；
# 完全不管子agent用 --no-subagents

# 手动编辑 config/config.yaml -> training.lora.base_model 指向新模型

# 第2步：提炼(可选) + 全量重训 + 自动回归检查，一次跑完
python migrate/migrate_base_model.py --step train-and-check
```

### 方式B：分步手动跑（想更细粒度控制时用）

```bash
# 1. 旧大脑快照
python migrate/self_distillation.py --provider local --label before_switch_2026q3

# 2. （可选）提炼原始流水账
python migrate/distill_training_corpus.py

# 3. 改 config.yaml -> training.lora.base_model

# 4. 全量重训（--include-used 把历史样本也一起拿来训，新base model要"重新出发"）
python train/train_lora.py --include-used

# 5. 自动回归门槛检查（身份没丢、安全边界没松）
python migrate/regression_score.py --version v6   # 版本号从上一步的输出里看

# 6. 人工核对 eval_report.json + regression_report.json

# 7. 手动合并adapter+转GGUF+切换local_fallback（见 train_lora.py 文件末尾注释）
```

---

## 五、如果要彻底弃用一个具体的旧 LoRA adapter

场景：`data/adapters/<base>/v4` 这个具体版本即将因为换 base model 被弃用，
想在丢弃前把它学到的东西尽量转成文本继承下去（而不只是"把它训练时用过的
原始语料重放一遍"——因为训练本身可能让它产生了一些语料里没有、但权重里
已经学到的行为模式）：

```bash
python migrate/self_distillation.py \
    --adapter-path data/adapters/Qwen2.5-3B-Instruct/v4 \
    --base-model Qwen/Qwen2.5-3B-Instruct \
    --label retiring_qwen_v4
```

这个"重量级模式"会直接加载这个具体的 adapter+base 组合做推理，比"轻量模式"
（通过 `model_router` 调 provider）更能捕捉到这个特定 adapter 训练出来的、
可能没被显式记录在 `training_samples.db` 里的细微行为差异。

---

## 六、后续可以继续加的东西（这次没做）

- **DPO 偏好对齐**：见 `README_TRAINING.md` 第五节，把 `self_distillation.py`
  的输出和当时的本地模型自己的回答配成 chosen/rejected 对。
- **自动化定时任务**：现在提炼/探测/训练都需要你手动触发，可以用 cron /
  Windows 计划任务定期跑 `distill_training_corpus.py --dry-run` 检查数据量，
  攒够了发通知提醒你。
- **regression_score.py 的漂移打分**目前用的是 `core/embeddings.py` 里的
  本地 embedding（可能是哈希向量，精度有限）。如果你已经配置了真实的
  `bge-small-zh-v1.5` 模型，这个漂移打分的可信度会明显提升。
