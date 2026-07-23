import inspect
import queue
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import ui
from i18n import Translator
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
    def __init__(
        self,
        project_index=0,
        *,
        running=False,
        synced_count=0,
        bin_ready=False,
        has_error=False,
        full_sync_active=False,
    ):
        self.project_index = project_index
        self.event_queue = queue.Queue()
        self.running = running
        self.synced_count = synced_count
        self.bin_ready = bin_ready
        self.has_error = has_error
        self.full_sync_active = full_sync_active
        self.start_calls = []
        self.stop_calls = 0
        self.cancel_full_sync_calls = 0

    def preflight_snapshot(self):
        return ("snapshot", self.project_index)

    def start(self, **kwargs):
        self.start_calls.append(kwargs)
        self.running = True
        return True

    def stop(self):
        self.stop_calls += 1
        self.running = False

    def request_full_sync_cancel(self):
        self.cancel_full_sync_calls += 1


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
        self.pack_calls = []
        self.pack_forget_calls = 0

    def configure(self, **kwargs):
        self.configures.append(kwargs)

    def pack(self, **kwargs):
        self.pack_calls.append(kwargs)

    def pack_forget(self):
        self.pack_forget_calls += 1


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

    def test_app_build_ui_does_not_create_hidden_legacy_panels(self):
        source = inspect.getsource(App._build_ui)

        self.assertNotIn("self.config_panel = ConfigPanel(self.scroll_area.inner, self)", source)
        self.assertNotIn("self.log_panel = LogPanel(self.scroll_area.inner, self)", source)
        self.assertNotIn("self.config_panel.pack_forget()", source)
        self.assertNotIn("self.log_panel.pack_forget()", source)

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
        self.assertIn("PROJECT_RUN_BUTTON_WIDTH", source)
        self.assertIn("PROJECT_RUN_BUTTON_HEIGHT", source)
        self.assertEqual(84, ui.PROJECT_RUN_BUTTON_WIDTH)
        self.assertEqual(30, ui.PROJECT_RUN_BUTTON_HEIGHT)

    def test_project_header_actions_align_with_config_card_edge(self):
        source = inspect.getsource(ui.ProjectPane.__init__)

        self.assertIn('header.pack(fill="x", padx=0', source)
        self.assertNotIn('header.pack(fill="x", padx=4', source)
        self.assertIn('self.pause_btn.pack(side="right")', source)
        self.assertNotIn('self.pause_btn.pack(side="right", padx=(0, 6))', source)

    def test_add_project_button_uses_requested_word_order(self):
        self.assertEqual("添加同步项目", Translator("zh").tr("ui.button.add_project"))

    def test_project_disable_button_is_in_action_row_not_project_header(self):
        build_source = inspect.getsource(App._build_ui)
        pane_source = inspect.getsource(ui.ProjectPane.__init__)

        self.assertIn("remove_project_btn", build_source)
        self.assertIn("self._set_project_enabled(1, False)", build_source)
        self.assertNotIn("ui.button.remove_project", pane_source)

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
        app._latest_bin_return_times = {1: 1753243200.0}

        App._set_project_enabled(app, 1, True)
        self.assertTrue(app.cm.config.projects[1].enabled)
        self.assertEqual(1, app.project_panels[1].show_calls)

        App._set_project_enabled(app, 1, False)
        self.assertFalse(app.cm.config.projects[1].enabled)
        self.assertEqual(1, app.project_panels[1].hide_calls)
        self.assertFalse(app.project_panels[1].visible)
        self.assertNotIn(1, app._latest_bin_return_times)

    def test_project_2_action_row_swaps_add_and_disable_buttons(self):
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
        app.add_project_btn = FakeButton()
        app.remove_project_btn = FakeButton()
        app.window = FakeWindow()

        App._set_project_enabled(app, 1, True, save=False)
        self.assertEqual(1, app.add_project_btn.pack_forget_calls)
        self.assertEqual([{"side": "right"}], app.remove_project_btn.pack_calls)

        App._set_project_enabled(app, 1, False, save=False)
        self.assertEqual(2, app.remove_project_btn.pack_forget_calls)
        self.assertEqual([{"side": "right"}], app.add_project_btn.pack_calls)

    def test_disabling_project_cancels_project_full_sync_before_hiding(self):
        app = object.__new__(App)
        app.cm = SimpleNamespace(
            config=SimpleNamespace(
                projects=[
                    SimpleNamespace(enabled=True),
                    SimpleNamespace(enabled=True),
                ]
            ),
            save=lambda: None,
        )
        app.project_panels = {
            0: FakeProjectPanel(),
            1: FakeProjectPanel(),
        }
        app.sync_managers = [FakeSync(0), FakeSync(1, full_sync_active=True)]
        app.add_project_btn = SimpleNamespace(
            pack_forget=lambda: None,
            pack=lambda **_kwargs: None,
        )
        app.window = FakeWindow()

        App._set_project_enabled(app, 1, False, save=False)

        self.assertEqual(1, app.sync_managers[1].cancel_full_sync_calls)
        self.assertEqual(1, app.project_panels[1].hide_calls)

    def test_poll_events_routes_each_manager_to_its_project_log_panel(self):
        app = object.__new__(App)
        app._shutting_down = False
        app._maybe_check_appearance_change = lambda: None
        app._schedule_after = lambda *_args, **_kwargs: None
        bin_ready_events = []
        bin_unchanged_events = []
        app._on_bin_ready = lambda filename, project_index=0: bin_ready_events.append((project_index, filename))
        app._on_bin_unchanged = lambda filename, project_index=0: bin_unchanged_events.append((project_index, filename))
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
        app.sync_managers[0].event_queue.put(("bin_ready", "same-name.bin"))
        app.sync_managers[1].event_queue.put(("bin_unchanged", "same-name.bin"))

        App._poll_events(app)

        self.assertEqual("project-1", app.project_panels[0].log_panel.events[0].message)
        self.assertEqual("project-2", app.project_panels[1].log_panel.events[0].message)
        self.assertEqual([(0, "same-name.bin")], bin_ready_events)
        self.assertEqual([(1, "same-name.bin")], bin_unchanged_events)
        self.assertIn((3, True), app.project_panels[0].stats_updates)
        self.assertIn((7, False), app.project_panels[1].stats_updates)

    def test_poll_events_refreshes_project_controls_after_auto_stop(self):
        app = object.__new__(App)
        app._shutting_down = False
        app._maybe_check_appearance_change = lambda: None
        app._schedule_after = lambda *_args, **_kwargs: None
        app._on_bin_ready = lambda *_args, **_kwargs: None
        app._on_bin_unchanged = lambda *_args, **_kwargs: None
        app.sync_managers = [
            FakeSync(0, running=False, synced_count=3, bin_ready=False),
            FakeSync(1, running=True, synced_count=7, bin_ready=True),
        ]
        app.project_panels = {
            0: FakeProjectPanel(),
            1: FakeProjectPanel(),
        }
        status_updates = []
        tray_updates = []
        app.any_running = lambda: any(sync.running for sync in app.sync_managers)
        app._update_status_indicator = lambda running: status_updates.append(running)
        app._update_tray_menu = lambda: tray_updates.append(True)
        app.control = SimpleNamespace(update_stats=lambda *_args: None)
        app.aggregate_sync_count = lambda: 10
        app.aggregate_bin_ready = lambda: False

        app.sync_managers[0].event_queue.put(("info", "sync_stopped"))

        App._poll_events(app)

        self.assertEqual([False], app.project_panels[0].running_ui)
        self.assertEqual([], app.project_panels[1].running_ui)
        self.assertEqual([True], status_updates)
        self.assertEqual([True], tray_updates)

    def test_poll_events_clears_previous_return_time_when_project_starts(self):
        app = object.__new__(App)
        app._shutting_down = False
        app._maybe_check_appearance_change = lambda: None
        app._schedule_after = lambda *_args, **_kwargs: None
        app._on_bin_ready = lambda *_args, **_kwargs: None
        app._on_bin_unchanged = lambda *_args, **_kwargs: None
        app._latest_bin_return_times = {0: 1753243200.0, 1: 1753243300.0}
        app.sync_managers = [
            FakeSync(0, running=True),
            FakeSync(1, running=True),
        ]
        app.project_panels = {
            0: FakeProjectPanel(),
            1: FakeProjectPanel(),
        }
        app.control = SimpleNamespace(update_stats=lambda *_args: None)
        app.aggregate_sync_count = lambda: 0
        app.aggregate_bin_ready = lambda: False

        app.sync_managers[1].event_queue.put(("info", "sync_started"))

        App._poll_events(app)

        self.assertEqual({0: 1753243200.0}, app._latest_bin_return_times)

    def test_poll_events_gives_each_project_a_chance_with_small_tick_budget(self):
        app = object.__new__(App)
        app._shutting_down = False
        app._maybe_check_appearance_change = lambda: None
        app._schedule_after = lambda *_args, **_kwargs: None
        app.EVENTS_PER_TICK = 2
        app._on_bin_ready = lambda *_args, **_kwargs: None
        app._on_bin_unchanged = lambda *_args, **_kwargs: None
        app.sync_managers = [
            FakeSync(0, synced_count=3, bin_ready=True),
            FakeSync(1, synced_count=7, bin_ready=False),
        ]
        app.project_panels = {
            0: FakeProjectPanel(),
            1: FakeProjectPanel(),
        }
        app.control = SimpleNamespace(update_stats=lambda *_args: None)
        app.aggregate_sync_count = lambda: 10
        app.aggregate_bin_ready = lambda: False

        app.sync_managers[0].event_queue.put(("log", LogEvent("i", "project-1-first", "info")))
        app.sync_managers[0].event_queue.put(("log", LogEvent("i", "project-1-second", "info")))
        app.sync_managers[1].event_queue.put(("log", LogEvent("i", "project-2-first", "info")))

        App._poll_events(app)

        self.assertEqual(["project-1-first"], [event.message for event in app.project_panels[0].log_panel.events])
        self.assertEqual(["project-2-first"], [event.message for event in app.project_panels[1].log_panel.events])

    def test_start_all_is_atomic_across_enabled_projects(self):
        calls = []

        syncs = [FakeSync(0), FakeSync(1)]

        control = object.__new__(ControlPanel)
        control.app = SimpleNamespace(
            project_panels={
                0: FakeProjectPanel(),
                1: FakeProjectPanel(),
            },
            get_enabled_project_indexes=lambda: [0, 1],
            get_sync_manager=lambda index: syncs[index],
            sync_managers=syncs,
            _collect_preflight_report=lambda project_index=0, **_kwargs: (
                PreflightReport(errors=["bad project 2"])
                if project_index == 1
                else PreflightReport()
            ),
            _emit_preflight_report=lambda _report, **_kwargs: None,
            set_all_config_enabled=lambda _enabled: None,
            _update_status_indicator=lambda _running: None,
            _update_tray_menu=lambda: None,
            cm=SimpleNamespace(config=SimpleNamespace(language="zh")),
        )
        control.start_btn = SimpleNamespace(configure=lambda **_kwargs: calls.append("start_btn"))
        control.pause_btn = FakeButton()
        control.uptime_label = FakeButton()
        control.after = lambda _delay, callback: callback()
        control._start_time = None
        control._last_uptime_text = ""

        with patch("ui.threading.Thread", ImmediateThread):
            ControlPanel._start(control)

        self.assertEqual([], syncs[0].start_calls)
        self.assertEqual([], syncs[1].start_calls)

    def test_start_all_checks_every_enabled_project_before_blocking_on_failures(self):
        collected = []
        emitted = []
        reports = {
            0: PreflightReport(errors=["bad project 1"]),
            1: PreflightReport(errors=["bad project 2"]),
        }
        syncs = [FakeSync(0), FakeSync(1)]

        def collect(project_index=0, **_kwargs):
            collected.append(project_index)
            return reports[project_index]

        control = object.__new__(ControlPanel)
        control.app = SimpleNamespace(
            project_panels={
                0: FakeProjectPanel(),
                1: FakeProjectPanel(),
            },
            get_enabled_project_indexes=lambda: [0, 1],
            get_sync_manager=lambda index: syncs[index],
            sync_managers=syncs,
            _collect_preflight_report=collect,
            _emit_preflight_report=lambda report, project_index=None, **_kwargs: emitted.append(
                (project_index, tuple(report.errors))
            ),
            set_all_config_enabled=lambda _enabled: None,
            _update_status_indicator=lambda _running: None,
            _update_tray_menu=lambda: None,
            cm=SimpleNamespace(config=SimpleNamespace(language="zh")),
        )
        control.start_btn = FakeButton()
        control.pause_btn = FakeButton()
        control.uptime_label = FakeButton()
        control.after = lambda _delay, callback: callback()
        control._start_time = None
        control._last_uptime_text = ""

        with patch("ui.threading.Thread", ImmediateThread):
            ControlPanel._start(control)

        self.assertEqual([0, 1], collected)
        self.assertIn((0, ("bad project 1",)), emitted)
        self.assertIn((1, ("bad project 2",)), emitted)
        self.assertEqual([], syncs[0].start_calls)
        self.assertEqual([], syncs[1].start_calls)

    def test_start_all_logs_to_passed_project_when_another_project_fails_preflight(self):
        control = object.__new__(ControlPanel)
        project_1 = FakeProjectPanel()
        project_2 = FakeProjectPanel()
        syncs = [FakeSync(0), FakeSync(1)]
        control.app = SimpleNamespace(
            project_panels={0: project_1, 1: project_2},
            get_enabled_project_indexes=lambda: [0, 1],
            get_sync_manager=lambda index: syncs[index],
            sync_managers=syncs,
            _collect_preflight_report=lambda project_index=0, **_kwargs: (
                PreflightReport(errors=["bad project 2"])
                if project_index == 1
                else PreflightReport()
            ),
            _emit_preflight_report=lambda _report, **_kwargs: None,
            set_all_config_enabled=lambda _enabled: None,
            _update_status_indicator=lambda _running: None,
            _update_tray_menu=lambda: None,
            cm=SimpleNamespace(config=SimpleNamespace(language="zh")),
        )
        control.start_btn = FakeButton()
        control.pause_btn = FakeButton()
        control.uptime_label = FakeButton()
        control.after = lambda _delay, callback: callback()
        control._start_time = None
        control._last_uptime_text = ""

        with patch("ui.threading.Thread", ImmediateThread):
            ControlPanel._start(control)

        self.assertEqual([], project_2.log_panel.events)
        self.assertEqual(1, len(project_1.log_panel.events))
        event = project_1.log_panel.events[0]
        self.assertEqual(LogIcon.WARNING, event.icon)
        self.assertIn("项目 2", event.message)
        self.assertIn("未启动", event.message)
        self.assertIn("配置", event.message)
        self.assertIn("单独启动", event.message)

    def test_start_all_emits_preflight_reports_before_starting_projects(self):
        calls = []

        class OrderedSync(FakeSync):
            def start(self, **kwargs):
                calls.append(("start", self.project_index))
                return super().start(**kwargs)

        syncs = [OrderedSync(0), OrderedSync(1)]
        control = object.__new__(ControlPanel)
        control.app = SimpleNamespace(
            project_panels={
                0: FakeProjectPanel(),
                1: FakeProjectPanel(),
            },
            get_enabled_project_indexes=lambda: [0, 1],
            get_sync_manager=lambda index: syncs[index],
            sync_managers=syncs,
            _collect_preflight_report=lambda project_index=0, **_kwargs: PreflightReport(
                warnings=[f"warn {project_index + 1}"]
            ),
            _emit_preflight_report=lambda _report, project_index=None, **_kwargs: calls.append(
                ("preflight", project_index)
            ),
            set_all_config_enabled=lambda _enabled: None,
            _update_status_indicator=lambda _running: None,
            _update_tray_menu=lambda: None,
            cm=SimpleNamespace(config=SimpleNamespace(language="zh")),
        )
        control.start_btn = FakeButton()
        control.pause_btn = FakeButton()
        control.uptime_label = FakeButton()
        control.after = lambda _delay, callback: callback()
        control._start_time = None
        control._last_uptime_text = ""

        with patch("ui.threading.Thread", ImmediateThread):
            ControlPanel._start(control)

        self.assertLess(calls.index(("preflight", 0)), calls.index(("start", 0)))
        self.assertLess(calls.index(("preflight", 1)), calls.index(("start", 1)))

    def test_start_all_starts_projects_concurrently_after_preflight(self):
        p1_started = threading.Event()
        p1_continue = threading.Event()
        p2_started = threading.Event()

        class BlockingSync(FakeSync):
            def start(self, **kwargs):
                self.start_calls.append(kwargs)
                if self.project_index == 0:
                    p1_started.set()
                    self.assertTrue(p1_continue.wait(timeout=5))
                else:
                    p2_started.set()
                self.running = True
                return True

        syncs = [BlockingSync(0), BlockingSync(1)]
        control = object.__new__(ControlPanel)
        control.app = SimpleNamespace(
            project_panels={
                0: FakeProjectPanel(),
                1: FakeProjectPanel(),
            },
            get_enabled_project_indexes=lambda: [0, 1],
            get_sync_manager=lambda index: syncs[index],
            sync_managers=syncs,
            _collect_preflight_report=lambda project_index=0, **_kwargs: PreflightReport(),
            _emit_preflight_report=lambda _report, **_kwargs: None,
            set_all_config_enabled=lambda _enabled: None,
            _update_status_indicator=lambda _running: None,
            _update_tray_menu=lambda: None,
            cm=SimpleNamespace(config=SimpleNamespace(language="zh")),
        )
        control.start_btn = FakeButton()
        control.pause_btn = FakeButton()
        control.uptime_label = FakeButton()
        control.after = lambda _delay, callback: callback()
        control._start_time = None
        control._last_uptime_text = ""

        worker = threading.Thread(target=ControlPanel._start_worker, args=(control,))
        worker.start()
        self.assertTrue(p1_started.wait(timeout=5))
        time.sleep(0.2)

        try:
            self.assertTrue(p2_started.is_set())
        finally:
            p1_continue.set()
            worker.join(timeout=5)

        self.assertFalse(worker.is_alive())

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
            _save_values_only=lambda emit_log=False: None,
            mark_start_checking=lambda: None,
            apply_preflight_report=lambda _report: None,
            set_config_enabled=lambda _enabled: None,
        )
        pane.log_panel = SimpleNamespace(append=lambda _event: None)
        pane.start_btn = FakeButton()
        pane.pause_btn = FakeButton()
        pane.toggle_btn = FakeButton()
        pane.after = lambda _delay, callback: callback()
        pane.app._collect_preflight_report = lambda **_kwargs: PreflightReport()
        pane.app._emit_preflight_report = lambda _report, **_kwargs: None

        with patch("ui.threading.Thread", ImmediateThread):
            ui.ProjectPane._start_project(pane)

        self.assertEqual([], syncs[0].start_calls)
        self.assertEqual(1, len(syncs[1].start_calls))
        self.assertTrue(syncs[1].start_calls[0]["preflight_checked"])
        self.assertEqual([False, False], config_enabled)

    def test_project_pane_emits_preflight_report_before_starting_sync(self):
        calls = []

        class OrderedSync(FakeSync):
            def start(self, **kwargs):
                calls.append("start")
                return super().start(**kwargs)

        sync = OrderedSync(0)
        pane = object.__new__(ui.ProjectPane)
        pane.project_index = 0
        pane.app = SimpleNamespace(
            get_sync_manager=lambda _index: sync,
            set_all_config_enabled=lambda _enabled: None,
            any_running=lambda: sync.running,
            control=None,
            _update_status_indicator=lambda _running: None,
            _update_tray_menu=lambda: None,
            _collect_preflight_report=lambda **_kwargs: PreflightReport(warnings=["warn"]),
            _emit_preflight_report=lambda _report, **_kwargs: calls.append("preflight"),
        )
        pane.config_panel = SimpleNamespace(
            _save_values_only=lambda emit_log=False: None,
            mark_start_checking=lambda: None,
            apply_preflight_report=lambda _report: None,
            set_config_enabled=lambda _enabled: None,
        )
        pane.log_panel = SimpleNamespace(append=lambda _event: None)
        pane.start_btn = FakeButton()
        pane.pause_btn = FakeButton()
        pane.toggle_btn = None
        pane.after = lambda _delay, callback: callback()

        with patch("ui.threading.Thread", ImmediateThread):
            ui.ProjectPane._start_project(pane)

        self.assertLess(calls.index("preflight"), calls.index("start"))

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
        self.assertEqual("1180x955", ui.DUAL_PROJECT_GEOMETRY)
        self.assertEqual((1040, 740), ui.DUAL_PROJECT_MIN_SIZE)
        self.assertEqual(ui.DUAL_PROJECT_GEOMETRY, app.window.geometry_calls[-1])
        self.assertEqual(ui.DUAL_PROJECT_MIN_SIZE, app.window.minsize_calls[-1])

        App._set_project_enabled(app, 1, False, save=False)
        self.assertEqual("700x955", ui.SINGLE_PROJECT_GEOMETRY)
        self.assertEqual((640, 720), ui.SINGLE_PROJECT_MIN_SIZE)
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

    def test_status_indicator_reports_partial_error_for_suspended_project(self):
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
            FakeSync(1, running=True, has_error=True),
        ]
        app.status_dot = FakeLabel()
        app.status_text = FakeLabel()
        app._status_indicator_state = "ready"

        App._update_status_indicator(app, True)

        self.assertEqual("部分异常", app.status_text.configures[-1]["text"])

    def test_control_keeps_start_disabled_while_another_project_full_syncs(self):
        control = object.__new__(ControlPanel)
        control.start_btn = FakeButton()
        control.app = SimpleNamespace(
            any_running=lambda: False,
            any_full_sync_active=lambda: True,
            sync=SimpleNamespace(running=False),
        )

        ControlPanel.set_full_sync_active(control, False)

        self.assertTrue(
            any(call.get("state") == "disabled" for call in control.start_btn.configures)
        )
        self.assertFalse(
            any(call.get("state") == "normal" for call in control.start_btn.configures)
        )

    def test_project_pane_disables_project_start_pause_during_full_sync(self):
        pane = object.__new__(ui.ProjectPane)
        pane.start_btn = FakeButton()
        pane.pause_btn = FakeButton()
        pane.toggle_btn = FakeButton()
        pane.project_index = 0
        pane.config_panel = SimpleNamespace(set_config_enabled=lambda _enabled: None)
        pane._sync_manager = lambda: SimpleNamespace(running=False)

        ui.ProjectPane.set_full_sync_active(pane, True)

        self.assertTrue(any(call.get("state") == "disabled" for call in pane.start_btn.configures))
        self.assertTrue(any(call.get("state") == "disabled" for call in pane.pause_btn.configures))


if __name__ == "__main__":
    unittest.main()
