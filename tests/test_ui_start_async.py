import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from preflight import PreflightReport
from ui import App, ControlPanel


class FakeButton:
    def configure(self, **_kwargs):
        pass


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
        self.assertNotIn("_validate_and_save", source)

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
                message=r"VM .bin 文件不存在: Output\wrong.bin",
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
