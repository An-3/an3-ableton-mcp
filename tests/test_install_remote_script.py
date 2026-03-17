import tempfile
import unittest
from pathlib import Path

from MCP_Server import install_remote_script


class InstallRemoteScriptTest(unittest.TestCase):
    def test_discover_macos_remote_script_targets_includes_missing_script_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            root_a = home / "Library" / "Preferences" / "Ableton" / "Live 12.3.5" / "User Remote Scripts"
            root_b = home / "Library" / "Preferences" / "Ableton" / "Live 12.3.6" / "User Remote Scripts"
            root_a.mkdir(parents=True)
            root_b.mkdir(parents=True)
            (root_a / "AbletonMCP").mkdir()

            targets = install_remote_script.discover_macos_remote_script_targets(home=home)

        self.assertEqual(
            [str(path) for path in targets],
            [
                str(root_a / "AbletonMCP" / "__init__.py"),
                str(root_b / "AbletonMCP" / "__init__.py"),
            ],
        )

    def test_sync_remote_script_targets_dry_run_reports_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source.py"
            target = temp_path / "Live 12.3.6" / "User Remote Scripts" / "AbletonMCP" / "__init__.py"
            source.write_text("new-script\n", encoding="utf-8")
            target.parent.mkdir(parents=True)
            target.write_text("old-script\n", encoding="utf-8")

            result = install_remote_script.sync_remote_script_targets(
                source_path=source,
                targets=[target],
                dry_run=True,
            )

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["changed_count"], 1)
        self.assertTrue(result["targets"][0]["changed"])

    def test_sync_remote_script_targets_copies_source_and_creates_parent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "source.py"
            target = temp_path / "Live 12.3.6" / "User Remote Scripts" / "AbletonMCP" / "__init__.py"
            source.write_text("fresh-script\n", encoding="utf-8")

            result = install_remote_script.sync_remote_script_targets(
                source_path=source,
                targets=[target],
                dry_run=False,
            )

            written = target.read_text(encoding="utf-8")
            written_sha256 = install_remote_script.sha256_file(target)

        self.assertFalse(result["dry_run"])
        self.assertEqual(result["changed_count"], 1)
        self.assertEqual(written, "fresh-script\n")
        self.assertEqual(result["targets"][0]["installed_sha256"], written_sha256)


if __name__ == "__main__":
    unittest.main()
