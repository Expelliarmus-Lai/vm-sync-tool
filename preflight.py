"""Preflight checks that keep sync operations pointed at the intended project."""

from dataclasses import dataclass, field
from pathlib import PureWindowsPath, Path
from typing import List, Dict, Optional, Tuple

from config_manager import Config, ProjectConfig
from i18n import Translator
from vmrun_resolver import RunningVmsResult, list_running_vms, normalize_vmx_path

KEIL_PROJECT_EXTENSIONS = {".uvprojx", ".uvoptx", ".uvproj", ".uvopt", ".uv2", ".opt"}
PRIMARY_KEIL_PROJECT_EXTENSIONS = {".uvprojx", ".uvproj", ".uv2"}


@dataclass
class ProjectPreflightReport:
    index: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    project_files: list[str] = field(default_factory=list)
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


@dataclass
class PreflightReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    project_reports: Dict[int, ProjectPreflightReport] = field(default_factory=dict)
    
    vmrun_path: str = ""
    running_vmx_paths: list[str] = field(default_factory=list)
    configured_vmx_is_running: bool = False
    
    @property
    def ok(self) -> bool:
        if self.errors:
            return False
        for pr in self.project_reports.values():
            if not pr.ok:
                return False
        return True

    @property
    def error_text(self) -> str:
        errs = list(self.errors)
        for idx, pr in self.project_reports.items():
            if pr.errors:
                errs.extend([f"Project {idx + 1}: {e}" for e in pr.errors])
        return "\n".join(errs)

    @property
    def warning_text(self) -> str:
        warns = list(self.warnings)
        for idx, pr in self.project_reports.items():
            if pr.warnings:
                warns.extend([f"Project {idx + 1}: {w}" for w in pr.warnings])
        return "\n".join(warns)
        
    @property
    def summary(self) -> str:
        parts = []
        parts.append(f"vmrun: {self.vmrun_path}")
        for idx, pr in self.project_reports.items():
            if pr.summary:
                parts.append(f"\n[Project {idx + 1}]")
                parts.append(pr.summary)
        return "\n".join(parts)


class PreflightChecker:
    def __init__(self, config: Config, running_vms_provider=list_running_vms):
        self.config = config
        self.running_vms_provider = running_vms_provider
        self.t = Translator(config.language).tr

    def check(self, for_full_sync: bool = False, project_index: int | None = None) -> PreflightReport:
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

        if not cfg.vmx_path:
            report.errors.append(self.t("preflight.vmx.missing"))
        elif not Path(cfg.vmx_path).exists():
            report.errors.append(self.t("preflight.vmx.not_found", path=cfg.vmx_path))

        all_enabled_projects = [
            (idx, p) for idx, p in enumerate(self.config.projects)
            if p.enabled
        ]
        enabled_projects = [
            (idx, p) for idx, p in enumerate(self.config.projects)
            if p.enabled and (project_index is None or idx == project_index)
        ]
        
        for idx, p in enabled_projects:
            pr = self._check_project(p, idx, for_full_sync)
            report.project_reports[idx] = pr

        if len(all_enabled_projects) > 1:
            self._check_project_overlaps(all_enabled_projects, report)

        return report

    def _check_project(self, proj: ProjectConfig, index: int, for_full_sync: bool) -> ProjectPreflightReport:
        pr = ProjectPreflightReport(index=index)
        
        host_root = Path(proj.host_project_path) if proj.host_project_path else None
        if not proj.host_project_path:
            pr.errors.append(self.t("preflight.host_project.missing"))
        elif not host_root.exists():
            pr.errors.append(self.t("preflight.host_project.not_found", path=host_root))
        elif not host_root.is_dir():
            pr.errors.append(self.t("preflight.host_project.file", path=host_root))

        if not proj.vm_project_path:
            pr.errors.append(self.t("preflight.vm_project.missing"))
        else:
            self._check_vm_project_path(proj.vm_project_path, pr)

        if not proj.host_output_path:
            pr.errors.append(self.t("preflight.host_output.missing"))
        else:
            host_output = Path(proj.host_output_path)
            if host_output.exists() and not host_output.is_dir():
                pr.errors.append(self.t("preflight.host_output.file", path=host_output))

        if not proj.vm_bin_relative_path:
            pr.errors.append(self.t("preflight.bin.missing"))
        elif self._is_absolute_windows_path(proj.vm_bin_relative_path):
            pr.errors.append(self.t("preflight.bin.absolute"))

        if host_root and host_root.exists() and host_root.is_dir():
            pr.project_files = sorted(
                p.name for p in host_root.iterdir()
                if p.is_file() and p.suffix.lower() in KEIL_PROJECT_EXTENSIONS
            )
            if not pr.project_files:
                pr.warnings.append(
                    self.t("preflight.keil.not_found")
                )
            else:
                self._check_bin_name_matches_project(proj, pr)
            pr.sync_file_count = self._count_project_files(host_root) if for_full_sync else self._count_sync_files(host_root)

        pr.summary = self._build_project_summary(proj, pr, for_full_sync)
        return pr

    def _check_running_vm(self, report: PreflightReport):
        try:
            result: RunningVmsResult = self.running_vms_provider(
                self.config.vmrun_path,
                timeout=15,
            )
        except TypeError:
            result = self.running_vms_provider(self.config.vmrun_path)
        if not result.ok:
            if "瓒呮椂" in result.error or "timeout" in result.error.lower():
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

    def _check_vm_project_path(self, vm_path: str, pr: ProjectPreflightReport):
        path = PureWindowsPath(vm_path)
        normalized = vm_path.strip().rstrip("\\/")
        if path.drive and normalized.upper() == path.drive.upper():
            pr.errors.append(self.t("preflight.vm_project.root"))
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
            pr.errors.append(self.t("preflight.vm_project.danger", path=vm_path))

    def _count_sync_files(self, host_root: Path) -> int:
        exts = {ext.lower() for ext in self.config.watch_extensions}
        return sum(
            1 for p in host_root.rglob("*")
            if p.is_file() and p.suffix.lower() in exts
        )

    def _count_project_files(self, host_root: Path) -> int:
        return sum(1 for p in host_root.rglob("*") if p.is_file())

    def _check_bin_name_matches_project(self, proj: ProjectConfig, pr: ProjectPreflightReport):
        if PureWindowsPath(proj.vm_bin_relative_path).suffix.lower() != ".bin":
            return
        bin_stem = PureWindowsPath(proj.vm_bin_relative_path).stem.lower()
        project_stems = {
            Path(name).stem.lower()
            for name in pr.project_files
            if Path(name).suffix.lower() in PRIMARY_KEIL_PROJECT_EXTENSIONS
        }
        if project_stems and bin_stem not in project_stems:
            pr.warnings.append(
                self.t("preflight.bin.name_mismatch")
            )

    def _check_project_overlaps(self, enabled_projects: list[Tuple[int, ProjectConfig]], report: PreflightReport):
        # O(N^2) overlap check between enabled projects
        # In current design N <= 2
        for i in range(len(enabled_projects)):
            for j in range(i + 1, len(enabled_projects)):
                idx1, p1 = enabled_projects[i]
                idx2, p2 = enabled_projects[j]
                
                # check host path overlap
                if p1.host_project_path and p2.host_project_path:
                    if self._is_subpath(p1.host_project_path, p2.host_project_path) or \
                       self._is_subpath(p2.host_project_path, p1.host_project_path):
                        report.errors.append(f"Project {idx1 + 1} and Project {idx2 + 1} have overlapping host_project_paths.")
                        
                # check vm path overlap
                if p1.vm_project_path and p2.vm_project_path:
                    if self._is_subpath(p1.vm_project_path, p2.vm_project_path) or \
                       self._is_subpath(p2.vm_project_path, p1.vm_project_path):
                        report.errors.append(f"Project {idx1 + 1} and Project {idx2 + 1} have overlapping vm_project_paths.")

    def _is_subpath(self, path1: str, path2: str) -> bool:
        p1 = PureWindowsPath(path1)
        p2 = PureWindowsPath(path2)
        try:
            p1.relative_to(p2)
            return True
        except ValueError:
            return False

    def _build_project_summary(self, proj: ProjectConfig, pr: ProjectPreflightReport, for_full_sync: bool) -> str:
        action_key = "preflight.action.full" if for_full_sync else "preflight.action.watch"
        project = ", ".join(pr.project_files) if pr.project_files else self.t("preflight.summary.project.none")
        return "\n".join([
            self.t(action_key, count=pr.sync_file_count),
            self.t("preflight.summary.source", path=proj.host_project_path),
            self.t("preflight.summary.target", path=proj.vm_project_path),
            self.t("preflight.summary.project", project=project),
            self.t("preflight.summary.output", path=proj.vm_bin_relative_path),
        ])

    def _is_absolute_windows_path(self, path: str) -> bool:
        return PureWindowsPath(path).is_absolute()

