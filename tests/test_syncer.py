import hashlib
import inspect
import queue
import subprocess
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from config_manager import ConfigManager
from preflight import PreflightReport
from syncer import SyncManager
import syncer


class Completed:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class SyncManagerTests(unittest.TestCase):
    def test_syncer_log_emit_calls_use_emoji_icons(self):
        source = inspect.getsource(syncer.SyncManager)
        legacy_icons = ('"⏹"', '"✕"', '"✗"', '"✓"', '"ℹ"', '"↗"', '"▶"')

        for icon in legacy_icons:
            self.assertNotIn(icon, source)

    def test_full_sync_cancel_log_uses_cancel_emoji(self):
        manager, _cm = self._manager()

        manager._cancel_full_sync("已在上传前取消")

        _event_type, event = manager.event_queue.get_nowait()
        self.assertEqual("🚫", event.icon)
        self.assertEqual("warning", event.level)

    def _manager(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cm = ConfigManager(str(Path(tmp.name) / "config.json"))
        cm.config.language = "zh"
        return SyncManager(cm), cm

    def test_guest_mtime_returns_none_when_dir_output_cannot_be_parsed(self):
        manager, cm = self._manager()

        with patch("syncer.subprocess.run", return_value=Completed(stdout="unexpected output")):
            mtime = manager._get_guest_mtime(
                r"C:\project\Output\firmware.bin",
                cm.config.vmx_path,
            )

        self.assertIsNone(mtime)

    def test_guest_mtime_uses_absolute_guest_cmd_path(self):
        manager, cm = self._manager()
        cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
        cm.config.vm_guest_user = "h"
        cm.config.vm_guest_password = "password"

        with patch("syncer.subprocess.run", return_value=Completed(stdout="unexpected output")) as run:
            manager._get_guest_mtime(r"C:\project\Output\firmware.bin", cm.config.vmx_path)

        command = run.call_args.args[0]
        self.assertIn(r"C:\Windows\System32\cmd.exe", command)

    def test_guest_file_state_uses_powershell_ticks_length_and_hash(self):
        manager, cm = self._manager()
        cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
        cm.config.vm_guest_user = "h"
        cm.config.vm_guest_password = "password"
        digest = "a" * 64

        with patch(
            "syncer.subprocess.run",
            return_value=Completed(stdout=f"638838144000000000|4096|{digest}\n"),
        ) as run:
            state = manager._get_guest_file_state(
                r"C:\project\Output\firmware.bin",
                cm.config.vmx_path,
            )

        command = run.call_args.args[0]
        command_text = " ".join(command)
        self.assertIn(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe", command)
        self.assertIn("-WindowStyle", command)
        self.assertIn("Hidden", command)
        self.assertIn("-NonInteractive", command)
        self.assertIn("SHA256", command_text)
        self.assertEqual((638838144000000000, 4096, digest), state)

    def test_guest_file_state_falls_back_to_guest_tempfile_sidecar_output(self):
        manager, cm = self._manager()
        cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
        cm.config.vm_guest_user = "h"
        cm.config.vm_guest_password = "password"
        digest = "b" * 64
        commands = []
        guest_temp = r"C:\Users\h\AppData\Local\Temp\vmware-state.tmp"

        def fake_run(cmd, **_kwargs):
            commands.append(cmd)
            if "CreateTempfileInGuest" in cmd:
                return Completed(stdout=guest_temp, returncode=0)
            if "CopyFileFromGuestToHost" in cmd:
                Path(cmd[-1]).write_text(
                    f"638838144000000001|8192|{digest}",
                    encoding="utf-8",
                )
            return Completed(returncode=0)

        with patch("syncer.subprocess.run", side_effect=fake_run):
            state = manager._get_guest_file_state(
                r"C:\project\Output\firmware.bin",
                cm.config.vmx_path,
            )

        self.assertEqual((638838144000000001, 8192, digest), state)
        copied_from = [
            cmd[-2]
            for cmd in commands
            if "CopyFileFromGuestToHost" in cmd
        ]
        self.assertEqual(1, len(copied_from))
        self.assertEqual(guest_temp, copied_from[0])
        self.assertFalse(copied_from[0].startswith("C:\\project\\Output\\"))
        self.assertTrue(any("CreateTempfileInGuest" in cmd for cmd in commands))
        self.assertFalse(any("deleteFileInGuest" in cmd for cmd in commands))

    def test_guest_file_state_reuses_guest_tempfile_after_stdout_is_unavailable(self):
        manager, cm = self._manager()
        cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
        cm.config.vm_guest_user = "h"
        cm.config.vm_guest_password = "password"
        guest_temp = r"C:\Users\h\AppData\Local\Temp\vmware-state.tmp"
        commands = []

        def fake_run(cmd, **_kwargs):
            commands.append(cmd)
            if "CreateTempfileInGuest" in cmd:
                return Completed(stdout=guest_temp, returncode=0)
            if "CopyFileFromGuestToHost" in cmd:
                Path(cmd[-1]).write_text(
                    "638838144000000001|8192|" + ("b" * 64),
                    encoding="utf-8",
                )
                return Completed(returncode=0)
            return Completed(returncode=0)

        with patch("syncer.subprocess.run", side_effect=fake_run):
            first = manager._get_guest_file_state(
                r"C:\project\Output\firmware.bin",
                cm.config.vmx_path,
            )
            second = manager._get_guest_file_state(
                r"C:\project\Output\firmware.bin",
                cm.config.vmx_path,
            )

        self.assertEqual(first, second)
        self.assertEqual(1, sum(1 for cmd in commands if "CreateTempfileInGuest" in cmd))
        self.assertEqual(2, sum(1 for cmd in commands if "CopyFileFromGuestToHost" in cmd))
        self.assertFalse(any("deleteFileInGuest" in cmd for cmd in commands))

    def test_stop_deletes_reused_guest_state_tempfile(self):
        manager, cm = self._manager()
        cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
        cm.config.vmx_path = r"C:\VMs\dev.vmx"
        cm.config.vm_guest_user = "h"
        cm.config.vm_guest_password = "password"
        manager._guest_state_sidecar_vmx = cm.config.vmx_path
        manager._guest_state_sidecar_path = r"C:\Users\h\AppData\Local\Temp\vmware-state.tmp"

        with patch("syncer.subprocess.run", return_value=Completed(returncode=0)) as run:
            manager.stop()

        commands = [call.args[0] for call in run.call_args_list]
        self.assertTrue(any("deleteFileInGuest" in cmd for cmd in commands))

    def test_check_bin_copies_existing_bin_without_guest_mtime(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out

            def fake_run(cmd, **_kwargs):
                if "fileExistsInGuest" in cmd:
                    return Completed(stdout="The file exists.", returncode=0)
                if "CopyFileFromGuestToHost" in cmd:
                    dest = Path(cmd[-1])
                    dest.write_bytes(b"firmware-v1")
                    return Completed(returncode=0)
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run), \
                    patch.object(manager, "_get_guest_mtime", return_value=None):
                manager._check_bin()

            copied = Path(out) / "firmware.bin"
            self.assertEqual(b"firmware-v1", copied.read_bytes())
            self.assertTrue(manager.bin_ready)

    def test_check_bin_skips_guest_copy_when_metadata_is_unchanged(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out

            copies = []

            def fake_run(cmd, **_kwargs):
                if "fileExistsInGuest" in cmd:
                    return Completed(stdout="The file exists.", returncode=0)
                if "CopyFileFromGuestToHost" in cmd:
                    copies.append(cmd)
                    Path(cmd[-1]).write_bytes(b"firmware-v1")
                    return Completed(returncode=0)
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run), \
                    patch.object(
                        manager,
                        "_get_guest_file_state",
                        return_value=(638838144000000000, 11),
                        create=True,
                    ):
                manager._check_bin()
                manager._check_bin()

            self.assertEqual(1, len(copies))

    def test_check_bin_reuses_cached_explicit_bin_target(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out

            file_exists_calls = []

            def fake_run(cmd, **_kwargs):
                if "fileExistsInGuest" in cmd:
                    file_exists_calls.append(cmd)
                    return Completed(stdout="The file exists.", returncode=0)
                if "CopyFileFromGuestToHost" in cmd:
                    Path(cmd[-1]).write_bytes(b"firmware-v1")
                    return Completed(returncode=0)
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run), \
                    patch.object(
                        manager,
                        "_get_guest_file_state",
                        return_value=(638838144000000000, 11, "a" * 64),
                    ):
                manager._check_bin()
                manager._check_bin()

            self.assertEqual(1, len(file_exists_calls))

    def test_check_bin_copies_when_guest_hash_changes_with_same_time_and_size(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out

            copies = []
            payloads = [b"firmware-a", b"firmware-b"]

            def fake_run(cmd, **_kwargs):
                if "fileExistsInGuest" in cmd:
                    return Completed(stdout="The file exists.", returncode=0)
                if "CopyFileFromGuestToHost" in cmd:
                    copies.append(cmd)
                    Path(cmd[-1]).write_bytes(payloads[len(copies) - 1])
                    return Completed(returncode=0)
                return Completed(returncode=0)

            states = [
                (638838144000000000, 10, "a" * 64),
                (638838144000000000, 10, "b" * 64),
            ]
            with patch("syncer.subprocess.run", side_effect=fake_run), \
                    patch.object(manager, "_get_guest_file_state", side_effect=states), \
                    patch("syncer.time.time", side_effect=[100.0, 120.0]):
                manager._check_bin()
                manager._check_bin()

            self.assertEqual(2, len(copies))
            self.assertEqual(b"firmware-b", (Path(out) / "firmware.bin").read_bytes())

    def test_start_ignores_existing_bin_until_guest_bin_content_changes(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out

            copies = []

            def fake_run(cmd, **_kwargs):
                if "fileExistsInGuest" in cmd:
                    return Completed(stdout="The file exists.", returncode=0)
                if "CopyFileFromGuestToHost" in cmd:
                    copies.append(cmd)
                    Path(cmd[-1]).write_bytes(b"firmware-new")
                    return Completed(returncode=0)
                return Completed(returncode=0)

            states = [
                (638838144000000000, 12, "a" * 64),
                (638838144000000000, 12, "a" * 64),
                (638838144000100000, 12, "b" * 64),
            ]
            with patch(
                "syncer.PreflightChecker.check",
                return_value=PreflightReport(),
            ), patch("syncer.subprocess.run", side_effect=fake_run), \
                    patch.object(manager, "_get_guest_file_state", side_effect=states), \
                    patch.object(manager, "_start_observer"), \
                    patch.object(manager, "_start_poller"):
                self.assertTrue(manager.start())
                manager._check_bin()
                self.assertFalse((Path(out) / "firmware.bin").exists())
                self.assertEqual(0, len(copies))

                manager._check_bin()
                self.assertFalse((Path(out) / "firmware.bin").exists())
                self.assertEqual(0, len(copies))

                manager._check_bin()

            self.assertEqual(1, len(copies))
            self.assertEqual(b"firmware-new", (Path(out) / "firmware.bin").read_bytes())

    def test_startup_baseline_same_content_with_new_time_copies_once(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out

            copies = []

            def fake_run(cmd, **_kwargs):
                if "fileExistsInGuest" in cmd:
                    return Completed(stdout="The file exists.", returncode=0)
                if "CopyFileFromGuestToHost" in cmd:
                    copies.append(cmd)
                    Path(cmd[-1]).write_bytes(b"firmware-same")
                    return Completed(returncode=0)
                return Completed(returncode=0)

            states = [
                (638838144000000000, 13, "a" * 64),
                (638838144000100000, 13, "a" * 64),
                (638838144000200000, 13, "a" * 64),
            ]
            with patch(
                "syncer.PreflightChecker.check",
                return_value=PreflightReport(),
            ), patch("syncer.subprocess.run", side_effect=fake_run), \
                    patch.object(manager, "_get_guest_file_state", side_effect=states), \
                    patch.object(manager, "_start_observer"), \
                    patch.object(manager, "_start_poller"):
                self.assertTrue(manager.start())
                manager._check_bin()
                manager._check_bin()
                manager._check_bin()

            self.assertEqual(1, len(copies))
            self.assertEqual(b"firmware-same", (Path(out) / "firmware.bin").read_bytes())
            logs = []
            while not manager.event_queue.empty():
                event_type, data = manager.event_queue.get_nowait()
                if event_type == "log":
                    logs.append(data.message)
            self.assertTrue(any("首次记录后 .bin 时间已更新" in message for message in logs))

    def test_start_uses_temp_signature_baseline_when_guest_state_is_unavailable(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out

            payloads = [b"firmware-old", b"firmware-old", b"firmware-new"]

            def fake_run(cmd, **_kwargs):
                if "fileExistsInGuest" in cmd:
                    return Completed(stdout="The file exists.", returncode=0)
                if "CopyFileFromGuestToHost" in cmd:
                    Path(cmd[-1]).write_bytes(payloads.pop(0))
                    return Completed(returncode=0)
                return Completed(returncode=0)

            with patch(
                "syncer.PreflightChecker.check",
                return_value=PreflightReport(),
            ), patch("syncer.subprocess.run", side_effect=fake_run), \
                    patch.object(manager, "_get_guest_file_state", return_value=None), \
                    patch.object(manager, "_start_observer"), \
                    patch.object(manager, "_start_poller"):
                self.assertTrue(manager.start())
                manager._check_bin()
                self.assertFalse((Path(out) / "firmware.bin").exists())

                manager._check_bin()
                self.assertFalse((Path(out) / "firmware.bin").exists())

                manager._check_bin()

            self.assertEqual(b"firmware-new", (Path(out) / "firmware.bin").read_bytes())

    def test_check_bin_logs_when_guest_state_changes_but_content_is_unchanged(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out

            copies = []
            def fake_run(cmd, **_kwargs):
                if "fileExistsInGuest" in cmd:
                    return Completed(stdout="The file exists.", returncode=0)
                if "CopyFileFromGuestToHost" in cmd:
                    copies.append(cmd)
                    Path(cmd[-1]).write_bytes(b"firmware-v1")
                    return Completed(returncode=0)
                return Completed(returncode=0)

            states = [
                (638838144000000000, 11, "a" * 64),
                (638838144000100000, 11, "a" * 64),
            ]
            with patch("syncer.subprocess.run", side_effect=fake_run), \
                    patch.object(manager, "_get_guest_file_state", side_effect=states), \
                    patch("syncer.time.time", side_effect=[100.0, 120.0]):
                manager._check_bin()
                manager._check_bin()

            self.assertEqual(1, len(copies))
            logs = []
            unchanged_events = []
            while not manager.event_queue.empty():
                event_type, data = manager.event_queue.get_nowait()
                if event_type == "log":
                    logs.append(data.message)
                if event_type == "bin_unchanged":
                    unchanged_events.append(data)
            self.assertTrue(any("firmware.bin" in message for message in logs))
            self.assertEqual(["firmware.bin"], unchanged_events)

    def test_recent_post_copy_timestamp_drift_is_suppressed(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out

            copies = []

            def fake_run(cmd, **_kwargs):
                if "fileExistsInGuest" in cmd:
                    return Completed(stdout="The file exists.", returncode=0)
                if "CopyFileFromGuestToHost" in cmd:
                    copies.append(cmd)
                    Path(cmd[-1]).write_bytes(b"firmware-v1")
                    return Completed(returncode=0)
                return Completed(returncode=0)

            digest = hashlib.sha256(b"firmware-v1").hexdigest()
            states = [
                (638838144000000000, 11, digest),
                (638838144000200000, 11, digest),
            ]
            with patch("syncer.subprocess.run", side_effect=fake_run), \
                    patch.object(manager, "_get_guest_file_state", side_effect=states), \
                    patch("syncer.time.time", side_effect=[100.0, 104.0]):
                manager._check_bin()
                manager._check_bin()

            self.assertEqual(1, len(copies))
            self.assertEqual(
                (r"c:\project\output\firmware.bin", 638838144000200000, 11, digest),
                manager._last_bin_state,
            )
            logs = []
            unchanged_events = []
            while not manager.event_queue.empty():
                event_type, data = manager.event_queue.get_nowait()
                if event_type == "log":
                    logs.append(data.message)
                if event_type == "bin_unchanged":
                    unchanged_events.append(data)
            self.assertFalse(any("内容未变化" in message for message in logs))
            self.assertEqual([], unchanged_events)

    def test_stop_suppresses_late_unchanged_bin_update_events(self):
        manager, _cm = self._manager()
        manager._stop_requested = True

        manager._log_bin_content_unchanged_once(("bin", "state"), "firmware.bin")

        self.assertTrue(manager.event_queue.empty())

    def test_stop_during_bin_state_read_suppresses_late_guest_copy(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out
            manager._last_bin_state = (
                r"c:\project\output\firmware.bin",
                638838144000000000,
                11,
                "a" * 64,
            )
            (Path(out) / "firmware.bin").write_bytes(b"firmware-v1")

            copies = []

            def stop_during_state_read(_vm_path, _vmx):
                manager._stop_requested = True
                return (638838144000100000, 11, "b" * 64)

            def fake_run(cmd, **_kwargs):
                if "fileExistsInGuest" in cmd:
                    return Completed(stdout="The file exists.", returncode=0)
                if "CopyFileFromGuestToHost" in cmd:
                    copies.append(cmd)
                    Path(cmd[-1]).write_bytes(b"firmware-v2")
                    return Completed(returncode=0)
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run), \
                    patch.object(manager, "_get_guest_file_state", side_effect=stop_during_state_read):
                manager._check_bin()

            self.assertEqual([], copies)
            self.assertEqual(b"firmware-v1", (Path(out) / "firmware.bin").read_bytes())

    def test_poll_loop_logs_unexpected_bin_check_errors(self):
        manager, cm = self._manager()
        cm.config.poll_interval_sec = 1
        manager._running = True

        def fail_once():
            manager._running = False
            raise RuntimeError("metadata failed")

        with patch.object(manager, "_check_bin", side_effect=fail_once):
            manager._poll_loop()

        logs = []
        while not manager.event_queue.empty():
            event_type, data = manager.event_queue.get_nowait()
            if event_type == "log":
                logs.append(data.message)

        self.assertTrue(any(".bin" in message for message in logs))

    def test_check_bin_uses_system_temp_dir_for_guest_copy(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out

            temp_destinations = []

            def fake_run(cmd, **_kwargs):
                if "fileExistsInGuest" in cmd:
                    return Completed(stdout="The file exists.", returncode=0)
                if "CopyFileFromGuestToHost" in cmd:
                    temp_destinations.append(Path(cmd[-1]))
                    Path(cmd[-1]).write_bytes(b"firmware-v1")
                    return Completed(returncode=0)
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run), \
                    patch.object(
                        manager,
                        "_get_guest_file_state",
                        return_value=None,
                        create=True,
                    ):
                manager._check_bin()

            self.assertEqual(1, len(temp_destinations))
            self.assertNotEqual(Path(out), temp_destinations[0].parent)

    def test_check_bin_logs_unchanged_content_when_guest_state_is_unavailable(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out

            def fake_run(cmd, **_kwargs):
                if "fileExistsInGuest" in cmd:
                    return Completed(stdout="The file exists.", returncode=0)
                if "CopyFileFromGuestToHost" in cmd:
                    Path(cmd[-1]).write_bytes(b"firmware-v1")
                    return Completed(returncode=0)
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run), \
                    patch.object(manager, "_get_guest_file_state", return_value=None):
                manager._check_bin()
                manager._check_bin()

            logs = []
            bin_ready_count = 0
            while not manager.event_queue.empty():
                event_type, data = manager.event_queue.get_nowait()
                if event_type == "log":
                    logs.append(data.message)
                if event_type == "bin_ready":
                    bin_ready_count += 1

            self.assertTrue(any("内容未变化" in message for message in logs))
            self.assertEqual(1, bin_ready_count)

    def test_check_bin_does_not_notify_again_when_content_is_unchanged(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out

            def fake_run(cmd, **_kwargs):
                if "fileExistsInGuest" in cmd:
                    return Completed(stdout="The file exists.", returncode=0)
                if "CopyFileFromGuestToHost" in cmd:
                    Path(cmd[-1]).write_bytes(b"firmware-v1")
                    return Completed(returncode=0)
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run):
                manager._check_bin()
                manager._check_bin()

            bin_ready_count = 0
            logs = []
            while not manager.event_queue.empty():
                event_type, data = manager.event_queue.get_nowait()
                if event_type == "bin_ready":
                    bin_ready_count += 1
                if event_type == "log":
                    logs.append(data.message)

            self.assertEqual(1, bin_ready_count)
            self.assertTrue(any("内容未变化" in message for message in logs))

    def test_check_bin_uses_single_bin_from_configured_directory(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\RL6492"
            cm.config.host_output_path = out

            copied_from = []

            def fake_run(cmd, **_kwargs):
                if "listDirectoryInGuest" in cmd:
                    return Completed(stdout="RL6492_Project_WithChkSum.bin\n", returncode=0)
                if "CopyFileFromGuestToHost" in cmd:
                    copied_from.append(cmd[-2])
                    Path(cmd[-1]).write_bytes(b"firmware-v2")
                    return Completed(returncode=0)
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run), \
                    patch.object(manager, "_get_guest_file_state", return_value=None):
                manager._check_bin()

            self.assertEqual(
                [r"C:\project\Output\RL6492\RL6492_Project_WithChkSum.bin"],
                copied_from,
            )
            self.assertEqual(
                b"firmware-v2",
                (Path(out) / "RL6492_Project_WithChkSum.bin").read_bytes(),
            )

    def test_check_bin_does_not_fallback_when_configured_file_is_missing(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\RL6492\wrong.bin"
            cm.config.host_output_path = out

            commands = []

            def fake_run(cmd, **_kwargs):
                commands.append(cmd)
                if "fileExistsInGuest" in cmd:
                    return Completed(stdout="The file does not exist.", returncode=1)
                if "listDirectoryInGuest" in cmd:
                    return Completed(stdout="actual.bin\n", returncode=0)
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run):
                manager._check_bin()

            self.assertFalse(any("CopyFileFromGuestToHost" in cmd for cmd in commands))
            logs = []
            while not manager.event_queue.empty():
                event_type, data = manager.event_queue.get_nowait()
                if event_type == "log":
                    logs.append(data.message)
            log_text = "\n".join(logs)
            self.assertIn(r"Output\RL6492\wrong.bin", log_text)
            self.assertIn("actual.bin", log_text)

    def test_check_bin_warns_when_directory_has_multiple_bins(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\RL6492"
            cm.config.host_output_path = out

            commands = []

            def fake_run(cmd, **_kwargs):
                commands.append(cmd)
                if "listDirectoryInGuest" in cmd:
                    return Completed(stdout="a.bin\nb.bin\n", returncode=0)
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run):
                manager._check_bin()

            self.assertFalse(any("CopyFileFromGuestToHost" in cmd for cmd in commands))
            logs = []
            while not manager.event_queue.empty():
                event_type, data = manager.event_queue.get_nowait()
                if event_type == "log":
                    self.assertEqual("error", data.level)
                    logs.append(data.message)
            warning_text = "\n".join(logs)
            self.assertIn("多个 .bin", warning_text)
            self.assertIn(".bin 相对路径", warning_text)
            self.assertIn(r"Output\RL6492\a.bin", warning_text)
            self.assertIn(r"Output\RL6492\b.bin", warning_text)

    def test_vmrun_error_handles_none_stdout_and_stderr(self):
        manager, _cm = self._manager()

        message = manager._vmrun_error(Completed(stdout=None, stderr=None, returncode=1))

        self.assertEqual("unknown error (return code 1)", message)

    def test_full_sync_uses_native_guest_directory_commands(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as host:
            host_root = Path(host)
            (host_root / "main.c").write_text("int main(void) { return 0; }", encoding="utf-8")
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.host_project_path = host
            cm.config.vm_project_path = r"C:\project"
            cm.config.host_output_path = host

            commands = []

            def fake_run(cmd, **_kwargs):
                commands.append(cmd)
                if "directoryExistsInGuest" in cmd:
                    return Completed(stdout="The directory exists.", returncode=0)
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run):
                manager.full_sync()

        flattened = [" ".join(cmd) for cmd in commands]
        self.assertTrue(any("directoryExistsInGuest" in cmd for cmd in flattened))
        self.assertFalse(any("cmd.exe /c if not exist" in cmd for cmd in flattened))

    def test_start_does_not_run_when_host_project_path_is_invalid(self):
        manager, cm = self._manager()
        cm.config.vmx_path = r"C:\vm\machine.vmx"
        cm.config.host_project_path = r"C:\definitely\missing\project"
        cm.config.vm_project_path = r"C:\project"
        cm.config.host_output_path = r"C:\output"

        started = manager.start()

        self.assertFalse(started)
        self.assertFalse(manager.running)

    def test_start_does_not_prime_bin_baseline_before_reporting_running(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out

            def fake_run(cmd, **_kwargs):
                if "fileExistsInGuest" in cmd:
                    return Completed(stdout="The file exists.", returncode=0)
                return Completed(returncode=0)

            with patch(
                "syncer.PreflightChecker.check",
                return_value=PreflightReport(),
            ), patch("syncer.subprocess.run", side_effect=fake_run), \
                    patch.object(
                        manager,
                        "_get_guest_file_state",
                        side_effect=AssertionError("baseline should be lazy"),
                    ), patch.object(
                        manager,
                        "_read_guest_bin_signature",
                        side_effect=AssertionError("baseline should be lazy"),
                    ), patch.object(manager, "_start_observer"), \
                    patch.object(manager, "_start_poller"):
                started = manager.start()

        self.assertTrue(started)
        self.assertTrue(manager.running)

    def test_prechecked_start_reuses_cached_bin_target_when_snapshot_matches(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out
            manager._cached_bin_target_key = manager._bin_target_cache_key()
            manager._cached_bin_target = (r"C:\project\Output\firmware.bin", "firmware.bin")
            snapshot = manager.preflight_snapshot()

            with patch("syncer.subprocess.run") as run, \
                    patch.object(manager, "_start_observer"), \
                    patch.object(manager, "_start_poller"):
                started = manager.start(
                    preflight_checked=True,
                    preflight_snapshot=snapshot,
                )

        self.assertTrue(started)
        run.assert_not_called()

    def test_prechecked_start_rechecks_when_snapshot_is_stale(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out
            stale_snapshot = manager.preflight_snapshot()
            cm.config.host_project_path = r"C:\changed\after\preflight"

            with patch(
                "syncer.PreflightChecker.check",
                return_value=PreflightReport(errors=["bad changed path"]),
            ) as check, patch("syncer.subprocess.run") as run, \
                    patch.object(manager, "_start_observer"), \
                    patch.object(manager, "_start_poller"):
                started = manager.start(
                    preflight_checked=True,
                    preflight_snapshot=stale_snapshot,
                )

        self.assertFalse(started)
        self.assertFalse(manager.running)
        check.assert_called_once()
        run.assert_not_called()

    def test_start_rejects_ambiguous_bin_directory_before_running(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\RL6492"
            cm.config.host_output_path = out

            def fake_run(cmd, **_kwargs):
                if "listDirectoryInGuest" in cmd:
                    return Completed(stdout="a.bin\nb.bin\n", returncode=0)
                return Completed(returncode=0)

            with patch(
                "syncer.PreflightChecker.check",
                return_value=PreflightReport(),
            ), patch("syncer.subprocess.run", side_effect=fake_run), \
                    patch.object(manager, "_start_observer") as start_observer, \
                    patch.object(manager, "_start_poller") as start_poller:
                started = manager.start()

        self.assertFalse(started)
        self.assertFalse(manager.running)
        start_observer.assert_not_called()
        start_poller.assert_not_called()

        logs = []
        while not manager.event_queue.empty():
            event_type, data = manager.event_queue.get_nowait()
            if event_type == "log":
                logs.append(data.message)
        log_text = "\n".join(logs)
        self.assertIn(".bin", log_text)
        self.assertIn(r"Output\RL6492\a.bin", log_text)
        self.assertIn(r"Output\RL6492\b.bin", log_text)

    def test_start_rejects_missing_explicit_bin_file_before_running(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\RL6492\wrong.bin"
            cm.config.host_output_path = out

            def fake_run(cmd, **_kwargs):
                if "fileExistsInGuest" in cmd:
                    return Completed(stdout="The file does not exist.", returncode=1)
                if "listDirectoryInGuest" in cmd:
                    return Completed(stdout="actual.bin\n", returncode=0)
                return Completed(returncode=0)

            with patch(
                "syncer.PreflightChecker.check",
                return_value=PreflightReport(),
            ), patch("syncer.subprocess.run", side_effect=fake_run), \
                    patch.object(manager, "_start_observer") as start_observer, \
                    patch.object(manager, "_start_poller") as start_poller:
                started = manager.start()

        self.assertFalse(started)
        self.assertFalse(manager.running)
        start_observer.assert_not_called()
        start_poller.assert_not_called()

    def test_pending_debounce_timer_does_not_fire_after_stop(self):
        fired = []
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as host:
            cm.config.host_project_path = host
            cm.config.vmx_path = r"C:\vm\machine.vmx"
            cm.config.vm_project_path = r"C:\project"
            cm.config.host_output_path = host

            with patch.object(manager, "_can_start", return_value=True), \
                    patch.object(manager, "_start_poller"):
                self.assertTrue(manager.start())
            manager._debouncer.callback = lambda path: fired.append(path)
            manager._on_file_changed(str(Path(host) / "main.c"))
            manager.stop()
            time.sleep((cm.config.debounce_ms / 1000.0) + 0.2)

        self.assertEqual([], fired)

    def test_incremental_changes_are_enqueued_for_single_worker(self):
        queued = []
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as host:
            cm.config.host_project_path = host
            cm.config.vmx_path = r"C:\vm\machine.vmx"
            cm.config.vm_project_path = r"C:\project"
            cm.config.host_output_path = host

            with patch.object(manager, "_can_start", return_value=True), \
                    patch.object(manager, "_start_poller"), \
                    patch.object(manager, "_start_copy_worker") as start_worker:
                self.assertTrue(manager.start())

            manager._debouncer.callback = lambda path: queued.append(path)
            first = str(Path(host) / "main.c")
            second = str(Path(host) / "util.c")
            manager._on_file_changed(first)
            manager._on_file_changed(second)
            time.sleep((cm.config.debounce_ms / 1000.0) + 0.2)
            manager.stop()

        start_worker.assert_called_once()
        self.assertCountEqual([first, second], queued)

    def test_incremental_event_without_content_change_is_not_enqueued(self):
        queued = []
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as host:
            host_root = Path(host)
            host_file = host_root / "Src" / "main.c"
            host_file.parent.mkdir()
            host_file.write_text("int main(void) { return 0; }", encoding="utf-8")
            cm.config.host_project_path = host
            cm.config.vmx_path = r"C:\vm\machine.vmx"
            cm.config.vm_project_path = r"C:\project"
            cm.config.host_output_path = host

            with patch.object(manager, "_can_start", return_value=True), \
                    patch.object(manager, "_start_poller"), \
                    patch.object(manager, "_start_copy_worker"):
                self.assertTrue(manager.start())

            manager._copy_queue = queue.Queue()
            manager._on_file_changed(str(host_file))
            time.sleep((cm.config.debounce_ms / 1000.0) + 0.2)
            while not manager._copy_queue.empty():
                queued.append(manager._copy_queue.get_nowait())
            manager.stop()

        self.assertEqual([], queued)

    def test_incremental_event_with_content_change_is_enqueued_once(self):
        queued = []
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as host:
            host_root = Path(host)
            host_file = host_root / "Src" / "main.c"
            host_file.parent.mkdir()
            host_file.write_text("int main(void) { return 0; }", encoding="utf-8")
            cm.config.host_project_path = host
            cm.config.vmx_path = r"C:\vm\machine.vmx"
            cm.config.vm_project_path = r"C:\project"
            cm.config.host_output_path = host

            with patch.object(manager, "_can_start", return_value=True), \
                    patch.object(manager, "_start_poller"), \
                    patch.object(manager, "_start_copy_worker"):
                self.assertTrue(manager.start())

            manager._copy_queue = queue.Queue()
            host_file.write_text("int main(void) { return 1; }", encoding="utf-8")
            manager._on_file_changed(str(host_file))
            manager._on_file_changed(str(host_file))
            time.sleep((cm.config.debounce_ms / 1000.0) + 0.2)
            while not manager._copy_queue.empty():
                queued.append(manager._copy_queue.get_nowait())
            manager.stop()

        self.assertEqual([str(host_file)], queued)

    def test_incremental_timeout_suspends_uploads_and_clears_queue(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as host:
            host_root = Path(host)
            first = host_root / "Src" / "main.c"
            second = host_root / "Src" / "util.c"
            first.parent.mkdir()
            first.write_text("int main(void) { return 0; }", encoding="utf-8")
            second.write_text("int util(void) { return 0; }", encoding="utf-8")
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.host_project_path = host
            cm.config.vm_project_path = r"C:\project"

            commands = []

            def fake_run(cmd, **_kwargs):
                commands.append(cmd)
                raise subprocess.TimeoutExpired(cmd, 15)

            with patch("syncer.subprocess.run", side_effect=fake_run):
                manager._running = True
                manager._copy_queue = queue.Queue()
                manager._copy_pending = {str(first), str(second)}
                manager._copy_queue.put(str(first))
                manager._copy_queue.put(str(second))
                manager._copy_worker_loop()

        self.assertTrue(manager._incremental_sync_suspended)
        self.assertEqual(1, len(commands))
        self.assertEqual(set(), manager._copy_pending)
        self.assertTrue(manager._copy_queue.empty())
        logs = []
        while not manager.event_queue.empty():
            event_type, data = manager.event_queue.get_nowait()
            if event_type == "log":
                logs.append(data.message)
        self.assertTrue(any("增量同步已暂停" in message for message in logs))

    def test_incremental_copy_uses_guest_temp_then_move(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as host:
            host_root = Path(host)
            host_file = host_root / "Src" / "main.c"
            host_file.parent.mkdir()
            host_file.write_text("int main(void) { return 0; }", encoding="utf-8")
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.host_project_path = host
            cm.config.vm_project_path = r"C:\project"

            commands = []

            def fake_run(cmd, **_kwargs):
                commands.append(cmd)
                if "directoryExistsInGuest" in cmd:
                    return Completed(stdout="The directory exists.", returncode=0)
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run):
                manager._running = True
                manager._do_copy_to_vm(str(host_file))

        copy_commands = [cmd for cmd in commands if "CopyFileFromHostToGuest" in cmd]
        self.assertEqual(1, len(copy_commands))
        copied_dest = copy_commands[0][-1]
        self.assertIn(".vm_sync_tmp", copied_dest)
        command_text = "\n".join(" ".join(cmd) for cmd in commands)
        self.assertIn("Move-Item", command_text)
        self.assertIn(r"C:\project\Src\main.c", command_text)

    def test_full_sync_cancel_after_upload_cleans_guest_temp_paths(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as host:
            host_root = Path(host)
            (host_root / "main.c").write_text("int main(void) { return 0; }", encoding="utf-8")
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.host_project_path = host
            cm.config.vm_project_path = r"C:\project"
            cm.config.host_output_path = host

            commands = []
            guest_temp = r"C:\Users\h\AppData\Local\Temp\vm-sync.tmp"

            def fake_run(cmd, **_kwargs):
                commands.append(cmd)
                if "CreateTempfileInGuest" in cmd:
                    return Completed(stdout=guest_temp, returncode=0)
                if "CopyFileFromHostToGuest" in cmd:
                    manager.request_full_sync_cancel()
                    return Completed(returncode=0)
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run):
                count = manager.full_sync()

        self.assertEqual(0, count)
        command_text = "\n".join(" ".join(cmd) for cmd in commands)
        self.assertIn(guest_temp + ".zip", command_text)
        self.assertIn("Remove-Item", command_text)
        self.assertIn(guest_temp + "_extract", command_text)
        self.assertNotIn("Expand-Archive", command_text)

    def test_cleanup_treats_missing_guest_path_as_success(self):
        manager, cm = self._manager()
        cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
        cm.config.vm_guest_user = "h"
        cm.config.vm_guest_password = "password"

        commands = []

        def fake_run(cmd, **_kwargs):
            commands.append(cmd)
            return Completed(returncode=0)

        with patch("syncer.subprocess.run", side_effect=fake_run):
            cleaned = manager._cleanup_guest_path(
                r"C:\VMs\dev.vmx",
                r"C:\Users\h\AppData\Local\Temp\vmware55_extract",
                is_dir=True,
            )

        self.assertTrue(cleaned)
        command_text = " ".join(commands[0])
        self.assertIn("Test-Path", command_text)
        self.assertIn("Remove-Item", command_text)

    def test_full_sync_uploads_one_zip_and_extracts_it_in_guest(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as host:
            host_root = Path(host)
            (host_root / "main.c").write_text("int main(void) { return 0; }", encoding="utf-8")
            (host_root / "legacy.uvproj").write_text("<Project />", encoding="utf-8")
            (host_root / "ignored.bin").write_text("nope", encoding="utf-8")
            (host_root / "Tool" / "precompile").mkdir(parents=True)
            (host_root / "Tool" / "precompile" / "pch_support.bat").write_text("@echo off\n", encoding="utf-8")
            (host_root / "Tool" / "precompile" / "helper.exe").write_bytes(b"MZ")
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.host_project_path = host
            cm.config.vm_project_path = r"C:\project"
            cm.config.host_output_path = host

            commands = []

            def fake_run(cmd, **_kwargs):
                commands.append(cmd)
                if "CopyFileFromHostToGuest" in cmd:
                    zip_path = Path(cmd[3])
                    zip_path = Path(cmd[cmd.index("CopyFileFromHostToGuest") + 2])
                    self.assertTrue(zip_path.exists())
                    with zipfile.ZipFile(zip_path) as archive:
                        self.assertEqual(
                            sorted(archive.namelist()),
                            [
                                "Tool/precompile/helper.exe",
                                "Tool/precompile/pch_support.bat",
                                "ignored.bin",
                                "legacy.uvproj",
                                "main.c",
                            ],
                        )
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run):
                count = manager.full_sync()

        self.assertEqual(5, count)
        copy_commands = [cmd for cmd in commands if "CopyFileFromHostToGuest" in cmd]
        self.assertEqual(1, len(copy_commands))
        self.assertIn("-gu", copy_commands[0])
        self.assertIn("-gp", copy_commands[0])
        self.assertTrue(any("Expand-Archive" in " ".join(cmd) for cmd in commands))
        self.assertTrue(any("Copy-Item" in " ".join(cmd) for cmd in commands))
        self.assertTrue(any(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" in cmd for cmd in commands))
        powershell_commands = [
            cmd for cmd in commands
            if r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" in cmd
        ]
        self.assertTrue(all("-WindowStyle" in cmd and "Hidden" in cmd for cmd in powershell_commands))
        self.assertTrue(all("-NonInteractive" in cmd for cmd in powershell_commands))
        self.assertTrue(any("Remove-Item" in " ".join(cmd) for cmd in commands))

    def test_full_sync_rejects_empty_guest_password_before_vmrun(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as host:
            (Path(host) / "main.c").write_text("int main(void) { return 0; }", encoding="utf-8")
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = ""
            cm.config.host_project_path = host
            cm.config.vm_project_path = r"C:\project"
            cm.config.host_output_path = host

            with patch("syncer.subprocess.run") as run:
                count = manager.full_sync()

        self.assertEqual(0, count)
        run.assert_not_called()

    def test_full_sync_emits_progress_events(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as host:
            host_root = Path(host)
            (host_root / "main.c").write_text("int main(void) { return 0; }", encoding="utf-8")
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.host_project_path = host
            cm.config.vm_project_path = r"C:\project"
            cm.config.host_output_path = host

            with patch("syncer.subprocess.run", return_value=Completed(returncode=0)):
                manager.full_sync()

        progress = []
        while not manager.event_queue.empty():
            event_type, data = manager.event_queue.get_nowait()
            if event_type == "full_sync_progress":
                progress.append(data)

        self.assertGreaterEqual(len(progress), 2)
        self.assertEqual(0.0, progress[0]["value"])
        self.assertEqual(1.0, progress[-1]["value"])
        self.assertFalse(progress[-1]["active"])

    def test_full_sync_failure_stops_progress(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as host:
            host_root = Path(host)
            (host_root / "main.c").write_text("int main(void) { return 0; }", encoding="utf-8")
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.host_project_path = host
            cm.config.vm_project_path = r"C:\project"
            cm.config.host_output_path = host

            def fake_run(cmd, **_kwargs):
                if "CopyFileFromHostToGuest" in cmd:
                    return Completed(stderr="copy failed", returncode=1)
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run):
                count = manager.full_sync()

        self.assertEqual(0, count)
        progress = []
        while not manager.event_queue.empty():
            event_type, data = manager.event_queue.get_nowait()
            if event_type == "full_sync_progress":
                progress.append(data)

        self.assertFalse(progress[-1]["active"])
        self.assertIn("失败", progress[-1]["message"])


if __name__ == "__main__":
    unittest.main()
