import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

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


@dataclass
class _RuntimeState:
    engine: Optional[AutoReverseEngine] = None
    pending_pipeline_override: Optional[Dict[str, Any]] = None


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

