"""
hardware/serial_transport.py
===============================
所有"USB转串口"类硬件驱动共用的连接层：按 VID/PID 自动找端口（或用户在
config.yaml 里手动指定的端口号）、起一个后台线程持续读取一行行文本、
掉线自动重连（带退避）。每个具体设备驱动（hardware/devices/<name>/driver.py）
只需要关心"收到一行文本该怎么解析"，不需要重复写端口发现/重连这些样板代码
——这是"以后再接入其它硬件"时最大程度复用代码的地方。

**非阻塞是这里最重要的设计约束**：start() 必须立刻返回，真正的串口连接、
读取、重连全部在后台 daemon 线程里做，且任何异常都在线程内部捕获、不会
抛到调用者。这样即使硬件从来没连上（比如用户还没买这个模块、或者ESP32
还没插上USB），也完全不影响 KaiAgent 的正常启动，更不会阻塞网页版的
聊天请求线程——网页请求线程自始至终只读驱动内存里缓存的"最新状态"
（一个被 threading.Lock 保护的 dict），从不直接等待/操作串口本身。
"""
import threading
import time
import logging

logger = logging.getLogger("kai.hardware")

try:
    import serial
    import serial.tools.list_ports
    _HAS_PYSERIAL = True
except ImportError:
    _HAS_PYSERIAL = False


def pyserial_available() -> bool:
    return _HAS_PYSERIAL


def find_port(vid: int = None, pid: int = None, port_hint: str = None) -> str:
    """
    找到要连接的串口设备名（比如 Windows 上的 "COM5"，Linux 上的
    "/dev/ttyACM0"）。优先级：
    1. port_hint（用户在 config.yaml 里手动指定的端口）—— 自动识别不一定
       100%准确（不同批次/驱动下 VID/PID 可能有出入），手动指定永远是最
       可靠的兜底方案。
    2. 按 vid/pid 在当前所有已连接的串口设备里匹配。
    找不到返回 None，调用方（SerialLineReader）会隔一段时间自动重试，
    不会抛异常。
    """
    if port_hint:
        return port_hint
    if not _HAS_PYSERIAL:
        return None
    for p in serial.tools.list_ports.comports():
        if vid is not None and p.vid != vid:
            continue
        if pid is not None and p.pid != pid:
            continue
        return p.device
    return None


class SerialLineReader:
    """
    见文件头说明。用法：

        reader = SerialLineReader(vid=0x303A, pid=0x1001, baud=115200,
                                   on_line=self._on_line, name="mr60bha2")
        reader.start()   # 立刻返回，不阻塞
        ...
        reader.is_connected()   # 随时查当前是否真的连着
        reader.send_line('{"schema":"kai-hw/1","cmd":"set_led","args":{...}}')
                                 # 往设备发一行指令（PC->设备方向，比如控制LED）
        reader.stop()           # 程序退出时清理
    """

    def __init__(self, vid, pid, baud, on_line, port_hint: str = None,
                 reconnect_interval: float = 5.0, name: str = "device"):
        self.vid = vid
        self.pid = pid
        self.baud = baud
        self.on_line = on_line
        self.port_hint = port_hint
        self.reconnect_interval = reconnect_interval
        self.name = name
        self._ser = None
        self._write_lock = threading.Lock()  # 读线程和"发指令"这个调用方是两个不同线程，
                                               # 串口对象本身不是天然线程安全的，写之前上锁
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._thread = None

    def is_connected(self) -> bool:
        return self._connected.is_set()

    def send_line(self, text: str) -> bool:
        """
        往设备发一行文本指令（自动补换行）。非阻塞地失败：没连接/写入异常都只是
        返回 False，不抛异常——调用方（driver.py）应该把 False 当成"这次指令
        没发出去"处理，而不是让整个请求线程跟着崩。
        """
        if not self.is_connected() or self._ser is None:
            return False
        try:
            with self._write_lock:
                self._ser.write((text.rstrip("\n") + "\n").encode("utf-8"))
            return True
        except Exception as e:
            logger.warning(f"[{self.name}] 发送指令失败: {e}")
            return False

    def start(self):
        if not _HAS_PYSERIAL:
            logger.warning(
                f"[{self.name}] 未安装 pyserial，这个硬件设备暂时不可用。"
                f"运行 `pip install pyserial` 后重启小K即可。"
            )
            return
        logger.warning(
                f"[{self.port_hint},{self.vid},{self.vid}] 查看配置"
            )
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"hw-{self.name}")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass

    def _run(self):
        while not self._stop.is_set():
            port = find_port(self.vid, self.pid, self.port_hint)
            if not port:
                self._connected.clear()
                time.sleep(self.reconnect_interval)
                continue
            try:
                self._ser = serial.Serial(port, self.baud, timeout=1)
                self._connected.set()
                logger.info(f"[{self.name}] 已连接: {port}")
                while not self._stop.is_set():
                    line = self._ser.readline()
                    if not line:
                        continue  # readline超时(timeout=1)会返回空bytes，正常现象，继续等
                    try:
                        text = line.decode("utf-8", errors="ignore").strip()
                    except Exception:
                        continue
                    if text:
                        self.on_line(text)
            except Exception as e:
                logger.warning(
                    f"[{self.name}] 串口连接断开或出错: {e}，"
                    f"{self.reconnect_interval}秒后自动重试"
                )
            finally:
                self._connected.clear()
                if self._ser is not None:
                    try:
                        self._ser.close()
                    except Exception:
                        pass
                    self._ser = None
                if not self._stop.is_set():
                    time.sleep(self.reconnect_interval)
