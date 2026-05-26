"""Configuration management for VM Sync Tool."""

import json
import ntpath
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List


@dataclass
class Config:
    vmrun_path: str = ""
    vmx_path: str = ""
    vm_guest_user: str = ""
    vm_guest_password: str = ""
    host_project_path: str = ""
    vm_project_path: str = ""
    vm_bin_relative_path: str = ""
    host_output_path: str = ""
    debounce_ms: int = 500
    poll_interval_sec: int = 1
    watch_extensions: List[str] = field(
        default_factory=lambda: [
            ".c", ".h", ".cpp", ".hpp", ".s", ".asm", ".inc", ".txt",
            ".uvprojx", ".uvoptx", ".uvproj", ".uvopt", ".uv2", ".opt"
        ]
    )


class ConfigManager:
    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        self.config = Config()
        self._load()

    def _load(self):
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for key, value in data.items():
                    if hasattr(self.config, key):
                        setattr(self.config, key, value)
                changed = self.normalize_paths()
                changed = self.normalize_runtime_defaults() or changed
                if changed:
                    self._save()
            except (json.JSONDecodeError, KeyError):
                self._save()

    def save(self):
        self._save()

    def _save(self):
        self.normalize_paths()
        self.normalize_runtime_defaults()
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(asdict(self.config), f, indent=2, ensure_ascii=False)

    def normalize_paths(self) -> bool:
        before = asdict(self.config)
        for key in (
            "vmrun_path",
            "vmx_path",
            "host_project_path",
            "vm_project_path",
            "host_output_path",
        ):
            setattr(
                self.config,
                key,
                _normalize_windows_path(getattr(self.config, key)),
            )
        self.config.vm_bin_relative_path = _normalize_relative_windows_path(
            self.config.vm_bin_relative_path
        )
        return asdict(self.config) != before

    def normalize_runtime_defaults(self) -> bool:
        before = asdict(self.config)
        if self.config.poll_interval_sec == 3:
            self.config.poll_interval_sec = 1
        return asdict(self.config) != before

    def validate_paths(self) -> dict:
        issues = {}
        if self.config.host_project_path:
            host = Path(self.config.host_project_path)
            if not host.exists():
                issues["host_project_path"] = "路径不存在"
        if self.config.host_output_path:
            out = Path(self.config.host_output_path)
            if not out.exists():
                issues["host_output_path"] = "路径不存在"
        if self.config.vmx_path:
            vmx = Path(self.config.vmx_path)
            if not vmx.exists():
                issues["vmx_path"] = "VMX 文件不存在"
        return issues

    def get_vm_bin_full_path(self) -> str:
        return _join_windows_path(
            self.config.vm_project_path,
            self.config.vm_bin_relative_path,
        )

    def get_bin_filename(self) -> str:
        return ntpath.basename(self.config.vm_bin_relative_path)


def _normalize_windows_path(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return ntpath.normpath(text.replace("/", "\\"))


def _normalize_relative_windows_path(value: str) -> str:
    text = str(value or "").strip().replace("/", "\\")
    if not text:
        return ""
    drive, _tail = ntpath.splitdrive(text)
    if not drive:
        text = text.lstrip("\\")
    if not text:
        return ""
    return ntpath.normpath(text)


def _join_windows_path(root: str, child: str) -> str:
    root = _normalize_windows_path(root)
    child = _normalize_relative_windows_path(child)
    return ntpath.normpath(ntpath.join(root, child))
