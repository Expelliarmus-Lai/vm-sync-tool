"""Configuration management for VM Sync Tool."""

import json
import ntpath
import copy
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from i18n import detect_system_language, normalize_language


class ConfigPersistenceError(RuntimeError):
    """Raised when config data cannot be durably persisted."""


@dataclass
class ProjectConfig:
    enabled: bool = False
    host_project_path: str = ""
    vm_project_path: str = ""
    vm_bin_relative_path: str = ""
    host_output_path: str = ""


def _default_projects() -> List[ProjectConfig]:
    return [ProjectConfig(enabled=True), ProjectConfig(enabled=False)]


@dataclass
class SyncProfile:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    vmx_path: str = ""
    vm_guest_user: str = ""
    vm_guest_password: str = ""
    projects: List[ProjectConfig] = field(default_factory=_default_projects)


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
    active_profile_id: str = ""
    profiles: List[SyncProfile] = field(default_factory=list)

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
        self.backup_path = self.config_path.with_name(self.config_path.name + ".bak")
        self.corrupt_path = self.config_path.with_name(self.config_path.name + ".corrupt")
        self.config = Config()
        self._load()
        changed = self.normalize_runtime_defaults()
        if changed and self.config_path.exists():
            self._save()

    def _load(self):
        if not self.config_path.exists():
            self._ensure_projects()
            self.normalize_runtime_defaults()
            self._ensure_profiles(apply_active=True)
            return

        rewrite_needed = self._try_load_path(self.config_path)
        recovered = False
        if rewrite_needed is None:
            self._preserve_corrupt_config()
            rewrite_needed = self._try_load_path(self.backup_path)
            recovered = rewrite_needed is not None

        if rewrite_needed is None:
            self.config = Config()
            self._ensure_projects()
            self.normalize_runtime_defaults()
            self._ensure_profiles(apply_active=True)
            self._save()
            return

        if rewrite_needed or recovered:
            self._save()

    def _try_load_path(self, path: Path) -> Optional[bool]:
        try:
            with open(path, "r", encoding="utf-8") as config_file:
                data = json.load(config_file)
            if not isinstance(data, dict):
                return None
            self.config = Config()
            return self._apply_loaded_data(data)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            self.config = Config()
            return None

    def _apply_loaded_data(self, data: dict) -> bool:
        old_keys = [
            "host_project_path",
            "vm_project_path",
            "vm_bin_relative_path",
            "host_output_path",
        ]
        needs_migration = any(key in data for key in old_keys) and "projects" not in data

        for key, value in data.items():
            if key == "projects":
                self.config.projects = [
                    self._project_from_dict(project)
                    for project in value
                    if isinstance(project, dict)
                ]
            elif key == "profiles":
                self.config.profiles = [
                    self._profile_from_dict(profile)
                    for profile in value
                    if isinstance(profile, dict)
                ]
            elif (
                hasattr(self.config, key)
                and key not in old_keys
                and key not in {"projects", "profiles"}
            ):
                setattr(self.config, key, value)

        if needs_migration:
            self.config.projects = [
                ProjectConfig(
                    enabled=True,
                    host_project_path=data.get("host_project_path", ""),
                    vm_project_path=data.get("vm_project_path", ""),
                    vm_bin_relative_path=data.get("vm_bin_relative_path", ""),
                    host_output_path=data.get("host_output_path", ""),
                )
            ]

        self._ensure_projects()
        changed = self.normalize_runtime_defaults()
        changed = self._ensure_profiles(apply_active=True) or changed
        changed = self.normalize_paths() or changed
        return changed or needs_migration or "profiles" not in data

    def _preserve_corrupt_config(self):
        try:
            if self.config_path.exists():
                shutil.copy2(self.config_path, self.corrupt_path)
        except OSError:
            pass

    def _ensure_projects(self):
        while len(self.config.projects) < 2:
            self.config.projects.append(ProjectConfig(enabled=False))
        if self.config.projects:
            self.config.projects[0].enabled = True

    @staticmethod
    def _project_from_dict(data: dict) -> ProjectConfig:
        return ProjectConfig(
            enabled=bool(data.get("enabled", False)),
            host_project_path=str(data.get("host_project_path", "") or ""),
            vm_project_path=str(data.get("vm_project_path", "") or ""),
            vm_bin_relative_path=str(data.get("vm_bin_relative_path", "") or ""),
            host_output_path=str(data.get("host_output_path", "") or ""),
        )

    @classmethod
    def _profile_from_dict(cls, data: dict) -> SyncProfile:
        projects = [
            cls._project_from_dict(project)
            for project in data.get("projects", [])
            if isinstance(project, dict)
        ]
        while len(projects) < 2:
            projects.append(ProjectConfig(enabled=False))
        if projects:
            projects[0].enabled = True
        return SyncProfile(
            id=str(data.get("id", "") or ""),
            name=str(data.get("name", "") or ""),
            vmx_path=str(data.get("vmx_path", "") or ""),
            vm_guest_user=str(data.get("vm_guest_user", "") or ""),
            vm_guest_password=str(data.get("vm_guest_password", "") or ""),
            projects=projects,
        )

    def _default_profile_name(self) -> str:
        return "Default Profile" if self.config.language == "en" else "默认配置"

    def _profile_from_live_config(self, name: str, profile_id: str = "") -> SyncProfile:
        self._ensure_projects()
        return SyncProfile(
            id=profile_id or str(uuid.uuid4()),
            name=name,
            vmx_path=self.config.vmx_path,
            vm_guest_user=self.config.vm_guest_user,
            vm_guest_password=self.config.vm_guest_password,
            projects=copy.deepcopy(self.config.projects),
        )

    def _blank_profile(self, name: str) -> SyncProfile:
        return SyncProfile(name=name, projects=_default_projects())

    def _active_profile_index(self) -> int:
        for index, profile in enumerate(self.config.profiles):
            if profile.id == self.config.active_profile_id:
                return index
        return -1

    def get_active_profile(self) -> SyncProfile:
        self._ensure_profiles()
        index = self._active_profile_index()
        return self.config.profiles[index if index >= 0 else 0]

    def get_profile(self, profile_id: str) -> Optional[SyncProfile]:
        return next(
            (profile for profile in self.config.profiles if profile.id == profile_id),
            None,
        )

    def _apply_profile_to_live_config(self, profile: SyncProfile):
        self.config.vmx_path = profile.vmx_path
        self.config.vm_guest_user = profile.vm_guest_user
        self.config.vm_guest_password = profile.vm_guest_password
        self.config.projects = copy.deepcopy(profile.projects)
        self._ensure_projects()

    def _sync_active_profile_from_live_config(self):
        profile = self.get_active_profile()
        profile.vmx_path = self.config.vmx_path
        profile.vm_guest_user = self.config.vm_guest_user
        profile.vm_guest_password = self.config.vm_guest_password
        profile.projects = copy.deepcopy(self.config.projects)

    def _ensure_profiles(self, apply_active: bool = False) -> bool:
        changed = False
        if not self.config.profiles:
            profile = self._profile_from_live_config(self._default_profile_name())
            self.config.profiles = [profile]
            self.config.active_profile_id = profile.id
            return True

        seen_ids = set()
        seen_names = set()
        for index, profile in enumerate(self.config.profiles):
            if not profile.id or profile.id in seen_ids:
                profile.id = str(uuid.uuid4())
                changed = True
            seen_ids.add(profile.id)

            name = profile.name.strip()
            if not name:
                name = self._default_profile_name() if index == 0 else f"{self._default_profile_name()} {index + 1}"
                changed = True
            base_name = name
            suffix = 2
            while name.casefold() in seen_names:
                name = f"{base_name} ({suffix})"
                suffix += 1
                changed = True
            if profile.name != name:
                profile.name = name
                changed = True
            seen_names.add(name.casefold())

            while len(profile.projects) < 2:
                profile.projects.append(ProjectConfig(enabled=False))
                changed = True
            if profile.projects and not profile.projects[0].enabled:
                profile.projects[0].enabled = True
                changed = True

        if self._active_profile_index() < 0:
            self.config.active_profile_id = self.config.profiles[0].id
            changed = True
        if apply_active:
            self._apply_profile_to_live_config(
                self.get_profile(self.config.active_profile_id) or self.config.profiles[0]
            )
        return changed

    def validate_profile_name(self, name: str, exclude_profile_id: str = "") -> str:
        normalized = str(name or "").strip()
        if not normalized:
            raise ValueError("empty")
        folded = normalized.casefold()
        if any(
            profile.id != exclude_profile_id and profile.name.strip().casefold() == folded
            for profile in self.config.profiles
        ):
            raise ValueError("duplicate")
        return normalized

    def activate_profile(self, profile_id: str) -> SyncProfile:
        previous = copy.deepcopy(self.config)
        profile = self.get_profile(profile_id)
        if profile is None:
            raise ValueError("not_found")
        try:
            self.config.active_profile_id = profile.id
            self._apply_profile_to_live_config(profile)
            self._save()
        except ConfigPersistenceError:
            self.config = previous
            raise
        return profile

    def create_profile(self, name: str, copy_current: bool = True) -> SyncProfile:
        previous = copy.deepcopy(self.config)
        normalized_name = self.validate_profile_name(name)
        profile = (
            self._profile_from_live_config(normalized_name)
            if copy_current
            else self._blank_profile(normalized_name)
        )
        try:
            self.config.profiles.append(profile)
            self.config.active_profile_id = profile.id
            self._apply_profile_to_live_config(profile)
            self._save()
        except ConfigPersistenceError:
            self.config = previous
            raise
        return profile

    def save_active_profile(self, name: Optional[str] = None) -> SyncProfile:
        previous = copy.deepcopy(self.config)
        profile = self.get_active_profile()
        try:
            if name is not None:
                profile.name = self.validate_profile_name(name, exclude_profile_id=profile.id)
            self._save()
        except ConfigPersistenceError:
            self.config = previous
            raise
        return profile

    def rename_profile(self, profile_id: str, name: str) -> SyncProfile:
        previous = copy.deepcopy(self.config)
        profile = self.get_profile(profile_id)
        if profile is None:
            raise ValueError("not_found")
        try:
            profile.name = self.validate_profile_name(name, exclude_profile_id=profile.id)
            self._save()
        except ConfigPersistenceError:
            self.config = previous
            raise
        return profile

    def delete_active_profile(self) -> SyncProfile:
        previous = copy.deepcopy(self.config)
        if len(self.config.profiles) <= 1:
            raise ValueError("last_profile")
        active_index = max(0, self._active_profile_index())
        del self.config.profiles[active_index]
        next_index = min(active_index, len(self.config.profiles) - 1)
        profile = self.config.profiles[next_index]
        try:
            self.config.active_profile_id = profile.id
            self._apply_profile_to_live_config(profile)
            self._save()
        except ConfigPersistenceError:
            self.config = previous
            raise
        return profile

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
            "active_profile_id": self.config.active_profile_id,
            "profiles": [asdict(profile) for profile in self.config.profiles],
        }

    def _save(self):
        self.normalize_paths()
        self.normalize_runtime_defaults()
        self._ensure_profiles()
        self._sync_active_profile_from_live_config()
        self.normalize_paths()
        # Avoid writing legacy properties into JSON by extracting __dict__ explicitly
        config_text = json.dumps(self._to_dict(), indent=2, ensure_ascii=False)
        current_text = None
        if self.config_path.exists():
            try:
                current_text = self.config_path.read_text(encoding="utf-8")
                if current_text == config_text:
                    return
            except (OSError, UnicodeDecodeError):
                pass
        if current_text is not None:
            try:
                if isinstance(json.loads(current_text), dict):
                    _atomic_write_text(self.backup_path, current_text)
            except (json.JSONDecodeError, TypeError):
                self._preserve_corrupt_config()
        _atomic_write_text(self.config_path, config_text)

    def normalize_paths(self) -> bool:
        before = json.dumps({
            "v": self.config.vmrun_path, "x": self.config.vmx_path,
            "p": [asdict(p) for p in self.config.projects],
            "profiles": [asdict(profile) for profile in self.config.profiles],
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

        for profile in self.config.profiles:
            profile.vmx_path = _normalize_windows_path(profile.vmx_path)
            for proj in profile.projects:
                proj.host_project_path = _normalize_windows_path(proj.host_project_path)
                proj.vm_project_path = _normalize_windows_path(proj.vm_project_path)
                proj.host_output_path = _normalize_windows_path(proj.host_output_path)
                proj.vm_bin_relative_path = _normalize_relative_windows_path(proj.vm_bin_relative_path)
            
        after = json.dumps({
            "v": self.config.vmrun_path, "x": self.config.vmx_path,
            "p": [asdict(p) for p in self.config.projects],
            "profiles": [asdict(profile) for profile in self.config.profiles],
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


def _atomic_write_text(path: Path, text: str):
    temp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(text)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, path)
    except OSError as error:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise ConfigPersistenceError(str(error)) from error
