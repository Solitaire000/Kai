# MR60BHA2 毫米波呼吸心率传感器 + LED 控制

Seeed Studio 60GHz毫米波雷达套件，非接触式测呼吸率、心率、在场状态；
同一块板子上还带一颗可由Kai自由控制颜色/模式的RGB LED。官方入门文档：
https://wiki.seeedstudio.com/cn/getting_started_with_mr60bha2_mmwave_kit/

这个文件夹是这个具体设备的"驱动包"，结构对应 [`../../README.md`](../../README.md)
里定义的通用硬件接入规范：

```
mr60bha2_breath/
├── device.yaml       # 设备清单（VID/PID、波特率等）
├── driver.py          # PC端Python驱动，实现 HardwareDevice 接口，暴露两个工具：
│                       #   read_vital_signs（读取）、set_led（控制）
├── firmware/
│   └── kai_mr60bha2_bridge/
│       └── kai_mr60bha2_bridge.ino   # 烧录到ESP32上的固件
└── README.md          # 本文件
```

**当前状态提醒**：呼吸率(`breath_rate`)/心率(`heart_rate`)对应的官方库API
方法名还没有核实过（现有的官方示例代码只确认了在场检测`isHumanDetected()`
和人员位置追踪的API，不是呼吸心率专用示例），固件里这两个字段目前先占位
发送`-1`（PC端会正确识别成"暂无数据"，不会报错，但也不会有真实读数）。
在场检测(`presence`)和LED控制这两部分是完整可用的。等确认了
`mmWaveBreath.ino`官方示例的方法名后，固件里标了`TODO`的那两行需要更新。

---

## 一、硬件准备

- Seeed Studio MR60BHA2 毫米波雷达模块
- XIAO ESP32C6（套件通常已经把雷达模块和这块主控板接好）
- 一颗 NeoPixel（WS2812）LED，接在 `D1` 引脚（板载或外接，取决于你的具体
  套件版本——固件里这个引脚是写死的常量，接线不同的话改
  `kai_mr60bha2_bridge.ino` 里的 `LED_PIN` 即可）
- USB-C 数据线（**要能传数据的线，不能是纯充电线**）

拓扑关系：
```
雷达模块 --(板载UART,套件已接好)--> XIAO ESP32C6 --(USB数据线)--> 运行小K的PC
                                        │
                                    D1引脚接LED
```

## 二、烧录固件

1. Arduino IDE 里，`文件 > 首选项`，附加开发板管理器网址里加上 ESP32 官方源
   （`https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`）。
2. `工具 > 开发板 > 开发板管理器`，搜索 `esp32` 装上（Espressif Systems 那个）。
3. `工具 > 开发板`，选择 `XIAO_ESP32C6`。
4. `项目 > 加载库 > 管理库`，依次搜索安装：
   - `Seeed_Arduino_mmWave`（官方雷达库）
   - `Adafruit NeoPixel`（LED库）
   - `ArduinoJson`（固件解析PC发来的LED指令用，选装最新的6.x或7.x都可以）
5. 打开 `firmware/kai_mr60bha2_bridge/kai_mr60bha2_bridge.ino`。
6. USB连接ESP32，选对串口号，点上传。
7. 上传完成后，`工具 > 串口监视器`，波特率选 115200，应该能看到类似这样的
   一行行输出（这就是 PC 端驱动要读的格式）：
   ```
   {"schema":"kai-hw/1","device":"mr60bha2","type":"hello","fw_version":"1.1.0"}
   {"schema":"kai-hw/1","device":"mr60bha2","seq":0,"ts_ms":3210,"type":"vitals","data":{"presence":false,"breath_rate":-1.0,"heart_rate":-1.0}}
   ```
   雷达前方站一个人，`presence` 应该变成 `true`（`breath_rate`/`heart_rate`
   目前会一直是`-1.0`，见上面"当前状态提醒"）。

   测试LED：串口监视器的发送框里输入下面这行（要选"没有行结束符"或者
   "换行符"，回车发送）：
   ```
   {"schema":"kai-hw/1","cmd":"set_led","args":{"r":0,"g":150,"b":255,"pattern":"breathe","duration_ms":5000}}
   ```
   LED应该开始呼吸灯效果，5秒后自动熄灭，同时串口监视器里应该能看到一条
   `"type":"ack"` 的确认帧。

**排查 `mmWave.update()` 一直拿不到数据**：官方wiki提到过，先确认雷达模块
本身的固件版本是不是最新——用 Seeed 官方提供的固件升级工具/流程升级一遍，
旧固件不支持部分数据字段。

## 三、PC端配置

关掉串口监视器（**串口同一时间只能被一个程序占用**，Arduino IDE 的串口监视器
开着的话，小K这边会连不上），然后：

1. 确认 `pip install -r requirements.txt` 已经装好（里面含 `pyserial`）。
2. `config/config.yaml` 里打开硬件总开关：
   ```yaml
   hardware:
     enabled: true
     # mr60bha2:
     #   port: "COM5"   # 自动识别失败时才需要手动填，见下面「自动识别失败怎么办」
   ```
3. 启动小K（CLI或网页版都行），`/skills`（CLI）或网页版侧栏应该能看到
   `read_vital_signs` 和 `set_led` 一起出现在"硬件"分组里，旁边会标注是否
   已连接。

## 四、自动识别失败怎么办

`device.yaml` 里预填的 VID `0x303A`、PID `0x1001` 是 XIAO ESP32C6 原生USB
的常见默认值，但不同批次/驱动环境下可能不完全一致。如果启动后一直显示
"未连接"：

1. 打开系统设备管理器（Windows）或 `ls /dev/tty*`（Mac/Linux），插拔一下
   ESP32，确认它出现的时候对应哪个端口号。
2. 在 `config.yaml` 里手动指定，比 VID/PID 自动识别更可靠：
   ```yaml
   hardware:
     enabled: true
     mr60bha2:
       port: "COM5"           # Windows示例
       # port: "/dev/ttyACM0"   # Linux示例
   ```
   手动指定的 `port` 优先级高于自动识别，配置了就不会再走VID/PID匹配。

## 五、怎么验证Kai真的能用上这个设备

**读取传感器**：聊天里问一句"帮我看看现在有没有人在监测范围内"，或者提到
"最近感觉有点累/心慌"这类话题，观察Kai是不是**自己判断**要不要调用
`read_vital_signs`——这是设计上刻意不做硬编码触发规则的地方，模型自己
决定什么时候查一下传感器，详见
[`docs/HARDWARE_ARCHITECTURE.md`](../../../docs/HARDWARE_ARCHITECTURE.md)。

**控制LED**：直接跟Kai说"把灯调成蓝色""闪烁一下红灯提醒我""任务做完了
点个绿灯"，观察Kai是不是自己组织了合理的 `r`/`g`/`b`/`pattern` 参数去调用
`set_led`——**没有任何预设的颜色对照表**，Kai需要自己把"蓝色"翻译成
`r=0,g=0,b=255`这样的参数，这个翻译过程本身就是模型能力的体现，不是
写死在代码里的映射表。

也可以直接进入检测范围站一会儿，几分钟后再问"你知道我刚才在干嘛吗"——
如果一切正常，Kai应该能从最近的记忆里看到"[硬件观测·mr60bha2] 检测到有人
进入…"这类记录，可能会主动提一句，也可能选择不提——都是正常的，取决于
当时对话的上下文。
