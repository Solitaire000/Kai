# 设计文档：子agent"总览+咨询+共同进化"架构

对应需求：Kai 始终总览一切，子agent只是被咨询、被搭配使用的能力，而且子agent
要跟着 Kai 主人格一起被训练迭代，不是"调用一次就丢"的一次性工具。

---

## 一、设计决策总览

| 决策点 | 选择 | 为什么 |
|---|---|---|
| 子agent怎么被使用 | 注册成一个 tool（`consult_subagent`），由 Kai 自己的模型决定要不要调用 | 保证"总览"：用户全程只跟Kai对话，子agent的产出先经过Kai消化 |
| 子agent的"专精"体现在哪 | `system_prompt` + 允许调用的 skills 范围，**不是**换模型 | 模型层面只做"要不要更强推理"（`model_complex`）和"要不要多模态"（`required_capability`）这两个维度的差异化，其余全部收敛到同一个 `model_router`，保证身份和训练数据的一致性 |
| 子agent用什么模型 | 默认和Kai共享同一个 `model_router`；只用`complex`标志做强弱区分，不绑定固定模型名 | 这是"共同进化"成立的**前提条件**——只有共享同一套权重，子agent才可能真的跟着训练一起变强；换了不同模型，子agent的输出根本没法蒸馏进同一个LoRA |
| 子agent的产出怎么沉淀 | 打上 `agent=<name>` 标签写进 `training_samples.db`，走和Kai主人格完全一样的蒸馏规则 | 复用现有 `training_logger.py` 的"只收在线教师、非降级"规则，不用另起一套 |
| 子agent的身份怎么防止被冲淡 | 新增 `memory/identity/subagents/<name>.jsonl`，每次训练强制混入 | 和主`identity_anchors`同样的道理：不能指望"聊得够多就不会忘"，得强制锚定。这两类身份锚定语料统一算作"记忆资产"的一部分，完整清单见 [`docs/MEMORY_MODEL.md`](MEMORY_MODEL.md) |
| 换base model时子agent怎么办 | `migrate/self_distillation.py --include-subagents`（或 `--subagents 名单` 只挑一部分）：额外用每个子agent的人设把它`probe_categories`里的分类再探测一遍 | 主动补上"子agent从没被聊到过但确实该会"的盲区，和Kai主人格的换模型流程完全对齐。`migrate/migrate_base_model.py --step distill-old` 默认就会自动带上这个选项，不需要单独手动调用 |
| 怎么知道子agent是不是真的在"进化" | `corpus_builder.py` 输出 `composition["by_agent"]`，逐版本可比对 | 让"子agent持续没被咨询过"这种情况变得可见、可追溯，而不是悄悄被遗忘 |

一句话总结这套设计的核心：**子agent和Kai主人格永远共享同一个LoRA adapter、同一个版本号**。不存在"子agent单独训练"这回事——它们的差异只体现在 system_prompt、身份锚定语料、探测题库这三处，训练本身永远是"全部一起，一次训完"。这是回答"子agent能不能跟着一起进化"最根本的答案：能，因为它们从一开始就没被当成独立的东西。

---

## 二、涉及文件清单

### 核心实现

| 文件 | 作用 |
|---|---|
| `core/subagent_manager.py` | 把子agent注册成`consult_subagent`工具；执行咨询；按现有蒸馏规则记录训练样本 |
| `memory/identity/subagents/life.jsonl` | LifeAgent专属身份锚定 |
| `memory/identity/subagents/schedule.jsonl` | ScheduleAgent专属身份锚定 |
| `memory/identity/subagents/research.jsonl` | ResearchAgent专属身份锚定（含学术诚信边界样例） |
| `memory/identity/subagents/work.jsonl` | WorkAgent专属身份锚定（含代码类安全边界样例） |

### 配合这套架构的其它文件

| 文件 | 相关内容 |
|---|---|
| `agents/base_agent.py` | `SubAgent`基类字段：`model_complex`、`required_capability`、`identity_anchors_path`、`probe_categories`，及`get_identity_anchors_path()` |
| `agents/specialized_agents.py` | 每个子agent的`model_complex`/`probe_categories`；`route_to_agent()`（兼容包装，见下）；`suggest_subagents()`、`KAI_CORE_PERSONA` |
| `core/agent.py` | 不在轮次开始整体切换人设；`consult_subagent`注册为tool；`_run_tool_loop`识别并分发这个tool；`chat()`记录`consulted_agents` |
| `core/corpus_builder.py` | `load_subagent_identity_anchors()`；`assemble_training_corpus()`合并子agent身份锚定，产出`composition["by_agent"]` |
| `train/train_lora.py` | `run_eval()`结果携带`agent`字段 |
| `data/probes/probe_set.yaml` | 部分分类加`applies_to_agent`注释（文档性，标注对应哪个子agent） |
| `migrate/self_distillation.py` | `--include-subagents`/`--subagents`：对每个（或指定）子agent按其`probe_categories`用子agent人设再探测一遍，输出打`agent`标签；`--list-agents`列出所有子agent |
| `migrate/migrate_base_model.py` | `distill-old`步骤默认带上`--include-subagents`；`train-and-check`步骤打印`by_agent`分布；同样支持`--subagents`/`--list-agents` |
| `data/eval/eval_set.jsonl` | 2条子agent专属回归用例（work/research 的安全边界），带`agent`+`system`字段 |
| `migrate/regression_score.py` | 硬性检查失败时标注是哪个agent出的问题 |

---

## 三、核心变化：从"整体换人设"到"总览+咨询"

### 改之前

```python
sub_agent = route_to_agent(user_input)          # 关键词命中就整体换人设
messages = self._build_messages(user_input, sub_agent)
result = self._run_tool_loop(...)
# 这一整轮，"Kai"事实上不存在——存在的是"这一轮临时变成的XX子agent"
```

### 改之后

```python
messages = self._build_messages(user_input)      # 永远是Kai自己的核心人格起手
tools = skills_tools + [subagent_manager.to_openai_tool()]
result = self._run_tool_loop(messages, ..., tools)
# Kai自己判断要不要调用 consult_subagent("work", "帮我写个求和函数")
# 子agent的回复作为tool_result塞回Kai的上下文，Kai自己组织最终回复
# 用户全程只看到Kai说的话，从没直接看到子agent的原始输出
```

`route_to_agent()`函数还保留着（避免有其它地方直接引用报错），但语义变了：现在只是`suggest_subagents()`的一个兼容包装，不再被`core/agent.py`用来整体换人设。

---

## 四、核心变化：训练管线怎么"看见"子agent

这是回答"共同进化"的关键部分，涉及三个环节的配合：

**1. 日常使用阶段（`core/subagent_manager.py`）**

```python
# Kai调用 consult_subagent("research", "...") 时：
sample_id = self.training_logger.log_sample(
    agent=agent_name,          # 打上"research"标签，不是"kai"
    source=resp.get("source"), # 复用和主人格完全一样的"只收在线教师"规则
    ...
)
```

和Kai自己主对话产生的样本一样，落进同一张`training_samples`表，只是`agent`字段不同。`migrate/distill_training_corpus.py`本来就按`agent`分组处理，不用改。

**2. 换base model前的主动补盲（`migrate/self_distillation.py --include-subagents`）**

```python
for sub in target_agents:      # 默认是全部子agent，--subagents 可以只选一部分
    sub_probes = [题库里属于 sub.probe_categories 的题]
    探测结果打上 "agent": sub.name，写进 self_distillation.jsonl
```

**3. 组装训练语料时（`core/corpus_builder.py`）**

```python
merged = identity + subagent_identity + profile_samples + refined + self_distill + raw_samples
composition["by_agent"] = {按agent统计这次训练里各自贡献了多少条}
```

这六个来源共同构成的"记忆资产"完整分层见 [`docs/MEMORY_MODEL.md`](MEMORY_MODEL.md)。

`train_lora.py`会把`composition`整个写进`eval_report.json`和`registry.json`的`lineage`条目里——**这意味着每一个训练版本，你都能查到"这一版里，Kai主人格和每个子agent各自贡献了多少语料"**，跨版本一比对，就是子agent的成长曲线。`migrate/migrate_base_model.py`跑完训练会直接把这份分布打印出来，并提示"如果某个子agent持续是0，该给它多加探测题了"。

---

## 五、验证方式

建议按这个顺序验证一遍：
```bash
# 1. 正常聊几句，观察是不是全程都是"小K"在说话（不再有整段突然换语气的情况）
# 2. 问一句明显该转给子agent的问题，比如"帮我写个函数计算斐波那契数列"，
#    观察最终回复是不是Kai整合过的，而不是子agent的原始输出直接糊你脸上
python main.py   # 或你平时启动的方式

# 3. 攒够样本后跑一次训练，检查 eval_report.json 里的 corpus_composition.by_agent
python train/train_lora.py --include-used

# 4. 检查子agent的安全边界回归用例是否通过
python migrate/regression_score.py --version <最新版本号>
```

---

## 六、值得后续再做的事

- `consult_subagent`目前不支持子agent自己再调用底层skills（比如ResearchAgent想自己读一个工作区文件）。现在的实现里子agent只做纯文本分析，不接skills工具。如果需要，可以给`SubAgent`基类新加一个`allowed_skills`字段（`base_agent.py`目前**没有**预留这个字段，需要新增），`subagent_manager.execute()`里把对应的skills tools一起传给子agent自己的`router.chat()`调用。
- 子agent之间目前不能互相咨询（比如WorkAgent想问一下ResearchAgent），只有Kai能发起`consult_subagent`。如果以后需要多子agent协作，可以考虑把`consult_subagent`也开放给子agent自己的调用上下文，但要小心控制递归深度，避免死循环。
- `required_capability`字段目前只是预留，`model_router`还没有真正按能力标签过滤provider——等你需要接多模态子agent（比如给ResearchAgent接视觉模型看实验图）时再实现。
