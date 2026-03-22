from dataclasses import dataclass
import difflib
from typing import Dict, List, Optional


@dataclass
class RecognizedCard:
    slot: int
    name: str
    price: int


@dataclass
class PlannedAction:
    action_type: int
    slot: int
    name: str
    price: int


def normalize_text(text: str, correction_map: Dict[str, str]) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return ""

    if cleaned in correction_map:
        cleaned = correction_map[cleaned]

    for wrong, right in correction_map.items():
        if wrong in cleaned:
            cleaned = cleaned.replace(wrong, right)

    return cleaned


def is_list_match(ocr_text: str, target_list: List[str], correction_map: Dict[str, str]) -> bool:
    normalized = normalize_text(ocr_text, correction_map)
    if not normalized:
        return False

    normalized_nospace = normalized.replace(" ", "")
    for target in target_list:
        if not target:
            continue

        target_nospace = target.replace(" ", "")

        # 完全匹配
        if target_nospace == normalized_nospace:
            return True

        # 限制长度误差不超过1，避免 原始干员 与 异格干员 因为子串包含和高的相似度互相误判
        if abs(len(target_nospace) - len(normalized_nospace)) <= 1:
            if target in normalized or target_nospace in normalized_nospace:
                return True

            if len(target_nospace) >= 2:
                ratio = difflib.SequenceMatcher(None, target_nospace, normalized_nospace).ratio()
                if ratio >= 0.6:
                    return True

    return False


def classify_action(
    card: RecognizedCard,
    item_list: List[str],
    operator_list: List[str],
    buy_only_operator_list: List[str],
    six_star_list: List[str],
    correction_map: Dict[str, str],
) -> Optional[int]:

    # 0: 购买道具, 1: 购买保留干员, 2: 购买倒转干员, 3: 0、1费正常倒转
    if is_list_match(card.name, item_list, correction_map):
        return 0

    if card.slot == 6:
        return None

    if is_list_match(card.name, buy_only_operator_list, correction_map):
        return 1

    if is_list_match(card.name, operator_list, correction_map):
        return 2

    # 命中不处理名单时，直接跳过该干员（与费用无关）。
    if is_list_match(card.name, six_star_list, correction_map):
        return None

    if card.price in (0, 1):
        return 3

    return None


def plan_actions(
    cards: List[RecognizedCard],
    item_list: List[str],
    operator_list: List[str],
    buy_only_operator_list: List[str],
    six_star_list: List[str],
    correction_map: Dict[str, str],
) -> List[PlannedAction]:
    actions: List[PlannedAction] = []

    for card in cards:
        if not card.name.strip():
            continue

        action_type = classify_action(
            card,
            item_list=item_list,
            operator_list=operator_list,
            buy_only_operator_list=buy_only_operator_list,
            six_star_list=six_star_list,
            correction_map=correction_map,
        )
        if action_type is None:
            continue

        actions.append(
            PlannedAction(
                action_type=action_type,
                slot=card.slot,
                name=normalize_text(card.name, correction_map),
                price=card.price,
            )
        )

    actions.sort(key=lambda x: (x.action_type, x.price, x.slot))
    return actions

