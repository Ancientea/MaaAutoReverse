import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from maa.custom_action import CustomAction
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit
from maa.controller import (
    AdbController,
    Win32Controller,
    MaaWin32ScreencapMethodEnum,
    MaaWin32InputMethodEnum,
)

from .engine import AutoReverseConfig, AutoReverseEngine
from .strategy import RecognizedCard


@dataclass
class _RuntimeState:
    engine: Optional[AutoReverseEngine] = None
    pending_pipeline_override: Optional[Dict[str, Any]] = None
    scan_event: Optional[threading.Event] = None
    scan_cards: List[RecognizedCard] = field(default_factory=list)
    scan_debug: Dict[str, Any] = field(default_factory=dict)


_RESOURCE = Resource()
_RUNTIME = _RuntimeState()
_RUNTIME_LOCK = threading.RLock()


@_RESOURCE.custom_action("AutoReverseTick")
class AutoReverseTickAction(CustomAction):
    def run(self, context, argv):
        del argv
        with _RUNTIME_LOCK:
            engine = _RUNTIME.engine
            override = _RUNTIME.pending_pipeline_override
            _RUNTIME.pending_pipeline_override = None

        if override:
            context.override_pipeline(override)

        if engine is None:
            return False

        return engine.tick(context)


@_RESOURCE.custom_action("AutoReverseScanOnce")
class AutoReverseScanOnceAction(CustomAction):
    def run(self, context, argv):
        del argv
        with _RUNTIME_LOCK:
            engine = _RUNTIME.engine
            scan_event = _RUNTIME.scan_event

        cards: List[RecognizedCard] = []
        debug: Dict[str, Any] = {}
        if engine is not None:
            result = engine.scan_once_debug(context)
            cards = list(result.get("cards", []))
            debug = dict(result.get("debug", {}))

        with _RUNTIME_LOCK:
            _RUNTIME.scan_cards = cards
            _RUNTIME.scan_debug = debug
            if scan_event is not None:
                scan_event.set()

        return False


class MaaAutoReverseRunner:
    def __init__(self, logger=print):
        self.log = logger
        self.tasker: Optional[Tasker] = None
        self.controller = None
        self._task_job = None

    @property
    def running(self) -> bool:
        return bool(self.tasker and self.tasker.running)

    @staticmethod
    def _build_controller(controller_type: str, window_title: str = ""):
        if controller_type == "adb":
            devices = Toolkit.find_adb_devices()
            if not devices:
                raise RuntimeError("No ADB device found")
            device = devices[0]
            return AdbController(
                adb_path=device.adb_path,
                address=device.address,
                screencap_methods=device.screencap_methods,
                input_methods=device.input_methods,
                config=device.config,
            )

        windows = Toolkit.find_desktop_windows()
        if not windows:
            raise RuntimeError("No desktop window found")

        selected = windows[0]
        if window_title:
            for win in windows:
                if window_title in win.window_name:
                    selected = win
                    break

        # Use positional handle argument for compatibility across maa Python package versions.
        return Win32Controller(
            selected.hwnd,
            screencap_method=MaaWin32ScreencapMethodEnum.FramePool,
            mouse_method=MaaWin32InputMethodEnum.Seize,
            keyboard_method=MaaWin32InputMethodEnum.Seize,
        )

    def start(
        self,
        config: AutoReverseConfig,
        controller_type: str = "win32",
        window_title: str = "",
        bundle_path: str = "resource/autoreverse_bundle",
        pipeline_override: Optional[Dict[str, Any]] = None,
    ):
        if self.running:
            return

        Toolkit.init_option(str(Path.cwd()))

        engine = AutoReverseEngine(config=config, logger=self.log)
        engine.initialize()

        self.controller = self._build_controller(controller_type, window_title)
        self.controller.post_connection().wait()

        bundle = Path(bundle_path).resolve()
        if not bundle.exists():
            raise FileNotFoundError(f"Bundle path not found: {bundle}")


        if not _RESOURCE.post_bundle(str(bundle)).wait().succeeded:
            raise RuntimeError("Failed to load bundle")

        tasker = Tasker()
        if not tasker.bind(_RESOURCE, self.controller):
            raise RuntimeError("Failed to bind resource/controller")
        if not tasker.inited:
            raise RuntimeError("Tasker init failed")

        with _RUNTIME_LOCK:
            _RUNTIME.engine = engine
            _RUNTIME.pending_pipeline_override = pipeline_override

        self.tasker = tasker
        self._task_job = tasker.post_task("AutoReverseEntry", pipeline_override or {})
        self.log("[AutoReverse] runner started")

    def stop(self):
        if not self.tasker:
            return

        if self.tasker.running:
            self.tasker.post_stop().wait()

        with _RUNTIME_LOCK:
            _RUNTIME.engine = None
            _RUNTIME.pending_pipeline_override = None

        self.tasker = None
        self.controller = None
        self._task_job = None
        self.log("[AutoReverse] runner stopped")

    def update_config(self, new_config: AutoReverseConfig):
        with _RUNTIME_LOCK:
            if _RUNTIME.engine is not None:
                _RUNTIME.engine.update_config(new_config)

    def update_pipeline_override(self, pipeline_override: Dict[str, Any]):
        with _RUNTIME_LOCK:
            _RUNTIME.pending_pipeline_override = pipeline_override

        if self._task_job:
            self._task_job.override_pipeline(pipeline_override)

    def watch_pipeline_override_file(self, override_path: str, interval: float = 1.0):
        path = Path(override_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"override file not found: {path}")

        def _watch():
            last_mtime = 0.0
            while self.running:
                try:
                    mtime = path.stat().st_mtime
                    if mtime > last_mtime:
                        last_mtime = mtime
                        data = json.loads(path.read_text(encoding="utf-8"))
                        self.update_pipeline_override(data)
                        self.log(f"[AutoReverse] pipeline override reloaded: {path}")
                except Exception as exc:
                    self.log(f"[AutoReverse] override reload failed: {exc}")
                time.sleep(interval)

        thread = threading.Thread(target=_watch, daemon=True)
        thread.start()
        return thread

    def scan_once(
        self,
        config: AutoReverseConfig,
        controller_type: str = "win32",
        window_title: str = "",
        bundle_path: str = "resource/autoreverse_bundle",
        timeout: float = 6.0,
    ) -> List[RecognizedCard]:
        """启动一次临时任务，执行单次识别并返回识别到的卡片列表。"""
        result = self.scan_once_debug(
            config=config,
            controller_type=controller_type,
            window_title=window_title,
            bundle_path=bundle_path,
            timeout=timeout,
        )
        return list(result.get("cards", []))

    def scan_once_debug(
        self,
        config: AutoReverseConfig,
        controller_type: str = "win32",
        window_title: str = "",
        bundle_path: str = "resource/autoreverse_bundle",
        timeout: float = 6.0,
    ) -> Dict[str, Any]:
        """启动一次临时任务，返回 cards + 整图/ROI 调试数据。"""
        if self.running:
            raise RuntimeError("runner is running")

        Toolkit.init_option(str(Path.cwd()))
        engine = AutoReverseEngine(config=config, logger=self.log)
        engine.initialize()

        controller = self._build_controller(controller_type, window_title)
        controller.post_connection().wait()

        bundle = Path(bundle_path).resolve()
        if not bundle.exists():
            raise FileNotFoundError(f"Bundle path not found: {bundle}")
        if not _RESOURCE.post_bundle(str(bundle)).wait().succeeded:
            raise RuntimeError("Failed to load bundle")

        tasker = Tasker()
        if not tasker.bind(_RESOURCE, controller):
            raise RuntimeError("Failed to bind resource/controller")
        if not tasker.inited:
            raise RuntimeError("Tasker init failed")

        scan_event = threading.Event()
        with _RUNTIME_LOCK:
            _RUNTIME.engine = engine
            _RUNTIME.pending_pipeline_override = None
            _RUNTIME.scan_event = scan_event
            _RUNTIME.scan_cards = []
            _RUNTIME.scan_debug = {}

        try:
            tasker.post_task("AutoReverseScanEntry", {})
            scan_event.wait(timeout=max(0.5, timeout))
            with _RUNTIME_LOCK:
                return {
                    "cards": list(_RUNTIME.scan_cards or []),
                    "debug": dict(_RUNTIME.scan_debug or {}),
                }
        finally:
            if tasker.running:
                tasker.post_stop().wait()
            with _RUNTIME_LOCK:
                _RUNTIME.engine = None
                _RUNTIME.pending_pipeline_override = None
                _RUNTIME.scan_event = None
                _RUNTIME.scan_cards = []
                _RUNTIME.scan_debug = {}

