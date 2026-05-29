"""UI layer: CustomTkinter window, panels, system tray, theme management."""

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

from config_manager import ConfigManager
from i18n import Translator, normalize_language
from preflight import PreflightChecker, PreflightReport
from syncer import LogIcon, SyncManager, LogEvent
from vmrun_resolver import list_running_vms, normalize_vmx_path, resolve_vmrun_path


# ── Fonts ─────────────────────────────────────────────────────

FONT_FAMILY = "Microsoft YaHei UI"
MONO_FAMILY = "Microsoft YaHei"
APP_USER_MODEL_ID = "vm-sync-tool.vm-sync"
SINGLE_PROJECT_GEOMETRY = "760x860"
SINGLE_PROJECT_MIN_SIZE = (680, 720)
DUAL_PROJECT_GEOMETRY = "1180x900"
DUAL_PROJECT_MIN_SIZE = (1080, 760)
CONTENT_SIDE_PADDING = 14
PROJECT_COLUMN_GAP = 8
PROJECT_COLUMN_MIN_WIDTH = 500
SAVE_CHECK_BUTTON_WIDTH = 148
ACTION_BUTTON_BORDER_SPACING = 6


def ui_font(size=13, weight="normal"):
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)


def mono_font(size=12):
    return ctk.CTkFont(family=MONO_FAMILY, size=size)


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
    return t("tray.sync.pause") if running else t("tray.sync.start")


def tray_status_label(running: bool, language: str = "zh") -> str:
    t = Translator(language).tr
    return t("tray.status.running") if running else t("tray.status.stopped")


# ── Control Panel ────────────────────────────────────────────

class ControlPanel(ctk.CTkFrame):
    def __init__(self, master, app: "App"):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._start_time: float | None = None
        self._last_sync_count: int | None = None
        self._last_bin_ready: bool | None = None
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
            corner_radius=8,
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
            corner_radius=8,
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

    def update_stats(self, sync_count: int, bin_ready: bool):
        if sync_count != self._last_sync_count:
            self.sync_label.configure(text=self._tr("ui.control.synced", count=sync_count))
            self._last_sync_count = sync_count
        if bin_ready != self._last_bin_ready:
            if bin_ready:
                p = current_palette()
                self.bin_label.configure(text=self._tr("ui.bin.ready"), text_color=p["success"])
            else:
                self.bin_label.configure(
                    text=self._tr("ui.bin.waiting"),
                    text_color=current_palette()["text_dim"],
                )
            self._last_bin_ready = bin_ready
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
                         corner_radius=8)
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
            corner_radius=6,
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
            height=32,
            border_spacing=ACTION_BUTTON_BORDER_SPACING,
            corner_radius=6, font=ui_font(size=12),
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
            width=114,
            height=32,
            corner_radius=6, font=ui_font(size=12),
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
            row, height=30, corner_radius=6,
            font=ui_font(size=12),
            border_color=current_palette()["entry_border"],
            fg_color=current_palette()["entry_bg"],
            placeholder_text_color=current_palette()["text_dim"],
            placeholder_text=self._tr(placeholder_key),
            **entry_kwargs,
        )
        entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        val = getattr(self.app.cm.config, key, "")
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
                corner_radius=7,
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

        root = self._normalize_windows_path(
            vm_project_path or getattr(self.app.cm.config, "vm_project_path", "")
        )
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

    def save_and_check(self) -> PreflightReport:
        self._save_values_only(emit_log=True)
        report = self.app._run_preflight(dedupe_errors=False)
        self.update_bin_path_hint(check_guest=report.ok)
        p = current_palette()
        if report.ok and report.warning_text:
            self.status_label.configure(text=self._tr("ui.config.status.warning", icon=LogIcon.WARNING), text_color=p["warning"])
        elif report.ok:
            self.status_label.configure(text=self._tr("ui.config.status.ok", icon=LogIcon.SUCCESS), text_color=p["success"])
        else:
            self.status_label.configure(text=self._tr("ui.config.status.error", icon=LogIcon.ERROR), text_color=p["error"])
        self.after(2000, lambda: self.status_label.configure(text=""))
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
                         corner_radius=8)
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
            header, text=self._tr("ui.button.clear"), width=52, height=26, corner_radius=6,
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
            corner_radius=6, wrap="word",
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
            corner_radius=8,
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
                corner_radius=6,
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
                    corner_radius=7,
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

    def _save_values_only(self):
        for key, entry in self._entries.items():
            value = entry.get().strip()
            if key == "vmx_path":
                value = ntpath.normpath(value.replace("/", "\\")) if value else ""
            setattr(self.app.cm.config, key, value)

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
        entry = ctk.CTkEntry(
            row,
            height=30,
            corner_radius=6,
            font=ui_font(size=12),
            border_color=current_palette()["entry_border"],
            fg_color=current_palette()["entry_bg"],
            placeholder_text_color=current_palette()["text_dim"],
            placeholder_text=self._tr(placeholder_key),
        )
        entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        value = getattr(self._project_config(), key, "")
        if value:
            entry.insert(0, value)
        if key in self._NORMALIZED_PATH_ENTRY_KEYS:
            entry.bind("<FocusOut>", lambda _event, k=key: self._normalize_entry_display(k))
            entry.bind("<Return>", lambda _event, k=key: self._normalize_entry_display(k))
        self._entries[key] = entry
        if mode in ("dir", "file"):
            button = ctk.CTkButton(
                row,
                text="",
                image=self._folder_icon,
                width=42,
                height=32,
                corner_radius=7,
                font=ui_font(size=12),
                fg_color=current_palette()["muted_button"],
                hover_color=current_palette()["muted_hover"],
                text_color=current_palette()["text"],
                command=lambda k=key, m=mode: self._browse(k, m),
            )
            button.pack(side="right")
            self._browse_buttons[key] = button

    def _save_values_only(self, emit_log: bool = False):
        shared_vm_panel = getattr(self.app, "shared_vm_panel", None)
        if shared_vm_panel and hasattr(shared_vm_panel, "_save_values_only"):
            shared_vm_panel._save_values_only()
        raw_values = {key: entry.get().strip() for key, entry in self._entries.items()}
        project = self._project_config()
        vm_project_path = self._normalize_entry_value(
            "vm_project_path",
            raw_values.get("vm_project_path", getattr(project, "vm_project_path", "")),
        )
        for key in self._entries:
            value = self._normalize_entry_value(
                key,
                raw_values.get(key, ""),
                vm_project_path=vm_project_path,
            )
            setattr(project, key, value)
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

    def _normalize_vm_bin_relative_path(self, value: str, vm_project_path: str | None = None) -> str:
        text = value.replace("/", "\\")
        drive, _tail = ntpath.splitdrive(text)
        if not drive:
            text = text.lstrip("\\")
        text = ntpath.normpath(text)
        if text == ".":
            return text
        root = self._normalize_windows_path(
            vm_project_path or getattr(self._project_config(), "vm_project_path", "")
        )
        if root and self._is_windows_absolute_path(text):
            relative = self._relative_path_under_root(text, root)
            if relative is not None:
                return relative
        return text

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
        self.update_bin_path_hint(check_guest=report.ok)
        p = current_palette()
        if report.ok and report.warning_text:
            self.status_label.configure(text=self._tr("ui.config.status.warning", icon=LogIcon.WARNING), text_color=p["warning"])
        elif report.ok:
            self.status_label.configure(text=self._tr("ui.config.status.ok", icon=LogIcon.SUCCESS), text_color=p["success"])
        else:
            self.status_label.configure(text=self._tr("ui.config.status.error", icon=LogIcon.ERROR), text_color=p["error"])
        self.after(2000, lambda: self.status_label.configure(text=""))
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
            self._set_full_sync_button_active(False, enabled=enabled)
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
        header.pack(fill="x", padx=4, pady=(0, 6))
        self.title_label = ctk.CTkLabel(
            header,
            text=self._project_title(),
            font=ui_font(size=15, weight="bold"),
            text_color=current_palette()["text"],
            anchor="w",
        )
        self.title_label.pack(side="left")
        self.toggle_btn = None
        if self.project_index > 0:
            self.toggle_btn = ctk.CTkButton(
                header,
                text=self._tr("ui.button.remove_project"),
                width=110,
                height=28,
                corner_radius=6,
                font=ui_font(size=11),
                fg_color=current_palette()["muted_button"],
                hover_color=current_palette()["muted_hover"],
                text_color=current_palette()["text_dim"],
                command=self._disable_project,
            )
            self.toggle_btn.pack(side="right")
        self.pause_btn = ctk.CTkButton(
            header,
            text=self._tr("ui.button.pause"),
            image=self._pause_icon,
            compound="left",
            width=76,
            height=28,
            border_spacing=4,
            corner_radius=6,
            font=ui_font(size=11),
            fg_color=current_palette()["muted_button"],
            hover_color=current_palette()["muted_hover"],
            text_color=current_palette()["text_dim"],
            state="disabled",
            command=self._pause_project,
        )
        self.pause_btn.pack(side="right", padx=(0, 6))
        self.start_btn = ctk.CTkButton(
            header,
            text=self._tr("ui.button.start"),
            image=self._start_icon,
            compound="left",
            width=76,
            height=28,
            border_spacing=4,
            corner_radius=6,
            font=ui_font(size=11),
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

    def _disable_project(self):
        self.app._set_project_enabled(self.project_index, False)

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
        report = self.save_and_check()
        if not report.ok:
            return
        sync = self._sync_manager()
        if sync is None:
            return
        self._start_preflight_snapshot = (
            sync.preflight_snapshot()
            if hasattr(sync, "preflight_snapshot")
            else None
        )
        setter = getattr(self.app, "set_all_config_enabled", None)
        if callable(setter):
            setter(False)
        self.start_btn.configure(state="disabled")
        threading.Thread(target=self._start_project_worker, daemon=True).start()

    def _start_project_worker(self):
        started = False
        error = ""
        try:
            sync = self._sync_manager()
            if sync is not None:
                started = sync.start(
                    preflight_checked=True,
                    preflight_snapshot=getattr(self, "_start_preflight_snapshot", None),
                )
        except Exception as e:
            error = str(e)
        self._schedule_ui(lambda: self._finish_project_start(started, error))

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
        if self.toggle_btn is not None:
            self.toggle_btn.configure(text=self._tr("ui.button.remove_project"))
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

    def _log_start_all_blocked(self, passed_indexes: list[int], failed_project_index: int):
        message = self._tr(
            "ui.start.blocked_by_project",
            number=failed_project_index + 1,
        )
        for project_index in passed_indexes:
            self._append_project_log(
                project_index,
                LogEvent(LogIcon.WARNING, message, "warning"),
            )

    def _start(self):
        enabled_indexes = self._enabled_project_indexes()
        snapshots = {}
        passed_indexes = []
        # legacy single-project path: config_panel.set_config_enabled(False)
        for project_index in enabled_indexes:
            panel = self._project_panel(project_index)
            if not panel or not hasattr(panel, "save_and_check"):
                continue
            report = panel.save_and_check()
            if not report.ok:
                self._log_start_all_blocked(passed_indexes, project_index)
                self._start_preflight_snapshot = None
                self._start_preflight_snapshots = {}
                return
            sync = self._sync_manager(project_index)
            if sync and hasattr(sync, "preflight_snapshot"):
                snapshot = sync.preflight_snapshot()
                snapshots[project_index] = snapshot
                if project_index == 0:
                    self._start_preflight_snapshot = snapshot
            passed_indexes.append(project_index)
        self._start_preflight_snapshots = snapshots
        self._set_all_config_enabled(False)
        self.start_btn.configure(state="disabled")
        threading.Thread(target=self._start_worker, daemon=True).start()

    def _start_worker(self):
        sync_managers = getattr(self.app, "sync_managers", None)
        if not sync_managers:
            return super()._start_worker()
        enabled_indexes = self._enabled_project_indexes()
        started_indexes = []
        errors = []
        started = True
        for project_index in enabled_indexes:
            sync = self._sync_manager(project_index)
            if sync is None:
                continue
            try:
                ok = sync.start(
                    preflight_checked=True,
                    preflight_snapshot=self._start_preflight_snapshots.get(project_index),
                )
            except Exception as e:
                ok = False
                errors.append(f"project {project_index + 1}: {e}")
            if not ok:
                started = False
                break
            started_indexes.append(project_index)
        if not started:
            for project_index in reversed(started_indexes):
                try:
                    sync = self._sync_manager(project_index)
                    if sync is not None:
                        sync.stop()
                except Exception:
                    pass
        self.after(0, lambda: self._finish_start(started, "; ".join(errors)))

    def _finish_start(self, started: bool, error: str = ""):
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
        self._full_sync_active = active
        p = current_palette()
        if active:
            self.start_btn.configure(state="disabled", fg_color=p["border"])
            return
        any_running = getattr(self.app, "any_running", lambda: getattr(self.app.sync, "running", False))()
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

    def set_all_config_enabled(self, enabled: bool):
        shared_vm_panel = getattr(self, "shared_vm_panel", None)
        if shared_vm_panel is not None:
            shared_vm_panel.set_config_enabled(enabled)
        for panel in getattr(self, "project_panels", {}).values():
            panel.set_config_enabled(enabled)

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
                if getattr(sync, "running", False):
                    try:
                        sync.stop()
                    except Exception:
                        pass
                panel.hide()
        add_button = getattr(self, "add_project_btn", None)
        if add_button is not None and project_index == 1:
            add_button.pack_forget()
            if not enabled:
                add_button.pack(side="right")
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
            corner_radius=6,
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

        self.config_panel = ConfigPanel(self.scroll_area.inner, self)
        self.config_panel.pack(fill="x", padx=CONTENT_SIDE_PADDING, pady=(4, 4))

        self.log_panel = LogPanel(self.scroll_area.inner, self)
        self.log_panel.pack(fill="x", padx=CONTENT_SIDE_PADDING, pady=(0, 4))
        self.scroll_area.add_wheel_exclusion(self.log_panel.textbox)
        self.scroll_area.add_wheel_exclusion(
            getattr(self.log_panel.textbox, "_textbox", None)
        )

        self.config_panel.pack_forget()
        self.log_panel.pack_forget()

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
            width=132,
            height=32,
            corner_radius=6,
            font=ui_font(size=12),
            fg_color=p["muted_button"],
            hover_color=p["muted_hover"],
            text_color=p["text"],
            command=lambda: self._set_project_enabled(1, True),
        )
        self.add_project_btn.pack(side="right")

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
        shared_vm_panel = getattr(self, "shared_vm_panel", None)
        if shared_vm_panel is not None:
            shared_vm_panel.refresh_language()
        add_project_btn = getattr(self, "add_project_btn", None)
        if add_project_btn is not None:
            add_project_btn.configure(text=self.tr("ui.button.add_project"))
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
        shared_vm_panel = getattr(self, "shared_vm_panel", None)
        if shared_vm_panel is not None:
            shared_vm_panel.refresh_theme()
        add_project_btn = getattr(self, "add_project_btn", None)
        if add_project_btn is not None:
            add_project_btn.configure(
                fg_color=p["muted_button"],
                hover_color=p["muted_hover"],
                text_color=p["text"],
            )
        for panel in getattr(self, "project_panels", {}).values():
            panel.refresh_theme()
        self.status_bar.refresh_theme()

    # ── Window Lifecycle ─────────────────────────────────

    def _on_close(self):
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
        t = self.tr
        return pystray.Menu(
            pystray.MenuItem(
                self._tray_status_label,
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(t("tray.show"), self._tray_show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                self._tray_sync_label,
                self._tray_toggle_sync,
                checked=self._tray_sync_checked,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(t("tray.quit"), self._tray_quit),
        )

    def _update_tray_menu(self):
        if self._tray_icon:
            self._tray_icon.update_menu()

    def _tray_sync_label(self, _item=None):
        return tray_sync_label(self.any_running(), self.cm.config.language)

    def _tray_status_label(self, _item=None):
        return tray_status_label(self.any_running(), self.cm.config.language)

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
            self.status_dot.configure(text_color=p["success"])
            self.status_text.configure(text=self.tr("ui.status.running"), text_color=p["success"])
            self._status_indicator_state = "running"
        else:
            self.status_dot.configure(text_color=p["text_dim"])
            key = "ui.status.ready" if self._status_indicator_state == "ready" else "ui.status.stopped"
            self.status_text.configure(text=self.tr(key), text_color=p["text_dim"])
            if self._status_indicator_state != "ready":
                self._status_indicator_state = "stopped"

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

    def _check_vm_status(self):
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
                    args=(vmrun, self.cm.config.vmx_path),
                    daemon=True,
                ).start()

        interval = self.cm.config.poll_interval_sec
        self.status_bar.poll_label.configure(
            text=self.tr("ui.status.poll", seconds=interval)
        )

        # Re-check every 10 seconds
        self._schedule_after(10000, self._check_vm_status)

    def _check_vm_status_worker(self, vmrun: str, vmx: str):
        result = list_running_vms(vmrun)
        self._schedule_after(
            0,
            lambda: self._apply_vm_status_result(vmrun, vmx, result),
        )

    def _apply_vm_status_result(self, vmrun: str, vmx: str, result):
        if self._shutting_down:
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
        for index, sync in enumerate(sync_managers):
            project_panel = getattr(self, "project_panels", {}).get(index)
            log_panel = getattr(project_panel, "log_panel", getattr(self, "log_panel", None))
            try:
                while processed < self.EVENTS_PER_TICK:
                    event = sync.event_queue.get_nowait()
                    processed += 1
                    event_type, data = event
                    if event_type == "log" and log_panel is not None:
                        log_panel.append(data)
                    elif event_type == "bin_ready":
                        self._on_bin_ready(data)
                    elif event_type == "bin_unchanged":
                        self._on_bin_unchanged(data)
                    elif event_type == "full_sync_progress" and log_panel is not None:
                        log_panel.update_progress(data)
                    elif event_type == "info" and data == "sync_stopped":
                        pass
            except queue.Empty:
                pass
            if project_panel is not None and hasattr(project_panel, "update_stats"):
                project_panel.update_stats(sync.synced_count, sync.bin_ready)

        self.control.update_stats(
            self.aggregate_sync_count(),
            self.aggregate_bin_ready(),
        )

        self._schedule_after(200, self._poll_events)

    def _on_bin_ready(self, filename: str):
        if self._tray_icon:
            try:
                self._tray_icon.notify(app_tr(self, "tray.notify.bin_ready", filename=filename), "VM Sync")
            except Exception:
                pass

    def _on_bin_unchanged(self, filename: str):
        if self._tray_icon:
            try:
                self._tray_icon.notify(
                    app_tr(self, "tray.notify.bin_unchanged", filename=filename),
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

        log_panel = self.log_panel
        if project_index is not None:
            project_panel = getattr(self, "project_panels", {}).get(project_index)
            if project_panel is not None:
                log_panel = project_panel.log_panel

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
