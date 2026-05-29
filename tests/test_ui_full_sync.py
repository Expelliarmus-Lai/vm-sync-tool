import inspect
import tkinter as tk
import unittest
from types import SimpleNamespace

from i18n import Translator
from ui import App, AutoScrollFrame, ConfigPanel, ControlPanel, DARK, LIGHT


class FullSyncUiTests(unittest.TestCase):
    def test_full_sync_button_does_not_start_background_service(self):
        source = inspect.getsource(ConfigPanel._full_sync)

        self.assertNotIn(".sync.start(", source)

    def test_full_sync_ui_uses_full_sync_label(self):
        source = inspect.getsource(ConfigPanel)

        self.assertEqual("全量同步", Translator("zh").tr("ui.button.full_sync"))
        self.assertIn("ui.button.full_sync", source)
        self.assertNotIn("首次同步", source)

    def test_title_bar_has_language_switch(self):
        source = inspect.getsource(App._build_ui)

        self.assertIn("CTkSegmentedButton", source)
        self.assertIn("_on_language_selected", source)
        self.assertIn("set_language", inspect.getsource(App))

    def test_config_uses_firmware_return_directory_label(self):
        source = inspect.getsource(ConfigPanel)

        self.assertEqual("固件回传目录", Translator("zh").tr("ui.config.field.host_output"))
        self.assertEqual("Firmware return folder", Translator("en").tr("ui.config.field.host_output"))
        self.assertIn("ui.config.field.host_output", source)

    def test_config_placeholders_are_short_and_specific(self):
        zh = Translator("zh")

        self.assertEqual("当前运行 VM 的 .vmx", zh.tr("ui.config.placeholder.vmx"))
        self.assertEqual("VM Windows 登录用户名", zh.tr("ui.config.placeholder.vm_user"))
        self.assertEqual("VM Windows 登录密码", zh.tr("ui.config.placeholder.vm_password"))
        self.assertEqual("宿主机 Keil 工程根目录", zh.tr("ui.config.placeholder.host_project"))
        self.assertEqual(r"VM 内工程根目录，如 C:\project", zh.tr("ui.config.placeholder.vm_project"))
        self.assertEqual(r"相对 VM 工程，如 Output\RL6492", zh.tr("ui.config.placeholder.bin"))
        self.assertEqual("宿主机固件回传目录", zh.tr("ui.config.placeholder.host_output"))

    def test_config_panel_refreshes_empty_placeholders_after_build(self):
        source = inspect.getsource(ConfigPanel._build)

        self.assertIn("_refresh_entry_placeholders", source)
        self.assertIn("after_idle", source)

    def test_background_click_clears_entry_focus(self):
        app = object.__new__(App)

        class FakeWindow:
            def __init__(self):
                self.focus_calls = 0

            def focus_set(self):
                self.focus_calls += 1

        class FakeWidget:
            def __init__(self, class_name, master=None):
                self.class_name = class_name
                self.master = master

            def winfo_class(self):
                return self.class_name

        app.window = FakeWindow()
        entry = FakeWidget("Entry")
        entry_child = FakeWidget("Canvas", master=entry)
        label = FakeWidget("Label")

        self.assertTrue(App._is_text_input_event_widget(app, entry_child))
        self.assertFalse(App._is_text_input_event_widget(app, label))

        App._clear_entry_focus_on_background_click(app, SimpleNamespace(widget=entry_child))
        App._clear_entry_focus_on_background_click(app, SimpleNamespace(widget=label))

        self.assertEqual(1, app.window.focus_calls)

    def test_section_headers_use_vector_icons(self):
        source = inspect.getsource(ConfigPanel)

        self.assertIn('"sliders"', source)
        self.assertIn("pack_section_title", source)
        self.assertIn('"check"', source)
        self.assertIn('"upload"', source)
        self.assertIn('"folder"', source)
        self.assertIn("width=42", source)
        self.assertIn("height=32", source)
        self.assertNotIn("▣  配置", source)
        self.assertNotIn("⚙  配 置", source)
        self.assertNotIn("💾 保存并检测", source)
        self.assertNotIn("↻  全量同步", source)

    def test_palette_has_unified_button_and_hint_tokens(self):
        for palette in (DARK, LIGHT):
            self.assertIn("button_text", palette)
            self.assertIn("muted_button", palette)
            self.assertIn("muted_hover", palette)
            self.assertIn("hint_bg", palette)

    def test_config_panel_can_disable_path_controls(self):
        source = inspect.getsource(ConfigPanel)

        self.assertIn("def set_config_enabled", source)
        self.assertIn("_browse_buttons", source)
        self.assertIn("entry.configure(state=state)", source)
        self.assertIn("button.configure(state=state)", source)
        self.assertIn("self.save_btn.configure(state=state)", source)
        self.assertIn("self.fullsync_btn.configure(state=state)", source)

    def test_start_and_pause_toggle_config_panel_enabled_state(self):
        start_source = inspect.getsource(ControlPanel._start)
        stopped_source = inspect.getsource(ControlPanel._set_stopped)

        self.assertIn("config_panel.set_config_enabled(False)", start_source)
        self.assertIn("config_panel.set_config_enabled(True)", stopped_source)

    def test_save_button_forces_preflight_log_feedback(self):
        source = inspect.getsource(ConfigPanel._save)

        self.assertIn("save_and_check", source)

    def test_save_values_logs_config_path_when_requested(self):
        saved = []

        class FakeEntry:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

        class FakeConfigManager:
            config_path = r"C:\tools\VM Sync\config.json"

            def __init__(self):
                self.config = type("Config", (), {})()

            def save(self):
                saved.append("save")

        class FakeLogPanel:
            def __init__(self):
                self.events = []

            def append(self, event):
                self.events.append(event)

        cm = FakeConfigManager()
        log_panel = FakeLogPanel()
        panel = object.__new__(ConfigPanel)
        panel.app = type("App", (), {})()
        panel.app.cm = cm
        panel.app.log_panel = log_panel
        panel.app.resolve_vmrun_path = lambda save=False: ""
        panel._entries = {
            "host_project_path": FakeEntry(r"C:\project"),
            "vm_project_path": FakeEntry(r"C:\vm_project"),
        }

        ConfigPanel._save_values_only(panel, emit_log=True)

        self.assertEqual(["save"], saved)
        self.assertEqual(r"C:\project", cm.config.host_project_path)
        self.assertEqual(r"C:\vm_project", cm.config.vm_project_path)
        self.assertTrue(any("路径已保存至 config.json 文件" in event.message for event in log_panel.events))
        self.assertTrue(any("config.json" in event.message for event in log_panel.events))

    def test_start_pause_buttons_use_larger_aligned_icons(self):
        source = inspect.getsource(ControlPanel.__init__)

        self.assertIn('"play",\n            19', source)
        self.assertIn('"pause",\n            19', source)
        self.assertIn('anchor="center"', source)
        self.assertIn("width=132", source)
        self.assertIn("height=40", source)

    def test_config_action_buttons_use_larger_icons(self):
        source = inspect.getsource(ConfigPanel.__init__)

        self.assertIn('"check",\n            18', source)
        self.assertIn('"upload",\n            18', source)

    def test_save_check_button_has_comfortable_text_padding(self):
        source = inspect.getsource(ConfigPanel._build)

        self.assertIn("SAVE_CHECK_BUTTON_WIDTH", source)
        self.assertIn("ACTION_BUTTON_BORDER_SPACING", source)

    def test_save_check_status_uses_log_icons_only_in_config_hint(self):
        save_source = inspect.getsource(ConfigPanel.save_and_check)
        control_source = inspect.getsource(ControlPanel)

        for icon_name in ("WARNING", "SUCCESS", "ERROR"):
            self.assertIn(f"LogIcon.{icon_name}", save_source)
        self.assertNotIn('"✓', save_source)
        self.assertNotIn('"✗', save_source)
        self.assertEqual(".bin    就绪 ✓", Translator("zh").tr("ui.bin.ready"))
        self.assertIn("ui.bin.ready", control_source)

    def test_main_window_starts_large_and_has_no_small_max_size_cap(self):
        source = inspect.getsource(App.__init__)

        self.assertIn("SINGLE_PROJECT_GEOMETRY", source)
        self.assertIn("SINGLE_PROJECT_MIN_SIZE", source)
        self.assertNotIn('geometry("760x860")', source)
        self.assertNotIn("minsize(680, 720)", source)
        self.assertNotIn("maxsize(900, 780)", source)

    def test_polling_and_stats_avoid_unnecessary_repaints(self):
        app_source = inspect.getsource(App._poll_events)
        control_init_source = inspect.getsource(ControlPanel.__init__)
        control_update_source = inspect.getsource(ControlPanel.update_stats)

        self.assertIn("_maybe_check_appearance_change", app_source)
        self.assertIn("_last_sync_count", control_init_source)
        self.assertIn("if sync_count != self._last_sync_count", control_update_source)
        self.assertIn("if bin_ready != self._last_bin_ready", control_update_source)
        self.assertIn("processed < self.EVENTS_PER_TICK", app_source)

    def test_outer_scroll_uses_global_wheel_with_log_exclusion(self):
        frame_source = inspect.getsource(AutoScrollFrame)
        build_source = inspect.getsource(App._build_ui)

        self.assertIn("add_wheel_exclusion", frame_source)
        self.assertIn("_is_wheel_excluded", frame_source)
        self.assertIn("bind_all", frame_source)
        self.assertNotIn("unbind_all", frame_source)
        self.assertIn("add_wheel_exclusion(self.log_panel.textbox)", build_source)

    def test_outer_scroll_does_not_force_layout_during_configure(self):
        source = inspect.getsource(AutoScrollFrame)

        self.assertIn("_last_canvas_size", source)
        self.assertIn("_schedule_scroll_sync", source)
        self.assertIn("after_idle", source)
        self.assertNotIn("update_idletasks", source)

    def test_full_sync_disables_config_until_worker_finishes(self):
        full_sync_source = inspect.getsource(ConfigPanel._full_sync)
        worker_source = inspect.getsource(ConfigPanel._run_full_sync)
        finish_source = inspect.getsource(ConfigPanel._finish_full_sync)

        self.assertIn("set_config_enabled(False)", full_sync_source)
        self.assertIn("control.set_full_sync_active(True)", full_sync_source)
        self.assertIn("_set_project_toggle_enabled(False)", full_sync_source)
        self.assertIn("_finish_full_sync", worker_source)
        self.assertIn("control.set_full_sync_active(False)", finish_source)
        self.assertIn("set_config_enabled(enabled)", finish_source)
        self.assertIn("_set_project_toggle_enabled(enabled)", finish_source)

    def test_finish_full_sync_ignores_tcl_error_after_shutdown(self):
        panel = object.__new__(ConfigPanel)
        panel.app = SimpleNamespace(
            sync=SimpleNamespace(running=False),
            control=SimpleNamespace(set_full_sync_active=lambda _active: None),
        )

        def raise_tcl_error(*_args, **_kwargs):
            raise tk.TclError("widget destroyed")

        panel.set_config_enabled = raise_tcl_error
        panel._set_full_sync_button_active = lambda *_args, **_kwargs: None

        ConfigPanel._finish_full_sync(panel)

    def test_cancel_full_sync_requests_cancel_and_disables_button(self):
        calls = []

        class FakeButton:
            def configure(self, **kwargs):
                calls.append(("button", kwargs))

        class FakeSync:
            def request_full_sync_cancel(self):
                calls.append("cancel")

        class FakeLogPanel:
            def append(self, event):
                calls.append(("log", event.message))

        panel = object.__new__(ConfigPanel)
        panel.app = SimpleNamespace(sync=FakeSync(), log_panel=FakeLogPanel())
        panel.fullsync_btn = FakeButton()

        ConfigPanel._cancel_full_sync(panel)

        self.assertIn("cancel", calls)
        self.assertTrue(any(item[0] == "button" and item[1].get("state") == "disabled" for item in calls))
        self.assertFalse(any(item[0] == "log" for item in calls))

    def test_control_full_sync_active_disables_start_button(self):
        calls = []

        class FakeButton:
            def configure(self, **kwargs):
                calls.append(kwargs)

        control = object.__new__(ControlPanel)
        control.start_btn = FakeButton()

        ControlPanel.set_full_sync_active(control, True)

        self.assertTrue(any(kwargs.get("state") == "disabled" for kwargs in calls))


if __name__ == "__main__":
    unittest.main()
