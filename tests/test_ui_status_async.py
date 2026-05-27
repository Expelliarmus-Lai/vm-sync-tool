import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from syncer import LogIcon
from ui import App
from vmrun_resolver import RunningVmsResult


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
            vmrun_label=FakeLabel(f"{LogIcon.SUCCESS} vmrun 就绪"),
            vm_label=FakeLabel(f"{LogIcon.SUCCESS} VM 运行中"),
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
        self.assertNotIn(f"{LogIcon.CHECK} vmrun 检查中...", vmrun_texts)
        self.assertEqual(f"{LogIcon.SUCCESS} vmrun 就绪", app.status_bar.vmrun_label.text)

    def test_status_bar_uses_log_icons_for_vm_and_vmrun_states(self):
        app = object.__new__(App)
        app._shutting_down = False
        app._status_check_running = False
        app.cm = SimpleNamespace(
            config=SimpleNamespace(
                vmx_path=r"C:\VMs\dev.vmx",
                poll_interval_sec=1,
            ),
            save=lambda: None,
        )
        app.status_bar = SimpleNamespace(
            vmrun_label=FakeLabel(""),
            vm_label=FakeLabel(""),
            poll_label=FakeLabel(""),
        )
        app.config_panel = SimpleNamespace(load_values=lambda: None)

        app._apply_vm_status_result(
            r"C:\VMware\vmrun.exe",
            r"C:\VMs\dev.vmx",
            RunningVmsResult(True, [r"C:\VMs\dev.vmx"], ""),
        )

        self.assertEqual(f"{LogIcon.SUCCESS} VM 运行中", app.status_bar.vm_label.text)
        self.assertEqual(f"{LogIcon.SUCCESS} vmrun 就绪", app.status_bar.vmrun_label.text)

    def test_status_check_uses_log_icons_for_unavailable_and_poll_labels(self):
        app = object.__new__(App)
        app._shutting_down = False
        app._status_check_running = False
        app._vmrun_status_state = "unknown"
        app.cm = SimpleNamespace(
            config=SimpleNamespace(poll_interval_sec=1, vmx_path="")
        )
        app.status_bar = SimpleNamespace(
            vmrun_label=FakeLabel(""),
            vm_label=FakeLabel(""),
            poll_label=FakeLabel(""),
        )
        app.resolve_vmrun_path = lambda save=False: ""
        app._schedule_after = lambda *_args, **_kwargs: None

        app._check_vm_status()

        self.assertEqual(f"{LogIcon.ERROR} vmrun 不可用", app.status_bar.vmrun_label.text)
        self.assertEqual(f"{LogIcon.INFO} VM 状态未知", app.status_bar.vm_label.text)
        self.assertEqual(f"{LogIcon.BIN} .bin 轮询 1s", app.status_bar.poll_label.text)

    def test_title_status_indicator_uses_start_and_stop_log_icons(self):
        app = object.__new__(App)
        app.status_dot = FakeLabel("")
        app.status_text = FakeLabel("")

        app._update_status_indicator(True)
        self.assertEqual(LogIcon.START, app.status_dot.text)
        self.assertEqual("运行中", app.status_text.text)

        app._update_status_indicator(False)
        self.assertEqual(LogIcon.STOP, app.status_dot.text)
        self.assertEqual("已停止", app.status_text.text)


if __name__ == "__main__":
    unittest.main()
