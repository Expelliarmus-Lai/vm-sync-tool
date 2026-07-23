import hashlib
import inspect
import queue
import subprocess
import tempfile
import threading
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
        legacy_icons = ('"⏹"', '"✕"', '"✗"', '"✓"', '"ℹ"', '"ℹ️"', '"↗"', '"▶"')

        for icon in legacy_icons:
            self.assertNotIn(icon, source)

    def test_info_log_icon_uses_color_emoji(self):
        self.assertEqual("💡", syncer.LogIcon.INFO)

    def test_firmware_ready_log_uses_fire_icon(self):
        self.assertEqual("🔥", syncer.LogIcon.FIRMWARE)

    def test_translator_is_cached_until_language_changes(self):
        manager, cm = self._manager()

        self.assertEqual("同步服务已启动", manager._tr("sync.service_started"))
        first_translator = manager._translator
        self.assertEqual("同步服务已停止", manager._tr("sync.service_stopped"))
        self.assertIs(first_translator, manager._translator)

        cm.config.language = "en"
        self.assertEqual("Sync service started", manager._tr("sync.service_started"))
        self.assertIsNot(first_translator, manager._translator)

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

    def test_moved_file_to_watched_extension_is_enqueued_at_destination(self):
        manager, _cm = self._manager()
        handler = syncer.ProjectFileHandler(manager)
        event = type(
            "MovedEvent",
            (),
            {
                "is_directory": False,
                "src_path": r"C:\project\.claude_tmp",
                "dest_path": r"C:\project\Src\main.c",
            },
        )()

        with patch.object(manager, "_on_file_changed") as changed:
            handler.on_moved(event)

        changed.assert_called_once_with(r"C:\project\Src\main.c")

    def test_bin_ready_event_includes_actual_return_time(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out
            manager._running = True
            manager._run_token = 1

            def fake_run(cmd, **_kwargs):
                if "CopyFileFromGuestToHost" in cmd:
                    Path(cmd[-1]).write_bytes(b"firmware-v2")
                return Completed(returncode=0)

            with patch.object(
                manager,
                "_resolve_vm_bin_cached",
                return_value=(r"C:\project\Output\firmware.bin", "firmware.bin"),
            ), patch.object(
                manager,
                "_get_guest_file_state",
                return_value=(123, 11, hashlib.sha256(b"firmware-v2").hexdigest()),
            ), patch("syncer.subprocess.run", side_effect=fake_run), patch(
                "syncer.time.time", return_value=1753243200.0
            ):
                manager._check_bin(run_token=1)

            bin_ready_events = [
                data
                for event_type, data in list(manager.event_queue.queue)
                if event_type == "bin_ready"
            ]

        self.assertEqual("firmware.bin", bin_ready_events[-1]["filename"])
        self.assertEqual(1753243200.0, bin_ready_events[-1]["returned_at"])
        self.assertNotIn("local_mtime", bin_ready_events[-1])

    def test_powered_off_guest_state_error_stops_before_fallback_copy(self):
        manager, cm = self._manager()
        cm.config.vmx_path = r"C:\VMs\dev.vmx"
        cm.config.vm_project_path = r"C:\project"
        cm.config.vm_bin_relative_path = r"Output\firmware.bin"
        manager._running = True
        manager._run_token = 1
        powered_off = Completed(
            stderr="Error: The virtual machine is not powered on",
            returncode=1,
        )

        def fail_state_read(_vm_path, _vmx):
            manager._last_guest_file_state_error = powered_off
            return None

        with patch.object(
            manager,
            "_resolve_vm_bin_cached",
            return_value=(r"C:\project\Output\firmware.bin", "firmware.bin"),
        ), patch.object(
            manager, "_get_guest_file_state", side_effect=fail_state_read
        ), patch.object(manager, "_read_guest_bin_signature") as fallback_copy:
            manager._check_bin(run_token=1)

        self.assertFalse(manager.running)
        fallback_copy.assert_not_called()

    def test_powered_off_sidecar_failure_keeps_path_for_reuse(self):
        manager, _cm = self._manager()
        vmx = r"C:\VMs\dev.vmx"
        sidecar = r"C:\Users\builder\AppData\Local\Temp\vmware1.tmp"
        manager._guest_state_sidecar_vmx = vmx
        manager._guest_state_sidecar_path = sidecar

        with patch.object(
            manager,
            "_run_vmrun",
            return_value=Completed(
                stderr="Error: The virtual machine is not powered on",
                returncode=1,
            ),
        ):
            state = manager._get_guest_file_state_via_sidecar(
                r"C:\project\Output\firmware.bin",
                vmx,
            )

        self.assertIsNone(state)
        self.assertEqual(vmx, manager._guest_state_sidecar_vmx)
        self.assertEqual(sidecar, manager._guest_state_sidecar_path)

    def test_tools_not_running_is_not_classified_as_powered_off(self):
        manager, _cm = self._manager()
        result = Completed(
            stderr="Error: The VMware Tools are not running in the virtual machine",
            returncode=1,
        )

        self.assertFalse(manager._is_vm_powered_off_result(result))

    def test_powered_off_auto_stop_waits_for_copy_worker(self):
        manager, _cm = self._manager()
        manager._running = True

        with patch.object(manager, "_join_copy_worker_for_stop") as join_worker:
            manager._stop_after_vm_powered_off(
                Completed(stderr="virtual machine is not running", returncode=1)
            )

        join_worker.assert_called_once_with()

    def test_powered_off_vm_stops_project_and_logs_once(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out
            manager._running = True
            manager._run_token = 1

            with patch.object(
                manager,
                "_resolve_vm_bin_cached",
                return_value=(r"C:\project\Output\firmware.bin", "firmware.bin"),
            ), patch.object(
                manager,
                "_get_guest_file_state",
                return_value=None,
            ), patch(
                "syncer.subprocess.run",
                return_value=Completed(
                    stderr="Error: The virtual machine is not powered on",
                    returncode=1,
                ),
            ):
                manager._check_bin(run_token=1)
                manager._check_bin(run_token=1)

        logs = [
            data.message
            for event_type, data in list(manager.event_queue.queue)
            if event_type == "log"
        ]
        stopped_events = [
            data
            for event_type, data in list(manager.event_queue.queue)
            if event_type == "info"
        ]

        self.assertFalse(manager.running)
        self.assertEqual(1, sum("虚拟机已关闭" in message for message in logs))
        self.assertFalse(any("拉取 .bin 失败" in message for message in logs))
        self.assertIn("sync_stopped", stopped_events)

    def test_guest_mtime_dead_code_is_removed(self):
        self.assertFalse(hasattr(SyncManager, "_get_guest_mtime"))

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

    def test_guest_file_state_stdout_queries_can_run_in_parallel(self):
        manager1, cm = self._manager()
        manager2 = SyncManager(cm, project_index=1)
        cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
        cm.config.vmx_path = r"C:\VMs\dev.vmx"
        cm.config.vm_guest_user = "h"
        cm.config.vm_guest_password = "password"
        digest = "a" * 64
        active = 0
        max_active = 0
        active_lock = threading.Lock()
        both_inside = threading.Event()
        results = []

        def fake_run(cmd, **_kwargs):
            nonlocal active, max_active
            with active_lock:
                active += 1
                max_active = max(max_active, active)
                if active == 2:
                    both_inside.set()
            try:
                both_inside.wait(timeout=0.3)
                return Completed(stdout=f"638838144000000000|4096|{digest}\n")
            finally:
                with active_lock:
                    active -= 1

        def read_state(manager):
            results.append(
                manager._get_guest_file_state(
                    r"C:\project\Output\firmware.bin",
                    cm.config.vmx_path,
                )
            )

        with patch("syncer.subprocess.run", side_effect=fake_run):
            t1 = threading.Thread(target=read_state, args=(manager1,))
            t2 = threading.Thread(target=read_state, args=(manager2,))
            t1.start()
            t2.start()
            t1.join(timeout=2)
            t2.join(timeout=2)

        self.assertFalse(t1.is_alive())
        self.assertFalse(t2.is_alive())
        self.assertEqual([(638838144000000000, 4096, digest)] * 2, results)
        self.assertGreaterEqual(max_active, 2)

    def test_vmrun_file_copy_operations_remain_serialized(self):
        manager1, cm = self._manager()
        manager2 = SyncManager(cm, project_index=1)
        cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
        cm.config.vm_guest_user = "h"
        cm.config.vm_guest_password = "password"
        active = 0
        max_active = 0
        active_lock = threading.Lock()

        def fake_run(cmd, **_kwargs):
            nonlocal active, max_active
            with active_lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.05)
                return Completed(returncode=0)
            finally:
                with active_lock:
                    active -= 1

        with patch("syncer.subprocess.run", side_effect=fake_run):
            t1 = threading.Thread(
                target=manager1._run_vmrun,
                args=(["CopyFileFromGuestToHost", r"C:\VMs\dev.vmx", r"C:\a.bin", r"C:\out\a.bin"], 10),
            )
            t2 = threading.Thread(
                target=manager2._run_vmrun,
                args=(["CopyFileFromGuestToHost", r"C:\VMs\dev.vmx", r"C:\b.bin", r"C:\out\b.bin"], 10),
            )
            t1.start()
            t2.start()
            t1.join(timeout=2)
            t2.join(timeout=2)

        self.assertFalse(t1.is_alive())
        self.assertFalse(t2.is_alive())
        self.assertEqual(1, max_active)

    def test_vmrun_output_prefers_utf8_for_guest_chinese_errors(self):
        manager, cm = self._manager()
        cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
        cm.config.vm_guest_user = "h"
        cm.config.vm_guest_password = "password"

        expected = "该对象不是一个目录"
        with patch(
            "syncer.subprocess.run",
            return_value=Completed(stderr=expected.encode("utf-8"), returncode=1),
        ) as run:
            result = manager._run_vmrun(["list"], timeout=5)

        self.assertEqual(expected, result.stderr)
        self.assertNotIn("text", run.call_args.kwargs)
        self.assertNotIn("encoding", run.call_args.kwargs)

    def test_vmrun_output_falls_back_to_windows_chinese_codepage(self):
        manager, cm = self._manager()
        cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
        cm.config.vm_guest_user = "h"
        cm.config.vm_guest_password = "password"

        expected = "虚拟机未运行"
        with patch(
            "syncer.subprocess.run",
            return_value=Completed(stderr=expected.encode("gb18030"), returncode=1),
        ):
            result = manager._run_vmrun(["list"], timeout=5)

        self.assertEqual(expected, result.stderr)

    def test_bin_target_read_only_guest_checks_can_run_in_parallel(self):
        manager1, cm = self._manager()
        manager2 = SyncManager(cm, project_index=1)
        cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
        cm.config.vmx_path = r"C:\VMs\dev.vmx"
        cm.config.vm_guest_user = "h"
        cm.config.vm_guest_password = "password"
        active = 0
        max_active = 0
        active_lock = threading.Lock()
        both_inside = threading.Event()

        def fake_run(cmd, **_kwargs):
            nonlocal active, max_active
            with active_lock:
                active += 1
                max_active = max(max_active, active)
                if active == 2:
                    both_inside.set()
            try:
                both_inside.wait(timeout=0.3)
                return Completed(stdout="The file exists.", returncode=0)
            finally:
                with active_lock:
                    active -= 1

        with patch("syncer.subprocess.run", side_effect=fake_run):
            t1 = threading.Thread(target=manager1._guest_file_exists, args=(r"C:\project\a.bin",))
            t2 = threading.Thread(target=manager2._guest_file_exists, args=(r"C:\project\b.bin",))
            t1.start()
            t2.start()
            t1.join(timeout=2)
            t2.join(timeout=2)

        self.assertFalse(t1.is_alive())
        self.assertFalse(t2.is_alive())
        self.assertGreaterEqual(max_active, 2)

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

    def test_check_bin_copies_existing_bin_without_guest_state(self):
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
                    patch.object(manager, "_get_guest_file_state", return_value=None):
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

    def test_recent_post_copy_same_signature_is_suppressed_when_guest_state_is_unavailable(self):
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
                    patch.object(manager, "_get_guest_file_state", return_value=None), \
                    patch("syncer.time.time", side_effect=[100.0, 104.0]):
                manager._check_bin()
                manager._check_bin()

            self.assertEqual(2, len(copies))
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
                    patch.object(manager, "_get_guest_file_state", return_value=None), \
                    patch("syncer.time.time", side_effect=[100.0, 120.0]):
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

            with patch("syncer.subprocess.run", side_effect=fake_run), \
                    patch("syncer.time.time", side_effect=[100.0, 120.0]):
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

    def test_preflight_snapshot_tolerates_missing_project_list(self):
        manager, cm = self._manager()
        cm.config.projects = []

        snapshot = manager.preflight_snapshot()

        self.assertTrue(snapshot[4])
        self.assertEqual("", snapshot[5])

    def test_start_logs_host_baseline_before_hashing_files(self):
        manager, _cm = self._manager()
        logs_seen_before_prime = []

        def fake_prime():
            while not manager.event_queue.empty():
                event_type, data = manager.event_queue.get_nowait()
                if event_type == "log":
                    logs_seen_before_prime.append(data)

        with patch.object(manager, "_can_start", return_value=True), \
                patch.object(manager, "_prime_host_file_signatures", side_effect=fake_prime), \
                patch.object(manager, "_start_copy_worker"), \
                patch.object(manager, "_start_observer"), \
                patch.object(manager, "_start_poller"):
            self.assertTrue(manager.start())

        self.assertTrue(any("文件基线" in event.message for event in logs_seen_before_prime))
        baseline_events = [
            event for event in logs_seen_before_prime
            if "文件基线" in event.message
        ]
        self.assertEqual(syncer.LogIcon.CHECK, baseline_events[0].icon)

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
            run_token = manager._run_token
            manager._on_file_changed(str(host_file))
            manager._on_file_changed(str(host_file))
            time.sleep((cm.config.debounce_ms / 1000.0) + 0.2)
            queued_tokens = []
            while not manager._copy_queue.empty():
                item = manager._copy_queue.get_nowait()
                if isinstance(item, tuple):
                    queued_tokens.append(item[0])
                    queued.append(item[1])
                else:
                    queued.append(item)
            manager.stop()

        self.assertEqual([str(host_file)], queued)
        self.assertEqual([run_token], queued_tokens)

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

    def test_suspended_worker_drains_queue_with_task_done(self):
        manager, _cm = self._manager()
        manager._running = True
        manager._incremental_sync_suspended = True
        manager._copy_queue = queue.Queue()
        manager._copy_queue.put((None, r"C:\project\main.c", None))

        manager._copy_worker_loop()

        self.assertTrue(manager._copy_queue.empty())
        self.assertEqual(0, manager._copy_queue.unfinished_tasks)

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

    def test_incremental_copy_marks_current_signature_when_file_changed_while_pending(self):
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

            original_signature = manager._host_file_signature(str(host_file))
            host_file.write_text("int main(void) { return 1; }", encoding="utf-8")
            current_signature = manager._host_file_signature(str(host_file))
            key = manager._host_signature_key(str(host_file))
            manager._queued_host_file_signatures[key] = original_signature

            def fake_run(cmd, **_kwargs):
                if "directoryExistsInGuest" in cmd:
                    return Completed(stdout="The directory exists.", returncode=0)
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run):
                manager._running = True
                manager._do_copy_to_vm(
                    str(host_file),
                    expected_signature=original_signature,
                )

        self.assertEqual(current_signature, manager._host_file_signatures[key])
        self.assertNotIn(key, manager._queued_host_file_signatures)

    def test_incremental_copy_failure_allows_same_content_to_be_requeued(self):
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
            cm.config.host_output_path = host

            with patch.object(manager, "_can_start", return_value=True), \
                    patch.object(manager, "_start_poller"), \
                    patch.object(manager, "_start_copy_worker"):
                self.assertTrue(manager.start())

            manager._copy_queue = queue.Queue()
            manager._copy_pending = set()
            host_file.write_text("int main(void) { return 1; }", encoding="utf-8")
            run_token = manager._run_token

            manager._enqueue_copy_to_vm(str(host_file), run_token)
            first_item = manager._copy_queue.get_nowait()
            with manager._copy_lock:
                manager._copy_pending.discard(str(host_file))

            def fake_run(cmd, **_kwargs):
                if "directoryExistsInGuest" in cmd:
                    return Completed(stdout="The directory exists.", returncode=0)
                if "CopyFileFromHostToGuest" in cmd:
                    return Completed(stderr="copy failed", returncode=1)
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run):
                manager._do_copy_to_vm(str(host_file), run_token=run_token)

            manager._enqueue_copy_to_vm(str(host_file), run_token)
            second_item = manager._copy_queue.get_nowait()
            manager.stop()

        self.assertEqual((run_token, str(host_file)), first_item[:2])
        self.assertEqual((run_token, str(host_file)), second_item[:2])

    def test_late_incremental_copy_from_stale_run_does_not_move_to_final_path(self):
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
            manager._running = True
            manager._run_token = 1
            commands = []

            def fake_run(cmd, **_kwargs):
                commands.append(cmd)
                if "directoryExistsInGuest" in cmd:
                    return Completed(stdout="The directory exists.", returncode=0)
                if "CopyFileFromHostToGuest" in cmd:
                    manager._running = True
                    manager._stop_requested = False
                    manager._run_token = 2
                    return Completed(returncode=0)
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run):
                manager._do_copy_to_vm(str(host_file), run_token=1)

        command_text = "\n".join(" ".join(cmd) for cmd in commands)
        self.assertIn("CopyFileFromHostToGuest", command_text)
        self.assertNotIn("Move-Item", command_text)
        self.assertEqual(0, manager.synced_count)

    def test_startup_window_changes_are_enqueued_after_observer_starts(self):
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

            real_prime = manager._prime_host_file_signatures

            def prime_then_modify():
                real_prime()
                host_file.write_text("int main(void) { return 1; }", encoding="utf-8")

            def fake_start_copy_worker(_run_token=None):
                manager._copy_queue = queue.Queue()
                manager._copy_pending = set()

            with patch.object(manager, "_can_start", return_value=True), \
                    patch.object(manager, "_prime_host_file_signatures", side_effect=prime_then_modify), \
                    patch.object(manager, "_start_copy_worker", side_effect=fake_start_copy_worker), \
                    patch.object(manager, "_start_observer"), \
                    patch.object(manager, "_start_poller"), \
                    patch("syncer.time.time_ns", return_value=0):
                self.assertTrue(manager.start())
            started_run_token = manager._run_token

            queued = []
            while not manager._copy_queue.empty():
                queued.append(manager._copy_queue.get_nowait())
            manager.stop()

        self.assertEqual([(started_run_token, str(host_file))], [(item[0], item[1]) for item in queued])

    def test_start_reports_service_started_before_startup_window_requeue(self):
        manager, _cm = self._manager()
        logs_seen_during_requeue = []

        def capture_logs(_run_token=None):
            while not manager.event_queue.empty():
                event_type, data = manager.event_queue.get_nowait()
                if event_type == "log":
                    logs_seen_during_requeue.append(data.message)

        with patch.object(manager, "_can_start", return_value=True), \
                patch.object(manager, "_prime_host_file_signatures"), \
                patch.object(manager, "_start_copy_worker"), \
                patch.object(manager, "_start_observer"), \
                patch.object(manager, "_start_poller"), \
                patch.object(manager, "_enqueue_startup_window_changes", side_effect=capture_logs):
            self.assertTrue(manager.start())

        self.assertTrue(any("同步服务已启动" in message for message in logs_seen_during_requeue))

    def test_late_bin_copy_from_stale_run_does_not_overwrite_host_output(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as out:
            host_out = Path(out) / "firmware.bin"
            host_out.write_bytes(b"old-firmware")
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out
            manager._running = True
            manager._run_token = 1

            def fake_run(cmd, **_kwargs):
                if "CopyFileFromGuestToHost" in cmd:
                    Path(cmd[-1]).write_bytes(b"new-firmware")
                    manager._running = True
                    manager._stop_requested = False
                    manager._run_token = 2
                return Completed(returncode=0)

            with patch.object(
                manager,
                "_resolve_vm_bin_cached",
                return_value=(r"C:\project\Output\firmware.bin", "firmware.bin"),
            ), patch.object(
                manager,
                "_get_guest_file_state",
                return_value=None,
            ), patch("syncer.subprocess.run", side_effect=fake_run):
                manager._check_bin(run_token=1)

            self.assertEqual(b"old-firmware", host_out.read_bytes())
            self.assertFalse(manager.bin_ready)
            self.assertTrue(manager.event_queue.empty())

    def test_late_unchanged_bin_state_from_stale_run_does_not_notify(self):
        manager, cm = self._manager()
        digest = "a" * 64
        with tempfile.TemporaryDirectory() as out:
            host_out = Path(out) / "firmware.bin"
            host_out.write_bytes(b"firmware")
            vm_bin = r"C:\project\Output\firmware.bin"
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.vm_project_path = r"C:\project"
            cm.config.vm_bin_relative_path = r"Output\firmware.bin"
            cm.config.host_output_path = out
            manager._running = True
            manager._run_token = 1
            manager._last_bin_state = (vm_bin.lower(), 100, 8, digest)

            def mark_stale(_state_key, _host_out):
                manager._run_token = 2
                return True

            with patch.object(
                manager,
                "_resolve_vm_bin_cached",
                return_value=(vm_bin, "firmware.bin"),
            ), patch.object(
                manager,
                "_get_guest_file_state",
                return_value=(101, 8, digest),
            ), patch.object(
                manager,
                "_guest_bin_content_is_unchanged",
                side_effect=mark_stale,
            ):
                manager._check_bin(run_token=1)

            self.assertEqual(b"firmware", host_out.read_bytes())
            self.assertFalse(manager.bin_ready)
            self.assertTrue(manager.event_queue.empty())

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
        self.assertIn(guest_temp + "_p1.zip", command_text)
        self.assertIn("Remove-Item", command_text)
        self.assertIn(guest_temp + "_p1_extract", command_text)
        self.assertNotIn("Expand-Archive", command_text)

    def test_parallel_full_sync_waits_for_other_project_vm_phase(self):
        manager1, cm = self._manager()
        manager2 = SyncManager(cm, project_index=1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host1 = root / "p1"
            host2 = root / "p2"
            host1.mkdir()
            host2.mkdir()
            (host1 / "main.c").write_text("int p1(void) { return 1; }", encoding="utf-8")
            (host2 / "main.c").write_text("int p2(void) { return 2; }", encoding="utf-8")
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.projects[0].enabled = True
            cm.config.projects[0].host_project_path = str(host1)
            cm.config.projects[0].vm_project_path = r"C:\project1"
            cm.config.projects[0].host_output_path = str(root / "out1")
            cm.config.projects[1].enabled = True
            cm.config.projects[1].host_project_path = str(host2)
            cm.config.projects[1].vm_project_path = r"C:\project2"
            cm.config.projects[1].host_output_path = str(root / "out2")

            vm_commands = []
            p1_in_vm_phase = threading.Event()
            p1_continue = threading.Event()

            def fake_run(cmd, **_kwargs):
                vm_commands.append(cmd)
                if "CreateTempfileInGuest" in cmd:
                    return Completed(stdout=rf"C:\Users\h\AppData\Local\Temp\vm_sync_{len(vm_commands)}.tmp", returncode=0)
                if "directoryExistsInGuest" in cmd:
                    return Completed(stdout="The directory exists.", returncode=0)
                return Completed(returncode=0)

            def p1_ensure_guest_directory(vm_path, *_args):
                p1_in_vm_phase.set()
                self.assertTrue(p1_continue.wait(timeout=5))
                return Completed(stdout="The directory exists.", returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run), \
                    patch.object(manager1, "_ensure_guest_directory", side_effect=p1_ensure_guest_directory):
                t1 = threading.Thread(target=manager1.full_sync)
                t1.start()
                self.assertTrue(p1_in_vm_phase.wait(timeout=5))

                t2 = threading.Thread(target=manager2.full_sync)
                t2.start()
                time.sleep(0.2)

                try:
                    self.assertEqual([], vm_commands)
                    waiting_logs = []
                    while not manager2.event_queue.empty():
                        event_type, data = manager2.event_queue.get_nowait()
                        if event_type == "log":
                            waiting_logs.append(data.message)
                    self.assertTrue(
                        any("另一个项目正在执行虚拟机全量同步" in message for message in waiting_logs)
                    )
                finally:
                    p1_continue.set()
                    t1.join(timeout=5)
                    t2.join(timeout=5)

            self.assertFalse(t1.is_alive())
            self.assertFalse(t2.is_alive())
            resumed_logs = []
            while not manager2.event_queue.empty():
                event_type, data = manager2.event_queue.get_nowait()
                if event_type == "log":
                    resumed_logs.append(data.message)
            self.assertTrue(
                any("继续执行本项目全量同步" in message for message in resumed_logs)
            )

    def test_full_sync_waiting_for_vm_phase_can_be_cancelled(self):
        manager1, cm = self._manager()
        manager2 = SyncManager(cm, project_index=1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host1 = root / "p1"
            host2 = root / "p2"
            host1.mkdir()
            host2.mkdir()
            (host1 / "main.c").write_text("int p1(void) { return 1; }", encoding="utf-8")
            (host2 / "main.c").write_text("int p2(void) { return 2; }", encoding="utf-8")
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.projects[0].enabled = True
            cm.config.projects[0].host_project_path = str(host1)
            cm.config.projects[0].vm_project_path = r"C:\project1"
            cm.config.projects[0].host_output_path = str(root / "out1")
            cm.config.projects[1].enabled = True
            cm.config.projects[1].host_project_path = str(host2)
            cm.config.projects[1].vm_project_path = r"C:\project2"
            cm.config.projects[1].host_output_path = str(root / "out2")

            p1_in_vm_phase = threading.Event()
            p1_continue = threading.Event()

            def fake_run(cmd, **_kwargs):
                if "CreateTempfileInGuest" in cmd:
                    return Completed(stdout=r"C:\Users\h\AppData\Local\Temp\vm_sync.tmp", returncode=0)
                if "directoryExistsInGuest" in cmd:
                    return Completed(stdout="The directory exists.", returncode=0)
                return Completed(returncode=0)

            def p1_ensure_guest_directory(vm_path, *_args):
                p1_in_vm_phase.set()
                self.assertTrue(p1_continue.wait(timeout=5))
                return Completed(stdout="The directory exists.", returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run), \
                    patch.object(manager1, "_ensure_guest_directory", side_effect=p1_ensure_guest_directory):
                t1 = threading.Thread(target=manager1.full_sync)
                t1.start()
                self.assertTrue(p1_in_vm_phase.wait(timeout=5))

                t2 = threading.Thread(target=manager2.full_sync)
                t2.start()
                try:
                    deadline = time.time() + 5
                    saw_wait_log = False
                    while time.time() < deadline:
                        queued = list(manager2.event_queue.queue)
                        saw_wait_log = any(
                            event_type == "log"
                            and "另一个项目正在执行虚拟机全量同步" in data.message
                            for event_type, data in queued
                        )
                        if saw_wait_log:
                            break
                        time.sleep(0.05)
                    self.assertTrue(saw_wait_log)

                    manager2.request_full_sync_cancel()
                    t2.join(timeout=2)
                    self.assertFalse(t2.is_alive())
                finally:
                    p1_continue.set()
                    t1.join(timeout=5)

            self.assertFalse(t1.is_alive())

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
                                "Tool/",
                                "Tool/precompile/",
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

    def test_full_sync_zip_preserves_empty_directories(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as host:
            host_root = Path(host)
            (host_root / "main.c").write_text("int main(void) { return 0; }", encoding="utf-8")
            (host_root / "Generated" / "empty").mkdir(parents=True)
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.host_project_path = host
            cm.config.vm_project_path = r"C:\project"
            cm.config.host_output_path = host

            def fake_run(cmd, **_kwargs):
                if "CopyFileFromHostToGuest" in cmd:
                    zip_path = Path(cmd[cmd.index("CopyFileFromHostToGuest") + 2])
                    with zipfile.ZipFile(zip_path) as archive:
                        self.assertIn("Generated/empty/", archive.namelist())
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run):
                count = manager.full_sync()

        self.assertEqual(1, count)

    def test_full_sync_skips_output_directory_contents(self):
        manager, cm = self._manager()
        with tempfile.TemporaryDirectory() as host:
            host_root = Path(host)
            (host_root / "main.c").write_text("int main(void) { return 0; }", encoding="utf-8")
            (host_root / "Output" / "RL6492").mkdir(parents=True)
            (host_root / "Output" / "RL6492" / "RL6492_Project.bin").write_bytes(b"firmware")
            (host_root / "Output" / "build.log").write_text("build output", encoding="utf-8")
            cm.config.vmrun_path = r"C:\VMware\vmrun.exe"
            cm.config.vmx_path = r"C:\VMs\dev.vmx"
            cm.config.vm_guest_user = "h"
            cm.config.vm_guest_password = "password"
            cm.config.host_project_path = host
            cm.config.vm_project_path = r"C:\project"
            cm.config.host_output_path = host

            def fake_run(cmd, **_kwargs):
                if "CopyFileFromHostToGuest" in cmd:
                    zip_path = Path(cmd[cmd.index("CopyFileFromHostToGuest") + 2])
                    with zipfile.ZipFile(zip_path) as archive:
                        names = archive.namelist()
                        self.assertIn("main.c", names)
                        self.assertFalse(any(name.lower().startswith("output/") for name in names))
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run):
                count = manager.full_sync()

        self.assertEqual(1, count)

    def test_full_sync_cover_copies_stage_children_without_literal_wildcard(self):
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
                return Completed(returncode=0)

            with patch("syncer.subprocess.run", side_effect=fake_run):
                manager.full_sync()

        cover_commands = [
            " ".join(cmd) for cmd in commands
            if "Copy-Item" in " ".join(cmd)
        ]
        self.assertTrue(cover_commands)
        self.assertTrue(any("Get-ChildItem -LiteralPath" in cmd for cmd in cover_commands))
        self.assertFalse(any("\\*'" in cmd or "\\* " in cmd for cmd in cover_commands))

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
