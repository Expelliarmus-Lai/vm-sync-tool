import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from config_manager import ConfigManager
from ui import ConfigPanel


class FakeLabel:
    def __init__(self):
        self.kwargs = {}

    def configure(self, **kwargs):
        self.kwargs.update(kwargs)


class FakeEntry:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def delete(self, *_args):
        self.value = ""

    def insert(self, _index, value):
        self.value = value


class FakePlaceholderEntry(FakeEntry):
    def __init__(self, value=""):
        super().__init__(value)
        self.placeholder_refreshes = 0
        self.draws = 0

    def _entry_focus_out(self):
        self.placeholder_refreshes += 1

    def _draw(self):
        self.draws += 1


class FakeSync:
    def __init__(self, resolved):
        self.resolved = resolved

    def resolve_vm_bin_path_for_display(self):
        return self.resolved


class FakeLogPanel:
    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(event)


class FakeApp:
    def __init__(self, cm, resolved, log_panel=None):
        self.cm = cm
        self.sync = FakeSync(resolved)
        self.log_panel = log_panel

    def resolve_vmrun_path(self, save=False):
        return self.cm.config.vmrun_path


class ConfigPanelBinHintTests(unittest.TestCase):
    def _panel(self, bin_rel, resolved):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cm = ConfigManager(str(Path(tmp.name) / "config.json"))
        cm.config.language = "zh"
        cm.config.vm_project_path = r"C:\Users\h\Desktop\project"
        cm.config.vm_bin_relative_path = bin_rel
        panel = object.__new__(ConfigPanel)
        panel.app = FakeApp(cm, resolved)
        panel.bin_resolved_label = FakeLabel()
        return panel

    def test_directory_bin_path_displays_resolved_single_bin_file(self):
        panel = self._panel(
            r"Output\RL6492",
            (r"C:\Users\h\Desktop\project\Output\RL6492\ActualProject.bin", "ActualProject.bin"),
        )

        panel.update_bin_path_hint(check_guest=True)

        text = panel.bin_resolved_label.kwargs["text"]
        self.assertIn("VM .bin 输出文件", text)
        self.assertIn("已识别 .bin", text)
        self.assertIn("ActualProject.bin", text)
        self.assertIn(r"C:\Users\h\Desktop\project\Output\RL6492\ActualProject.bin", text)

    def test_directory_bin_path_autofills_entry_and_config_when_unique_bin_resolves(self):
        panel = self._panel(
            r"Output\RL6492",
            (r"C:\Users\h\Desktop\project\Output\RL6492\ActualProject.bin", "ActualProject.bin"),
        )
        panel._entries = {"vm_bin_relative_path": FakeEntry(r"Output\RL6492")}
        saves = []
        panel.app.cm.save = lambda: saves.append(panel.app.cm.config.vm_bin_relative_path)

        panel.update_bin_path_hint(check_guest=True)

        self.assertEqual(r"Output\RL6492\ActualProject.bin", panel._entries["vm_bin_relative_path"].get())
        self.assertEqual(r"Output\RL6492\ActualProject.bin", panel.app.cm.config.vm_bin_relative_path)
        self.assertEqual([r"Output\RL6492\ActualProject.bin"], saves)

    def test_autofill_log_does_not_repeat_config_save_wording(self):
        panel = self._panel(
            r"Output\RL6492",
            (r"C:\Users\h\Desktop\project\Output\RL6492\ActualProject.bin", "ActualProject.bin"),
        )
        log_panel = FakeLogPanel()
        panel.app.log_panel = log_panel
        panel._entries = {"vm_bin_relative_path": FakeEntry(r"Output\RL6492")}

        panel.update_bin_path_hint(check_guest=True)

        messages = [event.message for event in log_panel.events]
        self.assertTrue(any("已自动补全 .bin 相对路径" in message for message in messages))
        self.assertFalse(any("保存至 config.json" in message for message in messages))

    def test_save_converts_vm_project_absolute_bin_path_to_relative_and_updates_entry(self):
        panel = self._panel("", None)
        panel._entries = {
            "vm_project_path": FakeEntry(r"C:/Users/h/Desktop/project"),
            "vm_bin_relative_path": FakeEntry(r"C:/Users/h/Desktop/project/Output/RL6492"),
            "host_output_path": FakeEntry(r"C:/Users/h/Desktop/bin"),
        }

        panel._save_values_only()

        self.assertEqual(r"C:\Users\h\Desktop\project", panel.app.cm.config.vm_project_path)
        self.assertEqual(r"Output\RL6492", panel.app.cm.config.vm_bin_relative_path)
        self.assertEqual(r"C:\Users\h\Desktop\bin", panel.app.cm.config.host_output_path)
        self.assertEqual(r"C:\Users\h\Desktop\project", panel._entries["vm_project_path"].get())
        self.assertEqual(r"Output\RL6492", panel._entries["vm_bin_relative_path"].get())
        self.assertEqual(r"C:\Users\h\Desktop\bin", panel._entries["host_output_path"].get())

    def test_save_keeps_outside_absolute_bin_path_for_preflight_rejection(self):
        panel = self._panel("", None)
        panel._entries = {
            "vm_project_path": FakeEntry(r"C:\Users\h\Desktop\project"),
            "vm_bin_relative_path": FakeEntry(r"C:/Users/h/Desktop/other/Output/RL6492"),
        }

        panel._save_values_only()

        self.assertEqual(
            r"C:\Users\h\Desktop\other\Output\RL6492",
            panel.app.cm.config.vm_bin_relative_path,
        )
        self.assertEqual(
            r"C:\Users\h\Desktop\other\Output\RL6492",
            panel._entries["vm_bin_relative_path"].get(),
        )

    def test_browse_normalizes_selected_path_separator(self):
        panel = object.__new__(ConfigPanel)
        panel.app = SimpleNamespace(
            cm=SimpleNamespace(config=SimpleNamespace(vm_project_path=""))
        )
        panel._entries = {"host_project_path": FakeEntry("")}

        with patch("ui.filedialog.askdirectory", return_value=r"C:/Users/h/Desktop/project"):
            panel._browse("host_project_path", "dir")

        self.assertEqual(r"C:\Users\h\Desktop\project", panel._entries["host_project_path"].get())

    def test_empty_replacement_refreshes_placeholder_immediately(self):
        panel = object.__new__(ConfigPanel)
        entry = FakePlaceholderEntry("old value")

        panel._replace_entry_value(entry, "")

        self.assertEqual("", entry.get())
        self.assertEqual(1, entry.placeholder_refreshes)
        self.assertEqual(1, entry.draws)

    def test_directory_bin_path_without_unique_bin_prompts_for_specific_file(self):
        panel = self._panel(r"Output\RL6492", None)

        panel.update_bin_path_hint(check_guest=True)

        text = panel.bin_resolved_label.kwargs["text"]
        self.assertIn("VM .bin 输出目录", text)
        self.assertIn(r"C:\Users\h\Desktop\project\Output\RL6492", text)
        self.assertIn("请选择具体 .bin 文件", text)

    def test_file_bin_path_displays_output_file_label(self):
        panel = self._panel(r"Output\RL6492\firmware.bin", None)

        panel.update_bin_path_hint()

        text = panel.bin_resolved_label.kwargs["text"]
        self.assertIn("VM .bin 输出文件", text)
        self.assertIn(r"C:\Users\h\Desktop\project\Output\RL6492\firmware.bin", text)


if __name__ == "__main__":
    unittest.main()
