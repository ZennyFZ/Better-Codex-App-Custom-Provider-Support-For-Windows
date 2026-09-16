import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


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


class TomlWriterTests(unittest.TestCase):
    def test_toml_update_preserves_unrelated_settings_and_comments(self):
        from codex_config import write_codex_config

        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            config = tmp_path / "config.toml"
            config.write_text(
                '# Keep this comment\nmodel = "gpt-5.6"\n\n'
                '[features]\nexperimental = true\n\n'
                '[model_providers.old]\nname = "Old"\nbase_url = "http://old"\n',
                encoding="utf-8",
            )

            write_codex_config(
                config,
                {"model_catalog_json": str(tmp_path / "models.json")},
                [
                    {
                        "id": "openrouter",
                        "name": "OpenRouter",
                        "base_url": "https://openrouter.ai/api/v1",
                        "wire_api": "responses",
                        "auth_mode": "environment",
                        "env_key": "OPENROUTER_API_KEY",
                    }
                ],
            )

            text = config.read_text(encoding="utf-8")
            self.assertIn("# Keep this comment", text)
            self.assertIn('model = "gpt-5.6"', text)
            self.assertIn("[features]", text)
            self.assertIn("experimental = true", text)
            self.assertIn("[model_providers.openrouter]", text)
            self.assertIn('env_key = "OPENROUTER_API_KEY"', text)
            self.assertNotIn("[model_providers.old]", text)

    def test_plaintext_mode_serializes_experimental_bearer_token(self):
        from codex_config import write_codex_config

        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            write_codex_config(
                config,
                {},
                [
                    {
                        "id": "custom",
                        "name": "Custom",
                        "base_url": "https://example.test/v1",
                        "wire_api": "responses",
                        "auth_mode": "plaintext",
                        "token": "secret-token",
                    }
                ],
            )

            text = config.read_text(encoding="utf-8")
            self.assertIn('experimental_bearer_token = "secret-token"', text)
            self.assertNotIn("env_key =", text)

    def test_provider_ids_with_punctuation_use_quoted_toml_keys(self):
        from codex_config import provider_toml_section

        self.assertEqual(
            provider_toml_section("my.provider"),
            '[model_providers."my.provider"]',
        )


class CredentialTests(unittest.TestCase):
    def test_environment_mode_sets_env_key_without_exposing_secret(self):
        import codex_config

        calls = []
        with mock.patch.object(
            codex_config,
            "_write_user_environment",
            side_effect=lambda name, value: calls.append((name, value)),
        ):
            provider = {
                "auth_mode": "environment",
                "env_key": "CUSTOM_API_KEY",
                "token": "secret",
            }
            codex_config.apply_environment_credential(provider)

        self.assertEqual(calls, [("CUSTOM_API_KEY", "secret")])
        summary = codex_config.credential_summary(provider)
        self.assertEqual(summary, "environment variable CUSTOM_API_KEY")
        self.assertNotIn("secret", summary)

    def test_plaintext_mode_requires_token(self):
        from codex_config import validate_credential_mode
        from windows_portable import PatchError

        with self.assertRaises(PatchError):
            validate_credential_mode({"auth_mode": "plaintext", "token": ""})


class CatalogMenuTests(unittest.TestCase):
    def test_clone_model_template_preserves_advanced_metadata(self):
        from codex_config import clone_model_template

        catalog = {
            "models": [
                {
                    "slug": "template",
                    "display_name": "Template",
                    "description": "Template description",
                    "supported_reasoning_levels": [
                        {"effort": "medium", "description": "Balanced"}
                    ],
                    "visibility": "list",
                }
            ]
        }

        result = clone_model_template(
            catalog,
            "template",
            "provider/model",
            "Provider Model",
            "Custom model",
        )

        self.assertEqual(result["slug"], "provider/model")
        self.assertEqual(result["display_name"], "Provider Model")
        self.assertEqual(
            result["supported_reasoning_levels"],
            catalog["models"][0]["supported_reasoning_levels"],
        )
        self.assertNotEqual(result, catalog["models"][0])

    def test_provider_menu_builder_maps_models_to_existing_provider(self):
        from codex_config import build_provider_menu

        result = build_provider_menu(
            [
                {"id": "openai", "label": "OpenAI", "description": ""},
                {"id": "custom", "label": "Custom", "description": ""},
            ],
            "openai",
            {"provider/model": "custom"},
        )

        self.assertEqual(result["default_provider"], "openai")
        self.assertEqual(
            result["model_providers"],
            {"provider/model": "custom"},
        )
        self.assertNotIn("token", json.dumps(result))

    def test_upsert_and_remove_model_keep_catalog_metadata(self):
        from codex_config import remove_model, upsert_model

        catalog = {
            "catalog_version": 2,
            "models": [
                {
                    "slug": "old",
                    "display_name": "Old",
                    "description": "Old",
                    "vendor_metadata": {"keep": True},
                }
            ],
        }
        updated = upsert_model(
            catalog,
            {
                "slug": "new",
                "display_name": "New",
                "description": "New",
                "provider": "custom",
            },
        )
        self.assertEqual(updated["catalog_version"], 2)
        self.assertEqual(len(updated["models"]), 2)
        self.assertEqual(remove_model(updated, "old")["models"][0]["slug"], "new")
        self.assertEqual(catalog["models"][0]["slug"], "old")


if __name__ == "__main__":
    unittest.main()
