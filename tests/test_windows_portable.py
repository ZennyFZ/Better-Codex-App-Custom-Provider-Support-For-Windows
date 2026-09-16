import tempfile
import unittest
import hashlib
import json
from pathlib import Path

import windows_portable as portable
from windows_portable import PatchError, locate_portable_app


class PortableLayoutTests(unittest.TestCase):
    def make_layout(self, root: Path, include_unpacked: bool = True) -> Path:
        resources = root / "app" / "resources"
        resources.mkdir(parents=True)
        (root / "app" / "ChatGPT.exe").write_bytes(b"MZ")
        (root / "app" / "Codex.exe").write_bytes(b"MZ")
        (resources / "app.asar").write_bytes(b"asar")
        if include_unpacked:
            (resources / "app.asar.unpacked").mkdir()
        return root

    def test_locates_app_resources_and_executable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.make_layout(Path(temp) / "portable")

            app = locate_portable_app(root)

            self.assertEqual(app.root, root)
            self.assertEqual(app.executable, root / "app" / "ChatGPT.exe")
            self.assertEqual(app.asar, root / "app" / "resources" / "app.asar")
            self.assertTrue(app.unpacked.is_dir())

    def test_rejects_msix_file_as_portable_root(self):
        with tempfile.TemporaryDirectory() as temp:
            msix = Path(temp) / "ChatGPT-x64.msix"
            msix.write_bytes(b"not a directory")

            with self.assertRaises(PatchError):
                locate_portable_app(msix)

    def test_requires_unpacked_companion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.make_layout(Path(temp) / "portable", include_unpacked=False)

            with self.assertRaises(PatchError):
                locate_portable_app(root)


class ProcessAndBackupTests(unittest.TestCase):
    def test_process_parser_accepts_single_record_and_skips_incomplete_rows(self):
        payload = json.dumps(
            {
                "ProcessId": 42,
                "ExecutablePath": r"D:\Apps\ChatGPT-portable\app\ChatGPT.exe",
                "CommandLine": '"D:\\Apps\\ChatGPT-portable\\app\\ChatGPT.exe"',
            }
        )

        self.assertEqual(
            portable.parse_windows_processes(payload),
            [
                (
                    42,
                    r"D:\Apps\ChatGPT-portable\app\ChatGPT.exe",
                    '"D:\\Apps\\ChatGPT-portable\\app\\ChatGPT.exe"',
                )
            ],
        )
        self.assertEqual(portable.parse_windows_processes('[{"ProcessId": null}]'), [])

    def test_backup_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "portable"
            resources = root / "app" / "resources"
            resources.mkdir(parents=True)
            (root / "app" / "ChatGPT.exe").write_bytes(b"MZ")
            asar = resources / "app.asar"
            asar.write_bytes(b"original archive")
            (resources / "app.asar.unpacked").mkdir()
            app = locate_portable_app(root)

            backup = portable.backup_portable_asar(app, Path(temp) / "backups")

            self.assertEqual(backup.read_bytes(), asar.read_bytes())
            self.assertEqual(hashlib.sha256(backup.read_bytes()).digest(), hashlib.sha256(asar.read_bytes()).digest())


class CurrentBuildPatchTests(unittest.TestCase):
    def make_sources(self, directory: Path) -> tuple[Path, Path]:
        central = directory / "app-initial.js"
        picker = directory / "app-primary.js"
        central.write_text(
            "function ZCn(e,t,n){}\n"
            "async sendRequest(e,t,n){if(this.dispatchMessage==null)throw Error(`AppServerRequestClient is missing a message dispatcher`);return e===`config/read`?t:n}\n"
            "async prewarmThreadStart(e,t){if(this.dispatchMessage==null)throw Error(`AppServerRequestClient is missing a message dispatcher`);return e}\n",
            encoding="utf-8",
        )
        picker.write_text(
            "function ZKr(e){let H=V,te;} composer.intelligenceDropdown.tooltip modelOptionsDisabled",
            encoding="utf-8",
        )
        return central, picker

    def test_selects_current_bundles_and_patches_request_and_picker(self):
        with tempfile.TemporaryDirectory() as temp:
            assets = Path(temp)
            central, picker = self.make_sources(assets)

            self.assertEqual(portable.select_current_bundle_assets(assets), (central, picker))
            portable.patch_current_bundle_sources(central, picker)

            central_text = central.read_text(encoding="utf-8")
            picker_text = picker.read_text(encoding="utf-8")
            self.assertIn(portable.PATCH_MARKER.decode(), central_text)
            self.assertIn(portable.PATCH_MARKER.decode(), picker_text)
            self.assertIn("codexPatchAppServerParams", central_text)
            self.assertIn("CodexCustomProviderPickerSection", picker_text)
            self.assertEqual(central_text.count("t=await codexPatchAppServerParams(e,t);"), 1)
            self.assertEqual(picker_text.count("let H=(0,b7.jsx)"), 1)

    def test_duplicate_current_bundle_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            assets = Path(temp)
            central, picker = self.make_sources(assets)
            (assets / "duplicate.js").write_text(central.read_text(encoding="utf-8"), encoding="utf-8")

            with self.assertRaises(PatchError):
                portable.select_current_bundle_assets(assets)

    def test_unsupported_sources_are_not_modified(self):
        with tempfile.TemporaryDirectory() as temp:
            central, picker = self.make_sources(Path(temp))
            central.write_text("unsupported", encoding="utf-8")
            original_picker = picker.read_bytes()

            with self.assertRaises(PatchError):
                portable.patch_current_bundle_sources(central, picker)

            self.assertEqual(central.read_bytes(), b"unsupported")
            self.assertEqual(picker.read_bytes(), original_picker)


class AsarRebuildTests(unittest.TestCase):
    def write_fixture(self, path: Path) -> tuple[str, str, bytes]:
        central_path = "webview/assets/app-initial.js"
        picker_path = "webview/assets/app-primary.js"
        external_path = "node_modules/native.node"
        central = b"central-original"
        picker = b"picker-original"
        external = b"external-native"
        header = {
            "files": {
                "webview": {
                    "files": {
                        "assets": {
                            "files": {
                                "app-initial.js": {"size": len(central), "offset": "0"},
                                "app-primary.js": {"size": len(picker), "offset": str(len(central))},
                            }
                        }
                    }
                },
                "node_modules": {
                    "files": {
                        "native.node": {
                            "size": len(external),
                            "unpacked": True,
                            "integrity": {"algorithm": "SHA256", "hash": "unused"},
                        }
                    }
                },
            }
        }
        path.write_bytes(portable._asar_header_pickle(header) + central + picker)
        return central_path, picker_path, external

    def test_rebuild_preserves_unpacked_entries_and_replaces_packed_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "app.asar"
            target = Path(temp) / "patched.asar"
            central_path, picker_path, external = self.write_fixture(source)
            unpacked = source.with_name("app.asar.unpacked") / "node_modules"
            unpacked.mkdir(parents=True)
            external_path = unpacked / "native.node"
            external_path.write_bytes(external)
            external_before = external_path.read_bytes()

            portable.rebuild_asar_with_replacements(
                source,
                {central_path: b"central-patched", picker_path: b"picker-patched"},
                target,
            )

            header, _size, base, _raw = portable._read_asar_header(target)
            self.assertEqual(
                portable._read_asar_file(target, base, portable._asar_entry(header, central_path)),
                b"central-patched",
            )
            self.assertEqual(
                portable._read_asar_file(target, base, portable._asar_entry(header, picker_path)),
                b"picker-patched",
            )
            self.assertEqual(external_path.read_bytes(), external_before)
            self.assertTrue(portable._asar_entry(header, "node_modules/native.node").get("unpacked"))


class CliTests(unittest.TestCase):
    def test_help_exposes_portable_root_and_check_only(self):
        with self.assertRaises(SystemExit) as raised:
            portable.build_parser().parse_args(["--help"])
        self.assertEqual(raised.exception.code, 0)

        help_text = portable.build_parser().format_help()
        self.assertIn("--app-root", help_text)
        self.assertIn("--check-only", help_text)


if __name__ == "__main__":
    unittest.main()
