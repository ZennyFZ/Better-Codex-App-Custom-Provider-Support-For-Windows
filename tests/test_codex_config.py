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


if __name__ == "__main__":
    unittest.main()
