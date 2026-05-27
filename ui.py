"""UI layer: CustomTkinter window, panels, system tray, theme management."""

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import queue
import time
import os
import ctypes
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageTk
import pystray

from config_manager import ConfigManager
from preflight import PreflightChecker, PreflightReport
from syncer import LogIcon, SyncManager, LogEvent
from vmrun_resolver import list_running_vms, normalize_vmx_path, resolve_vmrun_path


# ── Fonts ─────────────────────────────────────────────────────

FONT_FAMILY = "Microsoft YaHei UI"
MONO_FAMILY = "Microsoft YaHei"
APP_USER_MODEL_ID = "vm-sync-tool.vm-sync"


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


def tray_sync_label(running: bool) -> str:
    return "⏸  暂停同步 (运行中)" if running else "▶  启动同步 (已停止)"


def tray_status_label(running: bool) -> str:
    return "状态：运行中" if running else "状态：已停止"


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
            text="启动",
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
            text="暂停",
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
            text="已同步  0",
            font=ui_font(size=13),
            text_color=p["text_dim"],
            anchor="w",
        )
        self.sync_label.pack(anchor="w", pady=(0, 2))

        self.bin_label = ctk.CTkLabel(
            stats_frame,
            text=".bin    —",
            font=ui_font(size=13),
            text_color=p["text_dim"],
            anchor="w",
        )
        self.bin_label.pack(anchor="w", pady=(0, 2))

        self.uptime_label = ctk.CTkLabel(
            stats_frame,
            text="运行时间  —",
            font=ui_font(size=13),
            text_color=p["text_dim"],
            anchor="w",
        )
        self.uptime_label.pack(anchor="w")

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
            message = f"启动同步失败: {error}" if error else "启动同步失败，请查看上方错误并修正配置"
            self.app.log_panel.append(LogEvent(LogIcon.ERROR, message, "error"))
            self._set_stopped()

    def _pause(self):
        try:
            self.app.sync.stop()
        except Exception as e:
            self.app.log_panel.append(LogEvent(LogIcon.ERROR, f"暂停同步失败: {e}。处理方法: 查看同步状态，必要时退出程序后重新启动。", "error"))
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
        self.app._update_status_indicator(False)
        self.app._update_tray_menu()
        self._start_time = None
        self.uptime_label.configure(text="运行时间  —")
        self._last_uptime_text = "运行时间  —"

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
            self.sync_label.configure(text=f"已同步  {sync_count}")
            self._last_sync_count = sync_count
        if bin_ready != self._last_bin_ready:
            if bin_ready:
                p = current_palette()
                self.bin_label.configure(text=".bin    就绪 ✓", text_color=p["success"])
            else:
                self.bin_label.configure(
                    text=".bin    —",
                    text_color=current_palette()["text_dim"],
                )
            self._last_bin_ready = bin_ready
        if self._start_time:
            elapsed = int(time.time() - self._start_time)
            h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
            uptime_text = f"运行时间  {h:02d}:{m:02d}:{s:02d}"
            if uptime_text != self._last_uptime_text:
                self.uptime_label.configure(text=uptime_text)
                self._last_uptime_text = uptime_text

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
    def __init__(self, master, app: "App"):
        super().__init__(master, fg_color=current_palette()["card"],
                         border_color=current_palette()["border"], border_width=1,
                         corner_radius=8)
        self.app = app
        self._entries = {}
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

    def _build(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(10, 5))
        self._header_text_label = pack_section_title(
            header,
            self._header_icon,
            "配置",
        )

        # Entries
        entries_frame = ctk.CTkFrame(self, fg_color="transparent")
        entries_frame.pack(fill="x", padx=14, pady=(0, 4))

        fields = [
            ("vmx_path", "VMX 路径", "file", "选择 VMware 虚拟机 .vmx 文件"),
            ("vm_guest_user", "VM 用户名", "path", "虚拟机 Windows 登录用户名"),
            ("vm_guest_password", "VM 密码", "password", "虚拟机 Windows 登录密码"),
            ("host_project_path", "宿主机工程路径", "dir", "选择宿主机上的工程目录"),
            ("vm_project_path", "VM 工程路径", "path", "虚拟机内工程目录 (例: C:\\project)"),
            ("vm_bin_relative_path", ".bin 相对路径", "path", "可填 .bin 文件或目录 (例: Output\\RL6492)"),
            ("host_output_path", "固件回传目录", "dir", "选择 .bin 回传到宿主机后的保存目录"),
        ]

        for key, label, mode, placeholder in fields:
            self._add_field(entries_frame, key, label, mode, placeholder)

        self.bin_resolved_label = ctk.CTkLabel(
            self,
            text="VM .bin 输出位置: —",
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
            text="保存并检测",
            image=self._save_icon,
            compound="left",
            width=124,
            height=32,
            corner_radius=6, font=ui_font(size=12),
            fg_color=current_palette()["accent"],
            hover_color=current_palette()["accent_hover"],
            text_color=current_palette()["button_text"],
            command=self._save,
        )
        self.save_btn.pack(side="left", padx=(0, 8))

        self.fullsync_btn = ctk.CTkButton(
            btn_row,
            text="全量同步",
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

    def _add_field(self, parent, key, label, mode, placeholder):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=2)

        ctk.CTkLabel(
            row, text=label, width=132, anchor="w",
            font=ui_font(size=12),
            text_color=current_palette()["text_dim"],
        ).pack(side="left", padx=(0, 6))

        entry_kwargs = {"show": "*"} if mode == "password" else {}
        entry = ctk.CTkEntry(
            row, height=30, corner_radius=6,
            font=ui_font(size=12),
            border_color=current_palette()["entry_border"],
            fg_color=current_palette()["entry_bg"],
            placeholder_text=placeholder,
            **entry_kwargs,
        )
        entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        val = getattr(self.app.cm.config, key, "")
        if val:
            entry.insert(0, val)
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
            path = filedialog.askdirectory(title="选择目录")
        else:
            path = filedialog.askopenfilename(
                title="选择 VMX 文件",
                filetypes=[("VMware VMX", "*.vmx"), ("All files", "*.*")],
            )
        if path:
            self._entries[key].delete(0, "end")
            self._entries[key].insert(0, path)

    def _save_values_only(self, emit_log: bool = False):
        for key, entry in self._entries.items():
            setattr(self.app.cm.config, key, entry.get().strip())
        self.app.resolve_vmrun_path(save=True)
        self.app.cm.save()
        if emit_log and hasattr(self.app, "log_panel"):
            self.app.log_panel.append(
                LogEvent(
                    LogIcon.CONFIG,
                    f"路径已保存至 config.json 文件: {self.app.cm.config_path}",
                    "success",
                )
            )

    def update_bin_path_hint(self, check_guest: bool = False):
        p = current_palette()
        cfg = self.app.cm.config
        text_color = p["text_dim"]

        if not cfg.vm_project_path or not cfg.vm_bin_relative_path:
            self.bin_resolved_label.configure(
                text="VM .bin 输出位置: —",
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
                text = f"VM .bin 输出文件: {vm_path}"
            else:
                self._autofill_resolved_bin_path(vm_path)
                text = (
                    f"已识别 .bin: {self._relative_vm_bin_path(vm_path)}    "
                    f"VM .bin 输出文件: {vm_path}"
                )
            text_color = p["success"]
        elif check_guest and not is_file:
            text = (
                f"VM .bin 输出目录: {configured_path}    "
                "请选择具体 .bin 文件"
            )
            text_color = p["warning"]
        elif is_file:
            text = f"VM .bin 输出文件: {configured_path}"
        else:
            text = f"VM .bin 输出目录: {configured_path}"

        self.bin_resolved_label.configure(text=text, text_color=text_color)

    def _relative_vm_bin_path(self, vm_path: str) -> str:
        root = self.app.cm.config.vm_project_path.rstrip("\\/")
        prefix = root + "\\"
        if vm_path.lower().startswith(prefix.lower()):
            return vm_path[len(prefix):]
        return vm_path

    def _autofill_resolved_bin_path(self, vm_path: str):
        rel_path = self._relative_vm_bin_path(vm_path)
        if not rel_path.lower().endswith(".bin"):
            return
        entry = getattr(self, "_entries", {}).get("vm_bin_relative_path")
        current = entry.get().strip() if entry else self.app.cm.config.vm_bin_relative_path
        if current.lower() == rel_path.lower():
            return
        if entry:
            entry.delete(0, "end")
            entry.insert(0, rel_path)
        self.app.cm.config.vm_bin_relative_path = rel_path
        self.app.cm.save()
        if hasattr(self.app, "log_panel"):
            self.app.log_panel.append(
                LogEvent(
                    LogIcon.BIN,
                    f"已自动补全 .bin 相对路径并保存至 config.json 文件: {rel_path}",
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
            self.status_label.configure(text="⚠ 已保存，有警告", text_color=p["warning"])
        elif report.ok:
            self.status_label.configure(text="✓ 已保存，检测通过", text_color=p["success"])
        else:
            self.status_label.configure(text="✗ 已保存，检测失败", text_color=p["error"])
        self.after(2000, lambda: self.status_label.configure(text=""))
        return report

    def _full_sync(self):
        self._save_values_only(emit_log=True)
        report = self.app._run_preflight(for_full_sync=True, show_dialog=True)
        if not report.ok:
            return
        details = report.summary
        if report.warning_text:
            details = f"{details}\n\n警告:\n{report.warning_text}"
        if not messagebox.askyesno(
            "确认全量同步",
            f"{details}\n\n确认执行全量同步吗？",
            parent=self.app.window,
        ):
            self.app.log_panel.append(LogEvent(LogIcon.CANCEL, "已取消全量同步: 用户未确认执行，未修改 VM 工程目录。", "info"))
            return
        self.set_config_enabled(False)
        self.app.control.set_full_sync_active(True)
        self._set_full_sync_button_active(True)
        self._full_sync_thread = threading.Thread(target=self._run_full_sync)
        self._full_sync_thread.start()

    def _cancel_full_sync(self):
        self.app.sync.request_full_sync_cancel()
        self.fullsync_btn.configure(text="取消中...", state="disabled")

    def _run_full_sync(self):
        try:
            self.app.sync.full_sync()
        finally:
            try:
                self.after(0, self._finish_full_sync)
            except tk.TclError:
                pass

    def _finish_full_sync(self):
        enabled = not self.app.sync.running
        self.set_config_enabled(enabled)
        self._set_full_sync_button_active(False, enabled=enabled)
        self.app.control.set_full_sync_active(False)

    def _set_full_sync_button_active(self, active: bool, enabled: bool = True):
        p = current_palette()
        if active:
            self.fullsync_btn.configure(
                text="取消全量同步",
                image=self._cancel_icon,
                command=self._cancel_full_sync,
                state="normal",
                fg_color=p["error"],
                hover_color=p["error"],
                text_color=p["button_text"],
            )
            return
        self.fullsync_btn.configure(
            text="全量同步",
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


# ── Log Panel ────────────────────────────────────────────────

class LogPanel(ctk.CTkFrame):
    MAX_LINES = 500

    def __init__(self, master):
        super().__init__(master, fg_color=current_palette()["card"],
                         border_color=current_palette()["border"], border_width=1,
                         corner_radius=8)
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
            "同步日志",
        )

        self.clear_btn = ctk.CTkButton(
            header, text="清空", width=52, height=26, corner_radius=6,
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


# ── Status Bar ───────────────────────────────────────────────

class StatusBar(ctk.CTkFrame):
    def __init__(self, master, app: "App"):
        super().__init__(master, fg_color="transparent", height=28)
        self.app = app

        self.vm_label = ctk.CTkLabel(
            self, text="● 检查 VM...", font=ui_font(size=11),
            text_color=current_palette()["text_dim"],
        )
        self.vm_label.pack(side="left", padx=(10, 16))

        self.vmrun_label = ctk.CTkLabel(
            self, text="vmrun —", font=ui_font(size=11),
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


# ── Main Application Window ──────────────────────────────────

class App:
    EVENTS_PER_TICK = 40

    def __init__(self, config_manager: ConfigManager, sync_manager: SyncManager):
        self.cm = config_manager
        self.sync = sync_manager

        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        set_windows_app_user_model_id()
        self.window = ctk.CTk()
        self.window.title("VM Sync")
        self.window.geometry("760x860")
        self.window.minsize(680, 720)
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

        self._build_ui()
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        # Tray — show immediately on startup, persists until "退出"
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
            title_frame, text="就绪",
            font=ui_font(size=12),
            text_color=p["text_dim"],
        )
        self.status_text.pack(side="right")

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
        self.config_panel.pack(fill="x", padx=14, pady=(4, 4))

        self.log_panel = LogPanel(self.scroll_area.inner)
        self.log_panel.pack(fill="x", padx=14, pady=(0, 4))
        self.scroll_area.add_wheel_exclusion(self.log_panel.textbox)
        self.scroll_area.add_wheel_exclusion(
            getattr(self.log_panel.textbox, "_textbox", None)
        )

        # Status bar (fixed at bottom)
        self.status_bar = StatusBar(self.window, self)
        self.status_bar.pack(fill="x", padx=18, pady=(0, 8))

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
        self.scroll_area.scrollbar.configure(
            button_color=p["border"], button_hover_color=p["accent"],
        )
        self.scroll_area.canvas.configure(bg=p["bg"])
        self.control.refresh_theme()
        self.config_panel.refresh_theme()
        self.log_panel.refresh_theme()
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
        return pystray.Menu(
            pystray.MenuItem(
                self._tray_status_label,
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("显示窗口", self._tray_show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                self._tray_sync_label,
                self._tray_toggle_sync,
                checked=self._tray_sync_checked,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._tray_quit),
        )

    def _update_tray_menu(self):
        if self._tray_icon:
            self._tray_icon.update_menu()

    def _tray_sync_label(self, _item=None):
        return tray_sync_label(self.sync.running)

    def _tray_status_label(self, _item=None):
        return tray_status_label(self.sync.running)

    def _tray_sync_checked(self, _item=None):
        return self.sync.running

    def _tray_toggle_sync(self):
        if self._shutting_down:
            return
        if self.sync.running:
            self.window.after(0, self.control._pause)
        else:
            self.window.after(0, self.control._start)

    def _tray_notify_start(self):
        if self._tray_icon and self._tray_notified_close:
            try:
                self._tray_icon.notify("VM Sync 已在后台运行", "VM Sync")
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
        if getattr(self.sync, "full_sync_active", False):
            self.sync.request_full_sync_cancel()
        self.sync.stop()
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
            self.status_text.configure(text="运行中", text_color=p["success"])
        else:
            self.status_dot.configure(text_color=p["text_dim"])
            self.status_text.configure(text="已停止", text_color=p["text_dim"])

    def _check_vm_status(self):
        if self._shutting_down:
            return
        p = current_palette()
        vmrun = self.resolve_vmrun_path(save=True)
        if not vmrun:
            self._vmrun_status_state = "unavailable"
            self.status_bar.vmrun_label.configure(
                text="vmrun 不可用", text_color=p["error"]
            )
            self.status_bar.vm_label.configure(
                text="○ VM 状态未知", text_color=p["text_dim"]
            )
        else:
            if getattr(self, "_vmrun_status_state", "unknown") == "unknown":
                self._vmrun_status_state = "checking"
                self.status_bar.vmrun_label.configure(
                    text="vmrun 检查中...", text_color=p["text_dim"]
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
            text=f"轮询间隔 {interval}s"
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
                self.config_panel.load_values()
                vmx = self.cm.config.vmx_path

            if vmx and normalize_vmx_path(vmx) in running:
                self.status_bar.vm_label.configure(
                    text="● VM 运行中", text_color=p["success"]
                )
            elif vmx:
                self.status_bar.vm_label.configure(
                    text="○ VM 未运行", text_color=p["warning"]
                )
            else:
                self.status_bar.vm_label.configure(
                    text="○ 未配置 VMX", text_color=p["text_dim"]
                )
            self.status_bar.vmrun_label.configure(
                text="vmrun 就绪", text_color=p["success"]
            )
            self._vmrun_status_state = "ready"
        else:
            is_timeout = "超时" in result.error
            self.status_bar.vmrun_label.configure(
                text="vmrun 检查超时" if is_timeout else "vmrun 不可用",
                text_color=p["warning"] if is_timeout else p["error"],
            )
            self._vmrun_status_state = "timeout" if is_timeout else "unavailable"
            self.status_bar.vm_label.configure(
                text="○ VM 状态未知", text_color=p["text_dim"]
            )

    # ── Event Polling ────────────────────────────────────

    def _poll_events(self):
        if self._shutting_down:
            return
        self._maybe_check_appearance_change()
        processed = 0
        try:
            while processed < self.EVENTS_PER_TICK:
                event = self.sync.event_queue.get_nowait()
                processed += 1
                event_type, data = event
                if event_type == "log":
                    self.log_panel.append(data)
                elif event_type == "bin_ready":
                    self._on_bin_ready(data)
                elif event_type == "bin_unchanged":
                    self._on_bin_unchanged(data)
                elif event_type == "full_sync_progress":
                    self.log_panel.update_progress(data)
                elif event_type == "info" and data == "sync_stopped":
                    pass
        except queue.Empty:
            pass

        self.control.update_stats(
            self.sync.synced_count,
            self.sync.bin_ready,
        )

        self._schedule_after(200, self._poll_events)

    def _on_bin_ready(self, filename: str):
        if self._tray_icon:
            try:
                self._tray_icon.notify(f"固件已就绪: {filename}", "VM Sync")
            except Exception:
                pass

    def _on_bin_unchanged(self, filename: str):
        if self._tray_icon:
            try:
                self._tray_icon.notify(
                    f"固件内容未变化，已跳过覆盖: {filename}",
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
    ) -> PreflightReport:
        report = PreflightChecker(self.cm.config).check(for_full_sync=for_full_sync)
        if report.ok and not for_full_sync and hasattr(self.sync, "validate_bin_target"):
            bin_report = self.sync.validate_bin_target(emit=False)
            if not bin_report.ok:
                report.errors.append(bin_report.message)
            elif bin_report.level == "warning" and bin_report.message:
                report.warnings.append(bin_report.message)

        if not report.ok:
            now = time.time()
            is_repeat = (
                dedupe_errors
                and report.error_text == self._last_preflight_error
                and now - self._last_preflight_error_time < 10
            )
            if not is_repeat:
                self.log_panel.append(LogEvent(LogIcon.ERROR, f"路径预检失败:\n{report.error_text}", "error"))
                self._last_preflight_error = report.error_text
                self._last_preflight_error_time = now
            if show_dialog:
                messagebox.showerror(
                    "路径预检失败",
                    report.error_text,
                    parent=self.window,
                )
            return report

        if report.warning_text:
            self.log_panel.append(LogEvent(LogIcon.WARNING, f"路径预检警告:\n{report.warning_text}", "warning"))
            if show_dialog:
                messagebox.showwarning(
                    "路径预检警告",
                    report.warning_text,
                    parent=self.window,
                )
        else:
            self.log_panel.append(LogEvent(LogIcon.SUCCESS, "路径预检通过", "success"))
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
