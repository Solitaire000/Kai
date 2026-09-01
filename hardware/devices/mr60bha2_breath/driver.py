"""
hardware/devices/mr60bha2_breath/driver.py
=============================================
Seeed MR60BHA2 60GHz毫米波呼吸心率传感器 + 板载LED 的驱动。

架构上刻意不在PC端重新实现雷达模块本身的私有二进制协议——那个协议闭源
（Seeed官方wiki原话：雷达模块的固件和算法不开源），PC端也没必要重新造轮子。
真正"读雷达"的是烧录在ESP32上的固件（见 firmware/kai_mr60bha2_bridge/），
固件用官方 Seeed_Arduino_mmWave 库和雷达模块通信，解析出在场状态/呼吸率/
心率后，重新编码成一行行JSON，通过USB虚拟串口发给PC。PC这一侧（也就是本
文件）只需要认识 hardware/README.md 里定义的那份通用JSON信封协议
（"kai-hw/1"），完全不需要认识任何厂商的私有协议——这也是"以后再接入其它
硬件"时的关键：只要新固件也讲这份JSON协议，这个文件的结构可以原样复制给
新设备当模板，core/hardware_manager.py 和 serial_transport.py 都不用改。

这块板子同时带一个可控LED（板载/外接NeoPixel）。**LED怎么亮、什么时候亮，
固件本身不做任何决策**——固件只负责"收到一条set_led指令就照做"，具体要不要
点灯、点什么颜色，是Kai（模型）通过调用 set_led 工具自己决定的。这是本次
接入LED控制时刻意坚持的原则，完整理由见 docs/HARDWARE_ARCHITECTURE.md。
"""
import json
import time

from hardware.base_device import HardwareDevice
from hardware.serial_transport import SerialLineReader

# 多久没收到新一帧presence=true的数据，就认为"有人在场"这件事已经在记忆里
# 记过了，不用每隔0.5秒收到一帧就往episodic表里塞一遍——那样一天下来能把
# 记忆刷屏。见 _maybe_emit_event()。
_PRESENCE_EVENT_MIN_INTERVAL_SEC = 600  # 10分钟
# 超过这么久没收到任何新数据帧，即使串口连接本身没断，也认为"数据是不新鲜的"
# （比如固件卡死但串口连接没掉），execute()里会用这个直接告诉模型"数据可能过期了"
_STALE_DATA_SEC = 10
_VALID_LED_PATTERNS = {"solid", "blink", "breathe", "off"}


class Driver(HardwareDevice):
    def __init__(self, manifest, dev_cfg, base_dir, on_event=None):
        super().__init__(manifest, dev_cfg, base_dir, on_event)
        self._state = {
            "presence": None,
            "breath_rate_per_min": None,
            "heart_rate_bpm": None,
            "distance_cm": None,
            "last_frame_ts": None,
        }
        self._last_presence = None
        self._last_event_ts = 0.0
        self._last_led_command = None  # 记录最近一次成功发出的LED指令，供preview/排查用
        self._transport = None

    # ---------------- 生命周期 ----------------
    def start(self):
        self._transport = SerialLineReader(
            vid=self.dev_cfg.get("vid", self.manifest.get("vid")),
            pid=self.dev_cfg.get("pid", self.manifest.get("pid")),
            baud=self.dev_cfg.get("baud", self.manifest.get("baud", 115200)),
            port_hint=self.dev_cfg.get("port"),  # config.yaml手动指定port时优先用它
            on_line=self._on_line,
            name="mr60bha2",
        )
        self._transport.start()  # 非阻塞

    def stop(self):
        if self._transport:
            self._transport.stop()

    def is_connected(self) -> bool:
        return bool(self._transport and self._transport.is_connected())

    # ---------------- 数据解析（后台线程里被调用） ----------------
    def _on_line(self, line: str):
        try:
            frame = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return  # 固件启动时打印的调试信息/乱码，直接丢弃，不影响后续帧
        if frame.get("schema") != "kai-hw/1" or frame.get("device") != "mr60bha2":
            return
        frame_type = frame.get("type")
        if frame_type == "vitals":
            self._handle_vitals(frame.get("data", {}))
        # type=="hello"/"ack" 目前只做日志用途，不需要更新状态，忽略即可

    def _handle_vitals(self, data: dict):
        # 固件里 breath_rate/heart_rate 在还没确认官方API之前，先用 -1 占位
        # 上报"这次没有有效数据"（不是真的测到负数）。这里统一转成 None，
        # 这样 execute() 返回给模型的是"这个字段暂时没有数据"而不是一个
        # 会被误当成真实读数的 -1.0。等固件那边接上真实API、不再发-1之后，
        # 这段兜底逻辑不需要跟着改——正常正数值不受影响。
        def _clean(v):
            return None if (v is None or v < 0) else v

        with self._lock:
            self._state.update({
                "presence": data.get("presence"),
                "breath_rate_per_min": _clean(data.get("breath_rate")),
                "heart_rate_bpm": _clean(data.get("heart_rate")),
                "distance_cm": _clean(data.get("distance_cm")),
                "last_frame_ts": time.time(),
            })
            snapshot = dict(self._state)
        self._maybe_emit_event(snapshot)

    def _maybe_emit_event(self, state: dict):
        """
        把"观测到的事实"写进记忆，不做任何"该不该提醒/报警/点灯"的判断——这一步
        只负责让 Kai 在下一次对话时能看到这个观测（core/memory.py 的
        recent_episodic() 每轮都会被读进 system prompt），具体要不要提、
        怎么提、要不要顺便调用 set_led 工具点个灯提示，全部交给模型自己在
        对话时结合上下文推理决定。这里刻意没有写任何"if 心率 > 阈值"或者
        "presence变化就自动点灯"这类硬编码规则——这正是需求里"体现agent的
        智能性而不是简单条件判断"的具体落地方式，完整说明见
        docs/HARDWARE_ARCHITECTURE.md。
        """
        if self.on_event is None:
            return
        presence = state.get("presence")
        now = time.time()
        presence_changed = presence != self._last_presence
        due_for_periodic_update = bool(
            presence and now - self._last_event_ts > _PRESENCE_EVENT_MIN_INTERVAL_SEC
        )
        if not (presence_changed or due_for_periodic_update):
            return
        self._last_presence = presence
        self._last_event_ts = now

        if presence:
            br = state.get("breath_rate_per_min")
            hr = state.get("heart_rate_bpm")
            extra = []
            if br:
                extra.append(f"呼吸率约{br:.1f}次/分")
            if hr:
                extra.append(f"心率约{hr:.1f}次/分")
            suffix = ("，" + "，".join(extra)) if extra else ""
            text = f"[硬件观测·mr60bha2] 检测到有人进入毫米波雷达检测范围{suffix}。"
        else:
            text = "[硬件观测·mr60bha2] 毫米波雷达检测范围内已无人。"
        self.on_event(text)

    # ---------------- 通用工具注册表接口 ----------------
    def tool_names(self):
        return {"read_vital_signs", "set_led"}

    def to_openai_tools(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_vital_signs",
                    "description": (
                        "读取毫米波雷达传感器(MR60BHA2)当前测到的呼吸率、心率和在场状态。"
                        "这是一个纯读取型传感器，不会对用户的电脑或身体做任何操作，"
                        "随时可以调用查看当前生理体征数据。适合在用户提到身体状态、"
                        "疲惫、心悸、睡眠这类话题时，或者用户主动问'我现在状态怎么样'"
                        "'帮我看看有没有人在'这类问题时调用；也可以结合刚才的"
                        "[硬件观测]记忆里提到的情况，主动核实一下最新数据。"
                    ),
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "set_led",
                    "description": (
                        "控制这块传感器板子上的一颗RGB LED灯——颜色、亮度、闪烁模式"
                        "完全由你决定，没有预设的'什么状态就该用什么颜色'的规则，"
                        "这是你可以自由发挥、用灯光向用户传达信息的一个通道。适合在"
                        "你判断值得给用户一点视觉反馈的时候用，比如任务完成、检测到"
                        "有人进入/离开、或者单纯响应用户'把灯调成蓝色'这类直接请求。"
                        "duration_ms 设置成大于0会在这么久之后自动熄灭，适合做"
                        "'提示一下就好，不用一直亮着'这种场景；设成0则一直保持"
                        "直到你下次再调用这个工具改变它。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "r": {"type": "integer", "minimum": 0, "maximum": 255, "description": "红色分量"},
                            "g": {"type": "integer", "minimum": 0, "maximum": 255, "description": "绿色分量"},
                            "b": {"type": "integer", "minimum": 0, "maximum": 255, "description": "蓝色分量"},
                            "brightness": {"type": "integer", "minimum": 0, "maximum": 255,
                                           "description": "整体亮度缩放，不填默认128（半亮）"},
                            "pattern": {"type": "string", "enum": sorted(_VALID_LED_PATTERNS),
                                        "description": "solid=常亮 blink=闪烁 breathe=呼吸灯渐亮渐暗 off=关灯，不填默认solid"},
                            "duration_ms": {"type": "integer", "minimum": 0,
                                             "description": "持续这么久后自动熄灭，0=一直保持（默认0）"},
                        },
                        "required": ["r", "g", "b"],
                    },
                },
            },
        ]

    def is_dangerous(self, name: str) -> bool:
        # set_led只是控制一颗指示灯，纯视觉反馈，不涉及任何真实世界的破坏性
        # 后果，也很容易撤销（再发一条指令改回来/关掉即可），所以默认不需要
        # 用户确认，避免每次点个灯都要弹一次确认框、打断对话体验。如果你不
        # 认同这个判断（比如这颗灯接在什么更敏感的场合），把这里改成
        # `return name == "set_led"` 即可让它走确认流程。
        return False

    def preview(self, name: str, params: dict) -> str:
        if name == "set_led":
            return (f"设置LED为 rgb({params.get('r', 0)},{params.get('g', 0)},{params.get('b', 0)}) "
                    f"模式={params.get('pattern', 'solid')} "
                    f"持续{params.get('duration_ms', 0)}ms")
        return super().preview(name, params)

    def execute(self, name, params):
        if name == "set_led":
            return self._execute_set_led(params)
        return self._execute_read_vital_signs(params)

    def _execute_read_vital_signs(self, params):
        with self._lock:
            state = dict(self._state)

        if not self.is_connected():
            return {
                "ok": False,
                "error": (
                    "毫米波传感器当前未连接。请检查：① ESP32是否已经通过USB插好；"
                    "② 固件是否已经烧录（见 hardware/devices/mr60bha2_breath/README.md）；"
                    "③ 如果确认硬件没问题但还是连不上，去 config.yaml 的 "
                    "hardware.mr60bha2.port 手动填一下具体串口号（比如 COM5 或 "
                    "/dev/ttyACM0），不要依赖自动识别。"
                ),
            }

        last_ts = state.get("last_frame_ts")
        age = time.time() - last_ts if last_ts else None
        if age is None:
            return {"ok": False, "error": "串口已连接，但还没收到过任何数据帧，可能固件刚启动，稍等几秒再试"}
        if age > _STALE_DATA_SEC:
            return {
                "ok": False,
                "error": f"传感器串口已连接，但{age:.0f}秒没收到新数据帧了，"
                         f"数据可能不新鲜——雷达模块本身可能没响应，或者固件卡住了，"
                         f"建议拔插一下ESP32的USB",
            }

        return {
            "ok": True,
            "result": {
                "presence": state["presence"],
                "breath_rate_per_min": state["breath_rate_per_min"],
                "heart_rate_bpm": state["heart_rate_bpm"],
                "distance_cm": state["distance_cm"],
                "data_age_seconds": round(age, 1),
            },
        }

    def _execute_set_led(self, params):
        if not self.is_connected():
            return {"ok": False, "error": "设备当前未连接，没法控制LED（检查USB连接/串口配置）"}

        r = max(0, min(255, int(params.get("r", 0))))
        g = max(0, min(255, int(params.get("g", 0))))
        b = max(0, min(255, int(params.get("b", 0))))
        brightness = max(0, min(255, int(params.get("brightness", 128))))
        pattern = params.get("pattern", "solid")
        if pattern not in _VALID_LED_PATTERNS:
            return {"ok": False, "error": f"pattern 必须是 {sorted(_VALID_LED_PATTERNS)} 之一，收到的是: {pattern}"}
        duration_ms = max(0, int(params.get("duration_ms", 0)))

        command = {
            "schema": "kai-hw/1",
            "cmd": "set_led",
            "args": {"r": r, "g": g, "b": b, "brightness": brightness,
                      "pattern": pattern, "duration_ms": duration_ms},
        }
        sent = self._transport.send_line(json.dumps(command, ensure_ascii=False))
        if not sent:
            return {"ok": False, "error": "指令发送失败（串口写入异常，可能是设备刚好掉线）"}

        with self._lock:
            self._last_led_command = command["args"]

        return {
            "ok": True,
            "result": {
                "led": command["args"],
                "note": "指令已通过串口发出。固件不会回传逐帧确认，如果没起作用，"
                        "先确认硬件接线和固件是否已正确烧录。",
            },
        }

