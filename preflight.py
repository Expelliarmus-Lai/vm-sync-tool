"""Preflight checks that keep sync operations pointed at the intended project."""

from dataclasses import dataclass, field
from pathlib import PureWindowsPath, Path

from config_manager import Config
from i18n import Translator
from vmrun_resolver import RunningVmsResult, list_running_vms, normalize_vmx_path

KEIL_PROJECT_EXTENSIONS = {".uvprojx", ".uvoptx", ".uvproj", ".uvopt", ".uv2", ".opt"}
PRIMARY_KEIL_PROJECT_EXTENSIONS = {".uvprojx", ".uvproj", ".uv2"}


@dataclass
class PreflightReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    project_files: list[str] = field(default_factory=list)
    vmrun_path: str = ""
    running_vmx_paths: list[str] = field(default_factory=list)
    configured_vmx_is_running: bool = False
    sync_file_count: int = 0
    summary: str = ""

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def error_text(self) -> str:
        return "\n".join(self.errors)

    @property
    def warning_text(self) -> str:
        return "\n".join(self.warnings)


class PreflightChecker:
    def __init__(self, config: Config, running_vms_provider=list_running_vms):
        self.config = config
        self.running_vms_provider = running_vms_provider
        self.t = Translator(config.language).tr

    def check(self, for_full_sync: bool = False) -> PreflightReport:
        report = PreflightReport()
        cfg = self.config
        report.vmrun_path = cfg.vmrun_path

        if not cfg.vmrun_path:
            report.errors.append(self.t("preflight.vmrun.missing"))
        elif not Path(cfg.vmrun_path).exists():
            report.errors.append(self.t("preflight.vmrun.not_found", path=cfg.vmrun_path))
        else:
            self._check_running_vm(report)

        if not cfg.vm_guest_user:
            report.errors.append(self.t("preflight.guest.user_missing"))
        if not cfg.vm_guest_password:
            report.errors.append(self.t("preflight.guest.password_missing"))

        host_root = Path(cfg.host_project_path) if cfg.host_project_path else None
        if not cfg.host_project_path:
            report.errors.append(self.t("preflight.host_project.missing"))
        elif not host_root.exists():
            report.errors.append(self.t("preflight.host_project.not_found", path=host_root))
        elif not host_root.is_dir():
            report.errors.append(self.t("preflight.host_project.file", path=host_root))

        if not cfg.vmx_path:
            report.errors.append(self.t("preflight.vmx.missing"))
        elif not Path(cfg.vmx_path).exists():
            report.errors.append(self.t("preflight.vmx.not_found", path=cfg.vmx_path))

        if not cfg.vm_project_path:
            report.errors.append(self.t("preflight.vm_project.missing"))
        else:
            self._check_vm_project_path(cfg.vm_project_path, report)

        if not cfg.host_output_path:
            report.errors.append(self.t("preflight.host_output.missing"))
        else:
            host_output = Path(cfg.host_output_path)
            if host_output.exists() and not host_output.is_dir():
                report.errors.append(self.t("preflight.host_output.file", path=host_output))

        if not cfg.vm_bin_relative_path:
            report.errors.append(self.t("preflight.bin.missing"))
        elif self._is_absolute_windows_path(cfg.vm_bin_relative_path):
            report.errors.append(self.t("preflight.bin.absolute"))

        if host_root and host_root.exists() and host_root.is_dir():
            report.project_files = sorted(
                p.name for p in host_root.iterdir()
                if p.is_file() and p.suffix.lower() in KEIL_PROJECT_EXTENSIONS
            )
            if not report.project_files:
                report.warnings.append(
                    self.t("preflight.keil.not_found")
                )
            else:
                self._check_bin_name_matches_project(report)
            report.sync_file_count = self._count_project_files(host_root) if for_full_sync else self._count_sync_files(host_root)

        report.summary = self._build_summary(report, for_full_sync)
        return report

    def _check_running_vm(self, report: PreflightReport):
        try:
            result: RunningVmsResult = self.running_vms_provider(
                self.config.vmrun_path,
                timeout=15,
            )
        except TypeError:
            result = self.running_vms_provider(self.config.vmrun_path)
        if not result.ok:
            if "超时" in result.error or "timeout" in result.error.lower():
                report.errors.append(
                    self.t("preflight.vmrun.list_timeout", error=result.error)
                )
                return
            report.errors.append(self.t("preflight.vmrun.list_failed", error=result.error))
            return

        report.running_vmx_paths = result.paths
        if not self.config.vmx_path:
            return

        configured = normalize_vmx_path(self.config.vmx_path)
        running = {normalize_vmx_path(path) for path in result.paths}
        report.configured_vmx_is_running = configured in running
        if not report.configured_vmx_is_running:
            report.errors.append(self.t("preflight.vmx.not_running"))

    def _check_vm_project_path(self, vm_path: str, report: PreflightReport):
        path = PureWindowsPath(vm_path)
        normalized = vm_path.strip().rstrip("\\/")
        if path.drive and normalized.upper() == path.drive.upper():
            report.errors.append(self.t("preflight.vm_project.root"))
            return

        risky = {
            r"C:\Windows",
            r"C:\Program Files",
            r"C:\Program Files (x86)",
            r"C:\Users",
            r"D:\Keil",
            r"C:\Keil",
        }
        if normalized.lower() in {p.lower() for p in risky}:
            report.errors.append(self.t("preflight.vm_project.danger", path=vm_path))

    def _count_sync_files(self, host_root: Path) -> int:
        exts = {ext.lower() for ext in self.config.watch_extensions}
        return sum(
            1 for p in host_root.rglob("*")
            if p.is_file() and p.suffix.lower() in exts
        )

    def _count_project_files(self, host_root: Path) -> int:
        return sum(1 for p in host_root.rglob("*") if p.is_file())

    def _check_bin_name_matches_project(self, report: PreflightReport):
        if PureWindowsPath(self.config.vm_bin_relative_path).suffix.lower() != ".bin":
            return
        bin_stem = PureWindowsPath(self.config.vm_bin_relative_path).stem.lower()
        project_stems = {
            Path(name).stem.lower()
            for name in report.project_files
            if Path(name).suffix.lower() in PRIMARY_KEIL_PROJECT_EXTENSIONS
        }
        if project_stems and bin_stem not in project_stems:
            report.warnings.append(
                self.t("preflight.bin.name_mismatch")
            )

    def _build_summary(self, report: PreflightReport, for_full_sync: bool) -> str:
        cfg = self.config
        action_key = "preflight.action.full" if for_full_sync else "preflight.action.watch"
        project = ", ".join(report.project_files) if report.project_files else self.t("preflight.summary.project.none")
        return "\n".join([
            self.t(action_key, count=report.sync_file_count),
            f"vmrun: {cfg.vmrun_path}",
            self.t("preflight.summary.source", path=cfg.host_project_path),
            self.t("preflight.summary.target", path=cfg.vm_project_path),
            self.t("preflight.summary.project", project=project),
            self.t("preflight.summary.output", path=cfg.vm_bin_relative_path),
        ])

    def _is_absolute_windows_path(self, path: str) -> bool:
        return PureWindowsPath(path).is_absolute()
