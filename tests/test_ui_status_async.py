import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from i18n import Translator
from ui import App


class FakeLabel:
    def __init__(self, text=""):
        self.text = text
        self.configures = []

    def configure(self, **kwargs):
        self.configures.append(kwargs)
        if "text" in kwargs:
            self.text = kwargs["text"]


class FakeThread:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.started = False

    def start(self):
        self.started = True


class StatusCheckTests(unittest.TestCase):
    def test_vm_status_check_starts_background_worker(self):
        source = inspect.getsource(App._check_vm_status)

        self.assertIn("threading.Thread", source)
        self.assertNotIn("list_running_vms(vmrun)", source)

    def test_vmrun_ready_status_is_kept_while_rechecking(self):
        app = object.__new__(App)
        app._shutting_down = False
        app._status_check_running = False
        app._vmrun_status_state = "ready"
        app.cm = SimpleNamespace(
            config=SimpleNamespace(poll_interval_sec=3, vmx_path=r"C:\VMs\dev.vmx")
        )
        app.status_bar = SimpleNamespace(
            vmrun_label=FakeLabel("vmrun 就绪"),
            vm_label=FakeLabel("● 虚拟机运行中"),
            poll_label=FakeLabel(""),
        )
        app.resolve_vmrun_path = lambda save=False: r"C:\VMware\vmrun.exe"
        app._schedule_after = lambda *_args, **_kwargs: None

        with patch("ui.threading.Thread", FakeThread):
            app._check_vm_status()

        vmrun_texts = [
            kwargs["text"]
            for kwargs in app.status_bar.vmrun_label.configures
            if "text" in kwargs
        ]
        self.assertNotIn("vmrun 检查中...", vmrun_texts)
        self.assertEqual("vmrun 就绪", app.status_bar.vmrun_label.text)

    def test_bin_return_status_lists_each_enabled_project_time(self):
        app = object.__new__(App)
        app.cm = SimpleNamespace(
            config=SimpleNamespace(
                language="zh",
                projects=[
                    SimpleNamespace(enabled=True),
                    SimpleNamespace(enabled=True),
                ],
            )
        )
        app._latest_bin_return_times = {0: 1717215306.0}

        text = App._format_bin_return_status(app, bin_ready=False)

        self.assertIn(".bin", text)
        self.assertIn("项目 1", text)
        self.assertIn("12:15:06", text)
        self.assertIn("项目 2 未回传", text)
        self.assertIn("  |  ", text)

    def test_single_project_bin_return_status_stays_compact(self):
        app = object.__new__(App)
        app.cm = SimpleNamespace(
            config=SimpleNamespace(
                language="en",
                projects=[SimpleNamespace(enabled=True)],
            )
        )
        app._latest_bin_return_times = {0: 1717215306.0}

        text = App._format_bin_return_status(app, bin_ready=True)

        self.assertIn(Translator("en").tr("ui.bin.ready"), text)
        self.assertIn("Latest 06-01 12:15:06", text)
        self.assertNotIn("Project 1", text)

    def test_bin_ready_records_returned_at_and_accepts_legacy_mtime(self):
        app = object.__new__(App)
        app._tray_icon = None
        app._latest_bin_return_times = {}

        App._on_bin_ready(
            app,
            {"filename": "firmware.bin", "returned_at": 1753243200.0},
            1,
        )
        App._on_bin_ready(
            app,
            {"filename": "legacy.bin", "local_mtime": 1753243300.0},
            0,
        )

        self.assertEqual(1753243200.0, app._latest_bin_return_times[1])
        self.assertEqual(1753243300.0, app._latest_bin_return_times[0])


if __name__ == "__main__":
    unittest.main()
