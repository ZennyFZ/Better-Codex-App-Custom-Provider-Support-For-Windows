"""Safe, display-free configuration services for the Windows GUI."""

from __future__ import annotations

import copy
import datetime as dt
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from dataclasses import dataclass
import re
from typing import Any, Dict, Optional

try:
    import tomllib
except ImportError:  # pragma: no cover - exercised only on Python 3.9/3.10
    tomllib = None

from windows_portable import PatchError


ProviderConfig = Dict[str, Any]
ProviderMenuConfig = Dict[str, Any]
ModelCatalog = Dict[str, Any]

_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TOML_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_TOML_ASSIGNMENT = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*=")
_MANAGED_PROVIDER_FIELDS = {
    "name",
    "base_url",
    "wire_api",
    "env_key",
    "experimental_bearer_token",
}


@dataclass(frozen=True)
class ConfigPaths:
    codex_home: Path
    config_toml: Path
    provider_menu: Path
    model_catalog: Path
    settings: Path
    backup_dir: Path


@dataclass(frozen=True)
class SaveResult:
    provider_menu: Path
    model_catalog: Path
    config_toml: Path
    backups: tuple[Path, ...]


@dataclass
class ConfigBundle:
    paths: ConfigPaths
    providers: list[dict[str, Any]]
    provider_menu: ProviderMenuConfig
    model_catalog: ModelCatalog
    root_updates: dict[str, Any]


_GUI_SETTING_KEYS = {
    "portable_root",
    "codex_home",
    "provider_menu",
    "config_toml",
    "model_catalog",
    "backup_dir",
}


def default_config_paths(codex_home: Optional[Path] = None) -> ConfigPaths:
    home = Path(codex_home or os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    return ConfigPaths(
        codex_home=home,
        config_toml=home / "config.toml",
        provider_menu=home / "desktop-model-providers.json",
        model_catalog=home / "model-catalogs" / "custom.json",
        settings=Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        / "BetterCodexPortablePatcher"
        / "settings.json",
        backup_dir=home / "backups",
    )


def load_json(path: Path, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    candidate = Path(path).expanduser()
    if not candidate.exists():
        if default is None:
            raise PatchError(f"JSON file does not exist: {candidate}")
        return copy.deepcopy(default)
    try:
        value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PatchError(f"Cannot read valid JSON from {candidate}: {exc}") from exc
    if not isinstance(value, dict):
        raise PatchError(f"JSON root must be an object: {candidate}")
    return value


def backup_file(path: Path, backup_dir: Path) -> Optional[Path]:
    source = Path(path).expanduser()
    if not source.exists():
        return None
    destination_dir = Path(backup_dir).expanduser()
    destination_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination = destination_dir / f"{source.name}.bak-{stamp}"
    counter = 1
    while destination.exists():
        destination = destination_dir / f"{source.name}.bak-{stamp}-{counter}"
        counter += 1
    try:
        shutil.copy2(source, destination)
    except OSError as exc:
        raise PatchError(f"Cannot back up {source} to {destination}: {exc}") from exc
    return destination


def _atomic_write_text(path: Path, text: str) -> None:
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(
    path: Path,
    data: Dict[str, Any],
    backup_dir: Optional[Path] = None,
) -> Optional[Path]:
    destination = Path(path).expanduser()
    original_backup = backup_file(destination, backup_dir) if backup_dir is not None else None
    try:
        serialized = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        _atomic_write_text(destination, serialized)
    except (OSError, TypeError, ValueError) as exc:
        raise PatchError(f"Cannot write JSON to {destination}: {exc}") from exc
    return original_backup


def load_gui_settings(path: Path) -> Dict[str, Any]:
    return load_json(path, {})


def save_gui_settings(path: Path, settings: Dict[str, Any]) -> None:
    filtered = {
        key: value
        for key, value in settings.items()
        if key in _GUI_SETTING_KEYS and isinstance(value, (str, int, float, bool))
    }
    try:
        _atomic_write_text(
            Path(path).expanduser(),
            json.dumps(filtered, indent=2, ensure_ascii=False) + "\n",
        )
    except (OSError, TypeError, ValueError) as exc:
        raise PatchError(f"Cannot write GUI settings: {exc}") from exc


def serialize_toml_string(value: str) -> str:
    """Serialize a string as a TOML basic string without exposing its value."""

    if not isinstance(value, str):
        raise PatchError("TOML string values must be strings")
    return json.dumps(value, ensure_ascii=False)


def provider_toml_section(provider_id: str) -> str:
    """Return the table header for a model provider id."""

    provider_id = _require_non_empty_string(
        provider_id,
        "Provider id must be a non-empty string",
    )
    key = provider_id if _TOML_BARE_KEY.fullmatch(provider_id) else serialize_toml_string(provider_id)
    return f"[model_providers.{key}]"


def _without_line_ending(line: str) -> str:
    return line[:-2] if line.endswith("\r\n") else line[:-1] if line.endswith(("\r", "\n")) else line


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""


def _inline_comment_start(line: str) -> Optional[int]:
    raw = _without_line_ending(line)
    quote: Optional[str] = None
    escaped = False
    for index, character in enumerate(raw):
        if quote == '"':
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quote = None
            continue
        if quote == "'":
            if character == "'":
                quote = None
            continue
        if character in {'"', "'"}:
            quote = character
        elif character == "#" and (index == 0 or raw[index - 1].isspace()):
            return index
    return None


def _parse_provider_header(line: str) -> Optional[str]:
    raw = _without_line_ending(line).strip()
    match = re.match(r"^\[\s*model_providers\.(.*?)\s*\](?:\s*#.*)?$", raw)
    if not match or raw.startswith("[["):
        return None
    key = match.group(1).strip()
    if _TOML_BARE_KEY.fullmatch(key):
        return key
    if len(key) >= 2 and key[0] == key[-1] == "'":
        return key[1:-1]
    if len(key) >= 2 and key[0] == key[-1] == '"':
        try:
            decoded = json.loads(key)
        except json.JSONDecodeError:
            return None
        return decoded if isinstance(decoded, str) else None
    return None


def _is_table_header(line: str) -> bool:
    raw = _without_line_ending(line).strip()
    return bool(re.match(r"^(?:\[\[.*\]\]|\[.*\])(?:\s*#.*)?$", raw))


def _assignment_key(line: str) -> Optional[str]:
    match = _TOML_ASSIGNMENT.match(_without_line_ending(line))
    return match.group(1) if match else None


def _find_provider_sections(lines: list[str]) -> dict[str, tuple[int, int]]:
    boundaries = [index for index, line in enumerate(lines) if _is_table_header(line)]
    sections: dict[str, tuple[int, int]] = {}
    for position, start in enumerate(boundaries):
        provider_id = _parse_provider_header(lines[start])
        if provider_id is None or provider_id in sections:
            continue
        end = boundaries[position + 1] if position + 1 < len(boundaries) else len(lines)
        sections[provider_id] = (start, end)
    return sections


def _parse_toml_scalar(raw: str) -> Any:
    value = raw.strip()
    comment_index = _inline_comment_start(value)
    if comment_index is not None:
        value = value[:comment_index].rstrip()
    if value.startswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise PatchError(f"Invalid TOML string value: {exc}") from exc
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    if value == "true":
        return True
    if value == "false":
        return False
    try:
        return int(value.replace("_", ""))
    except ValueError:
        return value


def _fallback_read_managed_toml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    providers: dict[str, dict[str, Any]] = {}
    active_provider: Optional[str] = None
    for line in text.splitlines():
        provider_id = _parse_provider_header(line)
        if provider_id is not None:
            active_provider = provider_id
            providers.setdefault(provider_id, {})
            continue
        if _is_table_header(line):
            active_provider = None
            continue
        key = _assignment_key(line)
        if key is None:
            continue
        raw = _without_line_ending(line)
        equals = raw.find("=")
        if equals < 0:
            continue
        value = _parse_toml_scalar(raw[equals + 1 :])
        if active_provider is not None and key in _MANAGED_PROVIDER_FIELDS:
            providers[active_provider][key] = value
        elif active_provider is None and key in {"model_provider", "model_catalog_json"}:
            root[key] = value
    return {"root": root, "providers": providers}


def read_managed_toml_config(path: Path) -> dict[str, Any]:
    """Read the Codex root settings and model provider sections."""

    candidate = Path(path).expanduser()
    if not candidate.exists():
        return {"root": {}, "providers": {}}
    try:
        text = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PatchError(f"Cannot read TOML configuration {candidate}: {exc}") from exc

    if tomllib is None:
        return _fallback_read_managed_toml(text)
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PatchError(f"Cannot read valid TOML from {candidate}: {exc}") from exc
    root = {
        key: parsed[key]
        for key in ("model_provider", "model_catalog_json")
        if key in parsed
    }
    providers = parsed.get("model_providers", {})
    if not isinstance(providers, dict):
        raise PatchError("TOML model_providers must be a table")
    return {
        "root": root,
        "providers": {
            provider_id: dict(values)
            for provider_id, values in providers.items()
            if isinstance(values, dict)
        },
    }


def _serialize_toml_value(value: Any) -> str:
    if isinstance(value, str):
        return serialize_toml_string(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_serialize_toml_value(item) for item in value) + "]"
    raise PatchError("Unsupported TOML value in managed root settings")


def _replace_toml_assignment(line: str, key: str, serialized_value: str) -> str:
    raw = _without_line_ending(line)
    ending = _line_ending(line)
    match = re.match(r"^(\s*)[A-Za-z0-9_-]+\s*=", raw)
    indentation = match.group(1) if match else ""
    comment_index = _inline_comment_start(line)
    comment = raw[comment_index:] if comment_index is not None else ""
    suffix = f" {comment.lstrip()}" if comment else ""
    return f"{indentation}{key} = {serialized_value}{suffix}{ending}"


def _ensure_line_ending(lines: list[str], start: int, end: int) -> None:
    for index in range(end - 1, start - 1, -1):
        if lines[index]:
            if not _line_ending(lines[index]):
                lines[index] += "\n"
            return


def _provider_assignments(provider: dict[str, Any]) -> dict[str, str]:
    provider_id = _require_non_empty_string(
        provider.get("id"),
        "Every provider id must be a non-empty string",
    )
    del provider_id  # validation above also keeps this function explicit about its input contract
    assignments = {
        "name": serialize_toml_string(provider.get("name") or provider.get("label", "")),
        "base_url": serialize_toml_string(provider.get("base_url", "")),
        "wire_api": serialize_toml_string(provider.get("wire_api", "")),
    }
    auth_mode = provider.get("auth_mode", "none")
    if auth_mode == "environment":
        assignments["env_key"] = serialize_toml_string(provider["env_key"])
    elif auth_mode == "plaintext":
        assignments["experimental_bearer_token"] = serialize_toml_string(provider["token"])
    return assignments


def _update_provider_section(
    lines: list[str],
    start: int,
    end: int,
    assignments: dict[str, str],
) -> None:
    present: set[str] = set()
    for index in range(start + 1, end):
        key = _assignment_key(lines[index])
        if key in _MANAGED_PROVIDER_FIELDS:
            if key in assignments and key not in present:
                lines[index] = _replace_toml_assignment(lines[index], key, assignments[key])
                present.add(key)
            elif key not in assignments:
                lines[index] = ""
            else:
                lines[index] = ""
    missing = [key for key in assignments if key not in present]
    if missing:
        _ensure_line_ending(lines, start + 1, end)
        lines[end:end] = [f"{key} = {assignments[key]}\n" for key in missing]


def write_codex_config(
    path: Path,
    root_updates: dict[str, Any],
    providers: list[dict[str, Any]],
    backup_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Update managed Codex TOML keys while preserving unrelated text."""

    if not isinstance(root_updates, dict):
        raise PatchError("Managed TOML root updates must be an object")
    if not isinstance(providers, list):
        raise PatchError("Managed TOML providers must be an array")
    for provider in providers:
        if not isinstance(provider, dict):
            raise PatchError("Every provider must be an object")
        validation_record = dict(provider)
        validation_record.setdefault(
            "label",
            validation_record.get("name") or validation_record.get("id", ""),
        )
        validate_provider_record(validation_record)
    for key in root_updates:
        if not isinstance(key, str) or not _TOML_BARE_KEY.fullmatch(key):
            raise PatchError(f"Invalid managed TOML key: {key!r}")

    destination = Path(path).expanduser()
    if destination.exists():
        try:
            text = destination.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise PatchError(f"Cannot read TOML configuration {destination}: {exc}") from exc
    else:
        text = ""
    lines = text.splitlines(keepends=True)

    sections = _find_provider_sections(lines)
    desired_ids = {provider["id"] for provider in providers}
    for provider_id, (start, end) in sorted(sections.items(), key=lambda item: item[1][0], reverse=True):
        if provider_id not in desired_ids:
            del lines[start:end]

    first_header = next(
        (index for index, line in enumerate(lines) if _is_table_header(line)),
        len(lines),
    )
    missing_root: list[str] = []
    for key, value in root_updates.items():
        serialized = _serialize_toml_value(value)
        found = False
        for index in range(first_header):
            if _assignment_key(lines[index]) == key:
                lines[index] = _replace_toml_assignment(lines[index], key, serialized)
                found = True
        if not found:
            missing_root.append(f"{key} = {serialized}\n")
    if missing_root:
        if first_header > 0:
            _ensure_line_ending(lines, 0, first_header)
        lines[first_header:first_header] = missing_root

    for provider in providers:
        provider_id = provider["id"]
        assignments = _provider_assignments(provider)
        sections = _find_provider_sections(lines)
        section = sections.get(provider_id)
        if section is None:
            if lines and not _line_ending(lines[-1]):
                lines[-1] += "\n"
            if lines and lines[-1].strip():
                lines.append("\n")
            lines.append(provider_toml_section(provider_id) + "\n")
            lines.extend(f"{key} = {value}\n" for key, value in assignments.items())
        else:
            _update_provider_section(lines, section[0], section[1], assignments)

    serialized_text = "".join(lines)
    original_backup = backup_file(destination, backup_dir) if backup_dir is not None else None
    try:
        _atomic_write_text(destination, serialized_text)
    except OSError as exc:
        raise PatchError(f"Cannot write TOML configuration {destination}: {exc}") from exc
    return original_backup


def _require_non_empty_string(value: Any, message: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PatchError(message)
    return value.strip()


def validate_provider_record(provider: Dict[str, Any]) -> None:
    if not isinstance(provider, dict):
        raise PatchError("Every provider must be an object")
    provider_id = _require_non_empty_string(provider.get("id"), "Every provider id must be a non-empty string")
    _require_non_empty_string(
        provider.get("label"),
        f"Provider '{provider_id}' needs a non-empty label",
    )
    for field in ("description", "name", "base_url", "wire_api"):
        value = provider.get(field, "")
        if not isinstance(value, str):
            raise PatchError(f"Provider '{provider_id}' field '{field}' must be a string")

    auth_mode = provider.get("auth_mode", "none")
    if auth_mode not in {"none", "environment", "plaintext"}:
        raise PatchError(f"Provider '{provider_id}' has an unsupported authentication mode")
    if auth_mode == "environment":
        env_key = _require_non_empty_string(
            provider.get("env_key"),
            f"Provider '{provider_id}' needs an environment variable name",
        )
        if not _ENVIRONMENT_NAME.fullmatch(env_key):
            raise PatchError(f"Provider '{provider_id}' has an invalid environment variable name")
    if auth_mode == "plaintext":
        _require_non_empty_string(
            provider.get("token"),
            f"Provider '{provider_id}' needs a plaintext token",
        )


def validate_provider_menu(data: Dict[str, Any], configured_provider_ids: set[str]) -> None:
    if not isinstance(data, dict):
        raise PatchError("Provider menu must be a JSON object")
    if data.get("version") != 1:
        raise PatchError("Provider menu version must be 1")
    providers = data.get("providers")
    if not isinstance(providers, list) or not providers:
        raise PatchError("Provider menu 'providers' must be a non-empty array")

    provider_ids: set[str] = set()
    for provider in providers:
        if not isinstance(provider, dict):
            raise PatchError("Every menu provider must be an object")
        provider_id = _require_non_empty_string(
            provider.get("id"),
            "Every menu provider id must be a non-empty string",
        )
        if provider_id in provider_ids:
            raise PatchError(f"Duplicate menu provider id: {provider_id}")
        provider_ids.add(provider_id)
        _require_non_empty_string(
            provider.get("label"),
            f"Menu provider '{provider_id}' needs a non-empty label",
        )
        if not isinstance(provider.get("description", ""), str):
            raise PatchError(f"Menu provider '{provider_id}' description must be a string")
        if provider_id not in configured_provider_ids:
            raise PatchError(f"Menu provider '{provider_id}' has no configured provider")

    default_provider = _require_non_empty_string(
        data.get("default_provider"),
        "default_provider must reference a configured provider",
    )
    if default_provider not in provider_ids:
        raise PatchError("default_provider must reference a configured provider")

    mappings = data.get("model_providers")
    if not isinstance(mappings, dict):
        raise PatchError("Provider menu 'model_providers' must be an object")
    for model, provider_id in mappings.items():
        _require_non_empty_string(model, "Every model mapping key must be a non-empty string")
        if provider_id not in provider_ids:
            raise PatchError(f"Model '{model}' references unknown provider '{provider_id}'")


def validate_model_catalog(data: Dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise PatchError("Model catalog must be a JSON object")
    models = data.get("models")
    if not isinstance(models, list) or not models:
        raise PatchError("Model catalog must contain a non-empty models array")
    slugs: set[str] = set()
    for model in models:
        if not isinstance(model, dict):
            raise PatchError("Every catalog model must be an object")
        slug = _require_non_empty_string(model.get("slug"), "Every model needs a non-empty slug")
        if slug in slugs:
            raise PatchError(f"Duplicate model slug: {slug}")
        slugs.add(slug)
        _require_non_empty_string(
            model.get("display_name"),
            f"Model '{slug}' needs a display name",
        )
        if not isinstance(model.get("description", ""), str):
            raise PatchError(f"Model '{slug}' description must be a string")
