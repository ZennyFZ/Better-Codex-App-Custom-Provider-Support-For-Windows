"""Portable patching backend for the Windows ChatGPT GUI.

It never installs an AppX package, changes an AppX signature, or starts
ChatGPT.exe.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
from typing import Any, NamedTuple, Optional, Union


PATCH_MARKER = b"__codexDesktopModelProvidersPatchV3"
LEGACY_PATCH_MARKER = b"__codexDesktopModelProvidersPatchV2"
ASAR_BLOCK_SIZE = 4 * 1024 * 1024


class PatchError(RuntimeError):
    """A safe, user-actionable patching failure."""


class PortableApp(NamedTuple):
    root: Path
    executable: Path
    resources: Path
    asar: Path
    unpacked: Path




# The current Windows build (26.903.8094.0) uses fD for the app IPC request
# helper in app-initial and ew in app-primary.  These are intentionally kept
# as exact runtime source blocks and are guarded by the surrounding markers.
CURRENT_CENTRAL_JS = r'''
function codexProviderRoutingFallback(){return{version:1,defaultProvider:`openai`,providers:[{id:`openai`,label:`ChatGPT / OpenAI`,description:`Uses your signed-in ChatGPT account`},{id:`openrouter`,label:`OpenRouter`,description:`Uses the OpenRouter provider from config.toml`}],modelProviders:{"moonshotai/kimi-k3":`openrouter`,"x-ai/grok-4.5":`openrouter`,"anthropic/claude-fable-5":`openrouter`}}}
function codexNormalizeProviderRoutingConfig(e){if(e==null||typeof e!==`object`||Array.isArray(e))throw Error(`Expected a JSON object`);if(e.version!==1)throw Error(`Unsupported version`);if(!Array.isArray(e.providers)||e.providers.length===0)throw Error(`providers must be a non-empty array`);let t=[],n=new Set;for(let r of e.providers){if(r==null||typeof r!==`object`||Array.isArray(r))throw Error(`Every provider must be an object`);let e=typeof r.id===`string`?r.id.trim():``;if(e.length===0||n.has(e))throw Error(`Provider ids must be unique non-empty strings`);n.add(e);let i=typeof r.label===`string`?r.label.trim():``;t.push({id:e,label:i.length>0?i:e,description:typeof r.description===`string`?r.description.trim():``})}let r=typeof e.default_provider===`string`?e.default_provider.trim():``;if(!n.has(r))throw Error(`default_provider must reference a configured provider`);let i={};if(e.model_providers==null||typeof e.model_providers!==`object`||Array.isArray(e.model_providers))throw Error(`model_providers must be an object`);for(let[t,r]of Object.entries(e.model_providers)){let e=t.trim();if(e.length===0||typeof r!==`string`||!n.has(r))throw Error(`Every model mapping must reference a configured provider`);i[e]=r}return{version:1,defaultProvider:r,providers:t,modelProviders:i}}
function codexProviderRoutingState(){return(window.__codexDesktopModelProvidersPatchV3??={config:codexProviderRoutingFallback(),configPath:null,error:null,loaded:!1,promise:null})}
async function codexLoadProviderRoutingConfig(e=!1){let t=codexProviderRoutingState();if(!e&&t.loaded)return t.config;if(t.promise!=null)return t.promise;return(t.promise=(async()=>{try{let{codexHome:e}=await fD(`codex-home`,{params:{hostId:`local`}}),n=e.includes(`\\`)&&!e.includes(`/`)?`\\`:`/`,r=`${e.replace(/[\\/]+$/u,``)}${n}desktop-model-providers.json`,{contents:i}=await fD(`read-file`,{params:{hostId:`local`,path:r}}),a=codexNormalizeProviderRoutingConfig(JSON.parse(i));return t.config=a,t.configPath=r,t.error=null,t.loaded=!0,a}catch(e){return t.config=codexProviderRoutingFallback(),t.error=e instanceof Error?e.message:String(e),t.loaded=!0,t.config}finally{t.promise=null}})(),t.promise)}
function codexCustomProviderChoice(e){try{let t=window.localStorage.getItem(`codex.customProviderSelection.v1`);return t===`auto`||e.providers.some(e=>e.id===t)?t:`auto`}catch{return`auto`}}
async function codexProviderForThreadStart(e){let t=await codexLoadProviderRoutingConfig(!0),n=codexCustomProviderChoice(t);return n===`auto`?(t.modelProviders[e?.model]??t.defaultProvider):n}
async function codexPatchAppServerParams(e,t){if(e===`thread/list`){let e=t!=null&&typeof t===`object`?t:{};return e.modelProviders==null?{...e,modelProviders:[]}:e}return e===`thread/start`&&t!=null&&typeof t===`object`?t.modelProvider==null?{...t,modelProvider:await codexProviderForThreadStart(t)}:t:t}
'''


CURRENT_PICKER_JS = r'''
function codexPickerProviderRoutingFallback(){return{version:1,defaultProvider:`openai`,providers:[{id:`openai`,label:`ChatGPT / OpenAI`,description:`Uses your signed-in ChatGPT account`},{id:`openrouter`,label:`OpenRouter`,description:`Uses the OpenRouter provider from config.toml`}],modelProviders:{"moonshotai/kimi-k3":`openrouter`,"x-ai/grok-4.5":`openrouter`,"anthropic/claude-fable-5":`openrouter`}}}
function codexPickerNormalizeProviderRoutingConfig(e){if(e==null||typeof e!==`object`||Array.isArray(e))throw Error(`Expected a JSON object`);if(e.version!==1)throw Error(`Unsupported version`);if(!Array.isArray(e.providers)||e.providers.length===0)throw Error(`providers must be a non-empty array`);let t=[],n=new Set;for(let r of e.providers){if(r==null||typeof r!==`object`||Array.isArray(r))throw Error(`Every provider must be an object`);let e=typeof r.id===`string`?r.id.trim():``;if(e.length===0||n.has(e))throw Error(`Provider ids must be unique non-empty strings`);n.add(e);let i=typeof r.label===`string`?r.label.trim():``;t.push({id:e,label:i.length>0?i:e,description:typeof r.description===`string`?r.description.trim():``})}let r=typeof e.default_provider===`string`?e.default_provider.trim():``;if(!n.has(r))throw Error(`default_provider must reference a configured provider`);let i={};if(e.model_providers==null||typeof e.model_providers!==`object`||Array.isArray(e.model_providers))throw Error(`model_providers must be an object`);for(let[t,r]of Object.entries(e.model_providers)){let e=t.trim();if(e.length===0||typeof r!==`string`||!n.has(r))throw Error(`Every model mapping must reference a configured provider`);i[e]=r}return{version:1,defaultProvider:r,providers:t,modelProviders:i}}
function codexPickerProviderRoutingState(){return(window.__codexDesktopModelProvidersPatchV3??={config:codexPickerProviderRoutingFallback(),configPath:null,error:null,loaded:!1,promise:null})}
async function codexPickerLoadProviderRoutingConfig(e=!1){let t=codexPickerProviderRoutingState();if(!e&&t.loaded)return t.config;if(t.promise!=null)return t.promise;return(t.promise=(async()=>{try{let{codexHome:e}=await ew(`codex-home`,{params:{hostId:`local`}}),n=e.includes(`\\`)&&!e.includes(`/`)?`\\`:`/`,r=`${e.replace(/[\\/]+$/u,``)}${n}desktop-model-providers.json`;t.configPath=r;let{contents:i}=await ew(`read-file`,{params:{hostId:`local`,path:r}}),a=codexPickerNormalizeProviderRoutingConfig(JSON.parse(i));return t.config=a,t.error=null,t.loaded=!0,a}catch(e){return t.config=codexPickerProviderRoutingFallback(),t.error=e instanceof Error?e.message:String(e),t.loaded=!0,t.config}finally{t.promise=null}})(),t.promise)}
function codexReadCustomProviderChoice(e){try{let t=window.localStorage.getItem(`codex.customProviderSelection.v1`);return t===`auto`||e.providers.some(e=>e.id===t)?t:`auto`}catch{return`auto`}}
function codexWriteCustomProviderChoice(e){try{window.localStorage.setItem(`codex.customProviderSelection.v1`,e)}catch{}}
function CodexCustomProviderPickerSection(){let e=codexPickerProviderRoutingState(),[t,n]=P6.useState(e.config),[r,i]=P6.useState(e.error),[a,o]=P6.useState(()=>codexReadCustomProviderChoice(e.config));P6.useEffect(()=>{let e=!0;return codexPickerLoadProviderRoutingConfig(!0).then(r=>{e&&(n(r),i(codexPickerProviderRoutingState().error),o(e=>e===`auto`||r.providers.some(t=>t.id===e)?e:`auto`))}),()=>{e=!1}},[]);let s=e=>t=>(t?.preventDefault(),codexWriteCustomProviderChoice(e),o(e)),c=t.providers.find(e=>e.id===t.defaultProvider)?.label??t.defaultProvider,l=t.providers.map(e=>(0,b7.jsx)(of.Item,{RightIcon:a===e.id?JT:void 0,SubText:e.description.length===0?null:(0,b7.jsx)(`span`,{className:`text-token-description-foreground`,children:e.description}),onSelect:s(e.id),children:e.label},e.id));return(0,b7.jsxs)(b7.Fragment,{children:[(0,b7.jsx)(of.Title,{children:`Provider for new tasks`}),r==null?null:(0,b7.jsx)(of.Item,{disabled:!0,SubText:(0,b7.jsx)(`span`,{className:`text-token-description-foreground`,children:r}),children:`Provider config error — using fallback`}),(0,b7.jsx)(of.Item,{RightIcon:a===`auto`?JT:void 0,SubText:(0,b7.jsx)(`span`,{className:`text-token-description-foreground`,children:`Uses the mapped provider for each model; ${c} when unmapped`}),onSelect:s(`auto`),children:`Automatic`}),l,(0,b7.jsx)(of.Separator,{})]})}
'''


def locate_portable_app(root: Path) -> PortableApp:
    """Locate the extracted MSIX root without accepting an archive file."""

    candidate = Path(root).expanduser()
    if candidate.is_file() or candidate.suffix.lower() in {".msix", ".zip"}:
        raise PatchError(
            f"Expected an extracted portable folder, not an archive: {candidate}"
        )
    if not candidate.exists() or not candidate.is_dir():
        raise PatchError(f"Portable root does not exist or is not a folder: {candidate}")
    candidate = candidate.resolve()

    layouts = [
        (candidate / "app", candidate),
        (candidate, candidate),
    ]
    for app_dir, reported_root in layouts:
        executable = app_dir / "ChatGPT.exe"
        resources = app_dir / "resources"
        asar = resources / "app.asar"
        unpacked = resources / "app.asar.unpacked"
        if executable.is_file() and asar.is_file():
            app = PortableApp(reported_root, executable, resources, asar, unpacked)
            validate_portable_layout(app)
            return app

    raise PatchError(
        f"Not a supported extracted ChatGPT layout: {candidate}. "
        "Expected <root>\\app\\ChatGPT.exe and <root>\\app\\resources\\app.asar."
    )


def validate_portable_layout(app: PortableApp) -> None:
    if not app.root.is_dir():
        raise PatchError(f"Portable root is not a folder: {app.root}")
    if not app.executable.is_file():
        raise PatchError(f"Missing portable ChatGPT executable: {app.executable}")
    if app.executable.suffix.lower() != ".exe":
        raise PatchError(f"Portable target is not a Windows executable: {app.executable}")
    if not app.asar.is_file():
        raise PatchError(f"Missing ASAR archive: {app.asar}")
    if not app.unpacked.is_dir():
        raise PatchError(f"Missing ASAR companion directory: {app.unpacked}")




def _portable_path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False))).rstrip("\\/")


def _path_is_under(path: Path, root: Path) -> bool:
    path_key = _portable_path_key(path)
    root_key = _portable_path_key(root)
    return path_key == root_key or path_key.startswith(root_key + os.sep)


def parse_windows_processes(payload: Union[str, bytes]) -> list[tuple[int, str, str]]:
    """Parse ConvertTo-Json output as (pid, executable, command line)."""

    try:
        value = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise PatchError(f"Could not parse the Windows process list: {exc}") from exc
    if value is None:
        return []
    records = value if isinstance(value, list) else [value]
    parsed: list[tuple[int, str, str]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            pid = int(record.get("ProcessId"))
        except (TypeError, ValueError):
            continue
        executable = record.get("ExecutablePath")
        command_line = record.get("CommandLine")
        if isinstance(executable, str) and executable:
            parsed.append((pid, executable, command_line if isinstance(command_line, str) else ""))
    return parsed


def find_windows_app_processes(root: Path) -> list[tuple[int, str]]:
    """Find processes whose executable is inside this portable root.

    The function only reports exact executable paths below the selected root;
    it never terminates a process and never matches by a broad process name.
    """

    command = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ExecutablePath,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PatchError(f"Could not inspect Windows processes: {exc}") from exc

    selected_root = Path(root).expanduser().resolve()
    matches: list[tuple[int, str]] = []
    for pid, executable, command_line in parse_windows_processes(result.stdout):
        if pid == os.getpid():
            continue
        executable_path = Path(executable)
        if _path_is_under(executable_path, selected_root):
            detail = executable if not command_line else f"{executable} {command_line}"
            matches.append((pid, detail))
    return matches


def backup_portable_asar(app: PortableApp, backup_dir: Path) -> Path:
    validate_portable_layout(app)
    backup_dir = Path(backup_dir).expanduser()
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = backup_dir / f"ChatGPT-portable-app-{stamp}.asar"
    suffix = 1
    while backup.exists():
        backup = backup_dir / f"ChatGPT-portable-app-{stamp}-{suffix}.asar"
        suffix += 1
    shutil.copy2(app.asar, backup)
    if backup.stat().st_size != app.asar.stat().st_size:
        raise PatchError(f"ASAR backup verification failed: {backup}")
    if _sha256_file(backup) != _sha256_file(app.asar):
        raise PatchError(f"ASAR backup checksum verification failed: {backup}")
    return backup


def latest_portable_asar_backup(backup_dir: Path) -> Path:
    """Return the newest backup created by ``backup_portable_asar``."""
    directory = Path(backup_dir).expanduser()
    if not directory.is_dir():
        raise PatchError(f"Backup directory does not exist: {directory}")
    pattern = re.compile(
        r"ChatGPT-portable-app-(\d{8}-\d{6})(?:-(\d+))?\.asar\Z",
        re.IGNORECASE,
    )
    backups = []
    for path in directory.glob("ChatGPT-portable-app-*.asar"):
        match = pattern.fullmatch(path.name)
        if path.is_file() and match:
            backups.append((match.group(1), int(match.group(2) or 0), path))
    if not backups:
        raise PatchError(
            f"No portable ASAR backup was found in: {directory}"
        )
    return max(backups, key=lambda item: (item[0], item[1]))[2]


def restore_portable_asar(app: PortableApp, backup_dir: Path) -> Path:
    """Restore the newest original ASAR backup without deleting any backup."""
    validate_portable_layout(app)
    backup = latest_portable_asar_backup(backup_dir)
    _atomic_replace(backup, app.asar)
    if _sha256_file(backup) != _sha256_file(app.asar):
        raise PatchError(f"Restored ASAR checksum verification failed: {app.asar}")
    return backup


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_asar_header(path: Path) -> tuple[dict[str, Any], int, int, bytes]:
    try:
        with path.open("rb") as handle:
            prefix = handle.read(8)
            if len(prefix) != 8:
                raise PatchError("ASAR archive is too short to contain a header")
            size_payload, header_size = struct.unpack("<II", prefix)
            if size_payload != 4 or header_size < 8:
                raise PatchError("ASAR archive has an invalid header-size pickle")
            header_pickle = handle.read(header_size)
            if len(header_pickle) != header_size:
                raise PatchError("ASAR archive contains a truncated header")
    except OSError as exc:
        raise PatchError(f"Cannot read ASAR header from {path}: {exc}") from exc

    payload_size, string_size = struct.unpack("<II", header_pickle[:8])
    if payload_size > header_size - 4 or string_size > header_size - 8:
        raise PatchError("ASAR header pickle has invalid payload sizes")
    raw_json = header_pickle[8 : 8 + string_size]
    try:
        header = json.loads(raw_json.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PatchError(f"ASAR header does not contain valid UTF-8 JSON: {exc}") from exc
    if not isinstance(header, dict) or not isinstance(header.get("files"), dict):
        raise PatchError("ASAR header does not contain a files tree")
    return header, header_size, 8 + header_size, raw_json


def asar_header_hash(path: Path) -> str:
    _header, _size, _base, raw_json = _read_asar_header(path)
    return hashlib.sha256(raw_json).hexdigest()


def _walk_asar_files(node: dict[str, Any], prefix: str = ""):
    for name, entry in node.items():
        path = f"{prefix}{name}"
        if not isinstance(entry, dict):
            raise PatchError(f"ASAR header has an invalid entry: {path}")
        children = entry.get("files")
        if isinstance(children, dict):
            yield from _walk_asar_files(children, f"{path}/")
        else:
            yield path, entry


def _asar_entry(header: dict[str, Any], path: str) -> dict[str, Any]:
    node: Any = header["files"]
    for part in path.split("/"):
        if not isinstance(node, dict) or part not in node:
            raise PatchError(f"ASAR entry is missing: {path}")
        node = node[part]
        if isinstance(node, dict) and "files" in node:
            node = node["files"]
    if not isinstance(node, dict) or "files" in node:
        raise PatchError(f"ASAR entry is not a file: {path}")
    return node


def _asar_integrity(data: bytes, block_size: int = ASAR_BLOCK_SIZE) -> dict[str, Any]:
    return {
        "algorithm": "SHA256",
        "hash": hashlib.sha256(data).hexdigest(),
        "blockSize": block_size,
        "blocks": [
            hashlib.sha256(data[start : start + block_size]).hexdigest()
            for start in range(0, len(data), block_size)
        ]
        or [hashlib.sha256(b"").hexdigest()],
    }


def _read_asar_file(
    archive: Path,
    data_base: int,
    entry: dict[str, Any],
) -> bytes:
    if entry.get("unpacked"):
        raise PatchError("The requested ASAR file is unpacked and has no archive bytes")
    try:
        offset = int(entry["offset"])
        size = int(entry["size"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PatchError("ASAR file entry has an invalid offset or size") from exc
    if offset < 0 or size < 0:
        raise PatchError("ASAR file entry has a negative offset or size")
    with archive.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        archive_size = handle.tell()
        if data_base + offset + size > archive_size:
            raise PatchError("ASAR file entry points beyond the end of the archive")
        handle.seek(data_base + offset)
        value = handle.read(size)
    if len(value) != size:
        raise PatchError("ASAR file entry is truncated")
    return value


def _asar_header_pickle(header: dict[str, Any]) -> bytes:
    raw_json = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    string_payload = struct.pack("<I", len(raw_json)) + raw_json
    string_payload += b"\0" * ((-len(string_payload)) % 4)
    header_pickle = struct.pack("<I", len(string_payload)) + string_payload
    return struct.pack("<II", 4, len(header_pickle)) + header_pickle


def _copy_range(source, target, start: int, size: int) -> None:
    source.seek(start)
    remaining = size
    while remaining:
        chunk = source.read(min(4 * 1024 * 1024, remaining))
        if not chunk:
            raise PatchError("ASAR archive ended while copying packed file data")
        target.write(chunk)
        remaining -= len(chunk)


def rebuild_asar_with_replacements(
    archive: Path,
    replacements: dict[str, bytes],
    output: Path,
) -> None:
    """Rebuild only the packed ASAR stream, preserving unpacked companions."""

    header, _header_size, data_base, _raw_json = _read_asar_header(archive)
    updated_header = copy.deepcopy(header)
    entries: list[tuple[str, dict[str, Any], dict[str, Any], Optional[bytes]]] = []
    packed_offset = 0
    for path, original_entry in _walk_asar_files(header["files"]):
        updated_entry = _asar_entry(updated_header, path)
        if original_entry.get("unpacked") or "link" in original_entry:
            continue
        replacement = replacements.get(path)
        if replacement is not None:
            updated_entry["size"] = len(replacement)
            if "integrity" in original_entry:
                block_size = int(original_entry["integrity"].get("blockSize", ASAR_BLOCK_SIZE))
                updated_entry["integrity"] = _asar_integrity(replacement, block_size)
        else:
            try:
                original_size = int(original_entry["size"])
            except (KeyError, TypeError, ValueError) as exc:
                raise PatchError(f"ASAR entry has an invalid size: {path}") from exc
            if original_size < 0:
                raise PatchError(f"ASAR entry has a negative size: {path}")
        updated_entry["offset"] = str(packed_offset)
        size = len(replacement) if replacement is not None else int(original_entry["size"])
        entries.append((path, original_entry, updated_entry, replacement))
        packed_offset += size

    header_pickle = _asar_header_pickle(updated_header)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp-{os.getpid()}")
    if temporary.exists():
        temporary.unlink()
    try:
        with archive.open("rb") as source, temporary.open("wb") as target:
            target.write(header_pickle)
            for path, original_entry, _updated_entry, replacement in entries:
                if replacement is not None:
                    target.write(replacement)
                    continue
                _copy_range(source, target, data_base + int(original_entry["offset"]), int(original_entry["size"]))
            target.flush()
            os.fsync(target.fileno())
        # A second parse and byte check catches malformed pickle/header offsets
        # before the caller replaces the user's archive.
        check_header, _size, check_base, _raw = _read_asar_header(temporary)
        for path, _original_entry, updated_entry, replacement in entries:
            if replacement is None:
                continue
            actual = _read_asar_file(temporary, check_base, _asar_entry(check_header, path))
            if actual != replacement:
                raise PatchError(f"ASAR replacement verification failed: {path}")
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()


def _replace_once(source: str, pattern: str, replacement: str, label: str) -> str:
    rendered, count = re.subn(pattern, replacement, source, count=1, flags=re.DOTALL)
    if count != 1:
        raise PatchError(f"Current build marker not found exactly once: {label}")
    return rendered


def _patch_central_source(source: str) -> str:
    if PATCH_MARKER.decode() in source or LEGACY_PATCH_MARKER.decode() in source:
        raise PatchError("The app-server bundle already contains an older provider patch")
    marker = re.compile(r"function ZCn\s*\(\s*e\s*,\s*t\s*,\s*n\s*\)")
    matches = list(marker.finditer(source))
    if len(matches) != 1:
        raise PatchError("Current app-server bundle marker is unsupported")
    source = source[: matches[0].start()] + CURRENT_CENTRAL_JS + source[matches[0].start() :]
    dispatch_check = r"async sendRequest\(e\s*,\s*t\s*,\s*n\s*\)\s*\{\s*if\s*\(\s*this\.dispatchMessage\s*==\s*null\s*\)\s*throw\s*Error\(\s*`AppServerRequestClient is missing a message dispatcher`\s*,?\s*\)\s*;?"
    source = _replace_once(
        source,
        dispatch_check,
        r"\g<0>t=await codexPatchAppServerParams(e,t);",
        "app-server sendRequest",
    )
    prewarm_check = r"async prewarmThreadStart\(e\s*,\s*t\s*\)\s*\{\s*if\s*\(\s*this\.dispatchMessage\s*==\s*null\s*\)\s*throw\s*Error\(\s*`AppServerRequestClient is missing a message dispatcher`\s*,?\s*\)\s*;?"
    source = _replace_once(
        source,
        prewarm_check,
        r"\g<0>e=await codexPatchAppServerParams(`thread/start`,e);",
        "app-server prewarmThreadStart",
    )
    return source


def _patch_picker_source(source: str) -> str:
    if PATCH_MARKER.decode() in source or LEGACY_PATCH_MARKER.decode() in source:
        raise PatchError("The model-picker bundle already contains an older provider patch")
    marker = re.compile(r"function ZKr\s*\(\s*e\s*\)")
    matches = list(marker.finditer(source))
    if len(matches) != 1:
        raise PatchError("Current model-picker bundle marker is unsupported")
    source = source[: matches[0].start()] + CURRENT_PICKER_JS + source[matches[0].start() :]
    source = _replace_once(
        source,
        r"let\s+H\s*=\s*V\s*,\s*te\s*;",
        "let H=(0,b7.jsx)(b7.Fragment,{children:[(0,b7.jsx)(CodexCustomProviderPickerSection,{}),V]}),te;",
        "model-picker beforeModels",
    )
    return source


def select_current_bundle_assets(assets: Path) -> tuple[Path, Path]:
    assets = Path(assets)
    if not assets.is_dir():
        raise PatchError(f"JavaScript asset directory does not exist: {assets}")
    candidates = sorted(path for path in assets.glob("*.js") if not path.name.endswith(".map.js"))
    central = [
        path
        for path in candidates
        if re.search(r"async sendRequest\s*\(\s*e\s*,\s*t\s*,\s*n\s*\)", path.read_text(encoding="utf-8"))
        and "async prewarmThreadStart" in path.read_text(encoding="utf-8")
        and "AppServerRequestClient is missing a message dispatcher" in path.read_text(encoding="utf-8")
    ]
    picker = [
        path
        for path in candidates
        if "function ZKr(e)" in path.read_text(encoding="utf-8")
        and "composer.intelligenceDropdown.tooltip" in path.read_text(encoding="utf-8")
        and "modelOptionsDisabled" in path.read_text(encoding="utf-8")
    ]
    if len(central) != 1 or len(picker) != 1:
        raise PatchError(
            "Expected exactly one current app-server and model-picker bundle; "
            f"found central={len(central)}, picker={len(picker)}"
        )
    return central[0], picker[0]


def patch_current_bundle_sources(central: Path, picker: Path) -> None:
    central = Path(central)
    picker = Path(picker)
    original_central = central.read_text(encoding="utf-8")
    original_picker = picker.read_text(encoding="utf-8")
    patched_central = _patch_central_source(original_central)
    patched_picker = _patch_picker_source(original_picker)
    central.write_text(patched_central, encoding="utf-8")
    try:
        picker.write_text(patched_picker, encoding="utf-8")
    except Exception:
        central.write_text(original_central, encoding="utf-8")
        raise


def _extract_target_sources(archive: Path) -> tuple[dict[str, Any], int, str, str, bytes, bytes]:
    header, _header_size, data_base, _raw_json = _read_asar_header(archive)
    matches: list[tuple[str, bytes]] = []
    for path, entry in _walk_asar_files(header["files"]):
        if entry.get("unpacked") or not path.startswith("webview/assets/") or not path.endswith(".js"):
            continue
        data = _read_asar_file(archive, data_base, entry)
        if re.search(rb"async sendRequest\s*\(\s*e\s*,\s*t\s*,\s*n\s*\)", data) and b"async prewarmThreadStart" in data and b"AppServerRequestClient is missing a message dispatcher" in data:
            matches.append((path, data))
    if len(matches) != 1:
        raise PatchError(f"Expected one current app-server bundle in ASAR, found {len(matches)}")
    central_path, central = matches[0]
    picker_matches: list[tuple[str, bytes]] = []
    for path, entry in _walk_asar_files(header["files"]):
        if entry.get("unpacked") or not path.startswith("webview/assets/") or not path.endswith(".js"):
            continue
        data = _read_asar_file(archive, data_base, entry)
        if b"function ZKr(e)" in data and b"composer.intelligenceDropdown.tooltip" in data and b"modelOptionsDisabled" in data:
            picker_matches.append((path, data))
    if len(picker_matches) != 1:
        raise PatchError(f"Expected one current model-picker bundle in ASAR, found {len(picker_matches)}")
    picker_path, picker = picker_matches[0]
    return header, data_base, central_path, picker_path, central, picker


def _atomic_replace(source: Path, target: Path) -> None:
    temporary = target.with_name(f".{target.name}.replace-{os.getpid()}")
    try:
        shutil.copyfile(source, temporary)
        shutil.copystat(target, temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def patch_portable_app(
    app: PortableApp,
    backup_dir: Path,
    allow_running: bool = False,
    check_only: bool = False,
) -> Optional[Path]:
    """Validate and patch a portable app; return the original ASAR backup."""

    validate_portable_layout(app)
    running = find_windows_app_processes(app.root)
    if running and not allow_running:
        detail = "; ".join(f"PID {pid}: {command}" for pid, command in running)
        raise PatchError(
            "The portable ChatGPT app is running. Close it before patching, "
            f"then retry. Detected: {detail}"
        )

    _header, _data_base, central_path, picker_path, central, picker = _extract_target_sources(app.asar)
    if PATCH_MARKER in central or PATCH_MARKER in picker:
        raise PatchError("This portable app already has the current provider patch")
    if LEGACY_PATCH_MARKER in central or LEGACY_PATCH_MARKER in picker:
        raise PatchError("An older provider patch is present; portable upgrade is not supported")
    patched_central = _patch_central_source(central.decode("utf-8"))
    patched_picker = _patch_picker_source(picker.decode("utf-8"))
    if check_only:
        return None

    backup = backup_portable_asar(app, Path(backup_dir).expanduser())
    temporary_archive = app.asar.with_name(f".{app.asar.name}.patched-{os.getpid()}")
    try:
        rebuild_asar_with_replacements(
            app.asar,
            {
                central_path: patched_central.encode("utf-8"),
                picker_path: patched_picker.encode("utf-8"),
            },
            temporary_archive,
        )
        _atomic_replace(temporary_archive, app.asar)
    except Exception:
        if temporary_archive.exists():
            temporary_archive.unlink()
        raise
    return backup
