# User-friendly Windows provider configurator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GUI editor that configures Codex providers, credentials, model catalog entries, and the patched provider menu without manual file editing.

**Architecture:** Keep ASAR discovery, process checks, backup, and patching in `windows_portable.py`. Add `codex_config.py` as a pure configuration boundary for provider-menu JSON, model-catalog JSON, targeted TOML updates, per-user Windows environment variables, backups, and validation. Extend the existing Tkinter window with Setup, Models, and Provider menu pages that exchange typed dictionaries with the configuration boundary and run writes through the existing background worker.

**Tech Stack:** Python 3.9+, standard library (`json`, `pathlib`, `tempfile`, `tomllib` when available, `winreg` on Windows), Tkinter, `unittest`, and the existing custom standard-library ASAR reader/rebuilder.

**Spec:** `docs/superpowers/specs/2026-09-16-user-friendly-configurator-design.md`

## Global Constraints

- Support Python 3.9 or newer.
- Keep the configuration layer dependency-free; do not add a package requirement for TOML or GUI support.
- Manage `%USERPROFILE%\\.codex\\config.toml`, `%USERPROFILE%\\.codex\\desktop-model-providers.json`, and `%USERPROFILE%\\.codex\\model-catalogs\\custom.json` by default.
- Preserve unrelated TOML keys/comments and unknown catalog fields whenever possible.
- Store environment-mode secrets in the current Windows user's environment; never write machine-wide environment state.
- Plaintext mode writes `experimental_bearer_token` only after explicit confirmation and masks the field by default.
- Never put credentials in provider-menu JSON, GUI settings, logs, exceptions, or test output.
- Validate every configuration file before changing `app.asar`.
- Create timestamped backups and use atomic replacement for every existing configuration file and the portable ASAR.
- Refuse to patch while a process launched from the selected portable root is running.
- Do not install or launch ChatGPT or modify the installed WindowsApps package.

---

### Task 1: Define configuration data contracts and validation

**Files:**
- Create: `codex_config.py`
- Create: `tests/test_codex_config.py`
- Modify: `windows_portable.py:135-170` only if a shared validation helper needs to be exported without changing its behavior

**Interfaces:**
- Produces `ProviderConfig`, `ProviderMenuConfig`, `ModelCatalog`, and `ConfigPaths` typed records.
- `ConfigPaths` contains `codex_home`, `config_toml`, `provider_menu`, `model_catalog`, `settings`, and `backup_dir` paths.
- Produces `default_config_paths(codex_home: Optional[Path] = None) -> ConfigPaths`.
- Produces `validate_provider_menu(data: dict[str, Any], configured_provider_ids: set[str]) -> None`.
- Produces `validate_model_catalog(data: dict[str, Any]) -> None`.
- Produces `validate_provider_record(provider: dict[str, Any]) -> None`.

- [ ] **Step 1: Write failing validation tests**

```python
class ConfigValidationTests(unittest.TestCase):
    def test_default_paths_are_under_codex_home(self):
        paths = default_config_paths(Path(r"C:\\Users\\Test\\.codex"))
        self.assertEqual(paths.config_toml, Path(r"C:\\Users\\Test\\.codex\\config.toml"))
        self.assertEqual(paths.provider_menu, Path(r"C:\\Users\\Test\\.codex\\desktop-model-providers.json"))
        self.assertEqual(paths.model_catalog, Path(r"C:\\Users\\Test\\.codex\\model-catalogs\\custom.json"))

    def test_provider_menu_rejects_mapping_to_unknown_provider(self):
        with self.assertRaisesRegex(PatchError, "unknown provider"):
            validate_provider_menu({
                "version": 1,
                "default_provider": "openai",
                "providers": [{"id": "openai", "label": "OpenAI", "description": ""}],
                "model_providers": {"model-x": "missing"},
            }, {"openai"})

    def test_model_catalog_requires_models_array(self):
        with self.assertRaisesRegex(PatchError, "models"):
            validate_model_catalog({})
```

Run: `python -m unittest tests.test_codex_config -v`

Expected: the new test module fails to import the new interfaces.

- [ ] **Step 2: Implement the contracts and validators**

Use `dataclass` records and keep validation independent of Tkinter. Reuse the existing provider-menu schema rules from `windows_portable.py` through a shared helper or a direct import that does not create a cycle. Validate provider IDs, labels, default provider, mapping targets, catalog `models`, unique model slugs, and each model's required `slug`, `display_name`, and `description`.

- [ ] **Step 3: Run the focused tests**

Run: `python -m unittest tests.test_codex_config -v`

Expected: PASS.

- [ ] **Step 4: Commit the configuration contracts**

```powershell
git add codex_config.py tests/test_codex_config.py
git commit -m "Add provider and model configuration contracts"
```

### Task 2: Add safe JSON, backup, and settings persistence

**Files:**
- Modify: `codex_config.py`
- Modify: `tests/test_codex_config.py`

**Interfaces:**
- Produces `load_json(path: Path, default: Optional[dict[str, Any]] = None) -> dict[str, Any]`.
- Produces `backup_file(path: Path, backup_dir: Path) -> Optional[Path]`.
- Produces `atomic_write_json(path: Path, data: dict[str, Any], backup_dir: Optional[Path] = None) -> Optional[Path]`.
- Produces `load_gui_settings(path: Path) -> dict[str, Any]` and `save_gui_settings(path: Path, settings: dict[str, Any]) -> None`.
- Produces `SaveResult` with `provider_menu: Path`, `model_catalog: Path`, `config_toml: Path`, and `backups: tuple[Path, ...]` fields for the later bundle-save task.

- [ ] **Step 1: Write failing tests for backup and atomic replacement**

```python
class PersistenceTests(unittest.TestCase):
    def test_atomic_json_write_keeps_original_in_timestamped_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            target = tmp_path / "desktop-model-providers.json"
            target.write_text('{"version": 1}\n', encoding="utf-8")
            backup = atomic_write_json(target, {"version": 1, "changed": True}, tmp_path / "backups")
            self.assertIsNotNone(backup)
            self.assertEqual(backup.read_text(encoding="utf-8"), '{"version": 1}\n')
            self.assertTrue(json.loads(target.read_text(encoding="utf-8"))["changed"])

    def test_gui_settings_never_persist_secret_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            save_gui_settings(settings_path, {"portable_root": "D:\\Apps", "api_key": "secret"})
            saved = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(saved, {"portable_root": "D:\\Apps"})
```

Run: `python -m unittest tests.test_codex_config -v`

Expected: FAIL because the safe persistence functions do not exist.

- [ ] **Step 2: Implement safe persistence**

Use a temporary file in the destination directory, flush and `fsync`, then `os.replace`. Back up an existing target before replacement. Filter settings through an allowlist containing only `portable_root`, `codex_home`, `provider_menu`, `config_toml`, `model_catalog`, and `backup_dir`; reject secret-looking keys rather than serializing them.

- [ ] **Step 3: Run focused and regression tests**

Run: `python -m unittest tests.test_codex_config tests.test_windows_portable -v`

Expected: PASS.

- [ ] **Step 4: Commit safe persistence**

```powershell
git add codex_config.py tests/test_codex_config.py
git commit -m "Add atomic configuration persistence and backups"
```

### Task 3: Implement targeted TOML provider and catalog settings updates

**Files:**
- Modify: `codex_config.py`
- Modify: `tests/test_codex_config.py`

**Interfaces:**
- Produces `read_managed_toml_config(path: Path) -> dict[str, Any]`.
- Produces `write_codex_config(path: Path, root_updates: dict[str, Any], providers: list[dict[str, Any]], backup_dir: Optional[Path] = None) -> Optional[Path]`.
- Produces `serialize_toml_string(value: str) -> str`.
- Produces `provider_toml_section(provider_id: str) -> str`.

- [ ] **Step 1: Write failing TOML preservation tests**

```python
class TomlWriterTests(unittest.TestCase):
    def test_toml_update_preserves_unrelated_settings_and_comments(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            config = tmp_path / "config.toml"
            config.write_text(
                '# Keep this comment\nmodel = "gpt-5.6"\n\n'
                '[features]\nexperimental = true\n\n'
                '[model_providers.old]\nname = "Old"\nbase_url = "http://old"\n',
                encoding="utf-8",
            )
            write_codex_config(config, {"model_catalog_json": str(tmp_path / "models.json")}, [{
                "id": "openrouter", "name": "OpenRouter",
                "base_url": "https://openrouter.ai/api/v1", "wire_api": "responses",
                "auth_mode": "environment", "env_key": "OPENROUTER_API_KEY",
            }])
            text = config.read_text(encoding="utf-8")
            self.assertIn('# Keep this comment', text)
            self.assertIn('model = "gpt-5.6"', text)
            self.assertIn('[features]', text)
            self.assertIn('experimental = true', text)
            self.assertIn('[model_providers.openrouter]', text)
            self.assertIn('env_key = "OPENROUTER_API_KEY"', text)

    def test_plaintext_mode_serializes_experimental_bearer_token(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.toml"
            write_codex_config(config, {}, [{
                "id": "custom", "name": "Custom",
                "base_url": "https://example.test/v1", "wire_api": "responses",
                "auth_mode": "plaintext", "token": "secret-token",
            }])
            text = config.read_text(encoding="utf-8")
            self.assertIn('experimental_bearer_token = "secret-token"', text)
            self.assertNotIn('env_key =', text)
```

Run: `python -m unittest tests.test_codex_config -v`

Expected: FAIL because TOML read/write functions are not implemented.

- [ ] **Step 2: Implement the targeted writer**

Parse managed provider sections with `tomllib` when available and a section-aware fallback for Python 3.9. Replace only managed root keys and provider authentication keys, preserve unrelated lines and unknown provider options, quote provider IDs containing TOML punctuation, and append missing sections at EOF. Remove the opposite auth key when switching modes. Never log the token value.

- [ ] **Step 3: Run tests, including a Python 3.9-compatible syntax check**

Run: `python -m unittest tests.test_codex_config -v` and `python -m py_compile codex_config.py`

Expected: PASS.

- [ ] **Step 4: Commit TOML support**

```powershell
git add codex_config.py tests/test_codex_config.py
git commit -m "Add safe targeted Codex TOML updates"
```

### Task 4: Add environment-variable and credential-mode handling

**Files:**
- Modify: `codex_config.py`
- Modify: `tests/test_codex_config.py`

**Interfaces:**
- Produces `set_user_environment_variable(name: str, value: str, registry_writer: Optional[Callable] = None) -> None`.
- Produces `apply_environment_credential(provider: dict[str, Any]) -> None`.
- Produces `credential_summary(provider: dict[str, Any]) -> str`.
- Produces `validate_credential_mode(provider: dict[str, Any]) -> None`.

- [ ] **Step 1: Write failing tests**

```python
class CredentialTests(unittest.TestCase):
    def test_environment_mode_sets_env_key_without_exposing_secret(self):
        calls = []
        with unittest.mock.patch.object(
            codex_config, "_write_user_environment",
            side_effect=lambda name, value: calls.append((name, value)),
        ):
            provider = {"auth_mode": "environment", "env_key": "CUSTOM_API_KEY", "token": "secret"}
            codex_config.apply_environment_credential(provider)
        self.assertEqual(calls, [("CUSTOM_API_KEY", "secret")])
        self.assertEqual(codex_config.credential_summary(provider), "environment variable CUSTOM_API_KEY")
        self.assertNotIn("secret", codex_config.credential_summary(provider))

    def test_plaintext_mode_requires_token(self):
        with self.assertRaises(PatchError):
            validate_credential_mode({"auth_mode": "plaintext", "token": ""})
```

Run: `python -m unittest tests.test_codex_config -v`

Expected: FAIL because credential handling is not implemented.

- [ ] **Step 2: Implement Windows-user environment persistence**

Use `winreg.HKEY_CURRENT_USER\\Environment` on Windows, set `os.environ` for the running GUI process, and broadcast `WM_SETTINGCHANGE` when the API is available. Keep a non-Windows test adapter so unit tests never modify the host environment. Validate variable names with `[A-Za-z_][A-Za-z0-9_]*`. Do not place secret values in return values, log messages, or exceptions.

- [ ] **Step 3: Run focused tests**

Run: `python -m unittest tests.test_codex_config -v`

Expected: PASS.

- [ ] **Step 4: Commit credential handling**

```powershell
git add codex_config.py tests/test_codex_config.py
git commit -m "Add selectable Codex credential modes"
```

### Task 5: Add model catalog and provider-menu editing operations

**Files:**
- Modify: `codex_config.py`
- Modify: `tests/test_codex_config.py`

**Interfaces:**
- Produces `load_provider_menu(path: Path) -> dict[str, Any]`.
- Produces `load_model_catalog(path: Path) -> dict[str, Any]`.
- Produces `clone_model_template(catalog: dict[str, Any], template_slug: str, new_slug: str, display_name: str, description: str) -> dict[str, Any]`.
- Produces `upsert_model(catalog: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]`.
- Produces `remove_model(catalog: dict[str, Any], slug: str) -> dict[str, Any]`.
- Produces `build_provider_menu(providers: list[dict[str, Any]], default_provider: str, mappings: dict[str, str]) -> dict[str, Any]`.
- Produces `seed_catalog_from_codex(codex_executable: str = "codex") -> dict[str, Any]`.

- [ ] **Step 1: Write failing catalog and menu tests**

```python
class CatalogMenuTests(unittest.TestCase):
    def test_clone_model_template_preserves_advanced_metadata(self):
        catalog = {"models": [{
            "slug": "template",
            "display_name": "Template",
            "description": "Template description",
            "supported_reasoning_levels": [{"effort": "medium", "description": "Balanced"}],
            "visibility": "list",
        }]}
        result = clone_model_template(catalog, "template", "provider/model", "Provider Model", "Custom model")
        self.assertEqual(result["slug"], "provider/model")
        self.assertEqual(result["display_name"], "Provider Model")
        self.assertEqual(result["supported_reasoning_levels"], catalog["models"][0]["supported_reasoning_levels"])

    def test_provider_menu_builder_maps_models_to_existing_provider(self):
        result = build_provider_menu(
            [{"id": "openai", "label": "OpenAI", "description": ""},
             {"id": "custom", "label": "Custom", "description": ""}],
            "openai",
            {"provider/model": "custom"},
        )
        self.assertEqual(result["default_provider"], "openai")
        self.assertEqual(result["model_providers"], {"provider/model": "custom"})
```

Run: `python -m unittest tests.test_codex_config -v`

Expected: FAIL because catalog/menu operations are not implemented.

- [ ] **Step 2: Implement catalog/menu operations**

Clone with `copy.deepcopy`, replace only basic fields, and preserve unknown fields. For an absent catalog, run `codex debug models --bundled`, parse the single JSON document, and raise a user-facing `PatchError` if the executable is missing or the output is invalid. Keep provider-menu credentials-free and reuse its version-1 schema.

- [ ] **Step 3: Run focused tests**

Run: `python -m unittest tests.test_codex_config -v`

Expected: PASS.

- [ ] **Step 4: Commit catalog/menu operations**

```powershell
git add codex_config.py tests/test_codex_config.py
git commit -m "Add model catalog and provider menu editing"
```

### Task 6: Build the classic GUI editor pages

**Files:**
- Modify: `patch_chatgpt_providers_windows_gui.py`
- Modify: `tests/test_windows_gui.py`

**Interfaces:**
- Produces `build_classic_ui_spec()` entries for `Setup`, `Models`, and `Provider menu` pages.
- Produces GUI methods `_load_configuration`, `_save_configuration`, `_validate_configuration`, `_add_provider`, `_edit_provider`, `_remove_provider`, `_add_model`, `_edit_model`, `_remove_model`, and `_update_provider_mapping`.
- Consumes the typed operations from `codex_config.py` and sends all writes through the background worker.

- [ ] **Step 1: Write failing display-free GUI contract tests**

```python
class GuiSpecTests(unittest.TestCase):
    def test_gui_spec_contains_configuration_pages(self):
        spec = build_classic_ui_spec()
        self.assertEqual(spec["pages"], ("Setup", "Models", "Provider menu"))
        self.assertEqual(spec["actions"], ("LOAD", "SAVE", "VALIDATE", "CHECK ONLY", "PATCH"))

    def test_gui_spec_explains_plaintext_warning(self):
        spec = build_classic_ui_spec()
        self.assertIn("plaintext", spec["plaintext_warning"].lower())
```

Run: `python -m unittest tests.test_windows_gui -v`

Expected: FAIL because the existing classic spec has no editor pages or actions.

- [ ] **Step 2: Implement the compact editor shell**

Keep the reference-inspired gray utility styling and use three classic page-selector buttons that switch a single content frame between `Setup`, `Models`, and `Provider menu`. Add Codex home and three file path controls under an advanced location section. Add a list plus editor fields on each page. Use masked token fields, a mode selector, explicit plaintext confirmation, and disabled actions while a worker is active. Keep the activity log and status bar.

- [ ] **Step 3: Implement provider and model form behavior**

Populate provider and model lists from loaded configuration. Validate required fields before adding/updating. Keep model mappings synchronized with provider IDs and expose template selection for new models. Make the default provider a dropdown populated from providers.

- [ ] **Step 4: Run focused GUI tests and compile**

Run: `python -m unittest tests.test_windows_gui -v` and `python -m py_compile patch_chatgpt_providers_windows_gui.py`

Expected: PASS. Do not require a display server for these tests.

- [ ] **Step 5: Commit the editor shell**

```powershell
git add patch_chatgpt_providers_windows_gui.py tests/test_windows_gui.py
git commit -m "Add GUI provider and model editor pages"
```

### Task 7: Wire load/save/validate into the existing patch workflow

**Files:**
- Modify: `patch_chatgpt_providers_windows_gui.py`
- Modify: `tests/test_windows_gui.py`
- Modify: `README.md`

**Interfaces:**
- Produces `codex_config.save_configuration_bundle(bundle: ConfigBundle) -> SaveResult`.
- Produces worker actions `load`, `save`, `validate`, `check`, and `patch` with redacted log messages.

- [ ] **Step 1: Write failing integration tests**

```python
class ConfigurationIntegrationTests(unittest.TestCase):
    def test_configuration_save_writes_menu_catalog_and_toml(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = default_config_paths(Path(directory) / ".codex")
            bundle = ConfigBundle(
                paths=paths,
                providers=[{
                    "id": "custom", "name": "Custom", "label": "Custom",
                    "description": "", "base_url": "https://example.test/v1",
                    "wire_api": "responses", "auth_mode": "environment",
                    "env_key": "CUSTOM_API_KEY", "token": "",
                }],
                provider_menu={
                    "version": 1, "default_provider": "custom",
                    "providers": [{"id": "custom", "label": "Custom", "description": ""}],
                    "model_providers": {"custom/model": "custom"},
                },
                model_catalog={"models": [{
                    "slug": "custom/model", "display_name": "Custom Model", "description": "",
                }]},
                root_updates={"model_catalog_json": str(paths.model_catalog)},
            )
            result = save_configuration_bundle(bundle)
            self.assertEqual(result.provider_menu, paths.provider_menu)
            self.assertEqual(json.loads(paths.provider_menu.read_text(encoding="utf-8"))["default_provider"], "custom")
            self.assertEqual(json.loads(paths.model_catalog.read_text(encoding="utf-8"))["models"][0]["slug"], "custom/model")
            self.assertIn('model_catalog_json =', paths.config_toml.read_text(encoding="utf-8"))

    def test_secret_is_absent_from_configuration_log_message(self):
        line = format_log_line("OK", credential_summary({"auth_mode": "plaintext", "token": "secret"}))
        self.assertNotIn("secret", line)
```

Run: `python -m unittest tests.test_codex_config tests.test_windows_gui -v`

Expected: FAIL because the bundle save service and GUI actions are not connected.

- [ ] **Step 2: Implement configuration bundle save**

Validate provider records, menu mappings, catalog, authentication modes, and file paths as one preflight. Back up and atomically write TOML, catalog, and provider menu. Stop on configuration failure before invoking `patch_portable_app`.

- [ ] **Step 3: Wire GUI worker actions**

`LOAD` reads the files and updates controls on the UI thread. `SAVE` calls the bundle writer and reports paths without secrets. `VALIDATE` performs preflight only. `CHECK ONLY` calls the existing portable check. `PATCH` saves and validates first, then calls the existing `patch_portable_app` with its default process guard. Preserve the plaintext confirmation dialog and archive confirmation dialog.

- [ ] **Step 4: Update documentation for GUI-only setup**

Rewrite the manual sections in `README.md` as optional schema/reference material. Add a short first-run workflow: launch the `.bat`, choose portable root, configure provider/auth/model/menu in the GUI, click Save, click Check Only, close portable ChatGPT, then click Patch. Explain the restart requirement for environment variables and the plaintext warning.

- [ ] **Step 5: Run integration tests**

Run: `python -m unittest tests.test_codex_config tests.test_windows_gui tests.test_windows_portable -v`

Expected: PASS with no secret values in output.

- [ ] **Step 6: Commit workflow integration**

```powershell
git add codex_config.py patch_chatgpt_providers_windows_gui.py tests/test_codex_config.py tests/test_windows_gui.py README.md
git commit -m "Connect GUI configuration to portable patch workflow"
```

### Task 8: End-to-end verification and handoff

**Files:**
- Modify: `docs/superpowers/plans/2026-09-16-user-friendly-configurator.md`
- Inspect: `launch_windows_portable_patcher.bat`, `README.md`, and all modified Python files

- [ ] **Step 1: Run the complete test suite and syntax checks**

```powershell
python -m unittest discover -s tests -v
python -m py_compile codex_config.py windows_portable.py patch_chatgpt_providers_windows.py patch_chatgpt_providers_windows_gui.py tests\test_codex_config.py tests\test_windows_portable.py tests\test_windows_gui.py
python patch_chatgpt_providers_windows_gui.py --help
git diff --check
```

Expected: all tests pass, all commands exit successfully, and `git diff --check` reports no whitespace errors.

- [ ] **Step 2: Run the real portable check without patching**

```powershell
python patch_chatgpt_providers_windows.py --app-root "..\\ChatGPT-x64-portable-20260916" --check-only
```

Expected: the layout and current ASAR markers are compatible; no archive or installed package is changed.

- [ ] **Step 3: Review secret-handling and process safety**

Search the diff with `rg -n "token|api_key|env_key|experimental_bearer_token|ChatGPT\.exe|Popen|Start-Process"` and confirm tokens appear only in serializer/test fixtures, the GUI field handling, and redacted mode summaries. Confirm the GUI never launches ChatGPT and the patch path still checks for running portable processes.

- [ ] **Step 4: Mark completed plan steps and report handoff**

Update the checkboxes only after the corresponding verification has passed. Report the launcher path, first-run GUI workflow, backup behavior, credential-mode limitation, and complete test result.
