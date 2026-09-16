# Better Codex App Custom Provider Support

An unofficial patch for the macOS ChatGPT/Codex desktop app that adds per-task model-provider selection without requiring you to sign out of your ChatGPT account.

The patch:

- Adds a provider section to the model menu.
- Sends the selected provider when a new task starts.
- Maps model IDs to providers automatically.
- Keeps tasks from all configured providers visible.
- Keeps the normal ChatGPT login active for OpenAI models.

This project supports the installed macOS app and a **portable Windows build
made by extracting the official ChatGPT MSIX**. The Windows helper does not
install the package and does not modify the installed WindowsApps copy.

> [!CAUTION]
> Changing the provider in a running conversation/thread does **not** work. The conversation/thread continues using the provider it started with.

<img width="500" src="https://github.com/user-attachments/assets/9b61e720-35e9-4021-9c6f-bd77e334e471" />
<br>

## Requirements

- Python 3.9 or newer
- macOS: ChatGPT installed at `/Applications/ChatGPT.app` and Node.js with `npx`
- Windows portable mode: an extracted official x64 MSIX folder; Node.js is not required

## Install

<img width="600" src="https://github.com/user-attachments/assets/8800efd1-d490-4bc3-9959-47ddff5a6db8" />

<br>
<br>

<img width="600" src="https://github.com/user-attachments/assets/90461000-8b4b-4632-93cc-125a116b0830" />

<br>
<br>

1. Click on the `patch_chatgpt_providers.py` file in the repository.
2. Open the menu in the top-right.
3. Click on **Download**.
4. Run the downloaded script:

```bash
python3 patch_chatgpt_providers.py
```

The installer closes processes belonging to the target app, creates a complete backup, patches `app.asar`, updates Electron's ASAR integrity metadata, and applies an ad-hoc signature.

Run `python3 patch_chatgpt_providers.py --help` to see alternate app, config, and backup paths.

## Configure a custom provider

Custom Codex providers belong in `~/.codex/config.toml`. Provider IDs such as `openrouter` are referenced by the patch configuration later.

Example OpenRouter provider:

```toml
[model_providers.openrouter]
name = "OpenRouter"
base_url = "https://openrouter.ai/api/v1"
wire_api = "responses"

[model_providers.openrouter.auth]
command = "/usr/bin/security"
args = ["find-generic-password", "-a", "YOUR_MACOS_USERNAME", "-s", "Codex OpenRouter API Key", "-w"]
timeout_ms = 5000
refresh_interval_ms = 0
```

Replace `YOUR_MACOS_USERNAME`, then add or update the API key in macOS Keychain. The command prompts for the key instead of placing it in shell history:

```bash
security add-generic-password -U -a "$USER" -s "Codex OpenRouter API Key" -w
```

Codex also supports environment-variable authentication with `env_key`. Do not combine `env_key` with a `[model_providers.<id>.auth]` section. For all authentication methods and provider options, see the [Codex custom model provider documentation](https://learn.chatgpt.com/docs/config-file/config-advanced#custom-model-providers).

Do not set a global `model_provider` if OpenAI and custom providers should coexist in the desktop app. The patch selects the provider when each new task starts.

## Windows portable mode

The Windows version is intentionally portable-only. Download the regular x64
ChatGPT MSIX from the official [ChatGPT Windows download](https://persistent.oaistatic.com/codex-app-prod/ChatGPT-x64.msix), make a byte-identical copy with a `.zip` extension, and extract that copy to a folder. Do not run the MSIX installer.

The extracted root must contain:

```text
<portable-root>\
  app\
    ChatGPT.exe
    resources\
      app.asar
      app.asar.unpacked\
```

From this repository, run the check first:

```powershell
python .\patch_chatgpt_providers_windows.py `
  --app-root 'D:\Apps\ChatGPT-portable' `
  --check-only
```

Then close every process launched from that portable folder and patch it:

```powershell
python .\patch_chatgpt_providers_windows.py `
  --app-root 'D:\Apps\ChatGPT-portable'
```

The helper backs up the original `app.asar`, updates only the two supported
JavaScript bundles, preserves `app.asar.unpacked`, and atomically replaces the
archive. It refuses to patch while the portable app is running. Use
`--backup-dir` and `--config` to select explicit locations. `--allow-running`
is available only when you understand the risk of modifying an in-use archive.

### Classic utility GUI

To use the same workflow in a compact classic utility window with folder
pickers and a live log, run:

```powershell
python .\patch_chatgpt_providers_windows_gui.py `
  --app-root 'D:\Apps\ChatGPT-portable'
```

The GUI is the recommended Windows workflow for patching: it does not edit,
create, or validate providers, credentials, models, or model-to-provider
mappings. Edit those files yourself in a text editor first. The GUI only
checks the portable layout and patches `app.asar` in a background thread; it
never installs or launches `ChatGPT.exe`.

First run:

1. Double-click `launch_windows_portable_patcher.bat`.
2. Optionally click `DOWNLOAD`, choose a destination folder, and wait for the
   MSIX to be downloaded and extracted as `ChatGPT-x64-portable`. This is a
   portable extraction only; Windows AppX is not installed or registered.
3. Edit these files manually if needed:
   `%USERPROFILE%\.codex\config.toml`,
   `%USERPROFILE%\.codex\desktop-model-providers.json`, and
   `%USERPROFILE%\.codex\model-catalogs\custom.json`.
4. In the GUI, choose the extracted portable root and click `CHECK ONLY`.
5. Close portable ChatGPT, then click `PATCH`. The GUI creates a backup and
   changes only the portable app's `app.asar`.
6. If needed, click `UNDO PATCH` to restore the newest backup. The backup is
   kept, so it can be used again later.

The optional `AUDIO: OFF` button plays the first `.mp3` or `.wav` file beside
the GUI in `media` at reduced volume. Audio is always off when the GUI starts.

`plaintext` authentication is available for providers that require a direct
bearer token, but it is experimental/insecure. Configure it manually in
`config.toml`; the patch-only GUI never reads or writes credentials. The
patcher does not modify provider-menu JSON, model catalog JSON, or GUI
settings.

For one-click use, double-click `launch_windows_portable_patcher.bat` beside
the Python files. It opens the GUI without prefilled portable paths; choose
the extracted folder inside the application.

The default Windows files are:

```text
%USERPROFILE%\.codex\config.toml
%USERPROFILE%\.codex\desktop-model-providers.json
%USERPROFILE%\.codex\model-catalogs\custom.json
```

Provider API keys must remain in Codex's `config.toml`, never in that JSON
file. On Windows, `env_key` is the simplest authentication option, for example:

```toml
[model_providers.openrouter]
name = "OpenRouter"
base_url = "https://openrouter.ai/api/v1"
wire_api = "responses"
env_key = "OPENROUTER_API_KEY"
```

Set `OPENROUTER_API_KEY` in the environment used to start the portable app,
then restart ChatGPT after changing `config.toml`. A patch is tied to the
current JavaScript bundle layout; after a ChatGPT update, rerun `--check-only`
before patching again.

## Configuration schema reference (optional)

Edit Codex's custom model catalog manually. Keep its advanced metadata intact
when changing a model; this patch-only GUI does not seed, clone, or rewrite
the catalog.

Edit the patched provider menu manually as well:

```text
~/.codex/desktop-model-providers.json
```

Example:

```json
{
  "version": 1,
  "default_provider": "openai",
  "providers": [
    {
      "id": "openai",
      "label": "ChatGPT / OpenAI",
      "description": "Uses your signed-in ChatGPT account"
    },
    {
      "id": "openrouter",
      "label": "OpenRouter",
      "description": "Uses [model_providers.openrouter] from config.toml"
    }
  ],
  "model_providers": {
    "moonshotai/kimi-k3": "openrouter",
    "x-ai/grok-4.5": "openrouter",
    "anthropic/claude-fable-5": "openrouter"
  }
}
```

- `providers` defines the providers displayed in the app menu.
- `model_providers` maps exact model slugs to provider IDs for Automatic mode.
- `default_provider` handles models without an explicit mapping.
- Every custom provider ID must match a `[model_providers.<id>]` section in `config.toml`.
- API keys do not belong in this JSON file.

The app reloads this file when the provider menu opens and before a new task
starts. Repatching is not required after editing it; run `CHECK ONLY` again if
you want to verify the portable bundle before a new patch.

## Updates and recovery

ChatGPT updates replace the patch. Run the installer again after an update.

The installer is not tied to a fixed app version or archive hash. It patches compatible source structures and stops before modifying the installed app if an update changes the relevant code.

Backups are stored by default in:

```text
~/Applications/ChatGPT Patch Backups/
```

## Disclaimer

Use this script entirely at your own risk. It modifies the installed ChatGPT application in an unofficial and unsupported way.

The author and contributors provide no warranty and accept no responsibility or liability for any problems, damage, or loss caused directly or indirectly by using this script. This includes, but is not limited to, lost or corrupted chat history or other data, an unusable or "bricked" application, account warnings or restrictions, account suspension or banning, security or privacy issues, and any other direct or consequential damage.

Create and verify your own backups before running the script.

---

_This is an unofficial modification and is not affiliated with or supported by OpenAI._
