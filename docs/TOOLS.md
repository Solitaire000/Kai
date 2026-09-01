# Tool 与 Skill 到底怎么区分

这份文档回答的问题：项目里"工具(tool)"和"技能(skill)"这两个词经常混着用，
代码里也确实存在没分清楚的地方——这里先给出清晰的概念定义，再列出具体在
哪些地方混淆了、会有什么后果，最后说明已经落地的修改。

---

## 一、概念定义（先把词理清楚）

- **Tool（工具）**：泛指一切最终会被塞进 `model_router.chat(..., tools=[...])`
  参数里、暴露给模型做 function-calling 的东西。这是 OpenAI 协议层的通用概念，
  不是本项目发明的。
- **Skill（技能）**：Tool 的**一种具体实现方式**——特指 `skills/` 目录下、按
  "`skill.yaml`（元数据+参数schema）+ `handler.py`（`run(params, ctx)`函数）"
  这个约定注册的插件，由 `core/skills_manager.py::SkillsManager` 统一管理：
  自动发现、危险标记（`dangerous`）、文件沙盒（`workspace_root`）、需要时
  弹出用户确认。**"Skill 是 Tool 的子集"，不是同义词。**
- **子agent咨询（`consult_subagent`）**：Tool 的**另一种具体实现方式**——由
  `core/subagent_manager.py::SubAgentManager` 管理，功能是把子任务转发给某个
  专精子agent（见 [`docs/SUBAGENT_COEVOLUTION.md`](SUBAGENT_COEVOLUTION.md)）。
  它**不是** skill：没有 `skill.yaml`、不在 `skills/` 目录下、不受
  `SkillsManager` 的沙盒/确认机制管理（原因见下面第三节）。
- **硬件工具**：Tool 的**第三种具体实现方式**——由
  `core/hardware_manager.py::HardwareManager` 管理，对应 `hardware/devices/`
  下接入的物理硬件设备（第一个例子：MR60BHA2毫米波传感器）。同样不是
  skill：不在 `skills/` 目录下，连接/读取硬件的逻辑跑在专门的后台线程里，
  和 skill 的文件沙盒/确认机制也不是一回事（除非某个硬件工具被显式标记
  `dangerous`，见 [`docs/HARDWARE_ARCHITECTURE.md`](HARDWARE_ARCHITECTURE.md)）。

一句话：**当前项目里"Tool"这个大类下，实际上并存三种起源、三种管理方式
不完全相同的具体实现**——这正是容易"分不清楚"的根源，不是命名习惯问题，
是架构上确实有三条并行的路径，且以后大概率还会有第四条（新硬件、新能力）。

```
                          tools=[...]  ← 最终传给模型的，就是这一份
                    ┌────────────────────────┬──────────────────────┐
                    │                          │                      │
        ┌───────────┴───────────┐  ┌───────────┴───────────┐  ┌───────┴───────────┐
        │   Skill（技能）         │  │  子agent咨询             │  │  硬件工具            │
        │   skills/ 目录约定      │  │  consult_subagent       │  │  hardware/devices/  │
        │   SkillsManager 管理    │  │  SubAgentManager 管理    │  │  HardwareManager管理 │
        │   有 dangerous/沙盒/确认 │  │  无 dangerous/沙盒概念    │  │  可选dangerous(预留) │
        └───────────────────────┘  └────────────────────────┘  └────────────────────┘
```

---

## 二、代码里实际存在的混淆点（改之前的状态）

### 1. 两条路径靠字符串硬编码分支区分，没有统一接口
`core/agent.py::_run_tool_loop` 里是这样分发工具调用的：

```python
if call["name"] == "consult_subagent":
    exec_result = self.subagents.execute(...)
    ...
    continue
if self.skills.is_dangerous(call["name"]) and not ...:
    ...
exec_result = self.skills.execute(call["name"], args)
```

`consult_subagent` 靠**名字字符串**特判，不是靠"这个 tool 属于哪个 manager"
这种结构化信息区分。这带来一个具体风险：**如果有人在 `skills/` 下新建一个
`skill.yaml` 把 `name` 写成 `consult_subagent`，`SkillsManager` 会正常把它
加载进去，但 `_run_tool_loop` 永远会先命中上面那个 `if` 分支，这个新技能
会被完全屏蔽、且没有任何报错提示**——这是一个真实存在、只是运气好还没被
触发的 bug。

### 2. 用户能看到的"技能列表"里看不到 consult_subagent
CLI 的 `/skills` 命令、网页版侧栏，原来都只调用
`agent.skills.list_skills()`——只展示 `skills/` 目录下的技能，`consult_subagent`
虽然同样出现在模型能调用的 `tools` 列表里，却完全不出现在这两个用户界面里。
用户只能靠读源码或者读 `docs/SUBAGENT_COEVOLUTION.md` 才知道有这么个工具存在。

### 3. system prompt 里对这两类工具的介绍是分裂的
`core/agent.py::_build_messages` 里塞给模型的说明分成两段、用了两套话术：

```python
system_prompt += "\n\n" + self.subagents.build_hint(user_input)     # 讲 consult_subagent
...
system_prompt += "\n\n【关于工具】你可以调用提供给你的工具(tools)..."   # 讲 skills
```

模型（以及读代码的人）不容易一眼看出这两段其实在描述"同一层机制"的两个实例。

### 4. 命名本身也有一点不一致
`SkillsManager.to_openai_tools()`（复数，返回列表）对应
`SubAgentManager.to_openai_tool()`（单数，返回一个dict）——因为 `consult_subagent`
设计成"一个万能工具 + `agent_name` 枚举参数"而不是"每个子agent一个工具"，这个
设计选择本身合理（模型选择负担更小），但命名上单复数不一致容易让人以为是
疏漏而不是有意为之，容易造成误解。

---

## 三、为什么不干脆把 consult_subagent 也做成一个 skill

这是看到上面的问题后，第一反应会问的问题——答案是：**不能简单合并，因为
两者的安全模型本质不同**：

- Skill 面对的是"操作用户电脑"这类有真实副作用的动作（写文件、执行命令），
  所以需要 `dangerous` 标记 + 文件沙盒 + 用户显式确认这一整套权限机制。
- `consult_subagent` 本质上是"再问一次模型，只是换了个 system_prompt"——它
  不直接读写用户的文件、不执行命令，产出只是一段文本，会先经过 Kai 自己
  消化才可能间接影响后续行为。套用 Skill 那套"文件沙盒+危险确认"机制对它
  没有意义，作为一个新技能塞进 `skills/` 目录反而会让路径解析、沙盒校验这些
  和"文件系统"强相关的逻辑莫名其妙地作用在一个根本不碰文件的东西上。

所以正确的修法不是"消灭 SubAgentManager 这条路径"，而是：**保留两条实现
路径（因为它们的安全需求确实不同），但补上一层统一的展示/防冲突机制**，
让"Tool"这个大类在用户可见、可校验的层面上是完整、一致的，即使底层实现
仍然分成两种。

---

## 四、已落地的修改

### 1. 保留名机制，防止 skill 静默覆盖内置工具（`core/skills_manager.py`）

```python
DEFAULT_RESERVED_TOOL_NAMES = {"consult_subagent"}   # 仅作为兜底默认值
```

`SkillsManager.__init__()` 现在接受一个 `reserved_names` 参数，`core/agent.py`
构造时会把 `SubAgentManager.tool_names()` 和 `HardwareManager.tool_names()`
的并集传进去——保留名单不再是写死的常量，而是"当前实际启用了哪些内置工具"
的动态并集，这样以后新增硬件设备、新增工具名，都会自动被纳入保留名单，
不需要去 `skills_manager.py` 里手动改代码。`SkillsManager._discover()` 加载
每个技能时，如果发现 `skill.yaml` 里的 `name` 撞上这个保留名单，**跳过加载
并打印醒目 warning**，而不是静默加载后被内置工具永久覆盖。

### 2. 统一的"当前一切可调用工具"视图（`core/agent.py`）

新增 `KaiAgent.list_tools()`：

```python
def list_tools(self) -> list:
    tools = [dict(s, kind="skill") for s in self.skills.list_skills()]
    tools += [dict(s, kind="subagent") for s in self.subagents.list_for_ui()]
    return tools
```

配合 `SubAgentManager` 新增的 `list_for_ui()`（返回和 `SkillsManager.list_skills()`
同样的字段结构：`name`/`description`/`dangerous`/`category`），两条路径的产出
在**展示层**被合并成一份结构一致的列表，每一项带 `kind` 字段（`"skill"` 或
`"subagent"`）区分底层来源。

### 3. CLI `/skills`、网页版侧栏、`/api/skills` 全部改用这份合并视图

- `main.py`：`/skills` 命令输出会给每一项加上 `[技能]`/`[子agent咨询]` 前缀。
- `web_app.py`：`/api/skills` 接口字段名保持 `skills` 不变（不破坏已有前端
  调用约定），但内容换成 `agent.list_tools()`。
- `web/static/app.js`：侧栏"已启用技能"列表里，`kind === "subagent"` 的条目
  会加上 `[子agent咨询]` 前缀，和普通技能视觉上能区分开。

### 4. 验证

新建一个 `name` 故意撞上 `consult_subagent` 的假技能，确认它会被跳过加载
并打印警告，而不是静默生效或者让程序崩溃（测试脚本见本次改动记录，未随
项目一起提交，是临时验证用）。`core/skills_manager.py`、
`core/subagent_manager.py`、`core/agent.py`、`main.py`、`web_app.py` 全部
通过语法检查。

### 5.（后续补充）system prompt 里也统一了两类工具的说明

第 1-4 点解决的是"用户能不能在 `/skills`、网页版侧栏里看到 consult_subagent"，
但还有一处更根本：**塞进模型自己看到的 system prompt 里的说明，之前也是
两段各说各话**——`SubAgentManager.build_hint()` 自己起了个【子agent】的框，
skills 那段又是另起的【关于工具】框，模型很难从文字上意识到这是"同一层
tools 概念下的两个类别"。现在改成 `KaiAgent._build_tools_explainer()` 统一
生成一段明确编号的说明（"第一类·技能"/"第二类·consult_subagent"），
`SubAgentManager.build_hint()` 只负责"这次要不要建议咨询、咨询谁"这个具体
判断，不再自己起框架性说明，避免两处话术不一致。

CLI `/skills` 和网页版侧栏也从"一份列表里给 consult_subagent 加前缀"改成
**真正分组显示**（"技能"和"子agent咨询"两个独立小节），视觉上不会让人
以为 consult_subagent 是 `skills/` 目录下的一个技能。

---

## 五、接入硬件层时，把"以后新增第三类工具"的建议真正落地了

前一版本文档在这里写的是"以后新增第三类工具时的约定"，是一份预先写好、
还没验证过的建议。接入 `hardware/` 这一层硬件工具时，正好是第一次真正
新增"既不适合做成 skill、也不是 consult_subagent"的第三类工具的机会，
所以顺手把当时的建议真正落地、验证了一遍：

1. **不再往 `_run_tool_loop` 加 `if` 分支**：`core/agent.py` 新增了
   `_tool_registry()`，构建一份 `{工具名: manager}` 的字典
   （`SkillsManager`/`SubAgentManager`/`HardwareManager` 三者都实现了
   `tool_names()`/`is_dangerous()`/`auto_confirm_enabled()`/`preview()`/
   `execute()` 这同一套接口）。`_run_tool_loop()` 用 `registry.get(name)`
   查出该找哪个manager执行，**接入硬件这个"第三类工具"时，`_run_tool_loop`
   一行代码都没改**——这正是当初这份建议想要达到的效果。
2. **`list_for_ui()` 结构对齐**：`HardwareManager.list_for_ui()` 返回和
   `SkillsManager.list_skills()`/`SubAgentManager.list_for_ui()` 同样的字段
   （`name`/`description`/`dangerous`/`category`，外加硬件特有的
   `connected` 字段），`KaiAgent.list_tools()` 把三者 merge 成一份列表，
   每项带 `kind` 字段（`"skill"`/`"subagent"`/`"hardware"`）。
3. **保留名单自动扩展**：见上面第四节第1点，`HardwareManager.tool_names()`
   自动被并入保留名单，不需要手动改 `skills_manager.py`。

完整的硬件架构设计（分层、非阻塞原则、智能性怎么落地、怎么继续加新硬件）
见 [`docs/HARDWARE_ARCHITECTURE.md`](HARDWARE_ARCHITECTURE.md)。

## 六、以后新增第四类工具时的约定

如果以后再要加一类新的、既不适合做成 skill、也不是"咨询子agent"/"硬件设备"
的工具，判断标准和第五节的经验完全一致：

1. 判断它有没有真实副作用（读写文件/执行命令/花钱调用外部API等）。**有**的话
   优先考虑直接做成一个 skill（`skills/` 下新建文件夹），复用现成的
   `dangerous`+确认机制，不要再造一个新的 manager。
2. 只有当它确实和 skill 的沙盒/确认模型不匹配时，才考虑新建一个独立的
   `XxxManager`，但**必须实现和 `SkillsManager`/`SubAgentManager`/
   `HardwareManager` 一致的接口**：`tool_names()`/`is_dangerous()`/
   `auto_confirm_enabled()`/`preview()`/`execute()`/`list_for_ui()`，
   这样才能直接塞进 `core/agent.py::_tool_registry()` 和 `list_tools()`，
   不需要改分发逻辑。
3. 不要再往 `core/agent.py::_run_tool_loop` 里加新的 `if call["name"] == "xxx"`
   硬编码分支——现在完全没有这种分支了，新工具一律走注册表分发。
