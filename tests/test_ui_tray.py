import inspect
import unittest
from types import SimpleNamespace

from ui import App, app_icon_path, create_app_icon, create_tray_icon, tray_status_label, tray_sync_label


class TrayMenuTests(unittest.TestCase):
    def test_tray_icon_uses_same_image_as_window_icon(self):
        app_icon = create_app_icon()
        tray_icon = create_tray_icon()

        self.assertEqual(app_icon.size, tray_icon.size)
        self.assertEqual(
            app_icon.tobytes(),
            tray_icon.tobytes(),
        )

    def test_app_applies_window_icon_from_shared_app_icon(self):
        names = App._apply_window_icon.__code__.co_names

        self.assertIn("app_icon_path", names)
        self.assertIn("iconbitmap", names)

    def test_app_sets_windows_app_user_model_id_before_creating_window(self):
        source = inspect.getsource(App.__init__)

        self.assertIn("set_windows_app_user_model_id()", source)
        self.assertLess(
            source.index("set_windows_app_user_model_id()"),
            source.index("ctk.CTk()"),
        )

    def test_app_icon_path_uses_customtkinter_window_icon_asset(self):
        self.assertTrue(app_icon_path().endswith("CustomTkinter_icon_Windows.ico"))

    def test_tray_sync_label_reflects_running_state(self):
        self.assertEqual("⏸  暂停同步 (运行中)", tray_sync_label(True))
        self.assertEqual("▶  启动同步 (已停止)", tray_sync_label(False))
        self.assertEqual("⏸  Pause sync (running)", tray_sync_label(True, "en"))
        self.assertEqual("▶  Start sync (stopped)", tray_sync_label(False, "en"))

    def test_tray_status_label_reflects_running_state(self):
        self.assertEqual("状态：运行中", tray_status_label(True))
        self.assertEqual("状态：已停止", tray_status_label(False))
        self.assertEqual("Status: Running", tray_status_label(True, "en"))
        self.assertEqual("Status: Stopped", tray_status_label(False, "en"))


    def test_tray_quit_runs_complete_shutdown(self):
        calls = []

        class FakeWindow:
            def after(self, _delay, callback):
                callback()

            def quit(self):
                calls.append("quit")

            def destroy(self):
                calls.append("destroy")

        class FakeSync:
            def stop(self):
                calls.append("sync.stop")

        class FakeSocket:
            def close(self):
                calls.append("socket.close")

        class FakeTrayIcon:
            def stop(self):
                calls.append("tray.stop")

        app = SimpleNamespace(
            window=FakeWindow(),
            sync=FakeSync(),
            _single_instance_sock=FakeSocket(),
            _tray_icon=FakeTrayIcon(),
            _shutting_down=False,
            _after_jobs=set(),
        )
        app._shutdown = lambda: App._shutdown(app)
        app._cancel_after_jobs = lambda: App._cancel_after_jobs(app)

        App._tray_quit(app)

        self.assertEqual(
            ["sync.stop", "socket.close", "tray.stop", "quit", "destroy"],
            calls,
        )
        self.assertIsNone(app._single_instance_sock)
        self.assertIsNone(app._tray_icon)
        self.assertTrue(app._shutting_down)

    def test_shutdown_waits_briefly_for_full_sync_cleanup(self):
        calls = []

        class FakeWindow:
            def quit(self):
                calls.append("quit")

            def destroy(self):
                calls.append("destroy")

        class FakeSync:
            full_sync_active = True

            def request_full_sync_cancel(self):
                calls.append("full_sync.cancel")

            def stop(self):
                calls.append("sync.stop")

        class FakeThread:
            def is_alive(self):
                return True

            def join(self, timeout=None):
                calls.append(("join", timeout))

        app = SimpleNamespace(
            window=FakeWindow(),
            sync=FakeSync(),
            config_panel=SimpleNamespace(_full_sync_thread=FakeThread()),
            _single_instance_sock=None,
            _tray_icon=None,
            _shutting_down=False,
            _after_jobs=set(),
        )
        app._cancel_after_jobs = lambda: App._cancel_after_jobs(app)

        App._shutdown(app)

        self.assertEqual(
            ["full_sync.cancel", "sync.stop", ("join", 2.0), "quit", "destroy"],
            calls,
        )

    def test_unchanged_bin_event_shows_tray_notification(self):
        notifications = []

        class FakeTrayIcon:
            def notify(self, message, title):
                notifications.append((message, title))

        app = SimpleNamespace(_tray_icon=FakeTrayIcon(), cm=SimpleNamespace(config=SimpleNamespace(language="en")))

        App._on_bin_unchanged(app, "firmware.bin")

        self.assertEqual(
            [("Firmware content unchanged, skipped overwrite: firmware.bin", "VM Sync")],
            notifications,
        )


if __name__ == "__main__":
    unittest.main()
