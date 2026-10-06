import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk, colorchooser
import tkinter.font as tkfont
import os
import cv2
import numpy as np

# --- Wayland support ---------------------------------------------------------
# pyautogui is X11-only: merely importing it on a Wayland session calls size(),
# which needs an X connection and raises Xlib.error.XauthError. Install the
# grim/ydotool replacement first so the import below picks it up. On Windows,
# macOS and X11 this is a no-op and the real pyautogui is used.
try:
    from flowchart_automation.wayland import install_shim as _install_shim
    _install_shim()
except Exception as _shim_error:  # not installed, or not a Wayland session
    print(f"Note: Wayland input backend unavailable ({_shim_error}).")

# Shared colour targeting (aim point, blob splitting) used by the executor.
from flowchart_automation.detection import color as flowchart_color

import pyautogui
import time
import keyboard
import json
import random
import math
import copy
from PIL import Image, ImageTk # Visual Rep
import urllib.request # For API requests
import sys # For portable Tesseract path
import threading
import ctypes
import shutil

# --- Helper for Portable Tesseract ---
def get_base_path():
    """ Get absolute path to resource, works for dev and for PyInstaller """
    # PyInstaller creates a temp folder and stores path in _MEIPASS
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    else:
        return os.path.abspath(".")

# --- OCR Dependency Check ---
try:
    import pytesseract
    
    # --- Path logic for portable Tesseract ---
    # The user should create a folder named 'tesseract' next to the script/EXE
    # and place the Tesseract-OCR contents there.
    portable_tesseract_path = os.path.join(get_base_path(), 'tesseract', 'tesseract.exe')
    
    if os.path.exists(portable_tesseract_path):
        pytesseract.pytesseract.tesseract_cmd = portable_tesseract_path
    else:
        _system_tesseract = shutil.which('tesseract')
        if _system_tesseract:
            pytesseract.pytesseract.tesseract_cmd = _system_tesseract
        else:
            pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    
    pytesseract.get_tesseract_version() 
    PYTESSERACT_AVAILABLE = True

except (ImportError, FileNotFoundError, pytesseract.TesseractNotFoundError):
    PYTESSERACT_AVAILABLE = False

__version__ = "0.66.0"


class FlowchartClickerApp:
    """
    An intelligent automation tool with an enhanced visual, node-based flowchart interface.
    """
    MULTIPLE_VALUES = "< multiple values >"

    # Settings a "Settings Inject" step may change mid-flow: display name -> key
    # in global_settings_map. That map is the single source of truth for the
    # model variable and its type, so this table only has to supply names.
    INJECTABLE_SETTINGS = {
        "Mouse Move Speed (s)": "mouse_speed",
        "Mouse Move Mode": "mouse_move_mode",
        "Pixels Per Second": "pixels_per_second",
        "Min Move Time (s)": "min_move_time",
        "Max Move Time (s)": "max_move_time",
        "Location Offset (±px)": "loc_offset_variance",
        "Speed Variance (±s)": "speed_variance",
        "Base Hold Duration (s)": "hold_duration",
        "Hold Variance (±s)": "hold_duration_variance",
        "Scan Interval (s)": "scan_interval",
    }

    # Allowed values for the string-valued setting, matching the radio buttons.
    MOVE_MODE_VALUES = ("Regular", "Dynamic", "Pixels Per Second")

    def __init__(self, root):
        self.root = root
        self.root.title("Flowchart Automation Tool")
        try:
            # This works on Windows and some Linux DEs. Fails gracefully on others.
            self.root.iconbitmap(os.path.join(get_base_path(), "Flow2.ico"))
        except tk.TclError:
            # self.log is not available yet, so we print
            print("Note: .ico format not supported on this system. Skipping icon.")

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        
        # Set window size to 90% of the screen
        win_w = int(screen_w * 0.9)
        win_h = int(screen_h * 0.9)

        # Calculate position to center the window
        pos_x = (screen_w // 2) - (win_w // 2)
        pos_y = (screen_h // 2) - (win_h // 2)

        self.root.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
        self.root.minsize(1200, 700)
                
        # --- Theme Settings ---
        self.current_theme = {}
        self.status_label_color_state = 'blue'

        # --- Global Settings ---
        self.mouse_move_mode = tk.StringVar(value='Regular')
        self.mouse_speed = tk.DoubleVar(value=0.25)
        self.pixels_per_second = tk.IntVar(value=1000)
        self.min_move_time = tk.DoubleVar(value=0.05)
        self.max_move_time = tk.DoubleVar(value=0.3)
        self.scan_interval = tk.DoubleVar(value=0.25)
        self.hold_duration = tk.DoubleVar(value=0.08)
        self.loc_offset_variance = tk.IntVar(value=4)
        self.speed_variance = tk.DoubleVar(value=0.06)
        self.hold_duration_variance = tk.DoubleVar(value=0.03)
        self.hide_on_select = tk.BooleanVar(value=True)
        self.enable_all_show_area = tk.BooleanVar(value=False)
        self.start_at_stopped_pos = tk.BooleanVar(value=False)
        self.enable_dynamic_speed = tk.BooleanVar(value=False)

        # --- Flowchart Grid Settings ---
        self.grid_visible = tk.BooleanVar(value=False)
        self.grid_latching = tk.BooleanVar(value=False)
        self.grid_spacing = tk.IntVar(value=30)
        self.grid_opacity = tk.DoubleVar(value=0.3)

        self.area_x1 = tk.IntVar(value=0); self.area_y1 = tk.IntVar(value=0)
        self.area_x2 = tk.IntVar(value=screen_w); self.area_y2 = tk.IntVar(value=screen_h)
        
        self.global_settings_map = {
            'mouse_move_mode': {'model': self.mouse_move_mode, 'type': str},
            'mouse_speed': {'model': self.mouse_speed, 'type': float},
            'pixels_per_second': {'model': self.pixels_per_second, 'type': int},
            'scan_interval': {'model': self.scan_interval, 'type': float},
            'hold_duration': {'model': self.hold_duration, 'type': float},
            'loc_offset_variance': {'model': self.loc_offset_variance, 'type': int},
            'speed_variance': {'model': self.speed_variance, 'type': float},
            'hold_duration_variance': {'model': self.hold_duration_variance, 'type': float},
            'area_x1': {'model': self.area_x1, 'type': int},
            'area_y1': {'model': self.area_y1, 'type': int},
            'area_x2': {'model': self.area_x2, 'type': int},
            'area_y2': {'model': self.area_y2, 'type': int},
            'min_move_time': {'model': self.min_move_time, 'type': float},
            'max_move_time': {'model': self.max_move_time, 'type': float},
            'grid_visible': {'model': self.grid_visible, 'type': bool},
            'grid_latching': {'model': self.grid_latching, 'type': bool},
            'grid_spacing': {'model': self.grid_spacing, 'type': int},
            'grid_opacity': {'model': self.grid_opacity, 'type': float},
        }
        self.global_settings_ui_vars = {key: tk.StringVar() for key in self.global_settings_map}

        # --- Core Data Structures ---
        self.steps = []
        self.annotations = []
        self.template_cache = {}
        self.folder_image_cache = {}
        self.clipboard = []
        self.clipboard_origin = (0, 0)
        
        # --- UI State & Data ---
        self.selected_items = []
        self.properties_widgets = {}
        self._drag_data = {"start_x": 0, "start_y": 0, "item": None, "mode": "move", "initial_positions": []}
        self._marquee_data = {}
        self.area_overlays = {}
        self.zoom_factor = 1.0
        self.search_query = tk.StringVar()
        self.search_results = []
        self.current_search_index = -1
        self.search_query.trace_add('write', self._reset_search)

        # --- Execution State ---
        self.running = False
        self.current_step_index = 0
        self.current_step_start_time = 0
        self.executor_after_id = None
        self.delay_countdown_id = None
        self.timeout_countdown_id = None
        self.stop_requested = False
        self.start_step = tk.StringVar(value='1')
        self.automation_start_time = 0
        self.cycle_time_display = tk.StringVar(value="Cycle Time: 0.0s")
        self.cycle_time_updater_id = None
        
        # --- Hotkey / Capture Mode State ---
        self.f3_mode = None
        self.hotkey_listener = None
        self.global_hotkeys = False
        # Picker overlay state (see enter_f3_mode)
        self.picker_overlay = None
        self.picker_pos_label = None
        self.picker_poll_id = None

        # --- Live Info & Logging ---
        self.last_detection_info = tk.StringVar(value="Detection: N/A")
        self.log_text = None 
        self.full_log_history = []
        self.log_search_query = tk.StringVar()
        self.log_search_query.trace_add('write', self.filter_log)
        self.log_auto_clear_lines = tk.IntVar(value=500)

        # --- Testing Panel ---
        self.active_test_type = tk.StringVar(value="PNG")
        self.test_png_mode = tk.StringVar(value='file')
        self.test_png_path = tk.StringVar()
        self.test_png_path_display = tk.StringVar(value="No path set")
        self.test_png_threshold = tk.DoubleVar(value=0.8)
        self.test_png_image_mode = tk.StringVar(value='Grayscale')
        self.test_png_count_expression = tk.StringVar(value='>= 1')
        self.test_area = None
        self.test_color_rgb = (255, 0, 0)
        self.test_color_tolerance = tk.IntVar(value=10)
        self.test_color_space = tk.StringVar(value='HSV')
        self.test_color_min_area = tk.IntVar(value=10)
        self.test_color_count_expression = tk.StringVar(value='>= 1')
        self.test_number_expression = tk.StringVar(value='> 0')
        self.psm_options = {
            "0: Orientation and script detection (OSD) only.": "0", "1: Automatic page segmentation with OSD.": "1",
            "3: Fully automatic page segmentation, but no OSD. (Default)": "3", "6: Assume a single uniform block of text.": "6",
            "7: Treat the image as a single text line.": "7", "8: Treat the image as a single word.": "8",
            "10: Treat the image as a single character.": "10", "13: Raw line. Treat the image as a single text line, bypassing hacks.": "13"
        }
        self.oem_options = { "0: Legacy Engine only.": "0", "1: Neural nets LSTM engine only.": "1", "2: Legacy + LSTM engines.": "2", "3: Default, based on what is available.": "3" }
        self.test_number_oem = tk.StringVar(value="3: Default, based on what is available.")
        self.test_number_psm = tk.StringVar(value="6: Assume a single uniform block of text.")

        # --- GE Interface ---
        self.api_headers = {'User-Agent': 'Flowchart Automation Tool - Contact on GitHub'}
        self.item_mapping_cache = None; self.item_price_cache = {}; self.all_item_prices_cache = None; self.hourly_volume_cache = None
        self.ge_interface_item_name = tk.StringVar(); self.ge_interface_item_quantity = tk.StringVar(value="1")
        self.ge_interface_buy_price_strategy = tk.StringVar(value='Flip-Buy (use Insta-Sell)')
        self.ge_interface_sell_price_strategy = tk.StringVar(value='Flip-Sell (use Insta-Buy)')
        self.ge_interface_buy_custom_price = tk.StringVar(value="0")
        self.ge_interface_sell_custom_price = tk.StringVar(value="0")
        self.ge_interface_buy_price_margin = tk.StringVar(value="1")
        self.ge_interface_sell_price_margin = tk.StringVar(value="1")
        self.ge_interface_display_buy_price = tk.StringVar(value="N/A")
        self.ge_interface_display_buy_total = tk.StringVar(value="N/A")
        self.ge_interface_display_sell_price = tk.StringVar(value="N/A")
        self.ge_interface_display_sell_total = tk.StringVar(value="N/A")
        self.ge_interface_last_data = None
        self.ge_auto_update_enabled = tk.BooleanVar(value=False)
        self.ge_auto_update_enabled.trace_add('write', self._toggle_ge_auto_update)
        self.ge_auto_update_interval = tk.StringVar(value="60"); self.ge_auto_update_after_id = None

        # --- Threading Lock for Detection ---
        self.detection_lock = threading.Lock()
        self.detection_thread = None
        self.detection_result = None

        # --- Final UI Setup ---
        self.build_ui()
        # apply_theme() must run before setup_hotkeys(): registering global
        # hotkeys fails on Linux (the keyboard library needs root), and its
        # error handler calls log(), which reads self.current_theme.
        self.apply_theme()
        self.setup_hotkeys()
        self.log("Application initialized successfully.")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def apply_theme(self):
        theme = {
            'bg': '#282C34', 'fg': '#ABB2BF', 'canvas': '#21252B', 'log': '#1E2228',
            'entry_bg': '#2C313A', 'entry_fg': '#D7D7D7', 'text': '#ABB2BF',
            'props_bg': '#2C313A', 'accent_green': '#98C379', 'accent_blue': '#61AFEF',
            'accent_grey': '#5C6370', 'accent_red': '#E06C75', 'accent_yellow': '#E5C07B',
            'accent_teal': '#56B6C2', 'accent_purple': '#C678DD', 'node_border': '#ABB2BF',
            'node_text_grey': '#8A92A0', 'btn_fg': '#FFFFFF', 'status_blue': '#61AFEF',
            'status_green': '#98C379', 'status_orange': '#D19A66', 'status_red': '#BE5046',
            'select_bg': '#3A4048', 'tree_heading_bg': '#2C313A', 'tree_heading_fg': '#ABB2BF', 'blk': '#b0192d'
        }
        self.current_theme = theme
        style = ttk.Style(); style.theme_use('clam')

        # General widget styling
        style.configure('.', background=theme['bg'], foreground=theme['fg'], fieldbackground=theme['entry_bg'], bordercolor=theme['node_border'], lightcolor=theme['bg'], darkcolor=theme['bg'])
        style.map('.', background=[('active', theme['entry_bg'])])

        # Specific widget configurations
        style.configure('TFrame', background=theme['bg'])
        style.configure('TLabel', background=theme['bg'], foreground=theme['fg'])
        style.configure('TLabelframe', background=theme['bg'], foreground=theme['fg'], bordercolor=theme['fg'])
        style.configure('TLabelframe.Label', background=theme['bg'], foreground=theme['fg'])
        style.configure('TEntry', fieldbackground=theme['entry_bg'], foreground=theme['entry_fg'], insertcolor=theme['text'])
        style.configure('TNotebook', background=theme['bg'], borderwidth=1)
        style.configure('TNotebook.Tab', background=theme['accent_grey'], foreground=theme['btn_fg'], padding=[8, 4])
        style.map('TNotebook.Tab', background=[('selected', theme['canvas']), ('active', theme['entry_bg'])], foreground=[('selected', theme['fg']), ('active', theme['fg'])])
        style.configure('TCheckbutton', background=theme['bg'], foreground=theme['fg'], indicatorcolor=theme['entry_bg'])
        style.map('TCheckbutton', 
                  indicatorcolor=[('selected', theme['status_green']), ('!selected', theme['entry_bg'])],
                  foreground=[('selected', theme['status_green'])],
                  background=[('active', theme['bg'])])
        style.configure('TRadiobutton', background=theme['bg'], foreground=theme['fg'])
        style.map('TRadiobutton', background=[('active', theme['entry_bg'])])
        style.configure('TCombobox', fieldbackground=theme['entry_bg'], foreground=theme['entry_fg'], arrowcolor=theme['fg'], background=theme['bg'])
        style.map('TCombobox', fieldbackground=[('readonly', theme['entry_bg'])])
        
        # Treeview styling for Deal Finder
        style.configure("Treeview", background=theme['entry_bg'], foreground=theme['entry_fg'], fieldbackground=theme['entry_bg'], rowheight=25)
        style.map("Treeview", background=[('selected', theme['select_bg'])], foreground=[('selected', theme['fg'])])
        style.configure("Treeview.Heading", background=theme['tree_heading_bg'], foreground=theme['tree_heading_fg'], font=('Helvetica', 10, 'bold'))
        style.map("Treeview.Heading", background=[('active', theme['accent_grey'])])

        self.root.config(bg=theme['bg'])
        self.update_widget_colors_recursive(self.root, theme)
        self.populate_properties_panel()
        self.redraw_flowchart()
        state_color_map = { 'blue': theme['status_blue'], 'green': theme['status_green'], 'orange': theme['status_orange'], 'red': theme['status_red'] }
        new_color = state_color_map.get(self.status_label_color_state, theme['status_blue'])
        self.status_label.config(foreground=new_color)
        
        self.root.after(10, self._set_title_bar_color)

    def _set_title_bar_color(self):
        """
        Applies the custom title bar color after a short delay to ensure the window is ready.
        This is a Windows-only feature.
        """
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            # First, set the window to dark mode (attribute 20)
            true_value = ctypes.c_bool(True)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(true_value), ctypes.sizeof(true_value))
            
            # Then, set the custom colors for caption (35) and border (34)
            title_bar_color = 0x003A312C # Dark Grey
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(ctypes.c_int(title_bar_color)), ctypes.sizeof(ctypes.c_int(title_bar_color)))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(ctypes.c_int(title_bar_color)), ctypes.sizeof(ctypes.c_int(title_bar_color)))
        except (AttributeError, TypeError):
            # Fails gracefully on non-Windows systems or if the call fails
            pass

    def update_widget_colors_recursive(self, widget, theme):
        widget_class = widget.winfo_class()
        try:
            if widget_class not in ('Canvas', 'Entry', 'Toplevel', 'ScrolledText', 'Text', 'TMenubutton', 'Treeview'):
                widget.config(bg=theme['bg'])
            if 'fg' in widget.config() and widget_class not in ('Button'):
                widget.config(fg=theme['fg'])
            
            if widget_class in ('Entry', 'Text'):
                widget.config(bg=theme['entry_bg'], fg=theme['entry_fg'], insertbackground=theme['text'])
            elif widget_class == 'ScrolledText':
                widget.config(bg=theme['log'], fg=theme['text'], insertbackground=theme['text'])
            elif widget_class == 'Radiobutton':
                widget.config(selectcolor=theme['entry_bg'], activebackground=theme['entry_bg'], highlightbackground=theme['bg'], highlightcolor=theme['bg'])
            elif widget_class == 'TMenubutton':
                widget.config(background=theme['entry_bg'])
            elif widget_class == 'Button':
                color_map = {
                    "Color Step": 'accent_green', "PNG Step": 'accent_blue', "Click / Press Step": 'accent_grey',
                    "Logical Step": 'accent_yellow', "Reset All": 'accent_red',
                    "Delete": 'accent_red', "Duplicate": 'accent_grey', "Snip": 'accent_yellow',
                    "Apply Changes": 'accent_green', "Apply Global Settings": 'accent_green',
                    "Run Test": 'accent_green', "Add Note": 'accent_teal', "Find Profitable": 'accent_teal',
                    "Fetch & Calculate Price": 'accent_purple'
                }
                bg_key = next((key for name, key in color_map.items() if name in widget.cget('text')), 'accent_grey')
                widget.config(bg=theme[bg_key], fg=theme['btn_fg'], activebackground=theme['entry_bg'], activeforeground=theme['fg'], relief=tk.FLAT, borderwidth=0)
        except (tk.TclError, AttributeError):
            pass # Ignore errors for widgets that don't support these properties
        for child in widget.winfo_children():
            self.update_widget_colors_recursive(child, theme)

    def on_closing(self):
        if getattr(self, 'hotkey_listener', None) is not None:
            try: self.hotkey_listener.stop()
            except Exception: pass
            self.hotkey_listener = None
        self._destroy_picker_overlay()
        self.destroy_all_overlays()
        self._stop_ge_auto_updater()
        if self.running: self.stop()
        self.root.destroy()

    def build_ui(self):
        main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL); main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        canvas_container = ttk.LabelFrame(main_pane, text="Flowchart Editor", padding=5)
        
        search_frame = ttk.Frame(canvas_container)
        search_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 5))
        ttk.Label(search_frame, text="Search:").pack(side=tk.LEFT, padx=(2, 5))
        search_entry = ttk.Entry(search_frame, textvariable=self.search_query)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        search_btn = ttk.Button(search_frame, text="Find", command=self.search_flowchart)
        search_btn.pack(side=tk.LEFT, padx=(5, 2))
        clear_btn = ttk.Button(search_frame, text="Clear", command=self.clear_search)
        clear_btn.pack(side=tk.LEFT, padx=(0, 2))
        search_entry.bind('<Return>', self.search_flowchart)
        
        h_scroll = ttk.Scrollbar(canvas_container, orient=tk.HORIZONTAL); v_scroll = ttk.Scrollbar(canvas_container, orient=tk.VERTICAL); self.canvas = tk.Canvas(canvas_container, bg="#3c3c3c", highlightthickness=0, xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set); h_scroll.config(command=self.canvas.xview); v_scroll.config(command=self.canvas.yview); h_scroll.pack(side=tk.BOTTOM, fill=tk.X); v_scroll.pack(side=tk.RIGHT, fill=tk.Y); self.canvas.pack(fill=tk.BOTH, expand=True); main_pane.add(canvas_container, weight=3); self.canvas.bind("<ButtonPress-1>", self.on_canvas_press); self.canvas.bind("<B1-Motion>", self.on_drag_motion); self.canvas.bind("<ButtonRelease-1>", self.on_drag_release); self._bind_mouse_scroll()
        right_panel = ttk.Frame(main_pane); right_panel.pack(fill=tk.Y); main_pane.add(right_panel, weight=1)
        
        status_display_frame = ttk.Frame(right_panel, padding=5); status_display_frame.pack(fill=tk.X, pady=(5, 5))
        header_frame = ttk.Frame(status_display_frame); header_frame.pack(fill=tk.X)
        self.status_label = ttk.Label(header_frame, text="Status: Stopped", anchor="w", font=('Helvetica', 11, 'bold')); self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.cycle_time_label = ttk.Label(header_frame, textvariable=self.cycle_time_display, anchor='e', font=('Helvetica', 10)); self.cycle_time_label.pack(side=tk.RIGHT)
        self.timeout_countdown_label = ttk.Label(status_display_frame, text="", anchor='w', font=('Helvetica', 9, 'italic')); self.timeout_countdown_label.pack(fill=tk.X)
        self.delay_countdown_label = ttk.Label(status_display_frame, text="", anchor='w', font=('Helvetica', 9, 'italic')); self.delay_countdown_label.pack(fill=tk.X)

        detection_info_frame = ttk.LabelFrame(right_panel, text="Live Detection Info", padding=5); detection_info_frame.pack(fill=tk.X, padx=5, pady=(0, 10)); ttk.Label(detection_info_frame, textvariable=self.last_detection_info, anchor='w', font=('Consolas', 10)).pack(fill=tk.X)

        # --- EDIT START: Implement vertical PanedWindow for resizable tabs/buttons ---
        # 1. Create a new vertical PanedWindow inside the main right_panel
        right_sub_pane = ttk.PanedWindow(right_panel, orient=tk.VERTICAL)
        right_sub_pane.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        # 2. Change the parent of the notebook to the new sub-pane. Do NOT .pack() it.
        notebook = ttk.Notebook(right_sub_pane)
        self.props_tab = ttk.Frame(notebook, padding=10); globals_tab = ttk.Frame(notebook, padding=10); testing_tab = ttk.Frame(notebook, padding=10); log_tab = ttk.Frame(notebook, padding=10); ge_interface_tab = ttk.Frame(notebook, padding=10); info_tab = ttk.Frame(notebook, padding=10)
        notebook.add(self.props_tab, text='Properties'); notebook.add(ge_interface_tab, text='GE Interface'); notebook.add(globals_tab, text='Global Settings'); notebook.add(testing_tab, text='Testing Logic'); notebook.add(log_tab, text='Execution Log'); notebook.add(info_tab, text='Info')
        self.build_properties_panel(); self.build_ge_interface_panel(ge_interface_tab); self.build_globals_panel(globals_tab); self.build_testing_panel(testing_tab); self.build_log_panel(log_tab); self.build_info_panel(info_tab)
        
        # 3. Change the parent of the control_bar to the new sub-pane. Do NOT .pack() it.
        control_bar = ttk.Frame(right_sub_pane, padding=5)

        # 4. Add the notebook and control bar to the pane using .add()
        right_sub_pane.add(notebook, weight=1)      # Give notebook more space by default
        right_sub_pane.add(control_bar, weight=0)   # Give control bar minimum space
        # --- EDIT END ---

        btn_style = {'fg': 'white', 'height': 2, 'font': ('Helvetica', 9, 'bold'), 'relief': tk.FLAT, 'borderwidth': 0}

        add_step_grid = ttk.Frame(control_bar); add_step_grid.pack(fill=tk.X, pady=(0, 5))
        add_step_grid.columnconfigure((0, 1), weight=1)

        grid_btn_style = {'sticky': 'ew', 'padx': 2, 'pady': (0, 3)}
        tk.Button(add_step_grid, text="+ Color Step", **btn_style, command=lambda: self.add_step('color')).grid(row=0, column=0, **grid_btn_style)
        tk.Button(add_step_grid, text="+ PNG Step", **btn_style, command=lambda: self.add_step('png')).grid(row=0, column=1, **grid_btn_style)
        tk.Button(add_step_grid, text="+ Click / Press Step", **btn_style, command=lambda: self.add_step('location')).grid(row=1, column=0, **grid_btn_style)
        tk.Button(add_step_grid, text="+ Logical Step", **btn_style, command=lambda: self.add_step('logical')).grid(row=1, column=1, **grid_btn_style)
        tk.Button(add_step_grid, text="+ Add Note", **btn_style, command=self.add_annotation).grid(row=2, column=0, columnspan=2, **grid_btn_style)
        
        start_frm = ttk.Frame(control_bar); start_frm.pack(fill=tk.X, pady=2); self.start_btn = ttk.Button(start_frm, text="Start (F2)", command=self.start); self.start_btn.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=(0, 5), ipady=5); self.stop_btn = ttk.Button(start_frm, text="Stop (F2)", command=self.stop, state=tk.DISABLED); self.stop_btn.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, ipady=5)
        start_at_frm = ttk.Frame(start_frm); start_at_frm.pack(side=tk.LEFT, fill=tk.NONE, padx=(10, 0)); ttk.Label(start_at_frm, text="Start Step:").pack(anchor='s'); ttk.Entry(start_at_frm, textvariable=self.start_step, width=5).pack(anchor='n', pady=(2,0))
        file_ops_frm = ttk.Frame(control_bar); file_ops_frm.pack(fill=tk.X, pady=(5, 0)); btn_pack_style = {'side': tk.LEFT, 'expand': True, 'fill': tk.X, 'padx': 2}; tk.Button(file_ops_frm, text="Import JSON", **btn_style, command=self.import_from_json).pack(**btn_pack_style); tk.Button(file_ops_frm, text="Export JSON", **btn_style, command=self.export_to_json).pack(**btn_pack_style); tk.Button(file_ops_frm, text="Reset All", **btn_style, command=self.reset_all).pack(**btn_pack_style)
   
    def build_properties_panel(self):
        self.properties_widgets['default_label'] = ttk.Label(self.props_tab, text="\n\nSelect a step or note in the flowchart\nto view and edit its properties.", justify=tk.CENTER, font=('Helvetica', 10)); self.properties_widgets['default_label'].pack(expand=True, fill=tk.BOTH)
        if self.current_theme: self.properties_widgets['default_label'].config(foreground=self.current_theme['node_text_grey'])

    def build_globals_panel(self, parent):
        self._sync_global_settings_ui_from_model()
        parent.columnconfigure(0, weight=1) # Make the single column expandable

        # --- Mouse Movement Section ---
        mouse_lf = ttk.LabelFrame(parent, text="Mouse Movement")
        mouse_lf.grid(row=0, column=0, sticky='ew', pady=(0, 10), padx=2)
        mouse_lf.columnconfigure(1, weight=1)
        
        ttk.Label(mouse_lf, text="Mode:").grid(row=0, column=0, sticky='w', padx=5, pady=5)
        
        mode_radio_frame = ttk.Frame(mouse_lf)
        mode_radio_frame.grid(row=0, column=1, sticky='ew', padx=5, pady=5)
        self.mouse_move_mode.trace_add("write", self._update_mouse_mode_visibility)
        ttk.Radiobutton(mode_radio_frame, text="Regular", variable=self.mouse_move_mode, value="Regular").grid(row=0, column=0, padx=(0, 5))
        ttk.Radiobutton(mode_radio_frame, text="Dynamic", variable=self.mouse_move_mode, value="Dynamic").grid(row=0, column=1, padx=5)
        ttk.Radiobutton(mode_radio_frame, text="Pixels/Sec", variable=self.mouse_move_mode, value="Pixels Per Second").grid(row=0, column=2, padx=5)
        
        # Frame for Regular mode settings
        self.regular_speed_frame = ttk.Frame(mouse_lf)
        self.regular_speed_frame.grid(row=1, column=0, columnspan=2, sticky='ew', padx=5)
        self.regular_speed_frame.columnconfigure(1, weight=1)
        ttk.Label(self.regular_speed_frame, text="Base Mouse Speed (s):").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(self.regular_speed_frame, textvariable=self.global_settings_ui_vars['mouse_speed'], width=10).grid(row=0, column=1, sticky="ew", pady=2)

        # Frame for Dynamic mode settings
        self.dynamic_speed_frame = ttk.Frame(mouse_lf)
        self.dynamic_speed_frame.grid(row=2, column=0, columnspan=2, sticky='ew', padx=5)
        self.dynamic_speed_frame.columnconfigure(1, weight=1)
        ttk.Label(self.dynamic_speed_frame, text="Min Move Time (s):").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(self.dynamic_speed_frame, textvariable=self.global_settings_ui_vars['min_move_time'], width=10).grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(self.dynamic_speed_frame, text="Max Move Time (s):").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Entry(self.dynamic_speed_frame, textvariable=self.global_settings_ui_vars['max_move_time'], width=10).grid(row=1, column=1, sticky="ew", pady=2)

        # Frame for Pixels Per Second mode settings
        self.pps_speed_frame = ttk.Frame(mouse_lf)
        self.pps_speed_frame.grid(row=3, column=0, columnspan=2, sticky='ew', padx=5)
        self.pps_speed_frame.columnconfigure(1, weight=1)
        ttk.Label(self.pps_speed_frame, text="Pixels Per Second:").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(self.pps_speed_frame, textvariable=self.global_settings_ui_vars['pixels_per_second'], width=10).grid(row=0, column=1, sticky="ew", pady=2)

        self._update_mouse_mode_visibility()

        # --- Click Variation Section ---
        variation_lf = ttk.LabelFrame(parent, text="Click Variation")
        variation_lf.grid(row=1, column=0, sticky='ew', pady=(0, 10), padx=2)
        variation_lf.columnconfigure(1, weight=1)
        ttk.Label(variation_lf, text="Location Offset (±px):").grid(row=0, column=0, sticky="w", pady=2, padx=5)
        ttk.Entry(variation_lf, textvariable=self.global_settings_ui_vars['loc_offset_variance'], width=10).grid(row=0, column=1, sticky="ew", pady=2, padx=5)
        ttk.Label(variation_lf, text="Speed Variance (±s):").grid(row=1, column=0, sticky="w", pady=2, padx=5)
        ttk.Entry(variation_lf, textvariable=self.global_settings_ui_vars['speed_variance'], width=10).grid(row=1, column=1, sticky="ew", pady=2, padx=5)
        ttk.Label(variation_lf, text="Hold Variance (±s):").grid(row=2, column=0, sticky="w", pady=2, padx=5)
        ttk.Entry(variation_lf, textvariable=self.global_settings_ui_vars['hold_duration_variance'], width=10).grid(row=2, column=1, sticky="ew", pady=2, padx=5)
        
        # --- Global Timings Section ---
        timing_lf = ttk.LabelFrame(parent, text="Global Timings")
        timing_lf.grid(row=2, column=0, sticky='ew', pady=(0, 10), padx=2)
        timing_lf.columnconfigure(1, weight=1)
        ttk.Label(timing_lf, text="Scan Interval (s):").grid(row=0, column=0, sticky="w", pady=2, padx=5)
        ttk.Entry(timing_lf, textvariable=self.global_settings_ui_vars['scan_interval'], width=10).grid(row=0, column=1, sticky="ew", pady=2, padx=5)
        ttk.Label(timing_lf, text="Base Hold Duration (s):").grid(row=1, column=0, sticky="w", pady=2, padx=5)
        ttk.Entry(timing_lf, textvariable=self.global_settings_ui_vars['hold_duration'], width=10).grid(row=1, column=1, sticky="ew", pady=2, padx=5)

        # --- Flowchart Grid Section ---
        flowchart_lf = ttk.LabelFrame(parent, text="Flowchart Grid")
        flowchart_lf.grid(row=3, column=0, sticky='ew', pady=(0, 10), padx=2)
        flowchart_lf.columnconfigure(1, weight=1)
        ttk.Checkbutton(flowchart_lf, text="Show Grid", variable=self.grid_visible, command=self.redraw_flowchart).grid(row=0, column=0, columnspan=2, sticky='w', pady=2, padx=5)
        ttk.Checkbutton(flowchart_lf, text="Enable Grid Latching", variable=self.grid_latching).grid(row=1, column=0, columnspan=2, sticky='w', pady=2, padx=5)
        ttk.Label(flowchart_lf, text="Grid Spacing (px):").grid(row=2, column=0, sticky="w", pady=2, padx=5)
        ttk.Entry(flowchart_lf, textvariable=self.global_settings_ui_vars['grid_spacing'], width=10).grid(row=2, column=1, sticky="ew", pady=2, padx=5)
        ttk.Label(flowchart_lf, text="Grid Opacity:").grid(row=3, column=0, sticky="w", pady=2, padx=5)
        ttk.Scale(flowchart_lf, from_=0.0, to=1.0, orient=tk.HORIZONTAL, variable=self.grid_opacity, command=lambda e: self.redraw_flowchart()).grid(row=3, column=1, sticky="ew", pady=2, padx=5)
        
        # --- Global Area Section ---
        garea_lf = ttk.LabelFrame(parent, text="Global Area (F4)")
        garea_lf.grid(row=4, column=0, sticky='ew', pady=(0, 10), padx=2)
        garea_lf.columnconfigure(0, weight=1)
        area_frame=ttk.Frame(garea_lf)
        area_frame.grid(row=0,column=0,sticky="ew")
        area_vars = [self.global_settings_ui_vars['area_x1'], self.global_settings_ui_vars['area_y1'], self.global_settings_ui_vars['area_x2'], self.global_settings_ui_vars['area_y2']]
        for i, var in enumerate(area_vars):
            entry = ttk.Entry(area_frame, textvariable=var, width=7)
            entry.grid(row=0, column=i, padx=2, sticky='ew')
            area_frame.columnconfigure(i, weight=1)
        btn_frame = ttk.Frame(garea_lf)
        btn_frame.grid(row=1, column=0, sticky="ew", pady=(5,0))
        btn_frame.columnconfigure((0,1), weight=1)
        tk.Button(btn_frame, text="Select Area (F4)", font=('Helvetica', 9, 'bold'), command=self.select_area_mode, relief=tk.FLAT).grid(row=0, column=0, sticky='ew', padx=(0,1))
        tk.Button(btn_frame, text="Full Screen", font=('Helvetica', 9, 'bold'), command=self.set_global_area_to_fullscreen, relief=tk.FLAT).grid(row=0, column=1, sticky='ew', padx=(1,0))

        # --- Convenience Section ---
        convenience_lf = ttk.LabelFrame(parent, text="Convenience")
        convenience_lf.grid(row=5, column=0, sticky='ew', pady=(0, 10), padx=2)
        ttk.Checkbutton(convenience_lf, text="Hide Window on Capture (F3/F4)", variable=self.hide_on_select, onvalue=True, offvalue=False).grid(row=0, column=0, sticky='w', pady=1, padx=5)
        ttk.Checkbutton(convenience_lf, text="Enable all 'Show Area' overlays", variable=self.enable_all_show_area, command=self.update_all_area_overlays).grid(row=1, column=0, sticky='w', pady=1, padx=5)
        ttk.Checkbutton(convenience_lf, text="Update 'Start Step' when stopped", variable=self.start_at_stopped_pos).grid(row=2, column=0, sticky='w', pady=1, padx=5)
        
        # --- Apply Button ---
        tk.Button(parent, text="Apply Global Settings", font=('Helvetica', 10, 'bold'), command=self.apply_global_settings, relief=tk.FLAT).grid(row=6, column=0, sticky='ew', pady=(5,5), ipady=4)

    def build_log_panel(self, parent):
        log_controls_frame = ttk.Frame(parent); log_controls_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(log_controls_frame, text="Search:").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Entry(log_controls_frame, textvariable=self.log_search_query, width=20).pack(side=tk.LEFT, expand=True, fill=tk.X)
        
        tk.Button(log_controls_frame, text="Clear", command=self.clear_log, font=('Helvetica', 9), relief=tk.FLAT).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Label(log_controls_frame, text="Auto-clear (lines):").pack(side=tk.LEFT, padx=(10, 5))
        ttk.Entry(log_controls_frame, textvariable=self.log_auto_clear_lines, width=6).pack(side=tk.LEFT)
        
        self.log_text = scrolledtext.ScrolledText(parent,state='disabled',wrap=tk.WORD,borderwidth=0,highlightthickness=1); self.log_text.pack(fill=tk.BOTH,expand=True)
        if self.current_theme: self.log_text.config(highlightbackground=self.current_theme['node_border'], highlightcolor=self.current_theme['node_border'])

    def build_info_panel(self, parent):
        info_frame = ttk.Frame(parent, padding=10)
        info_frame.pack(fill=tk.BOTH, expand=True)

        info_frame.columnconfigure(1, weight=1)

        header_font = ('Helvetica', 11, 'bold')
        label_font = ('Helvetica', 10, 'bold')
        value_font = ('Helvetica', 10)
        
        ttk.Label(info_frame, text="Application Information", font=header_font).grid(row=0, column=0, columnspan=2, pady=(0, 15), sticky='w')

        info_data = {
            "Application:": "Flowchart Automation Tool",
            "Version #:": __version__,
            "Description:": "A visual, node-based automation tool for creating and running complex task sequences using image, color, and text (OCR) detection.",
            "Last Updated:": "October 1, 2025",
            "Creator:": "u/WonRu2",
            "Key Dependencies:": "Tkinter, OpenCV-Python, PyAutoGUI, Keyboard, Pytesseract (Tesseract-OCR), Pillow",
            "License:": "Freeware"
        }
        
        row_num = 1
        for label_text, value_text in info_data.items():
            ttk.Label(info_frame, text=label_text, font=label_font).grid(row=row_num, column=0, sticky='nw', padx=(0, 10), pady=4)
            ttk.Label(info_frame, text=value_text, font=value_font, wraplength=400).grid(row=row_num, column=1, sticky='w', pady=4)
            row_num += 1

    def build_testing_panel(self, parent):
        self.test_area_buttons = []
        type_frame = ttk.Frame(parent); type_frame.pack(fill=tk.X, pady=(0, 10)); ttk.Label(type_frame, text="Test Type:", font=('Helvetica', 10, 'bold')).pack(side=tk.LEFT, padx=(0, 10)); ttk.Radiobutton(type_frame, text="PNG", variable=self.active_test_type, value="PNG", command=self._update_test_panel_visibility).pack(side=tk.LEFT); ttk.Radiobutton(type_frame, text="Color", variable=self.active_test_type, value="Color", command=self._update_test_panel_visibility).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(type_frame, text="PNG Count", variable=self.active_test_type, value="PNG Count", command=self._update_test_panel_visibility).pack(side=tk.LEFT)
        ttk.Radiobutton(type_frame, text="Color Count", variable=self.active_test_type, value="Color Count", command=self._update_test_panel_visibility).pack(side=tk.LEFT, padx=10)
        if PYTESSERACT_AVAILABLE: ttk.Radiobutton(type_frame, text="Number", variable=self.active_test_type, value="Number", command=self._update_test_panel_visibility).pack(side=tk.LEFT, padx=10)
        
        self.png_test_frame = ttk.LabelFrame(parent, text="PNG Test Settings")
        png_mode_frm = ttk.Frame(self.png_test_frame); png_mode_frm.grid(row=0, columnspan=3, sticky='w', pady=(0,5)); tk.Radiobutton(png_mode_frm, text="File", variable=self.test_png_mode, value='file').pack(side=tk.LEFT); tk.Radiobutton(png_mode_frm, text="Folder", variable=self.test_png_mode, value='folder').pack(side=tk.LEFT, padx=10)
        path_frm = ttk.Frame(self.png_test_frame); path_frm.grid(row=1, columnspan=3, sticky='ew', pady=5)
        tk.Button(path_frm, text="Snip", command=self.snip_image_for_test, font=('Helvetica', 9), relief=tk.FLAT).pack(side=tk.LEFT, padx=(0,5))
        tk.Button(path_frm, text="Browse", command=self.browse_for_test_path, font=('Helvetica', 9), relief=tk.FLAT).pack(side=tk.LEFT)
        self.test_path_label = ttk.Label(path_frm, textvariable=self.test_png_path_display, anchor='w', wraplength=200, justify='left'); self.test_path_label.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Label(self.png_test_frame, text="Threshold:").grid(row=2, column=0, sticky='w', pady=5); ttk.Entry(self.png_test_frame, textvariable=self.test_png_threshold, width=10).grid(row=2, column=1, sticky='w');
        
        ttk.Label(self.png_test_frame, text="Image Mode:").grid(row=3, column=0, sticky='w', pady=5);
        ttk.OptionMenu(self.png_test_frame, self.test_png_image_mode, 'Grayscale', 'Grayscale', 'Color', 'Binary (B&W)').grid(row=3, column=1, sticky='ew')
        
        self.test_png_area_btn = tk.Button(self.png_test_frame, text="Select Area", command=self.select_area_for_test, font=('Helvetica', 9), relief=tk.FLAT); self.test_png_area_btn.grid(row=2, column=2, rowspan=2, sticky='e', padx=5); self.png_test_frame.columnconfigure(2, weight=1)
        self.test_area_buttons.append(self.test_png_area_btn)

        self.color_test_frame = ttk.LabelFrame(parent, text="Color Test Settings")
        tk.Button(self.color_test_frame, text="Pick Color (F3)", font=('Helvetica', 9), command=lambda: self.enter_f3_mode('pick_test_color'), relief=tk.FLAT).grid(row=0, column=0, sticky='w', pady=2); self.test_color_swatch = tk.Label(self.color_test_frame, text=" ", bg=self.rgb_to_hex(self.test_color_rgb), relief=tk.SUNKEN, width=3); self.test_color_swatch.grid(row=0, column=1, padx=4)
        ttk.Label(self.color_test_frame, text="Tolerance:").grid(row=0, column=2, sticky='w', padx=(10,2)); ttk.Entry(self.color_test_frame, textvariable=self.test_color_tolerance, width=10).grid(row=0, column=3, sticky='w')
        ttk.Label(self.color_test_frame, text="Color Space:").grid(row=1, column=0, columnspan=2, sticky='w', pady=5)
        ttk.OptionMenu(self.color_test_frame, self.test_color_space, 'HSV', 'HSV', 'RGB').grid(row=1, column=2, columnspan=2, sticky='ew')
        self.test_color_area_btn = tk.Button(self.color_test_frame, text="Select Area", command=self.select_area_for_test, font=('Helvetica', 9), relief=tk.FLAT); self.test_color_area_btn.grid(row=0, column=4, rowspan=2, sticky='e', padx=5); self.color_test_frame.columnconfigure(4, weight=1)
        self.test_area_buttons.append(self.test_color_area_btn)

        self.color_count_test_frame = ttk.LabelFrame(parent, text="Color Count Test Settings")
        tk.Button(self.color_count_test_frame, text="Pick Color (F3)", font=('Helvetica', 9), command=lambda: self.enter_f3_mode('pick_test_color'), relief=tk.FLAT).grid(row=0, column=0, sticky='w', pady=2)
        self.test_color_swatch_count = tk.Label(self.color_count_test_frame, text=" ", bg=self.rgb_to_hex(self.test_color_rgb), relief=tk.SUNKEN, width=3); self.test_color_swatch_count.grid(row=0, column=1, padx=4)
        ttk.Label(self.color_count_test_frame, text="Tolerance:").grid(row=0, column=2, sticky='w', padx=(10,2)); ttk.Entry(self.color_count_test_frame, textvariable=self.test_color_tolerance, width=10).grid(row=0, column=3, sticky='w')
        ttk.Label(self.color_count_test_frame, text="Min Area (px):").grid(row=1, column=0, sticky='w', pady=2); ttk.Entry(self.color_count_test_frame, textvariable=self.test_color_min_area, width=10).grid(row=1, column=1, sticky='w', padx=2)
        ttk.Label(self.color_count_test_frame, text="Color Space:").grid(row=1, column=2, sticky='w', padx=(10,2)); ttk.OptionMenu(self.color_count_test_frame, self.test_color_space, 'HSV', 'HSV', 'RGB').grid(row=1, column=3, sticky='ew')
        ttk.Label(self.color_count_test_frame, text="Expression:").grid(row=2, column=0, sticky='w', pady=5); ttk.Entry(self.color_count_test_frame, textvariable=self.test_color_count_expression, width=15).grid(row=2, column=1, columnspan=3, sticky='ew', pady=5)
        self.test_color_count_area_btn = tk.Button(self.color_count_test_frame, text="Select Area", command=self.select_area_for_test, font=('Helvetica', 9), relief=tk.FLAT); self.test_color_count_area_btn.grid(row=0, column=4, rowspan=3, sticky='e', padx=5); self.color_count_test_frame.columnconfigure(4, weight=1)
        self.test_area_buttons.append(self.test_color_count_area_btn)

        self.number_test_frame = ttk.LabelFrame(parent, text="Number Test Settings")
        ttk.Label(self.number_test_frame, text="Expression:").grid(row=0, column=0, sticky='w', pady=5); ttk.Entry(self.number_test_frame, textvariable=self.test_number_expression, width=15).grid(row=0, column=1, columnspan=3, sticky='ew', pady=5)
        ttk.Label(self.number_test_frame, text="OEM:").grid(row=1, column=0, sticky='w', pady=5)
        ttk.OptionMenu(self.number_test_frame, self.test_number_oem, self.test_number_oem.get(), *self.oem_options.keys()).grid(row=1, column=1, columnspan=3, sticky='ew')
        ttk.Label(self.number_test_frame, text="PSM:").grid(row=2, column=0, sticky='w', pady=5)
        ttk.OptionMenu(self.number_test_frame, self.test_number_psm, self.test_number_psm.get(), *self.psm_options.keys()).grid(row=2, column=1, columnspan=3, sticky='ew')
        self.test_number_area_btn = tk.Button(self.number_test_frame, text="Select Area", command=self.select_area_for_test, font=('Helvetica', 9), relief=tk.FLAT); self.test_number_area_btn.grid(row=0, column=4, rowspan=3, sticky='e', padx=5)
        self.number_test_frame.columnconfigure(4, weight=1)
        self.test_area_buttons.append(self.test_number_area_btn)

        self.png_count_test_frame = ttk.LabelFrame(parent, text="PNG Count Test Settings")
        png_count_mode_frm = ttk.Frame(self.png_count_test_frame); png_count_mode_frm.grid(row=0, columnspan=3, sticky='w', pady=(0,5)); tk.Radiobutton(png_count_mode_frm, text="File", variable=self.test_png_mode, value='file').pack(side=tk.LEFT); tk.Radiobutton(png_count_mode_frm, text="Folder", variable=self.test_png_mode, value='folder').pack(side=tk.LEFT, padx=10)
        path_frm_count = ttk.Frame(self.png_count_test_frame); path_frm_count.grid(row=1, columnspan=3, sticky='ew', pady=5)
        tk.Button(path_frm_count, text="Snip", command=self.snip_image_for_test, font=('Helvetica', 9), relief=tk.FLAT).pack(side=tk.LEFT, padx=(0,5))
        tk.Button(path_frm_count, text="Browse", command=self.browse_for_test_path, font=('Helvetica', 9), relief=tk.FLAT).pack(side=tk.LEFT)
        ttk.Label(path_frm_count, textvariable=self.test_png_path_display, anchor='w', wraplength=200, justify='left').pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Label(self.png_count_test_frame, text="Threshold:").grid(row=2, column=0, sticky='w', pady=5); ttk.Entry(self.png_count_test_frame, textvariable=self.test_png_threshold, width=10).grid(row=2, column=1, sticky='w');
        ttk.Label(self.png_count_test_frame, text="Image Mode:").grid(row=3, column=0, sticky='w', pady=5);
        ttk.OptionMenu(self.png_count_test_frame, self.test_png_image_mode, 'Grayscale', 'Grayscale', 'Color', 'Binary (B&W)').grid(row=3, column=1, sticky='ew')
        ttk.Label(self.png_count_test_frame, text="Expression:").grid(row=4, column=0, sticky='w', pady=5); ttk.Entry(self.png_count_test_frame, textvariable=self.test_png_count_expression, width=15).grid(row=4, column=1, sticky='ew', pady=5)
        self.test_png_count_area_btn = tk.Button(self.png_count_test_frame, text="Select Area", command=self.select_area_for_test, font=('Helvetica', 9), relief=tk.FLAT); self.test_png_count_area_btn.grid(row=2, column=2, rowspan=3, sticky='e', padx=5); self.png_count_test_frame.columnconfigure(2, weight=1)
        self.test_area_buttons.append(self.test_png_count_area_btn)

        tk.Button(parent, text="Run Test", font=('Helvetica', 10, 'bold'), command=self.run_test, relief=tk.FLAT).pack(fill=tk.X, pady=(15, 5), ipady=4); self.test_results_text = scrolledtext.ScrolledText(parent, state='disabled', wrap=tk.WORD, height=8, borderwidth=0, highlightthickness=1); self.test_results_text.pack(fill=tk.BOTH, expand=True, pady=(5,0))
        if self.current_theme: self.test_results_text.config(highlightbackground=self.current_theme['node_border'], highlightcolor=self.current_theme['node_border'])
        self._update_test_panel_visibility()

    def _update_test_panel_visibility(self):
        self.png_test_frame.pack_forget(); self.color_test_frame.pack_forget(); self.number_test_frame.pack_forget(); self.png_count_test_frame.pack_forget(); self.color_count_test_frame.pack_forget()
        active_type = self.active_test_type.get()
        if active_type == "PNG": self.png_test_frame.pack(fill=tk.X, pady=5)
        elif active_type == "Color": self.color_test_frame.pack(fill=tk.X, pady=5)
        elif active_type == "PNG Count": self.png_count_test_frame.pack(fill=tk.X, pady=5)
        elif active_type == "Color Count": self.color_count_test_frame.pack(fill=tk.X, pady=5)
        elif active_type == "Number": self.number_test_frame.pack(fill=tk.X, pady=5)

    def build_ge_interface_panel(self, parent):
        # --- Item Input ---
        input_lf = ttk.LabelFrame(parent, text="Item & Quantity")
        input_lf.pack(fill=tk.X, padx=5, pady=5)
        input_lf.columnconfigure(1, weight=1)
        ttk.Label(input_lf, text="Item Name:").grid(row=0, column=0, sticky='w', padx=5, pady=5)
        ttk.Entry(input_lf, textvariable=self.ge_interface_item_name).grid(row=0, column=1, sticky='ew', padx=5, pady=5)
        ttk.Label(input_lf, text="Quantity:").grid(row=1, column=0, sticky='w', padx=5, pady=5)
        ttk.Entry(input_lf, textvariable=self.ge_interface_item_quantity).grid(row=1, column=1, sticky='ew', padx=5, pady=5)
        
        # --- Main frame for strategies ---
        strategy_frame = ttk.Frame(parent)
        strategy_frame.pack(fill=tk.X, padx=5, pady=5)
        strategy_frame.columnconfigure((0, 1), weight=1)

        # --- Buy Strategy ---
        buy_strategy_lf = ttk.LabelFrame(strategy_frame, text="Buy Strategy")
        buy_strategy_lf.grid(row=0, column=0, sticky='nsew', padx=(0, 2))
        buy_strategy_options = ["Insta-Buy", "+5%", "-5%", "Custom Price", "Flip-Buy (use Insta-Sell)", "Flip-Buy (Insta-Sell + Margin)"]
        buy_om = ttk.OptionMenu(buy_strategy_lf, self.ge_interface_buy_price_strategy, self.ge_interface_buy_price_strategy.get(), *buy_strategy_options, command=self._toggle_ge_buy_options)
        buy_om.pack(fill=tk.X, padx=5, pady=5)
        self.ge_buy_custom_price_entry = ttk.Entry(buy_strategy_lf, textvariable=self.ge_interface_buy_custom_price, width=15)
        self.ge_buy_margin_entry = ttk.Entry(buy_strategy_lf, textvariable=self.ge_interface_buy_price_margin, width=15)

        # --- Sell Strategy ---
        sell_strategy_lf = ttk.LabelFrame(strategy_frame, text="Sell Strategy")
        sell_strategy_lf.grid(row=0, column=1, sticky='nsew', padx=(2, 0))
        sell_strategy_options = ["Insta-Sell", "+5%", "-5%", "Custom Price", "Flip-Sell (use Insta-Buy)", "Flip-Sell (Insta-Buy - Margin)"]
        sell_om = ttk.OptionMenu(sell_strategy_lf, self.ge_interface_sell_price_strategy, self.ge_interface_sell_price_strategy.get(), *sell_strategy_options, command=self._toggle_ge_sell_options)
        sell_om.pack(fill=tk.X, padx=5, pady=5)
        self.ge_sell_custom_price_entry = ttk.Entry(sell_strategy_lf, textvariable=self.ge_interface_sell_custom_price, width=15)
        self.ge_sell_margin_entry = ttk.Entry(sell_strategy_lf, textvariable=self.ge_interface_sell_price_margin, width=15)

        self._toggle_ge_buy_options()
        self._toggle_ge_sell_options()

        # --- Auto-Update ---
        auto_update_lf = ttk.LabelFrame(parent, text="Auto-Update")
        auto_update_lf.pack(fill=tk.X, padx=5, pady=5)
        ttk.Checkbutton(auto_update_lf, text="Enable Auto-Update", variable=self.ge_auto_update_enabled).pack(side=tk.LEFT, padx=5)
        ttk.Label(auto_update_lf, text="Interval (s):").pack(side=tk.LEFT, padx=(10, 2))
        ttk.Entry(auto_update_lf, textvariable=self.ge_auto_update_interval, width=8).pack(side=tk.LEFT, padx=2)

        # --- Actions & Results ---
        results_lf = ttk.LabelFrame(parent, text="Actions & Results")
        results_lf.pack(fill=tk.X, padx=5, pady=5)
        results_lf.columnconfigure(1, weight=1)
        
        tk.Button(results_lf, text="Find Profitable Flips...", font=('Helvetica', 9, 'bold'), command=self.open_deal_finder_window, relief=tk.FLAT).grid(row=0, column=0, columnspan=2, sticky='ew', padx=5, pady=(5,0))
        tk.Button(results_lf, text="Fetch & Calculate Price", font=('Helvetica', 10, 'bold'), command=self.update_ge_interface_price, relief=tk.FLAT).grid(row=1, column=0, columnspan=2, sticky='ew', padx=5, pady=5, ipady=4)
        
        ttk.Label(results_lf, text="Calculated Buy Price:").grid(row=2, column=0, sticky='w', padx=5, pady=2)
        ttk.Label(results_lf, textvariable=self.ge_interface_display_buy_price, font=('Consolas', 10, 'bold')).grid(row=2, column=1, sticky='w', padx=5, pady=2)
        ttk.Label(results_lf, text="Total Buy Value:").grid(row=3, column=0, sticky='w', padx=5, pady=2)
        ttk.Label(results_lf, textvariable=self.ge_interface_display_buy_total, font=('Consolas', 10, 'bold')).grid(row=3, column=1, sticky='w', padx=5, pady=2)
        ttk.Label(results_lf, text="Calculated Sell Price:").grid(row=4, column=0, sticky='w', padx=5, pady=2)
        ttk.Label(results_lf, textvariable=self.ge_interface_display_sell_price, font=('Consolas', 10, 'bold')).grid(row=4, column=1, sticky='w', padx=5, pady=2)
        ttk.Label(results_lf, text="Total Sell Value:").grid(row=5, column=0, sticky='w', padx=5, pady=2)
        ttk.Label(results_lf, textvariable=self.ge_interface_display_sell_total, font=('Consolas', 10, 'bold')).grid(row=5, column=1, sticky='w', padx=5, pady=2)

    def _calculate_ge_price(self, action_type, high_price, low_price):
        """Calculates a final price based on the strategy for either 'buy' or 'sell'."""
        if action_type == 'buy':
            strategy = self.ge_interface_buy_price_strategy.get()
            custom_price = int(self.ge_interface_buy_custom_price.get())
            margin = int(self.ge_interface_buy_price_margin.get())
            
            if strategy == 'Insta-Buy': return high_price
            if strategy == '+5%': return int(high_price * 1.05)
            if strategy == '-5%': return int(high_price * 0.95)
            if strategy == 'Custom Price': return custom_price
            if strategy == 'Flip-Buy (use Insta-Sell)': return low_price
            if strategy == 'Flip-Buy (Insta-Sell + Margin)': return low_price + margin
            return high_price # Default
        else: # sell
            strategy = self.ge_interface_sell_price_strategy.get()
            custom_price = int(self.ge_interface_sell_custom_price.get())
            margin = int(self.ge_interface_sell_price_margin.get())
            
            if strategy == 'Insta-Sell': return low_price
            if strategy == '+5%': return int(low_price * 1.05)
            if strategy == '-5%': return int(low_price * 0.95)
            if strategy == 'Custom Price': return custom_price
            if strategy == 'Flip-Sell (use Insta-Buy)': return high_price
            if strategy == 'Flip-Sell (Insta-Buy - Margin)': return high_price - margin
            return low_price # Default

    def _reset_search(self, *args):
        """Resets the search index whenever the search query is modified."""
        self.search_results = []
        self.current_search_index = -1

    def search_flowchart(self, event=None):
        """Finds and navigates to the next item matching the search query."""
        query = self.search_query.get().lower()
        if not query:
            return

        # If it's a new search, populate the results list
        if not self.search_results:
            # Search Steps
            for i, step in enumerate(self.steps):
                # Build a string of all searchable content for the step
                content = f"step {i+1} " + str(step.get('name', '')).lower()
                if step.get('path'):
                    content += " " + str(os.path.basename(step.get('path'))).lower()
                if step.get('key_to_press'):
                    content += " " + str(step.get('key_to_press')).lower()
                if step.get('text_to_type'):
                    content += " " + str(step.get('text_to_type')).lower()
                if step.get('ge_inject_name'):
                    content += " " + str(step.get('ge_inject_name')).lower()

                # Check for direct step number match or content match
                if query == str(i + 1) or query in content:
                    self.search_results.append({'type': 'step', 'index': i})
            
            # Search Annotations
            for i, note in enumerate(self.annotations):
                if query in str(note.get('text', '')).lower():
                    self.search_results.append({'type': 'note', 'index': i})

        if not self.search_results:
            self.log(f"Search: No results found for '{query}'.")
            return

        # Cycle to the next result
        self.current_search_index = (self.current_search_index + 1) % len(self.search_results)
        found_item = self.search_results[self.current_search_index]
        
        self.log(f"Search: Found item {self.current_search_index + 1}/{len(self.search_results)} at {found_item['type']} index {found_item['index']}.")

        # Highlight, update properties, and redraw
        self.selected_items = [found_item]
        self.populate_properties_panel()
        self.redraw_flowchart()
        
        # Scroll the canvas to the found item
        self.root.after(50, lambda: self._scroll_to_item(found_item))

    def _scroll_to_item(self, item):
        """Calculates position and scrolls the canvas to bring the item into view."""
        item_data = None
        if item['type'] == 'step':
            item_data = self.steps[item['index']]
        elif item['type'] == 'note':
            item_data = self.annotations[item['index']]

        if not item_data:
            return
        
        # Ensure canvas dimensions are up-to-date
        self.canvas.update_idletasks()

        item_x, item_y = item_data.get('x', 0) * self.zoom_factor, item_data.get('y', 0) * self.zoom_factor
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        scroll_region = self.canvas.cget("scrollregion")
        if not scroll_region:
             return
        
        sr_parts = list(map(float, scroll_region.split()))
        sr_x, sr_y, sr_w, sr_h = sr_parts[0], sr_parts[1], sr_parts[2], sr_parts[3]
        total_w, total_h = sr_w - sr_x, sr_h - sr_y

        if total_w > 0 and total_h > 0:
            # Calculate desired top-left corner of the viewport
            target_x = item_x - (canvas_width / 2)
            target_y = item_y - (canvas_height / 2)
            
            # Convert to relative position (0.0 to 1.0) for moveto
            rel_x = max(0.0, target_x / total_w)
            rel_y = max(0.0, target_y / total_h)
            
            self.canvas.xview_moveto(rel_x)
            self.canvas.yview_moveto(rel_y)

    def clear_search(self):
        """Clears the search query and results."""
        self.search_query.set("")
        self._reset_search()
        self.selected_items = []
        self.populate_properties_panel()
        self.redraw_flowchart()
        self.log("Search cleared.")

    def _toggle_ge_buy_options(self, *args):
        strategy = self.ge_interface_buy_price_strategy.get()
        self.ge_buy_custom_price_entry.pack_forget()
        self.ge_buy_margin_entry.pack_forget()
        if strategy == 'Custom Price':
            self.ge_buy_custom_price_entry.pack(padx=5, pady=(0,5), fill=tk.X, expand=True)
        elif 'Margin' in strategy:
            self.ge_buy_margin_entry.pack(padx=5, pady=(0,5), fill=tk.X, expand=True)

    def _toggle_ge_sell_options(self, *args):
        strategy = self.ge_interface_sell_price_strategy.get()
        self.ge_sell_custom_price_entry.pack_forget()
        self.ge_sell_margin_entry.pack_forget()
        if strategy == 'Custom Price':
            self.ge_sell_custom_price_entry.pack(padx=5, pady=(0,5), fill=tk.X, expand=True)
        elif 'Margin' in strategy:
            self.ge_sell_margin_entry.pack(padx=5, pady=(0,5), fill=tk.X, expand=True)

    def _process_ge_price_data_on_main_thread(self, price_data):
        """Processes the fetched GE data and updates the UI. Runs in the main thread."""
        self.ge_interface_last_data = price_data
        try:
            if not isinstance(price_data, dict):
                raise ValueError("API returned no valid price data.")

            high_price = int(price_data.get('high'))
            low_price = int(price_data.get('low'))
            quantity = int(self.ge_interface_item_quantity.get())
            item_name = self.ge_interface_item_name.get()

            # Calculate final prices based on independent strategies
            final_buy_price = self._calculate_ge_price('buy', high_price, low_price)
            final_sell_price = self._calculate_ge_price('sell', high_price, low_price)

            # Update UI display
            self.ge_interface_display_buy_price.set(f"{final_buy_price:,}")
            self.ge_interface_display_buy_total.set(f"{final_buy_price * quantity:,}")
            self.ge_interface_display_sell_price.set(f"{final_sell_price:,}")
            self.ge_interface_display_sell_total.set(f"{final_sell_price * quantity:,}")
            
            self.log(f"GE Interface: Updated prices for {item_name}.")

        except (ValueError, TypeError, KeyError) as e:
            self.ge_interface_display_buy_price.set("Error")
            self.ge_interface_display_buy_total.set("Error")
            self.ge_interface_display_sell_price.set("Error")
            self.ge_interface_display_sell_total.set("Error")
            self.log(f"GE Interface: Failed to process data for '{self.ge_interface_item_name.get()}'. Reason: {e}", "red")

    def _toggle_ge_auto_update(self, *args):
        if self.ge_auto_update_enabled.get():
            self._start_ge_auto_updater()
        else:
            self._stop_ge_auto_updater()

    def _start_ge_auto_updater(self):
        self._stop_ge_auto_updater() # Ensure no duplicates
        self.log("GE auto-updater started.", "green")
        self._run_ge_auto_update_cycle()

    def _stop_ge_auto_updater(self):
        if self.ge_auto_update_after_id:
            self.root.after_cancel(self.ge_auto_update_after_id)
            self.ge_auto_update_after_id = None
            self.log("GE auto-updater stopped.")

    def _run_ge_auto_update_cycle(self):
        if not self.ge_auto_update_enabled.get():
            self._stop_ge_auto_updater()
            return

        self.update_ge_interface_price()
        try:
            interval_ms = int(self.ge_auto_update_interval.get()) * 1000
            if interval_ms > 0:
                 self.ge_auto_update_after_id = self.root.after(interval_ms, self._run_ge_auto_update_cycle)
            else:
                 self.log("Auto-update interval must be greater than 0.", "orange")
                 self.ge_auto_update_enabled.set(False)
        except ValueError:
            self.log("Invalid auto-update interval. Please enter a number.", "orange")
            self.ge_auto_update_enabled.set(False)

    def _toggle_ge_interface_price_options(self, *args):
        strategy = self.ge_interface_price_strategy.get()
        self.ge_custom_price_entry.pack_forget()
        self.ge_margin_entry.pack_forget()
        if strategy == 'Custom Price':
            self.ge_custom_price_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        elif 'Margin' in strategy:
            self.ge_margin_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
            
    def _update_mouse_mode_visibility(self, *args):
        """Shows or hides mouse movement setting frames based on the selected mode."""
        mode = self.mouse_move_mode.get()
        
        if hasattr(self, 'regular_speed_frame'):
            if mode == 'Regular':
                self.regular_speed_frame.grid()
            else:
                self.regular_speed_frame.grid_remove()
                
        if hasattr(self, 'dynamic_speed_frame'):
            if mode == 'Dynamic':
                self.dynamic_speed_frame.grid()
            else:
                self.dynamic_speed_frame.grid_remove()

        if hasattr(self, 'pps_speed_frame'):
            if mode == 'Pixels Per Second':
                self.pps_speed_frame.grid()
            else:
                self.pps_speed_frame.grid_remove()

    def redraw_flowchart(self):
        self.canvas.delete("all")
        self.canvas.config(bg=self.current_theme['canvas'])
        
        # --- NEW: Draw Grid ---
        if self.grid_visible.get():
            self._draw_grid()
        # --- END NEW ---

        for i in self.annotations: self.draw_annotation(i)
        if self.steps:
            for i in range(len(self.steps)): self._calculate_node_size(i)
            for i, step in enumerate(self.steps):
                self.draw_connection(i, 'on_success_action', 'on_success_goto_step')
                draw_timeout = False
                # --- FIX: Added 'Movement Detect' to ensure its timeout arrow is drawn ---
                if step.get('type') not in ['logical'] or step.get('logical_type') in ['Number', 'Wait', 'Movement Detect']:
                    draw_timeout = True
                if draw_timeout:
                    self.draw_connection(i, 'on_timeout_action', 'on_timeout_goto_step')
                if step.get('type') == 'logical' and step.get('logical_type') == 'Count':
                    self.draw_connection(i, 'on_count_reached_action', 'on_count_reached_goto_step')

            for i, step in enumerate(self.steps): self.draw_node(i)

        all_items_bbox = self.canvas.bbox("all")
        if all_items_bbox: self.canvas.config(scrollregion=(all_items_bbox[0]-50, all_items_bbox[1]-50, all_items_bbox[2]+50, all_items_bbox[3]+50))
        if self._marquee_data.get("rect"):
            rect = self._marquee_data["rect"]
            self.canvas.create_rectangle(rect, outline="#3399ff", width=2, dash=(4,2), tags="marquee_rect")

    def _draw_grid(self):
        """Draws the grid lines on the flowchart canvas based on current settings."""
        try:
            spacing = self.grid_spacing.get() * self.zoom_factor
            if spacing < 5: return # Avoid drawing too dense a grid

            canvas_width = self.canvas.winfo_width()
            canvas_height = self.canvas.winfo_height()
            
            scroll_region = self.canvas.bbox("all")
            if not scroll_region:
                x_start, y_start, x_end, y_end = 0, 0, canvas_width, canvas_height
            else:
                x_start, y_start, x_end, y_end = scroll_region

            x_start = min(x_start, self.canvas.canvasx(0))
            y_start = min(y_start, self.canvas.canvasy(0))
            x_end = max(x_end, self.canvas.canvasx(canvas_width))
            y_end = max(y_end, self.canvas.canvasy(canvas_height))

            # --- Calculate color based on opacity ---
            opacity = self.grid_opacity.get()
            grid_hex = self.current_theme.get('accent_grey', '#5C6370').lstrip('#')
            bg_hex = self.current_theme.get('canvas', '#21252B').lstrip('#')
            
            grid_rgb = tuple(int(grid_hex[i:i+2], 16) for i in (0, 2, 4))
            bg_rgb = tuple(int(bg_hex[i:i+2], 16) for i in (0, 2, 4))
            
            final_rgb = tuple(int(gc * opacity + bgc * (1 - opacity)) for gc, bgc in zip(grid_rgb, bg_rgb))
            final_color = self.rgb_to_hex(final_rgb)
            # --- End color calculation ---

            # Draw vertical lines
            for x in range(int(x_start // spacing * spacing), int(x_end), int(spacing)):
                self.canvas.create_line(x, y_start, x, y_end, fill=final_color, tags="grid_line")
            
            # Draw horizontal lines
            for y in range(int(y_start // spacing * spacing), int(y_end), int(spacing)):
                self.canvas.create_line(x_start, y, x_end, y, fill=final_color, tags="grid_line")
            
            self.canvas.tag_lower("grid_line")
        except (ValueError, tk.TclError):
            pass # Handles cases where spacing is invalid or window is not ready

    def _calculate_node_size(self, index):
        step = self.steps[index]; z = self.zoom_factor; title_font = tkfont.Font(family='Helvetica', size=int(9*z), weight='bold'); details_font = tkfont.Font(family='Helvetica', size=int(8*z))
        title = f"Step {index+1}: {step.get('name', 'Unnamed')}"
        action_text = step.get('action', '')
        step_type_display = step['type'].title()
        if step['type'] == 'location':
            step_type_display = 'Click / Press'
            action_text = step.get('action', 'Left Click')
            if action_text == 'Key Press':
                action_text = f"Press Key: {step.get('key_to_press', '')}"
        elif step['type'] == 'logical':
            if step.get('logical_type') == 'Number':
                action_text = step.get('expression', '> 0')
            elif step.get('logical_type') == 'Wait':
                action_text = f"Wait for {step.get('max_time', 0)}s"
            elif step.get('logical_type') == 'Type Text':
                if step.get('text_source') == 'GE Interface':
                    action_text = f"Type GE: {step.get('ge_data_field')}"
                else:
                    action_text = "Type Text"
            elif step.get('logical_type') == 'GE Name Inject':
                action_text = "GE Name Inject"
            else:
                action_text = step.get('logical_type', 'Execute')
        
        type_text = f"Type: {step_type_display}\nAction: {action_text}"; title_width = title_font.measure(title); details_width = max(details_font.measure(line) for line in type_text.split('\n'))
        padding_x, padding_y = 20 * z, 20 * z; node_width = max(title_width, details_width, 140*z) + padding_x; node_height = (title_font.metrics("linespace") + details_font.metrics("linespace") * 2) + padding_y
        step['_width'], step['_height'] = node_width, node_height

    def draw_node(self, index):
        step = self.steps[index]; x, y = step.get('x', 50), step.get('y', 50); z = self.zoom_factor; node_width, node_height = step.get('_width', 180*z), step.get('_height', 60*z)
        theme = self.current_theme
        node_colors = {"color": "#2c3a2c", "png": "#2a3a49", "location": "#4a4a4a", "logical": "#4d452c"}
        
        fill_color = node_colors.get(step['type'], "#555555")
        is_selected = any(item['type'] == 'step' and item['index'] == index for item in self.selected_items)
        border_color = "#2a9fd6" if is_selected else theme['node_border']; border_width = 3 if is_selected else 1; tag = f"step_{index}"
        self.canvas.create_rectangle(x*z, y*z, (x + node_width/z)*z, (y + node_height/z)*z, fill=fill_color, outline=border_color, width=border_width, tags=(tag, "node"))
        title = f"Step {index+1}: {step.get('name', 'Unnamed')}"; self.canvas.create_text((x + node_width/z/2)*z, (y + node_height/z * 0.25)*z, text=title, width=(node_width-15*z), justify=tk.CENTER, font=('Helvetica', int(9*z), 'bold'), tags=(tag, "node"), fill=theme['fg'])
        
        action_text = step.get('action', '')
        step_type_display = step['type'].title()
        if step['type'] == 'location':
            step_type_display = 'Click / Press'
            action_text = step.get('action', 'Left Click')
            if action_text == 'Key Press':
                action_text = f"Press Key: {step.get('key_to_press', '')}"
        elif step['type'] == 'logical':
            if step.get('logical_type') == 'Number':
                action_text = step.get('expression', '> 0')
            elif step.get('logical_type') == 'Wait':
                action_text = f"Wait for {step.get('max_time', 0)}s"
            elif step.get('logical_type') == 'Type Text':
                if step.get('text_source') == 'GE Interface':
                    action_text = f"Type GE: {step.get('ge_data_field')}"
                else:
                    action_text = f"Type: {step.get('text_to_type', '')[:15]}"
            elif step.get('logical_type') == 'GE Inject':
                if step.get('ge_inject_field') == 'Quantity':
                    action_text = f"Inject Qty: {step.get('ge_inject_quantity', '1')}"
                else: # Default to Name
                    action_text = f"Inject: {step.get('ge_inject_name', '')[:15]}"
            else:
                action_text = step.get('logical_type', 'Execute')

        type_text = f"Type: {step_type_display}\nAction: {action_text}"
        self.canvas.create_text((x + node_width/z/2)*z, (y + node_height/z * 0.65)*z, text=type_text, fill=theme['node_text_grey'], font=('Helvetica', int(8*z)), tags=(tag, "node"), justify=tk.CENTER)

        if self.running and index == self.current_step_index: self.canvas.create_oval((x-10)*z, (y-10)*z, (x+10)*z, (y+10)*z, fill=theme['status_green'], outline="", tags=("runtime_highlight", tag))

    def draw_annotation(self, note):
        x, y, w, h, z = note['x'], note['y'], note['width'], note['height'], self.zoom_factor; index = self.annotations.index(note)
        is_selected = any(item['type'] == 'note' and item['index'] == index for item in self.selected_items)
        border_color = "#2a9fd6" if is_selected else "#888888"; border_width = 3 if is_selected else 1; tag = f"note_{index}"
        opacity = note.get('opacity', '0% (Border Only)')
        fill_color = note['color'] if opacity != '0% (Border Only)' else ""
        stipple_map = {"100%": "", "75%": "gray75", "50%": "gray50", "25%": "gray25"}; stipple = stipple_map.get(opacity, "")
        self.canvas.create_rectangle(x*z, y*z, (x+w)*z, (y+h)*z, fill=fill_color, outline=border_color, width=border_width, stipple=stipple, tags=(tag, "annotation"))
        padding = 5 * z
        self.canvas.create_text((x*z + padding), (y*z + padding), text=note['text'], width=(w*z - padding*2),
                                font=('Helvetica', int(10*z), 'italic'), fill=self.current_theme['fg'],
                                justify=tk.LEFT, anchor=tk.NW, tags=(tag, "annotation"))
        if is_selected:
            handle_size = 8 * z; hx, hy = (x+w)*z - handle_size/2, (y+h)*z - handle_size/2
            self.canvas.create_rectangle(hx, hy, hx+handle_size, hy+handle_size, fill=border_color, outline='white', tags=(tag, "annotation", "resize_handle"))

    def _is_bidirectional(self, source_index, target_index):
        if not (0 <= target_index < len(self.steps)): return False
        target_step = self.steps[target_index]
        
        if target_step.get('on_success_action') == 'Go to Step' and target_step.get('on_success_goto_step') - 1 == source_index: return True
        if target_step.get('on_success_action') == 'Next Step' and target_index + 1 == source_index: return True

        is_timeout_step = target_step.get('type') not in ['logical'] or target_step.get('logical_type') in ['Number', 'Wait']
        if is_timeout_step and target_step.get('on_timeout_action') == 'Go to Step' and target_step.get('on_timeout_goto_step') - 1 == source_index: return True
        
        if target_step.get('type') == 'logical' and target_step.get('logical_type') == 'Count' and target_step.get('on_count_reached_action') == 'Go to Step' and target_step.get('on_count_reached_goto_step') - 1 == source_index: return True
        
        return False

    def draw_connection(self, source_index, action_key, goto_key):
        step = self.steps[source_index]; action = step.get(action_key); target_index = -1; line_style = {}
        if action == 'Next Step':
            if source_index + 1 < len(self.steps): target_index = source_index + 1; line_style = {'fill': '#5c7a96', 'dash': (10, 5), 'width': 1.5 * self.zoom_factor}
        elif action == 'Go to Step':
            target_index = step.get(goto_key, 1) - 1
            if 'success' in action_key: line_style = {'fill': self.current_theme['status_green'], 'width': 2.0 * self.zoom_factor}
            elif 'count_reached' in action_key: line_style = {'fill': self.current_theme['status_red'], 'dash': (8, 2, 2, 2), 'width': 2.0 * self.zoom_factor}
            elif 'fail' in action_key: line_style = {'fill': self.current_theme['status_red'], 'dash': (4, 4), 'width': 2.0 * self.zoom_factor}
            else: line_style = {'fill': self.current_theme['status_orange'], 'dash': (6, 4), 'width': 2.0 * self.zoom_factor}
        
        if 0 <= target_index < len(self.steps) and target_index != source_index:
            is_bidirectional = self._is_bidirectional(source_index, target_index)
            start_pos_center = self.get_node_center(source_index); target_center = self.get_node_center(target_index)
            target_step = self.steps[target_index]; z = self.zoom_factor; target_w = target_step.get('_width', 180*z)/z; target_h = target_step.get('_height', 60*z)/z
            start_pos_z = (start_pos_center[0] * z, start_pos_center[1] * z); target_center_z = (target_center[0] * z, target_center[1] * z)
            
            if is_bidirectional and source_index > target_index:
                dx, dy = target_center_z[0] - start_pos_z[0], target_center_z[1] - start_pos_z[1]; dist = math.hypot(dx, dy)
                if dist < 1: return
                mid_x, mid_y = start_pos_z[0] + dx*0.5, start_pos_z[1] + dy*0.5; perp_x, perp_y = -dy/dist, dx/dist
                curve_amount = dist * 0.2
                ctrl_point = (mid_x + curve_amount*perp_x, mid_y + curve_amount*perp_y)
                end_pos = self._get_line_to_node_edge(ctrl_point, target_center_z, target_w*z, target_h*z)
                self.canvas.create_line(start_pos_z, ctrl_point, end_pos, smooth=True, arrow=tk.LAST, **line_style)
            else:
                end_pos = self._get_line_to_node_edge(start_pos_z, target_center_z, target_w*z, target_h*z)
                self.canvas.create_line(start_pos_z, end_pos, arrow=tk.LAST, **line_style)

    def _get_line_to_node_edge(self, p1, p2, w, h):
        p1_x, p1_y = p1; p2_x, p2_y = p2; dx, dy = p2_x - p1_x, p2_y - p1_y
        if dx == 0 and dy == 0: return p2

        rect_ratio = h / w if w != 0 else float('inf')
        line_ratio = abs(dy / dx) if dx != 0 else float('inf')
        
        x, y = p2_x, p2_y

        if line_ratio < rect_ratio:
            if dx > 0: x, y = p2_x - w/2, p2_y - (w/2 * dy)/dx if dx!=0 else p2_y
            else: x, y = p2_x + w/2, p2_y + (w/2 * dy)/dx if dx!=0 else p2_y
        else:
            if dy > 0: x, y = p2_x - (h/2 * dx)/dy if dy!=0 else p2_x, p2_y - h/2
            else: x, y = p2_x + (h/2 * dx)/dy if dy!=0 else p2_x, p2_y + h/2
        
        return (x, y)

    def on_canvas_press(self, event):
        canvas_x, canvas_y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        overlapping = self.canvas.find_overlapping(canvas_x, canvas_y, canvas_x, canvas_y)
        is_shift_pressed = (event.state & 0x0001) != 0

        clicked_item = None
        for item_id in reversed(overlapping):
            tags = self.canvas.gettags(item_id)
            if any(t.startswith("step_") or t.startswith("note_") for t in tags):
                for tag in tags:
                    if tag.startswith("step_") or tag.startswith("note_"):
                        item_type, index_str = tag.split('_')
                        index = int(index_str)
                        mode = "move"
                        if "resize_handle" in tags and item_type == 'note':
                            mode = "resize"
                        clicked_item = {'type': item_type, 'index': index, 'mode': mode}
                        break
            if clicked_item:
                break
        
        if clicked_item:
            self._drag_data["item"] = f"{clicked_item['type']}_{clicked_item['index']}"
            self._drag_data["start_x"] = canvas_x / self.zoom_factor
            self._drag_data["start_y"] = canvas_y / self.zoom_factor
            self._drag_data["mode"] = clicked_item['mode']

            is_already_selected = any(item['type'] == clicked_item['type'] and item['index'] == clicked_item['index'] for item in self.selected_items)
            
            if is_shift_pressed:
                if is_already_selected:
                    self.selected_items = [item for item in self.selected_items if not (item['type'] == clicked_item['type'] and item['index'] == clicked_item['index'])]
                else:
                    if not self.selected_items or self.selected_items[0]['type'] == clicked_item['type']:
                         self.selected_items.append(clicked_item)
                    else: 
                         self.selected_items = [clicked_item]
            else:
                if not is_already_selected:
                    self.selected_items = [clicked_item]
            
            # --- Store initial positions for dragging ---
            self._drag_data['initial_positions'] = []
            for item in self.selected_items:
                item_list = self.steps if item['type'] == 'step' else self.annotations
                item_obj = item_list[item['index']]
                pos_data = {'x': item_obj.get('x', 0), 'y': item_obj.get('y', 0)}
                if item['type'] == 'note':
                    pos_data['width'] = item_obj.get('width', 100)
                    pos_data['height'] = item_obj.get('height', 50)
                self._drag_data['initial_positions'].append(pos_data)

        else:
            if is_shift_pressed:
                self._marquee_data = {"x": canvas_x, "y": canvas_y, "rect": (canvas_x, canvas_y, canvas_x, canvas_y)}
            else:
                self.selected_items = []
                self._drag_data["item"] = None
        
        self.populate_properties_panel()
        self.redraw_flowchart()

    def on_drag_motion(self, event):
        if self._marquee_data.get("x") is not None:
            canvas_x, canvas_y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
            x1 = self._marquee_data["x"]
            y1 = self._marquee_data["y"]
            self._marquee_data["rect"] = (x1, y1, canvas_x, canvas_y)
            self.redraw_flowchart()
            return

        if self._drag_data["item"] is None or not self.selected_items:
            return

        canvas_x = self.canvas.canvasx(event.x) / self.zoom_factor
        canvas_y = self.canvas.canvasy(event.y) / self.zoom_factor
        
        # Calculate total delta from the start of the drag
        total_dx = canvas_x - self._drag_data["start_x"]
        total_dy = canvas_y - self._drag_data["start_y"]

        # Handle resize mode for a single selected note
        if self._drag_data['mode'] == 'resize' and len(self.selected_items) == 1 and self.selected_items[0]['type'] == 'note':
            note = self.annotations[self.selected_items[0]['index']]
            initial_dims = self._drag_data['initial_positions'][0]
            note['width'] = max(50, initial_dims['width'] + total_dx)
            note['height'] = max(30, initial_dims['height'] + total_dy)
        else:  # Move mode for one or more items
            for i, selected in enumerate(self.selected_items):
                item_list = self.steps if selected['type'] == 'step' else self.annotations
                item_obj = item_list[selected['index']]
                
                if i >= len(self._drag_data['initial_positions']): continue
                
                initial_pos = self._drag_data['initial_positions'][i]
                
                new_x = initial_pos['x'] + total_dx
                new_y = initial_pos['y'] + total_dy
                
                # Apply grid latching if enabled
                if self.grid_latching.get():
                    try:
                        spacing = self.grid_spacing.get()
                        if spacing > 0:
                            item_obj['x'] = round(new_x / spacing) * spacing
                            item_obj['y'] = round(new_y / spacing) * spacing
                        else:
                            item_obj['x'] = new_x; item_obj['y'] = new_y
                    except (ValueError, tk.TclError):
                        item_obj['x'] = new_x; item_obj['y'] = new_y
                else:
                    item_obj['x'] = new_x
                    item_obj['y'] = new_y
        
        self.redraw_flowchart()

    def on_drag_release(self, event):
        if self._marquee_data:
            x1, y1, x2, y2 = self._marquee_data["rect"]
            
            overlapping_ids = self.canvas.find_enclosed(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
            
            newly_selected = []
            for item_id in overlapping_ids:
                tags = self.canvas.gettags(item_id)
                if any(t.startswith("step_") or t.startswith("note_") for t in tags):
                    for tag in tags:
                        if tag.startswith("step_") or tag.startswith("note_"):
                            item_type, index_str = tag.split('_')
                            item = {'type': item_type, 'index': int(index_str)}
                            if item not in self.selected_items and item not in newly_selected:
                                newly_selected.append(item)
                            break
            
            if newly_selected:
                first_new_type = newly_selected[0]['type']
                if not self.selected_items or self.selected_items[0]['type'] == first_new_type:
                    self.selected_items.extend([s for s in newly_selected if s['type'] == first_new_type])
                else: 
                    self.selected_items = [s for s in newly_selected if s['type'] == first_new_type]

            self._marquee_data = {}
            self.populate_properties_panel()
            self.redraw_flowchart()
            return

        self._drag_data = {"start_x": 0, "start_y": 0, "item": None, "mode": "move", "initial_positions": []}

    def populate_properties_panel(self):
        for widget in self.props_tab.winfo_children():
            widget.destroy()
        self.properties_widgets = {}

        if not self.selected_items:
            default_label = ttk.Label(self.props_tab, text="\n\nSelect a step or note in the flowchart\nto view and edit its properties.", justify=tk.CENTER, font=('Helvetica', 10))
            default_label.pack(expand=True, fill=tk.BOTH)
            if self.current_theme:
                default_label.config(foreground=self.current_theme['node_text_grey'])
            self.properties_widgets['default_label'] = default_label
            return
        
        container = ttk.Frame(self.props_tab)
        container.pack(fill="both", expand=True)
        self.properties_widgets['container'] = container
        
        if len(self.selected_items) == 1:
            item = self.selected_items[0]
            if item['type'] == 'step':
                self.populate_step_properties(container, item['index'])
            elif item['type'] == 'note':
                self.populate_note_properties(container, item['index'])
        elif len(self.selected_items) > 1 and self.selected_items[0]['type'] == 'step':
            self.populate_multi_select_properties(container)
        else: # Multiple notes selected
             self.populate_multi_select_properties(container)


        self.update_widget_colors_recursive(container, self.current_theme)
        
        if len(self.selected_items) == 1:
            item = self.selected_items[0]
            if item['type'] == 'step' and self.steps[item['index']]['type'] == 'color':
                if 'color_swatch' in self.properties_widgets:
                    self.properties_widgets['color_swatch'].config(bg=self.rgb_to_hex(self.steps[item['index']].get('rgb')))
            elif item['type'] == 'note':
                if 'note_swatch' in self.properties_widgets:
                    self.properties_widgets['note_swatch'].config(bg=self.annotations[item['index']].get('color'))

    def populate_multi_select_properties(self, container):
        num_selected = len(self.selected_items)
        item_type = self.selected_items[0]['type']
        
        tk.Label(container, text=f"{num_selected} {item_type.title()}s Selected", font=('Helvetica', 11, 'bold')).pack(pady=(0, 10), anchor='w')
        
        # --- Handle Notes ---
        if item_type == 'note':
            tk.Label(container, text="Multi-editing for notes is not yet available.\nOnly universal actions are available.", justify=tk.CENTER).pack(pady=5)
            action_btn_frm = tk.Frame(container)
            action_btn_frm.pack(fill=tk.X, pady=(15, 0))
            tk.Button(action_btn_frm, text="Delete Selected", font=('Helvetica', 9, 'bold'), command=self.delete_selected_from_key, relief=tk.FLAT).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)
            # Spacer to push content up
            ttk.Frame(container).pack(fill=tk.BOTH, expand=True)
            return

        # --- Handle Steps ---
        selected_steps = [self.steps[item['index']] for item in self.selected_items]

        def get_common_value(prop_key, default_value):
            first_value = selected_steps[0].get(prop_key, default_value)
            if all(s.get(prop_key, default_value) == first_value for s in selected_steps):
                return first_value
            return self.MULTIPLE_VALUES

        # --- Universal Options Frame ---
        options_lf = ttk.LabelFrame(container, text="Options")
        options_lf.pack(fill=tk.X, pady=(5,10))
        options_lf.columnconfigure(1, weight=1)
        
        # Enable Logging Checkbox
        log_val = get_common_value('enable_logging', True)
        log_var = tk.BooleanVar()
        if log_val is not self.MULTIPLE_VALUES: log_var.set(log_val)
        self.properties_widgets['enable_logging'] = log_var
        log_cb = ttk.Checkbutton(options_lf, text="Enable Execution Log", variable=log_var)
        log_cb.grid(row=0, column=0, columnspan=2, sticky='w', pady=2, padx=5)
        if log_val is self.MULTIPLE_VALUES: log_cb.config(text="Enable Execution Log (mixed)")

        # Show Area Checkbox (if applicable)
        is_area_applicable = any(s['type'] in ['color', 'png'] or (s['type'] == 'logical' and s.get('logical_type') in ['Number', 'Movement Detect']) for s in selected_steps)
        if is_area_applicable:
            area_val = get_common_value('show_area', False)
            area_var = tk.BooleanVar()
            if area_val is not self.MULTIPLE_VALUES: area_var.set(area_val)
            self.properties_widgets['show_area'] = area_var
            area_cb = ttk.Checkbutton(options_lf, text="Show Area Overlay", variable=area_var, command=self.update_all_area_overlays)
            area_cb.grid(row=1, column=0, columnspan=2, sticky='w', pady=2, padx=5)
            if area_val is self.MULTIPLE_VALUES: area_cb.config(text="Show Area Overlay (mixed)")

        # --- Type-Specific Flow Control Frame ---
        first_step_type = selected_steps[0]['type']
        if all(s['type'] == first_step_type for s in selected_steps):
            flow_lf = ttk.LabelFrame(container, text=f"{first_step_type.title()} Flow Control")
            flow_lf.pack(fill=tk.X)
            flow_lf.columnconfigure(1, weight=1)
            row = 0

            # Collect properties based on type
            props_to_show = ['delay_after', 'on_success_action']
            if first_step_type in ['color', 'png']:
                props_to_show.extend(['timeout', 'on_timeout_action'])
            
            for prop in props_to_show:
                default_map = {'delay_after': 1.0, 'on_success_action': 'Next Step', 'timeout': 5.0, 'on_timeout_action': 'Stop'}
                value = get_common_value(prop, default_map.get(prop))
                label_text = prop.replace('_', ' ').title()
                if "On Success" in label_text: label_text = "On Success:"
                if "On Timeout" in label_text: label_text = "On Timeout:"
                ttk.Label(flow_lf, text=f"{label_text}").grid(row=row, column=0, sticky='w', pady=3, padx=5)
                
                if prop.endswith('_action'):
                    options = ["Next Step", "Go to Step", "Stop"]
                    var = tk.StringVar(value=value if value != self.MULTIPLE_VALUES else "")
                    self.properties_widgets[prop] = var
                    ttk.OptionMenu(flow_lf, var, "" if value == self.MULTIPLE_VALUES else value, *options).grid(row=row, column=1, sticky='ew', padx=5)
                else: # Entry-based
                    var = tk.StringVar(value=value)
                    self.properties_widgets[prop] = var
                    entry = ttk.Entry(flow_lf, textvariable=var)
                    if value == self.MULTIPLE_VALUES: entry.config(foreground=self.current_theme['node_text_grey'])
                    entry.grid(row=row, column=1, sticky='ew', padx=5)
                row += 1
        else:
             tk.Label(container, text="Selected steps are of different types.\nOnly universal options are available.", justify=tk.CENTER).pack(pady=5)
        
        # --- Action Buttons ---
        tk.Button(container, text="Apply Changes to Selected", font=('Helvetica', 9, 'bold'), command=self.apply_multi_properties_changes, relief=tk.FLAT).pack(fill=tk.X, pady=(15, 5), ipady=4)
        
        action_btn_frm = tk.Frame(container)
        action_btn_frm.pack(fill=tk.X, pady=(0, 0))
        btn_pack_style = {'side': tk.LEFT, 'expand': True, 'fill': tk.X, 'padx': 2}
        tk.Button(action_btn_frm, text="Duplicate Selected", font=('Helvetica', 9, 'bold'), command=self.duplicate_selected, relief=tk.FLAT).pack(**btn_pack_style)
        tk.Button(action_btn_frm, text="Delete Selected", font=('Helvetica', 9, 'bold'), command=self.delete_selected_from_key, relief=tk.FLAT).pack(**btn_pack_style)

        # --- Spacer to push all content to the top ---
        ttk.Frame(container).pack(fill=tk.BOTH, expand=True)

    def populate_step_properties(self, container, i):
        step = self.steps[i]
        tk.Label(container, text=f"Properties for Step {i+1}", font=('Helvetica', 11, 'bold')).grid(row=0, columnspan=3, sticky='w', pady=(0,10))
        tk.Label(container, text="Name:").grid(row=1, column=0, sticky='w', pady=2); w = tk.Entry(container); w.insert(0, step.get('name', '')); w.grid(row=1, column=1, columnspan=2, sticky='ew', pady=2); self.properties_widgets['name_entry'] = w
        
        action_row = 2
        tk.Label(container, text="Action:").grid(row=action_row, column=0, sticky='w', pady=2)
        action_frm = tk.Frame(container); action_frm.grid(row=action_row, column=1, columnspan=2, sticky='w')

        details_label_text = {'location': 'Click / Press Details'}
        details_label = details_label_text.get(step['type'], f"{step['type'].title()} Details")
        
        details_lf = tk.LabelFrame(container, text=details_label, padx=5, pady=5); details_lf.grid(row=3, columnspan=3, sticky='ew', pady=10)
        self.properties_widgets['details_lf'] = details_lf

        options_lf = tk.LabelFrame(container, text="Options", padx=5, pady=5); options_lf.grid(row=5, columnspan=3, sticky='ew', pady=(0, 10))
        w = tk.BooleanVar(value=step.get('enable_logging', True)); self.properties_widgets['enable_logging'] = w
        ttk.Checkbutton(options_lf, text="Enable Execution Log", variable=w).pack(side=tk.LEFT, anchor='w')

        uses_area = step['type'] in ['color', 'png'] or (step['type'] == 'logical' and step.get('logical_type') in ['Number', 'Movement Detect'])
        if uses_area:
            w = tk.BooleanVar(value=step.get('show_area', False)); self.properties_widgets['show_area'] = w
            ttk.Checkbutton(options_lf, text="Show Area", variable=w, command=self.toggle_step_show_area_flag).pack(side=tk.LEFT, anchor='w', padx=(10, 0))

        flow_lf = tk.LabelFrame(container, text="Flow Control", padx=5, pady=5); flow_lf.grid(row=6, columnspan=3, sticky='ew', pady=0)

        if step['type'] == 'logical':
            logical_type_var = tk.StringVar(value=step.get('logical_type', 'Count')); self.properties_widgets['logical_type'] = logical_type_var
            def _update_logical_details_frame(flow_control_frame):
                for widget in details_lf.winfo_children(): widget.destroy()
                for w in flow_control_frame.grid_slaves():
                    if int(w.grid_info()["row"]) > 1: w.destroy()
                timeout_widgets = self.properties_widgets.get('timeout_widgets', [])
                selected_type = logical_type_var.get(); step['logical_type'] = selected_type
                if selected_type in ['Number', 'Movement Detect']: [w.grid() for w in timeout_widgets]
                else: [w.grid_remove() for w in timeout_widgets]
                if selected_type == 'Count':
                    tk.Label(details_lf, text="Current Count:").grid(row=0, column=0, sticky='w', pady=5); w = tk.Label(details_lf, text=str(step.get('counter_value', 0)), font=('Consolas', 10, 'bold')); w.grid(row=0, column=1, sticky='w', padx=5); self.properties_widgets['counter_display'] = w; w = tk.Button(details_lf, text="Reset Count", font=('Helvetica', 9), command=self.reset_logical_counter, relief=tk.FLAT); w.grid(row=0, column=2, padx=10)
                    tk.Label(details_lf, text="Max Count (0=inf):").grid(row=1, column=0, sticky='w', pady=5); w = tk.Entry(details_lf, width=8); w.insert(0, str(step.get('max_count', 0))); w.grid(row=1, column=1, sticky='w', padx=5); self.properties_widgets['max_count'] = w
                    w = tk.BooleanVar(value=step.get('reset_on_start', False)); self.properties_widgets['reset_on_start'] = w; ttk.Checkbutton(details_lf, text="Reset on Start (F2)", variable=w).grid(row=2, column=0, columnspan=3, sticky='w', pady=5)
                    w = tk.BooleanVar(value=step.get('reset_on_reach', False)); self.properties_widgets['reset_on_reach'] = w; ttk.Checkbutton(details_lf, text="Reset on Count Reached", variable=w).grid(row=3, column=0, columnspan=3, sticky='w', pady=5)
                    
                    tk.Label(flow_control_frame, text="On Count Reached:").grid(row=2,column=0,sticky='w',pady=2); w = tk.StringVar(value=step.get('on_count_reached_action')); self.properties_widgets['on_count_reached_action'] = w; tk.OptionMenu(flow_control_frame,w,"Next Step","Go to Step", "Stop").grid(row=2,column=1,sticky='ew'); w = tk.Entry(flow_control_frame,width=5); w.insert(0,str(step.get('on_count_reached_goto_step'))); w.grid(row=2,column=2,padx=5); self.properties_widgets['on_count_reached_goto_step'] = w
                    tk.Label(flow_control_frame, text="Delay (s):").grid(row=2, column=3, padx=(10,0)); w = tk.Entry(flow_control_frame, width=7); w.insert(0, str(step.get('on_count_reached_delay'))); w.grid(row=2, column=4); self.properties_widgets['on_count_reached_delay'] = w
                elif selected_type == 'Wait':
                    tk.Label(details_lf, text="Wait Duration (s):").grid(row=0, column=0, sticky='w', pady=5); w = tk.Entry(details_lf, width=8); w.insert(0, str(step.get('max_time', 0))); w.grid(row=0, column=1, sticky='w', padx=5); self.properties_widgets['max_time'] = w
                    w = tk.Button(details_lf, text="Reset Wait Timer", font=('Helvetica', 9), command=self.reset_timer, relief=tk.FLAT); w.grid(row=0, column=2, padx=10)
                    w = tk.BooleanVar(value=step.get('reset_on_start', False)); self.properties_widgets['reset_on_start'] = w; ttk.Checkbutton(details_lf, text="Reset on Start (F2)", variable=w).grid(row=1, column=0, columnspan=3, sticky='w', pady=5)
                elif selected_type == 'Type Text':
                    source_frame = ttk.Frame(details_lf); source_frame.grid(row=0, column=0, columnspan=3, sticky='w', pady=2)
                    source_var = tk.StringVar(value=step.get('text_source', 'Static Text')); self.properties_widgets['text_source'] = source_var
                    
                    static_entry = ttk.Entry(details_lf, width=25); self.properties_widgets['text_to_type'] = static_entry; static_entry.insert(0, str(step.get('text_to_type', '')))
                    ge_data_options = ["Item Name", "Quantity", "Calculated Buy Price", "Calculated Sell Price", "Calculated Buy Total", "Calculated Sell Total"]
                    ge_data_var = tk.StringVar(value=step.get('ge_data_field', 'Calculated Buy Price')); self.properties_widgets['ge_data_field'] = ge_data_var
                    ge_data_combo = ttk.Combobox(details_lf, textvariable=ge_data_var, values=ge_data_options, state='readonly', width=22)
                    
                    def _toggle_source_widgets(*args):
                        if source_var.get() == 'GE Interface':
                            static_entry.grid_remove(); ge_data_combo.grid(row=1, column=1, sticky='ew', padx=5)
                        else:
                            ge_data_combo.grid_remove(); static_entry.grid(row=1, column=1, sticky='ew', padx=5)
                    
                    ttk.Radiobutton(source_frame, text="Static Text:", variable=source_var, value="Static Text", command=_toggle_source_widgets).pack(side=tk.LEFT)
                    ttk.Radiobutton(source_frame, text="From GE Interface:", variable=source_var, value="GE Interface", command=_toggle_source_widgets).pack(side=tk.LEFT, padx=10)
                    
                    enter_frame = ttk.Frame(details_lf)
                    enter_frame.grid(row=2, column=1, sticky='ew', pady=5)
                    
                    press_enter_var = tk.BooleanVar(value=step.get('press_enter', False))
                    self.properties_widgets['press_enter'] = press_enter_var
                    
                    delay_label = ttk.Label(enter_frame, text="Delay (s):")
                    delay_entry = ttk.Entry(enter_frame, width=7)
                    delay_entry.insert(0, str(step.get('enter_press_delay', 0.1)))
                    self.properties_widgets['enter_press_delay'] = delay_entry
                    
                    def _toggle_enter_delay(*args):
                        if press_enter_var.get():
                            delay_label.pack(side=tk.LEFT, padx=(10, 2))
                            delay_entry.pack(side=tk.LEFT)
                        else:
                            delay_label.pack_forget()
                            delay_entry.pack_forget()

                    press_enter_cb = ttk.Checkbutton(enter_frame, text="Press Enter after", variable=press_enter_var, command=_toggle_enter_delay)
                    press_enter_cb.pack(side=tk.LEFT)
                    
                    press_enter_var.trace_add('write', _toggle_enter_delay)
                    _toggle_enter_delay() 
                    
                    details_lf.columnconfigure(1, weight=1)
                    _toggle_source_widgets()
                elif selected_type == 'GE Inject':
                    field_var = tk.StringVar(value=step.get('ge_inject_field', 'Name'))
                    self.properties_widgets['ge_inject_field'] = field_var

                    field_frame = ttk.Frame(details_lf)
                    field_frame.grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 5))
                    
                    name_label = ttk.Label(details_lf, text="Item Name:")
                    name_entry = ttk.Entry(details_lf, width=25)
                    name_entry.insert(0, str(step.get('ge_inject_name', '')))
                    self.properties_widgets['ge_inject_name'] = name_entry
                    
                    qty_label = ttk.Label(details_lf, text="Quantity:")
                    qty_entry = ttk.Entry(details_lf, width=25)
                    qty_entry.insert(0, str(step.get('ge_inject_quantity', '1')))
                    self.properties_widgets['ge_inject_quantity'] = qty_entry

                    def _toggle_inject_widgets(*args):
                        if field_var.get() == 'Quantity':
                            name_label.grid_remove(); name_entry.grid_remove()
                            qty_label.grid(row=1, column=0, sticky='w', pady=5)
                            qty_entry.grid(row=1, column=1, sticky='ew', padx=5)
                        else: # Name
                            qty_label.grid_remove(); qty_entry.grid_remove()
                            name_label.grid(row=1, column=0, sticky='w', pady=5)
                            name_entry.grid(row=1, column=1, sticky='ew', padx=5)
                    
                    ttk.Radiobutton(field_frame, text="Name", variable=field_var, value="Name", command=_toggle_inject_widgets).pack(side=tk.LEFT)
                    ttk.Radiobutton(field_frame, text="Quantity", variable=field_var, value="Quantity", command=_toggle_inject_widgets).pack(side=tk.LEFT, padx=10)

                    refresh_var = tk.BooleanVar(value=step.get('ge_inject_refresh', False))
                    self.properties_widgets['ge_inject_refresh'] = refresh_var
                    ttk.Checkbutton(details_lf, text="Refresh Price After Inject", variable=refresh_var).grid(row=2, column=0, columnspan=2, sticky='w', pady=(5, 0))

                    details_lf.columnconfigure(1, weight=1)
                    _toggle_inject_widgets()
                elif selected_type == 'Settings Inject':
                    setting_names = list(self.INJECTABLE_SETTINGS)
                    setting_var = tk.StringVar(value=step.get('inject_setting_name', setting_names[0]))
                    self.properties_widgets['inject_setting_name'] = setting_var
                    
                    tk.Label(details_lf, text="Setting to Change:").grid(row=0, column=0, sticky='w', pady=5)
                    ttk.OptionMenu(details_lf, setting_var, setting_var.get(), *setting_names).grid(row=0, column=1, sticky='ew', padx=5)
                    
                    tk.Label(details_lf, text="New Value:").grid(row=1, column=0, sticky='w', pady=5)
                    w = tk.Entry(details_lf, width=15); w.insert(0, str(step.get('inject_setting_value', ''))); w.grid(row=1, column=1, sticky='ew', padx=5)
                    self.properties_widgets['inject_setting_value'] = w
                    tk.Label(details_lf, text="e.g. 0.15, or Dynamic for the move mode", font=('Helvetica', 8)).grid(row=2, column=1, sticky='w', padx=5)
                    details_lf.columnconfigure(1, weight=1)
                elif selected_type == 'Number':
                    tk.Label(details_lf, text="Expression:").grid(row=0, column=0, sticky='w'); w=tk.Entry(details_lf, width=15); w.insert(0, str(step.get('expression', ''))); w.grid(row=0, column=1, columnspan=2, sticky='ew'); self.properties_widgets['expression'] = w; tk.Label(details_lf, text="e.g., > 100").grid(row=0, column=3, sticky='w', padx=5)
                    tk.Label(details_lf, text="Image Mode:").grid(row=1, column=0, sticky='w', pady=5); w = tk.StringVar(value=step.get('image_mode', 'Grayscale')); self.properties_widgets['number_image_mode'] = w; tk.OptionMenu(details_lf, w, 'Grayscale', 'Color', 'Binary (B&W)').grid(row=1, column=1, columnspan=3, sticky='ew')
                    tk.Label(details_lf, text="OEM:").grid(row=2, column=0, sticky='w', pady=2); oem_var = tk.StringVar(value=step.get('oem_mode', "3: Default, based on what is available.")); self.properties_widgets['oem_mode'] = oem_var; w = ttk.OptionMenu(details_lf, oem_var, oem_var.get(), *self.oem_options.keys()); w.grid(row=2, column=1, columnspan=3, sticky='ew')
                    tk.Label(details_lf, text="PSM:").grid(row=3, column=0, sticky='w', pady=2); psm_var = tk.StringVar(value=step.get('psm_mode', "6: Assume a single uniform block of text.")); self.properties_widgets['psm_mode'] = psm_var; w = ttk.OptionMenu(details_lf, psm_var, psm_var.get(), *self.psm_options.keys()); w.grid(row=3, column=1, columnspan=3, sticky='ew')
                    area_btn_frame = tk.Frame(details_lf); area_btn_frame.grid(row=4, column=0, columnspan=4, sticky='w', pady=(5,0))
                    area_text = f"Area: {step['area'][2]-step['area'][0]}x{step['area'][3]-step['area'][1]}" if step.get('area') else "Area: Global"
                    w = tk.Button(area_btn_frame, text=area_text, command=self.select_area_for_step, font=('Helvetica', 9), relief=tk.FLAT); w.pack(side=tk.LEFT, padx=(0, 2)); self.properties_widgets['area_btn'] = w
                    tk.Button(area_btn_frame, text="Full Screen", command=self.set_step_area_to_fullscreen, font=('Helvetica', 9), relief=tk.FLAT).pack(side=tk.LEFT, padx=(0, 2))
                    tk.Button(area_btn_frame, text="Use Global", command=self.set_step_area_to_global, font=('Helvetica', 9), relief=tk.FLAT).pack(side=tk.LEFT)
                    details_lf.columnconfigure(1, weight=1)
                elif selected_type == 'Movement Detect':
                    tk.Label(details_lf, text="Stillness Tolerance (%):").grid(row=0, column=0, sticky='w', pady=5)
                    w = tk.Entry(details_lf, width=8)
                    w.insert(0, str(step.get('movement_tolerance', 5.0)))
                    w.grid(row=0, column=1, sticky='w', padx=5)
                    self.properties_widgets['movement_tolerance'] = w
                    
                    w = tk.BooleanVar(value=step.get('reset_on_start', True))
                    self.properties_widgets['reset_on_start'] = w
                    ttk.Checkbutton(details_lf, text="Reset Comparison on Start (F2)", variable=w).grid(row=1, column=0, columnspan=3, sticky='w', pady=5)

                    area_btn_frame = tk.Frame(details_lf)
                    area_btn_frame.grid(row=2, column=0, columnspan=4, sticky='w', pady=(5,0))
                    area_text = f"Area: {step['area'][2]-step['area'][0]}x{step['area'][3]-step['area'][1]}" if step.get('area') else "Area: Global"
                    w = tk.Button(area_btn_frame, text=area_text, command=self.select_area_for_step, font=('Helvetica', 9), relief=tk.FLAT)
                    w.pack(side=tk.LEFT, padx=(0, 2))
                    self.properties_widgets['area_btn'] = w
                    tk.Button(area_btn_frame, text="Full Screen", command=self.set_step_area_to_fullscreen, font=('Helvetica', 9), relief=tk.FLAT).pack(side=tk.LEFT, padx=(0, 2))
                    tk.Button(area_btn_frame, text="Use Global", command=self.set_step_area_to_global, font=('Helvetica', 9), relief=tk.FLAT).pack(side=tk.LEFT)
                    details_lf.columnconfigure(1, weight=1)
                self.update_widget_colors_recursive(container, self.current_theme)
            
            command = lambda: _update_logical_details_frame(flow_lf)
            logical_radios_frm_1 = tk.Frame(action_frm); logical_radios_frm_1.pack(fill=tk.X, anchor='w')
            logical_radios_frm_2 = tk.Frame(action_frm); logical_radios_frm_2.pack(fill=tk.X, anchor='w')
            tk.Radiobutton(logical_radios_frm_1, text="Count", variable=logical_type_var, value="Count", command=command).pack(side=tk.LEFT, padx=(0,5))
            tk.Radiobutton(logical_radios_frm_1, text="Wait/Delay", variable=logical_type_var, value="Wait", command=command).pack(side=tk.LEFT, padx=5)
            tk.Radiobutton(logical_radios_frm_1, text="Type Text", variable=logical_type_var, value="Type Text", command=command).pack(side=tk.LEFT, padx=5)
            tk.Radiobutton(logical_radios_frm_2, text="GE Inject", variable=logical_type_var, value="GE Inject", command=command).pack(side=tk.LEFT, padx=(0,5))
            tk.Radiobutton(logical_radios_frm_2, text="Settings Inject", variable=logical_type_var, value="Settings Inject", command=command).pack(side=tk.LEFT, padx=5)
            if PYTESSERACT_AVAILABLE: tk.Radiobutton(logical_radios_frm_2, text="Number", variable=logical_type_var, value="Number", command=command).pack(side=tk.LEFT, padx=5)
            tk.Radiobutton(logical_radios_frm_2, text="Movement", variable=logical_type_var, value="Movement Detect", command=command).pack(side=tk.LEFT, padx=5)
        else:
            action_var = tk.StringVar(value=step.get('action')); self.properties_widgets['action'] = action_var
            if step['type'] == 'location':
                def _update_location_details():
                    is_key_press = action_var.get() == 'Key Press'
                    is_click_only = action_var.get() == 'Click Only'
                    for widget_key in ['key_press_entry', 'key_press_label']:
                        if self.properties_widgets.get(widget_key):
                            self.properties_widgets[widget_key].grid() if is_key_press else self.properties_widgets[widget_key].grid_remove()
                    for widget_key in ['get_loc_btn', 'coords_label']:
                        if self.properties_widgets.get(widget_key):
                             self.properties_widgets[widget_key].grid_remove() if is_key_press or is_click_only else self.properties_widgets[widget_key].grid()
                
                tk.Radiobutton(action_frm, text="Left Click", variable=action_var, value='Left Click', command=_update_location_details).pack(side=tk.LEFT)
                tk.Radiobutton(action_frm, text="Right Click", variable=action_var, value='Right Click', command=_update_location_details).pack(side=tk.LEFT, padx=5)
                tk.Radiobutton(action_frm, text="Move Only", variable=action_var, value='Move Only', command=_update_location_details).pack(side=tk.LEFT, padx=5)
                tk.Radiobutton(action_frm, text="Click Only", variable=action_var, value='Click Only', command=_update_location_details).pack(side=tk.LEFT, padx=5)
                tk.Radiobutton(action_frm, text="Key Press", variable=action_var, value='Key Press', command=_update_location_details).pack(side=tk.LEFT, padx=5)
                self.properties_widgets['get_loc_btn'], self.properties_widgets['coords_label'] = None, None

            elif step['type'] == 'png' or step['type'] == 'color':
                def _update_details_for_action():
                    action = action_var.get()
                    is_count_mode = (step['type'] == 'png' and action == 'PNG Count') or \
                                    (step['type'] == 'color' and action == 'Color Count')
                    
                    if 'count_details_lf' in self.properties_widgets:
                        self.properties_widgets['count_details_lf'].grid() if is_count_mode else self.properties_widgets['count_details_lf'].grid_remove()
                    
                    if 'timeout_action_label' in self.properties_widgets:
                        self.properties_widgets['timeout_action_label'].config(text="On Fail:") if is_count_mode else self.properties_widgets['timeout_action_label'].config(text="On Timeout:")
                    
                    if 'timeout_widgets' in self.properties_widgets:
                        timeout_label, w_timeout = self.properties_widgets['timeout_widgets'][3], self.properties_widgets['timeout_widgets'][4]
                        if is_count_mode:
                            timeout_label.grid_remove()
                            w_timeout.grid_remove()
                        else:
                            timeout_label.grid()
                            w_timeout.grid()

                tk.Radiobutton(action_frm, text="Left Click", variable=action_var, value='Click Object', command=_update_details_for_action).pack(side=tk.LEFT)
                tk.Radiobutton(action_frm, text="Right Click", variable=action_var, value='Right Click', command=_update_details_for_action).pack(side=tk.LEFT, padx=5)
                tk.Radiobutton(action_frm, text="Detect Only", variable=action_var, value='Detect Object', command=_update_details_for_action).pack(side=tk.LEFT, padx=5)
                if step['type'] == 'png':
                    tk.Radiobutton(action_frm, text="PNG Count", variable=action_var, value='PNG Count', command=_update_details_for_action).pack(side=tk.LEFT, padx=5)
                if step['type'] == 'color':
                    tk.Radiobutton(action_frm, text="Color Count", variable=action_var, value='Color Count', command=_update_details_for_action).pack(side=tk.LEFT, padx=5)

        if step['type'] == 'color':
            pixel_detect_var = tk.BooleanVar(value=step.get('pixel_detect_enabled', False))
            self.properties_widgets['pixel_detect_enabled'] = pixel_detect_var
            
            picker_frame = tk.Frame(details_lf)
            picker_frame.grid(row=0, column=0, columnspan=4, sticky='w')
            tk.Button(picker_frame,text="Pick (F3)", font=('Helvetica', 9), command=lambda: self.enter_f3_mode('pick_color'), relief=tk.FLAT).pack(side=tk.LEFT)
            w = tk.Label(picker_frame,text=" ",bg=self.rgb_to_hex(step.get('rgb')),relief=tk.SUNKEN,width=3); w.pack(side=tk.LEFT, padx=4); self.properties_widgets['color_swatch'] = w
            
            coords_text = f"Pixel: {step.get('pixel_coords')}" if step.get('pixel_coords') else "Pixel: Not Set"
            pixel_coords_label = tk.Label(picker_frame, text=coords_text); self.properties_widgets['pixel_coords_label'] = pixel_coords_label

            tk.Label(details_lf,text="Tolerance:").grid(row=1,column=0, sticky='w', pady=2); w=tk.Entry(details_lf,width=7); w.insert(0,str(step.get('tolerance'))); w.grid(row=1,column=1, sticky='w', padx=2); self.properties_widgets['tolerance'] = w
            tk.Label(details_lf, text="Min Area (px):").grid(row=1, column=2, sticky='w', padx=(10,2)); w=tk.Entry(details_lf, width=7); w.insert(0, str(step.get('min_pixel_area', 10))); w.grid(row=1, column=3, sticky='w', padx=2); self.properties_widgets['min_pixel_area'] = w
            
            tk.Label(details_lf, text="Color Space:").grid(row=2, column=0, sticky='w', pady=5); w = tk.StringVar(value=step.get('color_space', 'HSV')); self.properties_widgets['color_space'] = w; 
            tk.OptionMenu(details_lf, w, 'HSV', 'RGB').grid(row=2, column=1, sticky='ew')
            
            # Where to click when more than one blob matches the colour.
            tk.Label(details_lf, text="Aim Point:").grid(row=2, column=2, sticky='w', padx=(10,2)); w = tk.StringVar(value=step.get('blob_target', 'Largest Blob')); self.properties_widgets['blob_target'] = w
            aim_menu = tk.OptionMenu(details_lf, w, 'Largest Blob', 'Center Of All Matches', 'Nearest Blob To Area Center'); aim_menu.grid(row=2, column=3, sticky='ew'); self.properties_widgets['blob_target_menu'] = aim_menu

            tk.Label(details_lf, text="Split Blobs (px):").grid(row=5, column=0, sticky='w', pady=(5,0)); w = tk.Entry(details_lf, width=7); w.insert(0, str(step.get('split_blob_width', 0))); w.grid(row=5, column=1, sticky='w', padx=2, pady=(5,0)); self.properties_widgets['split_blob_width'] = w
            tk.Label(details_lf, text="0 = off. Cuts thin joins that merge blobs.", font=('Helvetica', 8)).grid(row=5, column=2, columnspan=2, sticky='w', pady=(5,0))

            area_btn_frame = tk.Frame(details_lf); area_btn_frame.grid(row=3, column=0, columnspan=4, sticky='w', pady=(5,0))
            area_text = f"Area: {step['area'][2]-step['area'][0]}x{step['area'][3]-step['area'][1]}" if step.get('area') else "Area: Global"
            w_area_btn = tk.Button(area_btn_frame, text=area_text, command=self.select_area_for_step, font=('Helvetica', 9), relief=tk.FLAT); w_area_btn.pack(side=tk.LEFT, padx=(0, 2)); self.properties_widgets['area_btn'] = w_area_btn
            tk.Button(area_btn_frame, text="Full Screen", command=self.set_step_area_to_fullscreen, font=('Helvetica', 9), relief=tk.FLAT).pack(side=tk.LEFT, padx=(0, 2))
            tk.Button(area_btn_frame, text="Use Global", command=self.set_step_area_to_global, font=('Helvetica', 9), relief=tk.FLAT).pack(side=tk.LEFT)

            def _update_color_details_ui(*args):
                is_pixel_mode = pixel_detect_var.get()
                if is_pixel_mode:
                    area_btn_frame.grid_remove()
                    pixel_coords_label.pack(side=tk.LEFT, padx=10)
                else:
                    area_btn_frame.grid()
                    pixel_coords_label.pack_forget()

                # Aim point and blob splitting only apply to area detection.
                for widget in details_lf.grid_slaves():
                    info = widget.grid_info()
                    if not info: continue
                    row, col = int(info['row']), int(info['column'])
                    if (row in (1, 2) and col in (2, 3)) or row == 5:
                        widget.grid_remove() if is_pixel_mode else widget.grid()


            ttk.Checkbutton(details_lf, text="Pixel Detect Mode", variable=pixel_detect_var, command=_update_color_details_ui).grid(row=4, column=0, columnspan=4, sticky='w', pady=(10,0))
            _update_color_details_ui()

        elif step['type'] == 'png':
            png_mode_frm = tk.Frame(details_lf); png_mode_frm.grid(row=0, columnspan=4, sticky='w')
            w = tk.StringVar(value=step.get('mode')); self.properties_widgets['png_mode'] = w
            tk.Radiobutton(png_mode_frm,text="File",variable=w,value='file').pack(side=tk.LEFT)
            tk.Radiobutton(png_mode_frm,text="Folder",variable=w,value='folder').pack(side=tk.LEFT, padx=10)
            
            path_frm = tk.Frame(details_lf); path_frm.grid(row=1, columnspan=4, sticky='ew', pady=5)
            tk.Button(path_frm,text="Snip",command=self.snip_image_for_step, font=('Helvetica', 9), relief=tk.FLAT).pack(side=tk.LEFT, padx=(0,5))
            tk.Button(path_frm,text="Browse",command=self.browse_for_step, font=('Helvetica', 9), relief=tk.FLAT).pack(side=tk.LEFT)
            w = tk.Label(path_frm,text=os.path.basename(step.get('path'))or"No path set",anchor='w',wraplength=180,justify='left'); w.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
            self.properties_widgets['path'] = w
            
            w_preview = tk.Label(details_lf, text="No Preview Available")
            w_preview.grid(row=2, column=0, columnspan=4, sticky='ew', pady=5)
            self.properties_widgets['png_preview'] = w_preview
            self._update_png_preview(step)

            tk.Label(details_lf,text="Threshold:").grid(row=3,column=0,sticky='w', pady=2)
            w=tk.Entry(details_lf,width=7); w.insert(0,str(step.get('threshold'))); w.grid(row=3,column=1)
            self.properties_widgets['threshold'] = w
            
            tk.Label(details_lf, text="Image Mode:").grid(row=4, column=0, sticky='w', pady=5)
            w = tk.StringVar(value=step.get('image_mode', 'Grayscale')); self.properties_widgets['image_mode'] = w
            tk.OptionMenu(details_lf, w, 'Grayscale', 'Color', 'Binary (B&W)').grid(row=4, column=1, columnspan=2, sticky='ew')

            w = tk.BooleanVar(value=step.get('find_first_match', False)); self.properties_widgets['find_first_match'] = w
            ttk.Checkbutton(details_lf, text="Fast Mode (Find First Match)", variable=w).grid(row=5, column=0, columnspan=3, sticky='w', pady=2)
            
            area_btn_frame = tk.Frame(details_lf); area_btn_frame.grid(row=6, column=0, columnspan=4, sticky='w', pady=(5,0))
            area_text = f"Area: {step['area'][2]-step['area'][0]}x{step['area'][3]-step['area'][1]}" if step.get('area') else "Area: Global"
            w = tk.Button(area_btn_frame, text=area_text, command=self.select_area_for_step, font=('Helvetica', 9), relief=tk.FLAT); w.pack(side=tk.LEFT, padx=(0, 2))
            self.properties_widgets['area_btn'] = w
            tk.Button(area_btn_frame, text="Full Screen", command=self.set_step_area_to_fullscreen, font=('Helvetica', 9), relief=tk.FLAT).pack(side=tk.LEFT, padx=(0, 2))
            tk.Button(area_btn_frame, text="Use Global", command=self.set_step_area_to_global, font=('Helvetica', 9), relief=tk.FLAT).pack(side=tk.LEFT)
        
        if step['type'] in ['png', 'color']:
            count_details_lf = tk.LabelFrame(container, text="Count Condition", padx=5, pady=5)
            count_details_lf.grid(row=4, columnspan=3, sticky='ew', pady=(0, 10))
            self.properties_widgets['count_details_lf'] = count_details_lf
            
            tk.Label(count_details_lf, text="Expression:").grid(row=0, column=0, sticky='w', pady=5)
            w = tk.Entry(count_details_lf, width=15); w.insert(0, str(step.get('count_expression', '>= 1')))
            w.grid(row=0, column=1, columnspan=2, sticky='ew', pady=5); self.properties_widgets['count_expression'] = w
            tk.Label(count_details_lf, text="e.g., >= 5, == 1, < 3").grid(row=0, column=3, sticky='w', padx=5)

            tk.Label(count_details_lf, text="Max Cycles:").grid(row=1, column=0, sticky='w', pady=5)
            w = tk.Entry(count_details_lf, width=8)
            w.insert(0, str(step.get('count_max_cycles', 1)))
            w.grid(row=1, column=1, sticky='w', pady=5)
            self.properties_widgets['count_max_cycles'] = w
            tk.Label(count_details_lf, text="(1 = fail immediately)").grid(row=1, column=2, columnspan=2, sticky='w', padx=5)
            
            count_details_lf.columnconfigure(1, weight=1)

        elif step['type'] == 'location':
            w_btn = tk.Button(details_lf,text="Get Loc (F3)", font=('Helvetica', 9), command=lambda: self.enter_f3_mode('pick_location'), relief=tk.FLAT); w_btn.grid(row=0,column=0, pady=2); self.properties_widgets['get_loc_btn'] = w_btn
            w_lbl = tk.Label(details_lf,text=str(step.get('coords'))); w_lbl.grid(row=0,column=1,padx=10); self.properties_widgets['coords_label'] = w_lbl
            w_label = tk.Label(details_lf, text="Key to Press:"); w_label.grid(row=1, column=0, sticky='w', pady=5); self.properties_widgets['key_press_label'] = w_label
            w_entry = tk.Entry(details_lf, width=15); w_entry.insert(0, step.get('key_to_press', '')); w_entry.grid(row=1, column=1, sticky='w'); self.properties_widgets['key_press_entry'] = w_entry
            _update_location_details()
            
        def add_flow(parent, row, label, action_key, goto_key):
            tk.Label(parent,text=label).grid(row=row,column=0,sticky='w',pady=2); w=tk.StringVar(value=step.get(action_key)); self.properties_widgets[action_key]=w; tk.OptionMenu(parent,w,"Next Step","Go to Step", "Stop").grid(row=row,column=1,sticky='ew'); w=tk.Entry(parent,width=5); w.insert(0,str(step.get(goto_key))); w.grid(row=row,column=2,padx=5); self.properties_widgets[goto_key]=w
        
        add_flow(flow_lf, 0, "On Success:", 'on_success_action', 'on_success_goto_step'); tk.Label(flow_lf, text="Delay (s):").grid(row=0, column=3, padx=(10,0)); w = tk.Entry(flow_lf, width=7); w.insert(0, str(step.get('delay_after'))); w.grid(row=0, column=4); self.properties_widgets['delay_after'] = w
        
        timeout_action_label = tk.Label(flow_lf); self.properties_widgets['timeout_action_label'] = timeout_action_label
        w_action_menu=tk.StringVar(value=step.get('on_timeout_action', 'Stop')); self.properties_widgets['on_timeout_action']=w_action_menu; timeout_action_menu = tk.OptionMenu(flow_lf,w_action_menu,"Next Step","Go to Step", "Stop"); w_goto=tk.Entry(flow_lf,width=5); w_goto.insert(0,str(step.get('on_timeout_goto_step', 1))); self.properties_widgets['on_timeout_goto_step']=w_goto
        timeout_label = tk.Label(flow_lf, text="Timeout (s):"); w_timeout=tk.Entry(flow_lf, width=7); w_timeout.insert(0, str(step.get('timeout', 5.0))); self.properties_widgets['timeout'] = w_timeout
        
        is_count_mode = (step.get('type') == 'png' and step.get('action') == 'PNG Count') or \
                        (step.get('type') == 'color' and step.get('action') == 'Color Count')
        is_number_fail = step.get('logical_type') == 'Number'
        timeout_label_text = "On Fail:" if (is_count_mode or is_number_fail) else "On Timeout:"
        timeout_action_label.config(text=timeout_label_text)
        timeout_action_label.grid(row=1, column=0, sticky='w', pady=2); timeout_action_menu.grid(row=1, column=1, sticky='ew'); w_goto.grid(row=1, column=2, padx=5)
        timeout_label.grid(row=1, column=3, padx=(10,0)); w_timeout.grid(row=1, column=4)
        
        self.properties_widgets['timeout_widgets'] = [timeout_action_label, timeout_action_menu, w_goto, timeout_label, w_timeout]
        
        if step['type'] in ['png', 'color']:
            _update_details_for_action()

        is_timeout_visible = (step['type'] not in ['logical']) or (step.get('logical_type') in ['Number', 'Movement Detect'])
        if not is_timeout_visible: [w.grid_remove() for w in self.properties_widgets['timeout_widgets']]

        flow_lf.columnconfigure(1, weight=1)
        if step['type'] == 'logical': _update_logical_details_frame(flow_lf)
        
        action_btn_frm = tk.Frame(container); action_btn_frm.grid(row=7, columnspan=3, sticky='ew', pady=(15,0)); btn_pack_style = {'side': tk.LEFT, 'expand': True, 'fill': tk.X, 'padx': 2}; tk.Button(action_btn_frm, text="Apply Changes", font=('Helvetica', 9, 'bold'), command=self.apply_properties_changes, relief=tk.FLAT).pack(**btn_pack_style); tk.Button(action_btn_frm, text="Duplicate Step", font=('Helvetica', 9, 'bold'), command=self.duplicate_step, relief=tk.FLAT).pack(**btn_pack_style); tk.Button(action_btn_frm, text="Delete Step", font=('Helvetica', 9, 'bold'), command=self.remove_step, relief=tk.FLAT).pack(**btn_pack_style)
        container.columnconfigure(1, weight=1)
 
    def _update_png_preview(self, step):
        if 'png_preview' not in self.properties_widgets:
            return
        
        preview_widget = self.properties_widgets['png_preview']
        path = step.get('path')

        if not path or not os.path.exists(path):
            preview_widget.config(image='', text="No Preview Available")
            return

        try:
            with Image.open(path) as img:
                img.thumbnail((200, 100)) # Resize to max 200x100
                photo = ImageTk.PhotoImage(img)
                preview_widget.config(image=photo, text="")
                preview_widget.image = photo # Keep a reference!
        except Exception as e:
            preview_widget.config(image='', text=f"Preview Error:\n{e}")
            self.log(f"Failed to create PNG preview for {os.path.basename(path)}: {e}", "orange")
 
    def open_deal_finder_window(self):
        if hasattr(self, 'deal_finder_window') and self.deal_finder_window.winfo_exists():
            self.deal_finder_window.lift()
            return

        df_win = tk.Toplevel(self.root)
        df_win.title("GE Deal Finder")
        df_win.geometry("800x600")
        df_win.transient(self.root)
        self.deal_finder_window = df_win
        df_win.config(bg=self.current_theme['bg'])

        main_frame = ttk.Frame(df_win, padding=10); main_frame.pack(fill=tk.BOTH, expand=True)
        
        filter_frame = ttk.LabelFrame(main_frame, text="Search Filters"); filter_frame.pack(padx=5, pady=5, fill=tk.X)
        filter_vars = { 'min_profit': tk.StringVar(value="1000"), 'max_buy_price': tk.StringVar(value="10000000"), 'min_volume': tk.StringVar(value="10"), 'search_query': tk.StringVar() }
        
        ttk.Label(filter_frame, text="Min Profit:").grid(row=0, column=0, padx=5, pady=5, sticky='w'); ttk.Entry(filter_frame, textvariable=filter_vars['min_profit'], width=10).grid(row=0, column=1, padx=5, pady=5)
        ttk.Label(filter_frame, text="Max Buy Price:").grid(row=0, column=2, padx=5, pady=5, sticky='w'); ttk.Entry(filter_frame, textvariable=filter_vars['max_buy_price'], width=12).grid(row=0, column=3, padx=5, pady=5)
        ttk.Label(filter_frame, text="Min Volume (1h):").grid(row=1, column=0, padx=5, pady=5, sticky='w'); ttk.Entry(filter_frame, textvariable=filter_vars['min_volume'], width=10).grid(row=1, column=1, padx=5, pady=5)
        ttk.Label(filter_frame, text="Item Name:").grid(row=1, column=2, padx=5, pady=5, sticky='w'); ttk.Entry(filter_frame, textvariable=filter_vars['search_query'], width=12).grid(row=1, column=3, padx=5, pady=5)
        
        search_btn = ttk.Button(filter_frame, text="Search"); search_btn.grid(row=0, column=4, rowspan=2, padx=5, pady=5, sticky='nsew'); filter_frame.columnconfigure(4, weight=1)
        
        tree_frame = ttk.Frame(main_frame); tree_frame.pack(padx=5, pady=(5, 5), fill=tk.BOTH, expand=True)
        cols = ('name', 'profit', 'buy_price', 'sell_price', 'volume', 'margin'); tree = ttk.Treeview(tree_frame, columns=cols, show='headings', height=5)
        tree.heading('name', text='Item', command=lambda: self._sort_tree_column(tree, 'name', False)); tree.heading('profit', text='Profit (2% Tax)', command=lambda: self._sort_tree_column(tree, 'profit', False)); tree.heading('buy_price', text='Buy Price', command=lambda: self._sort_tree_column(tree, 'buy_price', False)); tree.heading('sell_price', text='Sell Price', command=lambda: self._sort_tree_column(tree, 'sell_price', False)); tree.heading('volume', text='Volume (1h)', command=lambda: self._sort_tree_column(tree, 'volume', False)); tree.heading('margin', text='Margin', command=lambda: self._sort_tree_column(tree, 'margin', False))
        for col, width in [('name', 200), ('profit', 100), ('buy_price', 100), ('sell_price', 100), ('volume', 100), ('margin', 100)]: tree.column(col, width=width, anchor='w')
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        v_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview); v_scroll.pack(side=tk.RIGHT, fill=tk.Y); tree.configure(yscrollcommand=v_scroll.set)

        action_frame = ttk.LabelFrame(main_frame, text="Actions"); action_frame.pack(padx=5, pady=(0, 5), fill=tk.X)
        status_label = ttk.Label(action_frame, text="Ready to search."); status_label.pack(fill=tk.X, expand=True, pady=2, padx=5)

        df_btn_frame = ttk.Frame(action_frame)
        df_btn_frame.pack(fill=tk.X, expand=True, pady=(2,5), padx=5)
        df_btn_frame.columnconfigure((0,1), weight=1)
        
        use_item_btn = ttk.Button(df_btn_frame, text="Use Item in GE Interface", state=tk.DISABLED)
        use_item_btn.grid(row=0, column=0, sticky='ew', padx=(0,2))
        create_inject_step_btn = ttk.Button(df_btn_frame, text="Create GE Inject Step", state=tk.DISABLED)
        create_inject_step_btn.grid(row=0, column=1, sticky='ew', padx=(2,0))

        def on_tree_select(event):
            is_selected = True if tree.selection() else False
            use_item_btn.config(state=tk.NORMAL if is_selected else tk.DISABLED)
            create_inject_step_btn.config(state=tk.NORMAL if is_selected else tk.DISABLED)
        
        def _use_deal_in_interface():
            selected_item_id = tree.focus()
            if not selected_item_id: return
            item_data = tree.item(selected_item_id, 'values')
            name = item_data[0]
            self.ge_interface_item_name.set(name)
            self.log(f"Set GE Interface item to '{name}' from Deal Finder.")
            self.update_ge_interface_price() 
            df_win.destroy()

        def _create_ge_inject_step_from_deal():
            selected_item_id = tree.focus()
            if not selected_item_id: return
            item_data = tree.item(selected_item_id, 'values')
            name = item_data[0]
            self.add_step('logical')
            new_step = self.steps[-1]
            new_step['name'] = f"Inject: {name}"
            new_step['logical_type'] = 'GE Inject'
            new_step['ge_inject_field'] = 'Name'
            new_step['ge_inject_name'] = name
            self.log(f"Created 'GE Inject' step for '{name}' from Deal Finder.")
            self.selected_items = [{'type': 'step', 'index': len(self.steps) - 1}]
            self.populate_properties_panel()
            self.redraw_flowchart()
            df_win.destroy()

        def _search_for_deals():
            search_btn.config(state=tk.DISABLED); status_label.config(text="Fetching API data..."); df_win.update_idletasks(); tree.delete(*tree.get_children())
            
            if self.get_item_mapping() is None: status_label.config(text="Error: Could not load item map."); search_btn.config(state=tk.NORMAL); return
            all_prices = self.get_all_latest_prices(); 
            if not all_prices: status_label.config(text="Error: Could not load price data."); search_btn.config(state=tk.NORMAL); return
            all_volumes = self.get_all_hourly_volumes() 
            
            status_label.config(text="Analyzing data..."); df_win.update_idletasks()
            try:
                min_profit = int(filter_vars['min_profit'].get()); max_price = int(filter_vars['max_buy_price'].get()); min_volume = int(filter_vars['min_volume'].get()); query = filter_vars['search_query'].get().lower()
            except ValueError: status_label.config(text="Error: Invalid filter values."); search_btn.config(state=tk.NORMAL); return
            
            id_map, results = self.item_mapping_cache.get('by_id', {}), []
            for item_id, data in all_prices.items():
                if not (data and data.get('high') is not None and data.get('low') is not None and data['high'] > 0 and data['low'] > 0): continue
                buy_price, sell_price = data['low'], data['high']
                volume_data = all_volumes.get(item_id) if all_volumes else {}
                volume = (volume_data.get('highPriceVolume', 0) if volume_data else 0) + (volume_data.get('lowPriceVolume', 0) if volume_data else 0)
                item_info = id_map.get(int(item_id))
                
                if not item_info: continue
                profit = int(sell_price * 0.98) - buy_price
                
                if (buy_price < max_price and volume >= min_volume and profit >= min_profit and (query in item_info['name'].lower())):
                    results.append({'name': item_info['name'], 'profit': profit, 'buy': buy_price, 'sell': sell_price, 'volume': volume, 'margin': sell_price - buy_price})
            
            results.sort(key=lambda x: x['profit'], reverse=True)
            for res in results: tree.insert('', 'end', values=(res['name'], f"{res['profit']:,}", f"{res['buy']:,}", f"{res['sell']:,}", f"{res['volume']:,}", f"{res['margin']:,}"))
            status_label.config(text=f"Search complete. Found {len(results)} deals."); search_btn.config(state=tk.NORMAL)

        tree.bind('<<TreeviewSelect>>', on_tree_select)
        search_btn.config(command=lambda: threading.Thread(target=_search_for_deals, daemon=True).start())
        use_item_btn.config(command=_use_deal_in_interface)
        create_inject_step_btn.config(command=_create_ge_inject_step_from_deal)
        self.update_widget_colors_recursive(df_win, self.current_theme)

    def _sort_tree_column(self, tree, col, reverse):
        data_list = [(tree.set(k, col), k) for k in tree.get_children('')]
        try: data_list.sort(key=lambda t: int(str(t[0]).replace(',', '')), reverse=reverse)
        except ValueError: data_list.sort(key=lambda t: str(t[0]).lower(), reverse=reverse)
        for index, (val, k) in enumerate(data_list): tree.move(k, '', index)
        tree.heading(col, command=lambda: self._sort_tree_column(tree, col, not reverse))

    def populate_note_properties(self, container, i):
        note = self.annotations[i]
        tk.Label(container, text="Properties for Note", font=('Helvetica', 11, 'bold')).grid(row=0, columnspan=3, sticky='w', pady=(0,10)); tk.Label(container, text="Text:").grid(row=1, column=0, sticky='nw', pady=2); w = tk.Text(container, height=4, width=30, wrap=tk.WORD); w.insert('1.0', note.get('text', '')); w.grid(row=1, column=1, columnspan=2, sticky='ew'); self.properties_widgets['note_text'] = w
        tk.Label(container, text="Opacity:").grid(row=2, column=0, sticky='w', pady=2); w = tk.StringVar(value=note.get('opacity', '50%')); self.properties_widgets['note_opacity'] = w; tk.OptionMenu(container, w, "100%", "75%", "50%", "25%", "0% (Border Only)").grid(row=2, column=1, columnspan=2, sticky='w')
        tk.Label(container, text="Color:").grid(row=3, column=0, sticky='w', pady=2); color_frame = tk.Frame(container); color_frame.grid(row=3, column=1, columnspan=2, sticky='w'); w = tk.Label(color_frame, text=" ", bg=note.get('color'), relief=tk.SUNKEN, width=4); w.pack(side=tk.LEFT); self.properties_widgets['note_swatch'] = w; tk.Button(color_frame, text="Choose Color", font=('Helvetica', 9), command=self.choose_note_color, relief=tk.FLAT).pack(side=tk.LEFT, padx=5)
        action_btn_frm = tk.Frame(container); action_btn_frm.grid(row=4, columnspan=3, sticky='ew', pady=(15,0)); btn_pack_style = {'side': tk.LEFT, 'expand': True, 'fill': tk.X, 'padx': 2}; tk.Button(action_btn_frm, text="Apply Changes", font=('Helvetica', 9, 'bold'), command=self.apply_properties_changes, relief=tk.FLAT).pack(**btn_pack_style); tk.Button(action_btn_frm, text="Duplicate Note", font=('Helvetica', 9, 'bold'), command=self.duplicate_note, relief=tk.FLAT).pack(**btn_pack_style); tk.Button(action_btn_frm, text="Delete Note", font=('Helvetica', 9, 'bold'), command=self.remove_note, relief=tk.FLAT).pack(**btn_pack_style)
        container.columnconfigure(1, weight=1)

    def reset_movement_baseline(self):
        if not (self.selected_items and len(self.selected_items) == 1 and self.selected_items[0]['type'] == 'step'): return
        step = self.steps[self.selected_items[0]['index']]
        if step.get('logical_type') == 'Movement Detect': 
            step['_previous_frame_for_movement'] = None
            self.log(f"Reset movement comparison for Step {self.selected_items[0]['index'] + 1}.")
            self.populate_properties_panel()

    def choose_note_color(self):
        if not (self.selected_items and len(self.selected_items) == 1 and self.selected_items[0]['type'] == 'note'): return
        initial_color = self.annotations[self.selected_items[0]['index']].get('color'); color_code = colorchooser.askcolor(title="Choose note color", initialcolor=initial_color)
        if color_code and color_code[1]: self.properties_widgets['note_swatch'].config(bg=color_code[1])

    def apply_properties_changes(self):
        if len(self.selected_items) != 1: return
        w, item_type = self.properties_widgets, self.selected_items[0]['type']
        try:
            if item_type == 'step':
                i = self.selected_items[0]['index']; s = self.steps[i]
                s['name'] = w['name_entry'].get()
                s['enable_logging'] = w['enable_logging'].get()
                
                if 'show_area' in w:
                    s['show_area'] = w['show_area'].get()
    
                s['delay_after']=float(w['delay_after'].get()); s['on_success_action']=w['on_success_action'].get(); s['on_success_goto_step']=int(w['on_success_goto_step'].get())
                if s['type'] == 'logical':
                    s['logical_type'] = w['logical_type'].get()
                    if s['logical_type'] == 'Wait': 
                        s['max_time'] = float(w['max_time'].get())
                        s['reset_on_start'] = w['reset_on_start'].get()
                        s.pop('timeout', None); s.pop('on_timeout_action', None); s.pop('on_timeout_goto_step', None); s.pop('reset_on_timeout', None)
                    elif s['logical_type'] == 'Count': 
                        s['max_count'] = int(w['max_count'].get()); s['on_count_reached_action'] = w['on_count_reached_action'].get(); s['on_count_reached_goto_step'] = int(w['on_count_reached_goto_step'].get()); s['on_count_reached_delay'] = float(w['on_count_reached_delay'].get()); s['reset_on_start'] = w['reset_on_start'].get()
                        s['reset_on_reach'] = w['reset_on_reach'].get()
                    elif s['logical_type'] == 'Type Text': 
                        s['text_source'] = w['text_source'].get()
                        s['text_to_type'] = w['text_to_type'].get()
                        s['ge_data_field'] = w['ge_data_field'].get()
                        s['press_enter'] = w['press_enter'].get()
                        s['enter_press_delay'] = float(w['enter_press_delay'].get())
                    elif s['logical_type'] == 'GE Inject':
                        s['ge_inject_field'] = w['ge_inject_field'].get()
                        s['ge_inject_name'] = w['ge_inject_name'].get()
                        s['ge_inject_quantity'] = w['ge_inject_quantity'].get()
                        s['ge_inject_refresh'] = w['ge_inject_refresh'].get()
                    elif s['logical_type'] == 'Settings Inject':
                        s['inject_setting_name'] = w['inject_setting_name'].get()
                        s['inject_setting_value'] = w['inject_setting_value'].get()
                    elif s['logical_type'] == 'Number':
                        s['expression']=w['expression'].get(); s['timeout']=float(w['timeout'].get()); s['on_timeout_action']=w['on_timeout_action'].get(); s['on_timeout_goto_step']=int(w['on_timeout_goto_step'].get()); s['psm_mode'] = w['psm_mode'].get(); s['oem_mode'] = w['oem_mode'].get(); s['image_mode'] = w['number_image_mode'].get()
                    elif s['logical_type'] == 'Movement Detect':
                        s['movement_tolerance'] = float(w['movement_tolerance'].get())
                        s['reset_on_start'] = w['reset_on_start'].get()
                        s['timeout']=float(w['timeout'].get())
                        s['on_timeout_action']=w['on_timeout_action'].get()
                        s['on_timeout_goto_step']=int(w['on_timeout_goto_step'].get())
                else:
                    s['timeout']=float(w['timeout'].get()); s['on_timeout_action']=w['on_timeout_action'].get(); s['on_timeout_goto_step']=int(w['on_timeout_goto_step'].get()); s['action']=w['action'].get()
                    if s['type']=='color': 
                        s['tolerance']=int(w['tolerance'].get())
                        s['color_space']=w['color_space'].get()
                        s['pixel_detect_enabled'] = w['pixel_detect_enabled'].get()
                        if not s['pixel_detect_enabled']:
                            s['min_pixel_area'] = int(w['min_pixel_area'].get())
                            s['blob_target'] = w['blob_target'].get()
                            s['split_blob_width'] = max(0, int(w['split_blob_width'].get() or 0))
                        if s.get('action') == 'Color Count':
                            s['count_expression'] = w['count_expression'].get()
                            s['count_max_cycles'] = int(w['count_max_cycles'].get())
                    elif s['type']=='png':
                        current_path = s.get('path', '')
                        image_mode_to_clear = w['image_mode'].get()
                        cache_key = f"{current_path}|{image_mode_to_clear}"
    
                        if cache_key in self.template_cache:
                            del self.template_cache[cache_key]
                            self.log(f"Refreshed cache for: {os.path.basename(current_path)}")
    
                        if cache_key in self.folder_image_cache:
                            del self.folder_image_cache[cache_key]
                            self.log(f"Refreshed cache for folder: {os.path.basename(current_path)}")
                        
                        s['threshold']=float(w['threshold'].get())
                        s['mode']=w['png_mode'].get()
                        s['image_mode']=w['image_mode'].get()
                        s['find_first_match'] = w['find_first_match'].get()
                        if s.get('action') == 'PNG Count':
                            s['count_expression'] = w['count_expression'].get()
                            s['count_max_cycles'] = int(w['count_max_cycles'].get())
                            for old_prop in ['counter_value', 'max_count', 'reset_on_start', 'reset_on_reach', 'on_count_reached_action', 'on_count_reached_goto_step', 'on_count_reached_delay']:
                                s.pop(old_prop, None)

                    elif s['type']=='location': s['key_to_press'] = w['key_press_entry'].get()
                self.log(f"Applied changes to Step {i+1}.")
            elif item_type == 'note':
                i = self.selected_items[0]['index']; n = self.annotations[i]
                n['text'] = w['note_text'].get("1.0", tk.END).strip(); n['opacity'] = w['note_opacity'].get(); n['color'] = w['note_swatch'].cget('bg')
                self.log(f"Applied changes to Note.")
            self.redraw_flowchart()
            self.populate_properties_panel()
        except Exception as e: messagebox.showerror("Invalid Input",f"Please check your input values.\n\nDetails: {e}")

    def apply_multi_properties_changes(self):
        if len(self.selected_items) <= 1 or self.selected_items[0]['type'] != 'step':
            return

        w = self.properties_widgets
        changed_props = {}

        # Collect changed values from widgets
        for prop, widget_var in w.items():
            if prop in ['container']: continue
            try:
                value = widget_var.get()
                if value not in [self.MULTIPLE_VALUES, "", None]:
                    # Type conversion
                    if prop in ['delay_after', 'timeout', 'threshold']: value = float(value)
                    elif prop == 'tolerance': value = int(value)
                    changed_props[prop] = value
            except (tk.TclError, ValueError):
                continue # Ignore widgets that don't have a get() method or have invalid values

        if not changed_props:
            self.log("No changes to apply to multiple steps.")
            return

        # Apply changes to all selected steps
        for item in self.selected_items:
            step = self.steps[item['index']]
            for prop, value in changed_props.items():
                step[prop] = value
    
        self.log(f"Applied batch changes to {len(self.selected_items)} steps.", "green")
        self.redraw_flowchart()
        self.populate_properties_panel()

    def _convert_injected_value(self, setting_key, raw_value):
        """Convert a Settings Inject value to the type its model variable wants.

        The type comes from global_settings_map rather than being restated here,
        so adding a setting there is all that is needed for it to be injectable.
        """
        kind = self.global_settings_map[setting_key]['type']
        text = str(raw_value).strip()
        if kind is str:
            for option in self.MOVE_MODE_VALUES:
                if text.lower() == option.lower(): return option
            raise ValueError(f"must be one of: {', '.join(self.MOVE_MODE_VALUES)}")
        if kind is bool:
            if text.lower() in ('true', '1', 'yes', 'on'): return True
            if text.lower() in ('false', '0', 'no', 'off'): return False
            raise ValueError("must be true or false")
        return kind(text)

    def apply_global_settings(self):
        try:
            # Settings controlled by Radiobuttons, Checkbuttons, or Scales are updated
            # directly via their own variable bindings and do not need to be "applied"
            # by this function. We must skip them to avoid errors.
            keys_to_skip = ['mouse_move_mode', 'grid_visible', 'grid_latching', 'grid_opacity']

            for key, ui_var in self.global_settings_ui_vars.items():
                if key in keys_to_skip:
                    continue  # Skip settings that are not from Entry widgets.
                
                setting_map = self.global_settings_map[key]
                value = setting_map['type'](ui_var.get())
                setting_map['model'].set(value)
                
            self.log("Global settings applied successfully.", "green")
        except ValueError as e:
            messagebox.showerror("Invalid Input", f"Please check your global settings values.\nOne of the values is not a valid number.\n\nDetails: {e}")
            self.log(f"Failed to apply global settings: {e}", "red")

    def _sync_global_settings_ui_from_model(self):
        for key, ui_var in self.global_settings_ui_vars.items():
            ui_var.set(str(self.global_settings_map[key]['model'].get()))

    def add_step(self, step_type):
        new_x, new_y = 50, 50
        if self.steps: last_step = self.steps[-1]; self._calculate_node_size(len(self.steps)-1); new_x, new_y = last_step.get('x', 50), last_step.get('y', 50) + last_step.get('_height', 60)/self.zoom_factor + 40
        num_steps = len(self.steps)
        step_name_map = {'location': 'New Click / Press'}
        step_name = step_name_map.get(step_type, f'New {step_type.title()}')
        step_defaults = {
            'type': step_type, 'name': step_name, 'delay_after': 1.0, 'timeout': 0, 
            'on_timeout_action': 'Stop', 'on_timeout_goto_step': 1, 'on_success_action': 'Next Step', 
            'on_success_goto_step': num_steps + 2, 'x': new_x, 'y': new_y, 'enable_logging': True, 'show_area': False,
            '_last_run_info': {'timestamp': None, 'result': None, 'details': 'Not yet run'}
        }
        if step_type == 'color': 
            step_defaults.update({
                'action':'Click Object', 'rgb':(255,0,0), 'tolerance':2, 'area':None, 'color_space': 'HSV',
                'min_pixel_area': 10,
                'count_expression': '>= 1',
                'count_max_cycles': 1,
                'blob_target': 'Largest Blob',
                'split_blob_width': 0,
            })
        elif step_type == 'png': 
            step_defaults.update({
                'action':'Click Object', 'mode':'file', 'path':'', 'threshold':0.8, 'area':None, 
                'image_mode': 'Grayscale', 'find_first_match': True,
                'count_expression': '>= 1',
                'count_max_cycles': 1
            })
        elif step_type == 'location': step_defaults.update({'action': 'Left Click', 'coords':(100,100), 'key_to_press': ''})
        elif step_type == 'logical':
            step_defaults.update({
                'action': 'Execute', 'logical_type': 'Count', 'counter_value': 0, 'max_count': 0, 'reset_on_start': False, 'reset_on_reach': False,
                'delay_after': 0.1, 'timer_start_time': None, 'last_cycle_time': 'N/A', 'max_time': 5,
                'text_to_type': '', 'press_enter': False, 'enter_press_delay': 0.1, 'text_source': 'Static Text', 'ge_data_field': 'Calculated Buy Price',
                'ge_inject_name': '', 'ge_inject_field': 'Name', 'ge_inject_quantity': '1',
                'ge_inject_refresh': False,
                'inject_setting_name': next(iter(self.INJECTABLE_SETTINGS)), 'inject_setting_value': '0.15',
                'on_count_reached_action': 'Stop', 'on_count_reached_goto_step': 1, 'on_count_reached_delay': 1.0,
                'expression': '> 0', 'area': None, 'timeout': 5, 'on_timeout_action': 'Next Step', 
                'image_mode': 'Grayscale', 'psm_mode': '6: Assume a single uniform block of text.', 'oem_mode': '3: Default, based on what is available.',
                'movement_tolerance': 5.0,
                '_previous_frame_for_movement': None
            })
        self.steps.append(step_defaults); self.log(f"Added Step {len(self.steps)}: {step_name}"); 
        self.selected_items = [{'type': 'step', 'index': len(self.steps)-1}]
        self.populate_properties_panel()
        self.redraw_flowchart()

    def add_annotation(self):
        new_note = {'type': 'note', 'x': 60, 'y': 60, 'width': 200, 'height': 120, 'text': 'New Note', 'color': '#fffacd', 'opacity': '0% (Border Only)'}
        self.annotations.append(new_note); self.log("Added a new note to the flowchart."); 
        self.selected_items = [{'type': 'note', 'index': len(self.annotations)-1}]
        self.populate_properties_panel()
        self.redraw_flowchart()

    def remove_step(self):
        if not (self.selected_items and len(self.selected_items) == 1 and self.selected_items[0]['type'] == 'step'): return
        index_to_remove = self.selected_items[0]['index']
        if not messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete Step {index_to_remove + 1}?"): return
        
        if index_to_remove in self.area_overlays:
            self.area_overlays[index_to_remove].destroy()
            del self.area_overlays[index_to_remove]

        self.steps.pop(index_to_remove)
        for step in self.steps:
            for goto_key in ['on_success_goto_step', 'on_timeout_goto_step', 'on_count_reached_goto_step']:
                if goto_key not in step: continue
                current_goto = step.get(goto_key, 0)
                if current_goto > index_to_remove + 1: step[goto_key] -= 1
                elif current_goto == index_to_remove + 1: step[goto_key] = 1
        self.log(f"Removed step {index_to_remove + 1}.")
        self.selected_items = []
        self.populate_properties_panel()
        self.redraw_flowchart()

    def remove_note(self):
        if not (self.selected_items and len(self.selected_items) == 1 and self.selected_items[0]['type'] == 'note'): return
        index_to_remove = self.selected_items[0]['index']
        if not messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete this note?"): return
        self.annotations.pop(index_to_remove); self.log(f"Removed note."); 
        self.selected_items = []
        self.populate_properties_panel()
        self.redraw_flowchart()

    def duplicate_step(self):
        if not (self.selected_items and len(self.selected_items) == 1 and self.selected_items[0]['type'] == 'step'): return
        index = self.selected_items[0]['index']; original_step = self.steps[index]; new_step = copy.deepcopy(original_step); self._calculate_node_size(index)
        new_step['x'] = original_step.get('x', 50) + 20; new_step['y'] = original_step.get('y', 50) + original_step.get('_height', 60)/self.zoom_factor + 30; new_step['name'] = original_step.get('name', 'Unnamed') + " (Copy)"
        new_index = len(self.steps)
        if new_step.get('on_success_goto_step') == index + 1: new_step['on_success_goto_step'] = new_index + 1
        if new_step.get('on_timeout_goto_step') == index + 1: new_step['on_timeout_goto_step'] = new_index + 1
        self.steps.append(new_step); self.log(f"Duplicated Step {index + 1} to new Step {len(self.steps)}."); 
        self.selected_items = [{'type': 'step', 'index': len(self.steps) - 1}]
        self.populate_properties_panel()
        self.redraw_flowchart()

    def duplicate_note(self):
        if not (self.selected_items and len(self.selected_items) == 1 and self.selected_items[0]['type'] == 'note'): return
        index = self.selected_items[0]['index']
        original_note = self.annotations[index]
        new_note = copy.deepcopy(original_note)
        new_note['x'] = original_note.get('x', 50) + 20
        new_note['y'] = original_note.get('y', 50) + 20
        self.annotations.append(new_note)
        self.log("Duplicated note.")
        self.selected_items = [{'type': 'note', 'index': len(self.annotations) - 1}]
        self.populate_properties_panel()
        self.redraw_flowchart()

    def delete_selected(self):
        if not self.selected_items or self.selected_items[0]['type'] != 'step':
            return
        
        indices_to_remove = sorted([item['index'] for item in self.selected_items], reverse=True)
        for index in indices_to_remove:
            if index in self.area_overlays:
                self.area_overlays[index].destroy()
                del self.area_overlays[index]
        
        index_map = {i: i for i in range(len(self.steps))}
        for i in sorted(indices_to_remove, reverse=False):
            index_map.pop(i)
            for j in range(i + 1, len(self.steps)):
                if j in index_map: index_map[j] -= 1
        for index in indices_to_remove: self.steps.pop(index)
        for step in self.steps:
            for goto_key in ['on_success_goto_step', 'on_timeout_goto_step', 'on_count_reached_goto_step']:
                if goto_key not in step: continue
                old_target_idx = step.get(goto_key, 1) - 1
                new_target_idx = index_map.get(old_target_idx, -1)
                step[goto_key] = new_target_idx + 1 if new_target_idx != -1 else 1
        self.log(f"Removed {len(indices_to_remove)} steps.")
        self.selected_items = []
        self.populate_properties_panel()
        self.redraw_flowchart()
        self.update_all_area_overlays() # Refresh overlays as indices have changed

    def duplicate_selected(self):
        if not self.selected_items or self.selected_items[0]['type'] != 'step': return
        original_indices = sorted([item['index'] for item in self.selected_items]);
        if not original_indices: return
        new_steps, old_to_new_index_map, current_len = [], {}, len(self.steps)
        for i, original_index in enumerate(original_indices):
            new_index = current_len + i; old_to_new_index_map[original_index] = new_index
            original_step = self.steps[original_index]; new_step = copy.deepcopy(original_step); new_step['name'] += " (Copy)"; new_steps.append(new_step)
        for i, new_step in enumerate(new_steps):
            original_index = original_indices[i]
            for action_key, goto_key in [('on_success_action', 'on_success_goto_step'), ('on_timeout_action', 'on_timeout_goto_step'), ('on_count_reached_action', 'on_count_reached_goto_step')]:
                if action_key not in new_step: continue
                action = new_step.get(action_key)
                if action == 'Go to Step':
                    target_original_index = new_step.get(goto_key, 1) - 1
                    if target_original_index in old_to_new_index_map: new_step[goto_key] = old_to_new_index_map[target_original_index] + 1
                    else: new_step[action_key] = 'Stop'
                elif action == 'Next Step':
                    next_original_index = original_index + 1
                    if next_original_index not in old_to_new_index_map: new_step[action_key] = 'Stop'
        min_x = min(self.steps[i].get('x', 0) for i in original_indices); max_y = 0
        for i in original_indices:
            self._calculate_node_size(i)
            current_max_y = self.steps[i].get('y', 0) + self.steps[i].get('_height', 60) / self.zoom_factor
            if current_max_y > max_y: max_y = current_max_y
        y_offset = max_y + 60
        for i, new_step in enumerate(new_steps):
            original_pos_x = self.steps[original_indices[i]].get('x', 0); original_pos_y = self.steps[original_indices[i]].get('y', 0)
            new_step['x'] = original_pos_x ; new_step['y'] = y_offset + (original_pos_y - self.steps[original_indices[0]].get('y', 0))
        self.steps.extend(new_steps); self.log(f"Duplicated {len(new_steps)} steps.")
        new_indices_range = range(len(self.steps) - len(new_steps), len(self.steps))
        self.selected_items = [{'type': 'step', 'index': i} for i in new_indices_range]
        self.populate_properties_panel(); self.redraw_flowchart()
        self.update_all_area_overlays() # Redraw overlays for new duplicated steps

    def reset_logical_counter(self):
        if not (self.selected_items and len(self.selected_items) == 1 and self.selected_items[0]['type'] == 'step'): return
        step = self.steps[self.selected_items[0]['index']]
        if step.get('logical_type') == 'Count': step['counter_value'] = 0; self.log(f"Reset counter for Step {self.selected_items[0]['index'] + 1}."); self.populate_properties_panel()
       
    def reset_timer(self):
        if not (self.selected_items and len(self.selected_items) == 1 and self.selected_items[0]['type'] == 'step'): return
        step = self.steps[self.selected_items[0]['index']]
        if step.get('logical_type') == 'Wait': step['timer_start_time'] = None; step['last_cycle_time'] = 'N/A'; self.log(f"Reset wait timer for Step {self.selected_items[0]['index'] + 1}."); self.populate_properties_panel()

    def _pre_cache_folder_templates(self):
        """
        Proactively loads and caches templates for all PNG steps in folder mode.
        This prevents a long delay on the first detection attempt of each step.
        """
        self.log("Pre-caching templates for PNG Folder steps...")
        count = 0
        for i, step in enumerate(self.steps):
            if step.get('type') == 'png' and step.get('mode') == 'folder' and step.get('path') and os.path.isdir(step['path']):
                image_mode = step.get('image_mode', 'Grayscale')
                folder_cache_key = f"{step['path']}|{image_mode}"
                
                if folder_cache_key not in self.folder_image_cache:
                    self.folder_image_cache[folder_cache_key] = []
                    image_paths = [os.path.join(step['path'], fname) for fname in os.listdir(step['path']) if fname.lower().endswith('.png')]
                    for fpath in image_paths:
                        template_data = self.load_template(fpath, image_mode)
                        if template_data[0] is not None:
                            self.folder_image_cache[folder_cache_key].append(template_data)
                    
                    num_cached = len(self.folder_image_cache[folder_cache_key])
                    if num_cached > 0:
                        self.log(f" > Cached {num_cached} templates for Step {i+1} from '{os.path.basename(step['path'])}'.")
                        count += num_cached
        if count > 0:
            self.log(f"Finished pre-caching {count} total templates.", "green")
        else:
            self.log("No new PNG Folder steps found to pre-cache.")

    def start(self):
        if self.running or self.f3_mode: return
        if not self.steps: messagebox.showerror("Error", "No steps defined."); return
        
        self._pre_cache_folder_templates()
        
        resetted_items = []
        for i, step in enumerate(self.steps):
            if step.get('type') == 'logical' and step.get('reset_on_start'):
                if step.get('logical_type') == 'Count':
                    step['counter_value'] = 0
                    resetted_items.append(f"Counter for Step {i+1}")
                elif step.get('logical_type') == 'Wait':
                    step['timer_start_time'] = None
                    step['last_cycle_time'] = 'N/A'
                    resetted_items.append(f"Timer for Step {i+1}")
                elif step.get('logical_type') == 'Movement Detect':
                    step['_previous_frame_for_movement'] = None
                    resetted_items.append(f"Movement Comparison for Step {i+1}")

        if resetted_items: self.log(f"Reset on start: {', '.join(resetted_items)}.")
        try:
            start_index = int(self.start_step.get()) - 1
            if not (0 <= start_index < len(self.steps)): messagebox.showerror("Invalid Start Step", f"Start step must be between 1 and {len(self.steps)}."); return
            self.current_step_index = start_index
        except ValueError: messagebox.showerror("Invalid Input", "Start step must be a valid number."); return
        
        # --- FIX: Set running flag to True BEFORE starting the timer loop ---
        self.running = True
        self.automation_start_time = time.time()
        self.cycle_time_display.set("Cycle Time: 00:00:00")
        self._update_cycle_time()
        
        self.status_label_color_state = 'green'
        self.log("Automation started.", 'green')
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.advance_step()

    def stop(self, message="Status: Stopped", color_state='blue'):
        """
        Stops the automation script. This method is designed to be thread-safe,
        as it can be called from the keyboard listener thread.
        """
        # Use a flag to prevent re-entry from multiple rapid presses
        if self.stop_requested:
            return
        self.stop_requested = True
        
        # 1. Immediately set the main running flag to False. This is the primary
        #    mechanism to halt the execution loops and interruptible moves.
        self.running = False
        
        # 2. Cancel any pending `after` calls, which schedule future work.
        #    This is thread-safe according to Tkinter's documentation.
        if self.executor_after_id: self.root.after_cancel(self.executor_after_id)
        if self.delay_countdown_id: self.root.after_cancel(self.delay_countdown_id)
        if self.timeout_countdown_id: self.root.after_cancel(self.timeout_countdown_id)
        if self.cycle_time_updater_id: self.root.after_cancel(self.cycle_time_updater_id); self.cycle_time_updater_id = None

        # 3. Safely handle the background detection thread state.
        with self.detection_lock:
            self.detection_thread = None
            self.detection_result = None

        # 4. Schedule the final state changes and UI updates to run in the main Tkinter thread.
        self.root.after(0, self._finalize_stop_ui, message, color_state)

    def _finalize_stop_ui(self, message, color_state):
        """
        Performs the final, non-thread-safe actions to complete the stop process.
        This method MUST be called from the main Tkinter thread via `root.after()`.
        """
        if self.automation_start_time > 0:
            final_elapsed = time.time() - self.automation_start_time
            total_seconds = int(final_elapsed)
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            time_str = f"{hours:02}:{minutes:02}:{seconds:02}"
            self.log(f"Automation stopped. Total cycle time: {time_str}.")
            self.automation_start_time = 0

        # Update the 'Start Step' field if the option is enabled.
        if self.start_at_stopped_pos.get() and self.current_step_index < len(self.steps):
            next_start_step = str(self.current_step_index + 1)
            self.start_step.set(next_start_step)
            self.log(f"Next start step set to {next_start_step}.")

        # Reset internal state variables that hold `after` IDs.
        self.executor_after_id = None
        self.delay_countdown_id = None
        self.timeout_countdown_id = None

        # Update all UI elements to reflect the stopped state.
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_label_color_state = color_state
        color = self.current_theme.get(f"status_{color_state}", self.current_theme.get('status_blue'))
        self.status_label.config(text=message, foreground=color)
        self.delay_countdown_label.config(text="")
        self.timeout_countdown_label.config(text="")
        self.redraw_flowchart() # Redraw to remove the 'current step' highlight
        
        # Reset the request flag after everything is done.
        self.stop_requested = False

    def advance_step(self):
        if not self.running or not self.steps: self.stop(); return
        if self.timeout_countdown_id: self.root.after_cancel(self.timeout_countdown_id); self.timeout_countdown_id = None
        self.timeout_countdown_label.config(text=""); self.last_detection_info.set("Detection: N/A")
        
        with self.detection_lock:
            self.detection_thread = None
            self.detection_result = None

        if self.current_step_index >= len(self.steps): self.log("Completed all steps.", "green"); self.stop("Status: Completed all steps", color_state='green'); return
        self.current_step_start_time = time.time(); self.redraw_flowchart(); self.run_step_executor()

    def _update_cycle_time(self):
        if self.running:
            elapsed = time.time() - self.automation_start_time
            total_seconds = int(elapsed)
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            time_str = f"{hours:02}:{minutes:02}:{seconds:02}"
            self.cycle_time_display.set(f"Cycle Time: {time_str}")
            self.cycle_time_updater_id = self.root.after(100, self._update_cycle_time)

    def _perform_png_detection_in_thread(self, screen_cv, offset, step):
        """
        Runs the find_png method in a separate thread to avoid blocking the GUI.
        The result is stored in self.detection_result.
        """
        try:
            target_pos, confidence = self.find_png(screen_cv, offset, step)
            with self.detection_lock:
                if self.detection_thread is threading.current_thread():
                    self.detection_result = ('png', target_pos, confidence)
        except Exception as e:
            print(f"Error in detection thread: {e}")
            with self.detection_lock:
                if self.detection_thread is threading.current_thread():
                    self.detection_result = ('png', None, 0)

    def _perform_color_detection_in_thread(self, screen_cv, offset, step):
        """
        Runs color detection in a separate thread. The result is stored in self.detection_result.
        """
        try:
            target_pos, contour_area = None, 0
            if step.get('pixel_detect_enabled', False):
                coords = step.get('pixel_coords')
                if coords:
                    current_rgb = pyautogui.pixel(coords[0], coords[1])
                    target_rgb = step.get('rgb'); tolerance = step.get('tolerance'); color_space = step.get('color_space', 'HSV')
                    match = False
                    if color_space == 'RGB':
                        match = all(abs(c1 - c2) <= tolerance for c1, c2 in zip(current_rgb, target_rgb))
                    else: 
                        current_bgr = np.uint8([[list(reversed(current_rgb))]])
                        target_bgr = np.uint8([[list(reversed(target_rgb))]])
                        current_hsv = cv2.cvtColor(current_bgr, cv2.COLOR_BGR2HSV)[0][0]
                        target_hsv = cv2.cvtColor(target_bgr, cv2.COLOR_BGR2HSV)[0][0]
                        h, s, v = int(target_hsv[0]), int(target_hsv[1]), int(target_hsv[2])
                        h_tol, s_tol, v_tol = int(tolerance*1.8), int(tolerance*2.5), int(tolerance*2.5)
                        h_diff = abs(int(current_hsv[0]) - h); h_match = min(h_diff, 180 - h_diff) <= h_tol
                        s_match = abs(int(current_hsv[1]) - s) <= s_tol
                        v_match = abs(int(current_hsv[2]) - v) <= v_tol
                        match = h_match and s_match and v_match
                    if match:
                        target_pos, contour_area = coords, 1 
            else: 
                color_space = step.get('color_space', 'HSV')
                if color_space == 'RGB':
                    target_pos, contour_area = self.find_color_on_screen_rgb(screen_cv, offset, step)
                else:
                    target_pos, contour_area = self.find_color_on_screen_hsv(screen_cv, offset, step)
            
            with self.detection_lock:
                if self.detection_thread is threading.current_thread():
                    self.detection_result = ('color', target_pos, contour_area)
        except Exception as e:
            print(f"Error in color detection thread: {e}")
            with self.detection_lock:
                if self.detection_thread is threading.current_thread():
                    self.detection_result = ('color', None, 0)

    def _perform_movement_detection_in_thread(self, current_frame_cv, previous_frame, step):
        """
        Runs movement comparison logic in a separate thread.
        """
        try:
            if previous_frame.shape != current_frame_cv.shape:
                raise ValueError("Frame dimension mismatch during movement detection.")

            diff = cv2.absdiff(previous_frame, current_frame_cv)
            _, thresholded_diff = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
            
            non_zero_count = np.count_nonzero(thresholded_diff)
            total_pixels = thresholded_diff.size
            change_percentage = (non_zero_count / total_pixels) * 100 if total_pixels > 0 else 0
            
            tolerance = step.get('movement_tolerance', 5.0)
            is_still = change_percentage <= tolerance

            with self.detection_lock:
                if self.detection_thread is threading.current_thread():
                    self.detection_result = ('movement', is_still, change_percentage)
        except Exception as e:
            print(f"Error in movement detection thread: {e}")
            with self.detection_lock:
                if self.detection_thread is threading.current_thread():
                     self.detection_result = ('movement', False, -1) # Indicate error

    def grab_frame(self, area, gray=False):
        """Capture a screen area straight into an OpenCV array.

        The Wayland backend can hand back pixels without grim's PNG encoder, a
        PIL decode and a second copy back into numpy. Capture dominates the scan
        loop (colour detection itself is ~5 ms against ~350 ms of PNG work), so
        this is the difference between tracking a moving target and lagging it.

        Falls back to pyautogui, which returns a PIL image, on Windows/macOS and
        on any backend without the fast path.
        """
        x1, y1, x2, y2 = area
        region = (x1, y1, x2 - x1, y2 - y1)
        fast = getattr(pyautogui, 'screenshot_array', None)
        rgb = fast(region=region) if fast is not None else np.array(pyautogui.screenshot(region=region))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY if gray else cv2.COLOR_RGB2BGR)

    def run_step_executor(self):
        if not self.running: return
        if not (0 <= self.current_step_index < len(self.steps)):
            self.log(f"Error: Invalid step index {self.current_step_index} detected. Stopping.", "red"); self.stop("Status: Stopped due to invalid index", "red"); return

        step = self.steps[self.current_step_index]
        step['_last_run_info'] = {'timestamp': time.time(), 'result': 'Running', 'details': 'Executing...'}
        self.status_label.config(text=f"Running Step {self.current_step_index + 1}: {step.get('name', '')}", foreground=self.current_theme['status_green'])
        
        is_timeout_step = (step.get('type') in ['color', 'png']) or \
                          (step.get('logical_type') in ['Number', 'Movement Detect'])

        if is_timeout_step and step.get('timeout', 0) > 0:
            if time.time() - self.current_step_start_time > step['timeout']: self.handle_timeout(); return
            self.update_timeout_countdown(self.current_step_start_time, step['timeout'])
            
        target_pos, step_succeeded = None, False
        try:
            if step['type'] == 'color' and step.get('action') == 'Color Count':
                area = step.get('area') or (self.area_x1.get(), self.area_y1.get(), self.area_x2.get(), self.area_y2.get())
                w, h = area[2] - area[0], area[3] - area[1]
                if w < 1 or h < 1:
                    self.log_execution(f"Step {self.current_step_index + 1}: Invalid area for Color Count. Failing.", "red")
                    self.handle_timeout(); return

                screen_cv = self.grab_frame(area)
                
                count = self.find_and_count_color(screen_cv, area[0:2], step)
                expression_str = step.get('count_expression', '>= 1')
                
                step.setdefault('_count_current_cycle', 0)
                max_cycles = step.get('count_max_cycles', 1)
                
                self.last_detection_info.set(f"Color Count: Found {count} blobs. Condition: {expression_str}")
                
                try:
                    expression = expression_str.split()
                    if len(expression) != 2: raise ValueError("Expression must have 2 parts (e.g., '>= 5')")
                    op, val = expression[0], int(expression[1])
                    op_map = {'>': count > val, '<': count < val, '>=': count >= val, '<=': count <= val, '==': count == val, '!=': count != val}
                    result = op_map.get(op, False)
                    
                    if result:
                        self.log_execution(f"Step {self.current_step_index + 1}: Color Count SUCCEEDED. Found {count} blob(s). Condition '{expression_str}' is TRUE.", "green")
                        step['_last_run_info'] = {'timestamp': time.time(), 'result': True, 'details': f"Found {count} color blobs. Expression '{count} {op} {val}' was {result}."}
                        step['_count_current_cycle'] = 0
                        step_succeeded = True
                    else:
                        self.log_execution(f"Step {self.current_step_index + 1}: Color Count FAILED. Found {count} blob(s). Condition '{expression_str}' is FALSE.", "orange")
                        step['_last_run_info'] = {'timestamp': time.time(), 'result': False, 'details': f"Found {count} color blobs. Expression '{count} {op} {val}' was {result}."}
                        step['_count_current_cycle'] += 1
                        self.last_detection_info.set(f"Color Count: Failed. Cycle {step['_count_current_cycle']}/{max_cycles}")
                        if step['_count_current_cycle'] >= max_cycles:
                            self.log_execution(f"Step {self.current_step_index + 1}: Color Count failed after {max_cycles} cycle(s).", "orange")
                            step['_count_current_cycle'] = 0
                            self.handle_timeout()
                            return
                        else:
                            self.executor_after_id = self.root.after(int(self.scan_interval.get() * 1000), self.run_step_executor)
                            return
                except (ValueError, IndexError) as e:
                    self.log_execution(f"Step {self.current_step_index + 1}: Invalid expression '{expression_str}'. Failing: {e}", "red")
                    step['_count_current_cycle'] = 0
                    self.handle_timeout()
                    return

            elif step['type'] == 'png' and step.get('action') == 'PNG Count':
                area = step.get('area') or (self.area_x1.get(), self.area_y1.get(), self.area_x2.get(), self.area_y2.get())
                w, h = area[2] - area[0], area[3] - area[1]
                if w < 1 or h < 1:
                    self.log_execution(f"Step {self.current_step_index + 1}: Invalid area for PNG Count. Failing.", "red")
                    self.handle_timeout(); return

                screen_cv = self.grab_frame(area)
                
                count = self.find_and_count_png(screen_cv, area[0:2], step)
                expression_str = step.get('count_expression', '>= 1')
                
                step.setdefault('_count_current_cycle', 0)
                max_cycles = step.get('count_max_cycles', 1)
                
                self.last_detection_info.set(f"PNG Count: Found {count}. Condition: {expression_str}")
                
                try:
                    expression = expression_str.split()
                    if len(expression) != 2: raise ValueError("Expression must have 2 parts (e.g., '>= 5')")
                    op, val = expression[0], int(expression[1])
                    op_map = {'>': count > val, '<': count < val, '>=': count >= val, '<=': count <= val, '==': count == val, '!=': count != val}
                    result = op_map.get(op, False)
                    
                    if result:
                        self.log_execution(f"Step {self.current_step_index + 1}: PNG Count SUCCEEDED. Found {count} instance(s). Condition '{expression_str}' is TRUE.", "green")
                        step['_last_run_info'] = {'timestamp': time.time(), 'result': True, 'details': f"Found {count} instances. Expression '{count} {op} {val}' was {result}."}
                        step['_count_current_cycle'] = 0
                        step_succeeded = True
                    else:
                        self.log_execution(f"Step {self.current_step_index + 1}: PNG Count FAILED. Found {count} instance(s). Condition '{expression_str}' is FALSE.", "orange")
                        step['_last_run_info'] = {'timestamp': time.time(), 'result': False, 'details': f"Found {count} instances. Expression '{count} {op} {val}' was {result}."}
                        step['_count_current_cycle'] += 1
                        self.last_detection_info.set(f"PNG Count: Failed. Cycle {step['_count_current_cycle']}/{max_cycles}")
                        if step['_count_current_cycle'] >= max_cycles:
                            self.log_execution(f"Step {self.current_step_index + 1}: PNG Count failed after {max_cycles} cycle(s).", "orange")
                            step['_count_current_cycle'] = 0
                            self.handle_timeout()
                            return
                        else:
                            self.executor_after_id = self.root.after(int(self.scan_interval.get() * 1000), self.run_step_executor)
                            return
                except (ValueError, IndexError) as e:
                    self.log_execution(f"Step {self.current_step_index + 1}: Invalid expression '{expression_str}'. Failing: {e}", "red")
                    step['_count_current_cycle'] = 0
                    self.handle_timeout()
                    return
            
            elif step['type'] == 'location': 
                target_pos, step_succeeded = step['coords'], True
                action_text = f"Press Key '{step.get('key_to_press')}'" if step.get('action') == 'Key Press' else f"{step.get('action')} at {step.get('coords')}"
                self.last_detection_info.set(f"Action: {action_text}")
                step['_last_run_info'] = {'timestamp': time.time(), 'result': True, 'details': f"Action '{step.get('action')}' scheduled."}

            elif step['type'] == 'logical':
                step_succeeded, should_return = self.execute_logical_step(step)
                if should_return: return

            else: # Threaded Detection for regular PNG, Color
                with self.detection_lock:
                    if self.detection_thread and self.detection_thread.is_alive():
                        self.executor_after_id = self.root.after(int(self.scan_interval.get() * 1000), self.run_step_executor); return
                    
                    if self.detection_result:
                        result_type, target_pos, confidence = self.detection_result
                        current_step_type = step.get('logical_type') or step.get('type')
                        
                        if result_type == current_step_type:
                            if result_type == 'png':
                                if target_pos:
                                    step_succeeded = True
                                    self.last_detection_info.set(f"PNG Found: {confidence*100:.1f}%")
                                    self.log_execution(f"Step {self.current_step_index + 1}: PNG FOUND at {target_pos} with {confidence*100:.1f}% confidence.", "green")
                                    step['_last_run_info'] = {'timestamp': time.time(), 'result': True, 'details': f"Found at {target_pos} with {confidence*100:.1f}% confidence."}
                            
                            elif result_type == 'color':
                                contour_area = confidence # In color detection, confidence holds the area
                                if target_pos:
                                    step_succeeded = True
                                    self.last_detection_info.set(f"Color Found: Area {contour_area:.0f}px")
                                    if step.get('pixel_detect_enabled'):
                                        self.log_execution(f"Step {self.current_step_index + 1}: Pixel Color FOUND at {target_pos}.", "green")
                                        step['_last_run_info'] = {'timestamp': time.time(), 'result': True, 'details': f"Found pixel at {target_pos}."}
                                    else:
                                        self.log_execution(f"Step {self.current_step_index + 1}: Color Area FOUND at {target_pos} with area {contour_area:.0f}px.", "green")
                                        step['_last_run_info'] = {'timestamp': time.time(), 'result': True, 'details': f"Found at {target_pos} with area {contour_area:.0f}px."}
                        
                        self.detection_result = None

                if not step_succeeded:
                    area = step.get('area') or (self.area_x1.get(),self.area_y1.get(),self.area_x2.get(),self.area_y2.get())
                    w,h = area[2]-area[0],area[3]-area[1]
                    if w < 1 or h < 1: 
                        self.executor_after_id = self.root.after(int(self.scan_interval.get()*1000),self.run_step_executor); return
                    
                    screen_cv = self.grab_frame(area)

                    if step['type'] == 'png':
                        self.last_detection_info.set(f"PNG: Searching for {os.path.basename(step.get('path'))}...")
                        self.log_execution(f"Step {self.current_step_index + 1}: Searching for PNG '{os.path.basename(step.get('path'))}' in area {area} (Thresh: {step.get('threshold')}).")
                        self.detection_thread = threading.Thread(target=self._perform_png_detection_in_thread, args=(screen_cv, area[0:2], step), daemon=True)
                    elif step['type'] == 'color':
                        if step.get('pixel_detect_enabled'):
                            self.last_detection_info.set(f"Color: Searching for RGB {step.get('rgb')} at pixel {step.get('pixel_coords')}...")
                            self.log_execution(f"Step {self.current_step_index + 1}: Checking for Color {step.get('rgb')} at pixel {step.get('pixel_coords')} (Tol: {step.get('tolerance')}, Space: {step.get('color_space')}).")
                        else:
                            self.last_detection_info.set(f"Color: Searching for RGB {step.get('rgb')}...")
                            self.log_execution(f"Step {self.current_step_index + 1}: Searching for Color {step.get('rgb')} in area {area} (Tol: {step.get('tolerance')}, Space: {step.get('color_space')}).")
                        self.detection_thread = threading.Thread(target=self._perform_color_detection_in_thread, args=(screen_cv, area[0:2], step), daemon=True)
                    
                    if self.detection_thread: self.detection_thread.start()
                    self.executor_after_id = self.root.after(int(self.scan_interval.get()*1000), self.run_step_executor)
                    return

            # --- ACTION AND FLOW CONTROL (After a step succeeds) ---
            if step_succeeded:
                if self.timeout_countdown_id:
                    self.root.after_cancel(self.timeout_countdown_id)
                    self.timeout_countdown_id = None
                self.timeout_countdown_label.config(text="")
                
                if step['type'] == 'location':
                    if step.get('action') == 'Key Press':
                        pyautogui.press(step.get('key_to_press'))
                        self.log_execution(f"Step {self.current_step_index + 1}: Pressed key '{step.get('key_to_press')}'.")
                    else: 
                        self.execute_action_on_pos(step.get('action'), target_pos)
                elif step['type'] != 'logical': # For regular PNG and Color
                    self.execute_action_on_pos(step.get('action'), target_pos)
                
                self.handle_flow_control('on_success_action', 'on_success_goto_step')
            else:
                 self.executor_after_id = self.root.after(int(self.scan_interval.get()*1000), self.run_step_executor)

        except Exception as e:
            messagebox.showerror("Execution Error", str(e)); self.log(f"Execution Error: {e}", "red"); self.stop("Status: Stopped due to error", color_state='red'); return

    def execute_logical_step(self, step):
        logical_type = step.get('logical_type')
        if logical_type == 'Count':
            current_val = step.get('counter_value', 0)
            max_count = step.get('max_count', 0)
            self.last_detection_info.set(f"Count: {current_val + 1} / {max_count if max_count > 0 else '∞'}")
            step['counter_value'] = current_val + 1
            step['_last_run_info'] = {'timestamp': time.time(), 'result': True, 'details': f"Counter incremented to {step['counter_value']}."}
            self.log_execution(f"Step {self.current_step_index + 1}: Count is now {step['counter_value']}/{max_count if max_count > 0 else '∞'}.")
            
            if max_count > 0 and step['counter_value'] >= max_count:
                step['_last_run_info']['result'] = 'Reached'
                step['_last_run_info']['details'] += f" Max count of {max_count} reached."
                self.log_execution(f"Step {self.current_step_index + 1}: Max count of {max_count} reached.", "orange")
                self.handle_flow_control('on_count_reached_action', 'on_count_reached_goto_step')
                if step.get('reset_on_reach', False):
                    step['counter_value'] = 0
                    self.log_execution(f"Step {self.current_step_index + 1}: Counter reset after reaching max count.")
                return False, True 
            return True, False

        elif logical_type == 'Wait':
            if step.get('timer_start_time') is None:
                step['timer_start_time'] = time.time()
            elapsed = time.time() - step['timer_start_time']
            max_time = step.get('max_time', 0)
            self.last_detection_info.set(f"Wait: {elapsed:.1f}s / {max_time:.1f}s")
            step['_last_run_info'] = {'timestamp': time.time(), 'result': 'Waiting', 'details': f"Elapsed: {elapsed:.1f}s"}
            if elapsed >= max_time:
                step['_last_run_info']['result'] = True
                step['_last_run_info']['details'] = f"Waited for {elapsed:.2f}s."
                self.log_execution(f"Step {self.current_step_index + 1}: Wait timer of {max_time}s finished.")
                step['last_cycle_time'] = round(elapsed, 2); step['timer_start_time'] = None
                return True, False
            else:
                self.executor_after_id = self.root.after(int(self.scan_interval.get()*1000), self.run_step_executor)
                return False, True

        elif logical_type == 'Type Text':
            text_to_type = ""
            source = step.get('text_source', 'Static Text')
            if source == 'GE Interface':
                field = step.get('ge_data_field')
                if field == "Item Name":
                    text_to_type = self.ge_interface_item_name.get()
                elif field == "Quantity":
                    text_to_type = self.ge_interface_item_quantity.get()
                else:
                    if self.ge_interface_last_data:
                        try:
                            data = self.ge_interface_last_data
                            high_price = int(data.get('high', 0))
                            low_price = int(data.get('low', 0))
                            quantity = int(self.ge_interface_item_quantity.get())
                            
                            if field == "Calculated Buy Price":
                                text_to_type = self._calculate_ge_price('buy', high_price, low_price)
                            elif field == "Calculated Sell Price":
                                text_to_type = self._calculate_ge_price('sell', high_price, low_price)
                            elif field == "Calculated Buy Total":
                                price = self._calculate_ge_price('buy', high_price, low_price)
                                text_to_type = price * quantity
                            elif field == "Calculated Sell Total":
                                price = self._calculate_ge_price('sell', high_price, low_price)
                                text_to_type = price * quantity
                            
                        except (ValueError, TypeError) as e:
                            self.log_execution(f"Step {self.current_step_index + 1}: Error processing GE data: {e}", "red")
                            text_to_type = "ERROR"
                    else:
                        self.log_execution(f"Step {self.current_step_index + 1}: No GE data available to type. Fetch data first.", "orange")
                        text_to_type = ""
            else: 
                text_to_type = step.get('text_to_type', '')
            
            self.last_detection_info.set(f"Type Text: Typing '{str(text_to_type)[:25]}...'")
            pyautogui.write(str(text_to_type).replace(',', ''), interval=0.05)
            if step.get('press_enter', False):
                delay = step.get('enter_press_delay', 0.1)
                time.sleep(delay)
                pyautogui.press('enter')
            
            step['_last_run_info'] = {'timestamp': time.time(), 'result': True, 'details': f"Typed '{text_to_type}' from {source}."}
            self.log_execution(f"Step {self.current_step_index + 1}: Typed text '{text_to_type}' from {source}.")
            return True, False

        elif logical_type == 'GE Inject':
            field = step.get('ge_inject_field', 'Name')
            if field == 'Quantity':
                quantity_to_inject = step.get('ge_inject_quantity', '1')
                self.ge_interface_item_quantity.set(quantity_to_inject)
                self.last_detection_info.set(f"GE Inject: Set quantity to '{quantity_to_inject}'")
                step['_last_run_info'] = {'timestamp': time.time(), 'result': True, 'details': f"Injected quantity '{quantity_to_inject}'."}
                self.log_execution(f"Step {self.current_step_index + 1}: Injected quantity '{quantity_to_inject}' into GE Interface.")
            else: # Default to Name
                item_name = step.get('ge_inject_name', '')
                self.ge_interface_item_name.set(item_name)
                self.last_detection_info.set(f"GE Inject: Set item to '{item_name}'")
                step['_last_run_info'] = {'timestamp': time.time(), 'result': True, 'details': f"Injected item name '{item_name}'."}
                self.log_execution(f"Step {self.current_step_index + 1}: Injected item name '{item_name}' into GE Interface.")
            
            if step.get('ge_inject_refresh', False):
                self.log_execution(f"Step {self.current_step_index + 1}: Triggering GE price refresh after inject.")
                self.update_ge_interface_price()

            return True, False
        
        elif logical_type == 'Settings Inject':
            setting_name = step.get('inject_setting_name')
            new_value_str = step.get('inject_setting_value')

            setting_key = self.INJECTABLE_SETTINGS.get(setting_name)
            if setting_key is not None:
                try:
                    converted_value = self._convert_injected_value(setting_key, new_value_str)
                    self.global_settings_map[setting_key]['model'].set(converted_value)
                    self._sync_global_settings_ui_from_model() # Update UI
                    
                    self.last_detection_info.set(f"Inject: Set {setting_name} to {converted_value}")
                    details = f"Injected '{setting_name}' = {converted_value}"
                    step['_last_run_info'] = {'timestamp': time.time(), 'result': True, 'details': details}
                    self.log_execution(f"Step {self.current_step_index + 1}: {details}.")
                    return True, False
                except (ValueError, tk.TclError) as e:
                    details = f"Invalid value '{new_value_str}' for {setting_name}. Error: {e}"
                    step['_last_run_info'] = {'timestamp': time.time(), 'result': False, 'details': details}
                    self.log_execution(f"Step {self.current_step_index + 1}: {details}", "red")
            else:
                details = f"Unknown setting '{setting_name}' to inject."
                step['_last_run_info'] = {'timestamp': time.time(), 'result': False, 'details': details}
                self.log_execution(f"Step {self.current_step_index + 1}: {details}", "red")

            return False, False

        elif logical_type == 'Movement Detect':
            area = step.get('area') or (self.area_x1.get(), self.area_y1.get(), self.area_x2.get(), self.area_y2.get())
            w, h = area[2] - area[0], area[3] - area[1]
            if w < 1 or h < 1:
                self.log_execution(f"Step {self.current_step_index + 1}: Invalid area for Movement Detect. Failing.", "red")
                self.handle_timeout()
                return False, True

            current_frame_cv = self.grab_frame(area, gray=True)
            
            previous_frame = step.get('_previous_frame_for_movement')

            if previous_frame is None:
                step['_previous_frame_for_movement'] = current_frame_cv
                self.last_detection_info.set("Movement: 1st frame captured. Waiting for 2nd...")
                self.log_execution(f"Step {self.current_step_index + 1}: Captured first frame for movement comparison.")
                step['_last_run_info'] = {'timestamp': time.time(), 'result': 'Waiting', 'details': 'First frame captured.'}
                self.executor_after_id = self.root.after(int(self.scan_interval.get() * 1000), self.run_step_executor)
                return False, True
            else:
                if previous_frame.shape != current_frame_cv.shape:
                    self.log_execution(f"Step {self.current_step_index + 1}: Frame dimension mismatch. Resetting comparison.", "orange")
                    step['_previous_frame_for_movement'] = current_frame_cv
                    self.executor_after_id = self.root.after(int(self.scan_interval.get() * 1000), self.run_step_executor)
                    return False, True

                diff = cv2.absdiff(previous_frame, current_frame_cv)
                _, thresholded_diff = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
                
                non_zero_count = np.count_nonzero(thresholded_diff)
                total_pixels = thresholded_diff.size
                change_percentage = (non_zero_count / total_pixels) * 100 if total_pixels > 0 else 0
                
                tolerance = step.get('movement_tolerance', 5.0)
                
                self.last_detection_info.set(f"Movement: {change_percentage:.2f}% changed (Tolerance: {tolerance}%)")
                
                step['_previous_frame_for_movement'] = None

                if change_percentage <= tolerance:
                    self.log_execution(f"Step {self.current_step_index + 1}: Stillness detected between cycles ({change_percentage:.2f}% <= {tolerance}%). Success.")
                    step['_last_run_info'] = {'timestamp': time.time(), 'result': True, 'details': f"Stillness detected. Change: {change_percentage:.2f}%."}
                    return True, False
                else:
                    self.log_execution(f"Step {self.current_step_index + 1}: Movement detected between cycles ({change_percentage:.2f}%). Continuing.")
                    step['_last_run_info'] = {'timestamp': time.time(), 'result': 'Waiting', 'details': f"Movement ongoing. Change: {change_percentage:.2f}%."}
                    self.executor_after_id = self.root.after(int(self.scan_interval.get() * 1000), self.run_step_executor)
                    return False, True
        
        elif logical_type == 'Number':
            area = step.get('area') or (self.area_x1.get(), self.area_y1.get(), self.area_x2.get(), self.area_y2.get())
            expression_str = step.get('expression', '> 0')
            w, h = area[2] - area[0], area[3] - area[1]
            if w < 1 or h < 1:
                return False, False 
            
            self.log_execution(f"Step {self.current_step_index + 1}: Performing OCR in area {area} with expression '{expression_str}'.")
            try:
                screen_cv = self.grab_frame(area)

                image_mode = step.get('image_mode', 'Grayscale')
                gray = cv2.cvtColor(screen_cv, cv2.COLOR_BGR2GRAY)

                if image_mode == 'Binary (B&W)':
                    inverted = cv2.bitwise_not(gray)
                    _, processed_for_ocr = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                elif image_mode == 'Grayscale':
                    processed_for_ocr = cv2.bitwise_not(gray)
                else: 
                    processed_for_ocr = cv2.cvtColor(screen_cv, cv2.COLOR_BGR2RGB)

                psm_mode = self.psm_options.get(step.get('psm_mode'), '6')
                oem_mode = self.oem_options.get(step.get('oem_mode'), '3')
                ocr_config = f'--oem {oem_mode} --psm {psm_mode} -c tessedit_char_whitelist=0123456789:;,.-'
                ocr_text = pytesseract.image_to_string(Image.fromarray(processed_for_ocr), config=ocr_config)
                cleaned_text = "".join(filter(lambda x: x in '0123456789.-', ocr_text))

                self.log_execution(f" > OCR Raw Text: '{ocr_text.strip()}'. Cleaned Number: '{cleaned_text}'.")
                
                if not cleaned_text:
                    self.last_detection_info.set("OCR: No number detected in area.")
                    self.log_execution(" > OCR FAILED: No valid number characters found in area.", "orange")
                    return False, False 

                num = float(cleaned_text)
                expression = expression_str.split()
                if len(expression) != 2: raise ValueError("Invalid expression format")
                
                op, val = expression[0], float(expression[1])
                op_map = {'>': num > val, '<': num < val, '>=': num >= val, '<=': num <= val, '==': num == val, '!=': num != val}
                result = op_map.get(op, False)

                self.last_detection_info.set(f"OCR: '{num}'. Condition met: {result}")
                step['_last_run_info'] = {'timestamp': time.time(), 'result': result, 'details': f"OCR found '{num}'. Condition success: {result}."}
                
                if result:
                    self.log_execution(f" > Evaluation: '{num} {op} {val}' is TRUE. SUCCEEDED.", "green")
                else:
                    self.log_execution(f" > Evaluation: '{num} {op} {val}' is FALSE. FAILED.", "orange")

                return result, False

            except Exception as e:
                self.last_detection_info.set(f"OCR Error: Retrying...")
                self.log_execution(f" > OCR ERROR: {e}", "red")
                print(f"Error during OCR in step {self.current_step_index + 1}: {e}")
                return False, False

        return False, False

    def handle_timeout(self):
        step = self.steps[self.current_step_index]
        
        is_count_fail = (step.get('type') == 'png' and step.get('action') == 'PNG Count') or \
                        (step.get('type') == 'color' and step.get('action') == 'Color Count')
        is_number_fail = step.get('logical_type') == 'Number'
        
        if is_count_fail or is_number_fail:
            log_msg = f"Step {self.current_step_index+1} failed."
        else:
            log_msg = f"Step {self.current_step_index+1} timed out."

        self.log_execution(log_msg, "orange")
        
        step['_last_run_info']['result'] = 'Timeout'
        step['_last_run_info']['details'] = f"Step failed or timed out after {step.get('timeout', 0)}s."

        action = step['on_timeout_action']
        if action == 'Stop': self.stop(f"Status: Stopped on timeout at Step {self.current_step_index + 1}", color_state='orange'); return
        
        next_index = self.current_step_index + 1 if action == 'Next Step' else step['on_timeout_goto_step'] - 1
        self.current_step_index = next_index
        
        # Schedule advance_step to break any potential recursion loops.
        self.executor_after_id = self.root.after(1, self.advance_step)

    def handle_flow_control(self, action_key, goto_key):
        step = self.steps[self.current_step_index]; action = step.get(action_key, 'Stop')
        if action == 'Stop': self.stop(f"Status: Stopped by flow control at Step {self.current_step_index + 1}", color_state='orange'); return
        next_index = self.current_step_index + 1 if action == 'Next Step' else step.get(goto_key, 1) - 1
        self.current_step_index = next_index
        delay_key = 'delay_after'
        if action_key == 'on_count_reached_action': delay_key = 'on_count_reached_delay'
        self.start_delay_countdown(step.get(delay_key, 0))

    def start_delay_countdown(self, delay_seconds, next_action_func=None):
        if self.delay_countdown_id: self.root.after_cancel(self.delay_countdown_id)
        if next_action_func is None: next_action_func = self.advance_step
        if delay_seconds > 0: end_time = time.time() + delay_seconds; self.update_delay_countdown(end_time, next_action_func)
        else: next_action_func()

    def enter_f3_mode(self, action):
        if self.running: return
        index = self.selected_items[0]['index'] if (self.selected_items and len(self.selected_items) == 1 and self.selected_items[0]['type'] == 'step') else None
        context = 'test' if action in ['pick_test_color'] else 'step'
        if context == 'step' and index is None: return
        if self.f3_mode is not None: self.cancel_f3_mode()

        self.f3_mode = {'action': action, 'index': index, 'context': context, 'last_outside': None}
        if self.hide_on_select.get(): self.root.withdraw()

        # The global F3 hotkey needs root on Linux and cannot be registered, so
        # the picker owns its own focused overlay. That overlay receives F3 (and
        # Escape) directly, and shows buttons for a mouse-only capture, so the
        # app can never end up hidden with no way back.
        self._build_picker_overlay(action)
        self.status_label_color_state = 'orange'
        self.status_label.config(text=f"{self._picker_action_text(action)}: Move mouse and press F3", foreground=self.current_theme['status_orange'])
        self.log("Picker mode: move the mouse to the target, then press F3. Escape cancels.", "orange")

    def _picker_action_text(self, action):
        return {'pick_color': "PICKING COLOR", 'pick_location': "GETTING LOCATION", 'pick_test_color': "PICKING TEST COLOR"}.get(action, "CAPTURING")

    def _build_picker_overlay(self, action):
        self._destroy_picker_overlay()
        theme = self.current_theme
        overlay = tk.Toplevel(self.root)
        # Deliberately NOT overrideredirect(True): Hyprland will not deliver
        # keyboard input to an override-redirect window, so F3 and Escape never
        # arrive even though Tk reports the window as focused. A normal managed
        # toplevel receives them.
        overlay.title("Picker")
        # Best effort only: Hyprland/XWayland accepts these and then ignores them
        # (they read straight back as 0/1.0). They do take effect on Windows/X11.
        # The window is still placed and stacked by the compositor, and being a
        # managed toplevel is what matters for receiving F3.
        overlay.attributes("-topmost", True, "-alpha", 0.95)
        overlay.resizable(False, False)

        frame = tk.Frame(overlay, bg=theme['bg'], highlightbackground=theme['status_orange'], highlightthickness=2)
        frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(frame, text=self._picker_action_text(action), bg=theme['bg'], fg=theme['status_orange'], font=('Helvetica', 10, 'bold')).pack(padx=14, pady=(8, 0))
        self.picker_pos_label = tk.Label(frame, text="reading cursor...", bg=theme['bg'], fg=theme['fg'], font=('Consolas', 11))
        self.picker_pos_label.pack(padx=14)
        tk.Label(frame, text="Move the mouse, then press F3.   Esc cancels.", bg=theme['bg'], fg=theme['node_text_grey'], font=('Helvetica', 9)).pack(padx=14)

        buttons = tk.Frame(frame, bg=theme['bg']); buttons.pack(padx=14, pady=8)
        tk.Button(buttons, text="Capture (F3)", font=('Helvetica', 9), relief=tk.FLAT, bg=theme['accent_green'], fg=theme['btn_fg'], command=self.capture_from_hotkey).pack(side=tk.LEFT, padx=4)
        tk.Button(buttons, text="Cancel (Esc)", font=('Helvetica', 9), relief=tk.FLAT, bg=theme['accent_red'], fg=theme['btn_fg'], command=self.cancel_f3_mode).pack(side=tk.LEFT, padx=4)

        overlay.update_idletasks()
        width = overlay.winfo_reqwidth()
        screen_w = self.root.winfo_screenwidth()
        target = f"+{max(0, (screen_w - width) // 2)}+40"
        overlay.geometry(target)
        # Best effort: on compositors that honour it, re-asserting once the
        # window is mapped actually moves it.
        overlay.after(60, lambda: self._place_picker(target))

        overlay.bind("<F3>", lambda e: self.capture_from_hotkey())
        overlay.bind("<Escape>", lambda e: self.cancel_f3_mode())
        self.picker_overlay = overlay
        try: overlay.focus_force()
        except tk.TclError: pass
        self._picker_tick()

    def _place_picker(self, target):
        if self.picker_overlay is None: return
        try: self.picker_overlay.geometry(target)
        except tk.TclError: pass

    def _picker_tick(self):
        """Track the cursor so the displayed position stays live and so a click
        on the overlay still captures the point the cursor came from."""
        if self.picker_overlay is None or self.f3_mode is None: return
        try:
            x, y = pyautogui.position()
            self.f3_mode['cursor'] = (x, y)
            if not self._point_in_picker(x, y): self.f3_mode['last_outside'] = (x, y)
            if self.picker_pos_label is not None: self.picker_pos_label.config(text=f"{x}, {y}")
        except Exception:
            pass
        self.picker_poll_id = self.root.after(100, self._picker_tick)

    def _point_in_picker(self, x, y):
        overlay = self.picker_overlay
        if overlay is None: return False
        try:
            ox, oy = overlay.winfo_rootx(), overlay.winfo_rooty()
            return ox <= x <= ox + overlay.winfo_width() and oy <= y <= oy + overlay.winfo_height()
        except tk.TclError:
            return False

    def _destroy_picker_overlay(self):
        if getattr(self, 'picker_poll_id', None) is not None:
            try: self.root.after_cancel(self.picker_poll_id)
            except Exception: pass
            self.picker_poll_id = None
        if getattr(self, 'picker_overlay', None) is not None:
            try: self.picker_overlay.destroy()
            except tk.TclError: pass
            self.picker_overlay = None
        self.picker_pos_label = None

    def _finish_picker(self):
        self._destroy_picker_overlay()
        if self.hide_on_select.get():
            self.root.config(bg=self.current_theme['bg'])
            self.root.deiconify()
        self.f3_mode = None
        self.status_label_color_state = 'blue'
        self.status_label.config(text="Status: Stopped", foreground=self.current_theme.get('status_blue', 'blue'))

    def cancel_f3_mode(self):
        if self.f3_mode is None and getattr(self, 'picker_overlay', None) is None: return
        self._finish_picker()
        self.log("Capture cancelled.")

    def capture_from_hotkey(self):
        if self.f3_mode is None: return
        mode = self.f3_mode
        try:
            x, y = pyautogui.position()
            # Clicking the overlay's button moves the cursor onto the overlay, so
            # fall back to the last point seen outside it.
            if self._point_in_picker(x, y) and mode.get('last_outside'):
                x, y = mode['last_outside']
        except Exception:
            x, y = mode.get('last_outside') or (0, 0)

        wants_pixel = mode['action'] in ('pick_color', 'pick_test_color')
        self._destroy_picker_overlay()
        try:
            if wants_pixel:
                # Let the compositor repaint where the overlay was, or the pick
                # would sample the overlay's own pixels.
                time.sleep(0.15)
            context, index, action = mode['context'], mode['index'], mode['action']
            if context == 'step':
                step = self.steps[index]
                if action == 'pick_color':
                    step['rgb'] = pyautogui.pixel(x, y)
                    if step.get('pixel_detect_enabled'):
                        step['pixel_coords'] = (x, y)
                    self.log(f"Captured color {step['rgb']} for Step {index + 1}.")
                elif action == 'pick_location':
                    step['coords'] = (x, y); self.log(f"Captured location {(x,y)} for Step {index + 1}.")
                self.populate_properties_panel()
            elif context == 'test':
                if action == 'pick_test_color':
                    self.test_color_rgb = pyautogui.pixel(x, y)
                    hex_color = self.rgb_to_hex(self.test_color_rgb)
                    self.test_color_swatch.config(bg=hex_color)
                    if hasattr(self, 'test_color_swatch_count'):
                        self.test_color_swatch_count.config(bg=hex_color)
                    self.log(f"Captured color {self.test_color_rgb} for testing.")
        except Exception as e: messagebox.showerror("Error", f"Could not capture: {e}")
        finally:
            self._finish_picker()

    def select_area_for_step(self): 
        if self.selected_items and len(self.selected_items) == 1 and self.selected_items[0]['type'] == 'step': 
            self.select_area_mode(step_index=self.selected_items[0]['index'])
    
    def select_area_for_test(self): self.select_area_mode(is_test=True)

    def set_global_area_to_fullscreen(self):
        screen_w, screen_h = pyautogui.size()
        self.global_settings_ui_vars['area_x1'].set(0); self.global_settings_ui_vars['area_y1'].set(0)
        self.global_settings_ui_vars['area_x2'].set(screen_w); self.global_settings_ui_vars['area_y2'].set(screen_h)
        self.apply_global_settings(); self.log("Set global area to full screen.")

    def set_step_area_to_fullscreen(self):
        if not (self.selected_items and len(self.selected_items) == 1 and self.selected_items[0]['type'] == 'step'): return
        screen_w, screen_h = pyautogui.size(); index = self.selected_items[0]['index']; self.steps[index]['area'] = (0, 0, screen_w, screen_h); self.log(f"Set area for Step {index + 1} to full screen."); self.populate_properties_panel()
        self.update_all_area_overlays()

    def set_step_area_to_global(self):
        """Sets the selected step's area to None, causing it to use the global area."""
        if not (self.selected_items and len(self.selected_items) == 1 and self.selected_items[0]['type'] == 'step'):
            return
        index = self.selected_items[0]['index']
        self.steps[index]['area'] = None
        self.log(f"Set Step {index + 1} to use the Global Area setting.")
        self.populate_properties_panel()  # Refresh UI to show "Area: Global"
        self.update_all_area_overlays() # Update visual overlays

    def browse_for_step(self):
        if not (self.selected_items and len(self.selected_items) == 1 and self.selected_items[0]['type'] == 'step'): return
        index = self.selected_items[0]['index']; step = self.steps[index]
        mode = self.properties_widgets['png_mode'].get()
        path = filedialog.askopenfilename(filetypes=[("PNG Files", "*.png")]) if mode == 'file' else filedialog.askdirectory()
        
        if path:
            old_path = step.get('path', '')
            if old_path != path:
                image_mode = step.get('image_mode', 'Grayscale')
                old_single_key = f"{old_path}|{image_mode}"
                if old_single_key in self.template_cache:
                    del self.template_cache[old_single_key]
                old_folder_key = f"{old_path}|{image_mode}"
                if old_folder_key in self.folder_image_cache:
                    del self.folder_image_cache[old_folder_key]

            step['path'] = path
            self.properties_widgets['path'].config(text=os.path.basename(path), fg=self.current_theme['fg'])
            self._update_png_preview(step)
            self.log(f"Set path for Step {index + 1} to '{os.path.basename(path)}'.")

    def snip_image_for_step(self, event=None):
        if self.running or not (self.selected_items and len(self.selected_items) == 1 and self.selected_items[0]['type'] == 'step'): return
        index = self.selected_items[0]['index']
        window_state, current_geometry = self.root.state(), self.root.geometry()
        
        if self.hide_on_select.get():
            self.root.withdraw()
            self.root.update_idletasks()
            time.sleep(0.5) # Wait for OS to redraw behind the withdrawn window
            
        overlay = tk.Toplevel(self.root); overlay.attributes("-alpha", 0.3, "-topmost", True); overlay.overrideredirect(True); w, h = self.root.winfo_screenwidth(), self.root.winfo_screenheight(); overlay.geometry(f"{w}x{h}+0+0"); canvas = tk.Canvas(overlay, cursor="cross", bg="grey10"); canvas.pack(fill=tk.BOTH, expand=True); rect_id, start_x, start_y = None, 0, 0
        
        def on_press(e): nonlocal start_x, start_y, rect_id; start_x, start_y = e.x_root, e.y_root; rect_id = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#3399ff", width=2, dash=(4,2))
        def on_drag(e):
            if rect_id: canvas.coords(rect_id, start_x, start_y, e.x_root, e.y_root)
        
        def on_release(e):
            x1, y1, x2, y2 = min(start_x, e.x_root), min(start_y, e.y_root), max(start_x, e.x_root), max(start_y, e.y_root)
            overlay.destroy()

            # Abort if area is too small, but make sure to restore window first
            if (x2 - x1) < 10 or (y2 - y1) < 10:
                if self.hide_on_select.get():
                    self.root.deiconify()
                    self.root.state('zoomed') if window_state == 'zoomed' else self.root.geometry(current_geometry)
                self.root.focus_force()
                self.log("Snipping cancelled: area was too small.", "orange")
                return

            # Capture the screen region while the main window is still hidden
            captured_image = None
            try:
                time.sleep(0.1) # Brief pause for overlay to vanish
                captured_image = pyautogui.screenshot(region=(x1, y1, x2 - x1, y2 - y1))
            except Exception as ex:
                self.log(f"Error capturing screen snippet: {ex}", "red")
            
            # Now that the capture is done, restore the main window
            if self.hide_on_select.get():
                self.root.deiconify()
                self.root.state('zoomed') if window_state == 'zoomed' else self.root.geometry(current_geometry)
            self.root.focus_force()

            # If capture was successful, ask the user where to save it
            if captured_image:
                filepath = filedialog.asksaveasfilename(title="Save Snippet As", defaultextension=".png", filetypes=[("PNG Files", "*.png")], initialfile=f"snippet_step_{index+1}.png")
                if filepath:
                    try:
                        captured_image.save(filepath)
                        self.steps[index]['path'] = filepath
                        self.populate_properties_panel()
                        self._update_png_preview(self.steps[index])
                        self.log(f"Saved snippet and set path for Step {index+1}.")
                    except Exception as ex:
                        messagebox.showerror("Save Error", f"Failed to save snippet: {ex}")
                        self.log(f"Error saving snippet: {ex}", "red")

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)

    def browse_for_test_path(self):
        mode = self.test_png_mode.get(); path = filedialog.askopenfilename(filetypes=[("PNG Files", "*.png")]) if mode == 'file' else filedialog.askdirectory()
        if path: self.test_png_path.set(path); self.test_png_path_display.set(os.path.basename(path))

    def snip_image_for_test(self):
        if self.running: return
        window_state, current_geometry = self.root.state(), self.root.geometry()

        if self.hide_on_select.get():
            self.root.withdraw()
            self.root.update_idletasks()
            time.sleep(0.5) # Wait for OS to redraw behind the withdrawn window

        overlay = tk.Toplevel(self.root); overlay.attributes("-alpha", 0.3, "-topmost", True); overlay.overrideredirect(True); w, h = self.root.winfo_screenwidth(), self.root.winfo_screenheight(); overlay.geometry(f"{w}x{h}+0+0"); canvas = tk.Canvas(overlay, cursor="cross", bg="grey10"); canvas.pack(fill=tk.BOTH, expand=True); rect_id, start_x, start_y = None, 0, 0
        
        def on_press(e): nonlocal start_x, start_y, rect_id; start_x, start_y = e.x_root, e.y_root; rect_id = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#3399ff", width=2, dash=(4,2))
        def on_drag(e):
            if rect_id: canvas.coords(rect_id, start_x, start_y, e.x_root, e.y_root)

        def on_release(e):
            x1, y1, x2, y2 = min(start_x, e.x_root), min(start_y, e.y_root), max(start_x, e.x_root), max(start_y, e.y_root)
            overlay.destroy()

            # Abort if area is too small, but make sure to restore window first
            if (x2 - x1) < 10 or (y2 - y1) < 10:
                if self.hide_on_select.get():
                    self.root.deiconify()
                    self.root.state('zoomed') if window_state == 'zoomed' else self.root.geometry(current_geometry)
                self.root.focus_force()
                self.log("Snipping cancelled: area was too small.", "orange")
                return

            # Capture the screen region while the main window is still hidden
            captured_image = None
            try:
                time.sleep(0.1) # Brief pause for overlay to vanish
                captured_image = pyautogui.screenshot(region=(x1, y1, x2 - x1, y2 - y1))
            except Exception as ex:
                self.log(f"Error capturing screen snippet: {ex}", "red")

            # Now that the capture is done, restore the main window
            if self.hide_on_select.get():
                self.root.deiconify()
                self.root.state('zoomed') if window_state == 'zoomed' else self.root.geometry(current_geometry)
            self.root.focus_force()
            
            # If capture was successful, ask the user where to save it
            if captured_image:
                filepath = filedialog.asksaveasfilename(title="Save Test Snippet As", defaultextension=".png", filetypes=[("PNG Files", "*.png")], initialfile="test_snippet.png")
                if filepath:
                    try:
                        captured_image.save(filepath)
                        self.test_png_path.set(filepath)
                        self.test_png_path_display.set(os.path.basename(filepath))
                        self.log(f"Saved snippet and set path for PNG test.")
                    except Exception as ex:
                        messagebox.showerror("Save Error", f"Failed to save snippet: {ex}")
                        self.log(f"Error saving snippet: {ex}", "red")
        
        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)

    def export_to_json(self):
        filepath = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON Files", "*.json")], title="Export Flowchart")
        if not filepath: return
        steps_to_save = copy.deepcopy(self.steps)
        for s in steps_to_save:
            s.pop('_width', None)
            s.pop('_height', None)
            s.pop('_last_run_info', None)
            s.pop('_previous_frame_for_movement', None)
        settings = {
            "global_settings": {
                "mouse_move_mode": self.mouse_move_mode.get(),
                "mouse_speed": self.mouse_speed.get(),
                "pixels_per_second": self.pixels_per_second.get(),
                "min_move_time": self.min_move_time.get(),
                "max_move_time": self.max_move_time.get(),
                "scan_interval": self.scan_interval.get(), 
                "hold_duration": self.hold_duration.get(), 
                "loc_offset_variance": self.loc_offset_variance.get(), 
                "speed_variance": self.speed_variance.get(), 
                "hold_duration_variance": self.hold_duration_variance.get(), 
                "area_x1": self.area_x1.get(), "area_y1": self.area_y1.get(), "area_x2": self.area_x2.get(), 
                "area_y2": self.area_y2.get(), "hide_on_select": self.hide_on_select.get(),
                "start_at_stopped_pos": self.start_at_stopped_pos.get(),
                # --- Grid Settings ---
                "grid_visible": self.grid_visible.get(),
                "grid_latching": self.grid_latching.get(),
                "grid_spacing": self.grid_spacing.get(),
                "grid_opacity": self.grid_opacity.get()
            }, 
            "steps": steps_to_save, 
            "annotations": self.annotations 
        }
        
        ge_step_exists = any(s.get('logical_type') == 'GE Inject' or s.get('text_source') == 'GE Interface' for s in steps_to_save)
        if ge_step_exists:
            settings["ge_interface_settings"] = {
                'item_name': self.ge_interface_item_name.get(),
                'quantity': self.ge_interface_item_quantity.get(),
                'buy_price_strategy': self.ge_interface_buy_price_strategy.get(),
                'sell_price_strategy': self.ge_interface_sell_price_strategy.get(),
                'buy_custom_price': self.ge_interface_buy_custom_price.get(),
                'sell_custom_price': self.ge_interface_sell_custom_price.get(),
                'buy_price_margin': self.ge_interface_buy_price_margin.get(),
                'sell_price_margin': self.ge_interface_sell_price_margin.get()
            }
            self.log("GE Interface settings included in export.")
            
        try:
            with open(filepath,'w') as f: json.dump(settings,f,indent=4)
            self.log(f"Successfully exported flowchart to {os.path.basename(filepath)}.")
        except Exception as e: messagebox.showerror("Export Error",f"Failed to save file: {e}")

    def import_from_json(self):
        self.destroy_all_overlays()
        filepath = filedialog.askopenfilename(filetypes=[("JSON Files","*.json")], title="Import and Append Flowchart");
        if not filepath: return
        try:
            with open(filepath, 'r') as f: loaded_data = json.load(f)
            if "global_settings" in loaded_data:
                gs = loaded_data["global_settings"]
                
                # Handle backward compatibility for mouse mode
                if "mouse_move_mode" in gs:
                    self.mouse_move_mode.set(gs.get("mouse_move_mode", "Regular"))
                elif gs.get("enable_dynamic_speed", False):
                    self.mouse_move_mode.set("Dynamic")
                else:
                    self.mouse_move_mode.set("Regular")

                self.mouse_speed.set(gs.get("mouse_speed", 0.25))
                self.pixels_per_second.set(gs.get("pixels_per_second", 1000))
                self.min_move_time.set(gs.get("min_move_time", 0.05))
                self.max_move_time.set(gs.get("max_move_time", 0.3))
                self.scan_interval.set(gs.get("scan_interval", 0.25))
                self.hold_duration.set(gs.get("hold_duration", 0.08))
                self.loc_offset_variance.set(gs.get("loc_offset_variance", 4))
                self.speed_variance.set(gs.get("speed_variance", 0.06))
                self.hold_duration_variance.set(gs.get("hold_duration_variance", 0.03))
                self.area_x1.set(gs.get("area_x1", 0)); self.area_y1.set(gs.get("area_y1", 0))
                screen_w, screen_h = pyautogui.size()
                self.area_x2.set(gs.get("area_x2", screen_w)); self.area_y2.set(gs.get("area_y2", screen_h)); self.hide_on_select.set(gs.get("hide_on_select", True))
                self.start_at_stopped_pos.set(gs.get("start_at_stopped_pos", False))
                # --- Grid Settings ---
                self.grid_visible.set(gs.get("grid_visible", False))
                self.grid_latching.set(gs.get("grid_latching", False))
                self.grid_spacing.set(gs.get("grid_spacing", 30))
                self.grid_opacity.set(gs.get("grid_opacity", 0.3))
                self._sync_global_settings_ui_from_model(); self.apply_theme(); self.log("Loaded global settings from file.")

            if "ge_interface_settings" in loaded_data:
                gis = loaded_data["ge_interface_settings"]
                self.ge_interface_item_name.set(gis.get('item_name', ''))
                self.ge_interface_item_quantity.set(gis.get('quantity', '1'))
                self.ge_interface_buy_price_strategy.set(gis.get('buy_price_strategy', 'Flip-Buy (use Insta-Sell)'))
                self.ge_interface_sell_price_strategy.set(gis.get('sell_price_strategy', 'Flip-Sell (use Insta-Buy)'))
                self.ge_interface_buy_custom_price.set(gis.get('buy_custom_price', '0'))
                self.ge_interface_sell_custom_price.set(gis.get('sell_custom_price', '0'))
                self.ge_interface_buy_price_margin.set(gis.get('buy_price_margin', '1'))
                self.ge_interface_sell_price_margin.set(gis.get('sell_price_margin', '1'))
                self.log("Loaded GE Interface settings from file.")
                # --- FIX: Manually trigger UI update for margin widgets ---
                self._toggle_ge_buy_options()
                self._toggle_ge_sell_options()

            steps, notes = loaded_data.get("steps", []), loaded_data.get("annotations", [])
            
            cleaned_steps = []
            for s in steps:
                if s.get('type') == 'ge':
                    self.log(f"Note: Old 'GE Step' ({s.get('name')}) was ignored during import.", "orange")
                    continue
                if s.get('type') == 'number': s['type'] = 'logical'; s['logical_type'] = 'Number'
                if s.get('type') == 'location' and s.get('action') == 'Click Object': s['action'] = 'Left Click'
                if s.get('logical_type') == 'Timer': s['logical_type'] = 'Wait'
                if s.get('logical_type') == 'Number':
                    if s.get('psm_mode') and s['psm_mode'].isdigit(): s['psm_mode'] = next((k for k, v in self.psm_options.items() if v == s['psm_mode']), "6: Assume a single uniform block of text.")
                    if s.get('oem_mode') and s['oem_mode'].isdigit(): s['oem_mode'] = next((k for k, v in self.oem_options.items() if v == s['oem_mode']), "3: Default, based on what is available.")
                s['_last_run_info'] = {'timestamp': None, 'result': None, 'details': 'Imported, not yet run'}
                cleaned_steps.append(s)

            if not cleaned_steps and not notes: self.log("Imported file contains no compatible steps or notes.", "orange"); return
            count = len(self.steps)
            y_offset = 0
            if self.steps:
                for i in range(len(self.steps)): self._calculate_node_size(i)
                max_y = max((s.get('y', 0) + s.get('_height', 60) / self.zoom_factor for s in self.steps), default=0)
                y_offset = max_y + 60
            for s in cleaned_steps:
                for key in ['on_success_goto_step', 'on_timeout_goto_step', 'on_count_reached_goto_step']:
                    if s.get(key): s[key] += count
                if s.get('on_success_action') == 'Next Step' and 'on_success_goto_step' in s: s['on_success_goto_step'] += count
                s['y'] = s.get('y', 50) + y_offset
            for n in notes: n['y'] = n.get('y', 50) + y_offset
            self.steps.extend(cleaned_steps); self.annotations.extend(notes); self.redraw_flowchart(); self.log(f"Appended {len(cleaned_steps)} steps and {len(notes)} notes from {os.path.basename(filepath)}.")
        except Exception as e: messagebox.showerror("Import Error", f"Failed to load or process file: {e}"); self.log(f"Import failed: {e}", "red")

    def reset_all(self):
        if messagebox.askyesno("Confirm Reset", "Are you sure you want to delete all steps and notes? This cannot be undone."): 
            self.destroy_all_overlays()
            self.steps.clear(); self.annotations.clear(); self.template_cache.clear()
            self.folder_image_cache.clear()
            self.selected_items = []; self.populate_properties_panel(); self.redraw_flowchart()
            self.log("Flowchart has been reset.", "orange")

    def log(self, message, color_name=None):
        theme = self.current_theme
        # Logging must never be able to crash the app: the theme is empty
        # until apply_theme() runs, and a missing colour key should degrade to
        # the default rather than raise.
        if color_name in ["green", "orange", "red"]:
            self.status_label_color_state = color_name
            self.status_label.config(foreground=theme.get(f'status_{color_name}', theme.get('status_blue', '#61AFEF')))
        log_entry = f"[{time.strftime('%H:%M:%S')}] {message}"; self.full_log_history.append(log_entry); self.filter_log()

    def log_execution(self, message, color_name=None):
        """Logs a message during script execution, respecting the step's log setting."""
        if not self.running or not (0 <= self.current_step_index < len(self.steps)):
            self.log(message, color_name)
            return

        step = self.steps[self.current_step_index]
        if step.get('enable_logging', True):
            self.log(message, color_name)

    def filter_log(self, *args):
        query = self.log_search_query.get().lower(); self.log_text.config(state='normal'); self.log_text.delete('1.0', tk.END)
        filtered_log = [line for line in self.full_log_history if query in line.lower()] if query else self.full_log_history
        for line in filtered_log: self.log_text.insert(tk.END, line + "\n")
        max_lines = self.log_auto_clear_lines.get()
        if max_lines > 0 and not query:
            num_lines = int(self.log_text.index('end-1c').split('.')[0])
            if num_lines > max_lines:
                self.log_text.delete('1.0', f'{num_lines - max_lines + 1}.0')
                self.full_log_history = self.full_log_history[-(max_lines):]
        self.log_text.config(state='disabled'); self.log_text.yview(tk.END)

    def clear_log(self):
        self.full_log_history.clear(); self.log_search_query.set(""); self.log("Log cleared.")

    def get_node_center(self, index):
        step, z = self.steps[index], self.zoom_factor
        return (step.get('x', 50) + step.get('_width', 180*z)/z/2, step.get('y', 50) + step.get('_height', 60*z)/z/2)

    def _on_global_key(self, name):
        """Handle a hotkey from the global listener (already on the UI thread)."""
        if name == 'f2': self.stop() if self.running else self.start()
        elif name == 'f3':
            if self.f3_mode is not None: self.capture_from_hotkey()
        elif name == 'f4': self.select_area_mode()
        elif name == 'escape':
            # Only meaningful while the picker or an area overlay is open; never
            # swallow Escape for other applications (this is a passive listener).
            if self.f3_mode is not None: self.cancel_f3_mode()

    def _start_evdev_hotkeys(self):
        """Register global hotkeys by reading /dev/input directly.

        The keyboard library registers global hotkeys the same way but refuses to
        run unless euid is 0. Reading /dev/input/event* only needs membership of
        the ``input`` group, so this gives Linux users global F2/F3/F4 without
        root and without the app having to run as root.
        """
        from flowchart_automation.wayland.hotkeys import EvdevHotkeyListener, keyboards_available

        if not keyboards_available(): return None
        listener = EvdevHotkeyListener(lambda name: self._dispatch_global_key(name))
        if not listener.start(): return None
        return listener

    def _dispatch_global_key(self, name):
        """Hop from the listener thread onto the Tk main loop."""
        try: self.root.after(0, lambda: self._on_global_key(name))
        except (tk.TclError, RuntimeError): pass

    def setup_hotkeys(self):
        self.hotkey_listener = None
        try:
            keyboard.add_hotkey('f2',lambda: self.start() if not self.running else self.stop()); keyboard.add_hotkey('f3',self.capture_from_hotkey); keyboard.add_hotkey('f4',self.select_area_mode)
            self.global_hotkeys = True
        except Exception as e:
            # The keyboard library needs root on Linux. Fall back to reading
            # /dev/input directly, which needs only the `input` group.
            self.global_hotkeys = False
            try: self.hotkey_listener = self._start_evdev_hotkeys()
            except Exception: self.hotkey_listener = None
            if self.hotkey_listener is not None:
                self.global_hotkeys = True
                self.log(f"Global hotkeys active via {', '.join(self.hotkey_listener.devices)}.")
            else:
                self.log(f"Global hotkeys unavailable ({e}). Add yourself to the 'input' group for F2/F3/F4, or use the on-screen buttons.", "orange")
        # In-window bindings work on every platform, and cover the case where the
        # global listener is unavailable.
        self.root.bind("<F2>", lambda e: self.stop() if self.running else self.start())
        self.root.bind("<F3>", lambda e: self.capture_from_hotkey())
        self.root.bind("<Escape>", lambda e: self.cancel_f3_mode())
        self.root.bind("<Control-c>", self.copy_selection)
        self.root.bind("<Control-v>", self.paste_selection)
        self.root.bind("<Delete>", self.delete_selected_from_key)

    def _bind_mouse_scroll(self):
        def _on_mouse_wheel(event):
            is_ctrl, is_shift = (event.state & 0x0004) != 0, (event.state & 0x0001) != 0; scroll_dir = -1 if (event.num == 4 or event.delta > 0) else 1
            if is_ctrl: self.zoom_factor *= 1.1 if scroll_dir == -1 else 0.9; self.zoom_factor = max(0.2, min(3.0, self.zoom_factor)); self.redraw_flowchart()
            elif is_shift: self.canvas.xview_scroll(scroll_dir, "units")
            else: self.canvas.yview_scroll(scroll_dir, "units")
        self.canvas.bind("<MouseWheel>", _on_mouse_wheel); self.canvas.bind("<Button-4>", _on_mouse_wheel); self.canvas.bind("<Button-5>", _on_mouse_wheel)

    def select_area_mode(self, step_index=None, is_test=False):
        if self.running: return
        window_state, current_geometry = self.root.state(), self.root.geometry()
        if self.hide_on_select.get():
            self.root.withdraw()
            self.root.update_idletasks()
            time.sleep(0.3)
        overlay = tk.Toplevel(self.root); overlay.attributes("-alpha", 0.25, "-topmost", True); overlay.overrideredirect(True); w, h = self.root.winfo_screenwidth(), self.root.winfo_screenheight(); overlay.geometry(f"{w}x{h}+0+0"); canvas = tk.Canvas(overlay, cursor="cross", bg="grey10"); canvas.pack(fill=tk.BOTH, expand=True); rect_id, start_x, start_y = None, 0, 0
        def on_press(e): nonlocal start_x, start_y, rect_id; start_x, start_y = e.x_root, e.y_root; rect_id = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="red", width=2)
        def on_drag(e):
            if rect_id: canvas.coords(rect_id, start_x, start_y, e.x_root, e.y_root)
        def on_release(e):
            x1, y1, x2, y2 = min(start_x, e.x_root), min(start_y, e.y_root), max(start_x, e.x_root), max(start_y, e.y_root); overlay.destroy()
            if self.hide_on_select.get():
                self.root.config(bg=self.current_theme['bg'])
                self.root.deiconify()
                self.root.state('zoomed') if window_state == 'zoomed' else self.root.geometry(current_geometry)
            if (x2-x1)>10 and (y2-y1)>10:
                area = (x1, y1, x2, y2)
                if is_test: 
                    self.test_area = area
                    area_text = f"Area: {x2-x1}x{y2-y1}"
                    for btn in self.test_area_buttons:
                        if btn.winfo_exists():
                            btn.config(text=area_text)
                    self.log("Set area for testing.")
                elif step_index is not None: 
                    self.steps[step_index]['area'] = area; self.populate_properties_panel(); self.log(f"Set area for Step {step_index+1}.")
                    self.update_all_area_overlays()
                else: 
                    self.global_settings_ui_vars['area_x1'].set(x1); self.global_settings_ui_vars['area_y1'].set(y1); self.global_settings_ui_vars['area_x2'].set(x2); self.global_settings_ui_vars['area_y2'].set(y2)
                    self.apply_global_settings(); self.log("Set global area.")
        canvas.bind("<ButtonPress-1>", on_press); canvas.bind("<B1-Motion>", on_drag); canvas.bind("<ButtonRelease-1>", on_release)

    def update_delay_countdown(self, end_time, next_action_func):
        remaining = end_time - time.time()
        if remaining > 0 and self.running: self.delay_countdown_label.config(text=f"Next step in {remaining:.1f}s..."); self.delay_countdown_id = self.root.after(100, lambda: self.update_delay_countdown(end_time, next_action_func))
        elif self.running: self.delay_countdown_label.config(text=""); next_action_func()

    def update_timeout_countdown(self, start_time, total_timeout):
        if not self.running: return
        remaining = total_timeout - (time.time() - start_time)
        if remaining > 0: self.timeout_countdown_label.config(text=f"Timeout in {remaining:.1f}s..."); self.timeout_countdown_id = self.root.after(100, lambda: self.update_timeout_countdown(start_time, total_timeout))
        else: self.timeout_countdown_label.config(text="")

    def execute_move(self, pos):
        offset = self.loc_offset_variance.get()
        rand_x, rand_y = pos[0] + random.randint(-offset, offset), pos[1] + random.randint(-offset, offset)
        
        speed = 0
        move_mode = self.mouse_move_mode.get()
        start_x, start_y = pyautogui.position()
        distance = math.hypot(rand_x - start_x, rand_y - start_y)

        if move_mode == 'Dynamic':
            screen_w, screen_h = pyautogui.size()
            max_dist = math.hypot(screen_w, screen_h)
            
            min_time = self.min_move_time.get()
            max_time = self.max_move_time.get()
            
            # Linearly interpolate the base speed based on distance
            if max_dist > 0:
                base_speed = min_time + (max_time - min_time) * (distance / max_dist)
            else:
                base_speed = min_time
            speed = max(0, base_speed + random.uniform(-self.speed_variance.get(), self.speed_variance.get()))

        elif move_mode == 'Pixels Per Second':
            pps = self.pixels_per_second.get()
            if pps > 0:
                base_speed = distance / pps
            else:
                base_speed = 0.1 # A small default to prevent instant moves
            speed = max(0, base_speed + random.uniform(-self.speed_variance.get(), self.speed_variance.get()))

        else: # Default to 'Regular' mode
            speed = max(0, self.mouse_speed.get() + random.uniform(-self.speed_variance.get(), self.speed_variance.get()))
            
        pyautogui.moveTo(rand_x, rand_y, duration=speed, tween=pyautogui.easeOutQuad)

    def execute_varied_click(self,pos):
        self.execute_move(pos)
        # Add a check to ensure the click doesn't happen if the move was interrupted
        if not self.running:
            return
        hold = max(0.01, self.hold_duration.get() + random.uniform(-self.hold_duration_variance.get(), self.hold_duration_variance.get()))
        pyautogui.click(duration=hold)

    def execute_action_on_pos(self, action, pos):
        if action == 'Click Object' or action == 'Left Click':
            self.execute_varied_click(pos)
            # Check running state before logging to avoid extraneous logs after stopping
            if self.running:
                self.log_execution(f"Step {self.current_step_index + 1}: Left Clicked near {pos} (Speed: ~{self.mouse_speed.get()}s, Hold: ~{self.hold_duration.get()}s).")
        elif action == 'Click Only':
            if not self.running: return
            hold = max(0.01, self.hold_duration.get() + random.uniform(-self.hold_duration_variance.get(), self.hold_duration_variance.get()))
            pyautogui.click(duration=hold)
            if self.running:
                self.log_execution(f"Step {self.current_step_index + 1}: Clicked at current mouse position.")
        elif action == 'Right Click':
            self.execute_move(pos)
            if not self.running: return # Stop before the click
            pyautogui.rightClick()
            if self.running:
                self.log_execution(f"Step {self.current_step_index + 1}: Right Clicked near {pos}.")
        elif action == 'Move Only':
            self.execute_move(pos)
            if self.running:
                self.log_execution(f"Step {self.current_step_index + 1}: Moved mouse near {pos} (Speed: ~{self.mouse_speed.get()}s).")
   
    def find_png(self, screen_cv, offset, step):
        image_mode = step.get('image_mode', 'Grayscale')
        if image_mode == 'Grayscale': screen_processed = cv2.cvtColor(screen_cv, cv2.COLOR_BGR2GRAY)
        elif image_mode == 'Binary (B&W)': gray = cv2.cvtColor(screen_cv, cv2.COLOR_BGR2GRAY); _, screen_processed = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        else: screen_processed = screen_cv
        
        templates_to_check = []
        if step['mode'] == 'file' and step['path']:
            templates_to_check.append(self.load_template(step['path'], image_mode))
        elif step['mode'] == 'folder' and step['path'] and os.path.isdir(step['path']):
            folder_cache_key = f"{step['path']}|{image_mode}"
            if folder_cache_key not in self.folder_image_cache:
                self.folder_image_cache[folder_cache_key] = []
                image_paths = [os.path.join(step['path'], fname) for fname in os.listdir(step['path']) if fname.lower().endswith('.png')]
                for fpath in image_paths:
                    template_data = self.load_template(fpath, image_mode)
                    if template_data[0] is not None:
                        self.folder_image_cache[folder_cache_key].append(template_data)
            templates_to_check = self.folder_image_cache.get(folder_cache_key, [])

        find_first = step.get('find_first_match', False)
        if not find_first:
            best_match_pos, max_confidence = None, -1

        for template_data in templates_to_check:
            match = self.find_template_in_region(screen_processed, offset, template_data, step['threshold'])
            if match and math.isfinite(match[2]):
                if find_first:
                    return match[0:2], match[2]
                
                if match[2] > max_confidence:
                    max_confidence = match[2]
                    best_match_pos = match[0:2]

        if find_first:
            return None, 0
        else:
            return best_match_pos, max_confidence if max_confidence > -1 else 0

    def find_and_count_png(self, screen_cv, offset, step):
        """
        Finds all occurrences of template(s) in the screen region and returns the count.
        Uses an optimized, built-in OpenCV method to group overlapping matches.
        """
        image_mode = step.get('image_mode', 'Grayscale')
        if image_mode == 'Grayscale':
            screen_processed = cv2.cvtColor(screen_cv, cv2.COLOR_BGR2GRAY)
        elif image_mode == 'Binary (B&W)':
            gray = cv2.cvtColor(screen_cv, cv2.COLOR_BGR2GRAY)
            _, screen_processed = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        else:
            screen_processed = screen_cv
        
        templates_to_check = []
        if step['mode'] == 'file' and step['path']:
            templates_to_check.append(self.load_template(step['path'], image_mode))
        elif step['mode'] == 'folder' and step['path'] and os.path.isdir(step['path']):
            folder_cache_key = f"{step['path']}|{image_mode}"
            if folder_cache_key not in self.folder_image_cache: # Caching logic
                self.folder_image_cache[folder_cache_key] = []
                image_paths = [os.path.join(step['path'], fname) for fname in os.listdir(step['path']) if fname.lower().endswith('.png')]
                for fpath in image_paths:
                    template_data = self.load_template(fpath, image_mode)
                    if template_data[0] is not None: self.folder_image_cache[folder_cache_key].append(template_data)
            templates_to_check = self.folder_image_cache.get(folder_cache_key, [])
        
        all_rects = []
        threshold = step['threshold']

        for template, mask in templates_to_check:
            if template is None: continue
            h, w = template.shape[:2]
            if any(s_dim < t_dim for s_dim, t_dim in zip(screen_processed.shape, template.shape)):
                continue

            locs = None
            if mask is not None:
                # Use TM_SQDIFF_NORMED for transparent PNGs for consistency with single-detect
                res = cv2.matchTemplate(screen_processed, template, cv2.TM_SQDIFF_NORMED, mask=mask)
                # For SQDIFF, a lower score is better, so we invert the threshold check
                locs = np.where(res <= (1.0 - threshold))
            else:
                # Use the standard method for opaque images
                res = cv2.matchTemplate(screen_processed, template, cv2.TM_CCOEFF_NORMED)
                locs = np.where(res >= threshold)
            
            # Create a list of all found rectangles [x, y, width, height]
            for pt in zip(*locs[::-1]):
                all_rects.append([pt[0], pt[1], w, h])

        if not all_rects:
            return 0
        
        # Use OpenCV's optimized groupRectangles function to merge overlapping boxes.
        grouped_rects, _ = cv2.groupRectangles(all_rects, groupThreshold=1, eps=0.2)

        return len(grouped_rects)

    def find_and_count_color(self, screen_cv, offset, step):
        """
        Finds all occurrences of a color in the screen region and returns the count.
        """
        rgb = step['rgb']
        tolerance = step['tolerance']
        color_space = step.get('color_space', 'HSV')
        min_area = step.get('min_pixel_area', 10)
        
        if color_space == 'RGB':
            lower = np.array([max(0, rgb[2]-tolerance), max(0, rgb[1]-tolerance), max(0, rgb[0]-tolerance)]) 
            upper = np.array([min(255, rgb[2]+tolerance), min(255, rgb[1]+tolerance), min(255, rgb[0]+tolerance)])
            mask = cv2.inRange(screen_cv, lower, upper)
        else: # HSV
            hsv = cv2.cvtColor(screen_cv, cv2.COLOR_BGR2HSV)
            target_hsv = cv2.cvtColor(np.uint8([[list(reversed(rgb))]]), cv2.COLOR_BGR2HSV)[0][0]
            h, s, v = int(target_hsv[0]), int(target_hsv[1]), int(target_hsv[2])
            h_tol, s_tol, v_tol = int(tolerance*1.8), int(tolerance*2.5), int(tolerance*2.5)
            lower = np.array([max(0,h-h_tol), max(0,s-s_tol), max(0,v-v_tol)])
            upper = np.array([min(179,h+h_tol), min(255,s+s_tol), min(255,v+v_tol)])
            mask = cv2.inRange(hsv, lower, upper)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        valid_contours = [c for c in contours if cv2.contourArea(c) > min_area]
        
        return len(valid_contours)

    def load_template(self, path, image_mode='Grayscale'):
        cache_key = f"{path}|{image_mode}"
        if cache_key not in self.template_cache:
            try:
                img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
                if img is None: raise ValueError("Image not found or unable to read.")
                
                mask = None
                if len(img.shape) == 3 and img.shape[2] == 4:
                    alpha = img[:, :, 3]
                    _, mask = cv2.threshold(alpha, 1, 255, cv2.THRESH_BINARY)
                    img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                
                processed_template = None
                if image_mode == 'Color':
                    if len(img.shape) == 2: 
                        processed_template = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                    else: 
                        processed_template = img
                else: 
                    if len(img.shape) == 3: 
                        processed_template = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    else: 
                        processed_template = img

                    if image_mode == 'Binary (B&W)':
                        _, processed_template = cv2.threshold(processed_template, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

                self.template_cache[cache_key] = (processed_template, mask)
            except Exception as e: 
                self.log(f"Error loading template {os.path.basename(path)}: {e}", "red")
                self.template_cache[cache_key] = (None, None)
        return self.template_cache[cache_key]

    def rgb_to_hex(self,rgb): return f'#{int(rgb[0]):02x}{int(rgb[1]):02x}{int(rgb[2]):02x}' if rgb else '#000000'

    def preprocess_for_ocr(self, img_cv):
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY); inverted = cv2.bitwise_not(gray)
        _, thresh = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return thresh

    def find_color_on_screen_hsv(self,img_bgr,offset,step):
        # Delegated to the refactor target so the targeting modes live in one
        # tested place instead of being duplicated here.
        return flowchart_color.find_color_hsv(
            img_bgr, offset, step.get('rgb', (255,0,0)), step.get('tolerance', 2),
            step.get('min_pixel_area', 10), step.get('blob_target', 'Largest Blob'),
            step.get('split_blob_width', 0))

    def find_color_on_screen_rgb(self, img_bgr, offset, step):
        return flowchart_color.find_color_rgb(
            img_bgr, offset, step.get('rgb', (255,0,0)), step.get('tolerance', 2),
            step.get('min_pixel_area', 10), step.get('blob_target', 'Largest Blob'),
            step.get('split_blob_width', 0))

    def find_template_in_region(self, screen_processed, offset, template_data, threshold):
        """
        Finds a template in a pre-processed screen region using an optimized matching method.
        Uses a fast, mask-aware method for transparent PNGs.
        """
        template_processed, mask = template_data
        if template_processed is None or any(s_dim < t_dim for s_dim, t_dim in zip(screen_processed.shape, template_processed.shape)):
            return None

        h, w = template_processed.shape[:2]

        if mask is not None:
            res = cv2.matchTemplate(screen_processed, template_processed, cv2.TM_SQDIFF_NORMED, mask=mask)
            min_val, _, min_loc, _ = cv2.minMaxLoc(res)
            
            confidence = 1.0 - min_val
            if confidence >= threshold:
                return (min_loc[0] + w // 2 + offset[0], min_loc[1] + h // 2 + offset[1], confidence)
        else:
            res = cv2.matchTemplate(screen_processed, template_processed, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val >= threshold:
                return (max_loc[0] + w // 2 + offset[0], max_loc[1] + h // 2 + offset[1], max_val)
                
        return None

    def get_item_mapping(self):
        if self.item_mapping_cache is not None: return self.item_mapping_cache
        url = "https://prices.runescape.wiki/api/v1/osrs/mapping"
        try:
            req = urllib.request.Request(url, headers=self.api_headers)
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())
                    self.item_mapping_cache = {'by_name': {item['name'].lower(): item for item in data}, 'by_id': {item['id']: item for item in data}}
                    self.log("Successfully downloaded and cached OSRS item map.")
                    return self.item_mapping_cache
                else: self.log(f"API Error: Failed to get item map (Status: {response.status})", "red"); return None
        except Exception as e: self.log(f"API Request Error: {e}", "red"); return None

    def get_item_price(self, item_name):
        item_map_data = self.get_item_mapping()
        if not item_map_data:
            return None
        item_map = item_map_data.get('by_name')
        if not item_map:
            return None

        item_data = item_map.get(item_name.lower())
        if not item_data:
            self.log(f"Item '{item_name}' not found in the mapping.", "orange")
            return None
        
        item_id = item_data['id']
        if item_id in self.item_price_cache:
            cached_data, timestamp = self.item_price_cache[item_id]
            if (time.time() - timestamp) < 60:
                return cached_data
            
        url = f"https://prices.runescape.wiki/api/v1/osrs/latest?id={item_id}"
        try:
            req = urllib.request.Request(url, headers=self.api_headers)
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    response_json = json.loads(response.read().decode())
                    if not response_json or 'data' not in response_json or response_json['data'] is None:
                        self.log(f"API Error: Malformed data response for {item_name}", "red")
                        return None

                    data = response_json['data']
                    if str(item_id) in data:
                        item_price_info = data[str(item_id)]
                        self.item_price_cache[item_id] = (item_price_info, time.time())
                        return item_price_info
                    else:
                        self.log(f"API Warning: Price data not available for {item_name} (ID: {item_id})", "orange")
                        return None
                else:
                    self.log(f"API Error: Failed to get price for {item_name} (Status: {response.status})", "red")
                    return None
        except Exception as e:
            self.log(f"API Request Error for {item_name}: {e}", "red")
            return None

    def get_all_latest_prices(self):
        if self.all_item_prices_cache:
            cached_data, timestamp = self.all_item_prices_cache
            if (time.time() - timestamp) < 300: return cached_data
        
        url = "https://prices.runescape.wiki/api/v1/osrs/latest"
        try:
            req = urllib.request.Request(url, headers=self.api_headers)
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())['data']
                    self.all_item_prices_cache = (data, time.time()); self.log("Successfully downloaded latest prices for all items.")
                    return data
                else: self.log(f"API Error: Failed to get all prices (Status: {response.status})", "red"); return None
        except Exception as e: self.log(f"API Request Error (all prices): {e}", "red"); return None

    def get_all_hourly_volumes(self):
        if self.hourly_volume_cache:
            cached_data, timestamp = self.hourly_volume_cache
            if (time.time() - timestamp) < 300: return cached_data

        url = "https://prices.runescape.wiki/api/v1/osrs/1h"
        try:
            req = urllib.request.Request(url, headers=self.api_headers)
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode())['data']
                    self.hourly_volume_cache = (data, time.time())
                    self.log("Successfully downloaded 1-hour volumes for all items.")
                    return data
                else: self.log(f"API Error: Failed to get all volumes (Status: {response.status})", "red"); return None
        except Exception as e: self.log(f"API Request Error (all volumes): {e}", "red"); return None
        
    def update_ge_interface_price(self):
        item_name = self.ge_interface_item_name.get()
        if not item_name:
            self.log("GE Interface: Please enter an item name.", "orange")
            return
        
        # Set a loading state in the UI immediately
        self.ge_interface_display_buy_price.set("Fetching...")
        self.ge_interface_display_buy_total.set("Fetching...")
        self.ge_interface_display_sell_price.set("Fetching...")
        self.ge_interface_display_sell_total.set("Fetching...")

        # Run the network request in a separate thread to avoid freezing the GUI
        fetch_thread = threading.Thread(target=self._fetch_ge_price_in_thread, daemon=True)
        fetch_thread.start()

    def _fetch_ge_price_in_thread(self):
        """Wrapper to run get_item_price in a thread and schedule UI update."""
        item_name = self.ge_interface_item_name.get()
        price_data = self.get_item_price(item_name)
        # Safely schedule the UI update to run on the main thread
        self.root.after(0, self._process_ge_price_data_on_main_thread, price_data)

    def run_test(self):
        def log_test(message): self.test_results_text.config(state='normal'); self.test_results_text.insert(tk.END, message + "\n"); self.test_results_text.config(state='disabled'); self.test_results_text.yview(tk.END)
        self.test_results_text.config(state='normal'); self.test_results_text.delete('1.0', tk.END); self.test_results_text.config(state='disabled')
        
        active_type = self.active_test_type.get()
        area = self.test_area or (self.area_x1.get(), self.area_y1.get(), self.area_x2.get(), self.area_y2.get()); w, h = area[2]-area[0], area[3]-area[1]
        if w < 1 or h < 1: log_test("ERROR: Test area is invalid."); return
        log_test(f"--- Running {self.active_test_type.get()} Test ---\nUsing area: {area}")
        try:
            if self.hide_on_select.get(): window_state, current_geometry = self.root.state(), self.root.geometry(); self.root.withdraw(); time.sleep(0.3)
            screen_cv = cv2.cvtColor(np.array(pyautogui.screenshot(region=(area[0], area[1], w, h))), cv2.COLOR_RGB2BGR)
        except Exception as e: log_test(f"ERROR: Failed to capture screen: {e}"); return
        finally:
            if self.hide_on_select.get(): 
                self.root.config(bg=self.current_theme['bg'])
                self.root.deiconify(); 
                self.root.state('zoomed') if window_state == 'zoomed' else self.root.geometry(current_geometry)
        
        if active_type == 'PNG':
            path, threshold, mode, image_mode = self.test_png_path.get(), self.test_png_threshold.get(), self.test_png_mode.get(), self.test_png_image_mode.get()
            log_test(f"Searching with Image Mode: {image_mode}")
            if not path: log_test("ERROR: No PNG path selected."); return
            image_paths = []
            if mode == 'file' and os.path.isfile(path): image_paths.append(path)
            elif mode == 'folder' and os.path.isdir(path): image_paths = [os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith('.png')]
            if not image_paths: log_test("No valid PNG images found."); return
            if image_mode == 'Grayscale': screen_processed = cv2.cvtColor(screen_cv, cv2.COLOR_BGR2GRAY)
            elif image_mode == 'Binary (B&W)': _, screen_processed = cv2.threshold(cv2.cvtColor(screen_cv, cv2.COLOR_BGR2GRAY), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            else: screen_processed = screen_cv
            found_count = 0
            for fpath in image_paths:
                template_data = self.load_template(fpath, image_mode)
                if template_data[0] is None: log_test(f"Warning: Could not load template {os.path.basename(fpath)}"); continue
                match = self.find_template_in_region(screen_processed, area[0:2], template_data, threshold)
                if match and math.isfinite(match[2]):
                    found_count += 1; log_test(f"SUCCESS: Found {os.path.basename(fpath)} with {match[2]*100:.2f}% confidence.")
            if found_count == 0: log_test("RESULT: No PNGs detected above the threshold.")
            else: log_test(f"--- Finished: Found {found_count} matching PNG(s). ---")
        elif active_type == 'Color':
            rgb, tolerance, space = self.test_color_rgb, self.test_color_tolerance.get(), self.test_color_space.get()
            log_test(f"Searching for RGB: {rgb} with tolerance: {tolerance} in {space} space")
            mock_step = {'rgb': rgb, 'tolerance': tolerance, 'min_pixel_area': 10}
            if space == 'RGB': 
                target_pos, contour_area = self.find_color_on_screen_rgb(screen_cv, area[0:2], mock_step)
            else: 
                target_pos, contour_area = self.find_color_on_screen_hsv(screen_cv, area[0:2], mock_step)
            if target_pos: log_test(f"SUCCESS: Color found at {target_pos}.\nDetected area size: {contour_area:.2f} pixels.")
            else: log_test("RESULT: Color not detected.")
        elif active_type == 'PNG Count':
            path, threshold, mode, image_mode, expression_str = self.test_png_path.get(), self.test_png_threshold.get(), self.test_png_mode.get(), self.test_png_image_mode.get(), self.test_png_count_expression.get()
            log_test(f"Counting with Image Mode: {image_mode}")
            if not path: log_test("ERROR: No PNG path selected."); return
            
            mock_step = { 'path': path, 'threshold': threshold, 'mode': mode, 'image_mode': image_mode }
            count = self.find_and_count_png(screen_cv, area[0:2], mock_step)
            log_test(f"Found {count} instances.")
            
            try:
                expression = expression_str.split()
                if len(expression) == 2:
                    op, val = expression[0], int(expression[1])
                    op_map = {'>': count > val, '<': count < val, '>=': count >= val, '<=': count <= val, '==': count == val, '!=': count != val}
                    result = op_map.get(op, False)
                    
                    if result: log_test(f"SUCCESS: Condition '{count} {op} {val}' is TRUE.")
                    else: log_test(f"RESULT: Condition '{count} {op} {val}' is FALSE.")
                else: raise ValueError("Expression must have 2 parts (e.g., '>= 5')")
            except (ValueError, IndexError) as e: log_test(f"ERROR: Invalid expression format.\nDetails: {e}")
        elif active_type == 'Color Count':
            rgb, tolerance, space = self.test_color_rgb, self.test_color_tolerance.get(), self.test_color_space.get()
            min_area = self.test_color_min_area.get()
            expression_str = self.test_color_count_expression.get()
            log_test(f"Counting Color RGB: {rgb} with tolerance: {tolerance} in {space} space")
            log_test(f"Min Area: {min_area}px, Expression: '{expression_str}'")
            mock_step = {'rgb': rgb, 'tolerance': tolerance, 'min_pixel_area': min_area, 'color_space': space}
            count = self.find_and_count_color(screen_cv, area[0:2], mock_step)
            log_test(f"Found {count} color blobs.")
            try:
                expression = expression_str.split()
                if len(expression) != 2: raise ValueError("Expression must have 2 parts (e.g., '>= 5')")
                op, val = expression[0], int(expression[1])
                op_map = {'>': count > val, '<': count < val, '>=': count >= val, '<=': count <= val, '==': count == val, '!=': count != val}
                result = op_map.get(op, False)
                if result: log_test(f"SUCCESS: Condition '{count} {op} {val}' is TRUE.")
                else: log_test(f"RESULT: Condition '{count} {op} {val}' is FALSE.")
            except (ValueError, IndexError) as e: log_test(f"ERROR: Invalid expression format.\nDetails: {e}")
        elif active_type == 'Number':
            expression = self.test_number_expression.get()
            psm_mode = self.psm_options.get(self.test_number_psm.get(), '6')
            oem_mode = self.oem_options.get(self.test_number_oem.get(), '3')
            log_test(f"Searching for number: '{expression}' (OEM: {oem_mode}, PSM: {psm_mode})")
            preprocessed_img = self.preprocess_for_ocr(screen_cv)
            ocr_config = f'--oem {oem_mode} --psm {psm_mode} -c tessedit_char_whitelist=0123456789:;,.-'
            try:
                ocr_text = pytesseract.image_to_string(Image.fromarray(preprocessed_img), config=ocr_config)
                cleaned_text = "".join(filter(lambda x: x in '0123456789.-', ocr_text)); log_test(f"OCR detected: '{cleaned_text}'")
                try:
                    num = float(cleaned_text); expr = expression.split(); op, val = expr[0], float(expr[1])
                    op_map = {'>': num > val, '<': num < val, '>=': num >= val, '<=': num <= val, '==': num == val, '!=': num != val}
                    if op_map.get(op, False): log_test(f"SUCCESS: {num} {op} {val} is TRUE.")
                    else: log_test(f"RESULT: {num} {op} {val} is FALSE.")
                except (ValueError, IndexError) as e: log_test(f"ERROR: Invalid expression format.\nDetails: {e}")
            except pytesseract.TesseractNotFoundError: log_test("ERROR: Tesseract OCR not found.")
            except Exception as e: log_test(f"ERROR during OCR: {e}")

    def copy_selection(self, event=None):
        if not self.selected_items or self.selected_items[0]['type'] != 'step': return
        self.clipboard = []
        indices = sorted([item['index'] for item in self.selected_items])
        min_x = min(self.steps[i].get('x', 0) for i in indices)
        min_y = min(self.steps[i].get('y', 0) for i in indices)
        self.clipboard_origin = (min_x, min_y)
        for index in indices: self.clipboard.append({"data": copy.deepcopy(self.steps[index]),"original_index": index})
        self.log(f"Copied {len(self.clipboard)} steps.")

    def paste_selection(self, event=None):
        if not self.clipboard: return

        # Determine paste location based on the last step, similar to add_step
        paste_anchor_x, paste_anchor_y = 50, 50 
        if self.steps:
            last_step = self.steps[-1]
            self._calculate_node_size(len(self.steps) - 1)
            paste_anchor_x = last_step.get('x', 50)
            paste_anchor_y = last_step.get('y', 50) + last_step.get('_height', 60) / self.zoom_factor + 40
        
        # Calculate the offset needed to move the copied block from its original position
        # to the new anchor position.
        x_offset = paste_anchor_x - self.clipboard_origin[0]
        y_offset = paste_anchor_y - self.clipboard_origin[1]

        new_steps, old_to_new_index_map, current_len = [], {}, len(self.steps)

        for i, clip_item in enumerate(self.clipboard):
            original_index = clip_item["original_index"]
            old_to_new_index_map[original_index] = current_len + i
            new_step = copy.deepcopy(clip_item["data"])
            
            # Apply the calculated offset to each pasted step
            new_step['x'] = new_step.get('x', 0) + x_offset
            new_step['y'] = new_step.get('y', 0) + y_offset
            
            new_steps.append(new_step)

        # Update flow control to maintain links within the pasted block
        for i, new_step in enumerate(new_steps):
            new_index = current_len + i
            original_index = next((k for k, v in old_to_new_index_map.items() if v == new_index), None)

            for action_key, goto_key in [('on_success_action', 'on_success_goto_step'), ('on_timeout_action', 'on_timeout_goto_step'), ('on_count_reached_action', 'on_count_reached_goto_step')]:
                if action_key not in new_step: continue
                
                action = new_step.get(action_key)
                if action == 'Go to Step':
                    target_original_index = new_step.get(goto_key, 1) - 1
                    if target_original_index in old_to_new_index_map:
                        new_step[goto_key] = old_to_new_index_map[target_original_index] + 1
                    else:
                        new_step[action_key] = 'Stop'
                elif action == 'Next Step':
                    if original_index is not None and (original_index + 1) in old_to_new_index_map:
                        # Successor step is also part of the pasted group, so link to it
                        new_step[action_key] = 'Go to Step'
                        new_step[goto_key] = old_to_new_index_map[original_index + 1] + 1
                    else:
                        # This step's successor is outside the pasted group, so default to Stop
                        new_step[action_key] = 'Stop'
        
        self.steps.extend(new_steps)
        self.log(f"Pasted {len(new_steps)} steps.")
        new_indices_range = range(len(self.steps) - len(new_steps), len(self.steps))
        self.selected_items = [{'type': 'step', 'index': i} for i in new_indices_range]
        self.populate_properties_panel(); self.redraw_flowchart()
        self.update_all_area_overlays()

    def delete_selected_from_key(self, event=None):
        if not self.selected_items: return
        num_items, item_type = len(self.selected_items), self.selected_items[0]['type']
        if not messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete the {num_items} selected {item_type}s?"): return

        if item_type == 'step': self.delete_selected()
        elif item_type == 'note':
            indices_to_remove = sorted([item['index'] for item in self.selected_items], reverse=True)
            for index in indices_to_remove: self.annotations.pop(index)
            self.log(f"Removed {len(indices_to_remove)} notes.")
            self.selected_items = []
            self.populate_properties_panel(); self.redraw_flowchart()
    
    def toggle_step_show_area_flag(self):
        """Updates the 'show_area' flag for the currently selected step and refreshes overlays."""
        if not (self.selected_items and len(self.selected_items) == 1 and self.selected_items[0]['type'] == 'step'):
            return
        index = self.selected_items[0]['index']
        step = self.steps[index]
        
        if 'show_area' in self.properties_widgets:
            is_checked = self.properties_widgets['show_area'].get()
            step['show_area'] = is_checked
            self.update_all_area_overlays()

    def update_all_area_overlays(self):
        """Destroys all current overlays and redraws them based on global and per-step settings."""
        self.destroy_all_overlays()
        show_all = self.enable_all_show_area.get()
        
        for i, step in enumerate(self.steps):
            if step.get("area"):
                if show_all or step.get("show_area"):
                    self._draw_overlay_for_step(i)
    
    def _draw_overlay_for_step(self, index):
        """Creates and displays a single Toplevel window for a step's area."""
        if index in self.area_overlays:
            return
            
        step = self.steps[index]
        area = step.get("area")
        if not area:
            return

        try:
            x1, y1, x2, y2 = area
            width = x2 - x1
            height = y2 - y1

            if width <= 0 or height <= 0: return

            overlay = tk.Toplevel(self.root)
            overlay.overrideredirect(True)
            overlay.attributes("-topmost", True)
            overlay.attributes("-transparentcolor", "black")
            overlay.geometry(f"{width}x{height}+{x1}+{y1}")

            canvas = tk.Canvas(overlay, bg="black", highlightthickness=0)
            canvas.pack(fill=tk.BOTH, expand=True)

            border_color = self.current_theme.get('accent_teal', '#56B6C2')
            canvas.create_rectangle(0, 0, width, height, outline=border_color, width=3)
            
            self.area_overlays[index] = overlay
        except Exception as e:
            self.log(f"Error creating overlay for Step {index+1}: {e}", "red")

    def destroy_all_overlays(self):
        """Safely destroys all Toplevel windows used for area overlays."""
        for overlay in self.area_overlays.values():
            try:
                overlay.destroy()
            except tk.TclError:
                pass 
        self.area_overlays.clear()

if __name__ == "__main__":
    root = tk.Tk()
    app = FlowchartClickerApp(root)
    root.mainloop()
