import tempfile
import unittest
from pathlib import Path

from config_manager import Config
from preflight import PreflightChecker
from vmrun_resolver import RunningVmsResult


class PreflightCheckerTests(unittest.TestCase):
    def test_default_watch_extensions_include_legacy_keil_project_files(self):
        exts = {ext.lower() for ext in Config().watch_extensions}

        self.assertTrue({".uvproj", ".uvopt", ".uv2", ".opt"}.issubset(exts))

    def _project(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "RL6492_Project.uvprojx").write_text("<Project />", encoding="utf-8")
        (root / "main.c").write_text("int main(void) { return 0; }", encoding="utf-8")
        (root / "driver.h").write_text("#pragma once\n", encoding="utf-8")
        return root

    def _config(self, host_root: Path):
        return Config(
            vmrun_path=str(host_root / "vmrun.exe"),
            vmx_path=str(host_root / "vm.vmx"),
            vm_guest_user="h",
            vm_guest_password="password",
            host_project_path=str(host_root),
            vm_project_path=r"C:\firmware\RL6492_Project",
            vm_bin_relative_path=r"Output\RL6492\RL6492_Project.bin",
            host_output_path=str(host_root / "out"),
        )

    def _valid_project(self):
        host_root = self._project()
        (host_root / "vm.vmx").write_text("", encoding="utf-8")
        (host_root / "vmrun.exe").write_text("", encoding="utf-8")
        return host_root

    def _check(self, cfg, for_full_sync=False, running_paths=None):
        if running_paths is None:
            running_paths = [cfg.vmx_path]
        return PreflightChecker(
            cfg,
            running_vms_provider=lambda _path: RunningVmsResult(True, running_paths),
        ).check(for_full_sync=for_full_sync)

    def test_full_sync_summary_counts_syncable_files_and_project_file(self):
        host_root = self._valid_project()
        cfg = self._config(host_root)

        report = self._check(cfg, for_full_sync=True)

        self.assertTrue(report.ok)
        self.assertEqual(5, report.sync_file_count)
        self.assertEqual(["RL6492_Project.uvprojx"], report.project_files)
        self.assertIn("将同步 5 个文件", report.summary)

    def test_full_sync_summary_counts_whole_project_files(self):
        host_root = self._valid_project()
        (host_root / "Tool" / "precompile").mkdir(parents=True)
        (host_root / "Tool" / "precompile" / "pch_support.bat").write_text("@echo off\n", encoding="utf-8")
        (host_root / "Tool" / "precompile" / "helper.exe").write_bytes(b"MZ")
        cfg = self._config(host_root)

        report = self._check(cfg, for_full_sync=True)
        monitor_report = self._check(cfg, for_full_sync=False)

        self.assertEqual(7, report.sync_file_count)
        self.assertEqual(3, monitor_report.sync_file_count)

    def test_rejects_dangerous_vm_project_root(self):
        host_root = self._project()
        cfg = self._config(host_root)
        cfg.vm_project_path = r"C:\\"

        report = self._check(cfg, for_full_sync=True)

        self.assertFalse(report.ok)
        self.assertIn("VM 工程路径不能是磁盘根目录", report.error_text)

    def test_rejects_host_output_path_when_it_is_a_file(self):
        host_root = self._valid_project()
        cfg = self._config(host_root)
        output_file = Path(cfg.host_output_path)
        output_file.write_text("not a directory", encoding="utf-8")

        report = self._check(cfg)

        self.assertFalse(report.ok)
        self.assertIn("输出路径", report.error_text)

    def test_rejects_absolute_bin_relative_path(self):
        host_root = self._project()
        cfg = self._config(host_root)
        cfg.vm_bin_relative_path = r"C:\Output\firmware.bin"

        report = self._check(cfg)

        self.assertFalse(report.ok)
        self.assertIn(".bin 相对路径不能是绝对路径", report.error_text)

    def test_warns_when_host_project_has_no_keil_project_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp)
            (host_root / "main.c").write_text("int main(void) { return 0; }", encoding="utf-8")
            (host_root / "vm.vmx").write_text("", encoding="utf-8")
            (host_root / "vmrun.exe").write_text("", encoding="utf-8")
            cfg = self._config(host_root)

            report = self._check(cfg)

        self.assertTrue(report.ok)
        self.assertIn("未找到 Keil 工程文件", report.warning_text)

    def test_accepts_legacy_keil_project_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp)
            (host_root / "RL2556VD.uvproj").write_text("<Project />", encoding="utf-8")
            (host_root / "RL2556VD.uvopt").write_text("", encoding="utf-8")
            (host_root / "RL2556VD.Uv2").write_text("", encoding="utf-8")
            (host_root / "RL2556VD.Opt").write_text("", encoding="utf-8")
            (host_root / "vm.vmx").write_text("", encoding="utf-8")
            (host_root / "vmrun.exe").write_text("", encoding="utf-8")
            cfg = self._config(host_root)
            cfg.vm_bin_relative_path = r"Output\RL2556VD.bin"

            report = self._check(cfg)

        self.assertTrue(report.ok)
        self.assertEqual(
            ["RL2556VD.Opt", "RL2556VD.Uv2", "RL2556VD.uvopt", "RL2556VD.uvproj"],
            report.project_files,
        )
        self.assertNotIn("未找到 Keil 工程文件", report.warning_text)

    def test_rejects_missing_vmx_file(self):
        host_root = self._project()
        cfg = self._config(host_root)

        report = self._check(cfg)

        self.assertFalse(report.ok)
        self.assertIn("VMX 文件不存在", report.error_text)

    def test_warns_when_bin_name_does_not_match_project_name(self):
        host_root = self._valid_project()
        cfg = self._config(host_root)
        cfg.vm_bin_relative_path = r"Output\OtherFirmware.bin"

        report = self._check(cfg)

        self.assertTrue(report.ok)
        self.assertIn(".bin 文件名与 Keil 工程名不一致", report.warning_text)

    def test_does_not_warn_about_bin_name_when_bin_path_is_directory(self):
        host_root = self._valid_project()
        cfg = self._config(host_root)
        cfg.vm_bin_relative_path = r"Output\RL6492"

        report = self._check(cfg)

        self.assertTrue(report.ok)
        self.assertNotIn(".bin 文件名与 Keil 工程名不一致", report.warning_text)

    def test_rejects_missing_vmrun_path(self):
        host_root = self._valid_project()
        cfg = self._config(host_root)
        cfg.vmrun_path = ""

        report = self._check(cfg)

        self.assertFalse(report.ok)
        self.assertIn("请先配置 vmrun.exe 路径", report.error_text)

    def test_rejects_missing_guest_credentials(self):
        host_root = self._valid_project()
        cfg = self._config(host_root)
        cfg.vm_guest_user = ""

        report = self._check(cfg)

        self.assertFalse(report.ok)
        self.assertIn("请先配置 VM 用户名", report.error_text)

        cfg.vm_guest_user = "h"
        cfg.vm_guest_password = ""
        report = self._check(cfg)

        self.assertFalse(report.ok)
        self.assertIn("VM 密码", report.error_text)

    def test_rejects_missing_vmrun_file(self):
        host_root = self._valid_project()
        cfg = self._config(host_root)
        cfg.vmrun_path = str(host_root / "missing-vmrun.exe")

        report = self._check(cfg)

        self.assertFalse(report.ok)
        self.assertIn("vmrun.exe 不存在", report.error_text)

    def test_rejects_configured_vmx_when_not_running(self):
        host_root = self._valid_project()
        cfg = self._config(host_root)

        report = self._check(cfg, running_paths=[str(host_root / "other" / "vm.vmx")])

        self.assertFalse(report.ok)
        self.assertFalse(report.configured_vmx_is_running)
        self.assertIn("配置的 VMX 当前未运行", report.error_text)

    def test_rejects_same_vmx_name_in_different_directory(self):
        host_root = self._valid_project()
        cfg = self._config(host_root)

        report = self._check(cfg, running_paths=[r"C:\Other\vm.vmx"])

        self.assertFalse(report.ok)
        self.assertIn("配置的 VMX 当前未运行", report.error_text)

    def test_rejects_vmrun_list_failure(self):
        host_root = self._valid_project()
        cfg = self._config(host_root)
        checker = PreflightChecker(
            cfg,
            running_vms_provider=lambda _path: RunningVmsResult(False, [], "vmrun failed"),
        )

        report = checker.check()

        self.assertFalse(report.ok)
        self.assertIn("vmrun list 执行失败", report.error_text)

    def test_vmrun_timeout_message_suggests_recovery(self):
        host_root = self._valid_project()
        cfg = self._config(host_root)
        checker = PreflightChecker(
            cfg,
            running_vms_provider=lambda _path: RunningVmsResult(False, [], "vmrun list 超时"),
        )

        report = checker.check()

        self.assertFalse(report.ok)
        self.assertIn("VMware", report.error_text)
        self.assertIn("重启", report.error_text)


if __name__ == "__main__":
    unittest.main()
