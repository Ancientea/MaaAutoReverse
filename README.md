# MaaAutoReverse

《明日方舟》卫戍协议自动化买卖工具。当前版本以 `MaaFramework` 运行器为核心，由 `gui_app.py` 提供可视化配置和启停控制。

## 功能概览

- 自动识别商店卡片并按名单执行操作。
- 手牌区满判定（橙色或红色）避免误买。
- 两种运行模式：
  - `F8` 自动倒转：按完整策略执行买/卖。
  - `F9` 干员道具刷新保留：只买保留道具和保留干员，买完后自动按 `D` 刷新继续循环。
- 名单可在 GUI 中实时编辑，并保存到 `config/`。
- 支持预设复选框：
  - 预设道具（来自 `config/predefined_items.json`）
  - 预设保留干员（来自 `config/predefined_buy_only_operators.json`）

## 环境要求

- Windows 10/11
- Python 3.10+
- 游戏窗口建议 16:9，且运行时保持前台无遮挡

## 安装

先安装项目依赖，再补充 `maafw`（运行器依赖）。

```powershell
python -m pip install -r requirements.txt
python -m pip install maafw
```

## 快速开始

```powershell
python gui_app.py
```

启动后：

1. 在顶部选择目标游戏窗口。
2. 配置名单（保留道具、倒转干员、保留干员、不处理干员）。
3. 选择运行模式：
   - 点击 `启动自动倒转 (F8)` 或按 `F8`
   - 点击 `干员道具刷新保留 (F9)` 或按 `F9`

> 脚本会尝试提权运行。若提权窗口被取消，程序会直接退出。

## 运行模式说明

### 1) 自动倒转（F8）

- 按策略执行：
  - 保留道具：只买
  - 倒转干员：买后卖
  - 保留干员：只买
- 检测到商店刷新后进入下一轮识别。

### 2) 干员道具刷新保留（F9）

- 仅执行“保留道具 + 保留干员”的购买。
- 不执行买卖干员动作。
- 当前轮可购目标处理完后，自动发送 `D` 刷新商店并继续识别。

## 配置文件

`config/` 目录下常用文件：

- `buy_items.json`：保留道具名单
- `buy_sell_operators.json`：倒转干员名单
- `buy_only_operators.json`：保留干员名单
- `six_star_operators.json`：0费不买干员名单
- `predefined_items.json`：预设道具复选框
- `predefined_buy_only_operators.json`：预设保留干员复选框
- `maa_option.json`：GUI 运行选项（窗口等）

引擎阈值位于 `autoreverse/config.default.json`，如：

- `change_threshold`
- `shop_refresh_change_threshold`
- `stable_threshold`
- `stable_timeout`
- `post_action_refresh_wait`
- `sell_click_wait`

## 目录结构（核心）

```text
MaaAutoReverse/
|- gui_app.py                  # GUI 入口（F8/F9 控制）
|- maa_adapter.py              # GUI 到 Maa 运行器的适配层
|- autoreverse/engine.py       # 识别、策略执行、手牌满判定
|- autoreverse/runner.py       # Maa 任务生命周期
|- config/                     # 用户配置与预设
|- resource/autoreverse_bundle # Maa pipeline 资源
|- runtime/bin                 # Maa 运行时依赖
```

## 常见问题

### GUI 启动后直接退出

- 通常是提权流程被取消。请右键“以管理员身份运行”终端后再启动。

### 识别/点击不稳定

- 确保窗口前台、无覆盖。
- 检查分辨率比例是否为 16:9。
- 适当调整 `autoreverse/config.default.json` 中稳定性与刷新阈值。

### 快捷键无效

- 确保没有其他软件占用 `F8/F9/X/D`。
- 某些环境下需管理员权限才能全局监听热键。
