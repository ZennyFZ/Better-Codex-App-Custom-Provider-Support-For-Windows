import json
from pathlib import Path
import tempfile
import unittest


class ConfigValidationTests(unittest.TestCase):
    def test_default_paths_are_under_codex_home(self):
        from codex_config import default_config_paths

        paths = default_config_paths(Path(r"C:\Users\Test\.codex"))

        self.assertEqual(paths.config_toml, Path(r"C:\Users\Test\.codex\config.toml"))
        self.assertEqual(
            paths.provider_menu,
            Path(r"C:\Users\Test\.codex\desktop-model-providers.json"),
        )
        self.assertEqual(
            paths.model_catalog,
            Path(r"C:\Users\Test\.codex\model-catalogs\custom.json"),
        )

    def test_provider_menu_rejects_mapping_to_unknown_provider(self):
        from codex_config import validate_provider_menu
        from windows_portable import PatchError

        with self.assertRaisesRegex(PatchError, "unknown provider"):
            validate_provider_menu(
                {
                    "version": 1,
                    "default_provider": "openai",
                    "providers": [
                        {"id": "openai", "label": "OpenAI", "description": ""}
                    ],
                    "model_providers": {"model-x": "missing"},
                },
                {"openai"},
            )

    def test_model_catalog_requires_models_array(self):
        from codex_config import validate_model_catalog
        from windows_portable import PatchError

        with self.assertRaisesRegex(PatchError, "models"):
            validate_model_catalog({})

    def test_model_catalog_rejects_duplicate_slugs(self):
        from codex_config import validate_model_catalog
        from windows_portable import PatchError

        with self.assertRaisesRegex(PatchError, "Duplicate model slug"):
            validate_model_catalog(
                {
                    "models": [
                        {"slug": "same", "display_name": "One", "description": ""},
                        {"slug": "same", "display_name": "Two", "description": ""},
                    ]
                }
            )


class PersistenceTests(unittest.TestCase):
    def test_atomic_json_write_keeps_original_in_timestamped_backup(self):
        from codex_config import atomic_write_json

        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            target = tmp_path / "desktop-model-providers.json"
            target.write_text('{"version": 1}\n', encoding="utf-8")

            backup = atomic_write_json(
                target,
                {"version": 1, "changed": True},
                tmp_path / "backups",
            )

            self.assertIsNotNone(backup)
            self.assertEqual(backup.read_text(encoding="utf-8"), '{"version": 1}\n')
            self.assertTrue(json.loads(target.read_text(encoding="utf-8"))["changed"])

    def test_gui_settings_never_persist_secret_keys(self):
        from codex_config import save_gui_settings

        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            save_gui_settings(
                settings_path,
                {"portable_root": "D:\\Apps", "api_key": "secret"},
            )

            saved = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(saved, {"portable_root": "D:\\Apps"})

    def test_load_json_returns_default_for_missing_file(self):
        from codex_config import load_json

        with tempfile.TemporaryDirectory() as directory:
            result = load_json(Path(directory) / "missing.json", {"version": 1})

            self.assertEqual(result, {"version": 1})


if __name__ == "__main__":
    unittest.main()
