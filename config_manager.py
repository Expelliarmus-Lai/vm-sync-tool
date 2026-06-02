"""Configuration management for VM Sync Tool."""

import json
import ntpath
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from i18n import detect_system_language, normalize_language
from i18n import Translator


@dataclass
class ProjectConfig:
    enabled: bool = False
    host_project_path: str = ""
    vm_project_path: str = ""
    vm_bin_relative_path: str = ""
    host_output_path: str = ""


@dataclass
class Config:
    vmrun_path: str = ""
    vmx_path: str = ""
    vm_guest_user: str = ""
    vm_guest_password: str = ""
    language: str = ""
    debounce_ms: int = 500
    poll_interval_sec: int = 1
    watch_extensions: List[str] = field(
        default_factory=lambda: [
            ".c", ".h", ".cpp", ".hpp", ".s", ".asm", ".inc", ".txt",
            ".uvprojx", ".uvoptx", ".uvproj", ".uvopt", ".uv2", ".opt"
        ]
    )
    projects: List[ProjectConfig] = field(default_factory=list)

    # Legacy fields mapping
    @property
    def host_project_path(self): return self.projects[0].host_project_path if self.projects else ""
    @host_project_path.setter
    def host_project_path(self, val): 
        if self.projects: self.projects[0].host_project_path = val

    @property
    def vm_project_path(self): return self.projects[0].vm_project_path if self.projects else ""
    @vm_project_path.setter
    def vm_project_path(self, val): 
        if self.projects: self.projects[0].vm_project_path = val

    @property
    def vm_bin_relative_path(self): return self.projects[0].vm_bin_relative_path if self.projects else ""
    @vm_bin_relative_path.setter
    def vm_bin_relative_path(self, val): 
        if self.projects: self.projects[0].vm_bin_relative_path = val

    @property
    def host_output_path(self): return self.projects[0].host_output_path if self.projects else ""
    @host_output_path.setter
    def host_output_path(self, val): 
        if self.projects: self.projects[0].host_output_path = val

class ConfigManager:
    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        self.config = Config()
        self._load()
        changed = self.normalize_runtime_defaults()
        if changed and self.config_path.exists():
            self._save()

    def _load(self):
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                old_keys = ["host_project_path", "vm_project_path", "vm_bin_relative_path", "host_output_path"]
                needs_migration = any(k in data for k in old_keys) and "projects" not in data
                
                for key, value in data.items():
                    if key == "projects":
                        self.config.projects = [ProjectConfig(**p) for p in value]
                    elif hasattr(self.config, key) and key not in old_keys and key != "projects":
                        setattr(self.config, key, value)
                        
                if needs_migration:
                    p = ProjectConfig(
                        enabled=True,
                        host_project_path=data.get("host_project_path", ""),
                        vm_project_path=data.get("vm_project_path", ""),
                        vm_bin_relative_path=data.get("vm_bin_relative_path", ""),
                        host_output_path=data.get("host_output_path", "")
                    )
                    self.config.projects = [p]

                while len(self.config.projects) < 2:
                    self.config.projects.append(ProjectConfig(enabled=False))

                changed = self.normalize_paths()
                changed = self.normalize_runtime_defaults() or changed
                if changed or needs_migration:
                    self._save()
            except (json.JSONDecodeError, KeyError, TypeError):
                self._ensure_projects()
                self._save()
        else:
            self._ensure_projects()

    def _ensure_projects(self):
        while len(self.config.projects) < 2:
            self.config.projects.append(ProjectConfig(enabled=False))
        if self.config.projects:
            self.config.projects[0].enabled = True

    def save(self):
        self._save()

    def _to_dict(self):
        return {
            "vmrun_path": self.config.vmrun_path,
            "vmx_path": self.config.vmx_path,
            "vm_guest_user": self.config.vm_guest_user,
            "vm_guest_password": self.config.vm_guest_password,
            "language": self.config.language,
            "debounce_ms": self.config.debounce_ms,
            "poll_interval_sec": self.config.poll_interval_sec,
            "watch_extensions": self.config.watch_extensions,
            "projects": [asdict(p) for p in self.config.projects],
        }

    def _save(self):
        self.normalize_paths()
        self.normalize_runtime_defaults()
        # Avoid writing legacy properties into JSON by extracting __dict__ explicitly
        config_text = json.dumps(self._to_dict(), indent=2, ensure_ascii=False)
        if self.config_path.exists():
            try:
                if self.config_path.read_text(encoding="utf-8") == config_text:
                    return
            except OSError:
                pass
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            f.write(config_text)

    def normalize_paths(self) -> bool:
        before = json.dumps({
            "v": self.config.vmrun_path, "x": self.config.vmx_path,
            "p": [asdict(p) for p in self.config.projects]
        })
        for key in ("vmrun_path", "vmx_path"):
            setattr(
                self.config,
                key,
                _normalize_windows_path(getattr(self.config, key)),
            )
            
        for proj in self.config.projects:
            proj.host_project_path = _normalize_windows_path(proj.host_project_path)
            proj.vm_project_path = _normalize_windows_path(proj.vm_project_path)
            proj.host_output_path = _normalize_windows_path(proj.host_output_path)
            proj.vm_bin_relative_path = _normalize_relative_windows_path(proj.vm_bin_relative_path)
            
        after = json.dumps({
            "v": self.config.vmrun_path, "x": self.config.vmx_path,
            "p": [asdict(p) for p in self.config.projects]
        })
        return before != after

    def normalize_runtime_defaults(self) -> bool:
        before = json.dumps({"p": self.config.poll_interval_sec, "l": self.config.language, "prj": len(self.config.projects)})
        if self.config.poll_interval_sec == 3:
            self.config.poll_interval_sec = 1
        language = normalize_language(self.config.language)
        if not language:
            language = detect_system_language()
        self.config.language = language
        self._ensure_projects()
        after = json.dumps({"p": self.config.poll_interval_sec, "l": self.config.language, "prj": len(self.config.projects)})
        return before != after

    def get_vm_bin_full_path(self, project_index: int = 0) -> str:
        if project_index < len(self.config.projects):
            proj = self.config.projects[project_index]
            return _join_windows_path(proj.vm_project_path, proj.vm_bin_relative_path)
        return ""

    def get_bin_filename(self, project_index: int = 0) -> str:
        if project_index < len(self.config.projects):
            return ntpath.basename(self.config.projects[project_index].vm_bin_relative_path)
        return ""


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
