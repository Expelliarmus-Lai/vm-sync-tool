"""Resolve vmrun.exe and query running VMware VMs."""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from vmrun_output import decode_vmrun_result


DEFAULT_VMRUN_PATHS = [
    r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe",
    r"C:\Program Files\VMware\VMware Workstation\vmrun.exe",
]

_CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


@dataclass
class RunningVmsResult:
    ok: bool
    paths: list[str]
    error: str = ""


def vmrun_candidates(configured_path: str = "") -> list[str]:
    candidates: list[str] = []
    if configured_path:
        candidates.append(configured_path)
    candidates.extend(DEFAULT_VMRUN_PATHS)
    found = shutil.which("vmrun.exe") or shutil.which("vmrun")
    if found:
        candidates.append(found)

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(candidate))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def resolve_vmrun_path(configured_path: str = "") -> str:
    for candidate in vmrun_candidates(configured_path):
        if Path(candidate).exists():
            return str(Path(candidate))
    return ""


def list_running_vms(vmrun_path: str, timeout: int = 5) -> RunningVmsResult:
    try:
        result = subprocess.run(
            [vmrun_path, "list"],
            capture_output=True,
            timeout=timeout,
            creationflags=_CREATE_FLAGS,
        )
        result = decode_vmrun_result(result)
    except subprocess.TimeoutExpired:
        return RunningVmsResult(False, [], f"vmrun list 超时 ({timeout}s)")
    except Exception as e:
        return RunningVmsResult(False, [], str(e))

    if result.returncode != 0:
        return RunningVmsResult(
            False,
            [],
            result.stderr.strip() or result.stdout.strip() or "unknown error",
        )

    paths = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().lower().endswith(".vmx")
    ]
    return RunningVmsResult(True, paths)


def normalize_vmx_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(path)))
