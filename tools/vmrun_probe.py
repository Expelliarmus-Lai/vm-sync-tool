"""One-shot vmrun connectivity probe for the current Windows desktop user."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path


CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "vmrun_probe_result.txt"
GUEST_CMD = r"C:\Windows\System32\cmd.exe"
GUEST_POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


def hide_password(args: list[str]) -> str:
    safe = []
    hide_next = False
    for arg in args:
        if hide_next:
            safe.append("******")
            hide_next = False
            continue
        safe.append(arg)
        if arg == "-gp":
            hide_next = True
    return " ".join(safe)


def write(line: str = ""):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def run(label: str, args: list[str], timeout: int = 30):
    write(f"--- {label} ---")
    write("cmd: " + hide_password(args))
    start = time.time()
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=CREATE_FLAGS,
        )
    except subprocess.TimeoutExpired:
        write(f"TIMEOUT: {timeout}s")
        write()
        return None

    elapsed = time.time() - start
    write(f"returncode: {result.returncode} elapsed:{elapsed:.1f}s")
    if result.stdout.strip():
        write("stdout: " + result.stdout.strip())
    if result.stderr.strip():
        write("stderr: " + result.stderr.strip())
    write()
    return result


def main() -> int:
    LOG.write_text("", encoding="utf-8")
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    vmrun = cfg.get("vmrun_path", "")
    vmx = cfg.get("vmx_path", "")
    vm_project = cfg.get("vm_project_path", "")
    password = cfg.get("vm_guest_password", "")
    users = []
    for user in [cfg.get("vm_guest_user", ""), "h", "管理员", "Administrator"]:
        if user and user not in users:
            users.append(user)

    write("=== VM Sync vmrun probe ===")
    write("host user: " + os.getlogin())
    write("vmrun_path: " + vmrun)
    write("vmrun_exists: " + str(Path(vmrun).exists()))
    write("vmx_path: " + vmx)
    write("vmx_exists: " + str(Path(vmx).exists()))
    write("vm_project_path: " + vm_project)
    write("candidate_users: " + ", ".join(users))
    write()

    if not Path(vmrun).exists() or not Path(vmx).exists() or not vm_project:
        write("RESULT: basic config invalid")
        return 2

    list_result = run("vmrun list", [vmrun, "list"], timeout=40)
    if list_result and list_result.returncode == 0:
        running = [
            line.strip()
            for line in list_result.stdout.splitlines()
            if line.strip().lower().endswith(".vmx")
        ]
        configured = os.path.normcase(os.path.abspath(vmx))
        running_set = {os.path.normcase(os.path.abspath(path)) for path in running}
        write("configured_vmx_in_running_list: " + str(configured in running_set))
        for path in running:
            write("running: " + path)
        write()

    probe_host = ROOT / "__vm_sync_probe_host.txt"
    probe_back = ROOT / "__vm_sync_probe_back.txt"
    probe_name = f"__vm_sync_probe_{int(time.time())}.txt"
    probe_guest = vm_project.rstrip("\\/") + "\\" + probe_name
    probe_host.write_text("vm-sync-probe-ok\n", encoding="utf-8")
    probe_back.unlink(missing_ok=True)

    try:
        for user in users:
            write("====== user: " + user + " ======")
            base = [vmrun, "-gu", user, "-gp", password]
            run("whoami in guest", base + ["runProgramInGuest", vmx, GUEST_CMD, "/c", "whoami"])
            run(
                "powershell in guest",
                base + [
                    "runProgramInGuest",
                    vmx,
                    GUEST_POWERSHELL,
                    "-NoProfile",
                    "-Command",
                    "Write-Output probe",
                ],
            )
            exists = run(
                "directoryExistsInGuest target dir",
                base + ["directoryExistsInGuest", vmx, vm_project],
            )
            if exists is not None and exists.returncode != 0:
                run(
                    "createDirectoryInGuest target dir",
                    base + ["createDirectoryInGuest", vmx, vm_project],
                )

            copied = run(
                "CopyFileFromHostToGuest probe",
                base + ["CopyFileFromHostToGuest", vmx, str(probe_host), probe_guest],
                timeout=60,
            )
            if copied is None or copied.returncode != 0:
                continue

            exists = run("fileExistsInGuest probe", base + ["fileExistsInGuest", vmx, probe_guest])
            if exists is None or exists.returncode != 0:
                continue

            back = run(
                "CopyFileFromGuestToHost probe back",
                base + ["CopyFileFromGuestToHost", vmx, probe_guest, str(probe_back)],
                timeout=60,
            )
            if back is None or back.returncode != 0:
                continue

            ok = probe_back.exists() and probe_back.read_text(encoding="utf-8", errors="replace") == "vm-sync-probe-ok\n"
            write("roundtrip_content_ok: " + str(ok))
            run(
                "cleanup guest probe",
                base + ["deleteFileInGuest", vmx, probe_guest],
            )
            if ok:
                write("RESULT: OK user=" + user)
                return 0

        write("RESULT: FAILED")
        return 1
    finally:
        probe_host.unlink(missing_ok=True)
        probe_back.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
