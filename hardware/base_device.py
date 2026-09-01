"""
hardware/base_device.py
==========================
所有硬件驱动（hardware/devices/<name>/driver.py）都必须继承这个基类，
实现同样一套接口——这样 core/hardware_manager.py 才能用统一的方式管理
任意数量、任意种类的硬件，不需要为每个新设备改管理层代码。

完整的架构说明（为什么这么分层、以后怎么接入新硬件）见
docs/HARDWARE_ARCHITECTURE.md 和同目录下的 README.md。
"""
import threading


class HardwareDevice:
    """
    子类必须实现：
    - tool_names() -> set[str]           这个设备对外暴露哪些工具名
    - to_openai_tools() -> list[dict]    对应的 OpenAI function-calling schema
    - execute(name, params) -> dict      真正执行；返回 {"ok": True, "result": ...}
                                          或 {"ok": False, "error": "..."}
    - start() -> None                    非阻塞！内部自己起后台线程做真正的硬件
                                          连接/轮询，不能阻塞调用者（不能阻塞
                                          KaiAgent的构造、更不能阻塞网页版的
                                          请求线程）

    子类可选覆盖（有默认实现）：
    - stop() -> None                     程序退出时清理，默认什么都不做
    - is_connected() -> bool             默认永远 True，纯软件类"硬件"可以不覆盖
    - is_dangerous(name) -> bool         默认 False（纯读取型传感器/查询类工具
                                          不需要用户确认）；会真正驱动硬件做动作
                                          的（比如控制继电器）应该覆盖成 True
    - preview(name, params) -> str       is_dangerous 返回 True 时，这段文字会
                                          展示给用户做确认提示
    - list_for_ui() -> list[dict]        默认基于 to_openai_tools() 自动生成，
                                          一般不需要覆盖

    带"控制"能力（不只是读取数据）的设备，execute() 内部通常需要往设备发一条
    指令（比如 USB串口设备用 hardware.serial_transport.SerialLineReader.send_line()），
    这属于驱动自己的实现细节，基类不强制要求任何特定的发送方式——只要
    execute() 最终返回符合约定的 {"ok":...} 结构即可。
    """

    def __init__(self, manifest: dict, dev_cfg: dict, base_dir: str, on_event=None):
        self.manifest = manifest
        self.dev_cfg = dev_cfg or {}
        self.base_dir = base_dir
        # on_event(text: str)：设备驱动观测到"值得记一笔"的事实时调用这个回调，
        # 把这句话写进 core/memory.py 的episodic记忆。注意这里只是"记录事实"，
        # 不是"决定要不要报警/提醒"——那部分判断留给 Kai 下次对话时自己的推理，
        # 详见 docs/HARDWARE_ARCHITECTURE.md 里"智能性体现在哪"这一节。
        self.on_event = on_event
        self._lock = threading.Lock()

    # ---- 子类必须实现 ----
    def tool_names(self) -> set:
        raise NotImplementedError

    def to_openai_tools(self) -> list:
        raise NotImplementedError

    def execute(self, name: str, params: dict) -> dict:
        raise NotImplementedError

    def start(self) -> None:
        raise NotImplementedError

    # ---- 子类可选覆盖 ----
    def stop(self) -> None:
        pass

    def is_connected(self) -> bool:
        return True

    def is_dangerous(self, name: str) -> bool:
        return False

    def preview(self, name: str, params: dict) -> str:
        return self.manifest.get("description", self.__class__.__name__)

    def list_for_ui(self) -> list:
        return [{
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "dangerous": self.is_dangerous(t["function"]["name"]),
            "category": "hardware",
            "connected": self.is_connected(),
        } for t in self.to_openai_tools()]
