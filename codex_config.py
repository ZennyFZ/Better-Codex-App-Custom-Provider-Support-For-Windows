"""Safe, display-free configuration services for the Windows GUI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Dict, Optional

from windows_portable import PatchError


ProviderConfig = Dict[str, Any]
ProviderMenuConfig = Dict[str, Any]
ModelCatalog = Dict[str, Any]

_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ConfigPaths:
    codex_home: Path
    config_toml: Path
    provider_menu: Path
    model_catalog: Path
    settings: Path
    backup_dir: Path


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
