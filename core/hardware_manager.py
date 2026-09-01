"""
core/hardware_manager.py
===========================
硬件设备的统一管理层，职责和 SkillsManager/SubAgentManager 对等：发现、
加载、生命周期管理、对外暴露和另外两者字段结构一致的工具注册表接口
（tool_names/is_dangerous/preview/execute/list_for_ui），这样 core/agent.py
可以用一份统一的注册表分发全部工具调用，不需要为硬件再加一个if分支。

完整架构说明见 docs/HARDWARE_ARCHITECTURE.md。
"""
import os
import logging
import importlib.util

import yaml

logger = logging.getLogger("kai.hardware")


class HardwareManager:
    def __init__(self, config: dict, base_dir: str, on_event=None):
        self.base_dir = base_dir
        self.cfg = config.get("hardware", {}) or {}
        self.devices_dir = os.path.join(base_dir, "hardware", "devices")
        self.on_event = on_event
        self._drivers = {}      # device_name -> HardwareDevice实例
        self._tool_owner = {}   # tool_name -> device_name
        if self.cfg.get("enabled", False):
            self._discover_and_start()

    # ---------------- 发现 & 启动 ----------------
    def _discover_and_start(self):
        if not os.path.isdir(self.devices_dir):
            return
        enabled_list = self.cfg.get("enabled_devices")  # None = 全部启用

        for entry in sorted(os.listdir(self.devices_dir)):
            folder = os.path.join(self.devices_dir, entry)
            manifest_path = os.path.join(folder, "device.yaml")
            driver_path = os.path.join(folder, "driver.py")
            if not (os.path.isfile(manifest_path) and os.path.isfile(driver_path)):
                continue
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = yaml.safe_load(f) or {}
                name = manifest.get("name", entry)

                if enabled_list is not None and name not in enabled_list:
                    continue
                dev_cfg = self.cfg.get(name, {}) or {}
                if dev_cfg.get("enabled") is False:
                    continue

                spec = importlib.util.spec_from_file_location(f"kai_hw_{name}", driver_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                driver_cls = getattr(module, "Driver", None)
                if driver_cls is None:
                    logger.warning(f"硬件设备 {entry} 的 driver.py 里没有 Driver 类，跳过加载")
                    continue

                driver = driver_cls(manifest, dev_cfg, self.base_dir, on_event=self.on_event)
                self._drivers[name] = driver
                for tool_name in driver.tool_names():
                    if tool_name in self._tool_owner:
                        logger.warning(
                            f"硬件设备 {name} 声明的工具名「{tool_name}」和设备 "
                            f"{self._tool_owner[tool_name]} 撞车，后加载的会覆盖前面的——"
                            f"请去两边的 driver.py 改成不同的工具名"
                        )
                    self._tool_owner[tool_name] = name

                driver.start()  # 非阻塞：内部起后台线程去连硬件，连不上/找不到端口
                                 # 也不会抛异常到这里，见 hardware/base_device.py 说明
                logger.info(f"硬件设备 {name} 已加载（连接状态会在后台异步更新）")
            except Exception as e:
                logger.warning(f"加载硬件设备 {entry} 失败: {e}")

    # ---------------- 通用工具注册表接口（和 SkillsManager / SubAgentManager 对齐）----------------
    def tool_names(self) -> set:
        return set(self._tool_owner.keys())

    def is_dangerous(self, name: str) -> bool:
        driver = self._driver_for(name)
        return driver.is_dangerous(name) if driver else False

    def auto_confirm_enabled(self) -> bool:
        return bool(self.cfg.get("auto_confirm"))

    def preview(self, name: str, params: dict) -> str:
        driver = self._driver_for(name)
        return driver.preview(name, params) if driver else f"未知硬件工具: {name}"

    def execute(self, name: str, params: dict) -> dict:
        driver = self._driver_for(name)
        if driver is None:
            return {"ok": False, "error": f"硬件工具 {name} 不存在或未加载"}
        return driver.execute(name, params)

    # ---------------- 给 core/agent.py 组装 tools=[...] 用 ----------------
    def to_openai_tools(self) -> list:
        tools = []
        for driver in self._drivers.values():
            tools.extend(driver.to_openai_tools())
        return tools

    # ---------------- 给 UI 用：和 SkillsManager.list_skills() /
    # SubAgentManager.list_for_ui() 保持同样的字段结构 ----------------
    def list_for_ui(self) -> list:
        items = []
        for driver in self._drivers.values():
            items.extend(driver.list_for_ui())
        return items

    def _driver_for(self, tool_name: str):
        device_name = self._tool_owner.get(tool_name)
        return self._drivers.get(device_name) if device_name else None

    def close(self):
        for driver in self._drivers.values():
            try:
                driver.stop()
            except Exception:
                pass
