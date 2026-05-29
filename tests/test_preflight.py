import tempfile
import unittest
from pathlib import Path

from config_manager import Config, ProjectConfig
from preflight import PreflightChecker, PreflightReport
from vmrun_resolver import RunningVmsResult


class PreflightCheckerTests(unittest.TestCase):
    def test_default_watch_extensions_include_legacy_keil_project_files(self):
        exts = {ext.lower() for ext in Config().watch_extensions}
        self.assertIn(".uvprojx", exts)
        self.assertIn(".uvproj", exts)
        self.assertIn(".uv2", exts)
        self.assertIn(".opt", exts)

    def _config(self, host_root: Path, tmp_dir: str) -> Config:
        vmrun = Path(tmp_dir) / "vmrun.exe"
        vmrun.touch()
        vmx = Path(tmp_dir) / "vm.vmx"
        vmx.touch()
        cfg = Config(
            vmrun_path=str(vmrun),
            vmx_path=str(vmx),
            vm_guest_user="admin",
            vm_guest_password="password",
            language="zh",
        )
        proj = ProjectConfig(
            enabled=True,
            host_project_path=str(host_root),
            vm_project_path=r"C:\firmware\RL6492_Project",
            vm_bin_relative_path=r"Output\RL6492\RL6492_Project.bin",
            host_output_path=str(host_root / "out"),
        )
        cfg.projects.append(proj)
        return cfg

    def test_full_sync_summary_counts_syncable_files_and_project_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp) / "project"
            host_root.mkdir()
            (host_root / "main.c").touch()
            (host_root / "RL6492_Project.uvprojx").touch()
            (host_root / "readme.md").touch()
            (host_root / "out").mkdir()

            cfg = self._config(host_root, tmp)
            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(True, [cfg.vmx_path], "")).check()

        self.assertTrue(report.ok)
        self.assertEqual(2, report.project_reports[0].sync_file_count)
        self.assertIn("RL6492_Project.uvprojx", report.summary)

    def test_full_sync_summary_counts_whole_project_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp) / "project"
            host_root.mkdir()
            (host_root / "main.c").touch()
            (host_root / "RL6492_Project.uvprojx").touch()
            (host_root / "readme.md").touch()
            (host_root / "out").mkdir()

            cfg = self._config(host_root, tmp)
            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(True, [cfg.vmx_path], "")).check(for_full_sync=True)

        self.assertTrue(report.ok)
        self.assertEqual(3, report.project_reports[0].sync_file_count)

    def test_rejects_dangerous_vm_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp) / "project"
            host_root.mkdir()
            (host_root / "RL6492_Project.uvprojx").touch()
            (host_root / "out").mkdir()

            cfg = self._config(host_root, tmp)
            cfg.projects[0].vm_project_path = r"C:\\"

            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(True, [cfg.vmx_path], "")).check()

        self.assertFalse(report.ok)

    def test_rejects_host_output_path_when_it_is_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp) / "project"
            host_root.mkdir()
            (host_root / "RL6492_Project.uvprojx").touch()
            output_file = host_root / "out"
            output_file.touch()

            cfg = self._config(host_root, tmp)
            cfg.projects[0].host_output_path = str(output_file)

            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(True, [cfg.vmx_path], "")).check()

        self.assertFalse(report.ok)

    def test_rejects_absolute_bin_relative_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp) / "project"
            host_root.mkdir()
            (host_root / "RL6492_Project.uvprojx").touch()
            (host_root / "out").mkdir()

            cfg = self._config(host_root, tmp)
            cfg.projects[0].vm_bin_relative_path = r"C:\Output\firmware.bin"

            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(True, [cfg.vmx_path], "")).check()

        self.assertFalse(report.ok)

    def test_warns_when_host_project_has_no_keil_project_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp) / "project"
            host_root.mkdir()
            (host_root / "main.c").touch()
            (host_root / "out").mkdir()

            cfg = self._config(host_root, tmp)

            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(True, [cfg.vmx_path], "")).check()

        self.assertTrue(report.ok)

    def test_accepts_legacy_keil_project_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp) / "project"
            host_root.mkdir()
            (host_root / "RL2556VD.uv2").touch()
            (host_root / "out").mkdir()

            cfg = self._config(host_root, tmp)
            cfg.projects[0].vm_bin_relative_path = r"Output\RL2556VD.bin"

            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(True, [cfg.vmx_path], "")).check()

        self.assertTrue(report.ok)
        self.assertEqual("", report.warning_text)

    def test_rejects_missing_vmx_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp) / "project"
            host_root.mkdir()
            (host_root / "RL6492_Project.uvprojx").touch()
            (host_root / "out").mkdir()

            cfg = self._config(host_root, tmp)
            cfg.vmx_path = str(Path(tmp) / "missing.vmx")

            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(True, [], "")).check()

        self.assertFalse(report.ok)

    def test_warns_when_bin_name_does_not_match_project_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp) / "project"
            host_root.mkdir()
            (host_root / "RL6492_Project.uvprojx").touch()
            (host_root / "out").mkdir()

            cfg = self._config(host_root, tmp)
            cfg.projects[0].vm_bin_relative_path = r"Output\OtherFirmware.bin"

            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(True, [cfg.vmx_path], "")).check()

        self.assertTrue(report.ok)

    def test_does_not_warn_about_bin_name_when_bin_path_is_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp) / "project"
            host_root.mkdir()
            (host_root / "RL6492_Project.uvprojx").touch()
            (host_root / "out").mkdir()

            cfg = self._config(host_root, tmp)
            cfg.projects[0].vm_bin_relative_path = r"Output\RL6492"

            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(True, [cfg.vmx_path], "")).check()

        self.assertTrue(report.ok)
        self.assertEqual("", report.warning_text)

    def test_rejects_missing_vmrun_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp) / "project"
            host_root.mkdir()
            (host_root / "RL6492_Project.uvprojx").touch()
            (host_root / "out").mkdir()

            cfg = self._config(host_root, tmp)
            cfg.vmrun_path = ""

            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(True, [cfg.vmx_path], "")).check()

        self.assertFalse(report.ok)

    def test_rejects_missing_guest_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp) / "project"
            host_root.mkdir()
            (host_root / "RL6492_Project.uvprojx").touch()
            (host_root / "out").mkdir()

            cfg = self._config(host_root, tmp)
            cfg.vm_guest_user = ""

            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(True, [cfg.vmx_path], "")).check()

        self.assertFalse(report.ok)

    def test_rejects_missing_vmrun_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp) / "project"
            host_root.mkdir()
            (host_root / "RL6492_Project.uvprojx").touch()
            (host_root / "out").mkdir()

            cfg = self._config(host_root, tmp)
            cfg.vmrun_path = str(Path(tmp) / "missing_vmrun.exe")

            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(True, [cfg.vmx_path], "")).check()

        self.assertFalse(report.ok)

    def test_rejects_configured_vmx_when_not_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp) / "project"
            host_root.mkdir()
            (host_root / "RL6492_Project.uvprojx").touch()
            (host_root / "out").mkdir()

            cfg = self._config(host_root, tmp)

            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(True, [], "")).check()

        self.assertFalse(report.ok)

    def test_rejects_same_vmx_name_in_different_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp) / "project"
            host_root.mkdir()
            (host_root / "RL6492_Project.uvprojx").touch()
            (host_root / "out").mkdir()

            cfg = self._config(host_root, tmp)

            running = [str(Path(tmp) / "other" / "vm.vmx")]
            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(True, running, "")).check()

        self.assertFalse(report.ok)

    def test_rejects_vmrun_list_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp) / "project"
            host_root.mkdir()
            (host_root / "RL6492_Project.uvprojx").touch()
            (host_root / "out").mkdir()

            cfg = self._config(host_root, tmp)

            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(False, [], "Command failed")).check()

        self.assertFalse(report.ok)

    def test_vmrun_timeout_message_suggests_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp) / "project"
            host_root.mkdir()
            (host_root / "RL6492_Project.uvprojx").touch()
            (host_root / "out").mkdir()

            cfg = self._config(host_root, tmp)

            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(False, [], "timeout expired")).check()

        self.assertFalse(report.ok)
        self.assertIn("VMware Authorization Service", report.error_text)

    def test_english_preflight_messages_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp) / "project"
            host_root.mkdir()
            (host_root / "RL6492_Project.uvprojx").touch()
            (host_root / "out").mkdir()

            cfg = self._config(host_root, tmp)
            cfg.language = "en"
            cfg.vm_guest_password = ""

            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(True, [cfg.vmx_path], "")).check()

        self.assertFalse(report.ok)
        self.assertIn("Configure the VM password first", report.error_text)
        self.assertIn("Will watch", report.summary)
        self.assertIn("Project files: RL6492_Project.uvprojx", report.summary)

    def test_rejects_overlapping_host_or_vm_paths_when_two_projects_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "out").mkdir(parents=True, exist_ok=True)
            host1 = root / "p1"
            host1.mkdir(parents=True, exist_ok=True)
            (host1 / "main.c").touch()
            host2 = root / "p1" / "nested"
            host2.mkdir(parents=True, exist_ok=True)
            (host2 / "other.c").touch()

            cfg = self._config(host1, tmp)
            cfg.projects[0].vm_project_path = r"C:\project1"
            p2 = ProjectConfig(
                enabled=True,
                host_project_path=str(host2),
                vm_project_path=r"C:\project2",
                vm_bin_relative_path=r"Output\test.bin",
                host_output_path=str(root / "out"),
            )
            cfg.projects.append(p2)

            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(True, [cfg.vmx_path], "")).check()

            self.assertFalse(report.ok)
            self.assertTrue(any("overlapping host_project_paths" in err for err in report.errors))

            cfg.projects[1].host_project_path = str(root / "p2")
            (root / "p2").mkdir(parents=True, exist_ok=True)
            cfg.projects[1].vm_project_path = r"C:\project1\nested"

            report = PreflightChecker(cfg, lambda _, **kw: RunningVmsResult(True, [cfg.vmx_path], "")).check()
            self.assertFalse(report.ok)
            self.assertTrue(any("overlapping vm_project_paths" in err for err in report.errors))

    def test_rejects_project_overlap_during_single_project_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "out").mkdir(parents=True, exist_ok=True)
            host1 = root / "p1"
            host1.mkdir(parents=True, exist_ok=True)
            (host1 / "main.c").touch()
            host2 = host1 / "nested"
            host2.mkdir(parents=True, exist_ok=True)
            (host2 / "other.c").touch()

            cfg = self._config(host1, tmp)
            cfg.projects[0].vm_project_path = r"C:\project1"
            cfg.projects.append(ProjectConfig(
                enabled=True,
                host_project_path=str(host2),
                vm_project_path=r"C:\project2",
                vm_bin_relative_path=r"Output\test.bin",
                host_output_path=str(root / "out"),
            ))

            report = PreflightChecker(
                cfg,
                lambda _, **kw: RunningVmsResult(True, [cfg.vmx_path], ""),
            ).check(project_index=1)

            self.assertFalse(report.ok)
            self.assertTrue(any("overlapping host_project_paths" in err for err in report.errors))

if __name__ == "__main__":
    unittest.main()
