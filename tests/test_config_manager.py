import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config_manager import Config, ConfigManager, ConfigPersistenceError


class ConfigManagerPathNormalizationTests(unittest.TestCase):
    def test_config_example_uses_project_list_schema(self):
        data = json.loads(Path("config.example.json").read_text(encoding="utf-8"))

        self.assertIn("projects", data)
        self.assertNotIn("host_project_path", data)
        self.assertNotIn("vm_project_path", data)
        self.assertEqual(2, len(data["projects"]))
        self.assertTrue(data["projects"][0]["enabled"])
        self.assertFalse(data["projects"][1]["enabled"])
        self.assertIn("active_profile_id", data)
        self.assertEqual(1, len(data["profiles"]))
        self.assertEqual(data["active_profile_id"], data["profiles"][0]["id"])

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

    def test_load_prefers_projects_when_legacy_project_fields_also_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "host_project_path": "C:/legacy/project",
                        "vm_project_path": "C:/legacy/vm",
                        "vm_bin_relative_path": "Output/legacy.bin",
                        "host_output_path": "C:/legacy/out",
                        "projects": [
                            {
                                "enabled": True,
                                "host_project_path": "C:/new/project",
                                "vm_project_path": "C:/new/vm",
                                "vm_bin_relative_path": "Output/new.bin",
                                "host_output_path": "C:/new/out",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            cm = ConfigManager(str(config_path))

        self.assertEqual(r"C:\new\project", cm.config.projects[0].host_project_path)
        self.assertEqual(r"C:\new\vm", cm.config.projects[0].vm_project_path)
        self.assertEqual(r"Output\new.bin", cm.config.projects[0].vm_bin_relative_path)
        self.assertEqual(r"C:\new\out", cm.config.projects[0].host_output_path)

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

    def test_save_skips_rewrite_when_json_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            cm = ConfigManager(str(config_path))
            cm.save()

            with patch("builtins.open", side_effect=AssertionError("unexpected rewrite")):
                cm.save()

    def test_atomic_save_keeps_backup_and_recovers_corrupt_primary(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            cm = ConfigManager(str(config_path))
            cm.config.vmx_path = "D:/VM/one.vmx"
            cm.save()
            cm.config.vmx_path = "D:/VM/two.vmx"
            cm.save()

            backup_path = Path(str(config_path) + ".bak")
            self.assertTrue(backup_path.exists())
            self.assertEqual(
                r"D:\VM\one.vmx",
                json.loads(backup_path.read_text(encoding="utf-8"))["vmx_path"],
            )

            config_path.write_text("{broken", encoding="utf-8")
            recovered = ConfigManager(str(config_path))

            self.assertEqual(r"D:\VM\one.vmx", recovered.config.vmx_path)
            self.assertTrue(Path(str(config_path) + ".corrupt").exists())
            self.assertEqual(
                r"D:\VM\one.vmx",
                json.loads(config_path.read_text(encoding="utf-8"))["vmx_path"],
            )

    def test_profile_create_rolls_back_when_atomic_save_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            cm = ConfigManager(str(Path(tmp) / "config.json"))
            cm.save()
            original_id = cm.config.active_profile_id
            original_count = len(cm.config.profiles)

            with patch(
                "config_manager._atomic_write_text",
                side_effect=ConfigPersistenceError("disk full"),
            ):
                with self.assertRaises(ConfigPersistenceError):
                    cm.create_profile("不能保存", copy_current=False)

            self.assertEqual(original_id, cm.config.active_profile_id)
            self.assertEqual(original_count, len(cm.config.profiles))

    def test_existing_config_is_migrated_to_named_default_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "language": "zh",
                        "vmx_path": "D:/VM/dev.vmx",
                        "vm_guest_user": "builder",
                        "vm_guest_password": "secret",
                        "projects": [
                            {
                                "enabled": True,
                                "host_project_path": "C:/src/firmware",
                                "vm_project_path": "C:/vm/firmware",
                                "vm_bin_relative_path": "Output/app.bin",
                                "host_output_path": "C:/out",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            cm = ConfigManager(str(config_path))
            saved = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual("默认配置", cm.get_active_profile().name)
        self.assertEqual("builder", cm.get_active_profile().vm_guest_user)
        self.assertEqual("secret", saved["profiles"][0]["vm_guest_password"])
        self.assertEqual(saved["active_profile_id"], saved["profiles"][0]["id"])
        self.assertEqual(saved["vmx_path"], saved["profiles"][0]["vmx_path"])
        self.assertEqual(saved["projects"], saved["profiles"][0]["projects"])

    def test_profile_crud_supports_chinese_names_and_persists_active_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            cm = ConfigManager(str(config_path))
            original_id = cm.get_active_profile().id
            cm.config.vmx_path = "D:/VM/one.vmx"
            cm.config.projects[0].host_project_path = "C:/src/one"

            created = cm.create_profile("固件甲", copy_current=True)
            self.assertNotEqual(original_id, created.id)
            self.assertEqual(r"D:\VM\one.vmx", created.vmx_path)
            self.assertEqual(r"C:\src\one", created.projects[0].host_project_path)

            cm.config.projects[0].host_project_path = "C:/src/two"
            cm.save_active_profile("固件乙")
            reloaded = ConfigManager(str(config_path))

            self.assertEqual("固件乙", reloaded.get_active_profile().name)
            self.assertEqual(r"C:\src\two", reloaded.config.projects[0].host_project_path)
            reloaded.activate_profile(original_id)
            self.assertEqual("", reloaded.config.projects[0].host_project_path)

    def test_profile_name_validation_is_unicode_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            cm = ConfigManager(str(Path(tmp) / "config.json"))
            cm.save_active_profile("Firmware")

            with self.assertRaisesRegex(ValueError, "duplicate"):
                cm.create_profile(" firmware ")
            with self.assertRaisesRegex(ValueError, "empty"):
                cm.create_profile("   ")

    def test_rename_profile_by_id_does_not_activate_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            cm = ConfigManager(str(config_path))
            original = cm.get_active_profile()
            other = cm.create_profile("待重命名", copy_current=False)
            cm.activate_profile(original.id)

            renamed = cm.rename_profile(other.id, "离线固件")
            reloaded = ConfigManager(str(config_path))

            self.assertEqual("离线固件", renamed.name)
            self.assertEqual(original.id, cm.config.active_profile_id)
            self.assertEqual(original.id, reloaded.config.active_profile_id)
            self.assertEqual("离线固件", reloaded.get_profile(other.id).name)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                cm.rename_profile(other.id, original.name.upper())
            with self.assertRaisesRegex(ValueError, "empty"):
                cm.rename_profile(other.id, "   ")

    def test_blank_profile_and_delete_restore_adjacent_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            cm = ConfigManager(str(Path(tmp) / "config.json"))
            original = cm.get_active_profile()
            cm.config.vmx_path = "D:/VM/dev.vmx"
            cm.save_active_profile("现有配置")

            blank = cm.create_profile("空白配置", copy_current=False)
            self.assertEqual("", blank.vmx_path)
            self.assertTrue(blank.projects[0].enabled)
            self.assertFalse(blank.projects[1].enabled)

            restored = cm.delete_active_profile()
            self.assertEqual(original.id, restored.id)
            self.assertEqual(r"D:\VM\dev.vmx", cm.config.vmx_path)
            with self.assertRaisesRegex(ValueError, "last_profile"):
                cm.delete_active_profile()


if __name__ == "__main__":
    unittest.main()
