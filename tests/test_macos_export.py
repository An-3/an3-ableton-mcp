import unittest
from unittest import mock

from MCP_Server import macos_export


class MacOSExportTest(unittest.TestCase):
    def test_build_open_export_dialog_menu_script_contains_file_menu_path(self):
        script = macos_export.build_open_export_dialog_menu_script("Ableton Live 12 Suite")
        self.assertIn('menu bar item "File"', script)
        self.assertIn('menu item "Export Audio/Video..."', script)
        self.assertIn("waitForPrimarySheet", script)

    def test_build_set_export_dialog_fields_script_contains_labels_and_values(self):
        script = macos_export.build_set_export_dialog_fields_script(
            process_name="Ableton Live 12 Suite",
            render_source="Main",
            sample_rate="44100",
            bit_depth="24",
            normalize=False,
            dither="Triangular",
        )
        self.assertIn('"Rendered Track"', script)
        self.assertIn('"Sample Rate"', script)
        self.assertIn('"Bit Depth"', script)
        self.assertIn('"Normalize"', script)
        self.assertIn('"Dither Options"', script)
        self.assertIn('"Main"', script)
        self.assertIn('"44100"', script)
        self.assertIn('"24"', script)
        self.assertIn('"Triangular"', script)

    def test_build_save_panel_script_contains_go_to_folder_and_filename(self):
        script = macos_export.build_save_panel_script(
            process_name="Ableton Live 12 Suite",
            output_folder="/Users/test/Downloads",
            file_name="Test EXPORT.wav",
        )
        self.assertIn('keystroke "G" using {command down, shift down}', script)
        self.assertIn('/Users/test/Downloads', script)
        self.assertIn('Test EXPORT.wav', script)
        self.assertIn('"Save"', script)

    def test_build_overwrite_confirmation_script_contains_replace_button(self):
        script = macos_export.build_overwrite_confirmation_script("Ableton Live 12 Suite")
        self.assertIn('"Replace"', script)

    def test_preflight_blocks_when_not_macos(self):
        with mock.patch("platform.system", return_value="Linux"):
            result = macos_export.check_export_preflight()
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_code"], "not_macos")

    def test_preflight_blocks_when_accessibility_is_disabled(self):
        accessibility_failure = {
            "ok": False,
            "failure_code": "accessibility_unavailable",
            "reason": "UI scripting is disabled.",
        }
        with mock.patch("platform.system", return_value="Darwin"):
            with mock.patch("shutil.which", return_value="/usr/bin/osascript"):
                with mock.patch.object(macos_export, "run_applescript", return_value=accessibility_failure):
                    result = macos_export.check_export_preflight()
        self.assertFalse(result["ok"])
        self.assertEqual(result["failure_code"], "accessibility_unavailable")

    def test_preflight_succeeds_when_all_checks_pass(self):
        responses = [
            {"ok": True, "stdout": "enabled", "stderr": "", "returncode": 0},
            {"ok": True, "stdout": "Ableton Live 12 Suite", "stderr": "", "returncode": 0},
            {"ok": True, "stdout": "Ableton Live 12 Suite", "stderr": "", "returncode": 0},
            {"ok": True, "stdout": "clear", "stderr": "", "returncode": 0},
        ]
        with mock.patch("platform.system", return_value="Darwin"):
            with mock.patch("shutil.which", return_value="/usr/bin/osascript"):
                with mock.patch.object(macos_export, "run_applescript", side_effect=responses):
                    result = macos_export.check_export_preflight()
        self.assertTrue(result["ok"])
        self.assertEqual(result["process_name"], "Ableton Live 12 Suite")
        self.assertTrue(result["frontmost"])

    def test_run_export_audio_ui_falls_back_to_shortcut_when_menu_path_fails(self):
        preflight_ok = {
            "ok": True,
            "failure_code": None,
            "reason": None,
            "platform": "Darwin",
            "osascript_path": "/usr/bin/osascript",
            "ui_scripting_enabled": True,
            "process_name": "Ableton Live 12 Suite",
            "frontmost": True,
            "modal_dialog_open": False,
        }
        applescript_results = [
            {"ok": False, "failure_code": "export_dialog_not_found", "reason": "Menu open failed."},
            {"ok": True, "stdout": "shortcut", "stderr": "", "returncode": 0},
            {"ok": True, "stdout": "export", "stderr": "", "returncode": 0},
            {"ok": True, "stdout": "save", "stderr": "", "returncode": 0},
            {"ok": True, "stdout": "not-needed", "stderr": "", "returncode": 0},
        ]
        with mock.patch.object(macos_export, "check_export_preflight", return_value=preflight_ok):
            with mock.patch.object(macos_export, "run_applescript", side_effect=applescript_results):
                result = macos_export.run_export_audio_ui(
                    output_folder="/Users/test/Downloads",
                    file_name="Test EXPORT.wav",
                    render_source="Main",
                    sample_rate=44100,
                    bit_depth=24,
                    normalize=False,
                    dither="Triangular",
                )
        self.assertEqual(result["state"], "export-ready")
        self.assertTrue(result["ui_automation"]["ok"])
        self.assertEqual(result["ui_automation"]["stages"][0]["method"], "menu")
        self.assertEqual(result["ui_automation"]["stages"][1]["method"], "shortcut")


if __name__ == "__main__":
    unittest.main()
