import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np
from maa.pipeline import JOCR, JRecognitionType

try:
    import keyboard as keyboard_lib

    _KEYBOARD_AVAILABLE = True
except Exception:
    keyboard_lib = None
    _KEYBOARD_AVAILABLE = False

try:
    import pydirectinput

    pydirectinput.PAUSE = 0.05
    _PYDIRECTINPUT_AVAILABLE = True
except Exception:
    pydirectinput = None
    _PYDIRECTINPUT_AVAILABLE = False

from .strategy import RecognizedCard, PlannedAction, plan_actions


Rect = Tuple[int, int, int, int]

ROI_TEMPLATES = {
    "90%": {
        "ROIS": [
            (0.9381, 0.7481, 0.0240, 0.0342),
            (0.8141, 0.7704, 0.0100, 0.0232),
            (0.6990, 0.7704, 0.0100, 0.0232),
            (0.5839, 0.7704, 0.0100, 0.0232),
            (0.4688, 0.7704, 0.0100, 0.0232),
            (0.3537, 0.7704, 0.0100, 0.0232),
            (0.2386, 0.7704, 0.0100, 0.0232),
            (0.7807, 0.9556, 0.0818, 0.0250),
            (0.6656, 0.9556, 0.0818, 0.0250),
            (0.5505, 0.9556, 0.0818, 0.0250),
            (0.4354, 0.9556, 0.0818, 0.0250),
            (0.3203, 0.9556, 0.0818, 0.0250),
            (0.2052, 0.9556, 0.0818, 0.0250),
        ],
        "MAX_CARD_ROI": (0.3625, 0.7037, 0.2740, 0.0435),
        "HAND_AREA_ROI": (0.1234, 0.5907, 0.6599, 0.1102),
        "SHOP_DISPLAY_ROI": (0.1901, 0.7685, 0.6844, 0.2204),
    },
    "100%": {
        "ROIS": [
            (0.9313, 0.7204, 0.0266, 0.0370),
            (0.7927, 0.7444, 0.0120, 0.0269),
            (0.6650, 0.7444, 0.0120, 0.0269),
            (0.5373, 0.7444, 0.0120, 0.0269),
            (0.4095, 0.7444, 0.0120, 0.0269),
            (0.2818, 0.7444, 0.0120, 0.0269),
            (0.1541, 0.7444, 0.0120, 0.0269),
            (0.7568, 0.9500, 0.0896, 0.0296),
            (0.6289, 0.9500, 0.0896, 0.0296),
            (0.5010, 0.9500, 0.0896, 0.0296),
            (0.3730, 0.9500, 0.0896, 0.0296),
            (0.2451, 0.9500, 0.0896, 0.0296),
            (0.1172, 0.9500, 0.0896, 0.0296),
        ],
        "MAX_CARD_ROI": (0.3460, 0.6687, 0.3073, 0.0514),
        "HAND_AREA_ROI": (0.1240, 0.5824, 0.6594, 0.0889),
        "SHOP_DISPLAY_ROI": (0.0995, 0.7435, 0.7599, 0.2444),
    }
}


@dataclass
class AutoReverseConfig:
    item_list: List[str] = field(default_factory=list)
    operator_list: List[str] = field(default_factory=list)
    buy_only_operator_list: List[str] = field(default_factory=list)
    six_star_list: List[str] = field(default_factory=list)
    ocr_correction_map: Dict[str, str] = field(default_factory=lambda: {"铜": "锏", "湖": "溯"})
    change_threshold: float = 5.0
    shop_refresh_change_threshold: float = 1.0
    stable_threshold: float = 2.0
    stable_timeout: float = 2.0
    post_action_refresh_wait: float = 3
    sell_click_wait: float = 0.03
    refresh_keep_mode: bool = False
    auto_reverse_auto_refresh: bool = False
    ui_scale: str = "90%"
    double_click_interval: float = 0.01
    stable_poll_interval: float = 0.1
    action_interval: float = 0.1

    @staticmethod
    def from_json(path: Path) -> "AutoReverseConfig":
        data = json.loads(path.read_text(encoding="utf-8"))
        return AutoReverseConfig(
            item_list=data.get("item_list", []),
            operator_list=data.get("operator_list", []),
            buy_only_operator_list=data.get("buy_only_operator_list", []),
            six_star_list=data.get("six_star_list", []),
            ocr_correction_map=data.get("ocr_correction_map", {"铜": "锏", "湖": "溯"}),
            change_threshold=float(data.get("change_threshold", 5.0)),
            shop_refresh_change_threshold=float(data.get("shop_refresh_change_threshold", 8.0)),
            stable_threshold=float(data.get("stable_threshold", 2.0)),
            stable_timeout=float(data.get("stable_timeout", 2.0)),
            post_action_refresh_wait=float(data.get("post_action_refresh_wait", 1)),
            sell_click_wait=float(data.get("sell_click_wait", 0.03)),
            refresh_keep_mode=bool(data.get("refresh_keep_mode", False)),
            auto_reverse_auto_refresh=bool(data.get("auto_reverse_auto_refresh", False)),
            ui_scale=data.get("ui_scale", "90%"),
            double_click_interval=float(data.get("double_click_interval", 0.01)),
            stable_poll_interval=float(data.get("stable_poll_interval", 0.1)),
            action_interval=float(data.get("action_interval", 0.1)),
        )


class ShopChangeDetector:
    @staticmethod
    def _split_into_six_regions(img: np.ndarray) -> List[np.ndarray]:
        h, w = img.shape[:2]
        if h == 0 or w == 0:
            return []

        region_w = w / 6.0
        regions: List[np.ndarray] = []
        for i in range(6):
            x1 = int(i * region_w)
            x2 = int((i + 1) * region_w) if i < 5 else w
            regions.append(img[:, x1:x2])
        return regions

    @staticmethod
    def has_image_changed(img1: np.ndarray, img2: np.ndarray, threshold: float = 5.0) -> bool:
        if img1 is None or img2 is None:
            return True
        if img1.shape != img2.shape:
            return True

        i1 = cv2.resize(img1, (64, 64))
        i2 = cv2.resize(img2, (64, 64))
        diff = cv2.absdiff(i1, i2)
        return float(np.mean(diff)) > threshold

    def wait_for_stability(
        self,
        capture_func: Callable[[], np.ndarray],
        timeout: float = 2.0,
        threshold: float = 2.0,
        poll_interval: float = 0.1,
    ) -> np.ndarray:
        """等待画面稳定：在超时内轮询截图，直到前后帧变化低于阈值。"""
        last = capture_func()
        start = time.time()

        while time.time() - start < timeout:
            time.sleep(poll_interval)  # 控制稳定性轮询频率，避免过于频繁截图占用性能
            curr = capture_func()
            if not self.has_image_changed(last, curr, threshold=threshold):
                return curr
            last = curr

        return last

    @staticmethod
    def is_shop_refreshed(
        img_before: np.ndarray,
        img_after: np.ndarray,
        excluded_region: Optional[int] = None,
        region_change_threshold: float = 5.0,
    ) -> bool:
        refreshed, _, _ = ShopChangeDetector.eval_shop_refresh(
            img_before,
            img_after,
            excluded_region=excluded_region,
            region_change_threshold=region_change_threshold,
        )
        return refreshed

    @staticmethod
    def eval_shop_refresh(
        img_before: np.ndarray,
        img_after: np.ndarray,
        excluded_region: Optional[int] = None,
        region_change_threshold: float = 5.0,
    ) -> Tuple[bool, int, int]:
        """评估商店是否刷新，返回 (是否刷新, 变化区域数, 参与判断区域数)。"""
        if img_before is None or img_after is None:
            return False, 0, 0

        i1 = cv2.resize(img_before, (240, 60))
        i2 = cv2.resize(img_after, (240, 60))
        r1 = ShopChangeDetector._split_into_six_regions(i1)
        r2 = ShopChangeDetector._split_into_six_regions(i2)
        if len(r1) != 6 or len(r2) != 6:
            return False, 0, 0

        changed_count = 0
        checked_count = 0
        for idx in range(6):
            if excluded_region is not None and idx == excluded_region:
                continue
            checked_count += 1
            if ShopChangeDetector.has_image_changed(r1[idx], r2[idx], threshold=region_change_threshold):
                changed_count += 1

        # 判定规则：非排除区域中至少 3 个区域变化明显，视为商店刷新。
        refreshed = checked_count > 0 and changed_count >= 3
        return refreshed, changed_count, checked_count


class PriceOCR:
    def __init__(self):
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def initialize(self):
        self._ready = True

    @staticmethod
    def preprocess_roi(img_bgr: np.ndarray, is_number: bool = False) -> np.ndarray:
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

        if is_number:
            scale = 3.0
            gray = cv2.resize(gray, (int(gray.shape[1] * scale), int(gray.shape[0] * scale)), interpolation=cv2.INTER_CUBIC)
            border = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
            if np.mean(border) < 100:
                gray = cv2.bitwise_not(gray)
            _, gray = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        else:
            scale = 2.0
            gray = cv2.resize(gray, (int(gray.shape[1] * scale), int(gray.shape[0] * scale)), interpolation=cv2.INTER_CUBIC)
            if np.mean(gray) < 100:
                gray = cv2.bitwise_not(gray)

        gray = cv2.copyMakeBorder(
            gray,
            10,
            10,
            10,
            10,
            cv2.BORDER_CONSTANT,
            value=(255, 255, 255),
        )
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    def run_ocr(self, context, img_bgr: np.ndarray, roi_idx: int) -> str:
        """使用 Maa OCR 识别指定 ROI，数字区域仅保留数字字符。"""
        if not self._ready or context is None:
            return ""
        is_number = roi_idx <= 6
        ocr_input = self.preprocess_roi(img_bgr, is_number=is_number)

        try:
            reco = context.run_recognition_direct(
                JRecognitionType.OCR,
                JOCR(only_rec=True),
                ocr_input,
            )
            if reco is None:
                return ""
            best = getattr(reco, "best_result", None)
            text = getattr(best, "text", "") if best else ""
            if not text and getattr(reco, "filtered_results", None):
                text = " ".join(
                    [getattr(item, "text", "") for item in reco.filtered_results if getattr(item, "text", "")]
                )

            if is_number:
                # 针对数字进行常见的 OCR 视觉纠错（防止价格 0 被识别成字母 O）
                correction = {
                    'O': '0', 'o': '0', 'Q': '0', 'D': '0',
                    'I': '1', 'l': '1', 'i': '1',
                    'Z': '2', 'z': '2',
                    'S': '5', 's': '5',
                    'B': '8',
                    'b': '6',
                    'g': '9', 'q': '9'
                }
                for k, v in correction.items():
                    text = text.replace(k, v)
                return "".join([c for c in text if c.isdigit()])

            return text.strip()
        except Exception:
            return ""


class AutoReverseEngine:
    def __init__(self, config: AutoReverseConfig, logger: Callable[[str], None] = print):
        self._cfg = config
        self._cfg_lock = threading.RLock()
        self.log = logger
        self.ocr = PriceOCR()
        self.detector = ShopChangeDetector()
        self.last_shop_img: Optional[np.ndarray] = None

    @staticmethod
    def _is_d_pressed() -> bool:
        if not _KEYBOARD_AVAILABLE:
            return False
        try:
            return bool(keyboard_lib.is_pressed("d"))
        except Exception:
            return False

    def _get_config(self) -> AutoReverseConfig:
        with self._cfg_lock:
            return self._cfg

    def update_config(self, new_config: AutoReverseConfig):
        with self._cfg_lock:
            self._cfg = new_config
        self.log("配置已更新")

    def initialize(self):
        self.ocr.initialize()
        self.log(f"OCR 就绪状态: {self.ocr.ready}")

    @staticmethod
    def _crop(img: np.ndarray, roi: Tuple[float, float, float, float]) -> np.ndarray:
        h, w = img.shape[:2]
        x, y, rw, rh = roi
        x1 = max(0, int(x * w))
        y1 = max(0, int(y * h))
        x2 = min(w, int((x + rw) * w))
        y2 = min(h, int((y + rh) * h))
        return img[y1:y2, x1:x2]

    @staticmethod
    def _center_of_roi(img: np.ndarray, roi: Tuple[float, float, float, float]) -> Tuple[int, int]:
        h, w = img.shape[:2]
        x, y, rw, rh = roi
        cx = int((x + rw / 2.0) * w)
        cy = int((y + rh / 2.0) * h)
        return cx, cy

    @staticmethod
    def _is_orange_red_color(bgr: Tuple[float, float, float], roi_bgr: Optional[np.ndarray] = None) -> bool:
        b, g, r = bgr
        pixel = np.uint8([[[b, g, r]]])
        h, s, v = cv2.cvtColor(pixel, cv2.COLOR_BGR2HSV)[0][0]
        is_orange = bool(5 <= h <= 25 and s > 140 and v > 140)
        if roi_bgr is None or roi_bgr.size == 0:
            return is_orange

        roi_h, roi_s, roi_v, _ = cv2.mean(cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV))
        is_red = bool((roi_h <= 10 or roi_h >= 170) and roi_s > 120 and roi_v > 120)
        return is_orange or is_red

    def _is_hand_full(self, img: np.ndarray) -> bool:
        max_card_roi = ROI_TEMPLATES[self._get_config().ui_scale]["MAX_CARD_ROI"]
        roi = self._crop(img, max_card_roi)
        if roi.size == 0:
            return False
        b, g, r, _ = cv2.mean(roi)
        return self._is_orange_red_color((b, g, r), roi)

    def _double_click(self, controller, x: int, y: int):
        controller.post_click(x, y).wait()
        time.sleep(self._get_config().double_click_interval)
        controller.post_click(x, y).wait()

    def _slot_roi(self, slot: int) -> Tuple[float, float, float, float]:
        return ROI_TEMPLATES[self._get_config().ui_scale]["ROIS"][slot]

    def _slot_text_roi(self, slot: int) -> Tuple[float, float, float, float]:
        return ROI_TEMPLATES[self._get_config().ui_scale]["ROIS"][slot + 6]

    def _shop_region_index_from_slot(self, slot: int) -> Optional[int]:
        if slot < 1 or slot > 6:
            return None

        # 将槽位编号映射到“从左到右”的 6 等分区域索引。
        rois = ROI_TEMPLATES[self._get_config().ui_scale]["ROIS"]
        ordered_slots = sorted(
            range(1, 7),
            key=lambda s: (rois[s][0] + rois[s][2] / 2.0, rois[s][1] + rois[s][3] / 2.0),
        )
        region_map = {s: idx for idx, s in enumerate(ordered_slots)}
        return region_map.get(slot)

    def _scan_cards_with_debug(self, frame_bgr: np.ndarray, context=None) -> Tuple[List[RecognizedCard], Dict[str, Any]]:
        """扫描 1-6 槽位，返回识别卡片与调试信息（整图+ROI+OCR）。"""
        debug: Dict[str, Any] = {
            "frame_bgr": frame_bgr.copy() if frame_bgr is not None else None,
            "slots": [],
        }
        if context is None or frame_bgr is None:
            return [], debug

        h, w = frame_bgr.shape[:2]
        if h == 0 or w == 0:
            return [], debug

        cards: List[RecognizedCard] = []
        for slot in range(1, 7):
            number_crop = self._crop(frame_bgr, self._slot_roi(slot))
            text_crop = self._crop(frame_bgr, self._slot_text_roi(slot))
            if number_crop.size == 0 or text_crop.size == 0:
                debug["slots"].append(
                    {
                        "slot": slot,
                        "price_ocr": "",
                        "name_ocr": "",
                        "price_roi_bgr": None,
                        "name_roi_bgr": None,
                    }
                )
                continue

            price_str = self.ocr.run_ocr(context, number_crop, slot)
            name = self.ocr.run_ocr(context, text_crop, slot + 6)
            debug["slots"].append(
                {
                    "slot": slot,
                    "price_ocr": (price_str or "").strip(),
                    "name_ocr": (name or "").strip(),
                    "price_roi_bgr": number_crop.copy(),
                    "name_roi_bgr": text_crop.copy(),
                }
            )

            if not name:
                continue

            price = int(price_str) if price_str.isdigit() else -1
            cards.append(RecognizedCard(slot=slot, name=name, price=price))

        return cards, debug

    def _scan_cards(self, frame_bgr: np.ndarray, context=None) -> List[RecognizedCard]:
        cards, _ = self._scan_cards_with_debug(frame_bgr, context=context)
        return cards

    def _find_hand_change_center_old(self, img_before: np.ndarray, img_after: np.ndarray) -> Optional[float]:
        if img_before is None or img_after is None:
            return None
        if img_before.shape != img_after.shape:
            img_before = cv2.resize(img_before, (img_after.shape[1], img_after.shape[0]))

        h_roi, w_roi = img_after.shape[:2]
        if h_roi == 0 or w_roi == 0:
            return None

        num_slots = 10
        slot_width = w_roi / float(num_slots)
        blur_ksize = (5, 5) #卷积核可以过滤掉轻微的噪点

        max_score = 0
        max_idx = -1
        for i in range(num_slots):
            xs = int(i * slot_width)
            xe = int((i + 1) * slot_width) if i < num_slots - 1 else w_roi
            before_slot = cv2.GaussianBlur(img_before[:, xs:xe], blur_ksize, 0)
            after_slot = cv2.GaussianBlur(img_after[:, xs:xe], blur_ksize, 0)

            diff = cv2.absdiff(before_slot, after_slot)
            gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
            _, th = cv2.threshold(gray, 70, 255, cv2.THRESH_BINARY) # 阈值设为70，可以过滤掉轻微的噪点
            score = cv2.countNonZero(th)
            if score > max_score:
                max_score = score
                max_idx = i

        if max_idx == -1 or max_score <= 70:
            return None

        xs = int(max_idx * slot_width)
        xe = int((max_idx + 1) * slot_width) if max_idx < num_slots - 1 else w_roi
        return xs + (xe - xs) / 2.0

    def _find_hand_change_center_test(self, img_before: np.ndarray, img_after: np.ndarray) -> Optional[float]:
        if img_before is None or img_after is None:
            return None
        if img_before.shape != img_after.shape:
            img_before = cv2.resize(img_before, (img_after.shape[1], img_after.shape[0]))

        h_roi, w_roi = img_after.shape[:2]
        if h_roi == 0 or w_roi == 0:
            return None

        num_slots = 10
        slot_width = w_roi / float(num_slots)
        
        # 这个及格线代表RGB各通道(均值偏移+标准差偏移)的总和，你可以看图去调
        # 大部分的待机动画可能只会产生很小的总偏移(<5.0)，新干员则是爆炸级的数字
        change_threshold = 5.0 

        scores_t = []
        max_t = 0
        max_idx = -1
        
        # 调试画板
        debug_canvas = img_after.copy()
        
        for i in range(num_slots):
            xs = int(i * slot_width)
            xe = int((i + 1) * slot_width) if i < num_slots - 1 else w_roi
            
            # 截取包含 BGR 三通道的原图切片
            slice_before = img_before[:, xs:xe]
            slice_after = img_after[:, xs:xe]
            
            # mean_b/std_b 是形如 [[B], [G], [R]] 的多维数组
            mean_b, std_b = cv2.meanStdDev(slice_before)
            mean_a, std_a = cv2.meanStdDev(slice_after)
            
            # 分别计算 B,G,R 三个通道在 "均值" 和 "标准差(方差的平方根)" 上的绝对偏移量之和
            mean_diff = float(np.sum(np.abs(mean_a - mean_b)))
            std_diff = float(np.sum(np.abs(std_a - std_b)))
            
            # 综合判定分：综合均值偏移和方差偏移
            score_t = mean_diff + std_diff
            scores_t.append(score_t)
            
            if score_t > max_t:
                max_t = score_t
                max_idx = i
                
            # 在调试图上画格子和3个数字打分
            cv2.rectangle(debug_canvas, (xs, 0), (xe, h_roi), (0, 255, 0), 1)
            cv2.putText(debug_canvas, f"M:{mean_diff:.1f}", (xs + 2, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)
            cv2.putText(debug_canvas, f"V:{std_diff:.1f}", (xs + 2, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 255), 1)
            cv2.putText(debug_canvas, f"T:{score_t:.1f}", (xs + 2, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)

        self.log(f"【调试】10区域 RGB 方差+均值 综合变动率(T): {[round(x,1) for x in scores_t]}")

        # 拼图展示给用户看 (2行1列即可，因为原图包含了所有信息)
        row1 = np.hstack((img_before, img_after))
        black_canvas = np.zeros_like(img_before)
        cv2.putText(black_canvas, "Check Right Side --->", (50, int(h_roi/2)), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        row2 = np.hstack((black_canvas, debug_canvas))
        
        canvas = np.vstack((row1, row2))
        
        cv2.imshow(f"RGB Variance Debug | Best Slot: {max_idx} | Press ANY KEY to continue", canvas)
        cv2.waitKey(0) # 0 代表一直暂停死等
        cv2.destroyAllWindows()

        if max_idx == -1 or max_t <= change_threshold:
            return None

        xs = int(max_idx * slot_width)
        xe = int((max_idx + 1) * slot_width) if max_idx < num_slots - 1 else w_roi
        return xs + (xe - xs) / 2.0

    def _find_hand_change_center(self, img_before: np.ndarray, img_after: np.ndarray) -> Optional[float]:
        if img_before is None or img_after is None:
            return None
        if img_before.shape != img_after.shape:
            img_before = cv2.resize(img_before, (img_after.shape[1], img_after.shape[0]))

        h_roi, w_roi = img_after.shape[:2]
        if h_roi == 0 or w_roi == 0:
            return None

        num_slots = 10
        slot_width = w_roi / float(num_slots)
        change_threshold = 5.0 

        max_t = 0
        max_idx = -1
        
        for i in range(num_slots):
            xs = int(i * slot_width)
            xe = int((i + 1) * slot_width) if i < num_slots - 1 else w_roi
            
            slice_before = img_before[:, xs:xe]
            slice_after = img_after[:, xs:xe]
            
            mean_b, std_b = cv2.meanStdDev(slice_before)
            mean_a, std_a = cv2.meanStdDev(slice_after)
            
            mean_diff = float(np.sum(np.abs(mean_a - mean_b)))
            std_diff = float(np.sum(np.abs(std_a - std_b)))
            
            score_t = mean_diff + std_diff
            
            if score_t > max_t:
                max_t = score_t
                max_idx = i

        if max_idx == -1 or max_t <= change_threshold:
            return None

        xs = int(max_idx * slot_width)
        xe = int((max_idx + 1) * slot_width) if max_idx < num_slots - 1 else w_roi
        return xs + (xe - xs) / 2.0

    def _perform_buy_sell(self, controller, slot: int) -> bool:
        """执行单张干员的买卖流程，返回是否检测到商店刷新。"""
        cfg = self._get_config()
        shop_display_roi = ROI_TEMPLATES[cfg.ui_scale]["SHOP_DISPLAY_ROI"]
        hand_area_roi = ROI_TEMPLATES[cfg.ui_scale]["HAND_AREA_ROI"]
        
        frame_bgr = controller.post_screencap().wait().get()
        shop_before = self._crop(frame_bgr, shop_display_roi)
        hand_before = self._crop(frame_bgr, hand_area_roi)
        clicked_region = self._shop_region_index_from_slot(slot)

        click_x, click_y = self._center_of_roi(frame_bgr, self._slot_roi(slot))
        self._double_click(controller, click_x, click_y)

        # self.log(f"操作时延{cfg.post_action_refresh_wait:g}s")
        time.sleep(cfg.post_action_refresh_wait)  # 购买后统一等待商店刷新动画
        after_buy_frame = controller.post_screencap().wait().get()
        shop_after = self._crop(after_buy_frame, shop_display_roi)
        hand_full_after_buy = self._is_hand_full(after_buy_frame)

        refreshed_buy, changed_buy, checked_buy = self.detector.eval_shop_refresh(
            shop_before,
            shop_after,
            excluded_region=clicked_region,
            region_change_threshold=cfg.shop_refresh_change_threshold,
        )
        if hand_full_after_buy and refreshed_buy:
            self.log("购买后手牌区满，UI大面积置灰产生的巨大颜色差值被强制拦截为假刷新")
            refreshed_buy = False

        self.log(
            "购买后刷新检查: "
            f"商品{slot}号, 商店改变{changed_buy}/{checked_buy}, "
            f"商店是否刷新={refreshed_buy}"
        )
        if refreshed_buy:
            # 无论商店是否刷新，我们都必须贯彻执行当前的套现动作（把刚买的卡卖掉）！
            # 否则如果这里直接 return True 中断，会导致买进来的干员烂在手里
            self.log("购买后触发了商店刷新，程序将优先完成本次售卖套现")

        after_frame = after_buy_frame
        hand_after = self._crop(after_frame, hand_area_roi)
        center_x = self._find_hand_change_center(hand_before, hand_after)
        if center_x is None and hand_full_after_buy:
            self.log("购买后手牌已满，继续截图检测手牌变动位置后执行售卖")
            deadline = time.time() + max(0.3, cfg.stable_timeout)
            while time.time() < deadline:
                time.sleep(0.1)
                after_frame = controller.post_screencap().wait().get()
                hand_after = self._crop(after_frame, hand_area_roi)
                center_x = self._find_hand_change_center(hand_before, hand_after)
                if center_x is not None:
                    break

        if center_x is None:
            self.log("未检测到手牌变化")
            return refreshed_buy # 没法卖，但如果购买时刷新了必须报告刷新

        h, w = after_frame.shape[:2]
        hx, hy, hw, hh = hand_area_roi
        abs_x = int(hx * w + center_x)
        abs_y = int((hy + hh) * h)

        max_sell_retries = 3
        for attempt in range(max_sell_retries):
            controller.post_click(abs_x, abs_y).wait()
            time.sleep(cfg.sell_click_wait)  # 选中待售卡片后等待输入焦点稳定

            key_sent = self._send_sell_key_x(controller)
            if not key_sent:
                return refreshed_buy

            time.sleep(cfg.post_action_refresh_wait)  # 卖出后统一等待商店刷新动画

            after_sell_frame = controller.post_screencap().wait().get()
            hand_full_after_sell = self._is_hand_full(after_sell_frame)
            
            if not hand_full_after_sell:
                break
                
            if attempt < max_sell_retries - 1:
                self.log(f"售卖重试 {attempt+1}/{max_sell_retries}: 售卖后手牌仍然满载，漏键检测生效，再次对该坐标尝试出售...")

        shop_after_sell = self._crop(after_sell_frame, shop_display_roi)
        
        # 修正对比基准：如果购买时手牌满（UI置灰暗色），卖出后又会变亮，如果拿暗的去对比必然又会爆发假刷新，因此换回原始基准
        baseline_shop = shop_before if hand_full_after_buy else shop_after
        refreshed_sell, changed_sell, checked_sell = self.detector.eval_shop_refresh(
            baseline_shop,
            shop_after_sell,
            excluded_region=clicked_region,
            region_change_threshold=cfg.shop_refresh_change_threshold,
        )
        if hand_full_after_sell and refreshed_sell:
            self.log("售卖操作结束仍满载（假装卖掉了实际上是UI置灰发红），强制重置为假刷新")
            refreshed_sell = False

        self.log(
            "售卖后刷新检查: "
            f"商品{slot}号, 商店改变{changed_sell}/{checked_sell}, "
            f"商店是否刷新={refreshed_sell}, "
            f"售卖后手牌区是否满={hand_full_after_sell}"
        )
        
        # 只要购买时或售卖时发生了刷新，最终必须报告给外层重新扫描商店
        final_refresh_state = refreshed_buy or refreshed_sell
        
        if hand_full_after_sell:
            self.log("所有售卖重试结束，手牌区仍满载，请人工留意")

        if final_refresh_state:
            self.log("操作期间检测到商店刷新，即将重新扫描")
            return True

        return False

    def _send_sell_key_x(self, controller) -> bool:
        """发送 X 键（当前仅使用 pydirectinput）。"""
        if not _PYDIRECTINPUT_AVAILABLE:
            return False
        try:
            pydirectinput.keyDown("x")
            time.sleep(0.05)  # 按下与抬起之间保留最短按键持续时间，降低吞键概率
            pydirectinput.keyUp("x")
            return True
        except Exception:
            return False

    def _send_refresh_key_d(self, controller) -> bool:
        """发送 D 键触发商店刷新。"""
        del controller
        if not _PYDIRECTINPUT_AVAILABLE:
            return False
        try:
            pydirectinput.keyDown("d")
            time.sleep(0.05)
            pydirectinput.keyUp("d")
            return True
        except Exception:
            return False

    def scan_once(self, controller_or_context) -> List[RecognizedCard]:
        """执行一次稳定帧识别并返回当前商店 1-6 槽位识别结果。"""
        context = controller_or_context if hasattr(controller_or_context, "run_recognition_direct") else None
        controller = context.tasker.controller if context is not None else controller_or_context

        cfg = self._get_config()
        stable = self.detector.wait_for_stability(
            capture_func=lambda: controller.post_screencap().wait().get(),
            timeout=cfg.stable_timeout,
            threshold=cfg.stable_threshold,
            poll_interval=cfg.stable_poll_interval,
        )

        if context is not None:
            return self._scan_cards(stable, context)
        return self._scan_cards(stable)

    def scan_once_debug(self, controller_or_context) -> Dict[str, Any]:
        """执行一次稳定帧识别并返回 cards + 调试截图信息。"""
        context = controller_or_context if hasattr(controller_or_context, "run_recognition_direct") else None
        controller = context.tasker.controller if context is not None else controller_or_context

        cfg = self._get_config()
        stable = self.detector.wait_for_stability(
            capture_func=lambda: controller.post_screencap().wait().get(),
            timeout=cfg.stable_timeout,
            threshold=cfg.stable_threshold,
            poll_interval=cfg.stable_poll_interval,
        )

        cards, debug = self._scan_cards_with_debug(stable, context=context)
        return {"cards": cards, "debug": debug}

    def tick(self, controller_or_context) -> bool:
        """自动倒转主循环：截图、识别、规划并执行动作。"""
        context = controller_or_context if hasattr(controller_or_context, "run_recognition_direct") else None
        controller = context.tasker.controller if context is not None else controller_or_context

        cfg = self._get_config()
        frame = controller.post_screencap().wait().get()

        manual_refresh = self._is_d_pressed()
        if manual_refresh:
            self.log("检测到 D 键，立即执行新一轮识别")

        # 仅截取商店区域比准变动，防止全屏的动画特效让防沉睡机制失效
        changed = manual_refresh or self.last_shop_img is None or self.detector.has_image_changed(
            self._crop(self.last_shop_img, ROI_TEMPLATES[cfg.ui_scale]["SHOP_DISPLAY_ROI"]) if self.last_shop_img is not None else None,
            self._crop(frame, ROI_TEMPLATES[cfg.ui_scale]["SHOP_DISPLAY_ROI"]),
            threshold=cfg.change_threshold,
        )
        if not changed:
            return True

        stable = self.detector.wait_for_stability(
            capture_func=lambda: controller.post_screencap().wait().get(),
            timeout=cfg.stable_timeout,
            threshold=cfg.stable_threshold,
            poll_interval=cfg.stable_poll_interval,
        )

        if self._is_hand_full(stable):
            self.log("手牌已满，等待下一轮")
            self.last_shop_img = stable
            return True

        if context is not None:
            cards = self._scan_cards(stable, context)
        else:
            cards = self._scan_cards(stable)
        actions: List[PlannedAction] = plan_actions(
            cards,
            item_list=cfg.item_list,
            operator_list=cfg.operator_list,
            buy_only_operator_list=cfg.buy_only_operator_list,
            six_star_list=cfg.six_star_list,
            correction_map=cfg.ocr_correction_map,
        )
        if cfg.refresh_keep_mode:
            actions = [a for a in actions if a.action_type in (0, 1)]

        if not actions:
            if cfg.refresh_keep_mode:
                self.log("刷新保留模式：本轮无可购目标，按 D 刷新商店")
                if self._send_refresh_key_d(controller):
                    self.last_shop_img = None
                    return True
            elif cfg.auto_reverse_auto_refresh:
                self.log("倒转自动刷新：本轮无可操作目标，按 D 刷新商店")
                if self._send_refresh_key_d(controller):
                    self.last_shop_img = None
                    return True
            self.last_shop_img = stable
            return True

        self.log(f"本轮计划动作数: {len(actions)}")
        refresh_triggered = False
        for action in actions:
            if action.action_type == 0:
                self.log(f"购买道具: {action.name}")
                x, y = self._center_of_roi(stable, self._slot_roi(action.slot))
                self._double_click(controller, x, y)
            elif action.action_type == 1:
                self.log(f"仅购买干员: {action.name}")
                x, y = self._center_of_roi(stable, self._slot_roi(action.slot))
                shop_before = self._crop(controller.post_screencap().wait().get(), ROI_TEMPLATES[cfg.ui_scale]["SHOP_DISPLAY_ROI"])
                self._double_click(controller, x, y)
                # self.log(f"操作时延{cfg.post_action_refresh_wait:g}s")
                time.sleep(cfg.post_action_refresh_wait)  # 购买后统一等待商店刷新动画
                shop_after = self._crop(controller.post_screencap().wait().get(), ROI_TEMPLATES[cfg.ui_scale]["SHOP_DISPLAY_ROI"])
                clicked_region = self._shop_region_index_from_slot(action.slot)
                refreshed_keep, changed_keep, checked_keep = self.detector.eval_shop_refresh(
                    shop_before,
                    shop_after,
                    excluded_region=clicked_region,
                    region_change_threshold=cfg.shop_refresh_change_threshold,
                )
                if self._is_hand_full(after_buy_frame) and refreshed_keep:
                    self.log("购买保留类干员后手牌区已满导致的UI大幅置灰异常，已被过滤为假刷新")
                    refreshed_keep = False
                    
                self.log(
                    "仅购买后刷新检查: "
                    f"slot={action.slot}, excluded={clicked_region}, changed={changed_keep}/{checked_keep}, "
                    f"threshold={cfg.shop_refresh_change_threshold}, refreshed={refreshed_keep}"
                )
                if refreshed_keep:
                    self.log("仅购买后检测到商店刷新")
                    refresh_triggered = True
                    break
            else:
                self.log(f"买卖干员: {action.name}")
                if self._perform_buy_sell(controller, action.slot):
                    refresh_triggered = True
                    break

            time.sleep(cfg.action_interval)  # 每次动作后做短暂节流，避免连续操作过快导致漏输入

        if refresh_triggered:
            self.log("检测到商店刷新，下一轮立即重新识别")
            self.last_shop_img = None
            return True

        if cfg.refresh_keep_mode:
            self.log("刷新保留模式：本轮购买完成，按 D 刷新商店")
            if self._send_refresh_key_d(controller):
                self.last_shop_img = None
                return True
        elif cfg.auto_reverse_auto_refresh:
            self.log("倒转自动刷新：本轮操作完成，按 D 刷新商店")
            if self._send_refresh_key_d(controller):
                self.last_shop_img = None
                return True

        self.last_shop_img = controller.post_screencap().wait().get()
        return True
