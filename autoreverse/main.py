import argparse
import json
import time
from pathlib import Path
from typing import Optional

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

try:
    from .engine import AutoReverseConfig, AutoReverseEngine
except ImportError:
    from engine import AutoReverseConfig, AutoReverseEngine


resource = Resource()
_ENGINE: Optional[AutoReverseEngine] = None


@resource.custom_action("AutoReverseTick")
class AutoReverseTickAction(CustomAction):
    def run(self, context, argv):
        del argv
        if _ENGINE is None:
            return False
        return _ENGINE.tick(context)


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

    return Win32Controller(
        selected.hwnd,
        screencap_method=MaaWin32ScreencapMethodEnum.FramePool,
        mouse_method=MaaWin32InputMethodEnum.Seize,
        keyboard_method=MaaWin32InputMethodEnum.Seize,
    )


def run(args):
    global _ENGINE

    Toolkit.init_option(str(Path.cwd()))

    config_path = Path(args.config).resolve()
    bundle_path = Path(args.bundle).resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    if not bundle_path.exists():
        raise FileNotFoundError(f"Bundle path not found: {bundle_path}")


    cfg = AutoReverseConfig.from_json(config_path)
    _ENGINE = AutoReverseEngine(cfg)
    _ENGINE.initialize()

    controller = _build_controller(args.controller, args.window_title)
    controller.post_connection().wait()

    if not resource.post_bundle(str(bundle_path)).wait().succeeded:
        raise RuntimeError("Failed to load bundle")

    tasker = Tasker()
    if not tasker.bind(resource, controller):
        raise RuntimeError("Failed to bind resource/controller")

    if not tasker.inited:
        raise RuntimeError("Tasker init failed")

    override = {}
    if args.pipeline_override:
        override_path = Path(args.pipeline_override).resolve()
        override = json.loads(override_path.read_text(encoding="utf-8"))

    tasker.post_task("AutoReverseEntry", override)
    print("AutoReverse started. Press Ctrl+C to stop.")

    try:
        while tasker.running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Stopping...")
        tasker.post_stop().wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AutoReverse on MaaFramework")
    parser.add_argument(
        "--controller",
        choices=["win32", "adb"],
        default="win32",
        help="Controller backend",
    )
    parser.add_argument(
        "--window-title",
        default="",
        help="Window title keyword for Win32 controller",
    )
    parser.add_argument(
        "--bundle",
        default="resource/autoreverse_bundle",
        help="Bundle path that contains pipeline/",
    )
    parser.add_argument(
        "--config",
        default="autoreverse/config.default.json",
        help="AutoReverse config JSON path",
    )
    parser.add_argument(
        "--pipeline-override",
        default="",
        help="Optional JSON file for pipeline override",
    )

    run(parser.parse_args())
