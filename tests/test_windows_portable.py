import tempfile
import unittest
import hashlib
import json
import zipfile
from pathlib import Path
from unittest import mock

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


class PortableDownloadTests(unittest.TestCase):
    def test_download_streams_the_official_msix_to_a_temporary_file(self):
        from windows_download import PORTABLE_DOWNLOAD_URL, download_msix

        class FakeResponse:
            headers = {"Content-Length": "11"}

            def __init__(self):
                self.chunks = [b"hello ", b"world", b""]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, _size):
                return self.chunks.pop(0)

        with tempfile.TemporaryDirectory() as temp:
            with mock.patch(
                "windows_download.urllib.request.urlopen",
                return_value=FakeResponse(),
            ) as opener:
                package = download_msix(Path(temp))

            self.assertEqual(package.read_bytes(), b"hello world")
            request = opener.call_args.args[0]
            self.assertEqual(request.full_url, PORTABLE_DOWNLOAD_URL)
            package.unlink()

    def test_extracts_msix_zip_into_a_portable_folder(self):
        from windows_download import extract_msix

        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            msix = workspace / "ChatGPT-x64.msix"
            with zipfile.ZipFile(msix, "w") as archive:
                archive.writestr("app/ChatGPT.exe", b"MZ")
                archive.writestr("app/resources/app.asar", b"asar")
                archive.writestr("app/resources/app.asar.unpacked/", b"")

            portable_root = extract_msix(msix, workspace)

            self.assertEqual(portable_root.name, "ChatGPT-x64-portable")
            self.assertEqual((portable_root / "app/ChatGPT.exe").read_bytes(), b"MZ")
            self.assertTrue((portable_root / "app/resources/app.asar.unpacked").is_dir())

    def test_rejects_zip_slip_entries_before_extracting(self):
        from windows_download import DownloadError, extract_msix

        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            msix = workspace / "malicious.msix"
            with zipfile.ZipFile(msix, "w") as archive:
                archive.writestr("../outside.txt", b"must not escape")

            with self.assertRaises(DownloadError):
                extract_msix(msix, workspace)

            self.assertFalse((workspace.parent / "outside.txt").exists())

    def test_rejects_a_valid_zip_without_a_portable_chatgpt_layout(self):
        from windows_download import DownloadError, extract_msix

        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            msix = workspace / "not-chatgpt.msix"
            with zipfile.ZipFile(msix, "w") as archive:
                archive.writestr("readme.txt", b"not a portable app")

            with self.assertRaises(DownloadError):
                extract_msix(msix, workspace)

            self.assertFalse((workspace / "ChatGPT-x64-portable").exists())


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

    def test_process_scan_suppresses_the_powershell_window(self):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(
                portable.subprocess,
                "run",
                return_value=mock.Mock(stdout="[]"),
            ) as run:
                portable.find_windows_app_processes(Path(temp) / "portable")

            self.assertEqual(
                run.call_args.kwargs["creationflags"],
                getattr(portable.subprocess, "CREATE_NO_WINDOW", 0),
            )

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

    def test_restore_uses_the_latest_portable_backup_and_preserves_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "portable"
            resources = root / "app" / "resources"
            resources.mkdir(parents=True)
            (root / "app" / "ChatGPT.exe").write_bytes(b"MZ")
            asar = resources / "app.asar"
            asar.write_bytes(b"patched")
            (resources / "app.asar.unpacked").mkdir()
            app = locate_portable_app(root)
            backups = Path(temp) / "backups"
            backups.mkdir()
            older = backups / "ChatGPT-portable-app-20260101-010101.asar"
            latest = backups / "ChatGPT-portable-app-20260102-010101.asar"
            older.write_bytes(b"older original")
            latest.write_bytes(b"latest original")
            (backups / "unrelated.asar").write_bytes(b"must not restore")

            restored = portable.restore_portable_asar(app, backups)

            self.assertEqual(restored, latest)
            self.assertEqual(asar.read_bytes(), b"latest original")
            self.assertEqual(latest.read_bytes(), b"latest original")

    def test_restore_requires_a_matching_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "portable"
            resources = root / "app" / "resources"
            resources.mkdir(parents=True)
            (root / "app" / "ChatGPT.exe").write_bytes(b"MZ")
            asar = resources / "app.asar"
            asar.write_bytes(b"patched")
            (resources / "app.asar.unpacked").mkdir()
            app = locate_portable_app(root)

            with self.assertRaises(PatchError):
                portable.restore_portable_asar(app, Path(temp) / "empty-backups")

            self.assertEqual(asar.read_bytes(), b"patched")

    def test_restore_selects_the_later_suffix_when_backups_share_a_timestamp(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "portable"
            resources = root / "app" / "resources"
            resources.mkdir(parents=True)
            (root / "app" / "ChatGPT.exe").write_bytes(b"MZ")
            asar = resources / "app.asar"
            asar.write_bytes(b"patched")
            (resources / "app.asar.unpacked").mkdir()
            app = locate_portable_app(root)
            backups = Path(temp) / "backups"
            backups.mkdir()
            first = backups / "ChatGPT-portable-app-20260103-010101.asar"
            later = backups / "ChatGPT-portable-app-20260103-010101-1.asar"
            first.write_bytes(b"first original")
            later.write_bytes(b"later original")

            restored = portable.restore_portable_asar(app, backups)

            self.assertEqual(restored, later)
            self.assertEqual(asar.read_bytes(), b"later original")


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

    def test_patch_only_mode_does_not_prepare_or_write_provider_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "portable"
            resources = root / "app" / "resources"
            resources.mkdir(parents=True)
            executable = root / "app" / "ChatGPT.exe"
            executable.write_bytes(b"MZ")
            asar = resources / "app.asar"
            asar.write_bytes(b"archive")
            unpacked = resources / "app.asar.unpacked"
            unpacked.mkdir()
            app = portable.PortableApp(root, executable, resources, asar, unpacked)
            backup = Path(temp) / "backups" / "app.asar.orig"
            config = Path(temp) / "desktop-model-providers.json"

            with mock.patch.object(portable, "_extract_target_sources", return_value=(
                {}, 0, "central.js", "picker.js", b"central", b"picker"
            )), mock.patch.object(portable, "_patch_central_source", return_value="central-patched"), mock.patch.object(
                portable, "_patch_picker_source", return_value="picker-patched"
            ), mock.patch.object(portable, "backup_portable_asar", return_value=backup), mock.patch.object(
                portable, "rebuild_asar_with_replacements"
            ), mock.patch.object(
                portable, "_atomic_replace"
            ), mock.patch.object(portable, "ensure_provider_config") as ensure:
                portable.patch_portable_app(app, config, backup.parent, create_config=False)

            ensure.assert_not_called()
            self.assertFalse(config.exists())


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
