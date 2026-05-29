import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config_manager import ConfigManager
from config_manager import Config


class ConfigManagerPathNormalizationTests(unittest.TestCase):
    def test_default_bin_path_is_not_project_specific(self):
        self.assertNotIn("RL6492_Project.bin", Config().vm_bin_relative_path)

    def test_default_bin_poll_interval_is_fast(self):
        self.assertEqual(1, Config().poll_interval_sec)

    def test_save_normalizes_config_paths_to_windows_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            cm = ConfigManager(str(config_path))
            cm.config.vmrun_path = "C:/Program Files (x86)/VMware/VMware Workstation/vmrun.exe"
            cm.config.vmx_path = "D:/windows/Windows 10 VM_HW/Windows 10 x64/Windows 10 x64.vmx"
            cm.config.host_project_path = "C:/Users/Administrator/Desktop/鍚屾娴嬭瘯/js_2556vd_6282"
            cm.config.vm_project_path = "C:/Users/h/Desktop/js_2556vd_6282"
            cm.config.vm_bin_relative_path = "/Output/RL6492"
            cm.config.host_output_path = "C:/Users/Administrator/Desktop"

            cm.save()

            data = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(
            r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe",
            data["vmrun_path"],
        )
        self.assertEqual(
            r"D:\windows\Windows 10 VM_HW\Windows 10 x64\Windows 10 x64.vmx",
            data["vmx_path"],
        )
        self.assertEqual(
            r"C:\Users\Administrator\Desktop\鍚屾娴嬭瘯\js_2556vd_6282",
            data["projects"][0]["host_project_path"],
        )
        self.assertEqual(
            r"C:\Users\h\Desktop\js_2556vd_6282",
            data["projects"][0]["vm_project_path"],
        )
        self.assertEqual(r"Output\RL6492", data["projects"][0]["vm_bin_relative_path"])
        self.assertEqual(r"C:\Users\Administrator\Desktop", data["projects"][0]["host_output_path"])

    def test_load_rewrites_legacy_mixed_separator_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "vmrun_path": "C:/VMware/vmrun.exe",
                        "vmx_path": "D:/VMs/dev/dev.vmx",
                        "host_project_path": "C:/work/project",
                        "vm_project_path": "C:/Users/h/Desktop/project",
                        "vm_bin_relative_path": "\\Output/RL6492",
                        "host_output_path": "C:/Users/Administrator/Desktop",
                    }
                ),
                encoding="utf-8",
            )

            cm = ConfigManager(str(config_path))
            data = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(r"C:\VMware\vmrun.exe", cm.config.vmrun_path)
        self.assertEqual(r"D:\VMs\dev\dev.vmx", data["vmx_path"])
        self.assertEqual(r"Output\RL6492", data["projects"][0]["vm_bin_relative_path"])

    def test_load_upgrades_legacy_bin_poll_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                json.dumps({"poll_interval_sec": 3}),
                encoding="utf-8",
            )

            cm = ConfigManager(str(config_path))
            data = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(1, cm.config.poll_interval_sec)
        self.assertEqual(1, data["poll_interval_sec"])

    def test_load_adds_detected_language_to_legacy_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(json.dumps({}), encoding="utf-8")

            with patch("config_manager.detect_system_language", return_value="en"):
                cm = ConfigManager(str(config_path))

            data = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual("en", cm.config.language)
        self.assertEqual("en", data["language"])

    def test_invalid_language_falls_back_to_detected_language(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                json.dumps({"language": "fr"}),
                encoding="utf-8",
            )

            with patch("config_manager.detect_system_language", return_value="zh"):
                cm = ConfigManager(str(config_path))

            data = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual("zh", cm.config.language)
        self.assertEqual("zh", data["language"])

    def test_absolute_bin_path_stays_absolute_for_preflight_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            cm = ConfigManager(str(config_path))
            cm.config.vm_bin_relative_path = "C:/Output/firmware.bin"

            cm.save()

        self.assertEqual(r"C:\Output\firmware.bin", cm.config.vm_bin_relative_path)


if __name__ == "__main__":
    unittest.main()
