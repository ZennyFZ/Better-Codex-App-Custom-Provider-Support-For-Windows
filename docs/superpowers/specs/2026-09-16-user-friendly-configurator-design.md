# Earlier Windows provider configurator design (superseded)

> The current GUI intentionally uses a simpler patch-only workflow: users edit
> `config.toml`, `desktop-model-providers.json`, and the model catalog manually;
> the GUI only checks and patches the extracted portable app. The requirements
> below are retained as the historical design that led to the configurator
> implementation, but they are not the current product behavior.

## Goal

Turn the Windows portable provider patcher into a self-contained setup tool.
Users should be able to configure custom providers, credentials, models, and
the patched provider menu from the GUI without opening `config.toml`, JSON, or
model-catalog files in a text editor.

The existing portable patching safety rules remain unchanged: the tool only
modifies the selected extracted MSIX folder, creates backups before writes, and
never installs or launches the ChatGPT package.

## Scope

The GUI will manage these default Codex files, with an advanced path override
for each location:

```text
%USERPROFILE%\.codex\config.toml
%USERPROFILE%\.codex\desktop-model-providers.json
%USERPROFILE%\.codex\model-catalogs\custom.json
```

The GUI will also remember the last selected portable root and Codex home in a
small application settings file under `%APPDATA%\BetterCodexPortablePatcher`.
This file contains paths and UI preferences only, never credentials.

## Recommended approach

Extend the existing Tkinter application and add a small, dependency-free
configuration layer. This keeps the current one-click batch launcher and
portable patcher intact while giving the GUI a testable boundary for TOML,
JSON, catalog, and Windows environment updates.

Alternative approaches were considered:

1. Keep asking users to edit files: lowest implementation cost, but fails the
   usability goal.
2. Build a separate web/Electron editor: more styling freedom, but adds a
   runtime and packaging problem to a Python portable helper.
3. Extend the current Tkinter app: reuses the existing workflow, has no new
   runtime dependency, and is the selected approach.

## User flow and UI

The classic compact utility window will gain three logical pages or tabs:

### Setup / Providers

- Show configured custom providers in a list.
- Add, edit, and remove providers.
- Edit provider ID, display name, description, base URL, and wire API.
- Choose authentication mode:
  - `Environment variable`: enter a variable name and optional secret value.
    The GUI writes `env_key` to `config.toml` and can save the value to the
    current Windows user's environment. The new process must be restarted to
    see the updated variable.
  - `Plaintext token`: write the value as
    `experimental_bearer_token` in `config.toml`. The UI labels this as
    experimental/insecure, masks the field by default, and requires an explicit
    confirmation before saving.
- Never place credentials in `desktop-model-providers.json`, logs, or the GUI
  settings file.

### Models

- Show models from the selected custom catalog.
- Add, edit, and remove models using a form rather than raw JSON.
- Required basic fields: slug, display name, description, and provider.
- Offer a template-model selector. When adding a model, clone a bundled or
  existing catalog model so required metadata is preserved automatically.
- Provide an advanced section for context window, modalities, reasoning
  levels, tool support, visibility, and API availability. Basic users can
  leave these at template defaults.
- Automatically set or update `model_catalog_json` in `config.toml`.
- If no catalog exists, use `codex debug models --bundled` to seed the catalog.
  If the Codex CLI is unavailable, let the user select an existing catalog;
  when neither source exists, show a clear blocking error instead of silently
  writing a catalog with invalid required metadata.

### Provider menu

- Show the providers that will appear in the patched task menu.
- Edit menu label and description independently from the Codex provider ID.
- Choose `default_provider` from the configured provider list.
- Manage exact model-slug to provider mappings for Automatic mode.
- Validate that every mapped provider exists and every custom provider ID has a
  matching entry in `config.toml`.

## Save, validation, and patch actions

The bottom action bar will expose:

- `Load`: read all three files and refresh the UI.
- `Save`: validate and atomically write configuration files, creating backups
  for existing files first.
- `Validate`: report missing paths, invalid fields, duplicate IDs, missing
  providers, malformed catalog data, and authentication configuration errors.
- `Check only`: validate the portable app and current ASAR markers without
  writing the archive.
- `Patch`: require explicit confirmation, save/validate configuration first,
  create the original `app.asar` backup, then patch the archive.

All long-running work stays on the existing background worker. The activity
log shows actionable messages but redacts secret values and only reports
credential mode and variable name.

## Configuration persistence

### TOML

The configuration writer will update only the managed root keys and
`[model_providers.<id>]` sections. It will preserve unrelated keys, comments,
and provider options whenever possible instead of reserializing the whole
file. Existing files are copied to a timestamped backup before replacement,
and replacement is atomic.

The writer will support both documented environment authentication and the
direct bearer-token field used for the optional plaintext mode. Provider IDs
that require quoted TOML keys will be escaped correctly.

### Provider menu JSON

Use the existing version-1 schema and validation rules from `windows_portable`.
Writes remain UTF-8, indented, atomic, and separate from credentials.

### Model catalog JSON

Read and write the catalog's top-level `models` array while preserving unknown
top-level fields and unknown per-model fields copied from a template. New
models receive explicit basic metadata and inherit advanced metadata from the
selected template unless the user changes it in the advanced editor.

### Windows environment

Environment mode will write the variable for the current Windows user, not the
machine-wide environment, and update the current GUI process environment too.
The UI will explain that already-running ChatGPT/Codex processes need to be
closed and reopened.

## Error handling and safety

- Refuse writes when the portable app is running, as the current patcher does.
- Validate all form data before any write.
- Use per-file backups and atomic replacement; a failed replacement leaves the
  original file in place.
- If one configuration file cannot be written, report the exact path and stop
  before touching the ASAR archive.
- Require an explicit confirmation for plaintext credentials and archive patch.
- Never print or persist secret values in exceptions, logs, backups of the GUI
  settings file, or test output.

## Testing

Add unit tests for:

- provider-menu load, validation, and atomic write behavior;
- TOML provider add/update/remove while preserving unrelated content;
- environment-mode and plaintext-mode serialization, with secrets excluded
  from logs;
- model catalog template cloning and provider mapping validation;
- GUI parser, classic layout contract, and action-state behavior without a
  display server;
- end-to-end configuration save followed by portable `--check-only`.

Keep the existing ASAR rebuild and portable-process tests passing. Do not
launch ChatGPT or install the MSIX during tests.

## Non-goals

- No installer or MSIX repackaging.
- No automatic launch of ChatGPT after saving or patching.
- No cloud synchronization of provider configuration or credentials.
- No support for arbitrary TOML editing beyond the managed Codex settings.
