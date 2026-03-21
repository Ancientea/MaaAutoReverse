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

        if target in normalized:
            return True

        target_nospace = target.replace(" ", "")
        if target_nospace in normalized_nospace:
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
    # 0: item, 1: buy only operator, 2: specific buy/sell, 3: generic buy/sell
    if card.slot == 6:
        return 0 if is_list_match(card.name, item_list, correction_map) else None

    if is_list_match(card.name, buy_only_operator_list, correction_map):
        return 1

    if is_list_match(card.name, operator_list, correction_map):
        return 2

    # In skip list => no action, regardless of price.
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
        if card.price < 0 or not card.name.strip():
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

