import inspect
import queue
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from preflight import PreflightReport
from syncer import LogEvent
from ui import App, ConfigPanel, ControlPanel


class FakeProjectPanel:
    def __init__(self, report=None):
        self.report = report or PreflightReport()
        self.log_panel = SimpleNamespace(events=[], append=self._append, update_progress=self._update_progress)
        self.stats_updates = []
        self.visible = False
        self.show_calls = 0
        self.hide_calls = 0
        self.config_enabled = []

    def _append(self, event):
        self.log_panel.events.append(event)

    def _update_progress(self, data):
        self.log_panel.events.append(("progress", data))

    def save_and_check(self):
        return self.report

    def set_config_enabled(self, enabled):
        self.config_enabled.append(enabled)

    def update_stats(self, sync_count, bin_ready):
        self.stats_updates.append((sync_count, bin_ready))

    def show(self):
        self.visible = True
        self.show_calls += 1

    def hide(self):
        self.visible = False
        self.hide_calls += 1


class FakeSync:
    def __init__(self, project_index=0, *, running=False, synced_count=0, bin_ready=False):
        self.project_index = project_index
        self.event_queue = queue.Queue()
        self.running = running
        self.synced_count = synced_count
        self.bin_ready = bin_ready
        self.start_calls = []
        self.stop_calls = 0

    def preflight_snapshot(self):
        return ("snapshot", self.project_index)

    def start(self, **kwargs):
        self.start_calls.append(kwargs)
        self.running = True
        return True

    def stop(self):
        self.stop_calls += 1
        self.running = False


class MultiProjectUiTests(unittest.TestCase):
    def test_app_constructor_accepts_multiple_sync_managers(self):
        source = inspect.getsource(App.__init__)

        self.assertIn("sync_managers", source)
        self.assertIn("self.sync_managers", source)

    def test_app_builds_shared_vm_panel_and_project_panel_collection(self):
        source = inspect.getsource(App._build_ui)

        self.assertIn("shared_vm_panel", source)
        self.assertIn("project_panels", source)
        self.assertIn("add_project", source)

    def test_config_panel_targets_project_indexed_config(self):
        source = inspect.getsource(ConfigPanel)

        self.assertIn("project_index", source)
        self.assertIn("_project_config", source)

    def test_set_project_enabled_updates_config_and_visibility(self):
        app = object.__new__(App)
        app.cm = SimpleNamespace(
            config=SimpleNamespace(
                projects=[
                    SimpleNamespace(enabled=True),
                    SimpleNamespace(enabled=False),
                ]
            ),
            save=lambda: None,
        )
        app.project_panels = {
            0: FakeProjectPanel(),
            1: FakeProjectPanel(),
        }
        app.sync_managers = [FakeSync(0), FakeSync(1)]

        App._set_project_enabled(app, 1, True)
        self.assertTrue(app.cm.config.projects[1].enabled)
        self.assertEqual(1, app.project_panels[1].show_calls)

        App._set_project_enabled(app, 1, False)
        self.assertFalse(app.cm.config.projects[1].enabled)
        self.assertEqual(1, app.project_panels[1].hide_calls)

    def test_poll_events_routes_each_manager_to_its_project_log_panel(self):
        app = object.__new__(App)
        app._shutting_down = False
        app._maybe_check_appearance_change = lambda: None
        app._schedule_after = lambda *_args, **_kwargs: None
        app._on_bin_ready = lambda _filename: None
        app._on_bin_unchanged = lambda _filename: None
        app.sync_managers = [
            FakeSync(0, synced_count=3, bin_ready=True),
            FakeSync(1, synced_count=7, bin_ready=False),
        ]
        app.project_panels = {
            0: FakeProjectPanel(),
            1: FakeProjectPanel(),
        }
        app.control = SimpleNamespace(update_stats=lambda *_args: None)

        app.sync_managers[0].event_queue.put(("log", LogEvent("i", "project-1", "info")))
        app.sync_managers[1].event_queue.put(("log", LogEvent("i", "project-2", "info")))

        App._poll_events(app)

        self.assertEqual("project-1", app.project_panels[0].log_panel.events[0].message)
        self.assertEqual("project-2", app.project_panels[1].log_panel.events[0].message)
        self.assertIn((3, True), app.project_panels[0].stats_updates)
        self.assertIn((7, False), app.project_panels[1].stats_updates)

    def test_start_all_is_atomic_across_enabled_projects(self):
        calls = []

        class FakeThread:
            def __init__(self, target, daemon=False):
                self.target = target
                self.daemon = daemon
                calls.append("thread_created")

            def start(self):
                calls.append("thread_started")

        control = object.__new__(ControlPanel)
        control.app = SimpleNamespace(
            project_panels={
                0: FakeProjectPanel(report=PreflightReport()),
                1: FakeProjectPanel(report=PreflightReport(errors=["bad project 2"])),
            },
            get_enabled_project_indexes=lambda: [0, 1],
        )
        control.start_btn = SimpleNamespace(configure=lambda **_kwargs: calls.append("start_btn"))

        with patch("ui.threading.Thread", FakeThread):
            ControlPanel._start(control)

        self.assertNotIn("thread_created", calls)


if __name__ == "__main__":
    unittest.main()
