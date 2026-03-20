# AutoReverse on MaaFramework

This module ports the AutoReverse workflow to MaaFramework with a custom action loop.

## What is included

- `resource/autoreverse_bundle/pipeline/autoreverse.json`: loop pipeline entry.
- `autoreverse/engine.py`: Maa OCR, shop refresh detection, buy/sell logic.
- `autoreverse/main.py`: runnable entry for Win32/ADB controller.
- `autoreverse/config.default.json`: editable lists and thresholds.

## Quick start

```powershell
python -m pip install -r requirements.txt
python -m autoreverse.main --controller win32 --window-title "明日方舟"
```

For ADB:

```powershell
python -m autoreverse.main --controller adb
```

## Config

Edit `autoreverse/config.default.json`:

- `item_list`: items to buy.
- `operator_list`: operators to buy then sell.
- `buy_only_operator_list`: operators to buy and keep.
- `six_star_list`: 0-cost operators to keep.
- `ocr_correction_map`: OCR text correction map.
- `change_threshold`, `stable_threshold`, `stable_timeout`: image-change tuning.

## OCR backend

- This sample now uses Maa built-in OCR through `Context.run_recognition_direct(...)`.
- Python-side `rapidocr_onnxruntime` is no longer required for AutoReverse.

## Notes

- This implementation runs through MaaFramework controller APIs and does not depend on `pydirectinput`.
- Manual `D` key trigger from the legacy script is replaced by image-change driven looping.

## GUI integration

Root `gui_app.py` is connected to Maa runtime through root `maa_adapter.py`.
