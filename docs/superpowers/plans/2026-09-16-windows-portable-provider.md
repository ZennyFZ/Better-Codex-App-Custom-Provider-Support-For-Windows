# Windows Portable Custom Provider Implementation Plan

**Goal:** Add a safe Windows portable patcher that modifies an extracted ChatGPT MSIX folder without installing or re-signing the MSIX package.

**Architecture:** Keep the existing macOS patcher unchanged in its normal path. Add a focused Windows module that locates `app\\resources\\app.asar`, patches the two current JavaScript entries directly from the ASAR header, preserves the sibling `app.asar.unpacked` directory, and atomically replaces only the portable archive after validation. The provider-routing runtime code remains the existing embedded JavaScript behavior, while Windows-specific process, backup, path, and archive handling live in the new module.

**Tech Stack:** Python 3.9+, standard-library `unittest`, a standard-library ASAR header/stream rebuilder, and PowerShell test fixtures from the downloaded MSIX.

**Spec:** The approved in-chat design: portable root contains `app\\ChatGPT.exe` and `app\\resources\\app.asar`; no MSIX installation, AppX signature mutation, or `Info.plist` handling.

## Global Constraints

- Never call `Add-AppxPackage`, `winget install`, `msiexec`, or launch `ChatGPT.exe` during tests.
- Never modify the installed WindowsApps package or the original MSIX; patch only a user-selected extracted directory.
- Refuse unsupported or already-patched bundles before replacing `app.asar`.
- Preserve `app\\resources\\app.asar.unpacked` and fail closed if required external files cannot be preserved.
- Keep provider API keys out of the desktop provider JSON; document Windows-compatible `env_key` authentication.

---

### Task 1: Add failing tests for portable layout and safe archive targeting

**Files:**
- Create: `tests/test_windows_portable.py`
- Test fixture input: `work/ChatGPT-x64-portable-20260916`

**Interfaces:**
- Consumes: `windows_portable.PortableApp`, `windows_portable.locate_portable_app`, and `windows_portable.validate_portable_layout`.
- Produces: executable assertions for portable root detection, ASAR path resolution, rejection of an MSIX file path, and preservation of `app.asar.unpacked`.

- [x] **Step 1: Write the failing tests**

```python
class PortableLayoutTests(unittest.TestCase):
    def test_locates_app_resources_and_executable(self):
        app = locate_portable_app(self.fixture_root)
        self.assertEqual(app.executable, self.fixture_root / "app" / "ChatGPT.exe")
        self.assertEqual(app.asar, self.fixture_root / "app" / "resources" / "app.asar")
        self.assertTrue(app.unpacked.is_dir())

    def test_rejects_msix_file_as_portable_root(self):
        with self.assertRaises(PatchError):
            locate_portable_app(self.fixture_root / ".." / "outputs" / "ChatGPT-x64.msix")

    def test_layout_validation_requires_unpacked_companion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "portable"
            (root / "app" / "resources").mkdir(parents=True)
            (root / "app" / "ChatGPT.exe").write_bytes(b"MZ")
            (root / "app" / "resources" / "app.asar").write_bytes(b"asar")
            with self.assertRaises(PatchError):
                locate_portable_app(root)
```

- [x] **Step 2: Run the focused tests to verify they fail for the expected missing-module reason**

Run: `python -m unittest tests.test_windows_portable -v`

Expected: FAIL with `ModuleNotFoundError` or missing `windows_portable`, before any app mutation occurs.

### Task 2: Implement portable layout, backups, and process safety

**Files:**
- Create: `windows_portable.py`
- Test: `tests/test_windows_portable.py`

**Interfaces:**
- `class PortableApp(NamedTuple): root: Path; executable: Path; resources: Path; asar: Path; unpacked: Path`
- `locate_portable_app(root: Path) -> PortableApp`
- `validate_portable_layout(app: PortableApp) -> None`
- `backup_portable_asar(app: PortableApp, backup_dir: Path) -> Path`
- `find_windows_app_processes(root: Path) -> list[tuple[int, str]]`

- [x] **Step 1: Implement the smallest layout validator that satisfies Task 1**
- [x] **Step 2: Run `python -m unittest tests.test_windows_portable -v` and confirm all layout tests pass**
- [x] **Step 3: Add tests for backup byte identity and process matching using a pure data parser**
- [x] **Step 4: Implement timestamped backup and Windows process-query parsing without broad process termination**
- [x] **Step 5: Run the focused suite again and confirm zero failures**

### Task 3: Add current-build JavaScript patching with fail-closed matching

**Files:**
- Modify: `windows_portable.py`
- Test: `tests/test_windows_portable.py`
- Fixture source: `work/downloaded-app-asar-20260916/webview/assets/app-initial-92cbfeba4f7c.js`
- Fixture source: `work/downloaded-app-asar-20260916/webview/assets/app-primary-4d9eebe1ede1.js`

**Interfaces:**
- `select_current_bundle_assets(assets: Path) -> tuple[Path, Path]`
- `patch_current_bundle_sources(central: Path, picker: Path) -> None`
- `PATCH_MARKER: bytes`

- [x] **Step 1: Write failing tests that select exactly one current central/picker bundle and reject duplicates**
- [x] **Step 2: Run the tests and confirm they fail because current-build patching is not implemented**
- [x] **Step 3: Add exact source-marker transformations for request routing and provider-picker insertion**
- [x] **Step 4: Add a test that patches copies of both downloaded bundles and asserts the marker, `thread/start`, `thread/list`, and picker symbols are present**
- [x] **Step 5: Add a test for an unsupported source copy and confirm it raises `PatchError` without changing bytes**
- [x] **Step 6: Run the focused suite and confirm all current-build patch tests pass**

### Task 4: Implement ASAR repackaging that preserves external files

**Files:**
- Modify: `windows_portable.py`
- Test: `tests/test_windows_portable.py`

**Interfaces:**
- `patch_portable_app(app: PortableApp, config: Path, backup_dir: Path, allow_running: bool = False) -> Path`
- `run_npx(args: Sequence[str], cwd: Path | None = None) -> None`

- [x] **Step 1: Write a failing integration-style test that runs against a copied portable fixture and expects a patched ASAR plus unchanged `app.asar.unpacked` file hashes**
- [x] **Step 2: Run it and confirm failure at the missing portable patch pipeline**
- [x] **Step 3: Implement a targeted ASAR header/stream rebuild, retaining the original unpacked companion tree and failing if packed entries cannot be reconstructed**
- [x] **Step 4: Validate the packed archive, backup the original, and atomically replace only `app.asar`**
- [x] **Step 5: Run the integration test and confirm the original MSIX and installed package remain untouched**

### Task 5: Add the Windows CLI and documentation

**Files:**
- Create: `patch_chatgpt_providers_windows.py`
- Modify: `README.md`
- Test: `tests/test_windows_portable.py`

**Interfaces:**
- CLI: `python patch_chatgpt_providers_windows.py --app-root <extracted-root> [--config <path>] [--backup-dir <path>] [--allow-running]`
- `--check-only` performs layout, bundle, and ASAR compatibility checks without replacing files.

- [x] **Step 1: Write a failing CLI help test and a check-only test**
- [x] **Step 2: Implement the thin CLI wrapper over `windows_portable.patch_portable_app`**
- [x] **Step 3: Document ZIP extraction, backup/recovery, Windows authentication options, and the no-install scope**
- [x] **Step 4: Run the CLI check-only flow against the downloaded extracted fixture**

### Task 6: Full verification and handoff

**Files:**
- Test: `tests/test_windows_portable.py`
- Verify: `patch_chatgpt_providers.py`, `windows_portable.py`, `patch_chatgpt_providers_windows.py`, `README.md`

- [x] **Step 1: Run `python -m unittest discover -s tests -v`**
- [x] **Step 2: Run `python -m py_compile patch_chatgpt_providers.py windows_portable.py patch_chatgpt_providers_windows.py`**
- [x] **Step 3: Run the CLI `--check-only` command against the portable fixture**
- [x] **Step 4: Verify the original MSIX SHA-256 and installed WindowsApps package timestamp/content are unchanged**
- [x] **Step 5: Review the worktree diff and report any limitations, including future bundle-version updates**
