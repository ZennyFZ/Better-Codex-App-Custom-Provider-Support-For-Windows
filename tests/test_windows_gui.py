import unittest
import tempfile
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

        self.assertEqual(spec["geometry"], "620x460")
        self.assertEqual(spec["background"], "#555555")
        self.assertEqual(
            spec["fields"],
            ("Portable root (required):", "Backup directory (optional):"),
        )
        self.assertEqual(
            spec["buttons"],
            ("AUDIO: OFF", "DOWNLOAD", "CHECK ONLY", "PATCH", "CLEAR LOG"),
        )
        self.assertEqual(spec["visible_sections"], ("Patch target", "Activity log"))

    def test_gui_spec_contains_configuration_pages(self):
        from patch_chatgpt_providers_windows_gui import build_classic_ui_spec

        spec = build_classic_ui_spec()

        self.assertEqual(spec["pages"], ("Setup",))
        self.assertEqual(spec["actions"], ("DOWNLOAD", "CHECK ONLY", "PATCH"))

    def test_gui_spec_is_patch_only(self):
        from patch_chatgpt_providers_windows_gui import build_classic_ui_spec

        spec = build_classic_ui_spec()

        self.assertEqual(
            spec["action_labels"],
            {
                "AUDIO": "AUDIO: OFF",
                "DOWNLOAD": "DOWNLOAD",
                "CHECK ONLY": "CHECK ONLY",
                "PATCH": "PATCH",
            },
        )
        self.assertEqual(spec["patch_note"], "CHECK ONLY scans. PATCH backs up and replaces app.asar.")

    def test_one_click_batch_launches_gui_without_path_arguments(self):
        launcher = Path(__file__).parents[1] / "launch_windows_portable_patcher.bat"
        contents = launcher.read_text(encoding="utf-8").lower()

        self.assertIn("%~dp0", contents)
        self.assertIn("patch_chatgpt_providers_windows_gui.py", contents)
        self.assertIn("pythonw.exe", contents)
        self.assertNotIn("--app-root", contents)
        self.assertNotIn("--config", contents)
        self.assertNotIn("--backup-dir", contents)

    def test_compact_window_keeps_action_buttons_visible(self):
        import tkinter as tk

        from patch_chatgpt_providers_windows_gui import TerminalPatcherUi

        ui = None
        try:
            ui = TerminalPatcherUi()
            ui.root.geometry("560x360")
            ui.root.update()

            self.assertEqual(ui.audio_button.cget("text"), "AUDIO: OFF")
            for button in (
                ui.audio_button,
                ui.download_button,
                ui.check_button,
                ui.patch_button,
                ui.clear_button,
            ):
                self.assertTrue(button.winfo_ismapped())
                self.assertLessEqual(
                    button.winfo_rooty() + button.winfo_height(),
                    ui.root.winfo_rooty() + ui.root.winfo_height(),
                )
            self.assertGreater(ui.clear_button.winfo_rooty(), ui.log.winfo_rooty())
        except tk.TclError as exc:
            self.skipTest(f"Tk display is unavailable: {exc}")
        finally:
            if ui is not None:
                ui.root.destroy()

    def test_audio_player_is_off_until_toggled(self):
        from windows_audio import MciAudioPlayer

        with tempfile.TemporaryDirectory() as temp:
            media = Path(temp) / "media"
            media.mkdir()
            track = media / "theme.mp3"
            track.write_bytes(b"fake mp3")
            commands = []

            player = MciAudioPlayer(media, send_command=lambda command: commands.append(command) or 0)

            self.assertFalse(player.enabled)
            self.assertTrue(player.toggle())
            self.assertTrue(player.enabled)
            self.assertIn('open "', commands[0])
            self.assertIn("play better_codex_audio repeat", commands[1])

            self.assertFalse(player.toggle())
            self.assertFalse(player.enabled)
            self.assertEqual(commands[-2:], ["stop better_codex_audio", "close better_codex_audio"])

    def test_audio_player_reports_missing_media_without_playing(self):
        from windows_audio import AudioError, MciAudioPlayer

        with tempfile.TemporaryDirectory() as temp:
            commands = []
            player = MciAudioPlayer(
                Path(temp),
                send_command=lambda command: commands.append(command) or 0,
            )

            with self.assertRaises(AudioError):
                player.toggle()

            self.assertFalse(player.enabled)
            self.assertEqual(commands, [])


if __name__ == "__main__":
    unittest.main()
