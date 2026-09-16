import unittest
from pathlib import Path


class WindowsGuiTests(unittest.TestCase):
    def test_gui_module_exposes_parser_and_terminal_ui(self):
        from patch_chatgpt_providers_windows_gui import (
            TerminalPatcherUi,
            build_gui_parser,
        )

        parser = build_gui_parser()
        args = parser.parse_args(
            [
                "--app-root",
                r"D:\Apps\ChatGPT-portable",
                "--config",
                r"D:\Codex\providers.json",
                "--backup-dir",
                r"D:\Backups",
            ]
        )

        self.assertEqual(args.app_root.name, "ChatGPT-portable")
        self.assertEqual(args.config.name, "providers.json")
        self.assertEqual(args.backup_dir.name, "Backups")
        self.assertTrue(callable(TerminalPatcherUi))

    def test_gui_log_messages_are_prefixed_for_terminal_readability(self):
        from patch_chatgpt_providers_windows_gui import format_log_line

        self.assertEqual(format_log_line("OK", "portable app validated"), "[OK] portable app validated")
        self.assertEqual(format_log_line("ERROR", "patch failed"), "[ERROR] patch failed")

    def test_gui_exposes_compact_classic_utility_spec(self):
        from patch_chatgpt_providers_windows_gui import build_classic_ui_spec

        spec = build_classic_ui_spec()

        self.assertEqual(spec["geometry"], "620x600")
        self.assertEqual(spec["background"], "#555555")
        self.assertEqual(
            spec["fields"],
            ("Portable root:", "Config JSON:", "Backup directory:"),
        )
        self.assertEqual(spec["buttons"], ("CHECK ONLY", "PATCH", "CLEAR LOG"))

    def test_gui_spec_contains_configuration_pages(self):
        from patch_chatgpt_providers_windows_gui import build_classic_ui_spec

        spec = build_classic_ui_spec()

        self.assertEqual(spec["pages"], ("Setup", "Models", "Provider menu"))
        self.assertEqual(
            spec["actions"],
            ("LOAD", "SAVE", "VALIDATE", "CHECK ONLY", "PATCH"),
        )

    def test_gui_spec_explains_plaintext_warning(self):
        from patch_chatgpt_providers_windows_gui import build_classic_ui_spec

        self.assertIn("plaintext", build_classic_ui_spec()["plaintext_warning"].lower())

    def test_one_click_batch_launches_gui_without_path_arguments(self):
        launcher = Path(__file__).parents[1] / "launch_windows_portable_patcher.bat"
        contents = launcher.read_text(encoding="utf-8").lower()

        self.assertIn("%~dp0", contents)
        self.assertIn("patch_chatgpt_providers_windows_gui.py", contents)
        self.assertIn("pythonw.exe", contents)
        self.assertNotIn("--app-root", contents)
        self.assertNotIn("--config", contents)
        self.assertNotIn("--backup-dir", contents)


if __name__ == "__main__":
    unittest.main()
