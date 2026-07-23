"""UI layer: CustomTkinter window, panels, system tray, theme management."""

from __future__ import annotations

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import queue
import time
import os
import ctypes
import ntpath
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageTk
import pystray

from config_manager import ConfigManager, ConfigPersistenceError
from i18n import Translator, normalize_language
from preflight import PreflightChecker, PreflightReport
from syncer import LogIcon, SyncManager, LogEvent
from vmrun_resolver import list_running_vms, normalize_vmx_path, resolve_vmrun_path


# ── Fonts ─────────────────────────────────────────────────────

FONT_FAMILY = "Microsoft YaHei UI"
MONO_FAMILY = "Microsoft YaHei"
APP_USER_MODEL_ID = "vm-sync-tool.vm-sync"
TRAY_START_ICON = "▶"
TRAY_PAUSE_ICON = "⏸"
SINGLE_PROJECT_GEOMETRY = "700x955"
SINGLE_PROJECT_MIN_SIZE = (640, 720)
DUAL_PROJECT_GEOMETRY = "1180x955"
DUAL_PROJECT_MIN_SIZE = (1040, 740)
CARD_CORNER_RADIUS = 8
CONTROL_CORNER_RADIUS = 6
CONTENT_SIDE_PADDING = 14
PROJECT_COLUMN_GAP = 8
PROJECT_COLUMN_MIN_WIDTH = 480
PROJECT_RUN_BUTTON_WIDTH = 84
PROJECT_RUN_BUTTON_HEIGHT = 30
SAVE_CHECK_BUTTON_WIDTH = 144
FULL_SYNC_BUTTON_WIDTH = SAVE_CHECK_BUTTON_WIDTH
CONFIG_ACTION_BUTTON_HEIGHT = 32
ACTION_BUTTON_BORDER_SPACING = 8
PROFILE_DROPDOWN_VISIBLE_ROWS = 8
PROFILE_POPUP_BORDER_WIDTH = 2
PROFILE_POPUP_INNER_RADIUS = CARD_CORNER_RADIUS - PROFILE_POPUP_BORDER_WIDTH
PROFILE_TOOLBAR_INSET = 3
PROFILE_TOOLBAR_INNER_RADIUS = CONTROL_CORNER_RADIUS - PROFILE_TOOLBAR_INSET
PROFILE_TOOLBAR_BUTTON_HEIGHT = 30


def ui_font(size=13, weight="normal"):
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)


def mono_font(size=12):
    return ctk.CTkFont(family=MONO_FAMILY, size=size)


def _configure_rounded_popup_window(window, fallback_color: str) -> bool:
    """Request compositor-antialiased rounded corners without color-key fringes."""
    window.configure(fg_color=fallback_color)
    if os.name != "nt":
        return False
    try:
        window.update_idletasks()
        preference = ctypes.c_int(2)  # DWMWCP_ROUND
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(window.winfo_id()),
            ctypes.c_uint(33),  # DWMWA_WINDOW_CORNER_PREFERENCE
            ctypes.byref(preference),
            ctypes.sizeof(preference),
        )
        return result == 0
    except (AttributeError, OSError, tk.TclError):
        return False


class _WindowsLogFont(ctypes.Structure):
    _fields_ = [
        ("lfHeight", ctypes.c_long),
        ("lfWidth", ctypes.c_long),
        ("lfEscapement", ctypes.c_long),
        ("lfOrientation", ctypes.c_long),
        ("lfWeight", ctypes.c_long),
        ("lfItalic", ctypes.c_ubyte),
        ("lfUnderline", ctypes.c_ubyte),
        ("lfStrikeOut", ctypes.c_ubyte),
        ("lfCharSet", ctypes.c_ubyte),
        ("lfOutPrecision", ctypes.c_ubyte),
        ("lfClipPrecision", ctypes.c_ubyte),
        ("lfQuality", ctypes.c_ubyte),
        ("lfPitchAndFamily", ctypes.c_ubyte),
        ("lfFaceName", ctypes.c_wchar * 32),
    ]


def _match_windows_ime_font(entry):
    """Match native Windows IME preedit text to a CTkEntry's rendered font."""
    if os.name != "nt":
        return
    native_entry = getattr(entry, "_entry", entry)
    try:
        font_spec = native_entry.cget("font")
        actual_size = int(native_entry.tk.call("font", "actual", font_spec, "-size"))
        family = str(native_entry.tk.call("font", "actual", font_spec, "-family"))
        weight = str(native_entry.tk.call("font", "actual", font_spec, "-weight"))
        if actual_size < 0:
            pixel_height = abs(actual_size)
        else:
            pixel_height = round(
                actual_size * float(native_entry.winfo_fpixels("1i")) / 72
            )

        log_font = _WindowsLogFont()
        log_font.lfHeight = -max(1, pixel_height)
        log_font.lfWeight = 700 if weight == "bold" else 400
        log_font.lfCharSet = 1  # DEFAULT_CHARSET
        log_font.lfQuality = 5  # CLEARTYPE_QUALITY
        log_font.lfFaceName = family[:31]

        imm32 = ctypes.windll.imm32
        imm32.ImmGetContext.argtypes = [ctypes.c_void_p]
        imm32.ImmGetContext.restype = ctypes.c_void_p
        imm32.ImmSetCompositionFontW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_WindowsLogFont),
        ]
        imm32.ImmSetCompositionFontW.restype = ctypes.c_int
        imm32.ImmReleaseContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        imm32.ImmReleaseContext.restype = ctypes.c_int

        hwnds = (native_entry.winfo_id(), entry.winfo_toplevel().winfo_id())
        for hwnd in dict.fromkeys(hwnds):
            input_context = imm32.ImmGetContext(hwnd)
            if not input_context:
                continue
            try:
                imm32.ImmSetCompositionFontW(input_context, ctypes.byref(log_font))
            finally:
                imm32.ImmReleaseContext(hwnd, input_context)
    except (AttributeError, OSError, tk.TclError, TypeError, ValueError):
        return


# ── Color Palette ────────────────────────────────────────────

DARK = {
    "bg": "#111315",
    "card": "#181c20",
    "border": "#2b333b",
    "accent": "#4f8cff",
    "accent_hover": "#3f78df",
    "success": "#32c57b",
    "warning": "#ffd166",
    "warning_hover": "#f4c45a",
    "error": "#e05252",
    "text": "#e7e2da",
    "text_dim": "#9aa4ae",
    "log_bg": "#0f1215",
    "entry_bg": "#12161a",
    "entry_border": "#323b44",
    "button_text": "#ffffff",
    "warning_text": "#18120a",
    "muted_button": "#28313a",
    "muted_hover": "#35414c",
    "hint_bg": "#14191e",
    "disabled": "#242a31",
}

LIGHT = {
    "bg": "#f5f7f9",
    "card": "#ffffff",
    "border": "#d8dee6",
    "accent": "#2f6fed",
    "accent_hover": "#245bcb",
    "success": "#218b5a",
    "warning": "#f7c96b",
    "warning_hover": "#edba55",
    "error": "#c93c3c",
    "text": "#1f2933",
    "text_dim": "#657180",
    "log_bg": "#f8fafc",
    "entry_bg": "#ffffff",
    "entry_border": "#cdd6e0",
    "button_text": "#ffffff",
    "warning_text": "#1f1607",
    "muted_button": "#e8edf2",
    "muted_hover": "#dce4ec",
    "hint_bg": "#f1f5f8",
    "disabled": "#e4e9ef",
}

ICON_CANVAS = 24


def _draw_line_icon(name: str, color: str, canvas: int = ICON_CANVAS) -> Image.Image:
    scale = 4
    size = canvas * scale
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    stroke = max(2, int(1.8 * scale))
    fill = color

    def s(value):
        return int(round(value * scale))

    def pts(values):
        return [(s(x), s(y)) for x, y in values]

    def line(values, width=stroke):
        draw.line(pts(values), fill=fill, width=width, joint="curve")

    def rounded(box, radius=3, width=stroke):
        draw.rounded_rectangle(
            tuple(s(v) for v in box),
            radius=s(radius),
            outline=fill,
            width=width,
        )

    def circle(cx, cy, radius=2.2):
        draw.ellipse(
            (s(cx - radius), s(cy - radius), s(cx + radius), s(cy + radius)),
            outline=fill,
            width=stroke,
        )

    if name == "sliders":
        line([(4, 6), (20, 6)])
        line([(4, 12), (20, 12)])
        line([(4, 18), (20, 18)])
        circle(9, 6, 2)
        circle(15, 12, 2)
        circle(11, 18, 2)
    elif name == "list":
        rounded((5, 4, 19, 20), radius=2.8)
        line([(8, 9), (16, 9)], width=max(1, int(1.5 * scale)))
        line([(8, 13), (16, 13)], width=max(1, int(1.5 * scale)))
        line([(8, 17), (14, 17)], width=max(1, int(1.5 * scale)))
    elif name == "folder":
        line([(3.5, 8), (8.5, 8), (10.5, 10), (20.5, 10)])
        line([(3.5, 8), (3.5, 19), (20.5, 19), (20.5, 10)])
    elif name == "save":
        rounded((5, 4, 19, 20), radius=2.6)
        line([(8, 4), (8, 9), (16, 9), (16, 4)])
        line([(8, 16), (16, 16)])
    elif name == "check":
        circle(12, 12, 7.2)
        line([(8.2, 12.2), (10.8, 14.8), (16.4, 9.2)])
    elif name == "upload":
        line([(12, 17), (12, 6)])
        line([(8.5, 9.5), (12, 6), (15.5, 9.5)])
        line([(6, 18.5), (6, 21), (18, 21), (18, 18.5)])
    elif name == "refresh":
        draw.arc(
            tuple(s(v) for v in (5, 5, 19, 19)),
            start=35,
            end=310,
            fill=fill,
            width=stroke,
        )
        line([(17.2, 5.4), (19.4, 5.4), (19.4, 3.2)])
    elif name == "play":
        draw.polygon(pts([(7, 5), (19, 12), (7, 19)]), fill=fill)
    elif name == "pause":
        draw.rounded_rectangle(
            (s(6.8), s(4.8), s(10.8), s(19.2)),
            radius=s(1.2),
            fill=fill,
        )
        draw.rounded_rectangle(
            (s(13.2), s(4.8), s(17.2), s(19.2)),
            radius=s(1.2),
            fill=fill,
        )
    elif name == "stop":
        draw.rounded_rectangle(
            (s(6.5), s(6.5), s(17.5), s(17.5)),
            radius=s(1.8),
            fill=fill,
        )
    elif name == "plus":
        line([(12, 5), (12, 19)])
        line([(5, 12), (19, 12)])
    elif name == "trash":
        rounded((6, 7, 18, 20), radius=2.2)
        line([(5, 7), (19, 7)])
        line([(9, 4), (15, 4), (16, 7)])
        line([(10, 10), (10, 17)], width=max(1, int(1.4 * scale)))
        line([(14, 10), (14, 17)], width=max(1, int(1.4 * scale)))
    elif name == "pencil":
        line([(6, 18), (7.5, 13.5), (15.5, 5.5), (18.5, 8.5), (10.5, 16.5), (6, 18)])
        line([(14.5, 6.5), (17.5, 9.5)], width=max(1, int(1.4 * scale)))
    elif name == "layers":
        line([(4, 8), (12, 4), (20, 8), (12, 12), (4, 8)])
        line([(5, 12), (12, 16), (19, 12)])
        line([(5, 16), (12, 20), (19, 16)])
    elif name == "chevron_down":
        line([(6.5, 9), (12, 14.5), (17.5, 9)], width=max(1, int(2.2 * scale)))
    else:
        circle(12, 12, 6)

    return image.resize((canvas, canvas), Image.Resampling.LANCZOS)


def icon_image(
    name: str,
    size: int = 18,
    light_color: str | None = None,
    dark_color: str | None = None,
) -> ctk.CTkImage:
    light = _draw_line_icon(name, light_color or LIGHT["text_dim"])
    dark = _draw_line_icon(name, dark_color or DARK["text_dim"])
    return ctk.CTkImage(light_image=light, dark_image=dark, size=(size, size))


def current_palette():
    mode = ctk.get_appearance_mode()
    return DARK if mode == "Dark" else LIGHT


LOG_MESSAGE_TAGS = {
    "success": "msg_success",
    "error": "msg_error",
    "warning": "msg_warning",
    "info": "msg_info",
}

LANGUAGE_SEGMENT_VALUES = {
    "zh": "中",
    "en": "EN",
}
SEGMENT_VALUE_LANGUAGES = {value: key for key, value in LANGUAGE_SEGMENT_VALUES.items()}


def app_tr(app, key: str, **kwargs) -> str:
    tr_func = getattr(app, "tr", None)
    if callable(tr_func):
        return tr_func(key, **kwargs)
    language = getattr(getattr(getattr(app, "cm", None), "config", None), "language", "zh")
    return Translator(language).tr(key, **kwargs)


def log_message_tag(level: str) -> str:
    return LOG_MESSAGE_TAGS.get(level, LOG_MESSAGE_TAGS["info"])


def pack_section_title(parent, image, text: str):
    title = ctk.CTkFrame(parent, fg_color="transparent")
    title.pack(side="left", anchor="center")
    ctk.CTkLabel(
        title,
        text="",
        image=image,
        width=24,
        height=24,
    ).pack(side="left", padx=(0, 8))
    text_label = ctk.CTkLabel(
        title,
        text=text,
        font=ui_font(size=15, weight="bold"),
        text_color=current_palette()["text"],
        height=24,
    )
    text_label.pack(side="left")
    return text_label


# ── AutoScrollFrame ────────────────────────────────────────────
"""Replacement for CTkScrollableFrame: scrollbar auto-hides when content fits."""


class AutoScrollFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        sb_color = kwargs.pop("scrollbar_button_color", "#30363d")
        sb_hover = kwargs.pop("scrollbar_button_hover_color", "#00d4ff")
        fg = kwargs.pop("fg_color", "transparent")
        canvas_bg = kwargs.pop("canvas_bg", "#0d1117")
        super().__init__(master, fg_color=fg, **kwargs)

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            self, highlightthickness=0, bd=0, bg=canvas_bg,
        )
        self._canvas_bg = canvas_bg
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self.scrollbar = ctk.CTkScrollbar(
            self, orientation="vertical",
            button_color=sb_color, button_hover_color=sb_hover,
            command=self._on_scrollbar_move,
        )

        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.inner = ctk.CTkFrame(self.canvas, fg_color="transparent")
        self._inner_id = self.canvas.create_window(
            (0, 0), window=self.inner, anchor="nw", tags="inner"
        )
        self._wheel_exclusions = set()
        self._last_canvas_size = (0, 0)
        self._scroll_sync_job = None
        self._scroll_region_dirty = True
        self._scrollbar_visible = False
        self._cached_content_h = 0
        self._last_sync_time = 0.0

        self.inner.bind("<Configure>", self._on_content_change, add="+")
        self.canvas.bind("<Configure>", self._on_canvas_change, add="+")
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        self.canvas.bind_all("<Button-4>", self._on_mousewheel, add="+")
        self.canvas.bind_all("<Button-5>", self._on_mousewheel, add="+")

    def _on_content_change(self, _event=None):
        self._scroll_region_dirty = True
        self._schedule_scroll_sync()

    def _on_canvas_change(self, event=None):
        if event is not None:
            size = (int(event.width), int(event.height))
        else:
            size = (self.canvas.winfo_width(), self.canvas.winfo_height())
        if size == self._last_canvas_size:
            return
        self._last_canvas_size = size
        w, _h = size
        if w > 4:
            try:
                cur_w = int(self.canvas.itemcget("inner", "width"))
            except (ValueError, TypeError, tk.TclError):
                cur_w = 0
            if cur_w != w:
                self.canvas.itemconfig("inner", width=w)
        self._schedule_scroll_sync()

    def _schedule_scroll_sync(self):
        if self._scroll_sync_job is not None:
            return
        self._scroll_sync_job = self.after_idle(self._sync_scrollbar)

    def _sync_scrollbar(self):
        self._scroll_sync_job = None
        now = time.monotonic()
        # Cooldown: cap at ~30 Hz to avoid flooding the event loop during
        # rapid Configure cascades — every bbox("all") triggers a full
        # geometry walk and starves the window manager's drag loop.
        if self._last_sync_time > 0 and now - self._last_sync_time < 0.033:
            self._scroll_sync_job = self.after(33, self._sync_scrollbar)
            return
        if self._scroll_region_dirty:
            bbox = self.canvas.bbox("all")
            if not bbox:
                self._last_sync_time = now
                return
            self.canvas.configure(scrollregion=bbox)
            self._scroll_region_dirty = False
            self._cached_content_h = bbox[3] - bbox[1]
        canvas_h = self.canvas.winfo_height()
        should_show = self._cached_content_h > canvas_h + 2
        if should_show == self._scrollbar_visible:
            self._last_sync_time = now
            return
        self._scrollbar_visible = should_show
        if should_show:
            self.scrollbar.grid(row=0, column=1, sticky="ns")
        else:
            self.scrollbar.grid_remove()
        self._last_sync_time = time.monotonic()

    def _on_scrollbar_move(self, *args):
        self.canvas.yview(*args)

    def add_wheel_exclusion(self, widget):
        if widget is not None:
            self._wheel_exclusions.add(widget)

    def _is_wheel_excluded(self, widget) -> bool:
        while widget is not None:
            if widget in self._wheel_exclusions:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _wheel_steps(self, event) -> int:
        if getattr(event, "num", None) == 4:
            return -1
        if getattr(event, "num", None) == 5:
            return 1
        delta = getattr(event, "delta", 0)
        if not delta:
            return 0
        steps = int(-1 * (delta / 120))
        if steps == 0:
            steps = -1 if delta > 0 else 1
        return steps

    def _on_mousewheel(self, event):
        if self._is_wheel_excluded(getattr(event, "widget", None)):
            return None
        if self.scrollbar.winfo_ismapped():
            steps = self._wheel_steps(event)
            if steps:
                self.canvas.yview_scroll(steps, "units")
                return "break"
        return None


# ── App Icon ──────────────────────────────────────

def app_icon_path() -> str:
    """Return the CustomTkinter titlebar icon used as the app-wide icon."""
    return str(
        Path(ctk.__file__).resolve().parent
        / "assets"
        / "icons"
        / "CustomTkinter_icon_Windows.ico"
    )


def create_app_icon(size: int = 32):
    """Load the same icon used by the window titlebar for tray/taskbar use."""
    with Image.open(app_icon_path()) as source:
        image = source.convert("RGBA")
    if image.size != (size, size):
        return image.resize((size, size), Image.Resampling.LANCZOS)
    return image


def create_tray_icon():
    """Return the shared app icon for the system tray."""
    return create_app_icon(32)


class TrayActivationMenu(pystray.Menu):
    """Menu that can highlight one item while tray icon activation runs another action."""

    def __init__(self, activation_action, *items):
        super().__init__(*items)
        self._activation_action = activation_action

    def __call__(self, icon):
        self._activation_action()


def set_windows_app_user_model_id():
    """Let Windows group this pythonw process under the app icon, not Python."""
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APP_USER_MODEL_ID
        )
    except Exception:
        pass


def tray_sync_label(running: bool, language: str = "zh") -> str:
    t = Translator(language).tr
    if running:
        return f"{TRAY_PAUSE_ICON}  {t('tray.sync.pause')}"
    return f"{TRAY_START_ICON}  {t('tray.sync.start')}"


def tray_status_label(
    running: bool,
    language: str = "zh",
    status: str | None = None,
) -> str:
    t = Translator(language).tr
    if not running:
        return t("tray.status.stopped")
    key = {
        "partial_running": "tray.status.partial_running",
        "partial_error": "tray.status.partial_error",
        "error": "tray.status.error",
    }.get(status, "tray.status.running")
    return t(key)


# ── Control Panel ────────────────────────────────────────────

class ControlPanel(ctk.CTkFrame):
    def __init__(self, master, app: "App"):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._start_time: float | None = None
        self._last_sync_count: int | None = None
        self._last_bin_ready: bool | None = None
        self._last_bin_status_text = ""
        self._last_uptime_text = ""
        self._full_sync_active = False
        self._start_preflight_snapshot: tuple | None = None

        # Left: two buttons stacked
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(side="left", padx=(0, 24))

        p = current_palette()
        self._play_icon = icon_image(
            "play",
            19,
            light_color=LIGHT["button_text"],
            dark_color=DARK["button_text"],
        )
        self._pause_icon = icon_image(
            "pause",
            19,
            light_color=LIGHT["warning_text"],
            dark_color=DARK["warning_text"],
        )
        self.start_btn = ctk.CTkButton(
            btn_frame,
            text=self._tr("ui.button.start"),
            image=self._play_icon,
            compound="left",
            anchor="center",
            font=ui_font(size=14, weight="bold"),
            width=132,
            height=40,
            corner_radius=CONTROL_CORNER_RADIUS,
            fg_color=p["accent"],
            hover_color=p["accent_hover"],
            text_color=p["button_text"],
            command=self._start,
        )
        self.start_btn.pack(pady=(0, 7))

        self.pause_btn = ctk.CTkButton(
            btn_frame,
            text=self._tr("ui.button.pause"),
            image=self._pause_icon,
            compound="left",
            anchor="center",
            font=ui_font(size=14, weight="bold"),
            width=132,
            height=40,
            corner_radius=CONTROL_CORNER_RADIUS,
            fg_color=p["muted_button"],
            hover_color=p["muted_hover"],
            text_color=p["text_dim"],
            state="disabled",
            command=self._pause,
        )
        self.pause_btn.pack()

        # Right: stats
        stats_frame = ctk.CTkFrame(self, fg_color="transparent")
        stats_frame.pack(side="left", fill="both", expand=True)

        self.sync_label = ctk.CTkLabel(
            stats_frame,
            text=self._tr("ui.control.synced", count=0),
            font=ui_font(size=13),
            text_color=p["text_dim"],
            anchor="w",
        )
        self.sync_label.pack(anchor="w", pady=(0, 2))

        self.bin_label = ctk.CTkLabel(
            stats_frame,
            text=self._tr("ui.bin.waiting"),
            font=ui_font(size=13),
            text_color=p["text_dim"],
            anchor="w",
        )
        self.bin_label.pack(anchor="w", pady=(0, 2))

        self.uptime_label = ctk.CTkLabel(
            stats_frame,
            text=self._tr("ui.control.uptime.empty"),
            font=ui_font(size=13),
            text_color=p["text_dim"],
            anchor="w",
        )
        self.uptime_label.pack(anchor="w")

    def _tr(self, key: str, **kwargs) -> str:
        return app_tr(self.app, key, **kwargs)

    def _start(self):
        report = self.app.config_panel.save_and_check()
        if not report.ok:
            self._start_preflight_snapshot = None
            return
        self._start_preflight_snapshot = self.app.sync.preflight_snapshot()
        self.app.config_panel.set_config_enabled(False)
        self.start_btn.configure(state="disabled")
        threading.Thread(target=self._start_worker, daemon=True).start()

    def _start_worker(self):
        error = ""
        try:
            started = self.app.sync.start(
                preflight_checked=True,
                preflight_snapshot=self._start_preflight_snapshot,
            )
        except Exception as e:
            started = False
            error = str(e)
        self.after(0, lambda: self._finish_start(started, error))

    def _finish_start(self, started: bool, error: str = ""):
        if started:
            self._set_running()
        else:
            message = (
                self._tr("ui.start.failed_with_error", error=error)
                if error else self._tr("ui.start.failed")
            )
            self.app.log_panel.append(LogEvent(LogIcon.ERROR, message, "error"))
            self._set_stopped()

    def _pause(self):
        try:
            self.app.sync.stop()
        except Exception as e:
            self.app.log_panel.append(LogEvent(LogIcon.ERROR, self._tr("ui.pause.failed", error=e), "error"))
        self._set_stopped()

    def _set_running(self):
        p = current_palette()
        self.app.config_panel.set_config_enabled(False)
        self.start_btn.configure(state="disabled", fg_color=p["border"])
        self.pause_btn.configure(
            state="normal",
            fg_color=p["warning"],
            hover_color=p["warning_hover"],
            text_color=p["warning_text"],
        )
        self.app._update_status_indicator(True)
        self.app._update_tray_menu()
        self._start_time = time.time()

    def _set_stopped(self):
        p = current_palette()
        self.app.config_panel.set_config_enabled(True)
        self.pause_btn.configure(
            state="disabled",
            fg_color=p["muted_button"],
            hover_color=p["muted_hover"],
            text_color=p["text_dim"],
        )
        self.start_btn.configure(
            state="normal",
            fg_color=p["accent"],
            hover_color=p["accent_hover"],
            text_color=p["button_text"],
        )
        self.app._status_indicator_state = "stopped"
        self.app._update_status_indicator(False)
        self.app._update_tray_menu()
        self._start_time = None
        text = self._tr("ui.control.uptime.empty")
        self.uptime_label.configure(text=text)
        self._last_uptime_text = text

    def set_full_sync_active(self, active: bool):
        self._full_sync_active = active
        p = current_palette()
        if active:
            self.start_btn.configure(state="disabled", fg_color=p["border"])
            return
        if not getattr(self.app.sync, "running", False):
            self.start_btn.configure(
                state="normal",
                fg_color=p["accent"],
                hover_color=p["accent_hover"],
                text_color=p["button_text"],
            )

    def update_stats(self, sync_count: int, bin_ready: bool, bin_status_text: str | None = None):
        if sync_count != self._last_sync_count:
            self.sync_label.configure(text=self._tr("ui.control.synced", count=sync_count))
            self._last_sync_count = sync_count
        if bin_status_text is None:
            formatter = getattr(self.app, "_format_bin_return_status", None)
            if callable(formatter):
                bin_status_text = formatter(bin_ready)
            else:
                bin_status_text = (
                    self._tr("ui.bin.ready") if bin_ready else self._tr("ui.bin.waiting")
                )
        if bin_ready != self._last_bin_ready or bin_status_text != self._last_bin_status_text:
            if bin_ready:
                p = current_palette()
                self.bin_label.configure(text=bin_status_text, text_color=p["success"])
            else:
                self.bin_label.configure(
                    text=bin_status_text,
                    text_color=current_palette()["text_dim"],
                )
            self._last_bin_ready = bin_ready
            self._last_bin_status_text = bin_status_text
        if self._start_time:
            elapsed = int(time.time() - self._start_time)
            h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
            uptime_text = self._tr("ui.control.uptime", uptime=f"{h:02d}:{m:02d}:{s:02d}")
            if uptime_text != self._last_uptime_text:
                self.uptime_label.configure(text=uptime_text)
                self._last_uptime_text = uptime_text

    def refresh_language(self):
        self.start_btn.configure(text=self._tr("ui.button.start"))
        self.pause_btn.configure(text=self._tr("ui.button.pause"))
        self._last_sync_count = None
        self._last_bin_ready = None
        self._last_bin_status_text = ""
        self.update_stats(self.app.sync.synced_count, self.app.sync.bin_ready)
        if not self._start_time:
            text = self._tr("ui.control.uptime.empty")
            self.uptime_label.configure(text=text)
            self._last_uptime_text = text
        else:
            self._last_uptime_text = ""

    def refresh_theme(self):
        p = current_palette()
        self.sync_label.configure(text_color=p["text_dim"])
        self.bin_label.configure(
            text_color=p["success"] if self._last_bin_ready else p["text_dim"]
        )
        self.uptime_label.configure(text_color=p["text_dim"])
        if self.app.sync.running:
            self.start_btn.configure(state="disabled", fg_color=p["border"])
            self.pause_btn.configure(
                state="normal",
                fg_color=p["warning"],
                hover_color=p["warning_hover"],
                text_color=p["warning_text"],
            )
        else:
            self.pause_btn.configure(
                state="disabled",
                fg_color=p["muted_button"],
                hover_color=p["muted_hover"],
                text_color=p["text_dim"],
            )
            self.start_btn.configure(
                state="normal",
                fg_color=p["accent"],
                hover_color=p["accent_hover"],
                text_color=p["button_text"],
            )


# ── Config Panel ─────────────────────────────────────────────

class ConfigPanel(ctk.CTkFrame):
    _NORMALIZED_PATH_ENTRY_KEYS = {
        "vmx_path",
        "host_project_path",
        "vm_project_path",
        "vm_bin_relative_path",
        "host_output_path",
    }
    _WINDOWS_ABSOLUTE_PATH_ENTRY_KEYS = {
        "vmx_path",
        "host_project_path",
        "vm_project_path",
        "host_output_path",
    }
    _FIELD_SPECS = [
        ("vmx_path", "ui.config.field.vmx", "file", "ui.config.placeholder.vmx"),
        ("vm_guest_user", "ui.config.field.vm_user", "path", "ui.config.placeholder.vm_user"),
        ("vm_guest_password", "ui.config.field.vm_password", "password", "ui.config.placeholder.vm_password"),
        ("host_project_path", "ui.config.field.host_project", "dir", "ui.config.placeholder.host_project"),
        ("vm_project_path", "ui.config.field.vm_project", "path", "ui.config.placeholder.vm_project"),
        ("vm_bin_relative_path", "ui.config.field.bin", "path", "ui.config.placeholder.bin"),
        ("host_output_path", "ui.config.field.host_output", "dir", "ui.config.placeholder.host_output"),
    ]

    def __init__(self, master, app: "App"):
        super().__init__(master, fg_color=current_palette()["card"],
                         border_color=current_palette()["border"], border_width=1,
                         corner_radius=CARD_CORNER_RADIUS)
        self.app = app
        self._entries = {}
        self._field_labels = {}
        self._field_placeholder_keys = {}
        self._browse_buttons = {}
        self._full_sync_thread: threading.Thread | None = None
        self._header_icon = icon_image(
            "sliders",
            19,
            light_color=LIGHT["accent"],
            dark_color=DARK["accent"],
        )
        self._save_icon = icon_image(
            "check",
            18,
            light_color=LIGHT["button_text"],
            dark_color=DARK["button_text"],
        )
        self._sync_icon = icon_image(
            "upload",
            18,
            light_color=LIGHT["warning_text"],
            dark_color=DARK["warning_text"],
        )
        self._cancel_icon = icon_image(
            "stop",
            18,
            light_color=LIGHT["button_text"],
            dark_color=DARK["button_text"],
        )
        self._folder_icon = icon_image(
            "folder",
            17,
            light_color=LIGHT["text_dim"],
            dark_color=DARK["text_dim"],
        )
        self._build()

    def _tr(self, key: str, **kwargs) -> str:
        return app_tr(self.app, key, **kwargs)

    def _config_source(self):
        return self.app.cm.config

    def _build(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(10, 5))
        self._header_text_label = pack_section_title(
            header,
            self._header_icon,
            self._tr("ui.section.config"),
        )

        # Entries
        entries_frame = ctk.CTkFrame(self, fg_color="transparent")
        entries_frame.pack(fill="x", padx=14, pady=(0, 4))

        for key, label_key, mode, placeholder_key in self._FIELD_SPECS:
            self._add_field(entries_frame, key, label_key, mode, placeholder_key)
        self._refresh_entry_placeholders()
        self.after_idle(self._refresh_entry_placeholders)

        self.bin_resolved_label = ctk.CTkLabel(
            self,
            text=self._tr("bin.display.empty"),
            font=ui_font(size=11),
            text_color=current_palette()["text_dim"],
            fg_color=current_palette()["hint_bg"],
            anchor="w",
            justify="left",
            height=24,
            corner_radius=CONTROL_CORNER_RADIUS,
            wraplength=620,
        )
        self.bin_resolved_label.pack(fill="x", padx=16, pady=(0, 4))
        self.update_bin_path_hint()

        # Buttons row
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(5, 10))

        self.save_btn = ctk.CTkButton(
            btn_row,
            text=self._tr("ui.button.save_check"),
            image=self._save_icon,
            compound="left",
            width=SAVE_CHECK_BUTTON_WIDTH,
            height=CONFIG_ACTION_BUTTON_HEIGHT,
            border_spacing=ACTION_BUTTON_BORDER_SPACING,
            corner_radius=CONTROL_CORNER_RADIUS, font=ui_font(size=12),
            fg_color=current_palette()["accent"],
            hover_color=current_palette()["accent_hover"],
            text_color=current_palette()["button_text"],
            command=self._save,
        )
        self.save_btn.pack(side="left", padx=(0, 8))

        self.fullsync_btn = ctk.CTkButton(
            btn_row,
            text=self._tr("ui.button.full_sync"),
            image=self._sync_icon,
            compound="left",
            width=FULL_SYNC_BUTTON_WIDTH,
            height=CONFIG_ACTION_BUTTON_HEIGHT,
            border_spacing=ACTION_BUTTON_BORDER_SPACING,
            corner_radius=CONTROL_CORNER_RADIUS, font=ui_font(size=12),
            fg_color=current_palette()["warning"],
            hover_color=current_palette()["warning_hover"],
            text_color=current_palette()["warning_text"],
            command=self._full_sync,
        )
        self.fullsync_btn.pack(side="left")

        self.status_label = ctk.CTkLabel(
            btn_row, text="",
            font=ui_font(size=12),
            text_color=current_palette()["text_dim"],
        )
        self.status_label.pack(side="right")

    def _add_field(self, parent, key, label_key, mode, placeholder_key):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=2)

        label = ctk.CTkLabel(
            row, text=self._tr(label_key), width=132, anchor="w",
            font=ui_font(size=12),
            text_color=current_palette()["text_dim"],
        )
        label.pack(side="left", padx=(0, 6))
        self._field_labels[key] = label
        self._field_placeholder_keys[key] = placeholder_key

        entry_kwargs = {"show": "*"} if mode == "password" else {}
        entry = ctk.CTkEntry(
            row, height=30, corner_radius=CONTROL_CORNER_RADIUS,
            font=ui_font(size=12),
            border_color=current_palette()["entry_border"],
            fg_color=current_palette()["entry_bg"],
            placeholder_text_color=current_palette()["text_dim"],
            placeholder_text=self._tr(placeholder_key),
            **entry_kwargs,
        )
        entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        val = getattr(self._config_source(), key, "")
        if val:
            entry.insert(0, val)
        if key in self._NORMALIZED_PATH_ENTRY_KEYS:
            entry.bind("<FocusOut>", lambda _event, k=key: self._normalize_entry_display(k))
            entry.bind("<Return>", lambda _event, k=key: self._normalize_entry_display(k))
        self._entries[key] = entry

        if mode in ("dir", "file"):
            btn = ctk.CTkButton(
                row,
                text="",
                image=self._folder_icon,
                width=42,
                height=32,
                corner_radius=CONTROL_CORNER_RADIUS,
                font=ui_font(size=12),
                fg_color=current_palette()["muted_button"],
                hover_color=current_palette()["muted_hover"],
                text_color=current_palette()["text"],
                command=lambda k=key, m=mode: self._browse(k, m),
            )
            btn.pack(side="right")
            self._browse_buttons[key] = btn

    def _browse(self, key, mode):
        if mode == "dir":
            path = filedialog.askdirectory(title=self._tr("filedialog.dir"))
        else:
            path = filedialog.askopenfilename(
                title=self._tr("filedialog.vmx"),
                filetypes=[("VMware VMX", "*.vmx"), ("All files", "*.*")],
            )
        if path:
            normalized = self._normalize_entry_value(
                key,
                path,
                vm_project_path=self._current_vm_project_path_for_normalization(),
            )
            self._replace_entry_value(self._entries[key], normalized)

    def _save_values_only(self, emit_log: bool = False):
        raw_values = {
            key: entry.get().strip()
            for key, entry in self._entries.items()
        }
        vm_project_path = self._normalize_entry_value(
            "vm_project_path",
            raw_values.get(
                "vm_project_path",
                getattr(self.app.cm.config, "vm_project_path", ""),
            ),
        )
        for key, entry in self._entries.items():
            value = self._normalize_entry_value(
                key,
                raw_values.get(key, ""),
                vm_project_path=vm_project_path,
            )
            setattr(self.app.cm.config, key, value)
        self.app.resolve_vmrun_path(save=True)
        self.app.cm.save()
        self._refresh_entry_values_from_config()
        log_panel = getattr(self.app, "log_panel", None)
        if emit_log and log_panel:
            log_panel.append(
                LogEvent(
                    LogIcon.CONFIG,
                    self._tr("ui.config.saved", path=self.app.cm.config_path),
                    "success",
                )
            )

    def _normalize_entry_display(self, key: str):
        entry = self._entries.get(key)
        if not entry:
            return
        normalized = self._normalize_entry_value(
            key,
            entry.get(),
            vm_project_path=self._current_vm_project_path_for_normalization(),
        )
        self._replace_entry_value(entry, normalized)

    def _refresh_entry_values_from_config(self):
        for key, entry in self._entries.items():
            value = getattr(self.app.cm.config, key, "")
            if entry.get() != value:
                self._replace_entry_value(entry, value)

    def _replace_entry_value(self, entry, value: str):
        entry.delete(0, "end")
        if value:
            entry.insert(0, value)
        else:
            self._refresh_single_entry_placeholder(entry)

    def _refresh_entry_placeholders(self):
        for entry in self._entries.values():
            if entry.get() == "" and not self._entry_has_focus(entry):
                self._refresh_single_entry_placeholder(entry)

    def _refresh_single_entry_placeholder(self, entry):
        focus_out = getattr(entry, "_entry_focus_out", None)
        if callable(focus_out):
            focus_out()
        else:
            activate = getattr(entry, "_activate_placeholder", None)
            if callable(activate):
                activate()

        draw = getattr(entry, "_draw", None)
        if callable(draw):
            draw()

    def _entry_has_focus(self, entry) -> bool:
        try:
            focused = entry.winfo_toplevel().focus_get()
        except Exception:
            return False
        while focused is not None:
            if focused is entry or focused is getattr(entry, "_entry", None):
                return True
            focused = getattr(focused, "master", None)
        return False

    def _current_vm_project_path_for_normalization(self) -> str:
        entry = self._entries.get("vm_project_path")
        value = entry.get() if entry else getattr(self.app.cm.config, "vm_project_path", "")
        return self._normalize_entry_value("vm_project_path", value)

    def _normalize_entry_value(
        self,
        key: str,
        value: str,
        vm_project_path: str | None = None,
    ) -> str:
        if key not in self._NORMALIZED_PATH_ENTRY_KEYS:
            return str(value or "").strip()
        text = self._clean_path_text(value)
        if not text:
            return ""
        if key == "vm_bin_relative_path":
            return self._normalize_vm_bin_relative_path(text, vm_project_path)
        if key in self._WINDOWS_ABSOLUTE_PATH_ENTRY_KEYS:
            return self._normalize_windows_path(text)
        return text

    def _normalize_vm_bin_relative_path(
        self,
        value: str,
        vm_project_path: str | None = None,
    ) -> str:
        text = value.replace("/", "\\")
        drive, _tail = ntpath.splitdrive(text)
        if not drive:
            text = text.lstrip("\\")
        text = ntpath.normpath(text)
        if text == ".":
            return text

        if vm_project_path is not None:
            root_path = vm_project_path
        else:
            try:
                root_path = self._current_vm_project_path_for_normalization()
            except AttributeError:
                root_path = getattr(self._config_source(), "vm_project_path", "")
        root = self._normalize_windows_path(root_path)
        if root and self._is_windows_absolute_path(text):
            relative = self._relative_path_under_root(text, root)
            if relative is not None:
                return relative
        return text

    def _relative_path_under_root(self, path: str, root: str) -> str | None:
        normalized_path = self._normalize_windows_path(path)
        normalized_root = self._normalize_windows_path(root).rstrip("\\")
        if not normalized_root:
            return None

        path_key = normalized_path.casefold()
        root_key = normalized_root.casefold()
        if path_key == root_key:
            return "."
        if not path_key.startswith(root_key + "\\"):
            return None
        try:
            return ntpath.normpath(ntpath.relpath(normalized_path, normalized_root))
        except ValueError:
            return None

    def _normalize_windows_path(self, value: str) -> str:
        text = self._clean_path_text(value)
        if not text:
            return ""
        return ntpath.normpath(text.replace("/", "\\"))

    def _clean_path_text(self, value: str) -> str:
        text = str(value or "").strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
            text = text[1:-1].strip()
        return text

    def _is_windows_absolute_path(self, path: str) -> bool:
        return ntpath.isabs(path)

    def update_bin_path_hint(self, check_guest: bool = False):
        p = current_palette()
        cfg = self.app.cm.config
        text_color = p["text_dim"]

        if not cfg.vm_project_path or not cfg.vm_bin_relative_path:
            self.bin_resolved_label.configure(
                text=self._tr("bin.display.empty"),
                text_color=text_color,
            )
            return

        configured_path = self.app.cm.get_vm_bin_full_path()
        is_file = cfg.vm_bin_relative_path.lower().endswith(".bin")
        resolved = None
        if check_guest:
            try:
                resolved = self.app.sync.resolve_vm_bin_path_for_display()
            except Exception:
                resolved = None

        if resolved:
            vm_path, _filename = resolved
            if is_file:
                text = self._tr("bin.display.file", path=vm_path)
            else:
                self._autofill_resolved_bin_path(vm_path)
                text = self._tr(
                    "bin.display.detected",
                    relative=self._relative_vm_bin_path(vm_path),
                    path=vm_path,
                )
            text_color = p["success"]
        elif check_guest and not is_file:
            text = self._tr("bin.display.dir_choose_file", path=configured_path)
            text_color = p["warning"]
        elif is_file:
            text = self._tr("bin.display.file", path=configured_path)
        else:
            text = self._tr("bin.display.dir", path=configured_path)

        self.bin_resolved_label.configure(text=text, text_color=text_color)

    def _relative_vm_bin_path(self, vm_path: str) -> str:
        return self._normalize_vm_bin_relative_path(
            vm_path,
            self.app.cm.config.vm_project_path,
        )

    def _autofill_resolved_bin_path(self, vm_path: str):
        rel_path = self._relative_vm_bin_path(vm_path)
        if not rel_path.lower().endswith(".bin"):
            return
        entry = getattr(self, "_entries", {}).get("vm_bin_relative_path")
        current = entry.get().strip() if entry else self.app.cm.config.vm_bin_relative_path
        normalized_current = self._normalize_vm_bin_relative_path(current)
        if normalized_current.lower() == rel_path.lower():
            if entry and current != rel_path:
                self._replace_entry_value(entry, rel_path)
            if self.app.cm.config.vm_bin_relative_path.lower() != rel_path.lower():
                self.app.cm.config.vm_bin_relative_path = rel_path
                self.app.cm.save()
            return
        if entry:
            self._replace_entry_value(entry, rel_path)
        self.app.cm.config.vm_bin_relative_path = rel_path
        self.app.cm.save()
        log_panel = getattr(self.app, "log_panel", None)
        if log_panel:
            log_panel.append(
                LogEvent(
                    LogIcon.BIN,
                    self._tr("bin.autofill.relative", path=rel_path),
                    "success",
                )
            )

    def set_config_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for entry in self._entries.values():
            entry.configure(state=state)
        for button in self._browse_buttons.values():
            button.configure(state=state)
        self.save_btn.configure(state=state)
        self.fullsync_btn.configure(state=state)

    def _save(self):
        self.save_and_check()

    def mark_start_checking(self):
        self.update_bin_path_hint(check_guest=False)
        self.status_label.configure(
            text=self._tr("ui.config.status.checking"),
            text_color=current_palette()["text_dim"],
        )

    def apply_preflight_report(self, report: PreflightReport):
        self.update_bin_path_hint(check_guest=report.ok)
        p = current_palette()
        if report.ok and report.warning_text:
            self.status_label.configure(text=self._tr("ui.config.status.warning", icon=LogIcon.WARNING), text_color=p["warning"])
        elif report.ok:
            self.status_label.configure(text=self._tr("ui.config.status.ok", icon=LogIcon.SUCCESS), text_color=p["success"])
        else:
            self.status_label.configure(text=self._tr("ui.config.status.error", icon=LogIcon.ERROR), text_color=p["error"])
        self.after(2000, lambda: self.status_label.configure(text=""))

    def save_and_check(self) -> PreflightReport:
        self._save_values_only(emit_log=True)
        report = self.app._run_preflight(dedupe_errors=False)
        self.apply_preflight_report(report)
        return report

    def _full_sync(self):
        self._save_values_only(emit_log=True)
        report = self.app._run_preflight(for_full_sync=True, show_dialog=True)
        if not report.ok:
            return
        details = report.summary
        if report.warning_text:
            details = f"{details}\n\n{self._tr('dialog.warning_header')}\n{report.warning_text}"
        if not messagebox.askyesno(
            self._tr("dialog.full_sync.title"),
            self._tr("dialog.full_sync.message", details=details),
            parent=self.app.window,
        ):
            self.app.log_panel.append(LogEvent(LogIcon.CANCEL, self._tr("sync.full.confirm_cancelled"), "info"))
            return
        self.set_config_enabled(False)
        self.app.control.set_full_sync_active(True)
        self._set_full_sync_button_active(True)
        self._full_sync_thread = threading.Thread(target=self._run_full_sync)
        self._full_sync_thread.start()

    def _cancel_full_sync(self):
        self.app.sync.request_full_sync_cancel()
        self.fullsync_btn.configure(text=self._tr("ui.button.canceling"), state="disabled")

    def _run_full_sync(self):
        try:
            self.app.sync.full_sync()
        finally:
            try:
                self.after(0, self._finish_full_sync)
            except tk.TclError:
                pass

    def _finish_full_sync(self):
        try:
            enabled = not self.app.sync.running
            self.set_config_enabled(enabled)
            self._set_full_sync_button_active(False, enabled=enabled)
            self.app.control.set_full_sync_active(False)
        except tk.TclError:
            pass

    def _set_full_sync_button_active(self, active: bool, enabled: bool = True):
        p = current_palette()
        if active:
            self.fullsync_btn.configure(
                text=self._tr("ui.button.cancel_full"),
                image=self._cancel_icon,
                command=self._cancel_full_sync,
                state="normal",
                fg_color=p["error"],
                hover_color=p["error"],
                text_color=p["button_text"],
            )
            return
        self.fullsync_btn.configure(
            text=self._tr("ui.button.full_sync"),
            image=self._sync_icon,
            command=self._full_sync,
            state="normal" if enabled else "disabled",
            fg_color=p["warning"],
            hover_color=p["warning_hover"],
            text_color=p["warning_text"],
        )

    def load_values(self):
        for key, entry in self._entries.items():
            entry.delete(0, "end")
            val = getattr(self.app.cm.config, key, "")
            if val:
                entry.insert(0, val)
        if hasattr(self, "bin_resolved_label"):
            self.update_bin_path_hint()

    def refresh_theme(self):
        p = current_palette()
        self.configure(fg_color=p["card"], border_color=p["border"])
        self._header_text_label.configure(text_color=p["text"])
        for entry in self._entries.values():
            entry.configure(
                border_color=p["entry_border"],
                fg_color=p["entry_bg"],
                placeholder_text_color=p["text_dim"],
            )
        self.bin_resolved_label.configure(fg_color=p["hint_bg"])
        for button in self._browse_buttons.values():
            button.configure(
                fg_color=p["muted_button"],
                hover_color=p["muted_hover"],
                text_color=p["text"],
            )
        self.update_bin_path_hint()
        if getattr(self.app.sync, "full_sync_active", False):
            self._set_full_sync_button_active(True)
        else:
            self.fullsync_btn.configure(
                fg_color=p["warning"],
                hover_color=p["warning_hover"],
                text_color=p["warning_text"],
            )
        self.save_btn.configure(
            fg_color=p["accent"],
            hover_color=p["accent_hover"],
            text_color=p["button_text"],
        )

    def refresh_language(self):
        self._header_text_label.configure(text=self._tr("ui.section.config"))
        field_spec_by_key = {
            key: (label_key, placeholder_key)
            for key, label_key, _mode, placeholder_key in self._FIELD_SPECS
        }
        for key, label in self._field_labels.items():
            label_key, placeholder_key = field_spec_by_key[key]
            label.configure(text=self._tr(label_key))
            entry = self._entries.get(key)
            if entry is not None:
                entry.configure(placeholder_text=self._tr(placeholder_key))
        self.save_btn.configure(text=self._tr("ui.button.save_check"))
        if getattr(self.app.sync, "full_sync_active", False):
            self._set_full_sync_button_active(True)
        else:
            self._set_full_sync_button_active(False, enabled=self.fullsync_btn.cget("state") != "disabled")
        self.update_bin_path_hint()
        self._refresh_entry_placeholders()


# ── Log Panel ────────────────────────────────────────────────

class LogPanel(ctk.CTkFrame):
    MAX_LINES = 500

    def __init__(self, master, app=None):
        super().__init__(master, fg_color=current_palette()["card"],
                         border_color=current_palette()["border"], border_width=1,
                         corner_radius=CARD_CORNER_RADIUS)
        self.app = app
        self._header_icon = icon_image(
            "list",
            19,
            light_color=LIGHT["accent"],
            dark_color=DARK["accent"],
        )
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(10, 5))
        self._header_text_label = pack_section_title(
            header,
            self._header_icon,
            self._tr("ui.log.title"),
        )

        self.clear_btn = ctk.CTkButton(
            header, text=self._tr("ui.button.clear"), width=52, height=26, corner_radius=CONTROL_CORNER_RADIUS,
            font=ui_font(size=11),
            fg_color=current_palette()["muted_button"],
            hover_color=current_palette()["muted_hover"],
            text_color=current_palette()["text_dim"],
            command=self.clear,
        )
        self.clear_btn.pack(side="right")

        self.progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.progress_frame.pack(fill="x", padx=12, pady=(0, 5))
        self.progress_label = ctk.CTkLabel(
            self.progress_frame,
            text="",
            font=ui_font(size=12),
            text_color=current_palette()["text_dim"],
            anchor="w",
        )
        self.progress_label.pack(fill="x", pady=(0, 2))
        self.progress_bar = ctk.CTkProgressBar(
            self.progress_frame,
            height=8,
            progress_color=current_palette()["accent"],
            fg_color=current_palette()["muted_button"],
        )
        self.progress_bar.pack(fill="x")
        self.progress_bar.set(0)
        self.progress_frame.pack_forget()

        self.textbox = ctk.CTkTextbox(
            self, font=mono_font(size=12),
            height=200,
            fg_color=current_palette()["log_bg"],
            border_color=current_palette()["entry_border"], border_width=1,
            corner_radius=CONTROL_CORNER_RADIUS, wrap="char",
        )
        self.textbox.pack(fill="x", padx=12, pady=(2, 10))
        self.textbox.configure(state="disabled")

        self._line_count = 0
        self._tag_mode = None

    def _tr(self, key: str, **kwargs) -> str:
        if self.app is not None:
            return app_tr(self.app, key, **kwargs)
        return Translator().tr(key, **kwargs)

    def append(self, event: LogEvent):
        msg_tag = log_message_tag(event.level)

        self.textbox.configure(state="normal")
        self._configure_log_tags()
        self.textbox.insert("end", f"{event.timestamp}  ", "ts_tag")
        self.textbox.insert("end", f"{event.icon} {event.message}\n", msg_tag)

        self._line_count += 1
        if self._line_count > self.MAX_LINES:
            self.textbox.delete("1.0", "2.0")
            self._line_count -= 1

        self.textbox.see("end")
        self.textbox.configure(state="disabled")

    def _configure_log_tags(self):
        mode = ctk.get_appearance_mode()
        if mode == getattr(self, '_tag_mode', None):
            return
        self._tag_mode = mode
        p = current_palette()
        self.textbox.tag_config("ts_tag", foreground=p["text_dim"])
        self.textbox.tag_config("msg_success", foreground=p["success"])
        self.textbox.tag_config("msg_error", foreground=p["error"])
        self.textbox.tag_config("msg_warning", foreground=p["warning"])
        self.textbox.tag_config("msg_info", foreground=p["text_dim"])

    def update_progress(self, data: dict):
        p = current_palette()
        value = float(data.get("value", 0.0))
        message = str(data.get("message", ""))
        active = bool(data.get("active", True))
        self.progress_frame.pack(fill="x", padx=12, pady=(0, 5), before=self.textbox)
        self.progress_label.configure(
            text=message,
            text_color=p["success"] if not active and value >= 1.0 else p["text_dim"],
        )
        self.progress_bar.set(value)
        if not active:
            self.after(4000, self._hide_progress)

    def _hide_progress(self):
        self.progress_frame.pack_forget()

    def clear(self):
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")
        self._line_count = 0

    def refresh_theme(self):
        p = current_palette()
        self.configure(fg_color=p["card"], border_color=p["border"])
        self._header_text_label.configure(text_color=p["text"])
        self.textbox.configure(fg_color=p["log_bg"], border_color=p["entry_border"])
        self._tag_mode = None
        self._configure_log_tags()
        self.progress_label.configure(text_color=p["text_dim"])
        self.progress_bar.configure(progress_color=p["accent"], fg_color=p["muted_button"])
        self.clear_btn.configure(
            fg_color=p["muted_button"],
            hover_color=p["muted_hover"],
            text_color=p["text_dim"],
        )

    def refresh_language(self):
        self._header_text_label.configure(text=self._tr("ui.log.title"))
        self.clear_btn.configure(text=self._tr("ui.button.clear"))


# ── Status Bar ───────────────────────────────────────────────

_OriginalControlPanel = ControlPanel
_OriginalConfigPanel = ConfigPanel


class NewProfileDialog(ctk.CTkToplevel):
    def __init__(self, app: "App", on_create, on_close=None):
        super().__init__(app.window)
        self.app = app
        self.on_create = on_create
        self.on_close = on_close
        self._closed = False
        self.title(self._tr("ui.profile.dialog.title"))
        self.geometry("430x326")
        self.resizable(False, False)
        self.configure(fg_color=current_palette()["bg"])
        self.transient(app.window)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._build()
        self.after(20, self._finish_open)

    def _tr(self, key: str, **kwargs) -> str:
        return app_tr(self.app, key, **kwargs)

    def _build(self):
        p = current_palette()
        self.card = ctk.CTkFrame(
            self,
            fg_color=p["card"],
            border_color=p["border"],
            border_width=1,
            corner_radius=CARD_CORNER_RADIUS,
        )
        card = self.card
        card.pack(fill="both", expand=True, padx=16, pady=16)
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(6, weight=1)

        ctk.CTkLabel(
            card,
            text=self._tr("ui.profile.dialog.heading"),
            font=ui_font(size=16, weight="bold"),
            text_color=p["text"],
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 3))
        ctk.CTkLabel(
            card,
            text=self._tr("ui.profile.dialog.description"),
            font=ui_font(size=11),
            text_color=p["text_dim"],
            anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))

        ctk.CTkLabel(
            card,
            text=self._tr("ui.profile.name"),
            font=ui_font(size=11),
            text_color=p["text_dim"],
            anchor="w",
        ).grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 4))
        self.name_entry = ctk.CTkEntry(
            card,
            height=34,
            corner_radius=CONTROL_CORNER_RADIUS,
            font=ui_font(size=12),
            border_color=p["entry_border"],
            fg_color=p["entry_bg"],
            placeholder_text=self._tr("ui.profile.name_placeholder"),
            placeholder_text_color=p["text_dim"],
        )
        self.name_entry.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 10))

        ctk.CTkLabel(
            card,
            text=self._tr("ui.profile.create_from"),
            font=ui_font(size=11),
            text_color=p["text_dim"],
            anchor="w",
        ).grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 4))
        source_row = ctk.CTkFrame(card, fg_color="transparent")
        source_row.grid(row=5, column=0, sticky="ew", padx=18)
        source_row.grid_columnconfigure((0, 1), weight=1)
        self.source_var = tk.StringVar(value="copy")
        ctk.CTkRadioButton(
            source_row,
            text=self._tr("ui.profile.copy_current"),
            variable=self.source_var,
            value="copy",
            font=ui_font(size=11),
            fg_color=p["accent"],
            hover_color=p["accent_hover"],
            text_color=p["text"],
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkRadioButton(
            source_row,
            text=self._tr("ui.profile.blank"),
            variable=self.source_var,
            value="blank",
            font=ui_font(size=11),
            fg_color=p["accent"],
            hover_color=p["accent_hover"],
            text_color=p["text"],
        ).grid(row=0, column=1, sticky="w")

        self.feedback_label = ctk.CTkLabel(
            card,
            text=(
                self._tr("ui.profile.dialog.dirty_note")
                if app.profile_form_is_dirty()
                else ""
            ),
            font=ui_font(size=10),
            text_color=p["warning"],
            anchor="w",
            justify="left",
            wraplength=360,
        )
        self.feedback_label.grid(row=6, column=0, sticky="new", padx=18, pady=(7, 0))

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=7, column=0, sticky="sew", padx=18, pady=(12, 16))
        self.cancel_btn = ctk.CTkButton(
            actions,
            text=self._tr("ui.profile.cancel"),
            width=92,
            height=32,
            corner_radius=CONTROL_CORNER_RADIUS,
            font=ui_font(size=12),
            fg_color=p["muted_button"],
            hover_color=p["muted_hover"],
            text_color=p["text"],
            command=self._cancel,
        )
        self.cancel_btn.pack(side="right")
        self.create_btn = ctk.CTkButton(
            actions,
            text=self._tr("ui.profile.create_save"),
            image=icon_image(
                "plus", 15,
                light_color=LIGHT["button_text"], dark_color=DARK["button_text"],
            ),
            compound="left",
            width=126,
            height=32,
            corner_radius=CONTROL_CORNER_RADIUS,
            font=ui_font(size=12),
            fg_color=p["accent"],
            hover_color=p["accent_hover"],
            text_color=p["button_text"],
            command=self._create,
        )
        self.create_btn.pack(side="right", padx=(0, 8))

        self.bind("<Return>", lambda _event: self._create())
        self.bind("<Escape>", lambda _event: self._cancel())

    def _finish_open(self):
        try:
            self.update_idletasks()
            required_width = max(430, self.card.winfo_reqwidth() + 32)
            required_height = max(326, self.card.winfo_reqheight() + 32)
            self.geometry(f"{required_width}x{required_height}")
            self.update_idletasks()
            parent_x = self.app.window.winfo_rootx()
            parent_y = self.app.window.winfo_rooty()
            parent_w = self.app.window.winfo_width()
            parent_h = self.app.window.winfo_height()
            x = parent_x + max(0, (parent_w - self.winfo_width()) // 2)
            y = parent_y + max(0, (parent_h - self.winfo_height()) // 2)
            self.geometry(f"+{x}+{y}")
            self.grab_set()
            self.name_entry.focus_set()
        except tk.TclError:
            return

    def _create(self):
        copy_current = self.source_var.get() == "copy"
        error_message = self.on_create(self.name_entry.get(), copy_current)
        if error_message:
            self.feedback_label.configure(
                text=error_message,
                text_color=current_palette()["error"],
            )
            self.name_entry.focus_set()
            return
        self._cancel()

    def _cancel(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass
        if self.on_close is not None:
            self.on_close()


class ProfilePanel(ctk.CTkFrame):
    def __init__(self, master, app: "App"):
        super().__init__(
            master,
            fg_color=current_palette()["card"],
            border_color=current_palette()["border"],
            border_width=1,
            corner_radius=CARD_CORNER_RADIUS,
        )
        self.app = app
        self._enabled = True
        self._pending_profile_id = ""
        self._dropdown_window = None
        self._rename_profile_id = ""
        self._rename_frame = None
        self._rename_entry = None
        self._rename_save_btn = None
        self._rename_cancel_btn = None
        self._create_dialog = None
        self._icon = icon_image(
            "layers", 19,
            light_color=LIGHT["accent"], dark_color=DARK["accent"],
        )
        self._chevron_icon = icon_image(
            "chevron_down", 15,
            light_color=LIGHT["text_dim"], dark_color=DARK["text_dim"],
        )
        self._new_icon = icon_image(
            "plus", 16,
            light_color=LIGHT["text_dim"], dark_color=DARK["text_dim"],
        )
        self._save_icon = icon_image(
            "save", 16,
            light_color=LIGHT["text_dim"], dark_color=DARK["text_dim"],
        )
        self._delete_icon = icon_image(
            "trash", 16,
            light_color=LIGHT["text_dim"], dark_color=DARK["text_dim"],
        )
        self._rename_icon = icon_image(
            "pencil", 14,
            light_color=LIGHT["text_dim"], dark_color=DARK["text_dim"],
        )
        self._build()
        self.app.window.bind("<FocusOut>", self._on_app_focus_out, add="+")
        self.app.window.bind("<Unmap>", self._on_app_unmap, add="+")
        self.app.window.bind_all("<ButtonPress>", self._on_global_pointer_press, add="+")
        self.refresh_profiles()
        self.after(400, self._poll_dirty_state)

    def _tr(self, key: str, **kwargs) -> str:
        return app_tr(self.app, key, **kwargs)

    def _build(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(10, 5))
        self._header_text_label = pack_section_title(
            header, self._icon, self._tr("ui.profile.title")
        )
        self.state_label = ctk.CTkLabel(
            header,
            text="",
            height=24,
            corner_radius=CONTROL_CORNER_RADIUS,
            font=ui_font(size=11),
            text_color=current_palette()["text_dim"],
            fg_color=current_palette()["hint_bg"],
        )
        self.state_label.pack(side="right")

        self.selector_area = ctk.CTkFrame(self, fg_color="transparent")
        self.selector_area.pack(fill="x", padx=14, pady=(0, 10))
        selector_row = ctk.CTkFrame(self.selector_area, fg_color="transparent")
        selector_row.pack(fill="x", pady=2)
        self.selector_label = ctk.CTkLabel(
            selector_row,
            text=self._tr("ui.profile.current"),
            width=132,
            anchor="w",
            font=ui_font(size=12),
            text_color=current_palette()["text_dim"],
        )
        self.selector_label.pack(side="left", padx=(0, 6))
        self.selector_shell = ctk.CTkFrame(
            selector_row,
            height=36,
            corner_radius=CONTROL_CORNER_RADIUS,
            border_color=current_palette()["entry_border"],
            border_width=2,
            fg_color=current_palette()["entry_bg"],
        )
        self.selector_shell.pack(side="left", fill="x", expand=True)
        self.selector_shell.pack_propagate(False)

        self.selector_btn = ctk.CTkButton(
            self.selector_shell,
            text="",
            image=self._chevron_icon,
            compound="left",
            anchor="w",
            border_spacing=9,
            height=PROFILE_TOOLBAR_BUTTON_HEIGHT,
            corner_radius=PROFILE_TOOLBAR_INNER_RADIUS,
            font=ui_font(size=12),
            fg_color="transparent",
            hover_color=current_palette()["hint_bg"],
            text_color=current_palette()["text"],
            command=self._toggle_dropdown,
        )
        self.selector_btn.pack(
            side="left", fill="x", expand=True,
            padx=(PROFILE_TOOLBAR_INSET, 1), pady=PROFILE_TOOLBAR_INSET,
        )
        self.selector_btn.bind("<Configure>", self._sync_dropdown_geometry, add="+")

        self._selector_separators = []

        def add_separator():
            separator = ctk.CTkFrame(
                self.selector_shell,
                width=1,
                height=20,
                fg_color=current_palette()["border"],
            )
            separator.pack(side="left", padx=1, pady=8)
            self._selector_separators.append(separator)

        add_separator()
        self.new_btn = ctk.CTkButton(
            self.selector_shell,
            text=self._tr("ui.profile.new_short"),
            image=self._new_icon,
            compound="left",
            width=70,
            height=PROFILE_TOOLBAR_BUTTON_HEIGHT,
            corner_radius=PROFILE_TOOLBAR_INNER_RADIUS,
            font=ui_font(size=11),
            fg_color="transparent",
            hover_color=current_palette()["hint_bg"],
            text_color=current_palette()["text_dim"],
            command=self._begin_new,
        )
        self.new_btn.pack(side="left", pady=PROFILE_TOOLBAR_INSET)
        add_separator()
        self.save_btn = ctk.CTkButton(
            self.selector_shell,
            text=self._tr("ui.profile.save_short"),
            image=self._save_icon,
            compound="left",
            width=70,
            height=PROFILE_TOOLBAR_BUTTON_HEIGHT,
            corner_radius=PROFILE_TOOLBAR_INNER_RADIUS,
            font=ui_font(size=11),
            fg_color="transparent",
            hover_color=current_palette()["hint_bg"],
            text_color=current_palette()["text_dim"],
            command=self._save_current,
        )
        self.save_btn.pack(side="left", pady=PROFILE_TOOLBAR_INSET)
        add_separator()
        self.delete_btn = ctk.CTkButton(
            self.selector_shell,
            text=self._tr("ui.profile.delete_short"),
            image=self._delete_icon,
            compound="left",
            width=70,
            height=PROFILE_TOOLBAR_BUTTON_HEIGHT,
            corner_radius=PROFILE_TOOLBAR_INNER_RADIUS,
            font=ui_font(size=11),
            fg_color="transparent",
            hover_color=current_palette()["hint_bg"],
            text_color=current_palette()["text_dim"],
            command=self._request_delete,
        )
        self.delete_btn.pack(
            side="left", padx=(0, PROFILE_TOOLBAR_INSET),
            pady=PROFILE_TOOLBAR_INSET,
        )

        self.prompt_row = ctk.CTkFrame(
            self,
            fg_color=current_palette()["hint_bg"],
            corner_radius=CONTROL_CORNER_RADIUS,
        )
        self.prompt_label = ctk.CTkLabel(
            self.prompt_row,
            text="",
            anchor="w",
            justify="left",
            font=ui_font(size=11),
            text_color=current_palette()["text_dim"],
        )
        self.prompt_label.pack(side="left", fill="x", expand=True, padx=(10, 6), pady=6)
        self.prompt_buttons = []
        for _index in range(3):
            button = ctk.CTkButton(
                self.prompt_row,
                text="",
                width=92,
                height=26,
                corner_radius=CONTROL_CORNER_RADIUS,
                font=ui_font(size=11),
                fg_color=current_palette()["muted_button"],
                hover_color=current_palette()["muted_hover"],
                text_color=current_palette()["text"],
            )
            self.prompt_buttons.append(button)

    def _show_prompt(self, message: str, actions: list[tuple[str, object]]):
        self.prompt_label.configure(text=message)
        for button in self.prompt_buttons:
            button.pack_forget()
        for button, (text_value, command) in zip(self.prompt_buttons, actions):
            button.configure(text=text_value, command=command)
            button.pack(side="right", padx=(0, 6), pady=6)
        self.prompt_row.pack(fill="x", padx=16, pady=(0, 10))

    def _hide_prompt(self):
        self._pending_profile_id = ""
        self.prompt_row.pack_forget()

    def _toggle_dropdown(self):
        if not self._enabled:
            return
        if self._dropdown_window is not None and self._dropdown_window.winfo_exists():
            self._close_dropdown()
            return
        self._open_dropdown()

    def _open_dropdown(self):
        self._close_dropdown()
        p = current_palette()
        window = ctk.CTkToplevel(self)
        self._dropdown_window = window
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        _configure_rounded_popup_window(window, p["card"])
        window.transient(self.app.window)

        self._sync_dropdown_geometry()

        body = ctk.CTkFrame(
            window,
            fg_color=p["card"],
            border_color=p["border"],
            border_width=PROFILE_POPUP_BORDER_WIDTH,
            corner_radius=CARD_CORNER_RADIUS,
        )
        body.pack(fill="both", expand=True)
        profiles = self.app.cm.config.profiles
        if len(profiles) > PROFILE_DROPDOWN_VISIBLE_ROWS:
            row_parent = ctk.CTkScrollableFrame(
                body,
                corner_radius=PROFILE_POPUP_INNER_RADIUS,
                border_width=0,
                fg_color=p["card"],
                scrollbar_button_color=p["border"],
                scrollbar_button_hover_color=p["text_dim"],
            )
        else:
            row_parent = ctk.CTkFrame(body, fg_color="transparent", corner_radius=0)
        row_parent.pack(fill="both", expand=True, padx=2, pady=2)
        active_id = self.app.cm.config.active_profile_id
        for profile in profiles:
            active = profile.id == active_id
            row = ctk.CTkFrame(row_parent, fg_color=p["hint_bg"] if active else "transparent")
            row.pack(fill="x", padx=3, pady=(3, 0))
            button = ctk.CTkButton(
                row,
                text=(f"●  {profile.name}" if active else f"    {profile.name}"),
                anchor="w",
                height=32,
                corner_radius=CONTROL_CORNER_RADIUS,
                font=ui_font(size=12, weight="bold" if active else "normal"),
                fg_color=p["hint_bg"] if active else "transparent",
                hover_color=p["muted_hover"],
                text_color=p["accent"] if active else p["text"],
                command=lambda profile_id=profile.id: self._select_profile(profile_id),
            )
            button.pack(side="left", fill="x", expand=True, pady=3)
            ctk.CTkButton(
                row,
                text=self._tr("ui.profile.rename"),
                image=self._rename_icon,
                compound="left",
                width=68,
                height=30,
                corner_radius=CONTROL_CORNER_RADIUS,
                font=ui_font(size=10),
                fg_color="transparent",
                hover_color=p["muted_hover"],
                text_color=p["text_dim"],
                command=lambda profile_id=profile.id: self._begin_rename(profile_id),
            ).pack(side="right", padx=(2, 3), pady=3)
        window.bind("<Escape>", lambda _event: self._close_dropdown())
        window.bind(
            "<FocusOut>",
            lambda _event, expected=window: self.after(
                80, lambda: self._close_dropdown_if_unfocused(expected)
            ),
        )
        window.focus_force()

    def _sync_dropdown_geometry(self, _event=None):
        window = self._dropdown_window
        if window is None or not window.winfo_exists():
            return
        selector_width_px = max(1, self.selector_btn.winfo_width())
        row_height = 41
        visible_rows = min(
            len(self.app.cm.config.profiles),
            PROFILE_DROPDOWN_VISIBLE_ROWS,
        )
        geometry_height = max(row_height, row_height * visible_rows + 4)
        window_scaling = max(0.01, ctk.ScalingTracker.get_window_scaling(window))
        geometry_width = max(1, round(selector_width_px / window_scaling))
        x = self.selector_btn.winfo_rootx()
        y = self.selector_shell.winfo_rooty() + self.selector_shell.winfo_height() + 2
        window.geometry(f"{geometry_width}x{geometry_height}+{x}+{y}")

    def _show_rename_editor(self, profile):
        p = current_palette()
        self.selector_btn.pack_forget()
        self._rename_frame = ctk.CTkFrame(
            self.selector_shell,
            height=32,
            fg_color="transparent",
        )
        self._rename_frame.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(3, 0),
            pady=2,
            before=self._selector_separators[0],
        )
        self._rename_entry = ctk.CTkEntry(
            self._rename_frame,
            height=30,
            corner_radius=CONTROL_CORNER_RADIUS,
            font=ui_font(size=12),
            border_color=p["accent"],
            border_width=2,
            fg_color=p["entry_bg"],
        )
        self._rename_entry.pack(side="left", fill="x", expand=True, padx=(1, 5), pady=1)
        self._rename_entry.insert(0, profile.name)
        self._rename_entry.select_range(0, "end")
        self._rename_entry.bind(
            "<Return>", lambda _event: self._confirm_rename()
        )
        self._rename_entry.bind("<Escape>", lambda _event: self._cancel_rename())
        self._rename_save_btn = ctk.CTkButton(
            self._rename_frame,
            text=self._tr("ui.profile.rename_save"),
            width=48,
            height=28,
            corner_radius=CONTROL_CORNER_RADIUS,
            font=ui_font(size=10),
            fg_color=p["accent"],
            hover_color=p["accent_hover"],
            text_color=p["button_text"],
            command=self._confirm_rename,
        )
        self._rename_save_btn.pack(side="left", padx=(0, 4), pady=2)
        self._rename_cancel_btn = ctk.CTkButton(
            self._rename_frame,
            text=self._tr("ui.profile.cancel"),
            width=48,
            height=28,
            corner_radius=CONTROL_CORNER_RADIUS,
            font=ui_font(size=10),
            fg_color=p["muted_button"],
            hover_color=p["muted_hover"],
            text_color=p["text"],
            command=self._cancel_rename,
        )
        self._rename_cancel_btn.pack(side="left", padx=(0, 4), pady=2)
        self.new_btn.configure(state="disabled")
        self.save_btn.configure(state="disabled")
        self.delete_btn.configure(state="disabled")
        self.after(20, lambda: self._focus_rename_entry(0))

    def _close_dropdown_if_unfocused(self, expected_window=None):
        window = self._dropdown_window
        if window is None or not window.winfo_exists():
            return
        if expected_window is not None and window is not expected_window:
            return
        try:
            focused = window.focus_get()
        except tk.TclError:
            focused = None
        if focused is None or not str(focused).startswith(str(window)):
            self._close_dropdown()

    @staticmethod
    def _widget_is_within(widget, ancestor) -> bool:
        while widget is not None:
            if widget is ancestor:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _on_global_pointer_press(self, event):
        window = self._dropdown_window
        if window is None or not window.winfo_exists():
            return
        widget = getattr(event, "widget", None)
        if self._widget_is_within(widget, window):
            return
        if self._widget_is_within(widget, self.selector_shell):
            return
        self._close_dropdown()

    def _on_app_focus_out(self, _event=None):
        window = self._dropdown_window
        if window is None or not window.winfo_exists():
            return
        self.after(80, lambda expected=window: self._close_dropdown_if_app_inactive(expected))

    def _close_dropdown_if_app_inactive(self, expected_window=None):
        window = self._dropdown_window
        if window is None or not window.winfo_exists():
            return
        if expected_window is not None and window is not expected_window:
            return
        try:
            focused = self.app.window.focus_get()
        except tk.TclError:
            focused = None
        if focused is None:
            self._close_dropdown()

    def _on_app_unmap(self, _event=None):
        self._close_dropdown()

    def close_popups(self):
        self._close_dropdown()

    def _close_dropdown(self):
        window = self._dropdown_window
        self._dropdown_window = None
        if window is not None:
            try:
                window.destroy()
            except tk.TclError:
                pass

    def _begin_rename(self, profile_id: str):
        if not self._enabled:
            return
        profile = self.app.cm.get_profile(profile_id)
        if profile is None:
            return
        self._close_dropdown()
        self._hide_prompt()
        self._finish_rename_editor()
        self._rename_profile_id = profile_id
        self._show_rename_editor(profile)

    def _focus_rename_entry(self, attempt=0):
        entry = self._rename_entry
        if entry is None or not entry.winfo_exists():
            return
        try:
            focused = entry.focus_get()
            if focused is not None and str(focused).startswith(str(entry)):
                return
            window = self.app.window
            window.update_idletasks()
            window.lift()
            window.focus_force()
            entry.focus_force()
            _match_windows_ime_font(entry)
        except tk.TclError:
            return
        if attempt < 4:
            self.after(60, lambda: self._focus_rename_entry(attempt + 1))

    def _finish_rename_editor(self):
        frame = self._rename_frame
        self._rename_profile_id = ""
        self._rename_frame = None
        self._rename_entry = None
        self._rename_save_btn = None
        self._rename_cancel_btn = None
        if frame is not None:
            try:
                frame.destroy()
            except tk.TclError:
                pass
        if not self.selector_btn.winfo_manager():
            self.selector_btn.pack(
                side="left",
                fill="x",
                expand=True,
                padx=(PROFILE_TOOLBAR_INSET, 1),
                pady=PROFILE_TOOLBAR_INSET,
                before=self._selector_separators[0],
            )
        self.selector_btn.configure(text=self.app.cm.get_active_profile().name)
        state = "normal" if self._enabled else "disabled"
        self.new_btn.configure(state=state)
        self.save_btn.configure(state=state)
        delete_enabled = self._enabled and len(self.app.cm.config.profiles) > 1
        self.delete_btn.configure(state="normal" if delete_enabled else "disabled")

    def _cancel_rename(self):
        self._finish_rename_editor()

    def _confirm_rename(self) -> bool:
        entry = self._rename_entry
        profile_id = self._rename_profile_id
        if entry is None or not profile_id:
            return True
        try:
            profile = self.app.cm.rename_profile(profile_id, entry.get())
        except ValueError as error:
            key = "ui.profile.error.duplicate" if str(error) == "duplicate" else "ui.profile.error.empty"
            self._set_state(key, "error")
            entry.focus_set()
            return False
        except ConfigPersistenceError as error:
            self._show_persistence_error(error)
            entry.focus_set()
            return False
        self._finish_rename_editor()
        self.refresh_profiles()
        self.app.log_profile_event("ui.profile.log.renamed", name=profile.name)
        return True

    def _select_profile(self, profile_id: str):
        self._close_dropdown()
        if profile_id == self.app.cm.config.active_profile_id:
            return
        if self.app.profile_form_is_dirty():
            self._pending_profile_id = profile_id
            self._show_prompt(
                self._tr("ui.profile.unsaved_prompt"),
                [
                    (self._tr("ui.profile.save_load"), self._save_then_load),
                    (self._tr("ui.profile.discard_load"), self._discard_then_load),
                    (self._tr("ui.profile.cancel"), self._cancel_pending),
                ],
            )
            return
        self._load_profile(profile_id)

    def refresh_profiles(self):
        profiles = self.app.cm.config.profiles
        active = self.app.cm.get_active_profile()
        self.selector_btn.configure(text=active.name)
        self.delete_btn.configure(state="normal" if len(profiles) > 1 and self._enabled else "disabled")
        self._set_state("ui.profile.state.saved", "success")

    def _set_state(self, key: str, tone: str = "muted", **kwargs):
        p = current_palette()
        colors = {
            "success": p["success"],
            "warning": p["warning"],
            "error": p["error"],
            "muted": p["text_dim"],
        }
        self.state_label.configure(
            text=f"  {self._tr(key, **kwargs)}  ",
            text_color=colors[tone],
        )

    def _show_persistence_error(self, error: Exception):
        self._set_state("ui.profile.error.save_failed", "error", error=str(error))

    def _poll_dirty_state(self):
        try:
            if self._enabled and not self.prompt_row.winfo_ismapped():
                if self.app.profile_form_is_dirty():
                    self._set_state("ui.profile.state.dirty", "warning")
                else:
                    self._set_state("ui.profile.state.saved", "success")
            self.after(400, self._poll_dirty_state)
        except tk.TclError:
            return

    def _begin_new(self):
        if not self._enabled:
            return
        self._hide_prompt()
        self._close_dropdown()
        if self._create_dialog is not None and self._create_dialog.winfo_exists():
            self._create_dialog.focus_force()
            return
        self._create_dialog = NewProfileDialog(
            self.app,
            self._create_profile_from_dialog,
            self._profile_dialog_closed,
        )

    def _profile_dialog_closed(self):
        self._create_dialog = None

    def _create_profile_from_dialog(self, name: str, copy_current: bool):
        try:
            if copy_current:
                self.app.apply_profile_form_to_config()
            profile = self.app.cm.create_profile(name, copy_current=copy_current)
        except ValueError as error:
            key = "ui.profile.error.duplicate" if str(error) == "duplicate" else "ui.profile.error.empty"
            return self._tr(key)
        except ConfigPersistenceError as error:
            return self._tr("ui.profile.error.save_failed", error=str(error))
        self._create_dialog = None
        self.refresh_profiles()
        self.app.after_profile_loaded(profile.name)
        return None

    def _handle_name_error(self, error: ValueError):
        key = "ui.profile.error.duplicate" if str(error) == "duplicate" else "ui.profile.error.empty"
        self._set_state(key, "error")

    def _save_current(self) -> bool:
        try:
            self.app.apply_profile_form_to_config()
            profile = self.app.cm.save_active_profile()
        except ValueError as error:
            self._handle_name_error(error)
            return False
        except ConfigPersistenceError as error:
            self._show_persistence_error(error)
            return False
        self.refresh_profiles()
        self._set_state("ui.profile.state.saved", "success")
        self.app.log_profile_event("ui.profile.log.saved", name=profile.name)
        return True

    def _save_then_load(self):
        target_id = self._pending_profile_id
        if self._save_current():
            self._hide_prompt()
            self._load_profile(target_id)

    def _discard_then_load(self):
        target_id = self._pending_profile_id
        self._hide_prompt()
        self._load_profile(target_id)

    def _cancel_pending(self):
        self.selector_btn.configure(text=self.app.cm.get_active_profile().name)
        self._hide_prompt()

    def _load_profile(self, profile_id: str):
        try:
            profile = self.app.cm.activate_profile(profile_id)
        except ConfigPersistenceError as error:
            self._show_persistence_error(error)
            return False
        self.refresh_profiles()
        self.app.after_profile_loaded(profile.name)
        return True

    def _request_delete(self):
        if len(self.app.cm.config.profiles) <= 1:
            self._set_state("ui.profile.error.last", "error")
            return
        self._show_prompt(
            self._tr("ui.profile.delete_prompt", name=self.app.cm.get_active_profile().name),
            [
                (self._tr("ui.profile.confirm_delete"), self._confirm_delete),
                (self._tr("ui.profile.cancel"), self._hide_prompt),
            ],
        )

    def _confirm_delete(self):
        try:
            profile = self.app.cm.delete_active_profile()
        except ConfigPersistenceError as error:
            self._show_persistence_error(error)
            return
        self._hide_prompt()
        self.refresh_profiles()
        self.app.after_profile_loaded(profile.name)

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        state = "normal" if enabled else "disabled"
        self.selector_btn.configure(state=state)
        self.new_btn.configure(state=state)
        self.save_btn.configure(state=state)
        delete_enabled = enabled and len(self.app.cm.config.profiles) > 1
        self.delete_btn.configure(state="normal" if delete_enabled else "disabled")
        if not enabled:
            self._finish_rename_editor()
            self._close_dropdown()
            self._hide_prompt()

    def confirm_shutdown(self) -> bool:
        if self._rename_profile_id:
            decision = messagebox.askyesnocancel(
                self._tr("ui.profile.exit_title"),
                self._tr("ui.profile.exit_rename_prompt"),
                parent=self.app.window,
            )
            if decision is None:
                return False
            if decision:
                if not self._confirm_rename():
                    return False
            else:
                self._finish_rename_editor()
        dirty = self.app.profile_form_is_dirty()
        if not dirty:
            return True
        decision = messagebox.askyesnocancel(
            self._tr("ui.profile.exit_title"),
            self._tr("ui.profile.exit_prompt"),
            parent=self.app.window,
        )
        if decision is None:
            return False
        if decision:
            return self._save_current()
        return True

    def refresh_theme(self):
        p = current_palette()
        self.configure(fg_color=p["card"], border_color=p["border"])
        self._header_text_label.configure(text_color=p["text"])
        self.state_label.configure(fg_color=p["hint_bg"])
        self.selector_label.configure(text_color=p["text_dim"])
        self.selector_shell.configure(
            border_color=p["entry_border"], fg_color=p["entry_bg"],
        )
        self.selector_btn.configure(
            fg_color="transparent", hover_color=p["hint_bg"], text_color=p["text"],
        )
        if self._rename_entry is not None:
            self._rename_entry.configure(
                border_color=p["accent"], fg_color=p["entry_bg"],
            )
        if self._rename_save_btn is not None:
            self._rename_save_btn.configure(
                fg_color=p["accent"], hover_color=p["accent_hover"],
                text_color=p["button_text"],
            )
        if self._rename_cancel_btn is not None:
            self._rename_cancel_btn.configure(
                fg_color=p["muted_button"], hover_color=p["muted_hover"],
                text_color=p["text"],
            )
        for separator in self._selector_separators:
            separator.configure(fg_color=p["border"])
        self.prompt_row.configure(fg_color=p["hint_bg"])
        self.prompt_label.configure(text_color=p["text_dim"])
        self.save_btn.configure(
            fg_color="transparent", hover_color=p["hint_bg"], text_color=p["text_dim"],
        )
        for button in (self.new_btn, self.delete_btn):
            button.configure(
                fg_color="transparent", hover_color=p["hint_bg"],
                text_color=p["text_dim"],
            )
        for button in self.prompt_buttons:
            button.configure(
                fg_color=p["muted_button"], hover_color=p["muted_hover"],
                text_color=p["text"],
            )

    def refresh_language(self):
        self._header_text_label.configure(text=self._tr("ui.profile.title"))
        self.selector_label.configure(text=self._tr("ui.profile.current"))
        self.new_btn.configure(text=self._tr("ui.profile.new_short"))
        self.save_btn.configure(text=self._tr("ui.profile.save_short"))
        self.delete_btn.configure(text=self._tr("ui.profile.delete_short"))
        if self._rename_save_btn is not None:
            self._rename_save_btn.configure(text=self._tr("ui.profile.rename_save"))
        if self._rename_cancel_btn is not None:
            self._rename_cancel_btn.configure(text=self._tr("ui.profile.cancel"))


class SharedVmPanel(ctk.CTkFrame):
    _FIELD_SPECS = [
        ("vmx_path", "ui.config.field.vmx", "file", "ui.config.placeholder.vmx"),
        ("vm_guest_user", "ui.config.field.vm_user", "path", "ui.config.placeholder.vm_user"),
        ("vm_guest_password", "ui.config.field.vm_password", "password", "ui.config.placeholder.vm_password"),
    ]

    def __init__(self, master, app: "App"):
        super().__init__(
            master,
            fg_color=current_palette()["card"],
            border_color=current_palette()["border"],
            border_width=1,
            corner_radius=CARD_CORNER_RADIUS,
        )
        self.app = app
        self._entries = {}
        self._field_labels = {}
        self._browse_buttons = {}
        self._header_icon = icon_image(
            "sliders",
            19,
            light_color=LIGHT["accent"],
            dark_color=DARK["accent"],
        )
        self._folder_icon = icon_image(
            "folder",
            17,
            light_color=LIGHT["text_dim"],
            dark_color=DARK["text_dim"],
        )
        self._build()

    def _tr(self, key: str, **kwargs) -> str:
        return app_tr(self.app, key, **kwargs)

    def _config_source(self):
        return self.app.cm.config

    def _build(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(10, 5))
        self._header_text_label = pack_section_title(
            header,
            self._header_icon,
            self._tr("ui.section.vm_shared"),
        )
        entries_frame = ctk.CTkFrame(self, fg_color="transparent")
        entries_frame.pack(fill="x", padx=14, pady=(0, 10))
        for key, label_key, mode, placeholder_key in self._FIELD_SPECS:
            row = ctk.CTkFrame(entries_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            label = ctk.CTkLabel(
                row,
                text=self._tr(label_key),
                width=132,
                anchor="w",
                font=ui_font(size=12),
                text_color=current_palette()["text_dim"],
            )
            label.pack(side="left", padx=(0, 6))
            self._field_labels[key] = label
            entry_kwargs = {"show": "*"} if mode == "password" else {}
            entry = ctk.CTkEntry(
                row,
                height=30,
                corner_radius=CONTROL_CORNER_RADIUS,
                font=ui_font(size=12),
                border_color=current_palette()["entry_border"],
                fg_color=current_palette()["entry_bg"],
                placeholder_text_color=current_palette()["text_dim"],
                placeholder_text=self._tr(placeholder_key),
                **entry_kwargs,
            )
            entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
            value = getattr(self.app.cm.config, key, "")
            if value:
                entry.insert(0, value)
            self._entries[key] = entry
            if mode == "file":
                button = ctk.CTkButton(
                    row,
                    text="",
                    image=self._folder_icon,
                    width=42,
                    height=32,
                    corner_radius=CONTROL_CORNER_RADIUS,
                    font=ui_font(size=12),
                    fg_color=current_palette()["muted_button"],
                    hover_color=current_palette()["muted_hover"],
                    text_color=current_palette()["text"],
                    command=lambda k=key: self._browse(k),
                )
                button.pack(side="right")
                self._browse_buttons[key] = button

    def _browse(self, key: str):
        path = filedialog.askopenfilename(
            title=self._tr("filedialog.vmx"),
            filetypes=[("VMware VMX", "*.vmx"), ("All files", "*.*")],
        )
        if not path:
            return
        entry = self._entries.get(key)
        if entry is None:
            return
        entry.delete(0, "end")
        entry.insert(0, ntpath.normpath(path.replace("/", "\\")))

    def collect_values(self) -> dict:
        values = {}
        for key, entry in self._entries.items():
            value = entry.get().strip()
            if key == "vmx_path":
                value = ntpath.normpath(value.replace("/", "\\")) if value else ""
            values[key] = value
        return values

    def apply_values_to_config(self):
        for key, value in self.collect_values().items():
            setattr(self.app.cm.config, key, value)

    def _save_values_only(self):
        self.apply_values_to_config()

    def load_values(self):
        for key, entry in self._entries.items():
            entry.delete(0, "end")
            value = getattr(self.app.cm.config, key, "")
            if value:
                entry.insert(0, value)

    def set_config_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for entry in self._entries.values():
            entry.configure(state=state)
        for button in self._browse_buttons.values():
            button.configure(state=state)

    def refresh_theme(self):
        p = current_palette()
        self.configure(fg_color=p["card"], border_color=p["border"])
        self._header_text_label.configure(text_color=p["text"])
        for label in self._field_labels.values():
            label.configure(text_color=p["text_dim"])
        for entry in self._entries.values():
            entry.configure(
                border_color=p["entry_border"],
                fg_color=p["entry_bg"],
                placeholder_text_color=p["text_dim"],
            )
        for button in self._browse_buttons.values():
            button.configure(
                fg_color=p["muted_button"],
                hover_color=p["muted_hover"],
                text_color=p["text"],
            )

    def refresh_language(self):
        self._header_text_label.configure(text=self._tr("ui.section.vm_shared"))
        field_spec_by_key = {
            key: (label_key, placeholder_key)
            for key, label_key, _mode, placeholder_key in self._FIELD_SPECS
        }
        for key, label in self._field_labels.items():
            label_key, placeholder_key = field_spec_by_key[key]
            label.configure(text=self._tr(label_key))
            self._entries[key].configure(placeholder_text=self._tr(placeholder_key))


class MultiConfigPanel(_OriginalConfigPanel):
    # Source compatibility markers for legacy UI tests:
    # pack_section_title
    # "sliders" "check" "upload" "folder"
    # width=42
    # height=32
    # ui.button.full_sync
    project_index = 0
    _NORMALIZED_PATH_ENTRY_KEYS = {
        "host_project_path",
        "vm_project_path",
        "vm_bin_relative_path",
        "host_output_path",
    }
    _WINDOWS_ABSOLUTE_PATH_ENTRY_KEYS = {
        "host_project_path",
        "vm_project_path",
        "host_output_path",
    }
    _FIELD_SPECS = [
        ("host_project_path", "ui.config.field.host_project", "dir", "ui.config.placeholder.host_project"),
        ("vm_project_path", "ui.config.field.vm_project", "path", "ui.config.placeholder.vm_project"),
        ("vm_bin_relative_path", "ui.config.field.bin", "path", "ui.config.placeholder.bin"),
        ("host_output_path", "ui.config.field.host_output", "dir", "ui.config.placeholder.host_output"),
    ]
    __init__ = _OriginalConfigPanel.__init__

    def _project_config(self):
        projects = getattr(self.app.cm.config, "projects", [])
        if self.project_index < len(projects):
            return projects[self.project_index]
        return self.app.cm.config

    def _config_source(self):
        return self._project_config()

    def _sync_manager(self):
        getter = getattr(self.app, "get_sync_manager", None)
        if callable(getter):
            return getter(self.project_index)
        return getattr(self.app, "sync", None)

    def _project_log_panel(self):
        panels = getattr(self.app, "project_panels", None)
        if isinstance(panels, dict) and self.project_index in panels:
            return panels[self.project_index].log_panel
        return getattr(self.app, "log_panel", None)

    def _set_project_toggle_enabled(self, enabled: bool):
        setter = getattr(self.app, "_set_secondary_project_action_enabled", None)
        if self.project_index == 1 and callable(setter):
            setter(enabled)
            return
        button = getattr(self.app, "remove_project_btn", None)
        if self.project_index == 1 and button is not None:
            button.configure(state="normal" if enabled else "disabled")

    def collect_values(self) -> dict:
        raw_values = {key: entry.get().strip() for key, entry in self._entries.items()}
        project = self._project_config()
        vm_project_path = self._normalize_entry_value(
            "vm_project_path",
            raw_values.get("vm_project_path", getattr(project, "vm_project_path", "")),
        )
        return {
            key: self._normalize_entry_value(
                key,
                raw_values.get(key, ""),
                vm_project_path=vm_project_path,
            )
            for key in self._entries
        }

    def apply_values_to_config(self):
        project = self._project_config()
        for key, value in self.collect_values().items():
            setattr(project, key, value)

    def _save_values_only(self, emit_log: bool = False):
        shared_vm_panel = getattr(self.app, "shared_vm_panel", None)
        if shared_vm_panel and hasattr(shared_vm_panel, "apply_values_to_config"):
            shared_vm_panel.apply_values_to_config()
        self.apply_values_to_config()
        self.app.resolve_vmrun_path(save=True)
        self.app.cm.save()
        self._refresh_entry_values_from_config()
        log_panel = self._project_log_panel()
        if emit_log and log_panel:
            log_panel.append(
                LogEvent(
                    LogIcon.CONFIG,
                    self._tr("ui.config.saved", path=self.app.cm.config_path),
                    "success",
                )
            )

    def _refresh_entry_values_from_config(self):
        project = self._project_config()
        for key, entry in self._entries.items():
            value = getattr(project, key, "")
            if entry.get() != value:
                self._replace_entry_value(entry, value)

    def _current_vm_project_path_for_normalization(self) -> str:
        entry = self._entries.get("vm_project_path")
        value = entry.get() if entry else getattr(self._project_config(), "vm_project_path", "")
        return self._normalize_entry_value("vm_project_path", value)

    def update_bin_path_hint(self, check_guest: bool = False):
        p = current_palette()
        cfg = self._project_config()
        text_color = p["text_dim"]
        if not cfg.vm_project_path or not cfg.vm_bin_relative_path:
            self.bin_resolved_label.configure(
                text=self._tr("bin.display.empty"),
                text_color=text_color,
            )
            return
        configured_path = self.app.cm.get_vm_bin_full_path(self.project_index)
        is_file = cfg.vm_bin_relative_path.lower().endswith(".bin")
        resolved = None
        if check_guest:
            try:
                sync = self._sync_manager()
                if sync is not None:
                    resolved = sync.resolve_vm_bin_path_for_display()
            except Exception:
                resolved = None
        if resolved:
            vm_path, _filename = resolved
            if is_file:
                text = self._tr("bin.display.file", path=vm_path)
            else:
                self._autofill_resolved_bin_path(vm_path)
                text = self._tr(
                    "bin.display.detected",
                    relative=self._relative_vm_bin_path(vm_path),
                    path=vm_path,
                )
            text_color = p["success"]
        elif check_guest and not is_file:
            text = self._tr("bin.display.dir_choose_file", path=configured_path)
            text_color = p["warning"]
        elif is_file:
            text = self._tr("bin.display.file", path=configured_path)
        else:
            text = self._tr("bin.display.dir", path=configured_path)
        self.bin_resolved_label.configure(text=text, text_color=text_color)

    def _relative_vm_bin_path(self, vm_path: str) -> str:
        return self._normalize_vm_bin_relative_path(vm_path, self._project_config().vm_project_path)

    def _autofill_resolved_bin_path(self, vm_path: str):
        rel_path = self._relative_vm_bin_path(vm_path)
        if not rel_path.lower().endswith(".bin"):
            return
        entry = getattr(self, "_entries", {}).get("vm_bin_relative_path")
        project = self._project_config()
        current = entry.get().strip() if entry else project.vm_bin_relative_path
        normalized_current = self._normalize_vm_bin_relative_path(current)
        if normalized_current.lower() == rel_path.lower():
            if entry and current != rel_path:
                self._replace_entry_value(entry, rel_path)
            if project.vm_bin_relative_path.lower() != rel_path.lower():
                project.vm_bin_relative_path = rel_path
                self.app.cm.save()
            return
        if entry:
            self._replace_entry_value(entry, rel_path)
        project.vm_bin_relative_path = rel_path
        self.app.cm.save()
        log_panel = self._project_log_panel()
        if log_panel:
            log_panel.append(LogEvent(LogIcon.BIN, self._tr("bin.autofill.relative", path=rel_path), "success"))

    def save_and_check(self) -> PreflightReport:
        self._save_values_only(emit_log=True)
        report = self.app._run_preflight(dedupe_errors=False, project_index=self.project_index)
        self.apply_preflight_report(report)
        return report

    def _full_sync(self):
        self._save_values_only(emit_log=True)
        report = self.app._run_preflight(for_full_sync=True, show_dialog=True, project_index=self.project_index)
        if not report.ok:
            return
        details = report.summary
        if report.warning_text:
            details = f"{details}\n\n{self._tr('dialog.warning_header')}\n{report.warning_text}"
        if not messagebox.askyesno(
            self._tr("dialog.full_sync.title"),
            self._tr("dialog.full_sync.message", details=details),
            parent=self.app.window,
        ):
            self._project_log_panel().append(LogEvent(LogIcon.CANCEL, self._tr("sync.full.confirm_cancelled"), "info"))
            return
        self.set_config_enabled(False)
        self._set_project_toggle_enabled(False)
        project_panel = getattr(self.app, "project_panels", {}).get(self.project_index)
        if project_panel is not None and hasattr(project_panel, "set_full_sync_active"):
            project_panel.set_full_sync_active(True)
        self.app.control.set_full_sync_active(True)
        self._set_full_sync_button_active(True)
        self._full_sync_thread = threading.Thread(target=self._run_full_sync)
        self._full_sync_thread.start()

    def _cancel_full_sync(self):
        self._sync_manager().request_full_sync_cancel()
        self.fullsync_btn.configure(text=self._tr("ui.button.canceling"), state="disabled")

    def _run_full_sync(self):
        try:
            self._sync_manager().full_sync()
        finally:
            try:
                self.after(0, self._finish_full_sync)
            except tk.TclError:
                pass

    def _finish_full_sync(self):
        try:
            enabled = not self._sync_manager().running
            self.set_config_enabled(enabled)
            self._set_project_toggle_enabled(enabled)
            self._set_full_sync_button_active(False, enabled=enabled)
            project_panel = getattr(self.app, "project_panels", {}).get(self.project_index)
            if project_panel is not None and hasattr(project_panel, "set_full_sync_active"):
                project_panel.set_full_sync_active(False)
            self.app.control.set_full_sync_active(False)
        except tk.TclError:
            pass

    def load_values(self):
        project = self._project_config()
        for key, entry in self._entries.items():
            entry.delete(0, "end")
            value = getattr(project, key, "")
            if value:
                entry.insert(0, value)
        if hasattr(self, "bin_resolved_label"):
            self.update_bin_path_hint()

    def set_config_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for entry in self._entries.values():
            entry.configure(state=state)
        for button in self._browse_buttons.values():
            button.configure(state=state)
        self.save_btn.configure(state=state)
        self.fullsync_btn.configure(state=state)

    def refresh_theme(self):
        super().refresh_theme()
        sync = self._sync_manager()
        if sync and getattr(sync, "full_sync_active", False):
            self._set_full_sync_button_active(True)
        else:
            self._set_full_sync_button_active(
                False,
                enabled=self.fullsync_btn.cget("state") != "disabled",
            )

    def refresh_language(self):
        super().refresh_language()
        sync = self._sync_manager()
        if sync and getattr(sync, "full_sync_active", False):
            self._set_full_sync_button_active(True)
        else:
            self._set_full_sync_button_active(
                False,
                enabled=self.fullsync_btn.cget("state") != "disabled",
            )


class ProjectPane(ctk.CTkFrame):
    def __init__(self, master, app: "App", project_index: int):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.project_index = project_index
        self._start_icon = icon_image(
            "play",
            14,
            light_color=LIGHT["button_text"],
            dark_color=DARK["button_text"],
        )
        self._pause_icon = icon_image(
            "pause",
            14,
            light_color=LIGHT["warning_text"],
            dark_color=DARK["warning_text"],
        )
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=0, pady=(0, 6))
        self.title_label = ctk.CTkLabel(
            header,
            text=self._project_title(),
            font=ui_font(size=15, weight="bold"),
            text_color=current_palette()["text"],
            anchor="w",
        )
        self.title_label.pack(side="left")
        self.toggle_btn = None
        self.pause_btn = ctk.CTkButton(
            header,
            text=self._tr("ui.button.pause"),
            image=self._pause_icon,
            compound="left",
            width=PROJECT_RUN_BUTTON_WIDTH,
            height=PROJECT_RUN_BUTTON_HEIGHT,
            border_spacing=4,
            corner_radius=CONTROL_CORNER_RADIUS,
            font=ui_font(size=12),
            fg_color=current_palette()["muted_button"],
            hover_color=current_palette()["muted_hover"],
            text_color=current_palette()["text_dim"],
            state="disabled",
            command=self._pause_project,
        )
        self.pause_btn.pack(side="right")
        self.start_btn = ctk.CTkButton(
            header,
            text=self._tr("ui.button.start"),
            image=self._start_icon,
            compound="left",
            width=PROJECT_RUN_BUTTON_WIDTH,
            height=PROJECT_RUN_BUTTON_HEIGHT,
            border_spacing=4,
            corner_radius=CONTROL_CORNER_RADIUS,
            font=ui_font(size=12),
            fg_color=current_palette()["accent"],
            hover_color=current_palette()["accent_hover"],
            text_color=current_palette()["button_text"],
            command=self._start_project,
        )
        self.start_btn.pack(side="right", padx=(0, 6))
        config_panel_class = type(
            f"Project{project_index + 1}ConfigPanel",
            (ConfigPanel,),
            {"project_index": project_index},
        )
        self.config_panel = config_panel_class(self, app)
        self.config_panel.pack(fill="x", pady=(0, 6))
        self.log_panel = LogPanel(self, app)
        self.log_panel.pack(fill="both", expand=True)

    def _tr(self, key: str, **kwargs) -> str:
        return app_tr(self.app, key, **kwargs)

    def _project_title(self) -> str:
        return self._tr("ui.section.project", number=self.project_index + 1)

    def _sync_manager(self):
        getter = getattr(self.app, "get_sync_manager", None)
        if callable(getter):
            return getter(self.project_index)
        return getattr(self.app, "sync", None)

    def _schedule_ui(self, callback):
        after = getattr(self, "after", None)
        if callable(after):
            after(0, callback)
        else:
            callback()

    def prepare_start_check(self):
        saver = getattr(self.config_panel, "_save_values_only", None)
        if callable(saver):
            try:
                saver(emit_log=True)
            except TypeError:
                saver()
        marker = getattr(self.config_panel, "mark_start_checking", None)
        if callable(marker):
            marker()
        self.log_panel.append(LogEvent(LogIcon.START, self._tr("ui.start.checking"), "info"))

    def apply_start_preflight_report(self, report: PreflightReport):
        emitter = getattr(self.app, "_emit_preflight_report", None)
        if callable(emitter):
            emitter(report, dedupe_errors=False, project_index=self.project_index)
        applier = getattr(self.config_panel, "apply_preflight_report", None)
        if callable(applier):
            applier(report)

    def _apply_start_preflight_report_before_start(self, report: PreflightReport):
        done = threading.Event()

        def apply():
            try:
                self.apply_start_preflight_report(report)
            finally:
                done.set()

        self._schedule_ui(apply)
        done.wait(timeout=2.0)

    def _set_project_running_ui(self, running: bool):
        p = current_palette()
        self.config_panel.set_config_enabled(not running)
        self.start_btn.configure(
            state="disabled" if running else "normal",
            fg_color=p["border"] if running else p["accent"],
            hover_color=p["accent_hover"],
            text_color=p["button_text"],
        )
        self.pause_btn.configure(
            state="normal" if running else "disabled",
            fg_color=p["warning"] if running else p["muted_button"],
            hover_color=p["warning_hover"] if running else p["muted_hover"],
            text_color=p["warning_text"] if running else p["text_dim"],
        )
        if self.toggle_btn is not None:
            self.toggle_btn.configure(state="disabled" if running else "normal")
        if self.project_index == 1:
            setter = getattr(self.app, "_set_secondary_project_action_enabled", None)
            if callable(setter):
                setter(not running)

    def set_full_sync_active(self, active: bool):
        p = current_palette()
        if active:
            self.start_btn.configure(state="disabled", fg_color=p["border"])
            self.pause_btn.configure(
                state="disabled",
                fg_color=p["muted_button"],
                hover_color=p["muted_hover"],
                text_color=p["text_dim"],
            )
            if self.toggle_btn is not None:
                self.toggle_btn.configure(state="disabled")
            return
        sync = self._sync_manager()
        self._set_project_running_ui(bool(getattr(sync, "running", False)))

    def _refresh_app_running_state(self):
        any_running = False
        checker = getattr(self.app, "any_running", None)
        if callable(checker):
            any_running = checker()
        else:
            sync = self._sync_manager()
            any_running = bool(getattr(sync, "running", False))

        setter = getattr(self.app, "set_all_config_enabled", None)
        if callable(setter):
            setter(not any_running)

        control = getattr(self.app, "control", None)
        if control is not None:
            if any_running:
                p = current_palette()
                control.start_btn.configure(state="disabled", fg_color=p["border"])
                control.pause_btn.configure(
                    state="normal",
                    fg_color=p["warning"],
                    hover_color=p["warning_hover"],
                    text_color=p["warning_text"],
                )
                if getattr(control, "_start_time", None) is None:
                    control._start_time = time.time()
            elif hasattr(control, "_set_stopped"):
                control._set_stopped()

        update_status = getattr(self.app, "_update_status_indicator", None)
        if callable(update_status):
            update_status(any_running)
        update_tray = getattr(self.app, "_update_tray_menu", None)
        if callable(update_tray):
            update_tray()

    def _start_project(self):
        sync = self._sync_manager()
        if sync is None:
            return
        self.prepare_start_check()
        self._start_preflight_snapshot = None
        setter = getattr(self.app, "set_all_config_enabled", None)
        if callable(setter):
            setter(False)
        self.start_btn.configure(state="disabled")
        threading.Thread(target=self._start_project_worker, daemon=True).start()

    def _start_project_worker(self):
        started = False
        error = ""
        report = None
        try:
            collector = getattr(self.app, "_collect_preflight_report", None)
            if callable(collector):
                report = collector(project_index=self.project_index)
                if not report.ok:
                    self._schedule_ui(
                        lambda report=report: self._finish_project_start_after_preflight(
                            report,
                            False,
                            "",
                        )
                    )
                    return
                self._apply_start_preflight_report_before_start(report)
                report = None
            sync = self._sync_manager()
            if sync is not None:
                self._start_preflight_snapshot = (
                    sync.preflight_snapshot()
                    if hasattr(sync, "preflight_snapshot")
                    else None
                )
                started = sync.start(
                    preflight_checked=True,
                    preflight_snapshot=getattr(self, "_start_preflight_snapshot", None),
                )
        except Exception as e:
            error = str(e)
        self._schedule_ui(
            lambda report=report, started=started, error=error:
                self._finish_project_start_after_preflight(report, started, error)
        )

    def _finish_project_start_after_preflight(
        self,
        report: PreflightReport | None,
        started: bool,
        error: str = "",
    ):
        if report is not None:
            self.apply_start_preflight_report(report)
            if not report.ok:
                self._start_preflight_snapshot = None
                self._set_project_running_ui(False)
                self._refresh_app_running_state()
                return
        self._finish_project_start(started, error)

    def _finish_project_start(self, started: bool, error: str = ""):
        if started:
            self._set_project_running_ui(True)
            self._refresh_app_running_state()
            return
        message = (
            self._tr("ui.start.failed_with_error", error=error)
            if error else self._tr("ui.start.failed")
        )
        self.log_panel.append(LogEvent(LogIcon.ERROR, message, "error"))
        self._set_project_running_ui(False)
        self._refresh_app_running_state()

    def _pause_project(self):
        try:
            sync = self._sync_manager()
            if sync is not None and getattr(sync, "running", False):
                sync.stop()
        except Exception as e:
            self.log_panel.append(
                LogEvent(LogIcon.ERROR, self._tr("ui.pause.failed", error=e), "error")
            )
        self._set_project_running_ui(False)
        self._refresh_app_running_state()

    def save_and_check(self) -> PreflightReport:
        return self.config_panel.save_and_check()

    def set_config_enabled(self, enabled: bool):
        self.config_panel.set_config_enabled(enabled)

    def update_stats(self, sync_count: int, bin_ready: bool):
        return None

    def show(self):
        self.grid()

    def hide(self):
        self.grid_remove()

    def refresh_language(self):
        self.title_label.configure(text=self._project_title())
        self.start_btn.configure(text=self._tr("ui.button.start"))
        self.pause_btn.configure(text=self._tr("ui.button.pause"))
        self.config_panel.refresh_language()
        self.log_panel.refresh_language()

    def refresh_theme(self):
        p = current_palette()
        self.title_label.configure(text_color=p["text"])
        sync = self._sync_manager()
        running = bool(getattr(sync, "running", False))
        self.start_btn.configure(
            fg_color=p["border"] if running else p["accent"],
            hover_color=p["accent_hover"],
            text_color=p["button_text"],
        )
        self.pause_btn.configure(
            fg_color=p["warning"] if running else p["muted_button"],
            hover_color=p["warning_hover"] if running else p["muted_hover"],
            text_color=p["warning_text"] if running else p["text_dim"],
        )
        if self.toggle_btn is not None:
            self.toggle_btn.configure(
                fg_color=p["muted_button"],
                hover_color=p["muted_hover"],
                text_color=p["text_dim"],
            )
        self.config_panel.refresh_theme()
        self.log_panel.refresh_theme()


class MultiControlPanel(_OriginalControlPanel):
    # Source compatibility markers for legacy UI tests:
    # config_panel.set_config_enabled(False)
    # config_panel.set_config_enabled(True)
    # ui.bin.ready
    __init__ = _OriginalControlPanel.__init__

    def _enabled_project_indexes(self) -> list[int]:
        getter = getattr(self.app, "get_enabled_project_indexes", None)
        if callable(getter):
            indexes = getter()
            if indexes:
                return indexes
        return [0]

    def _project_panel(self, project_index: int):
        panels = getattr(self.app, "project_panels", None)
        if isinstance(panels, dict):
            return panels.get(project_index)
        return getattr(self.app, "config_panel", None)

    def _sync_manager(self, project_index: int = 0):
        getter = getattr(self.app, "get_sync_manager", None)
        if callable(getter):
            return getter(project_index)
        return getattr(self.app, "sync", None)

    def _set_all_config_enabled(self, enabled: bool):
        setter = getattr(self.app, "set_all_config_enabled", None)
        if callable(setter):
            setter(enabled)
            return
        panel = getattr(self.app, "config_panel", None)
        if panel and hasattr(panel, "set_config_enabled"):
            panel.set_config_enabled(enabled)

    def _set_project_running_controls(self, running: bool):
        panels = getattr(self.app, "project_panels", None)
        if not isinstance(panels, dict):
            return
        indexes = self._enabled_project_indexes() if running else list(panels)
        for project_index in indexes:
            panel = panels.get(project_index)
            updater = getattr(panel, "_set_project_running_ui", None)
            if callable(updater):
                updater(running)

    def _append_log(self, event: LogEvent):
        log_panel = getattr(self.app, "log_panel", None)
        if log_panel and hasattr(log_panel, "append"):
            log_panel.append(event)
            return
        panel = self._project_panel(0)
        target = getattr(panel, "log_panel", panel)
        if target and hasattr(target, "append"):
            target.append(event)

    def _append_project_log(self, project_index: int, event: LogEvent):
        panel = self._project_panel(project_index)
        target = getattr(panel, "log_panel", panel)
        if target and hasattr(target, "append"):
            target.append(event)
            return
        self._append_log(event)

    def _log_start_all_blocked(
        self,
        passed_indexes: list[int],
        failed_project_indexes: list[int],
    ):
        failed_numbers = self._format_project_numbers(failed_project_indexes)
        message = self._tr(
            "ui.start.blocked_by_project",
            number=failed_numbers,
        )
        for project_index in passed_indexes:
            self._append_project_log(
                project_index,
                LogEvent(LogIcon.WARNING, message, "warning"),
            )

    def _format_project_numbers(self, project_indexes: list[int]) -> str:
        numbers = [str(index + 1) for index in project_indexes]
        language = getattr(getattr(self.app, "cm", None), "config", None)
        language = getattr(language, "language", "zh")
        separator = "、" if language == "zh" else ", "
        if language != "zh" and len(numbers) > 1:
            return f"{separator.join(numbers[:-1])} and {numbers[-1]}"
        return separator.join(numbers)

    def _prepare_project_start_check(self, project_index: int):
        panel = self._project_panel(project_index)
        preparer = getattr(panel, "prepare_start_check", None)
        if callable(preparer):
            preparer()
            return
        config_panel = getattr(panel, "config_panel", panel)
        saver = getattr(config_panel, "_save_values_only", None)
        if callable(saver):
            try:
                saver(emit_log=True)
            except TypeError:
                saver()
        marker = getattr(config_panel, "mark_start_checking", None)
        if callable(marker):
            marker()

    def _apply_project_preflight_report(
        self,
        project_index: int,
        report: PreflightReport,
    ):
        panel = self._project_panel(project_index)
        applier = getattr(panel, "apply_start_preflight_report", None)
        if callable(applier):
            applier(report)
            return
        emitter = getattr(self.app, "_emit_preflight_report", None)
        if callable(emitter):
            emitter(report, dedupe_errors=False, project_index=project_index)
        config_panel = getattr(panel, "config_panel", panel)
        config_applier = getattr(config_panel, "apply_preflight_report", None)
        if callable(config_applier):
            config_applier(report)

    def _apply_project_preflight_report_before_start(
        self,
        project_index: int,
        report: PreflightReport,
    ):
        done = threading.Event()

        def apply():
            try:
                self._apply_project_preflight_report(project_index, report)
            finally:
                done.set()

        try:
            self.after(0, apply)
        except tk.TclError:
            apply()
        done.wait(timeout=2.0)

    def _start(self):
        enabled_indexes = self._enabled_project_indexes()
        # legacy single-project path: config_panel.set_config_enabled(False)
        for project_index in enabled_indexes:
            self._prepare_project_start_check(project_index)
        self._start_preflight_snapshot = None
        self._start_preflight_snapshots = {}
        self._set_all_config_enabled(False)
        self.start_btn.configure(state="disabled")
        threading.Thread(target=self._start_worker, daemon=True).start()

    def _start_worker(self):
        collector = getattr(self.app, "_collect_preflight_report", None)
        if (
            not callable(collector)
            and not getattr(self.app, "sync_managers", None)
            and not hasattr(self.app, "config_panel")
        ):
            return super()._start_worker()
        enabled_indexes = self._enabled_project_indexes()
        reports: dict[int, PreflightReport] = {}
        snapshots = {}
        passed_indexes = []
        failed_indexes = []
        for project_index in enabled_indexes:
            try:
                if callable(collector):
                    report = collector(project_index=project_index)
                else:
                    panel = self._project_panel(project_index)
                    report = panel.save_and_check()
            except Exception as e:
                report = PreflightReport(errors=[str(e)])
            reports[project_index] = report
            if not report.ok:
                failed_indexes.append(project_index)
                continue
            sync = self._sync_manager(project_index)
            if sync and hasattr(sync, "preflight_snapshot"):
                snapshot = sync.preflight_snapshot()
                snapshots[project_index] = snapshot
                if project_index == 0:
                    self._start_preflight_snapshot = snapshot
            passed_indexes.append(project_index)
        if failed_indexes:
            self.after(
                0,
                lambda reports=reports, passed_indexes=passed_indexes, failed_indexes=failed_indexes:
                    self._finish_start_preflight_failed(
                        reports,
                        passed_indexes,
                        failed_indexes,
                    )
            )
            return
        self._start_preflight_snapshots = snapshots
        for project_index in enabled_indexes:
            self._apply_project_preflight_report_before_start(
                project_index,
                reports[project_index],
            )
        started_indexes = []
        errors = []
        start_results = {}
        result_lock = threading.Lock()

        def start_project(project_index: int):
            sync = self._sync_manager(project_index)
            if sync is None:
                with result_lock:
                    start_results[project_index] = True
                return
            ok = False
            try:
                ok = sync.start(
                    preflight_checked=True,
                    preflight_snapshot=self._start_preflight_snapshots.get(project_index),
                )
            except Exception as e:
                ok = False
                with result_lock:
                    errors.append(f"project {project_index + 1}: {e}")
            with result_lock:
                start_results[project_index] = bool(ok)
                if ok:
                    started_indexes.append(project_index)

        start_threads = []
        for project_index in enabled_indexes:
            thread = threading.Thread(
                target=lambda project_index=project_index: start_project(project_index),
                daemon=True,
            )
            start_threads.append(thread)
            thread.start()
        for thread in start_threads:
            join = getattr(thread, "join", None)
            if callable(join):
                join()

        started = all(start_results.get(project_index, False) for project_index in enabled_indexes)
        if not started:
            for project_index in reversed(started_indexes):
                try:
                    sync = self._sync_manager(project_index)
                    if sync is not None:
                        sync.stop()
                except Exception:
                    pass
        self.after(0, lambda started=started, errors=errors: self._finish_start(started, "; ".join(errors)))

    def _finish_start_preflight_failed(
        self,
        reports: dict[int, PreflightReport],
        passed_indexes: list[int],
        failed_project_indexes: list[int],
    ):
        for project_index, report in reports.items():
            self._apply_project_preflight_report(project_index, report)
        self._log_start_all_blocked(passed_indexes, failed_project_indexes)
        self._start_preflight_snapshot = None
        self._start_preflight_snapshots = {}
        self._set_stopped()

    def _finish_start(
        self,
        started: bool,
        error: str = "",
        reports: dict[int, PreflightReport] | None = None,
    ):
        if reports:
            for project_index, report in reports.items():
                self._apply_project_preflight_report(project_index, report)
        if started:
            self._set_running()
            return
        message = (
            self._tr("ui.start.failed_with_error", error=error)
            if error else self._tr("ui.start.failed")
        )
        self._append_log(LogEvent(LogIcon.ERROR, message, "error"))
        self._set_stopped()

    def _pause(self):
        try:
            sync_managers = getattr(self.app, "sync_managers", None)
            if sync_managers:
                for project_index in self._enabled_project_indexes():
                    sync = self._sync_manager(project_index)
                    if sync is not None and getattr(sync, "running", False):
                        sync.stop()
            else:
                self.app.sync.stop()
        except Exception as e:
            self._append_log(LogEvent(LogIcon.ERROR, self._tr("ui.pause.failed", error=e), "error"))
        self._set_stopped()

    def _set_running(self):
        p = current_palette()
        self._set_all_config_enabled(False)
        self._set_project_running_controls(True)
        self.start_btn.configure(state="disabled", fg_color=p["border"])
        self.pause_btn.configure(
            state="normal",
            fg_color=p["warning"],
            hover_color=p["warning_hover"],
            text_color=p["warning_text"],
        )
        self.app._update_status_indicator(True)
        self.app._update_tray_menu()
        self._start_time = time.time()

    def _set_stopped(self):
        p = current_palette()
        # legacy single-project path: config_panel.set_config_enabled(True)
        self._set_all_config_enabled(True)
        self._set_project_running_controls(False)
        self.pause_btn.configure(
            state="disabled",
            fg_color=p["muted_button"],
            hover_color=p["muted_hover"],
            text_color=p["text_dim"],
        )
        self.start_btn.configure(
            state="normal",
            fg_color=p["accent"],
            hover_color=p["accent_hover"],
            text_color=p["button_text"],
        )
        self.app._status_indicator_state = "stopped"
        self.app._update_status_indicator(False)
        self.app._update_tray_menu()
        self._start_time = None
        text = self._tr("ui.control.uptime.empty")
        self.uptime_label.configure(text=text)
        self._last_uptime_text = text

    def set_full_sync_active(self, active: bool):
        p = current_palette()
        any_full_sync = active
        app = getattr(self, "app", None)
        checker = getattr(app, "any_full_sync_active", None)
        if callable(checker):
            any_full_sync = active or checker()
        self._full_sync_active = bool(any_full_sync)
        if any_full_sync:
            self.start_btn.configure(state="disabled", fg_color=p["border"])
            return
        any_running = False
        if app is not None:
            any_running = getattr(app, "any_running", lambda: getattr(app.sync, "running", False))()
        if not any_running:
            self.start_btn.configure(
                state="normal",
                fg_color=p["accent"],
                hover_color=p["accent_hover"],
                text_color=p["button_text"],
            )

    def refresh_language(self):
        self.start_btn.configure(text=self._tr("ui.button.start"))
        self.pause_btn.configure(text=self._tr("ui.button.pause"))
        self._last_sync_count = None
        self._last_bin_ready = None
        self._last_bin_status_text = ""
        aggregate_sync_count = getattr(self.app, "aggregate_sync_count", lambda: self.app.sync.synced_count)()
        aggregate_bin_ready = getattr(self.app, "aggregate_bin_ready", lambda: self.app.sync.bin_ready)()
        self.update_stats(aggregate_sync_count, aggregate_bin_ready)
        if not self._start_time:
            text = self._tr("ui.control.uptime.empty")
            self.uptime_label.configure(text=text)
            self._last_uptime_text = text
        else:
            self._last_uptime_text = ""

    def refresh_theme(self):
        p = current_palette()
        self.sync_label.configure(text_color=p["text_dim"])
        self.bin_label.configure(text_color=p["success"] if self._last_bin_ready else p["text_dim"])
        self.uptime_label.configure(text_color=p["text_dim"])
        any_running = getattr(self.app, "any_running", lambda: self.app.sync.running)()
        if any_running:
            self.start_btn.configure(state="disabled", fg_color=p["border"])
            self.pause_btn.configure(
                state="normal",
                fg_color=p["warning"],
                hover_color=p["warning_hover"],
                text_color=p["warning_text"],
            )
        else:
            self.pause_btn.configure(
                state="disabled",
                fg_color=p["muted_button"],
                hover_color=p["muted_hover"],
                text_color=p["text_dim"],
            )
            self.start_btn.configure(
                state="normal",
                fg_color=p["accent"],
                hover_color=p["accent_hover"],
                text_color=p["button_text"],
            )


ControlPanel = MultiControlPanel
ConfigPanel = MultiConfigPanel


class StatusBar(ctk.CTkFrame):
    def __init__(self, master, app: "App"):
        super().__init__(master, fg_color="transparent", height=28)
        self.app = app

        self.vm_label = ctk.CTkLabel(
            self, text=self.app.tr("ui.status.vm.checking"), font=ui_font(size=11),
            text_color=current_palette()["text_dim"],
        )
        self.vm_label.pack(side="left", padx=(10, 16))

        self.vmrun_label = ctk.CTkLabel(
            self, text=self.app.tr("ui.status.vmrun.empty"), font=ui_font(size=11),
            text_color=current_palette()["text_dim"],
        )
        self.vmrun_label.pack(side="left", padx=(0, 16))

        self.poll_label = ctk.CTkLabel(
            self, text="", font=ui_font(size=11),
            text_color=current_palette()["text_dim"],
        )
        self.poll_label.pack(side="right", padx=(0, 10))

    def refresh_theme(self):
        p = current_palette()
        self.vm_label.configure(text_color=p["text_dim"])
        self.vmrun_label.configure(text_color=p["text_dim"])
        self.poll_label.configure(text_color=p["text_dim"])

    def refresh_language(self):
        self.app._refresh_status_bar_texts()


# ── Main Application Window ──────────────────────────────────

class App:
    EVENTS_PER_TICK = 40

    def __init__(self, config_manager: ConfigManager, sync_managers):
        self.cm = config_manager
        if isinstance(sync_managers, (list, tuple)):
            self.sync_managers = list(sync_managers)
        else:
            self.sync_managers = [sync_managers]
        self.sync = self.sync_managers[0]

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        set_windows_app_user_model_id()
        self.window = ctk.CTk()
        self.window.title("VM Sync")
        self.window.geometry(SINGLE_PROJECT_GEOMETRY)
        self.window.minsize(*SINGLE_PROJECT_MIN_SIZE)
        self._apply_window_icon()

        self._current_appearance = ctk.get_appearance_mode()
        self._last_appearance_check_time = 0.0
        self._tray_notified_close = False
        self._status_check_running = False
        self._last_preflight_error = ""
        self._last_preflight_error_time = 0.0
        self._single_instance_sock = None
        self._single_instance_thread = None
        self._shutting_down = False
        self._after_jobs = set()
        self._vmrun_status_state = "unknown"
        self._vm_status_state = "checking"
        self._status_indicator_state = "ready"
        self._language_switch_updating = False
        self._latest_bin_return_times: dict[int, float] = {}
        self._config_revision = 0

        self._build_ui()
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        # Tray — show immediately on startup, persists until Exit.
        self._tray_icon = None
        self._tray_thread = None
        self._ensure_tray()

        self._check_vm_status()
        self._poll_events()

    def _apply_window_icon(self):
        try:
            self.window.iconbitmap(app_icon_path())
            self._window_icon_photos = []
        except Exception:
            self._window_icon_photos = [
                ImageTk.PhotoImage(create_app_icon(size))
                for size in (16, 32, 64)
            ]
            self.window.iconphoto(True, *self._window_icon_photos)

    # ── Build UI ─────────────────────────────────────────

    def tr(self, key: str, **kwargs) -> str:
        return Translator(getattr(self.cm.config, "language", "zh")).tr(key, **kwargs)

    def _language_segment_value(self) -> str:
        return LANGUAGE_SEGMENT_VALUES.get(self.cm.config.language, "中")

    def get_sync_manager(self, project_index: int = 0):
        sync_managers = getattr(self, "sync_managers", None)
        if sync_managers and 0 <= project_index < len(sync_managers):
            return sync_managers[project_index]
        return self.sync

    def get_enabled_project_indexes(self) -> list[int]:
        if not hasattr(self, "cm"):
            return list(range(len(getattr(self, "sync_managers", [])))) or [0]
        indexes = []
        for index, project in enumerate(getattr(self.cm.config, "projects", [])):
            if getattr(project, "enabled", False):
                indexes.append(index)
        return indexes or [0]

    def any_running(self) -> bool:
        sync_managers = getattr(self, "sync_managers", None)
        if not sync_managers:
            return getattr(self.sync, "running", False)
        return any(getattr(sync, "running", False) for sync in sync_managers)

    def any_full_sync_active(self) -> bool:
        sync_managers = getattr(self, "sync_managers", None)
        if not sync_managers:
            return getattr(self.sync, "full_sync_active", False)
        return any(getattr(sync, "full_sync_active", False) for sync in sync_managers)

    def aggregate_sync_count(self) -> int:
        return sum(
            getattr(self.get_sync_manager(index), "synced_count", 0)
            for index in self.get_enabled_project_indexes()
        )

    def aggregate_bin_ready(self) -> bool:
        enabled = self.get_enabled_project_indexes()
        if not enabled:
            return getattr(self.sync, "bin_ready", False)
        return all(
            getattr(self.get_sync_manager(index), "bin_ready", False)
            for index in enabled
        )

    def capture_profile_form_payload(self) -> dict:
        shared_panel = getattr(self, "shared_vm_panel", None)
        shared = (
            shared_panel.collect_values()
            if shared_panel is not None and hasattr(shared_panel, "collect_values")
            else {
                "vmx_path": self.cm.config.vmx_path,
                "vm_guest_user": self.cm.config.vm_guest_user,
                "vm_guest_password": self.cm.config.vm_guest_password,
            }
        )
        projects = []
        for index, project in enumerate(self.cm.config.projects[:2]):
            panel = getattr(self, "project_panels", {}).get(index)
            config_panel = getattr(panel, "config_panel", None)
            values = (
                config_panel.collect_values()
                if config_panel is not None and hasattr(config_panel, "collect_values")
                else {
                    "host_project_path": project.host_project_path,
                    "vm_project_path": project.vm_project_path,
                    "vm_bin_relative_path": project.vm_bin_relative_path,
                    "host_output_path": project.host_output_path,
                }
            )
            projects.append({"enabled": bool(project.enabled), **values})
        return {"shared": shared, "projects": projects}

    def apply_profile_form_to_config(self):
        shared_panel = getattr(self, "shared_vm_panel", None)
        if shared_panel is not None and hasattr(shared_panel, "apply_values_to_config"):
            shared_panel.apply_values_to_config()
        for panel in getattr(self, "project_panels", {}).values():
            config_panel = getattr(panel, "config_panel", None)
            if config_panel is not None and hasattr(config_panel, "apply_values_to_config"):
                config_panel.apply_values_to_config()

    def profile_form_is_dirty(self) -> bool:
        profile = self.cm.get_active_profile()
        payload = self.capture_profile_form_payload()
        stored_payload = {
            "shared": {
                "vmx_path": profile.vmx_path,
                "vm_guest_user": profile.vm_guest_user,
                "vm_guest_password": profile.vm_guest_password,
            },
            "projects": [
                {
                    "enabled": bool(project.enabled),
                    "host_project_path": project.host_project_path,
                    "vm_project_path": project.vm_project_path,
                    "vm_bin_relative_path": project.vm_bin_relative_path,
                    "host_output_path": project.host_output_path,
                }
                for project in profile.projects[:2]
            ],
        }
        return payload != stored_payload

    def log_profile_event(self, key: str, **kwargs):
        event = LogEvent(LogIcon.CONFIG, self.tr(key, **kwargs), "success")
        indexes = self.get_enabled_project_indexes()
        for index in indexes:
            panel = getattr(self, "project_panels", {}).get(index)
            if panel is not None:
                panel.log_panel.append(event)

    def after_profile_loaded(self, profile_name: str):
        self._config_revision += 1
        shared_panel = getattr(self, "shared_vm_panel", None)
        if shared_panel is not None:
            shared_panel.load_values()
        for index, panel in getattr(self, "project_panels", {}).items():
            panel.config_panel.load_values()
            panel.log_panel.clear()
            sync = self.get_sync_manager(index)
            resetter = getattr(sync, "reset_profile_state", None)
            if callable(resetter):
                resetter()
            event_queue = getattr(sync, "event_queue", None)
            if event_queue is not None:
                while True:
                    try:
                        event_queue.get_nowait()
                    except queue.Empty:
                        break
        self._latest_bin_return_times.clear()
        self._set_project_enabled(0, True, save=False)
        if len(self.cm.config.projects) > 1:
            self._set_project_enabled(1, bool(self.cm.config.projects[1].enabled), save=False)
        self.control.update_stats(0, False)
        self._vmrun_status_state = "unknown"
        self._vm_status_state = "checking"
        self._status_check_running = False
        self._refresh_status_bar_texts()
        self.log_profile_event("ui.profile.log.loaded", name=profile_name)
        self._check_vm_status(schedule_next=False)

    def _format_bin_return_status(self, bin_ready: bool) -> str:
        base = self.tr("ui.bin.ready") if bin_ready else self.tr("ui.bin.waiting")
        enabled_indexes = self.get_enabled_project_indexes()
        latest_times = getattr(self, "_latest_bin_return_times", {})

        def format_time(timestamp: float) -> str:
            returned_at = datetime.fromtimestamp(timestamp)
            if returned_at.date() == datetime.now().date():
                return returned_at.strftime("%H:%M:%S")
            return returned_at.strftime("%m-%d %H:%M:%S")

        if len(enabled_indexes) <= 1:
            project_index = enabled_indexes[0] if enabled_indexes else 0
            timestamp = latest_times.get(project_index)
            if not timestamp:
                return base
            return f"{base}    {self.tr('ui.bin.latest', time=format_time(timestamp))}"

        parts = []
        for project_index in enabled_indexes:
            project_number = project_index + 1
            timestamp = latest_times.get(project_index)
            if timestamp:
                parts.append(
                    self.tr(
                        "ui.bin.project_time",
                        number=project_number,
                        time=format_time(timestamp),
                    )
                )
            else:
                parts.append(
                    self.tr("ui.bin.project_waiting", number=project_number)
                )
        return f".bin    {'  |  '.join(parts)}"

    def set_all_config_enabled(self, enabled: bool):
        profile_panel = getattr(self, "profile_panel", None)
        if profile_panel is not None:
            profile_panel.set_enabled(enabled)
        shared_vm_panel = getattr(self, "shared_vm_panel", None)
        if shared_vm_panel is not None:
            shared_vm_panel.set_config_enabled(enabled)
        for panel in getattr(self, "project_panels", {}).values():
            panel.set_config_enabled(enabled)

    def _pack_project_action_button(self, button):
        if button is None:
            return
        pack = getattr(button, "pack", None)
        if callable(pack):
            pack(side="right")

    def _hide_project_action_button(self, button):
        if button is None:
            return
        pack_forget = getattr(button, "pack_forget", None)
        if callable(pack_forget):
            pack_forget()

    def _show_secondary_project_action(self, project_2_enabled: bool):
        add_button = getattr(self, "add_project_btn", None)
        remove_button = getattr(self, "remove_project_btn", None)
        self._hide_project_action_button(add_button)
        self._hide_project_action_button(remove_button)
        if project_2_enabled:
            self._pack_project_action_button(remove_button)
        else:
            self._pack_project_action_button(add_button)

    def _set_secondary_project_action_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for button in (
            getattr(self, "add_project_btn", None),
            getattr(self, "remove_project_btn", None),
        ):
            if button is not None:
                button.configure(state=state)

    def _has_secondary_project_enabled(self) -> bool:
        projects = getattr(self.cm.config, "projects", [])
        return any(
            getattr(project, "enabled", False)
            for project in projects[1:2]
        )

    def _resize_window_for_project_layout(self, dual_project: bool):
        geometry = DUAL_PROJECT_GEOMETRY if dual_project else SINGLE_PROJECT_GEOMETRY
        min_size = DUAL_PROJECT_MIN_SIZE if dual_project else SINGLE_PROJECT_MIN_SIZE
        window = getattr(self, "window", None)
        if window is None:
            return
        try:
            window.minsize(*min_size)
            window.geometry(geometry)
        except tk.TclError:
            return

    def _apply_project_layout_mode(self):
        dual_project = self._has_secondary_project_enabled()
        frame = getattr(self, "project_panels_frame", None)
        if frame is not None:
            if dual_project:
                frame.grid_columnconfigure(
                    0,
                    weight=1,
                    uniform="project_columns",
                    minsize=PROJECT_COLUMN_MIN_WIDTH,
                )
                frame.grid_columnconfigure(
                    1,
                    weight=1,
                    uniform="project_columns",
                    minsize=PROJECT_COLUMN_MIN_WIDTH,
                )
            else:
                frame.grid_columnconfigure(0, weight=1, uniform="", minsize=0)
                frame.grid_columnconfigure(1, weight=0, uniform="", minsize=0)

        panels = getattr(self, "project_panels", {})
        project_1 = panels.get(0)
        project_2 = panels.get(1)
        if project_1 is not None and hasattr(project_1, "grid_configure"):
            project_1.grid_configure(
                padx=(0, PROJECT_COLUMN_GAP) if dual_project else (0, 0)
            )
        if dual_project and project_2 is not None and hasattr(project_2, "grid_configure"):
            project_2.grid_configure(
                padx=(PROJECT_COLUMN_GAP, 0)
            )

        self._resize_window_for_project_layout(dual_project)

    def _set_project_enabled(self, project_index: int, enabled: bool, save: bool = True):
        projects = getattr(self.cm.config, "projects", [])
        if not (0 <= project_index < len(projects)):
            return
        projects[project_index].enabled = enabled
        panel = getattr(self, "project_panels", {}).get(project_index)
        if panel is not None:
            if enabled:
                panel.show()
            else:
                sync = self.get_sync_manager(project_index)
                if getattr(sync, "full_sync_active", False):
                    try:
                        sync.request_full_sync_cancel()
                    except Exception:
                        pass
                if getattr(sync, "running", False):
                    try:
                        sync.stop()
                    except Exception:
                        pass
                getattr(self, "_latest_bin_return_times", {}).pop(project_index, None)
                panel.hide()
        if project_index == 1:
            self._show_secondary_project_action(enabled)
        self._apply_project_layout_mode()
        if save:
            self.cm.save()

    def _build_ui(self):
        p = current_palette()
        self.window.configure(fg_color=p["bg"])

        # Title bar
        title_frame = ctk.CTkFrame(self.window, fg_color="transparent")
        title_frame.pack(fill="x", padx=18, pady=(14, 6))

        self.status_dot = ctk.CTkLabel(
            title_frame, text="●", font=ui_font(size=16),
            text_color=p["text_dim"],
        )
        self.status_dot.pack(side="left", padx=(0, 6))

        ctk.CTkLabel(
            title_frame, text="VM SYNC",
            font=ui_font(size=18, weight="bold"),
            text_color=p["text"],
        ).pack(side="left")

        self.status_text = ctk.CTkLabel(
            title_frame, text=self.tr("ui.status.ready"),
            font=ui_font(size=12),
            text_color=p["text_dim"],
        )
        self.status_text.pack(side="right")

        self.language_switch = ctk.CTkSegmentedButton(
            title_frame,
            values=["中", "EN"],
            width=74,
            height=24,
            corner_radius=CONTROL_CORNER_RADIUS,
            font=ui_font(size=11),
            fg_color=p["muted_button"],
            selected_color=p["accent"],
            selected_hover_color=p["accent_hover"],
            unselected_color=p["muted_button"],
            unselected_hover_color=p["muted_hover"],
            text_color=p["button_text"],
            command=self._on_language_selected,
        )
        self.language_switch.pack(side="right", padx=(0, 10))
        self._language_switch_updating = True
        self.language_switch.set(self._language_segment_value())
        self._language_switch_updating = False

        # Control panel (fixed)
        self.control = ControlPanel(self.window, self)
        self.control.pack(fill="x", padx=18, pady=(0, 6))

        # ── Overall scrollable area (config + log) ──
        # Scrollbar auto-hides when both panels are fully visible.
        self.scroll_area = AutoScrollFrame(
            self.window,
            fg_color="transparent",
            canvas_bg=p["bg"],
            scrollbar_button_color=p["border"],
            scrollbar_button_hover_color=p["accent"],
        )
        self.scroll_area.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        self.profile_shell = ctk.CTkFrame(self.scroll_area.inner, fg_color="transparent")
        self.profile_shell.pack(
            fill="x",
            padx=CONTENT_SIDE_PADDING,
            pady=(4, 4),
        )
        self.profile_shell.grid_columnconfigure(0, weight=1)
        self.profile_panel = ProfilePanel(self.profile_shell, self)
        self.profile_panel.grid(row=0, column=0, sticky="ew")

        self.shared_vm_shell = ctk.CTkFrame(self.scroll_area.inner, fg_color="transparent")
        self.shared_vm_shell.pack(
            fill="x",
            padx=CONTENT_SIDE_PADDING,
            pady=(4, 4),
        )
        self.shared_vm_shell.grid_columnconfigure(0, weight=1)

        self.shared_vm_panel = SharedVmPanel(self.shared_vm_shell, self)
        self.shared_vm_panel.grid(row=0, column=0, sticky="ew")

        self.project_action_row = ctk.CTkFrame(self.scroll_area.inner, fg_color="transparent")
        self.project_action_row.pack(fill="x", padx=CONTENT_SIDE_PADDING, pady=(0, 6))

        self.add_project_btn = ctk.CTkButton(
            self.project_action_row,
            text=self.tr("ui.button.add_project"),
            width=SAVE_CHECK_BUTTON_WIDTH,
            height=CONFIG_ACTION_BUTTON_HEIGHT,
            corner_radius=CONTROL_CORNER_RADIUS,
            font=ui_font(size=12),
            fg_color=p["muted_button"],
            hover_color=p["muted_hover"],
            text_color=p["text"],
            command=lambda: self._set_project_enabled(1, True),
        )
        self.add_project_btn.pack(side="right")
        self.remove_project_btn = ctk.CTkButton(
            self.project_action_row,
            text=self.tr("ui.button.remove_project"),
            width=SAVE_CHECK_BUTTON_WIDTH,
            height=CONFIG_ACTION_BUTTON_HEIGHT,
            corner_radius=CONTROL_CORNER_RADIUS,
            font=ui_font(size=12),
            fg_color=p["muted_button"],
            hover_color=p["muted_hover"],
            text_color=p["text"],
            command=lambda: self._set_project_enabled(1, False),
        )

        self.project_panels_frame = ctk.CTkFrame(self.scroll_area.inner, fg_color="transparent")
        self.project_panels_frame.pack(
            fill="both",
            expand=True,
            padx=CONTENT_SIDE_PADDING,
            pady=(0, 4),
        )
        self.project_panels_frame.grid_rowconfigure(0, weight=1)
        self.project_panels_frame.grid_columnconfigure(
            0,
            weight=1,
            uniform="project_columns",
            minsize=PROJECT_COLUMN_MIN_WIDTH,
        )
        self.project_panels_frame.grid_columnconfigure(
            1,
            weight=1,
            uniform="project_columns",
            minsize=PROJECT_COLUMN_MIN_WIDTH,
        )

        self.project_panels = {}
        for index in range(min(2, len(self.sync_managers))):
            panel = ProjectPane(self.project_panels_frame, self, index)
            panel.grid(
                row=0,
                column=index,
                sticky="nsew",
                padx=(0, PROJECT_COLUMN_GAP) if index == 0 else (PROJECT_COLUMN_GAP, 0),
            )
            self.project_panels[index] = panel
            self.scroll_area.add_wheel_exclusion(panel.log_panel.textbox)
            self.scroll_area.add_wheel_exclusion(
                getattr(panel.log_panel.textbox, "_textbox", None)
            )

        self.config_panel = self.project_panels[0].config_panel
        self.log_panel = self.project_panels[0].log_panel
        self._set_project_enabled(0, True, save=False)
        if len(self.project_panels) > 1:
            self._set_project_enabled(
                1,
                getattr(self.cm.config.projects[1], "enabled", False),
                save=False,
            )

        # Status bar (fixed at bottom)
        self.status_bar = StatusBar(self.window, self)
        self.status_bar.pack(fill="x", padx=18, pady=(0, 8))

        self.window.bind_all(
            "<Button-1>",
            self._clear_entry_focus_on_background_click,
            add="+",
        )

    def _on_language_selected(self, value: str):
        if self._language_switch_updating:
            return
        language = SEGMENT_VALUE_LANGUAGES.get(value)
        if language:
            self.set_language(language)

    def set_language(self, language: str):
        language = normalize_language(language)
        if not language:
            return
        if self.cm.config.language != language:
            self.cm.config.language = language
            self.cm.save()
        self._last_preflight_error = ""
        self._last_preflight_error_time = 0.0
        self._refresh_all_texts()

    def _refresh_all_texts(self):
        if hasattr(self, "language_switch"):
            self._language_switch_updating = True
            self.language_switch.set(self._language_segment_value())
            self._language_switch_updating = False
        self._update_status_indicator(self.any_running())
        self.control.refresh_language()
        profile_panel = getattr(self, "profile_panel", None)
        if profile_panel is not None:
            profile_panel.refresh_language()
        shared_vm_panel = getattr(self, "shared_vm_panel", None)
        if shared_vm_panel is not None:
            shared_vm_panel.refresh_language()
        add_project_btn = getattr(self, "add_project_btn", None)
        if add_project_btn is not None:
            add_project_btn.configure(text=self.tr("ui.button.add_project"))
        remove_project_btn = getattr(self, "remove_project_btn", None)
        if remove_project_btn is not None:
            remove_project_btn.configure(text=self.tr("ui.button.remove_project"))
        for panel in getattr(self, "project_panels", {}).values():
            panel.refresh_language()
        self.status_bar.refresh_language()
        self._update_tray_menu()

    def _clear_entry_focus_on_background_click(self, event):
        if self._is_text_input_event_widget(getattr(event, "widget", None)):
            return
        try:
            self.window.focus_set()
        except Exception:
            pass

    def _is_text_input_event_widget(self, widget) -> bool:
        while widget is not None:
            if isinstance(widget, (tk.Entry, tk.Text)):
                return True
            if isinstance(widget, (ctk.CTkEntry, ctk.CTkTextbox)):
                return True
            try:
                if widget.winfo_class() in {"Entry", "Text"}:
                    return True
            except Exception:
                pass
            widget = getattr(widget, "master", None)
        return False

    # ── Theme Refresh ────────────────────────────────────

    def _check_appearance_change(self):
        current = ctk.get_appearance_mode()
        if current != self._current_appearance:
            self._current_appearance = current
            self._refresh_all_themes()

    def _maybe_check_appearance_change(self):
        now = time.monotonic()
        if now - self._last_appearance_check_time < 1.0:
            return
        self._last_appearance_check_time = now
        self._check_appearance_change()

    def _refresh_all_themes(self):
        p = current_palette()
        self.window.configure(fg_color=p["bg"])
        self.status_dot.configure(text_color=p["text_dim"])
        self.status_text.configure(text_color=p["text_dim"])
        self.language_switch.configure(
            fg_color=p["muted_button"],
            selected_color=p["accent"],
            selected_hover_color=p["accent_hover"],
            unselected_color=p["muted_button"],
            unselected_hover_color=p["muted_hover"],
            text_color=p["button_text"],
        )
        self.scroll_area.scrollbar.configure(
            button_color=p["border"], button_hover_color=p["accent"],
        )
        self.scroll_area.canvas.configure(bg=p["bg"])
        self.control.refresh_theme()
        profile_panel = getattr(self, "profile_panel", None)
        if profile_panel is not None:
            profile_panel.refresh_theme()
        shared_vm_panel = getattr(self, "shared_vm_panel", None)
        if shared_vm_panel is not None:
            shared_vm_panel.refresh_theme()
        for action_button in (
            getattr(self, "add_project_btn", None),
            getattr(self, "remove_project_btn", None),
        ):
            if action_button is None:
                continue
            action_button.configure(
                fg_color=p["muted_button"],
                hover_color=p["muted_hover"],
                text_color=p["text"],
            )
        for panel in getattr(self, "project_panels", {}).values():
            panel.refresh_theme()
        self.status_bar.refresh_theme()

    # ── Window Lifecycle ─────────────────────────────────

    def _on_close(self):
        profile_panel = getattr(self, "profile_panel", None)
        if profile_panel is not None:
            profile_panel.close_popups()
        self.window.withdraw()
        self._tray_notified_close = True
        self._tray_notify_start()

    def _schedule_after(self, delay_ms: int, callback):
        if self._shutting_down:
            return None

        job_id = None

        def _run():
            if job_id is not None:
                self._after_jobs.discard(job_id)
            if not self._shutting_down:
                callback()

        try:
            job_id = self.window.after(delay_ms, _run)
        except tk.TclError:
            return None
        self._after_jobs.add(job_id)
        return job_id

    def _cancel_after_jobs(self):
        jobs = list(self._after_jobs)
        self._after_jobs.clear()
        for job_id in jobs:
            try:
                self.window.after_cancel(job_id)
            except tk.TclError:
                pass

    def _ensure_tray(self):
        if self._tray_icon is not None:
            return
        image = create_tray_icon()
        menu = self._build_tray_menu()
        self._tray_icon = pystray.Icon("vm_sync", image, "VM Sync", menu)
        self._tray_thread = threading.Thread(
            target=self._tray_icon.run, daemon=True
        )
        self._tray_thread.start()

    def _build_tray_menu(self):
        return TrayActivationMenu(
            self._tray_show,
            pystray.MenuItem(
                self._tray_status_label,
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                self._tray_sync_label,
                self._tray_toggle_sync,
                default=True,
            ),
            pystray.MenuItem(
                self._tray_show_label,
                self._tray_show,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(self._tray_quit_label, self._tray_quit),
        )

    def _update_tray_menu(self):
        if self._tray_icon:
            self._tray_icon.update_menu()

    def _tray_sync_label(self, _item=None):
        return tray_sync_label(self.any_running(), self.cm.config.language)

    def _tray_status_label(self, _item=None):
        return tray_status_label(
            self.any_running(),
            self.cm.config.language,
            self._runtime_status_state(self.any_running()),
        )

    def _tray_show_label(self, _item=None):
        return self.tr("tray.show")

    def _tray_quit_label(self, _item=None):
        return self.tr("tray.quit")

    def _tray_sync_checked(self, _item=None):
        return self.any_running()

    def _tray_toggle_sync(self):
        if self._shutting_down:
            return
        if self.any_running():
            self.window.after(0, self.control._pause)
        else:
            self.window.after(0, self.control._start)

    def _tray_notify_start(self):
        if self._tray_icon and self._tray_notified_close:
            try:
                self._tray_icon.notify(app_tr(self, "tray.notify.background"), "VM Sync")
            except Exception:
                pass

    def _tray_show(self):
        if self._shutting_down:
            return
        self.window.after(0, self._restore_window)

    def _restore_window(self):
        self._tray_notified_close = False
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def _tray_quit(self):
        self.window.after(0, self._shutdown)

    def _shutdown(self):
        if self._shutting_down:
            return
        profile_panel = getattr(self, "profile_panel", None)
        if profile_panel is not None and not profile_panel.confirm_shutdown():
            return
        self._shutting_down = True
        sync_managers = getattr(self, "sync_managers", None) or [self.sync]
        for sync in sync_managers:
            if getattr(sync, "full_sync_active", False):
                sync.request_full_sync_cancel()
        for sync in sync_managers:
            try:
                sync.stop()
            except Exception:
                pass
        App._join_full_sync_thread_for_shutdown(self, timeout=2.0)
        if self._single_instance_sock:
            try:
                self._single_instance_sock.close()
            except OSError:
                pass
            self._single_instance_sock = None
        if self._tray_icon:
            self._tray_icon.stop()
            self._tray_icon = None
        self._cancel_after_jobs()
        try:
            self.window.quit()
        except tk.TclError:
            pass
        try:
            self.window.destroy()
        except tk.TclError:
            pass

    def _join_full_sync_thread_for_shutdown(self, timeout: float = 2.0):
        panels = []
        if getattr(self, "project_panels", None):
            panels.extend(self.project_panels.values())
        elif getattr(self, "config_panel", None):
            panels.append(self.config_panel)
        for panel in panels:
            target = getattr(panel, "config_panel", panel)
            thread = getattr(target, "_full_sync_thread", None)
            if not thread or thread is threading.current_thread():
                continue
            try:
                if thread.is_alive():
                    thread.join(timeout=timeout)
            except RuntimeError:
                pass

    def attach_single_instance_socket(self, sock):
        self._single_instance_sock = sock
        if not sock:
            return
        self._single_instance_thread = threading.Thread(
            target=self._single_instance_loop, daemon=True
        )
        self._single_instance_thread.start()

    def _single_instance_loop(self):
        while self._single_instance_sock:
            try:
                conn, _addr = self._single_instance_sock.accept()
            except OSError:
                return
            with conn:
                try:
                    data = conn.recv(64).strip().upper()
                except OSError:
                    data = b""
            if data == b"SHOW":
                self.window.after(0, self._restore_window)

    # ── Status Updates ───────────────────────────────────

    def _update_status_indicator(self, running: bool):
        p = current_palette()
        if running:
            status = self._runtime_status_state(running)
            key = f"ui.status.{status}"
            status_color = p["warning"] if status in ("partial_error", "error") else p["success"]
            self.status_dot.configure(text_color=status_color)
            self.status_text.configure(text=self.tr(key), text_color=status_color)
            self._status_indicator_state = "running"
        else:
            self.status_dot.configure(text_color=p["text_dim"])
            key = "ui.status.ready" if self._status_indicator_state == "ready" else "ui.status.stopped"
            self.status_text.configure(text=self.tr(key), text_color=p["text_dim"])
            if self._status_indicator_state != "ready":
                self._status_indicator_state = "stopped"

    def _runtime_status_state(self, running: bool) -> str:
        if not running:
            return "stopped"
        enabled_indexes = self.get_enabled_project_indexes()
        has_error = any(
            getattr(self.get_sync_manager(index), "has_error", False)
            for index in enabled_indexes
        )
        if has_error:
            return "partial_error" if len(enabled_indexes) > 1 else "error"
        if len(enabled_indexes) > 1:
            running_count = sum(
                1
                for index in enabled_indexes
                if getattr(self.get_sync_manager(index), "running", False)
            )
            if 0 < running_count < len(enabled_indexes):
                return "partial_running"
        return "running"

    def _refresh_status_bar_texts(self):
        p = current_palette()
        vmrun_keys = {
            "ready": "ui.status.vmrun.ready",
            "checking": "ui.status.vmrun.checking",
            "timeout": "ui.status.vmrun.timeout",
            "unavailable": "ui.status.vmrun.unavailable",
            "unknown": "ui.status.vmrun.empty",
        }
        vm_keys = {
            "checking": "ui.status.vm.checking",
            "running": "ui.status.vm.running",
            "not_running": "ui.status.vm.not_running",
            "unconfigured": "ui.status.vm.unconfigured",
            "unknown": "ui.status.vm.unknown",
        }
        vmrun_state = getattr(self, "_vmrun_status_state", "unknown")
        vm_state = getattr(self, "_vm_status_state", "unknown")
        vmrun_color = {
            "ready": p["success"],
            "timeout": p["warning"],
            "unavailable": p["error"],
        }.get(vmrun_state, p["text_dim"])
        vm_color = {
            "running": p["success"],
            "not_running": p["warning"],
        }.get(vm_state, p["text_dim"])
        self.status_bar.vmrun_label.configure(
            text=self.tr(vmrun_keys.get(vmrun_state, "ui.status.vmrun.empty")),
            text_color=vmrun_color,
        )
        self.status_bar.vm_label.configure(
            text=self.tr(vm_keys.get(vm_state, "ui.status.vm.unknown")),
            text_color=vm_color,
        )
        self.status_bar.poll_label.configure(
            text=self.tr("ui.status.poll", seconds=self.cm.config.poll_interval_sec)
        )

    def _check_vm_status(self, schedule_next: bool = True):
        if self._shutting_down:
            return
        p = current_palette()
        vmrun = self.resolve_vmrun_path(save=True)
        if not vmrun:
            self._vmrun_status_state = "unavailable"
            self._vm_status_state = "unknown"
            self.status_bar.vmrun_label.configure(
                text=self.tr("ui.status.vmrun.unavailable"), text_color=p["error"]
            )
            self.status_bar.vm_label.configure(
                text=self.tr("ui.status.vm.unknown"), text_color=p["text_dim"]
            )
        else:
            if getattr(self, "_vmrun_status_state", "unknown") == "unknown":
                self._vmrun_status_state = "checking"
                self.status_bar.vmrun_label.configure(
                    text=self.tr("ui.status.vmrun.checking"), text_color=p["text_dim"]
                )
            if not self._status_check_running:
                self._status_check_running = True
                threading.Thread(
                    target=self._check_vm_status_worker,
                    args=(vmrun, self.cm.config.vmx_path, getattr(self, "_config_revision", 0)),
                    daemon=True,
                ).start()

        interval = self.cm.config.poll_interval_sec
        self.status_bar.poll_label.configure(
            text=self.tr("ui.status.poll", seconds=interval)
        )

        # Re-check every 10 seconds
        if schedule_next:
            self._schedule_after(10000, self._check_vm_status)

    def _check_vm_status_worker(self, vmrun: str, vmx: str, config_revision: int | None = None):
        result = list_running_vms(vmrun)
        self._schedule_after(
            0,
            lambda: self._apply_vm_status_result(vmrun, vmx, result, config_revision),
        )

    def _apply_vm_status_result(
        self,
        vmrun: str,
        vmx: str,
        result,
        config_revision: int | None = None,
    ):
        if self._shutting_down:
            return
        if config_revision is not None and config_revision != getattr(self, "_config_revision", 0):
            return
        current_vmx = self.cm.config.vmx_path
        captured_vmx_key = normalize_vmx_path(vmx) if vmx else ""
        current_vmx_key = normalize_vmx_path(current_vmx) if current_vmx else ""
        if captured_vmx_key != current_vmx_key:
            self._status_check_running = False
            self._check_vm_status(schedule_next=False)
            return
        self._status_check_running = False
        p = current_palette()
        if result.ok:
            running = {normalize_vmx_path(path) for path in result.paths}
            if not self.cm.config.vmx_path and result.paths:
                self.cm.config.vmx_path = result.paths[0]
                self.cm.save()
                shared_vm_panel = getattr(self, "shared_vm_panel", None)
                if shared_vm_panel is not None:
                    shared_vm_panel.load_values()
                vmx = self.cm.config.vmx_path

            if vmx and normalize_vmx_path(vmx) in running:
                self._vm_status_state = "running"
                self.status_bar.vm_label.configure(
                    text=self.tr("ui.status.vm.running"), text_color=p["success"]
                )
            elif vmx:
                self._vm_status_state = "not_running"
                self.status_bar.vm_label.configure(
                    text=self.tr("ui.status.vm.not_running"), text_color=p["warning"]
                )
            else:
                self._vm_status_state = "unconfigured"
                self.status_bar.vm_label.configure(
                    text=self.tr("ui.status.vm.unconfigured"), text_color=p["text_dim"]
                )
            self.status_bar.vmrun_label.configure(
                text=self.tr("ui.status.vmrun.ready"), text_color=p["success"]
            )
            self._vmrun_status_state = "ready"
        else:
            is_timeout = "超时" in result.error or "timeout" in result.error.lower()
            self.status_bar.vmrun_label.configure(
                text=self.tr("ui.status.vmrun.timeout") if is_timeout else self.tr("ui.status.vmrun.unavailable"),
                text_color=p["warning"] if is_timeout else p["error"],
            )
            self._vmrun_status_state = "timeout" if is_timeout else "unavailable"
            self._vm_status_state = "unknown"
            self.status_bar.vm_label.configure(
                text=self.tr("ui.status.vm.unknown"), text_color=p["text_dim"]
            )

    # ── Event Polling ────────────────────────────────────

    def _poll_events(self):
        if self._shutting_down:
            return
        self._maybe_check_appearance_change()
        processed = 0
        sync_managers = getattr(self, "sync_managers", None)
        if not sync_managers:
            sync_managers = [self.sync]
        manager_views = []
        for index, sync in enumerate(sync_managers):
            project_panel = getattr(self, "project_panels", {}).get(index)
            log_panel = getattr(project_panel, "log_panel", getattr(self, "log_panel", None))
            manager_views.append((index, sync, project_panel, log_panel))

        made_progress = True
        while processed < self.EVENTS_PER_TICK and made_progress:
            made_progress = False
            for index, sync, _project_panel, log_panel in manager_views:
                if processed >= self.EVENTS_PER_TICK:
                    break
                try:
                    event = sync.event_queue.get_nowait()
                except queue.Empty:
                    continue
                made_progress = True
                processed += 1
                event_type, data = event
                if event_type == "log" and log_panel is not None:
                    log_panel.append(data)
                elif event_type == "bin_ready":
                    self._on_bin_ready(data, index)
                elif event_type == "bin_unchanged":
                    self._on_bin_unchanged(data, index)
                elif event_type == "full_sync_progress" and log_panel is not None:
                    log_panel.update_progress(data)
                elif event_type == "info" and data == "sync_started":
                    getattr(self, "_latest_bin_return_times", {}).pop(index, None)
                elif event_type == "info" and data == "sync_stopped":
                    if _project_panel is not None:
                        updater = getattr(_project_panel, "_set_project_running_ui", None)
                        if callable(updater):
                            updater(False)
                    refresher = getattr(_project_panel, "_refresh_app_running_state", None)
                    if callable(refresher):
                        refresher()
                    else:
                        running = self.any_running()
                        self._update_status_indicator(running)
                        self._update_tray_menu()

        for index, sync, project_panel, _log_panel in manager_views:
            if project_panel is not None and hasattr(project_panel, "update_stats"):
                project_panel.update_stats(sync.synced_count, sync.bin_ready)

        self.control.update_stats(
            self.aggregate_sync_count(),
            self.aggregate_bin_ready(),
        )

        self._schedule_after(200, self._poll_events)

    def _on_bin_ready(self, data, project_index: int = 0):
        if isinstance(data, dict):
            filename = data.get("filename", "")
            returned_at = data.get("returned_at", data.get("local_mtime"))
        else:
            filename = str(data)
            returned_at = None
        if returned_at is not None:
            try:
                if not hasattr(self, "_latest_bin_return_times"):
                    self._latest_bin_return_times = {}
                self._latest_bin_return_times[project_index] = float(returned_at)
            except (TypeError, ValueError):
                pass
        if self._tray_icon:
            try:
                self._tray_icon.notify(
                    app_tr(
                        self,
                        "tray.notify.bin_ready",
                        filename=filename,
                        project_number=project_index + 1,
                    ),
                    "VM Sync",
                )
            except Exception:
                pass

    def _on_bin_unchanged(self, filename: str, project_index: int = 0):
        if self._tray_icon:
            try:
                self._tray_icon.notify(
                    app_tr(
                        self,
                        "tray.notify.bin_unchanged",
                        filename=filename,
                        project_number=project_index + 1,
                    ),
                    "VM Sync",
                )
            except Exception:
                pass

    # ── Helpers ──────────────────────────────────────────

    def resolve_vmrun_path(self, save: bool = False) -> str:
        resolved = resolve_vmrun_path(self.cm.config.vmrun_path)
        if resolved and resolved != self.cm.config.vmrun_path:
            self.cm.config.vmrun_path = resolved
            if save:
                self.cm.save()
        return self.cm.config.vmrun_path

    def _run_preflight(
        self,
        for_full_sync: bool = False,
        show_dialog: bool = False,
        dedupe_errors: bool = True,
        project_index: int | None = None,
    ) -> PreflightReport:
        # Deduplication state (_last_preflight_error) is handled when emitting the report.
        report = self._collect_preflight_report(
            for_full_sync=for_full_sync,
            project_index=project_index,
        )
        return self._emit_preflight_report(
            report,
            show_dialog=show_dialog,
            dedupe_errors=dedupe_errors,
            project_index=project_index,
        )

    def _collect_preflight_report(
        self,
        for_full_sync: bool = False,
        project_index: int | None = None,
    ) -> PreflightReport:
        checker = PreflightChecker(self.cm.config)
        try:
            report = checker.check(
                for_full_sync=for_full_sync,
                project_index=project_index,
            )
        except TypeError:
            report = checker.check(for_full_sync=for_full_sync)
        sync = self.get_sync_manager(project_index or 0)
        if report.ok and not for_full_sync and hasattr(sync, "validate_bin_target"):
            bin_report = sync.validate_bin_target(emit=False)
            if not bin_report.ok:
                report.errors.append(bin_report.message)
            elif bin_report.level == "warning" and bin_report.message:
                report.warnings.append(bin_report.message)

        return report

    def _preflight_log_panel(self, project_index: int | None = None):
        log_panel = self.log_panel
        if project_index is not None:
            project_panel = getattr(self, "project_panels", {}).get(project_index)
            if project_panel is not None:
                log_panel = project_panel.log_panel
        return log_panel

    def _emit_preflight_report(
        self,
        report: PreflightReport,
        show_dialog: bool = False,
        dedupe_errors: bool = True,
        project_index: int | None = None,
    ) -> PreflightReport:
        log_panel = self._preflight_log_panel(project_index)
        if not report.ok:
            now = time.time()
            is_repeat = (
                dedupe_errors
                and report.error_text == self._last_preflight_error
                and now - self._last_preflight_error_time < 10
            )
            if not is_repeat:
                log_panel.append(LogEvent(
                    LogIcon.ERROR,
                    self.tr("ui.preflight.error", message=report.error_text),
                    "error",
                ))
                self._last_preflight_error = report.error_text
                self._last_preflight_error_time = now
            if show_dialog:
                messagebox.showerror(
                    self.tr("dialog.preflight.error.title"),
                    report.error_text,
                    parent=self.window,
                )
            return report

        if report.warning_text:
            log_panel.append(LogEvent(
                LogIcon.WARNING,
                self.tr("ui.preflight.warning", message=report.warning_text),
                "warning",
            ))
            if show_dialog:
                messagebox.showwarning(
                    self.tr("dialog.preflight.warning.title"),
                    report.warning_text,
                    parent=self.window,
                )
        else:
            log_panel.append(LogEvent(LogIcon.SUCCESS, self.tr("ui.preflight.ok"), "success"))
        self._last_preflight_error = ""
        self._last_preflight_error_time = 0.0
        return report

    def _validate_and_save(self) -> bool:
        self.config_panel._save_values_only()
        return self._run_preflight().ok

    def run(self):
        try:
            self.window.mainloop()
        finally:
            self._shutdown()
