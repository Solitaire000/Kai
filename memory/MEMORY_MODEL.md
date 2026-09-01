# 记忆模型总览：小K的"记忆"到底存在哪、怎么用

这份文档把之前分散在 `README.md`、`train/README_TRAINING.md`、
`train/README_INHERITANCE.md`、`docs/SUBAGENT_COEVOLUTION.md` 里的"记忆"相关
内容整理到一个地方——项目里其实有**两类完全不同、但经常被放在一起讨论的
"记忆"**，混着看容易搞混，这里明确分开、再说明它们怎么互相配合。

---

## 一、两类记忆，一张图看懂

```
┌─────────────────────────────┐        ┌──────────────────────────────────┐
│   A. 运行时记忆（现查现用）      │        │   B. 训练侧记忆资产（蒸馏进权重）        │
│   core/memory.py              │        │   core/corpus_builder.py 组装          │
│   ------------------------    │        │   ------------------------------      │
│   1. 画像记忆 profile          │        │   1. identity_anchors（主人格身份锚定） │
│   2. 事件记忆 episodic         │  ──▶   │   2. subagent_identity（子agent身份） │
│   3. 语义记忆 semantic         │ 定期蒸馏 │   3. profile_samples（画像现算现用） │
│                                │        │   4. refined_corpus（提炼语料）        │
│   存在 memory.db + 向量库        │        │   5. self_distillation（主动探测快照） │
│   不需要训练，改了立刻生效        │        │   6. raw_samples（原始蒸馏问答流水账） │
└─────────────────────────────┘        └──────────────────────────────────┘
        每轮对话都会读/写                      只有跑 train/train_lora.py 时才生效
```

**核心区别**：A 是"数据库里的事实"，任何 provider（在线/离线、换哪个模型）
都能直接读到，改了立刻生效，不需要训练；B 是"权重里学到的行为"，只有真正
跑一次 LoRA 训练才会体现出来，但优点是哪怕检索层的 prompt 格式跟新模型没对齐，
学到的语气/推理方式也不会丢。两者不是互相替代关系，是互补的两层保险
（这也是 `corpus_builder.py` 为什么要把 A 的"画像记忆"也现算现用地混进 B
里的原因——见下面第三节）。

**目录约定**：A、B 两层涉及的全部文件统一放在项目根目录下和 `data/` 并列的
`memory/` 文件夹里（`memory/memory.db`、`memory/vector_store/`、
`memory/identity/`、`memory/knowledge/`、`memory/training_samples.db`），
和 `data/` 里那些"跟记忆无关的资产"（离线模型权重 `data/models/`、LoRA adapter
产出 `data/adapters/`、技能沙盒 `data/workspace/`、探测题库 `data/probes/`、
回归评测集 `data/eval/`）分开存放，一眼就能看出哪些目录需要备份/随移动硬盘
一起走（`memory/`）、哪些是可以按需重新生成或下载的（`data/`）。

---

## 二、A. 运行时记忆（`core/memory.py`）

三层，全部是本地文件，不依赖任何模型厂商，换模型/断网都不影响：

| 层 | 存储位置 | 内容 | 典型操作 |
|---|---|---|---|
| 画像记忆 profile | SQLite `profile` 表（key-value） | 长期稳定的"关于你"的事实，比如专业方向、常用称呼 | `/remember 专业=RF探针视觉检测` |
| 事件记忆 episodic | SQLite `episodic` 表（按时间流水） | 逐条对话/事件记录 | 每轮对话自动写入 |
| 语义记忆 semantic | 本地向量库（`vectors.npy` + `meta.jsonl`） | "这件事和之前说的哪件事像"，用于跨会话检索相关上下文 | 对话时自动检索注入 |

存储路径由 `config.yaml` 的 `memory.db_path` / `memory.vector_db_path` 配置，
默认在 `memory/memory.db` 和 `memory/vector_store/`。CLI/网页版共用同一份，
线程安全（`core/memory.py` 内部有显式锁，网页版多线程环境也安全）。

**日常怎么用**：不用管，正常聊天自动积累；想显式记一件事用 `/remember`
（CLI）或网页版侧栏"让小K记住一件事"。

---

## 三、B. 训练侧记忆资产（`core/corpus_builder.py` 组装）

这层回答的问题是："哪天彻底换掉 base model / 换掉当前依赖的在线大模型，
之前积累的一切要怎么继续带着走？"——光靠 A 里的被动聊天记录是不够的，
很多知识/语气从来没被聊到过，换 base model 会悄无声息地丢掉（详见第四节）。

`core/corpus_builder.py` 在每次 `train/train_lora.py` 跑的时候，自动把下面
六个来源按优先级合并、去重，不需要手动合并文件：

| 优先级 | 来源 | 落地文件 | 产出方式 |
|---|---|---|---|
| 1（最高） | identity_anchors | `memory/identity/identity_anchors.jsonl` | 手写，人格与安全红线，每次训练强制混入 |
| 2 | subagent_identity | `memory/identity/subagents/<name>.jsonl` | 手写，每个子agent专属身份锚定，防止被主人格样本稀释 |
| 3 | profile_samples | 不落盘，来自 A 层的画像记忆 | 每次组装语料时现算现用，永远反映最新状态——**这是A、B两层唯一的直接交汇点** |
| 4 | refined_corpus | `memory/knowledge/refined_corpus.jsonl` | `migrate/distill_training_corpus.py` 定期把原始问答提炼成结构化知识点 |
| 5 | self_distillation | `memory/knowledge/self_distillation.jsonl` | `migrate/self_distillation.py`，换模型前主动探测旧大脑产出 |
| 6（最低） | raw_samples | `memory/training_samples.db` | 日常对话自动积累的原始问答流水账 |

去重规则：按 `(user_input, assistant_output)` 去重，保留优先级更高、先出现的
那一份——身份锚定类语料权重最高，不会被同义但表达略有差异的原始流水账
"稀释掉"。

`train_lora.py` 训练完会把这份合并统计（`composition`，含 `composition["by_agent"]`
逐子agent统计）写进 `eval_report.json` 和 `registry.json` 的 `lineage` 条目，
每个训练版本都能查到"这一版里各个来源各贡献了多少语料"。

---

## 四、为什么需要"主动探测"而不能只靠被动记忆

A、B 两层的六个来源里，前 4 个（1/2/3/4）本质上都是"你恰好用过/聊过/手写过"
的内容，天然有覆盖盲区：如果日常使用高度集中在几类任务上，模型在其它领域
的知识、推理习惯、说话风格，即使旧模型本身具备，也从来没被记录下来——换新
base model 重训时这部分会悄无声息地丢失。

第 5 个来源 `self_distillation` 就是为了补这个盲区：`migrate/self_distillation.py`
在换 base model / 换 provider 之前，用 `data/probes/probe_set.yaml` 题库
（题库本身是"探测工具的配置"，不是记忆产出，所以留在 `data/` 而不是 `memory/`）
**主动、系统性地"问一遍"旧大脑**，覆盖身份、推理、代码、说话风格、领域知识
等多个维度，把回答存下来当训练语料。这是整套"记忆资产"里，"继承旧模型全部
内容"最关键的一步——不做这一步，训练语料本质上只是"日常问过的那些问题"的
子集。完整操作流程见 [`migrate/README.md`](../migrate/README.md) 和
[`train/README_INHERITANCE.md`](../train/README_INHERITANCE.md)。

子agent的身份/能力同样存在这个盲区，所以 `self_distillation.py` 支持
`--include-subagents`（全部子agent）/ `--subagents 名单`（只挑一部分）/
`--list-agents`（查看有哪些子agent可选），机制和主人格完全对齐——详见
[`docs/SUBAGENT_COEVOLUTION.md`](SUBAGENT_COEVOLUTION.md)。

---

## 五、相关文档索引

- [`README.md`](../README.md) —— 项目整体使用说明，A层记忆的日常操作在第七节
- [`train/README_TRAINING.md`](../train/README_TRAINING.md) —— 训练流程与QLoRA配置
- [`train/README_INHERITANCE.md`](../train/README_INHERITANCE.md) —— B层六个来源的操作细节、换base model完整步骤
- [`migrate/README.md`](../migrate/README.md) —— `migrate/` 目录下四个脚本的用法
- [`docs/SUBAGENT_COEVOLUTION.md`](SUBAGENT_COEVOLUTION.md) —— 子agent身份/记忆怎么跟着主人格共同进化
