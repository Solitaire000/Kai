# hardware/ —— 硬件接入层

这个目录是小K接入外部物理硬件（传感器/未来可能的执行器）的地方。设计目标
是"以后接入新硬件时，尽量不用改这个目录以外的代码"——完整架构说明见
[`docs/HARDWARE_ARCHITECTURE.md`](../docs/HARDWARE_ARCHITECTURE.md)，
这份文档只讲**接入规范本身**：新增一个设备需要放哪些文件、实现哪些接口。

## 目录结构

```
hardware/
├── README.md              # 本文件
├── base_device.py          # 所有设备驱动必须继承的基类（接口约定）
├── serial_transport.py      # USB转串口类硬件共用的连接层（端口发现+重连）
└── devices/
    └── <device_name>/
        ├── device.yaml       # 设备清单：name/连接方式/VID-PID/波特率等
        ├── driver.py          # 具体驱动，继承 base_device.HardwareDevice
        ├── README.md          # 这个设备的接线/烧录/排障指南
        └── firmware/           # 如果设备需要烧录固件（比如接ESP32），放这里
```

`core/hardware_manager.py` 启动时会自动扫描 `devices/` 下每个子目录，
只要同时存在 `device.yaml` 和 `driver.py` 就会尝试加载——不需要手动注册。

## 通用协议：USB串口设备统一讲同一份JSON

所有走 USB-串口连接的硬件（当前的例子是MR60BHA2，通过ESP32做桥接），固件
和PC之间的通信分两个方向，都是**一行一个JSON对象，换行分隔**：

### 设备 → PC（上报数据）

```json
{"schema": "kai-hw/1", "device": "mr60bha2", "seq": 1234, "ts_ms": 82931002, "type": "vitals", "data": {"...设备自己的具体字段..."}}
```

- `schema`: 固定 `"kai-hw/1"`，以后协议如果有不兼容改动会升到 `"kai-hw/2"`，
  PC端驱动可以按这个字段决定要不要处理。
- `device`: 设备名，要和 `device.yaml` 里的 `name` 一致。
- `type`: 帧类型。目前用到的：
  - `"hello"`: 开机握手帧，建议固件启动时发一次，PC端可选检查。
  - `"vitals"` / 或其它你自定义的类型名：实际数据帧，`data` 字段里放这个
    设备自己关心的具体字段，格式由设备驱动自己解析，PC端其它模块不关心。
  - `"ack"`: 对一条收到的PC指令的执行确认（可选但推荐），比如
    `{"schema":"kai-hw/1","device":"mr60bha2","type":"ack","cmd":"set_led","ok":true}`，
    driver.py 可以用来判断指令是否真的被执行了，而不是盲目假设发出去就成功。

### PC → 设备（下发指令，只有"可控制"的设备才需要这个方向）

```json
{"schema": "kai-hw/1", "cmd": "<命令名>", "args": {"...命令自己的具体参数..."}}
```

具体命令集由设备自己定义（写在对应设备的 `README.md` 里）。**这个方向的
存在不代表设备本身有智能决策能力**——固件收到指令只管照做，"什么时候该
发什么指令、发什么参数"这个判断永远在PC端的Kai那一层（`driver.py` 的
`execute()` 被调用，本质上是Kai自己决定要调用这个工具），固件端不应该
包含"看到传感器数据A就自动执行指令B"这类联动规则——那样会让"控制"这件事
的决策权从Kai身上转移到固件里，变成写死的自动化，而不是agent的智能判断。
完整的设计理由见 [`../docs/HARDWARE_ARCHITECTURE.md`](../docs/HARDWARE_ARCHITECTURE.md)。

**为什么要有这一层统一信封，而不是直接让PC端解析每个设备自己的私有协议**：
大部分硬件模块本身的通信协议是厂商私有的（MR60BHA2雷达模块本身的协议就
是这样，Seeed官方wiki明确写了不开源）。把"讲私有协议"这件事下放给贴身
的固件去做，PC端只需要认识一份自己定义、跨设备通用的JSON格式——这样
`hardware_manager.py`、`serial_transport.py` 完全不用管某个具体设备内部
是怎么通信的，新增设备时这两个文件不需要改一行。

## 新增一个硬件设备的步骤

1. `hardware/devices/<你的设备名>/` 下新建 `device.yaml`：
   ```yaml
   name: my_device
   description: "一句话说明这是什么设备"
   connection: usb-serial      # 目前只支持这一种，以后可能加 bluetooth/网络等
   vid: 0x1234                 # USB转串口芯片的VID，用于自动识别端口
   pid: 0x5678
   baud: 115200
   category: sensor            # 随便起一个分类名，仅用于展示分组
   ```
2. 同目录下写 `driver.py`，继承 `hardware.base_device.HardwareDevice`，
   实现 `tool_names()` / `to_openai_tools()` / `execute()` / `start()`
   （参考 `devices/mr60bha2_breath/driver.py`，结构可以直接照抄）。
   USB串口类设备直接复用 `hardware.serial_transport.SerialLineReader`
   处理连接，自己只需要写"收到一行JSON该怎么解析、怎么更新内存状态"。
3. 如果需要烧录固件（比如同样接在ESP32上），固件放
   `devices/<你的设备名>/firmware/`，按上面「通用协议」的JSON信封格式往
   PC发数据。
4. 写这个设备自己的 `README.md`（接线图、烧录步骤、排障提示，参考
   `devices/mr60bha2_breath/README.md`）。
5. 完事——不需要改 `core/hardware_manager.py`，重启小K会自动发现并加载。

## 关于"危险"操作

`HardwareDevice.is_dangerous(name)` 默认返回 `False`（纯读取型传感器/查询
类工具不需要用户确认）。如果以后的硬件带执行器、会真正对物理世界做动作
（比如控制一个继电器/舵机），驱动里应该把对应工具的 `is_dangerous()` 覆盖
成 `True`，并实现 `preview(name, params)` 返回一段给用户看的确认文案——
这会复用和 `skills/` 里"危险技能"完全一样的确认流程（`core/agent.py` 统一
处理，不需要在硬件这一层自己实现确认弹窗逻辑）。

## 工具名不能和别的工具撞车

每个设备声明的工具名（`tool_names()`）最终会和 `skills/` 目录下的技能名、
`consult_subagent` 放进同一个命名空间。`core/agent.py` 构造时会把
subagent + 全部硬件设备的工具名并集，作为保留名单传给 `SkillsManager`，
如果某个 `skills/` 下的技能刚好撞名会被跳过并报警告——但硬件设备之间、
硬件和 `consult_subagent` 之间目前没有自动冲突检测，起名字时自己注意避开
`consult_subagent` 和其它已有硬件设备的工具名即可。
