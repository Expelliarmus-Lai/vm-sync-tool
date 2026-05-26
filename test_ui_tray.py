import unittest
from types import SimpleNamespace

from ui import App, tray_status_label, tray_sync_label


class TrayMenuTests(unittest.TestCase):
    def test_tray_sync_label_reflects_running_state(self):
        self.assertEqual("⏸  暂停同步 (运行中)", tray_sync_label(True))
        self.assertEqual("▶  启动同步 (已停止)", tray_sync_label(False))

    def test_tray_status_label_reflects_running_state(self):
        self.assertEqual("状态：运行中", tray_status_label(True))
        self.assertEqual("状态：已停止", tray_status_label(False))


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


if __name__ == "__main__":
    unittest.main()
