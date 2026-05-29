import inspect
import queue
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import ui
from preflight import PreflightReport
from syncer import LogEvent, LogIcon
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
        self.grid_configure_calls = []
        self.running_ui = []

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

    def grid_configure(self, **kwargs):
        self.grid_configure_calls.append(kwargs)
        self.visible = True

    def _set_project_running_ui(self, running):
        self.running_ui.append(running)


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


class FakeWindow:
    def __init__(self):
        self.geometry_calls = []
        self.minsize_calls = []

    def geometry(self, value):
        self.geometry_calls.append(value)

    def minsize(self, width, height):
        self.minsize_calls.append((width, height))


class FakeButton:
    def __init__(self):
        self.configures = []

    def configure(self, **kwargs):
        self.configures.append(kwargs)


class FakeLabel:
    def __init__(self):
        self.configures = []

    def configure(self, **kwargs):
        self.configures.append(kwargs)


class ImmediateThread:
    def __init__(self, target, daemon=False):
        self.target = target
        self.daemon = daemon

    def start(self):
        self.target()


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

    def test_project_pane_has_independent_start_pause_controls(self):
        source = inspect.getsource(ui.ProjectPane)

        self.assertIn("start_btn", source)
        self.assertIn("pause_btn", source)
        self.assertIn("_start_project", source)
        self.assertIn("_pause_project", source)

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
        self.assertFalse(app.project_panels[1].visible)

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

    def test_start_all_logs_to_passed_project_when_another_project_fails_preflight(self):
        control = object.__new__(ControlPanel)
        project_1 = FakeProjectPanel(report=PreflightReport())
        project_2 = FakeProjectPanel(report=PreflightReport(errors=["bad project 2"]))
        control.app = SimpleNamespace(
            project_panels={0: project_1, 1: project_2},
            get_enabled_project_indexes=lambda: [0, 1],
            cm=SimpleNamespace(config=SimpleNamespace(language="zh")),
        )
        control.start_btn = FakeButton()

        ControlPanel._start(control)

        self.assertEqual([], project_2.log_panel.events)
        self.assertEqual(1, len(project_1.log_panel.events))
        event = project_1.log_panel.events[0]
        self.assertEqual(LogIcon.WARNING, event.icon)
        self.assertIn("项目 2", event.message)
        self.assertIn("未启动", event.message)
        self.assertIn("配置", event.message)

    def test_top_start_and_pause_all_updates_project_controls(self):
        control = object.__new__(ControlPanel)
        control.app = SimpleNamespace(
            project_panels={
                0: FakeProjectPanel(),
                1: FakeProjectPanel(),
            },
            get_enabled_project_indexes=lambda: [0, 1],
            set_all_config_enabled=lambda _enabled: None,
            _update_status_indicator=lambda _running: None,
            _update_tray_menu=lambda: None,
            sync=SimpleNamespace(running=False),
        )
        control.start_btn = FakeButton()
        control.pause_btn = FakeButton()
        control.uptime_label = FakeButton()
        control._start_time = None
        control._tr = lambda key, **_kwargs: key

        ControlPanel._set_running(control)
        self.assertEqual([True], control.app.project_panels[0].running_ui)
        self.assertEqual([True], control.app.project_panels[1].running_ui)

        ControlPanel._set_stopped(control)
        self.assertEqual([True, False], control.app.project_panels[0].running_ui)
        self.assertEqual([True, False], control.app.project_panels[1].running_ui)

    def test_project_pane_start_runs_only_its_project_manager(self):
        config_enabled = []
        syncs = [FakeSync(0), FakeSync(1)]
        pane = object.__new__(ui.ProjectPane)
        pane.project_index = 1
        pane.app = SimpleNamespace(
            get_sync_manager=lambda index: syncs[index],
            set_all_config_enabled=lambda enabled: config_enabled.append(enabled),
            any_running=lambda: any(sync.running for sync in syncs),
            control=None,
            _update_status_indicator=lambda _running: None,
            _update_tray_menu=lambda: None,
        )
        pane.config_panel = SimpleNamespace(
            save_and_check=lambda: PreflightReport(),
            set_config_enabled=lambda _enabled: None,
        )
        pane.log_panel = SimpleNamespace(append=lambda _event: None)
        pane.start_btn = FakeButton()
        pane.pause_btn = FakeButton()
        pane.toggle_btn = FakeButton()
        pane.after = lambda _delay, callback: callback()

        with patch("ui.threading.Thread", ImmediateThread):
            ui.ProjectPane._start_project(pane)

        self.assertEqual([], syncs[0].start_calls)
        self.assertEqual(1, len(syncs[1].start_calls))
        self.assertTrue(syncs[1].start_calls[0]["preflight_checked"])
        self.assertEqual([False, False], config_enabled)

    def test_project_pane_pause_stops_only_its_project_manager(self):
        syncs = [FakeSync(0, running=True), FakeSync(1, running=True)]
        pane = object.__new__(ui.ProjectPane)
        pane.project_index = 1
        pane.app = SimpleNamespace(
            get_sync_manager=lambda index: syncs[index],
            set_all_config_enabled=lambda _enabled: None,
            any_running=lambda: any(sync.running for sync in syncs),
            control=None,
            _update_status_indicator=lambda _running: None,
            _update_tray_menu=lambda: None,
        )
        pane.config_panel = SimpleNamespace(set_config_enabled=lambda _enabled: None)
        pane.log_panel = SimpleNamespace(append=lambda _event: None)
        pane.start_btn = FakeButton()
        pane.pause_btn = FakeButton()
        pane.toggle_btn = FakeButton()

        ui.ProjectPane._pause_project(pane)

        self.assertEqual(0, syncs[0].stop_calls)
        self.assertEqual(1, syncs[1].stop_calls)
        self.assertTrue(syncs[0].running)
        self.assertFalse(syncs[1].running)

    def test_project_columns_use_uniform_grid_with_minimum_width(self):
        source = inspect.getsource(App._build_ui)

        self.assertIn('uniform="project_columns"', source)
        self.assertIn("PROJECT_COLUMN_MIN_WIDTH", source)
        self.assertIn('sticky="nsew"', source)

    def test_shared_vm_config_stretches_to_match_project_area(self):
        source = inspect.getsource(App._build_ui)

        self.assertIn("shared_vm_shell", source)
        self.assertIn('sticky="ew"', source)
        self.assertIn("CONTENT_SIDE_PADDING", source)
        self.assertNotIn("self.shared_vm_panel.pack(fill=\"x\"", source)
        self.assertNotIn("SHARED_VM_PANEL_WIDTH", source)
        self.assertNotIn("self.shared_vm_panel.configure(width=", source)

    def test_window_uses_single_project_size_until_project_2_is_enabled(self):
        app = object.__new__(App)
        app.window = FakeWindow()
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
        app.add_project_btn = SimpleNamespace(
            pack_forget=lambda: None,
            pack=lambda **_kwargs: None,
        )

        App._set_project_enabled(app, 1, True, save=False)
        self.assertEqual(ui.DUAL_PROJECT_GEOMETRY, app.window.geometry_calls[-1])
        self.assertEqual(ui.DUAL_PROJECT_MIN_SIZE, app.window.minsize_calls[-1])

        App._set_project_enabled(app, 1, False, save=False)
        self.assertEqual(ui.SINGLE_PROJECT_GEOMETRY, app.window.geometry_calls[-1])
        self.assertEqual(ui.SINGLE_PROJECT_MIN_SIZE, app.window.minsize_calls[-1])

    def test_status_indicator_reports_partial_running_for_one_of_two_projects(self):
        app = object.__new__(App)
        app.cm = SimpleNamespace(
            config=SimpleNamespace(
                language="zh",
                projects=[
                    SimpleNamespace(enabled=True),
                    SimpleNamespace(enabled=True),
                ],
            )
        )
        app.sync_managers = [
            FakeSync(0, running=True),
            FakeSync(1, running=False),
        ]
        app.status_dot = FakeLabel()
        app.status_text = FakeLabel()
        app._status_indicator_state = "ready"

        App._update_status_indicator(app, True)

        self.assertEqual("部分运行", app.status_text.configures[-1]["text"])


if __name__ == "__main__":
    unittest.main()
