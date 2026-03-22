import tkinter as tk
from tkinter import ttk, messagebox
import pygetwindow as gw
import sys
import os
import json  # 导入 JSON
import ctypes
import re
import keyboard
import tkinter.font as tkfont
import threading
import cv2
from PIL import Image, ImageTk

import maa_adapter as Buy_Sell

# PREDEFINED_ITEMS 将从 config/predefined_items.json 加载

# 启用 DPI 感知（Windows 平台），防止截图坐标偏移或尺寸错误
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1) # PROCESS_SYSTEM_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# 获取当前脚本所在目录
current_dir = os.path.dirname(os.path.abspath(__file__))

# 定义 config 目录
CONFIG_DIR = os.path.join(current_dir, 'config')
if not os.path.exists(CONFIG_DIR):
    os.makedirs(CONFIG_DIR)

def load_json_config(filename, default=None):
    path = os.path.join(CONFIG_DIR, filename)
    if not os.path.exists(path):
        return default if default is not None else []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"加载 {filename} 失败: {e}")
        return default if default is not None else []

# 加载预设道具
predefined_items_data = load_json_config('predefined_items.json', [])
PREDEFINED_ITEMS = []
if predefined_items_data:
    for item in predefined_items_data:
        if isinstance(item, dict) and 'label' in item and 'value' in item:
            PREDEFINED_ITEMS.append((item['label'], item['value']))
        elif isinstance(item, list) and len(item) == 2:
            PREDEFINED_ITEMS.append(tuple(item))


predefined_buy_only_data = load_json_config('predefined_buy_only_operators.json', [])
PREDEFINED_BUY_ONLY_OPERATORS = []
if predefined_buy_only_data:
    for item in predefined_buy_only_data:
        if isinstance(item, dict) and 'label' in item and 'value' in item:
            PREDEFINED_BUY_ONLY_OPERATORS.append((item['label'], item['value']))
        elif isinstance(item, list) and len(item) == 2:
            PREDEFINED_BUY_ONLY_OPERATORS.append(tuple(item))

# 定义模型存储目录
model_dir = os.path.join(current_dir, 'model')
if not os.path.exists(model_dir):
    os.makedirs(model_dir)

# 解决 OpenMP 冲突可能导致的卡死（常见于多推理库混用或某些 Windows 环境）
os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'

# 设置控制台输出编码为 UTF-8，防止中文乱码（Windows 特有）
if sys.platform.startswith('win'):
    import io
    # PyInstaller --windowed 下 stdout/stderr 可能为 None，需先判空再包装。
    if getattr(sys.stdout, 'buffer', None) is not None:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    if getattr(sys.stderr, 'buffer', None) is not None:
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 旧版本地 OCR 已移除，当前仅使用 Maa 运行器内的 OCR。

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

class ROIProcessorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("卫戍协议-倒转小助手")
        self.root.geometry("1100x900") # 增加宽度以容纳配置区
        self.checkbox_font = tkfont.Font(family="Microsoft YaHei UI", size=11)

        # 加载配置
        self.buy_items = load_json_config('buy_items.json', ["人事部文档"])
        self.buy_sell_ops = load_json_config('buy_sell_operators.json', [])
        self.six_star_ops = load_json_config('six_star_operators.json', [])
        self.buy_only_ops = load_json_config('buy_only_operators.json', [])

        # 初始化 AutoTrader
        self.auto_trader = Buy_Sell.AutoTrader(None, None, self.log_to_status)
        # 使用已加载配置更新名单
        self.auto_trader.update_lists(
            self.buy_items,
            self.buy_sell_ops,
            self.six_star_ops,
            self.buy_only_ops
        )

        self.ui_scale_var = tk.IntVar(value=0) # 0 = 90%, 1 = 100%
        # 根据当前 auto_trader 从配置文件读取的默认值初始化
        if getattr(self.auto_trader, 'ui_scale', '90%') == '100%':
            self.ui_scale_var.set(1)

        # 顶部栏: 窗口选择与比例切换
        top_frame = tk.Frame(root)
        top_frame.pack(fill=tk.X, padx=10, pady=5)

        tk.Label(top_frame, text="选择窗口:").pack(side=tk.LEFT)

        self.window_combo = ttk.Combobox(top_frame, width=20)
        self.window_combo.pack(side=tk.LEFT, padx=5)
        self.refresh_windows()

        btn_refresh = tk.Button(top_frame, text="刷新", command=self.refresh_windows)
        btn_refresh.pack(side=tk.LEFT, padx=5)

        # 界面比例切换
        scale_frame = tk.Frame(top_frame)
        scale_frame.pack(side=tk.LEFT, padx=20)
        tk.Label(scale_frame, text="界面比例:").pack(side=tk.LEFT)
        tk.Label(scale_frame, text="90%").pack(side=tk.LEFT)
        self.scale_ui = ttk.Scale(scale_frame, from_=0, to=1, variable=self.ui_scale_var, orient=tk.HORIZONTAL, length=50, command=self.on_ui_scale_change)
        self.scale_ui.pack(side=tk.LEFT, padx=5)
        tk.Label(scale_frame, text="100%").pack(side=tk.LEFT)

        # 如果通过点击滑块以外部分，自动取整并应用
        self.scale_ui.bind("<ButtonRelease-1>", self.on_ui_scale_release)

        # 自动倒转控制区域
        ar_frame = tk.LabelFrame(root, text="自动倒转设置", padx=5, pady=5)
        ar_frame.pack(fill=tk.X, padx=10, pady=5)

        # 第 1 行：按钮与状态
        line1_frame = tk.Frame(ar_frame)
        line1_frame.pack(fill=tk.X, pady=2)

        self.btn_auto_reverse = tk.Button(line1_frame, text="启动自动倒转 (F8)", command=self.toggle_auto_reverse, bg="#dddddd", height=2)
        self.btn_auto_reverse.pack(side=tk.LEFT, padx=5)

        self.btn_refresh_keep = tk.Button(
            line1_frame,
            text="干员道具刷新保留 (F9)",
            command=self.toggle_refresh_keep_mode,
            bg="#dddddd",
            height=2,
        )
        self.btn_refresh_keep.pack(side=tk.LEFT, padx=5)

        self.btn_scan_test = tk.Button(
            line1_frame,
            text="扫描识别（测试用）",
            command=self.on_scan_test_click,
            bg="#dddddd",
            height=2,
        )
        self.btn_scan_test.pack(side=tk.LEFT, padx=5)



        # 第 2 行：名单配置（使用多行文本框）
        cfg_frame = tk.Frame(ar_frame)
        cfg_frame.pack(fill=tk.X, pady=5)

        # 辅助函数：创建“标签 + 文本框”
        def create_text_area(parent, label_text, default_text, height=3):
            f = tk.Frame(parent)
            f.pack(side=tk.TOP, fill=tk.X, pady=2)
            tk.Label(f, text=label_text, anchor="w").pack(side=tk.TOP, fill=tk.X)
            txt = tk.Text(f, height=height, width=100)
            txt.pack(side=tk.TOP, fill=tk.X, padx=2)
            txt.insert("1.0", default_text)
            return txt

        # 处理道具名单
        # current_items 已在 __init__ 中从 buy_items.json 加载
        current_items = self.buy_items
        predefined_dict = dict(PREDEFINED_ITEMS)
        predefined_values = set(predefined_dict.values())

        self.item_vars = {}

        # 初始化复选框变量
        for lbl, val in PREDEFINED_ITEMS:
            self.item_vars[val] = tk.BooleanVar(value=False)

        # 根据当前 auto_trader 设置状态
        for item in current_items:
            if item in predefined_values:
                # 属于预设项，勾选
                if item in self.item_vars:
                    self.item_vars[item].set(True)

        # 文本框显示所有当前道具
        default_items_text = "、".join(current_items)

        default_ops = "、".join(self.buy_sell_ops)
        default_six = "、".join(self.six_star_ops)
        default_buy_only = "、".join(self.buy_only_ops)
        self.txt_items = create_text_area(cfg_frame, "保留道具 (分割符: 逗号/顿号/分号):", default_items_text, height=2)

        # 预设道具选择区（放在保留道具和倒转干员之间）
        cb_frame = tk.LabelFrame(cfg_frame, text="预设道具选择 (实时生效，点击填入保留道具)", padx=5, pady=5)
        cb_frame.pack(fill=tk.X, pady=2)

        for idx, (label, val) in enumerate(PREDEFINED_ITEMS):
            chk = tk.Checkbutton(
                cb_frame,
                text=label,
                variable=self.item_vars[val],
                font=self.checkbox_font,
                command=lambda v=val: self.on_checkbox_click(v),
            )
            chk.grid(row=idx // 8, column=idx % 8, sticky="w", padx=4, pady=0)

        self.txt_ops = create_text_area(cfg_frame, "倒转干员 (直接买卖):", default_ops, height=2)
        self.txt_buy_only = create_text_area(cfg_frame, "保留干员 (只买不卖):", default_buy_only, height=2)

        # 预设保留干员选择区（逻辑同预设道具）
        self.buy_only_vars = {}
        for _, val in PREDEFINED_BUY_ONLY_OPERATORS:
            self.buy_only_vars[val] = tk.BooleanVar(value=(val in self.buy_only_ops))

        buy_only_cb_frame = tk.LabelFrame(cfg_frame, text="预设保留干员选择 (实时生效，点击填入保留干员)", padx=5, pady=5)
        buy_only_cb_frame.pack(fill=tk.X, pady=2)

        for idx, (label, val) in enumerate(PREDEFINED_BUY_ONLY_OPERATORS):
            chk = tk.Checkbutton(
                buy_only_cb_frame,
                text=label,
                variable=self.buy_only_vars[val],
                font=self.checkbox_font,
                command=lambda v=val: self.on_buy_only_checkbox_click(v),
            )
            chk.grid(row=idx // 8, column=idx % 8, sticky="w", padx=8, pady=4)

        self.txt_six = create_text_area(cfg_frame, "不处理名单:", default_six, height=3)

        self.status_label = tk.Label(top_frame, text="Maa 运行器就绪", fg="green")
        self.status_label.pack(side=tk.LEFT, padx=10)

        # F8 key detection via keyboard library
        keyboard.add_hotkey('f8', self.safe_toggle_auto_reverse)
        keyboard.add_hotkey('f9', self.safe_toggle_refresh_keep)

        # 底部折叠栏：展示单次扫描识别结果
        self.scan_panel_expanded = False
        bottom_frame = tk.LabelFrame(root, text="识别结果", padx=6, pady=6)
        bottom_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.btn_toggle_scan_panel = tk.Button(
            bottom_frame,
            text="▶ 单次扫描结果（点击展开）",
            anchor="w",
            command=self.toggle_scan_panel,
        )
        self.btn_toggle_scan_panel.pack(fill=tk.X)

        self.scan_panel_body = tk.Frame(bottom_frame)
        self.txt_scan_result = tk.Text(self.scan_panel_body, height=4, width=120)
        self.txt_scan_result.pack(fill=tk.X)
        self.txt_scan_result.insert("1.0", "暂无识别结果")
        self.txt_scan_result.config(state=tk.DISABLED)

        # 调试图文滚动区（整图 + 各槽位 ROI）
        self.scan_photo_refs = []
        self.scan_canvas = tk.Canvas(self.scan_panel_body, height=340)
        self.scan_scrollbar = tk.Scrollbar(self.scan_panel_body, orient="vertical", command=self.scan_canvas.yview)
        self.scan_canvas.configure(yscrollcommand=self.scan_scrollbar.set)
        self.scan_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.scan_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=(6, 0))

        self.scan_content_frame = tk.Frame(self.scan_canvas)
        self.scan_canvas_window = self.scan_canvas.create_window((0, 0), window=self.scan_content_frame, anchor="nw")
        self.scan_content_frame.bind("<Configure>", self._on_scan_content_configure)
        self.scan_canvas.bind("<Configure>", self._on_scan_canvas_configure)

    # 本地 OCR 初始化已移除，OCR 由 Maa AutoReverse 引擎内部处理。

    def log_to_status(self, msg):
        # AutoTrader 回调：更新状态栏
        # 使用 after 保证线程安全
        self.root.after(0, lambda: self.status_label.config(text=msg, fg="blue"))

    def on_checkbox_click(self, val):
        """当复选框被点击时，更新文本框内容"""
        is_checked = self.item_vars[val].get()
        # 获取当前文本框内容
        text_content = self.txt_items.get("1.0", "end")
        current_list = self.parse_list(text_content)

        if is_checked:
            if val not in current_list:
                current_list.append(val)
        else:
            if val in current_list:
                # 只有在列表里确实存在时才尝试删除
                # 这里只移除完全匹配的项
                current_list.remove(val)

        # 更新文本框
        new_text = "、".join(current_list)
        self.txt_items.delete("1.0", "end")
        self.txt_items.insert("1.0", new_text)

        # 触发后台更新
        self.update_autotrader_from_gui()

    def on_ui_scale_change(self, event=None):
        """处理滑块拖动中，只允许取整 0 或 1"""
        val = int(round(self.ui_scale_var.get()))
        # 如果 ttk.Scale 自己通过鼠标滑动赋值可能是浮点数，强制绑定更新并通知后台
        if val == 0:
            self.auto_trader.set_ui_scale("90%")
        else:
            self.auto_trader.set_ui_scale("100%")

    def on_ui_scale_release(self, event=None):
        val = int(round(self.ui_scale_var.get()))
        self.ui_scale_var.set(val)
        if val == 0:
            self.auto_trader.set_ui_scale("90%")
        else:
            self.auto_trader.set_ui_scale("100%")

    def on_buy_only_checkbox_click(self, val):
        """当预设保留干员复选框被点击时，更新保留干员文本框内容"""
        is_checked = self.buy_only_vars[val].get()
        text_content = self.txt_buy_only.get("1.0", "end")
        current_list = self.parse_list(text_content)

        if is_checked:
            if val not in current_list:
                current_list.append(val)
        else:
            if val in current_list:
                current_list.remove(val)

        self.txt_buy_only.delete("1.0", "end")
        self.txt_buy_only.insert("1.0", "、".join(current_list))
        self.update_autotrader_from_gui()

    def update_autotrader_from_gui(self):
        """从 GUI 控件同步更新 AutoTrader 名单"""
        # 现在以文本框内容为准
        all_items = self.parse_list(self.txt_items.get("1.0", "end"))

        ops = self.parse_list(self.txt_ops.get("1.0", "end"))
        sixs = self.parse_list(self.txt_six.get("1.0", "end"))
        buy_only = self.parse_list(self.txt_buy_only.get("1.0", "end"))

        self.auto_trader.update_lists(all_items, ops, sixs, buy_only)

    def safe_toggle_auto_reverse(self):
        """F8 热键的线程安全封装"""
        self.root.after(0, self.toggle_auto_reverse)

    def safe_toggle_refresh_keep(self):
        """F9 热键的线程安全封装"""
        self.root.after(0, self.toggle_refresh_keep_mode)

    def toggle_scan_panel(self):
        self.scan_panel_expanded = not self.scan_panel_expanded
        if self.scan_panel_expanded:
            self.btn_toggle_scan_panel.config(text="▼ 单次扫描结果（点击折叠）")
            self.scan_panel_body.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        else:
            self.btn_toggle_scan_panel.config(text="▶ 单次扫描结果（点击展开）")
            self.scan_panel_body.pack_forget()

    def _set_scan_result_text(self, lines):
        text = "\n".join(lines) if lines else "本次未识别到有效结果"
        self.txt_scan_result.config(state=tk.NORMAL)
        self.txt_scan_result.delete("1.0", "end")
        self.txt_scan_result.insert("1.0", text)
        self.txt_scan_result.config(state=tk.DISABLED)

    def _on_scan_content_configure(self, _event):
        self.scan_canvas.configure(scrollregion=self.scan_canvas.bbox("all"))

    def _on_scan_canvas_configure(self, event):
        self.scan_canvas.itemconfigure(self.scan_canvas_window, width=event.width)

    def _clear_scan_debug_widgets(self):
        for child in self.scan_content_frame.winfo_children():
            child.destroy()
        self.scan_photo_refs = []

    def _build_photo(self, bgr_img, max_width=440, max_height=220):
        if bgr_img is None:
            return None
        if not hasattr(bgr_img, "shape"):
            return None
        if bgr_img.size == 0:
            return None

        rgb = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        resampling = getattr(Image, "Resampling", Image)
        lanczos = getattr(resampling, "LANCZOS", Image.LANCZOS)
        pil_img.thumbnail((max_width, max_height), lanczos)
        return ImageTk.PhotoImage(pil_img)

    def _render_scan_debug(self, debug_data):
        self._clear_scan_debug_widgets()
        if not isinstance(debug_data, dict):
            return

        frame_bgr = debug_data.get("frame_bgr")
        slots = debug_data.get("slots", []) or []

        header = tk.Label(self.scan_content_frame, text="整张截图", anchor="w", font=("Microsoft YaHei UI", 10, "bold"))
        header.pack(fill=tk.X, pady=(0, 4))

        frame_photo = self._build_photo(frame_bgr, max_width=900, max_height=360)
        if frame_photo is not None:
            self.scan_photo_refs.append(frame_photo)
            tk.Label(self.scan_content_frame, image=frame_photo, anchor="w").pack(fill=tk.X, pady=(0, 8))
        else:
            tk.Label(self.scan_content_frame, text="整图不可用", fg="#666666", anchor="w").pack(fill=tk.X, pady=(0, 8))

        tk.Label(self.scan_content_frame, text="各扫描区域与识别结果", anchor="w", font=("Microsoft YaHei UI", 10, "bold")).pack(fill=tk.X)

        for slot_item in slots:
            slot = slot_item.get("slot", "?")
            block = tk.LabelFrame(self.scan_content_frame, text=f"槽位 {slot}", padx=6, pady=6)
            block.pack(fill=tk.X, pady=6)

            ocr_text = f"价格OCR: {slot_item.get('price_ocr', '') or '(空)'}    名称OCR: {slot_item.get('name_ocr', '') or '(空)'}"
            tk.Label(block, text=ocr_text, anchor="w", justify="left").pack(fill=tk.X, pady=(0, 6))

            imgs_frame = tk.Frame(block)
            imgs_frame.pack(fill=tk.X)

            price_photo = self._build_photo(slot_item.get("price_roi_bgr"), max_width=260, max_height=120)
            name_photo = self._build_photo(slot_item.get("name_roi_bgr"), max_width=420, max_height=120)

            left = tk.Frame(imgs_frame)
            left.pack(side=tk.LEFT, padx=(0, 8))
            tk.Label(left, text="费用区域", anchor="w").pack(fill=tk.X)
            if price_photo is not None:
                self.scan_photo_refs.append(price_photo)
                tk.Label(left, image=price_photo).pack()
            else:
                tk.Label(left, text="无截图", fg="#666666").pack()

            right = tk.Frame(imgs_frame)
            right.pack(side=tk.LEFT)
            tk.Label(right, text="名称区域", anchor="w").pack(fill=tk.X)
            if name_photo is not None:
                self.scan_photo_refs.append(name_photo)
                tk.Label(right, image=name_photo).pack()
            else:
                tk.Label(right, text="无截图", fg="#666666").pack()

    def on_scan_test_click(self):
        if self.auto_trader.running:
            messagebox.showinfo("提示", "请先停止 F8/F9 运行，再进行测试扫描。")
            return

        target_title = self.window_combo.get().strip()
        if not target_title:
            messagebox.showerror("错误", "请先选择一个窗口。")
            return

        self.update_autotrader_from_gui()
        self.btn_scan_test.config(state=tk.DISABLED)
        self.update_status("正在执行单次扫描识别...", error=False)

        worker = threading.Thread(target=self._run_scan_once_worker, args=(target_title,), daemon=True)
        worker.start()

    def _run_scan_once_worker(self, target_title):
        try:
            scan_result = self.auto_trader.scan_once_debug(target_title)
            cards = list(scan_result.get("cards", []))
            debug_data = scan_result.get("debug", {})
            lines = []
            for card in cards:
                price_text = str(card.price) if card.price >= 0 else "?"
                lines.append(f"槽位{card.slot} | 费用: {price_text} | 干员: {card.name}")

            def _ok():
                if not self.scan_panel_expanded:
                    self.toggle_scan_panel()
                self._set_scan_result_text(lines)
                self._render_scan_debug(debug_data)
                if lines:
                    self.update_status(f"扫描完成，共识别 {len(lines)} 条", error=False)
                else:
                    self.update_status("扫描完成，未识别到可用干员", error=False)
                self.btn_scan_test.config(state=tk.NORMAL)

            self.root.after(0, _ok)
        except Exception as e:
            def _err():
                if not self.scan_panel_expanded:
                    self.toggle_scan_panel()
                self._set_scan_result_text([f"扫描失败: {e}"])
                self._clear_scan_debug_widgets()
                self.update_status(f"扫描失败: {e}", error=True)
                self.btn_scan_test.config(state=tk.NORMAL)
            self.root.after(0, _err)

    def toggle_auto_reverse(self):
        try:
            target_title = self.window_combo.get()
            if not target_title:
                messagebox.showerror("错误", "请先选择一个窗口。")
                return

            if self.auto_trader.running:
                if self.auto_trader.refresh_keep_mode:
                    messagebox.showinfo("提示", "当前为刷新保留模式，请按 F9 停止。")
                    return
                self.stop_auto_reverse()
            else:
                # 启动前先同步名单
                self.update_autotrader_from_gui()
                self.start_auto_reverse(target_title, refresh_keep_mode=False)
        except Exception as e:
            self.update_status(f"切换自动倒转失败: {e}", error=True)
            messagebox.showerror("自动倒转错误", str(e))

    def toggle_refresh_keep_mode(self):
        try:
            target_title = self.window_combo.get()
            if not target_title:
                messagebox.showerror("错误", "请先选择一个窗口。")
                return

            if self.auto_trader.running:
                if self.auto_trader.refresh_keep_mode:
                    self.stop_auto_reverse()
                else:
                    messagebox.showinfo("提示", "当前为自动倒转模式，请先按 F8 停止后再启动 F9。")
                return

            self.update_autotrader_from_gui()
            self.start_auto_reverse(target_title, refresh_keep_mode=True)
        except Exception as e:
            self.update_status(f"切换刷新保留失败: {e}", error=True)
            messagebox.showerror("刷新保留错误", str(e))

    def parse_list(self, text):
        # 去除首尾空白
        text = text.strip()
        if not text:
            return []
        # 按逗号、顿号、分号、换行分割
        parts = re.split(r'[，,；;、\n]', text)
        # 过滤空项并去除空白
        return [p.strip() for p in parts if p.strip()]

    def start_auto_reverse(self, title, refresh_keep_mode=False):
        try:
            self.auto_trader.set_window(title)
            self.auto_trader.set_refresh_keep_mode(refresh_keep_mode)
            self.auto_trader.start()
            self.btn_scan_test.config(state=tk.DISABLED)
            if refresh_keep_mode:
                self.btn_refresh_keep.config(text="停止刷新保留 (F9)", bg="#ffcccc")
                self.btn_auto_reverse.config(bg="#dddddd")
                self.update_status("刷新保留模式已启动", error=False)
            else:
                self.btn_auto_reverse.config(text="停止自动倒转 (F8)", bg="#ffcccc")
                self.btn_refresh_keep.config(bg="#dddddd")
                self.update_status("自动倒转已启动", error=False)
        except Exception as e:
            self.update_status(f"启动失败: {e}", error=True)
            messagebox.showerror("启动失败", str(e))

    def stop_auto_reverse(self):
        try:
            self.auto_trader.stop()
            self.btn_auto_reverse.config(text="启动自动倒转 (F8)", bg="#dddddd")
            self.btn_refresh_keep.config(text="干员道具刷新保留 (F9)", bg="#dddddd")
            self.btn_scan_test.config(state=tk.NORMAL)
            self.update_status("自动倒转已停止", error=False)
        except Exception as e:
            self.update_status(f"停止失败: {e}", error=True)
            messagebox.showerror("停止失败", str(e))

    def refresh_windows(self):
        # 过滤掉不可见或标题为空的窗口
        titles = []
        for w in gw.getAllWindows():
            if not w.title:
                continue
            # 检查窗口是否可见
            if not w.isMinimized and (w.width <= 0 or w.height <= 0):
                 continue
            # 简单的可见性检查 (利用 ctypes)
            try:
                 # _hWnd 是 pygetwindow 内部属性，但在 Windows 平台可用
                 if hasattr(w, '_hWnd') and not ctypes.windll.user32.IsWindowVisible(w._hWnd):
                     continue
            except:
                pass

            titles.append(w.title)

        # 去重
        titles = list(set(titles))

        # 排序逻辑：优先 "明日方舟"，其次 "模拟器"，最后按名称排序
        def sort_key(title):
            if "明日方舟" in title:
                return 0
            if "模拟器" in title:
                return 1
            return 2

        # 先按名称排序，保证同级有序
        titles.sort()
        # 再按优先级排序
        titles.sort(key=sort_key)

        self.window_combo['values'] = titles
        if titles:
            self.window_combo.current(0)


    def update_status(self, msg, error=False):
        color = "red" if error else "green"
        self.root.after(0, lambda: self.status_label.config(text=msg, fg=color))


if __name__ == "__main__":
    if not is_admin():
        # 使用管理员权限重新启动程序
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join([f'"{arg}"' for arg in sys.argv]), None, 1)
        sys.exit()

    root = tk.Tk()
    app = ROIProcessorApp(root)
    root.mainloop()
