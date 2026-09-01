下面给出中文版使用说明，内容与前面的 run_migration.bat 参数化版本对应。可保存为项目根目录：

MIGRATION_GUIDE_CN.md
# 模型迁移控制面板使用说明

## 1. 功能概述

`run_migration.bat` 是模型迁移流程的统一控制入口，用于管理旧模型能力保存、知识蒸馏、训练数据优化、LoRA训练以及迁移后效果评估。

该脚本主要封装以下 Python 功能：

- 旧模型能力快照保存
- Self Distillation（自蒸馏）
- 历史训练语料优化
- Base Model迁移流程管理
- LoRA训练与回归验证
- 模型迁移质量评估

BAT 文件只负责参数输入和 Python 调用，不修改 Python 内部逻辑。

---

# 2. 文件结构要求

`run_migration.bat` 应放置在迁移工程根目录，与 `migrate` 文件夹同级。

推荐目录结构：


project_root
│
├── run_migration.bat
│
├── migrate
│ ├── migrate_base_model.py
│ ├── self_distillation.py
│ ├── distill_training_corpus.py
│ └── regression_score.py
│
├── config
│ └── config.yaml
│
├── memory
│ └── knowledge
│
└── train
└── train_lora.py


运行：


双击 run_migration.bat


或者命令行：


run_migration.bat


---

# 3. 启动菜单说明

启动后显示：

=====================================================
Model Migration Control

[1] List agents
[2] Self distillation
[3] Distill training corpus
[4] Base model migration pipeline
[5] Regression score
[0] Exit


对应功能：

|选项|功能|
|-|-|
|1|查看当前注册Agent|
|2|执行旧模型能力蒸馏|
|3|生成优化训练语料|
|4|执行Base Model迁移流程|
|5|执行迁移结果评分|
|0|退出程序|

---

# 4. 选项1：查看Agent列表

## 功能

查看当前系统支持的Agent。

调用：


python migrate\migrate_base_model.py --list-agents


用途：

- 确认Agent名称
- 查看可迁移对象
- 确认子Agent配置


示例：


research_agent

vision_agent

coding_agent


如果需要指定Agent进行数据蒸馏，应先执行此步骤。

---

# 5. 选项2：Self Distillation（旧模型能力保存）

## 功能

用于在更换Base Model之前，保存旧模型能力。

主要生成：

- 模型行为样本
- 能力快照
- 迁移参考数据


对应：


self_distillation.py


支持两种模式。

---

## 5.1 Provider模式

适用于：

- API模型
- 本地模型服务
- Router调用模型


选择：


Mode:
1


输入：


Snapshot label:
old_model_v1

Provider name:
local


等价命令：


python migrate\self_distillation.py ^
--provider local ^
--label old_model_v1



---

## 5.2 Adapter模式

适用于已有LoRA Adapter迁移。

需要输入：


Adapter path

Old base model


示例：


Adapter path:
models/adapter_v1

Old base model:
Qwen2.5-3B-Instruct


等价：


python migrate\self_distillation.py ^
--adapter-path models/adapter_v1 ^
--base-model Qwen2.5-3B-Instruct ^
--label old_model_v1


---

## 5.3 是否包含子Agent

程序会询问：


Include subagents?


选择：


Y


表示：

- 同时保存子Agent能力
- 扩展迁移覆盖范围


选择：


N


表示：

只处理主Agent。

---

# 6. 选项3：训练语料蒸馏

## 功能

将已有历史数据转换为更高质量训练数据。

调用：


distill_training_corpus.py



---

## Agent选择

输入：


Agent name(optional)


例如：


research_agent


表示：

只处理指定Agent。


---

## Batch Size

输入：


Batch size(default 20)


例如：


32


控制每次处理的数据量。

---

## Dry Run测试模式

询问：


Dry run?


选择：


Y


表示：

- 测试流程
- 不执行最终写入


用于首次运行检查。

---

## Provider

输入：


Provider(optional)


例如：


local


指定教师模型来源。

---

# 7. 选项4：Base Model迁移流程

## 功能

执行完整模型迁移管理。

支持：


distill-old
refine
train-and-check
all


---

# 7.1 distill-old

功能：

保存旧模型能力。

选择：


Step:
1



需要：


Snapshot label


例如：


before_migration



支持：

- Provider模式
- Adapter模式
- 子Agent保存


---

# 7.2 refine

功能：

生成优化后的训练语料。


执行：


python migrate\migrate_base_model.py --step refine



通常位于：

旧模型保存之后。

---

# 7.3 train-and-check

功能：

执行：

1. LoRA训练
2. 模型验证
3. 回归测试


可以选择：


Skip refine?


如果选择：


Y


表示：

跳过语料优化步骤。


---

# 7.4 all完整迁移流程

完整流程：


旧模型能力保存
|
↓
训练数据优化
|
↓
LoRA训练
|
↓
回归测试



输入：


Snapshot label:

Provider:


示例：


Snapshot label:
migration_v2

Provider:
local


---

# 8. 选项5：Regression Score

## 功能

执行迁移质量评估。

调用：


regression_score.py



需要输入：


Version



例如：


v2



可选：


Base model slug



例如：


Qwen2.5-3B



作用：

- 判断迁移后能力变化
- 检测性能下降
- 判断是否可以部署


---

# 9. 推荐迁移流程

标准迁移建议：


Step 1
|
|-- 查看Agent列表
|
v

Step 2
|
|-- 保存旧模型能力
|
v

Step 3
|
|-- 修改Base Model配置
|
v

Step 4
|
|-- 蒸馏训练语料
|
v

Step 5
|
|-- LoRA训练
|
v

Step 6
|
|-- Regression Score评估
|
v

Step 7
|
|-- 发布新模型


---

# 10. 常见问题

## 10.1 Python无法运行

错误：


python is not recognized



原因：

系统环境变量未配置Python。


解决：

确认：


python --version


可以正常执行。

---

## 10.2 找不到Python文件

错误：


migrate scripts not found



检查：


run_migration.bat


是否位于：


project_root


而不是：


project_root\migrate



---

## 10.3 模型路径错误

检查：

- Adapter路径
- Base Model路径
- 配置文件路径


确保模型已经存在。

BAT不会：

- 自动下载模型
- 自动修改路径
- 自动创建环境

---

# 11. 注意事项

1. 迁移前必须保存旧模型能力。

2. 不建议直接执行完整迁移流程，应先执行：
   

Option 1


确认Agent。

3. 第一次迁移建议：


Self Distillation
|
↓
Dry Run Corpus
|
↓
正式训练


4. Regression Score通过后再替换生产模型。

5. 保留历史snapshot，方便回滚。


---

# 12. 环境说明

该BAT不负责：

- Conda环境创建
- venv创建
- Python依赖安装
- CUDA配置
- 模型下载


运行前需要保证：


python
pip packages
model files
configuration files


均已准备完成。