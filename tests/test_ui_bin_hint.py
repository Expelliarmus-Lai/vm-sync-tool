import tempfile
import unittest
from pathlib import Path

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


class FakeSync:
    def __init__(self, resolved):
        self.resolved = resolved

    def resolve_vm_bin_path_for_display(self):
        return self.resolved


class FakeApp:
    def __init__(self, cm, resolved):
        self.cm = cm
        self.sync = FakeSync(resolved)


class ConfigPanelBinHintTests(unittest.TestCase):
    def _panel(self, bin_rel, resolved):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cm = ConfigManager(str(Path(tmp.name) / "config.json"))
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
