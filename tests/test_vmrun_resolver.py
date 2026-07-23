import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config_manager import ConfigManager
from vmrun_resolver import list_running_vms, normalize_vmx_path, resolve_vmrun_path


class Completed:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class VmrunResolverTests(unittest.TestCase):
    def test_config_loads_and_saves_vmrun_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            cm = ConfigManager(str(config_path))

            self.assertEqual("", cm.config.vmrun_path)

            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.save()
            reloaded = ConfigManager(str(config_path))

        self.assertEqual(r"C:\VMware\vmrun.exe", reloaded.config.vmrun_path)

    def test_resolve_prefers_existing_configured_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            configured = Path(tmp) / "vmrun.exe"
            configured.write_text("", encoding="utf-8")

            with patch("vmrun_resolver.shutil.which", return_value=None):
                resolved = resolve_vmrun_path(str(configured))

        self.assertEqual(str(configured), resolved)

    def test_resolve_falls_back_to_path_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = Path(tmp) / "vmrun.exe"
            found.write_text("", encoding="utf-8")

            with patch("vmrun_resolver.DEFAULT_VMRUN_PATHS", []), \
                    patch("vmrun_resolver.shutil.which", return_value=str(found)):
                resolved = resolve_vmrun_path(r"C:\missing\vmrun.exe")

        self.assertEqual(str(found), resolved)

    def test_list_running_vms_parses_vmx_paths(self):
        output = "Total running VMs: 2\nC:\\VMs\\A\\A.vmx\nD:\\VMs\\B\\B.vmx\n"
        with patch("vmrun_resolver.subprocess.run", return_value=Completed(stdout=output)):
            result = list_running_vms(r"C:\VMware\vmrun.exe")

        self.assertTrue(result.ok)
        self.assertEqual([r"C:\VMs\A\A.vmx", r"D:\VMs\B\B.vmx"], result.paths)

    def test_list_running_vms_reports_command_failure(self):
        with patch("vmrun_resolver.subprocess.run", return_value=Completed(stderr="bad", returncode=1)):
            result = list_running_vms(r"C:\VMware\vmrun.exe")

        self.assertFalse(result.ok)
        self.assertIn("bad", result.error)

    def test_list_running_vms_accepts_custom_timeout(self):
        with patch("vmrun_resolver.subprocess.run", return_value=Completed()) as run:
            list_running_vms(r"C:\VMware\vmrun.exe", timeout=15)

        self.assertEqual(15, run.call_args.kwargs["timeout"])

    def test_list_running_vms_decodes_utf8_chinese_errors(self):
        expected = "虚拟机未运行"
        with patch(
            "vmrun_resolver.subprocess.run",
            return_value=Completed(stderr=expected.encode("utf-8"), returncode=1),
        ) as run:
            result = list_running_vms(r"C:\VMware\vmrun.exe")

        self.assertEqual(expected, result.error)
        self.assertNotIn("text", run.call_args.kwargs)

    def test_normalize_vmx_path_uses_absolute_casefolded_path(self):
        self.assertEqual(
            normalize_vmx_path(r"C:\VMs\A\..\A\Machine.vmx"),
            normalize_vmx_path(r"c:\vms\a\machine.vmx"),
        )


if __name__ == "__main__":
    unittest.main()
