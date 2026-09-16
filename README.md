# Better Codex Windows Portable Patcher

A simple Windows GUI for patching an extracted official ChatGPT x64 MSIX so
Codex can load the custom provider menu.

The app is portable-only. It does not install or register AppX, modify
WindowsApps, launch ChatGPT, or edit provider, model, credential, or settings
files.

> [!CAUTION]
> A conversation keeps the provider selected when it starts. Changing the
> provider later does not move an existing conversation to another provider.

## Requirements

- Windows
- Python 3.9 or newer with Tcl/Tk support
- The official x64 ChatGPT MSIX:
  [ChatGPT-x64.msix](https://persistent.oaistatic.com/codex-app-prod/ChatGPT-x64.msix)

Node.js is not required.

## Quick start

1. Double-click `launch_windows_portable_patcher.bat`.
2. Click `DOWNLOAD`, choose a destination, and wait for extraction; or
   download the MSIX yourself, make a copy with a `.zip` extension, and
   extract it.
3. Choose the extracted folder in `Portable root`.
4. Click `CHECK ONLY`.
5. Close portable ChatGPT, then click `PATCH`.
6. Use `UNDO PATCH` when you need to restore the newest backup.

`DOWNLOAD` only downloads and extracts the MSIX. It does not install it.
The extracted folder is named `ChatGPT-x64-portable`; a numeric suffix is used
if that folder already exists.

The portable root should look like this:

```text
<portable-root>\
  app\
    ChatGPT.exe
    resources\
      app.asar
      app.asar.unpacked\
```

## Configure providers manually

The GUI only patches the JavaScript bundle. Configure providers and models
manually in Codex's own files before starting a new task:

```text
%USERPROFILE%\.codex\config.toml
%USERPROFILE%\.codex\desktop-model-providers.json
%USERPROFILE%\.codex\model-catalogs\custom.json
```

For environment-variable authentication, add a provider to
`%USERPROFILE%\.codex\config.toml`:

```toml
[model_providers.openrouter]
name = "OpenRouter"
base_url = "https://openrouter.ai/api/v1"
wire_api = "responses"
env_key = "OPENROUTER_API_KEY"
```

Set `OPENROUTER_API_KEY` in the environment used to start portable ChatGPT,
then restart the app. Add the provider and model mappings manually to
`desktop-model-providers.json`. Keep API keys out of JSON.

The GUI never creates or modifies these files. Editing them does not require
repatching.

## Backup and recovery

Before changing `app.asar`, `PATCH` creates a byte-identical backup. The
backup is kept after `UNDO PATCH`.

Backups default to:

```text
<portable-root>\backups\
```

A ChatGPT update replaces the patched archive. Run `CHECK ONLY` before
patching again after an update.

## Disclaimer

This is an unofficial modification and is not affiliated with or supported by
OpenAI. Use it at your own risk and keep independent backups of your files.
