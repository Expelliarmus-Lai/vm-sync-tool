import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from preflight import PreflightReport
from ui import App, ControlPanel


class FakeButton:
    def __init__(self):
        self.configures = []

    def configure(self, **_kwargs):
        self.configures.append(_kwargs)


class FakeLabel:
    def configure(self, **_kwargs):
        pass


class FakeLogPanel:
    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(event)


class StartButtonTests(unittest.TestCase):
    def test_start_button_runs_sync_start_in_background(self):
        source = inspect.getsource(ControlPanel._start)

        self.assertIn("threading.Thread", source)
        self.assertNotIn("save_and_check()", source)

    def test_start_worker_uses_prechecked_fast_start(self):
        calls = []

        class FakeSync:
            def preflight_snapshot(self):
                return ("saved-config",)

            def start(self, **kwargs):
                calls.append(kwargs)
                return True

        panel = object.__new__(ControlPanel)
        panel.app = SimpleNamespace(sync=FakeSync())
        panel._start_preflight_snapshot = ("saved-config",)
        panel.after = lambda _delay, callback: callback()
        panel._finish_start = lambda started, error="": calls.append(("finish", started, error))

        ControlPanel._start_worker(panel)

        self.assertIn(
            {
                "preflight_checked": True,
                "preflight_snapshot": ("saved-config",),
            },
            calls,
        )
        self.assertIn(("finish", True, ""), calls)

    def test_start_button_saves_values_and_defers_preflight_to_background(self):
        calls = []

        class FakeConfigPanel:
            def _save_values_only(self, emit_log=False):
                calls.append(("save_values", emit_log))

            def mark_start_checking(self):
                calls.append("mark_checking")

            def set_config_enabled(self, enabled):
                calls.append(("config_enabled", enabled))

            def save_and_check(self):
                calls.append("save_and_check")
                raise AssertionError("start should not run slow preflight on the UI thread")

        class FakeThread:
            def __init__(self, target, daemon=False):
                calls.append("thread_created")
                self.target = target
                self.daemon = daemon

            def start(self):
                calls.append("thread_started")

        panel = object.__new__(ControlPanel)
        panel.app = SimpleNamespace(config_panel=FakeConfigPanel())
        panel.start_btn = FakeButton()
        panel._start_preflight_snapshot = None

        class FakeSync:
            def preflight_snapshot(self):
                calls.append("snapshot")
                return ("saved-config",)

        panel.app.sync = FakeSync()

        with patch("ui.threading.Thread", FakeThread):
            ControlPanel._start(panel)

        self.assertEqual(
            [
                ("save_values", True),
                "mark_checking",
                ("config_enabled", False),
                "thread_created",
                "thread_started",
            ],
            calls,
        )
        self.assertIsNone(panel._start_preflight_snapshot)

    def test_start_worker_does_not_start_when_background_preflight_fails(self):
        calls = []

        class FakeSync:
            running = False

            def start(self, **_kwargs):
                calls.append("start")
                raise AssertionError("sync should not start after failed preflight")

        panel = object.__new__(ControlPanel)
        panel.app = SimpleNamespace(
            sync=FakeSync(),
            sync_managers=[FakeSync()],
            get_sync_manager=lambda _index=0: panel.app.sync_managers[0],
            _collect_preflight_report=lambda **_kwargs: PreflightReport(errors=["bad path"]),
            _emit_preflight_report=lambda report, **_kwargs: calls.append(("preflight", report.ok)),
            project_panels={},
        )
        panel.start_btn = FakeButton()
        panel.pause_btn = FakeButton()
        panel.uptime_label = FakeLabel()
        panel.after = lambda _delay, callback: callback()
        panel._set_stopped = lambda: calls.append("stopped")
        panel._enabled_project_indexes = lambda: [0]
        panel._start_preflight_snapshots = {}

        ControlPanel._start_worker(panel)

        self.assertEqual([("preflight", False), "stopped"], calls)

    def test_repeated_preflight_errors_are_deduplicated(self):
        source = inspect.getsource(App._run_preflight)

        self.assertIn("_last_preflight_error", source)

    def test_save_preflight_includes_guest_bin_validation_error(self):
        app = object.__new__(App)
        app.cm = SimpleNamespace(config=SimpleNamespace())
        app.sync = SimpleNamespace(
            validate_bin_target=lambda emit=False: SimpleNamespace(
                ok=False,
                level="error",
                message=r"虚拟机 .bin 文件不存在: Output\wrong.bin",
            )
        )
        app.log_panel = FakeLogPanel()
        app.window = None
        app._last_preflight_error = ""
        app._last_preflight_error_time = 0.0

        class FakeChecker:
            def __init__(self, _config):
                pass

            def check(self, for_full_sync=False):
                return PreflightReport()

        with patch("ui.PreflightChecker", FakeChecker):
            report = app._run_preflight()

        self.assertFalse(report.ok)
        self.assertIn(".bin", report.error_text)
        self.assertTrue(any(event.level == "error" for event in app.log_panel.events))

    def test_save_preflight_repeated_errors_are_not_deduplicated(self):
        app = object.__new__(App)
        app.cm = SimpleNamespace(config=SimpleNamespace())
        app.sync = SimpleNamespace(
            validate_bin_target=lambda emit=False: SimpleNamespace(
                ok=True,
                level="success",
                message="",
            )
        )
        app.log_panel = FakeLogPanel()
        app.window = None
        app._last_preflight_error = ""
        app._last_preflight_error_time = 0.0

        class FakeChecker:
            def __init__(self, _config):
                pass

            def check(self, for_full_sync=False):
                return PreflightReport(errors=["same error"])

        with patch("ui.PreflightChecker", FakeChecker):
            app._run_preflight(dedupe_errors=False)
            app._run_preflight(dedupe_errors=False)

        error_events = [
            event for event in app.log_panel.events
            if event.level == "error"
        ]
        self.assertEqual(2, len(error_events))

    def test_start_failure_appends_visible_log(self):
        panel = object.__new__(ControlPanel)
        panel.app = SimpleNamespace(log_panel=FakeLogPanel())
        panel._set_stopped = lambda: None

        ControlPanel._finish_start(panel, False)

        self.assertTrue(any(event.level == "error" for event in panel.app.log_panel.events))
        self.assertTrue(any("启动" in event.message for event in panel.app.log_panel.events))

    def test_pause_failure_appends_visible_log(self):
        panel = object.__new__(ControlPanel)
        panel.app = SimpleNamespace(
            sync=SimpleNamespace(stop=lambda: (_ for _ in ()).throw(RuntimeError("stop failed"))),
            log_panel=FakeLogPanel(),
        )
        panel.start_btn = FakeButton()
        panel.pause_btn = FakeButton()
        panel.uptime_label = FakeLabel()
        panel._set_stopped = lambda: None

        ControlPanel._pause(panel)

        self.assertTrue(any(event.level == "error" for event in panel.app.log_panel.events))
        self.assertTrue(any("暂停" in event.message for event in panel.app.log_panel.events))


if __name__ == "__main__":
    unittest.main()
