import os
import sys
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 当前文件位于 MaaAutoReverse 根目录。
repo_root = Path(__file__).resolve().parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

# 默认使用本目录下的 Maa 运行时二进制。
os.environ.setdefault("MAAFW_BINARY_PATH", str(repo_root / "runtime" / "bin"))

from autoreverse.engine import AutoReverseConfig
from autoreverse.strategy import RecognizedCard
from autoreverse.runner import MaaAutoReverseRunner


class AutoTrader:
    """兼容旧版 GUI 的适配层：在 Maa 运行器之上提供旧 AutoTrader 接口。"""

    def __init__(self, rois, ocr_manager, log_callback=None):
        del rois
        del ocr_manager
        self._log_callback = log_callback
        self.target_window_title = ""
        self.refresh_keep_mode = False
        self._runner = MaaAutoReverseRunner(logger=self.log)
        self._log_file = self._init_log_file()

        self.item_list: List[str] = []
        self.operator_list: List[str] = []
        self.buy_only_operator_list: List[str] = []
        self.six_star_list: List[str] = []
        self.ui_scale: str = "90%"

        self._runtime_options = self._load_runtime_options()
    @staticmethod
    def _init_log_file() -> Path:
        log_dir = repo_root / "debug"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / f"maa_autoreverse_{datetime.now().strftime('%Y%m%d')}.log"

    @staticmethod
    def _load_runtime_options() -> dict:
        cfg_path = repo_root / "autoreverse" / "config.default.json"
        defaults = {
            "ocr_correction_map": {"铜": "锏", "湖": "溯"},
            "change_threshold": 5.0,
            "shop_refresh_change_threshold": 8.0,
            "stable_threshold": 2.0,
            "stable_timeout": 2.0,
            "post_action_refresh_wait": 0.4,
            "sell_click_wait": 0.03,
            "ui_scale": "90%",
        }
        if not cfg_path.exists():
            return defaults

        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            return defaults

        opts = dict(defaults)
        opts["ocr_correction_map"] = data.get("ocr_correction_map", defaults["ocr_correction_map"])
        for key in [
            "change_threshold",
            "shop_refresh_change_threshold",
            "stable_threshold",
            "stable_timeout",
            "post_action_refresh_wait",
            "sell_click_wait",
        ]:
            if key in data:
                try:
                    opts[key] = float(data[key])
                except Exception:
                    pass
        opts["ui_scale"] = data.get("ui_scale", defaults["ui_scale"])
        return opts

    @property
    def running(self) -> bool:
        return self._runner.running

    def log(self, msg: str):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        print(line)
        try:
            with self._log_file.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
        if self._log_callback:
            self._log_callback(msg)

    def set_window(self, title: str):
        self.target_window_title = title

    def set_refresh_keep_mode(self, enabled: bool):
        self.refresh_keep_mode = bool(enabled)
        self.log(f"运行模式: {'刷新保留' if self.refresh_keep_mode else '自动倒转'}")
        if self.running:
            self._runner.update_config(self._build_config())

    def set_ui_scale(self, scale: str):
        if scale in ("90%", "100%"):
            self.ui_scale = scale
            self.log(f"设置 UI 比例为: {scale}")
            if self.running:
                self._runner.update_config(self._build_config())

    def update_lists(
        self,
        items: List[str],
        operators: List[str],
        six_stars: List[str],
        buy_only_operators: Optional[List[str]] = None,
    ):
        self.item_list = items or []
        self.operator_list = operators or []
        self.six_star_list = six_stars or []
        self.buy_only_operator_list = buy_only_operators or []

        self.log(
            "名单已更新: "
            f"道具[{len(self.item_list)}], 干员[{len(self.operator_list)}], "
            f"只买[{len(self.buy_only_operator_list)}], 六星[{len(self.six_star_list)}]"
        )

        if self.running:
            self._runner.update_config(self._build_config())

    def _build_config(self) -> AutoReverseConfig:
        self._runtime_options = self._load_runtime_options()
        return AutoReverseConfig(
            item_list=self.item_list,
            operator_list=self.operator_list,
            buy_only_operator_list=self.buy_only_operator_list,
            six_star_list=self.six_star_list,
            ocr_correction_map=self._runtime_options["ocr_correction_map"],
            change_threshold=self._runtime_options["change_threshold"],
            shop_refresh_change_threshold=self._runtime_options["shop_refresh_change_threshold"],
            stable_threshold=self._runtime_options["stable_threshold"],
            stable_timeout=self._runtime_options["stable_timeout"],
            post_action_refresh_wait=self._runtime_options["post_action_refresh_wait"],
            sell_click_wait=self._runtime_options["sell_click_wait"],
            refresh_keep_mode=self.refresh_keep_mode,
            ui_scale=self.ui_scale,
        )

    def start(self):
        if self.running:
            return


        self._runner.start(
            config=self._build_config(),
            controller_type="win32",
            window_title=self.target_window_title,
            bundle_path=str(repo_root / "resource" / "autoreverse_bundle"),
        )
        self.log("自动倒转已启动")

    def stop(self):
        self._runner.stop()
        self.log("自动倒转已停止")

    def scan_once(self, window_title: Optional[str] = None) -> List[RecognizedCard]:
        result = self.scan_once_debug(window_title)
        return list(result.get("cards", []))

    def scan_once_debug(self, window_title: Optional[str] = None) -> Dict[str, Any]:
        if self.running:
            raise RuntimeError("自动倒转运行中，请先停止后再测试扫描")

        title = (window_title or self.target_window_title or "").strip()
        if not title:
            raise ValueError("请先选择窗口")

        return self._runner.scan_once_debug(
            config=self._build_config(),
            controller_type="win32",
            window_title=title,
            bundle_path=str(repo_root / "resource" / "autoreverse_bundle"),
        )

