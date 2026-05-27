import inspect
import unittest
from types import SimpleNamespace

from ui import App, AutoScrollFrame, ConfigPanel, ControlPanel, DARK, LIGHT


class FullSyncUiTests(unittest.TestCase):
    def test_full_sync_button_does_not_start_background_service(self):
        source = inspect.getsource(ConfigPanel._full_sync)

        self.assertNotIn(".sync.start(", source)

    def test_full_sync_ui_uses_full_sync_label(self):
        source = inspect.getsource(ConfigPanel)

        self.assertIn("全量同步", source)
        self.assertNotIn("首次同步", source)

    def test_config_uses_firmware_return_directory_label(self):
        source = inspect.getsource(ConfigPanel)

        self.assertIn("固件回传目录", source)
        self.assertNotIn("宿主机输出路径", source)

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

    def test_main_window_starts_large_and_has_no_small_max_size_cap(self):
        source = inspect.getsource(App.__init__)

        self.assertIn('geometry("760x860")', source)
        self.assertIn("minsize(680, 720)", source)
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
        self.assertIn("_finish_full_sync", worker_source)
        self.assertIn("control.set_full_sync_active(False)", finish_source)
        self.assertIn("set_config_enabled(enabled)", finish_source)

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
