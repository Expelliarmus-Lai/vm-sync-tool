import inspect
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import customtkinter as ctk
import ui
from ui import App, NewProfileDialog, ProfilePanel


class ProfileUiTests(unittest.TestCase):
    def test_profile_panel_is_inline_before_shared_vm_panel(self):
        source = inspect.getsource(App._build_ui)

        self.assertIn("self.profile_panel = ProfilePanel", source)
        self.assertLess(source.index("self.profile_panel = ProfilePanel"), source.index("self.shared_vm_panel = SharedVmPanel"))
        self.assertNotIn("simpledialog", inspect.getsource(ProfilePanel))

    def test_new_profile_uses_compact_copy_or_blank_dialog(self):
        source = inspect.getsource(NewProfileDialog)

        self.assertIn("CTkToplevel", source)
        self.assertIn('self.geometry("430x326")', source)
        self.assertIn("card.grid_rowconfigure(6, weight=1)", source)
        self.assertIn('actions.grid(row=7, column=0, sticky="sew"', source)
        self.assertIn("self.create_btn = ctk.CTkButton", source)
        self.assertIn("self.create_btn.pack", source)
        self.assertIn("self.card.winfo_reqheight() + 32", source)
        self.assertIn("source_var", source)
        self.assertIn("CTkRadioButton", source)
        self.assertIn("ui.profile.copy_current", source)
        self.assertIn("ui.profile.blank", source)
        self.assertIn('self.bind("<Return>"', source)
        self.assertIn('self.bind("<Escape>"', source)

    def test_new_profile_dialog_clears_panel_reference_when_closed(self):
        source = inspect.getsource(ProfilePanel)

        self.assertIn("self._profile_dialog_closed", source)
        self.assertIn("def _profile_dialog_closed(self):", source)
        self.assertIn("self._create_dialog = None", source)

    def test_selector_loads_immediately_and_actions_share_its_toolbar(self):
        source = inspect.getsource(ProfilePanel)

        self.assertIn("selector_shell", source)
        self.assertIn("_select_profile", source)
        self.assertIn("self._load_profile(profile_id)", source)
        self.assertNotIn("load_btn", source)
        self.assertNotIn("_request_load", source)
        self.assertIn("self.selector_shell,\n            text=self._tr(\"ui.profile.new_short\")", source)
        self.assertIn("self.selector_shell,\n            text=self._tr(\"ui.profile.delete_short\")", source)

    def test_saved_profile_name_is_only_shown_and_renamed_in_dropdown(self):
        source = inspect.getsource(ProfilePanel)

        self.assertNotIn("self.name_label", source)
        self.assertNotIn("self.name_entry", source)
        self.assertIn('image=self._rename_icon', source)
        self.assertIn('text=self._tr("ui.profile.rename")', source)
        self.assertIn("def _begin_rename(self, profile_id: str):", source)
        self.assertIn("self.app.cm.rename_profile(profile_id, entry.get())", source)
        self.assertIn('ui.profile.rename_save', source)

    def test_profile_card_spacing_and_selector_border_match_existing_inputs(self):
        source = inspect.getsource(ProfilePanel._build)

        self.assertIn('self.selector_area.pack(fill="x", padx=14, pady=(0, 10))', source)
        self.assertIn('height=36', source)
        self.assertIn('border_width=2', source)
        self.assertIn('self.selector_shell.pack_propagate(False)', source)
        self.assertIn('height=PROFILE_TOOLBAR_BUTTON_HEIGHT', source)
        self.assertIn('corner_radius=PROFILE_TOOLBAR_INNER_RADIUS', source)
        self.assertIn('padx=(PROFILE_TOOLBAR_INSET, 1)', source)
        self.assertIn('hover_color=current_palette()["hint_bg"]', source)
        self.assertEqual(
            ui.CONTROL_CORNER_RADIUS - ui.PROFILE_TOOLBAR_INSET,
            ui.PROFILE_TOOLBAR_INNER_RADIUS,
        )
        self.assertEqual(30, ui.PROFILE_TOOLBAR_BUTTON_HEIGHT)

    def test_profile_action_icons_share_the_same_muted_color(self):
        source = inspect.getsource(ProfilePanel.__init__)

        self.assertIn('"save", 16', source)
        self.assertGreaterEqual(
            source.count('light_color=LIGHT["text_dim"], dark_color=DARK["text_dim"]'),
            4,
        )

    def test_profile_action_labels_share_the_same_muted_color(self):
        build_source = inspect.getsource(ProfilePanel._build)
        theme_source = inspect.getsource(ProfilePanel.refresh_theme)

        self.assertIn('text=self._tr("ui.profile.save_short")', build_source)
        self.assertNotIn('text_color=current_palette()["accent"]', build_source)
        self.assertIn('self.save_btn.configure(\n            fg_color="transparent", hover_color=p["hint_bg"], text_color=p["text_dim"]', theme_source)

    def test_rename_editor_moves_into_main_selector_for_windows_ime(self):
        begin_source = inspect.getsource(ProfilePanel._begin_rename)
        focus_source = inspect.getsource(ProfilePanel._close_dropdown_if_unfocused)
        editor_source = inspect.getsource(ProfilePanel._show_rename_editor)
        acquire_source = inspect.getsource(ProfilePanel._focus_rename_entry)
        close_source = inspect.getsource(ProfilePanel._close_dropdown)
        finish_source = inspect.getsource(ProfilePanel._finish_rename_editor)

        self.assertIn("self._close_dropdown()", begin_source)
        self.assertIn("self._show_rename_editor(profile)", begin_source)
        self.assertIn("self.selector_shell", editor_source)
        self.assertIn("before=self._selector_separators[0]", editor_source)
        self.assertIn("font=ui_font(size=12)", editor_source)
        self.assertNotIn("overrideredirect", editor_source)
        self.assertNotIn("grab_set", editor_source)
        self.assertIn("window = self.app.window", acquire_source)
        self.assertIn("window.focus_force()", acquire_source)
        self.assertIn("entry.focus_force()", acquire_source)
        self.assertIn("_match_windows_ime_font(entry)", acquire_source)
        self.assertIn("attempt < 4", acquire_source)
        self.assertNotIn("_rename_profile_id", focus_source)
        self.assertNotIn("grab_release", close_source)
        self.assertIn("self.selector_btn.pack(", finish_source)
        self.assertIn("before=self._selector_separators[0]", finish_source)

    def test_windows_ime_composition_font_matches_entry_without_resizing_text(self):
        source = inspect.getsource(ui._match_windows_ime_font)

        self.assertIn('tk.call("font", "actual", font_spec, "-size")', source)
        self.assertIn('tk.call("font", "actual", font_spec, "-family")', source)
        self.assertIn("ImmSetCompositionFontW", source)
        self.assertIn("entry.winfo_toplevel().winfo_id()", source)

    def test_dropdown_width_tracks_selector_when_window_resizes(self):
        build_source = inspect.getsource(ProfilePanel._build)

        self.assertIn('self.selector_shell.pack(side="left", fill="x", expand=True)', build_source)
        self.assertIn('self.selector_btn.bind("<Configure>"', build_source)

        geometry_calls = []
        window = SimpleNamespace(
            winfo_exists=lambda: True,
            geometry=lambda value: geometry_calls.append(value),
        )
        selector = SimpleNamespace(
            winfo_width=lambda: 480,
            winfo_rootx=lambda: 100,
            winfo_rooty=lambda: 200,
            winfo_height=lambda: 32,
        )
        selector_shell = SimpleNamespace(
            winfo_rooty=lambda: 198,
            winfo_height=lambda: 36,
        )
        panel = SimpleNamespace(
            _dropdown_window=window,
            selector_btn=selector,
            selector_shell=selector_shell,
            app=SimpleNamespace(
                cm=SimpleNamespace(config=SimpleNamespace(profiles=[object(), object()]))
            ),
        )

        with patch.object(ctk.ScalingTracker, "get_window_scaling", return_value=1.5):
            ProfilePanel._sync_dropdown_geometry(panel)

        self.assertEqual(["320x86+100+236"], geometry_calls)

    def test_dropdown_height_is_bounded_and_large_profile_sets_scroll(self):
        open_source = inspect.getsource(ProfilePanel._open_dropdown)

        self.assertIn("CTkScrollableFrame", open_source)
        self.assertIn("PROFILE_DROPDOWN_VISIBLE_ROWS", open_source)
        self.assertIn("corner_radius=PROFILE_POPUP_INNER_RADIUS", open_source)
        self.assertIn("border_width=PROFILE_POPUP_BORDER_WIDTH", open_source)
        self.assertIn('row_parent.pack(fill="both", expand=True, padx=2, pady=2)', open_source)
        self.assertEqual(
            ui.CARD_CORNER_RADIUS - ui.PROFILE_POPUP_BORDER_WIDTH,
            ui.PROFILE_POPUP_INNER_RADIUS,
        )

        geometry_calls = []
        window = SimpleNamespace(
            winfo_exists=lambda: True,
            geometry=lambda value: geometry_calls.append(value),
        )
        selector = SimpleNamespace(
            winfo_width=lambda: 480,
            winfo_rootx=lambda: 100,
            winfo_rooty=lambda: 200,
            winfo_height=lambda: 28,
        )
        selector_shell = SimpleNamespace(
            winfo_rooty=lambda: 198,
            winfo_height=lambda: 36,
        )
        panel = SimpleNamespace(
            _dropdown_window=window,
            selector_btn=selector,
            selector_shell=selector_shell,
            app=SimpleNamespace(
                cm=SimpleNamespace(config=SimpleNamespace(profiles=[object()] * 20))
            ),
        )

        with patch.object(ctk.ScalingTracker, "get_window_scaling", return_value=1.5):
            ProfilePanel._sync_dropdown_geometry(panel)

        self.assertEqual(["320x332+100+236"], geometry_calls)

    def test_dropdown_outer_window_uses_native_antialiased_rounding(self):
        calls = []
        window = SimpleNamespace(
            configure=lambda **kwargs: calls.append(("configure", kwargs)),
            update_idletasks=lambda: calls.append(("update", None)),
            winfo_id=lambda: 1234,
        )
        dwm = SimpleNamespace(DwmSetWindowAttribute=lambda *_args: 0)

        with (
            patch.object(ui.os, "name", "nt"),
            patch.object(
                ui.ctypes,
                "windll",
                SimpleNamespace(dwmapi=dwm),
                create=True,
            ),
        ):
            configured = ui._configure_rounded_popup_window(window, "#ffffff")

        self.assertTrue(configured)
        self.assertEqual(("configure", {"fg_color": "#ffffff"}), calls[0])
        self.assertIn(("update", None), calls)
        open_source = inspect.getsource(ProfilePanel._open_dropdown)
        self.assertIn("_configure_rounded_popup_window(window, p[\"card\"])", open_source)
        self.assertIn("corner_radius=CARD_CORNER_RADIUS", open_source)
        self.assertNotIn("transparentcolor", inspect.getsource(ui._configure_rounded_popup_window))

    def test_dropdown_rounded_window_falls_back_without_dwm_support(self):
        configured_colors = []
        window = SimpleNamespace(
            configure=lambda **kwargs: configured_colors.append(kwargs["fg_color"]),
            update_idletasks=lambda: None,
            winfo_id=lambda: 1234,
        )
        dwm = SimpleNamespace(DwmSetWindowAttribute=lambda *_args: 1)

        with (
            patch.object(ui.os, "name", "nt"),
            patch.object(
                ui.ctypes,
                "windll",
                SimpleNamespace(dwmapi=dwm),
                create=True,
            ),
        ):
            configured = ui._configure_rounded_popup_window(window, "#ffffff")

        self.assertFalse(configured)
        self.assertEqual(["#ffffff"], configured_colors)

    def test_dropdown_closes_for_outside_click_focus_loss_and_window_hide(self):
        panel_source = inspect.getsource(ProfilePanel.__init__)
        click_source = inspect.getsource(ProfilePanel._on_global_pointer_press)
        focus_source = inspect.getsource(ProfilePanel._close_dropdown_if_app_inactive)
        close_source = inspect.getsource(App._on_close)

        self.assertIn('self.app.window.bind("<FocusOut>"', panel_source)
        self.assertIn('self.app.window.bind("<Unmap>"', panel_source)
        self.assertIn('self.app.window.bind_all("<ButtonPress>"', panel_source)
        self.assertNotIn('self.bind_all("<ButtonPress>"', panel_source)
        self.assertIn("self._widget_is_within(widget, window)", click_source)
        self.assertIn("self._widget_is_within(widget, self.selector_shell)", click_source)
        self.assertIn("if focused is None:", focus_source)
        self.assertIn("profile_panel.close_popups()", close_source)

    def test_dropdown_chevron_is_left_aligned_padded_and_heavier(self):
        icon_source = inspect.getsource(ui._draw_line_icon)
        build_source = inspect.getsource(ProfilePanel._build)
        init_source = inspect.getsource(ProfilePanel.__init__)

        self.assertIn('"chevron_down", 15', init_source)
        self.assertIn('compound="left"', build_source)
        self.assertIn('border_spacing=9', build_source)
        self.assertIn('int(2.2 * scale)', icon_source)

    def test_profile_panel_is_disabled_with_other_config_controls(self):
        calls = []
        app = object.__new__(App)
        app.profile_panel = SimpleNamespace(set_enabled=lambda enabled: calls.append(enabled))
        app.shared_vm_panel = SimpleNamespace(set_config_enabled=lambda _enabled: None)
        app.project_panels = {}

        App.set_all_config_enabled(app, False)

        self.assertEqual([False], calls)

    def test_stale_vm_status_result_is_ignored_after_profile_change(self):
        app = object.__new__(App)
        app._shutting_down = False
        app._config_revision = 2
        app._status_check_running = True
        app.cm = SimpleNamespace(config=SimpleNamespace(vmx_path=""))

        App._apply_vm_status_result(
            app,
            "vmrun.exe",
            "old.vmx",
            SimpleNamespace(ok=True, paths=[], error=""),
            config_revision=1,
        )

        self.assertTrue(app._status_check_running)

    def test_stale_vm_status_result_is_rechecked_after_same_profile_vmx_edit(self):
        app = object.__new__(App)
        app._shutting_down = False
        app._config_revision = 2
        app._status_check_running = True
        app.cm = SimpleNamespace(config=SimpleNamespace(vmx_path=r"C:\VMs\new.vmx"))
        calls = []

        def recheck(schedule_next=True):
            calls.append(schedule_next)
            app._status_check_running = True

        app._check_vm_status = recheck

        App._apply_vm_status_result(
            app,
            "vmrun.exe",
            r"C:\VMs\old.vmx",
            SimpleNamespace(ok=True, paths=[], error=""),
            config_revision=2,
        )

        self.assertEqual([False], calls)
        self.assertTrue(app._status_check_running)

    def test_shutdown_prompts_for_unfinished_rename_before_form_changes(self):
        actions = []
        panel = SimpleNamespace(
            _rename_profile_id="profile-2",
            _tr=lambda key: key,
            _confirm_rename=lambda: actions.append("save") or True,
            _finish_rename_editor=lambda: actions.append("discard"),
            app=SimpleNamespace(
                window=object(),
                profile_form_is_dirty=lambda: False,
            ),
        )

        with patch("ui.messagebox.askyesnocancel", return_value=True):
            allowed = ProfilePanel.confirm_shutdown(panel)

        self.assertTrue(allowed)
        self.assertEqual(["save"], actions)

    def test_profile_management_translations_exist_in_both_languages(self):
        for language in ("zh", "en"):
            translator = ui.Translator(language)
            for key in (
                "ui.profile.title",
                "ui.profile.current",
                "ui.profile.create_save",
                "ui.profile.unsaved_prompt",
                "ui.profile.confirm_delete",
                "ui.profile.rename",
                "ui.profile.log.renamed",
                "ui.profile.dialog.heading",
            ):
                self.assertNotEqual(key, translator.tr(key))


if __name__ == "__main__":
    unittest.main()
