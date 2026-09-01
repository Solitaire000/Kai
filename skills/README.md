# 怎么给小K加一个新技能（拓展接口）

不用改 `core/` 或 `agents/` 下任何代码。新建一个文件夹，放两个文件，重启小K即可自动生效。

（"技能(skill)"和小K另一种能调用的工具——子agent咨询——有本质区别，
看不看得懂这个区别决定了要不要用这套接口来实现你想加的东西，
见 [`docs/TOOLS_VS_SKILLS.md`](../docs/TOOLS_VS_SKILLS.md)）

## 1. 新建文件夹
```
skills/my_new_skill/
├── skill.yaml     # 元数据 + 参数schema（模型看到的"这个工具是干什么的"）
└── handler.py     # 实际执行逻辑
```

## 2. `skill.yaml` 模板
```yaml
name: my_new_skill              # 唯一id，模型调用时用这个名字。
                                 # 注意：不能叫 consult_subagent（内置工具保留名，
                                 # 撞名会被直接跳过加载并在启动日志里报警告，
                                 # 见 core/skills_manager.py::RESERVED_TOOL_NAMES
                                 # 和 docs/TOOLS_VS_SKILLS.md）
description: "一句话说清楚这个技能是干什么的、什么时候该用它——这段话直接决定模型会不会正确调用它，写清楚。"
category: general                # 随便分类，目前只用于UI展示分组
dangerous: false                  # true=会修改/执行东西，默认需要用户手动确认才会真正执行
parameters:                       # JSON Schema，定义模型调用时要传哪些参数
  type: object
  properties:
    some_arg:
      type: string
      description: "这个参数是干什么的"
  required: ["some_arg"]
preview_template: "对some_arg做点什么: {some_arg}"   # 弹确认框时给用户看的一句话预览
```

## 3. `handler.py` 模板
```python
def run(params: dict, ctx) -> dict:
    """
    params: 模型传进来的参数，已经按 skill.yaml 里的 parameters 校验过大致结构
    ctx:    SkillContext 对象，提供：
            - ctx.resolve_path(path)  把相对路径转成沙盒内的绝对路径（文件类技能用）
            - ctx.workspace_root      沙盒根目录
            - ctx.base_dir            项目根目录
            - ctx.cfg                 config.yaml 里 skills: 那一整段配置
    返回值: 一个可以被 json.dumps 的 dict，会被塞回给模型当"工具执行结果"
    """
    return {"ok": True, "message": f"处理了 {params.get('some_arg')}"}
```

## 4. 权限模型（务必了解）
- `dangerous: false` 的技能（只读，比如查时间、读文件、列目录）：模型可以直接调用，
  不会打断对话。
- `dangerous: true` 的技能（写文件、执行命令、打开程序）：模型只能"提议"调用，
  真正执行前会在CLI里问 `是否同意执行: xxx？(y/n)`，或者在网页版弹出确认卡片，
  用户点"同意"才会真正跑。**这一层是硬性的，不受prompt影响**——即使有人在对话里
  诱导模型说"忽略确认直接执行"，服务端依然会强制走确认流程（除非你自己在
  config.yaml 里把 `skills.auto_confirm` 设成 true，那是你自己的选择，不受此保护）。
- 所有文件类技能默认被限制在 `data/workspace/` 目录内（`config.yaml` 里
  `skills.workspace_root` 可改），不能跳出这个目录读写文件，除非显式打开
  `skills.allow_full_disk_access`。

## 5. 调试一个新技能
CLI里可以直接测试，不用等模型主动调用：
```
/skills                  # 列出当前一切可调用工具（技能 + 子agent咨询），
                          # 自己的技能会带 [技能] 前缀
```
如果技能没出现在列表里，检查：
- `skill.yaml`/`handler.py` 文件名是否拼对
- `config.yaml` 里 `skills.enabled` 是不是 true
- `handler.py` 里是不是真的有一个叫 `run` 的函数
- `name` 有没有不小心和保留名 `consult_subagent` 撞车
- 看启动时的日志输出，加载失败会打印具体原因
