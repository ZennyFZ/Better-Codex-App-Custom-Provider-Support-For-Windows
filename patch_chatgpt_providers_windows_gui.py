"""Classic utility-style GUI for the Windows portable provider patcher."""

from __future__ import annotations

import argparse
import copy
import os
from pathlib import Path
import queue
import threading
from typing import Any, Optional, Sequence

import codex_config
from windows_portable import (
    PatchError,
    find_windows_app_processes,
    locate_portable_app,
    patch_portable_app,
)

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox
except ImportError:  # pragma: no cover - depends on the Python distribution.
    tk = None
    filedialog = None
    messagebox = None


CLASSIC_BG = "#555555"
CLASSIC_PANEL = "#4a4a4a"
CLASSIC_FIELD = "#343434"
CLASSIC_FIELD_FG = "#f2f2f2"
CLASSIC_BUTTON = "#686868"
CLASSIC_BUTTON_ACTIVE = "#7a7a7a"
CLASSIC_TEXT = "#f0f0f0"
CLASSIC_MUTED = "#c6c6c6"
CLASSIC_GREEN = "#b8e0b2"
CLASSIC_CYAN = "#b8d9f0"
CLASSIC_YELLOW = "#f0d58c"
CLASSIC_RED = "#ffadad"

BUILTIN_MENU_PROVIDER = {
    "id": "openai",
    "label": "ChatGPT / OpenAI",
    "description": "Built-in provider; uses your signed-in ChatGPT account",
}


def format_log_line(level: str, message: str) -> str:
    return f"[{level.upper()}] {message}"


def build_classic_ui_spec() -> dict[str, Any]:
    """Return the small Win32-style layout contract used by the GUI."""
    return {
        "geometry": "620x600",
        "background": CLASSIC_BG,
        "fields": ("Portable root:", "Config JSON:", "Backup directory:"),
        "buttons": ("CHECK ONLY", "PATCH", "CLEAR LOG"),
        "pages": ("Setup", "Models", "Provider menu"),
        "actions": ("LOAD", "SAVE", "VALIDATE", "CHECK ONLY", "PATCH"),
        "plaintext_warning": (
            "Plaintext bearer tokens are experimental and insecure; "
            "use an environment variable when possible."
        ),
    }


def build_gui_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open the classic utility GUI for the Windows portable patcher."
    )
    parser.add_argument("--app-root", type=Path, help="Pre-fill the extracted MSIX root")
    parser.add_argument("--config", type=Path, help="Pre-fill the provider-routing JSON path")
    parser.add_argument("--backup-dir", type=Path, help="Pre-fill the ASAR backup directory")
    return parser


def _default_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()


class TerminalPatcherUi:
    """A small Tkinter front end that keeps patching off the UI thread."""

    def __init__(
        self,
        app_root: Optional[Path] = None,
        config: Optional[Path] = None,
        backup_dir: Optional[Path] = None,
    ) -> None:
        if tk is None or filedialog is None or messagebox is None:
            raise PatchError(
                "Tkinter is not available in this Python installation. "
                "Install Python from python.org with Tcl/Tk support."
            )

        spec = build_classic_ui_spec()
        self.root = tk.Tk()
        self.root.title("Better Codex Windows Portable Patcher")
        self.root.geometry(spec["geometry"])
        self.root.minsize(560, 520)
        self.root.configure(bg=spec["background"])
        self.root.protocol("WM_DELETE_WINDOW", self._close_window)

        self._default_paths = codex_config.default_config_paths()
        self._default_config_path = self._default_paths.provider_menu
        try:
            saved_settings = codex_config.load_gui_settings(self._default_paths.settings)
        except PatchError:
            saved_settings = {}
        saved_root = saved_settings.get("portable_root", "")
        saved_codex_home = saved_settings.get("codex_home", self._default_paths.codex_home)
        saved_toml = saved_settings.get("config_toml", self._default_paths.config_toml)
        saved_menu = saved_settings.get("provider_menu", self._default_paths.provider_menu)
        saved_catalog = saved_settings.get("model_catalog", self._default_paths.model_catalog)
        saved_backup = saved_settings.get("backup_dir", "")
        self._settings_path = self._default_paths.settings
        self.app_root_var = tk.StringVar(value=str(app_root or saved_root or ""))
        self.codex_home_var = tk.StringVar(value=str(saved_codex_home))
        self.config_toml_var = tk.StringVar(value=str(saved_toml))
        self.provider_menu_var = tk.StringVar(value=str(config or saved_menu or self._default_paths.provider_menu))
        self.config_var = self.provider_menu_var  # Backwards-compatible name for the old GUI.
        self.model_catalog_var = tk.StringVar(value=str(saved_catalog))
        initial_backup = backup_dir or saved_backup or (Path(app_root) / "backups" if app_root else "")
        self.backup_dir_var = tk.StringVar(value=str(initial_backup))
        self.providers: list[dict[str, Any]] = []
        self.model_catalog: dict[str, Any] = {"models": []}
        self.provider_menu: dict[str, Any] = {
            "version": 1,
            "default_provider": "openai",
            "providers": [copy.deepcopy(BUILTIN_MENU_PROVIDER)],
            "model_providers": {},
        }
        self.root_updates: dict[str, Any] = {}
        self._page = "Setup"
        self.status_var = tk.StringVar(value="READY")
        self._events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._running = False

        self._build_widgets()
        self.root.after(100, self._drain_events)
        self._write_log("INFO", "Choose the extracted MSIX folder, then click CHECK ONLY.")
        self._write_log("INFO", "The installed MSIX is never changed or launched.")

    def _build_widgets(self) -> None:
        outer = tk.Frame(self.root, background=CLASSIC_BG, padx=8, pady=8)
        outer.pack(fill="both", expand=True)

        title = tk.Label(
            outer,
            text="Better Codex Windows Portable Patcher",
            background=CLASSIC_BG,
            foreground=CLASSIC_TEXT,
            anchor="w",
            font=("Segoe UI", 10, "bold"),
        )
        title.pack(fill="x", pady=(0, 5))
        tk.Label(
            outer,
            text="Patch the extracted official MSIX folder; the installed app is left untouched.",
            background=CLASSIC_BG,
            foreground=CLASSIC_MUTED,
            anchor="w",
            font=("Segoe UI", 8),
        ).pack(fill="x", pady=(0, 6))

        page_bar = tk.Frame(outer, background=CLASSIC_BG)
        page_bar.pack(fill="x", pady=(0, 5))
        self.page_buttons: dict[str, Any] = {}
        for page in build_classic_ui_spec()["pages"]:
            button = self._classic_button(page_bar, page, lambda value=page: self._show_page(value))
            button.pack(side="left", padx=(0, 5))
            self.page_buttons[page] = button

        self.page_frame = tk.Frame(outer, background=CLASSIC_BG)
        self.page_frame.pack(fill="both", expand=True, pady=(0, 6))
        self._show_page("Setup")

        log_frame = tk.LabelFrame(
            outer,
            text="Activity log",
            background=CLASSIC_PANEL,
            foreground=CLASSIC_TEXT,
            bd=1,
            relief="groove",
            padx=6,
            pady=5,
            font=("Segoe UI", 9, "bold"),
        )
        log_frame.pack(fill="both", expand=True, pady=(0, 7))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(
            log_frame,
            background=CLASSIC_FIELD,
            foreground=CLASSIC_TEXT,
            insertbackground=CLASSIC_TEXT,
            relief="sunken",
            borderwidth=1,
            wrap="word",
            font=("Consolas", 9),
            padx=7,
            pady=5,
            state="disabled",
        )
        scrollbar = tk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        for level, color in (
            ("INFO", CLASSIC_TEXT),
            ("SCAN", CLASSIC_CYAN),
            ("OK", CLASSIC_GREEN),
            ("PATCH", CLASSIC_YELLOW),
            ("ERROR", CLASSIC_RED),
        ):
            self.log.tag_configure(level, foreground=color)

        footer = tk.Frame(outer, background=CLASSIC_BG)
        footer.pack(fill="x")
        tk.Label(
            footer,
            textvariable=self.status_var,
            background=CLASSIC_BG,
            foreground=CLASSIC_MUTED,
            anchor="w",
            font=("Segoe UI", 8),
        ).pack(side="left", fill="x", expand=True)
        self.clear_button = self._classic_button(footer, "CLEAR LOG", self._clear_log)
        self.clear_button.pack(side="right", padx=(5, 0))
        self.patch_button = self._classic_button(footer, "PATCH", self._start_patch)
        self.patch_button.pack(side="right", padx=(5, 0))
        self.check_button = self._classic_button(footer, "CHECK ONLY", self._start_check)
        self.check_button.pack(side="right", padx=(5, 0))
        self.validate_button = self._classic_button(footer, "VALIDATE", self._start_validate)
        self.validate_button.pack(side="right", padx=(5, 0))
        self.save_button = self._classic_button(footer, "SAVE", self._start_save)
        self.save_button.pack(side="right", padx=(5, 0))
        self.load_button = self._classic_button(footer, "LOAD", self._start_load)
        self.load_button.pack(side="right")

    def _show_page(self, page: str) -> None:
        if page not in build_classic_ui_spec()["pages"]:
            return
        self._page = page
        for name in (
            "provider_listbox", "model_listbox", "menu_provider_listbox", "mapping_listbox",
            "model_provider_menu", "model_template_menu", "default_provider_menu",
            "mapping_provider_menu",
        ):
            self.__dict__.pop(name, None)
        for widget in self.page_frame.winfo_children():
            widget.destroy()
        if page == "Setup":
            self._build_setup_page()
        elif page == "Models":
            self._build_models_page()
        else:
            self._build_provider_menu_page()

    def _label_frame(self, parent, title: str):
        return tk.LabelFrame(
            parent,
            text=title,
            background=CLASSIC_PANEL,
            foreground=CLASSIC_TEXT,
            bd=1,
            relief="groove",
            padx=7,
            pady=6,
            font=("Segoe UI", 8, "bold"),
        )

    def _entry_row(self, parent, row: int, label: str, variable, show: Optional[str] = None):
        tk.Label(
            parent,
            text=label,
            background=CLASSIC_PANEL,
            foreground=CLASSIC_TEXT,
            anchor="w",
            font=("Segoe UI", 8),
        ).grid(row=row, column=0, sticky="w", padx=(0, 6), pady=2)
        entry = tk.Entry(
            parent,
            textvariable=variable,
            show=show or "",
            background=CLASSIC_FIELD,
            foreground=CLASSIC_FIELD_FG,
            insertbackground=CLASSIC_FIELD_FG,
            relief="sunken",
            borderwidth=1,
            highlightthickness=0,
            font=("Segoe UI", 8),
        )
        entry.grid(row=row, column=1, sticky="ew", pady=2)
        return entry

    def _option_menu(self, parent, variable, values):
        values = list(values) or [""]
        if variable.get() not in values:
            variable.set(values[0])
        menu = tk.OptionMenu(parent, variable, *values)
        menu.configure(
            background=CLASSIC_BUTTON,
            foreground=CLASSIC_TEXT,
            activebackground=CLASSIC_BUTTON_ACTIVE,
            activeforeground=CLASSIC_TEXT,
            highlightthickness=0,
            relief="raised",
            borderwidth=1,
            font=("Segoe UI", 8),
        )
        menu["menu"].configure(
            background=CLASSIC_FIELD,
            foreground=CLASSIC_TEXT,
            activebackground=CLASSIC_BUTTON_ACTIVE,
            activeforeground=CLASSIC_TEXT,
        )
        return menu

    def _build_setup_page(self) -> None:
        page = tk.Frame(self.page_frame, background=CLASSIC_BG)
        page.pack(fill="both", expand=True)

        locations = self._label_frame(page, "Locations (advanced)")
        locations.pack(fill="x", pady=(0, 6))
        locations.columnconfigure(0, weight=1)
        self.app_root_entry, self.app_root_browse = self._path_row(
            locations, 0, "Portable root:", self.app_root_var, self._browse_root
        )
        self.codex_home_entry, self.codex_home_browse = self._path_row(
            locations, 1, "Codex home:", self.codex_home_var, self._browse_codex_home
        )
        self.config_toml_entry, self.config_toml_browse = self._path_row(
            locations, 2, "config.toml:", self.config_toml_var, self._browse_config_toml
        )
        self.config_entry, self.config_browse = self._path_row(
            locations, 3, "Provider menu JSON:", self.provider_menu_var, self._browse_config
        )
        self.model_catalog_entry, self.model_catalog_browse = self._path_row(
            locations, 4, "Model catalog JSON:", self.model_catalog_var, self._browse_model_catalog
        )
        self.backup_entry, self.backup_browse = self._path_row(
            locations, 5, "Backup directory:", self.backup_dir_var, self._browse_backup
        )

        providers_frame = self._label_frame(page, "Providers")
        providers_frame.pack(fill="both", expand=True)
        providers_frame.columnconfigure(0, weight=1)
        providers_frame.columnconfigure(1, weight=2)
        providers_frame.rowconfigure(0, weight=1)

        list_panel = tk.Frame(providers_frame, background=CLASSIC_PANEL)
        list_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        list_panel.rowconfigure(0, weight=1)
        list_panel.columnconfigure(0, weight=1)
        self.provider_listbox = tk.Listbox(
            list_panel,
            background=CLASSIC_FIELD,
            foreground=CLASSIC_TEXT,
            selectbackground="#8aa8c0",
            selectforeground="#111111",
            height=7,
            exportselection=False,
            relief="sunken",
            borderwidth=1,
            font=("Segoe UI", 8),
        )
        self.provider_listbox.grid(row=0, column=0, sticky="nsew")
        self.provider_listbox.bind("<<ListboxSelect>>", self._on_provider_select)
        provider_buttons = tk.Frame(list_panel, background=CLASSIC_PANEL)
        provider_buttons.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        self._classic_button(provider_buttons, "ADD", self._add_provider).pack(side="left")
        self._classic_button(provider_buttons, "EDIT", self._edit_provider).pack(side="left", padx=4)
        self._classic_button(provider_buttons, "REMOVE", self._remove_provider).pack(side="left")

        editor = self._label_frame(providers_frame, "Provider details")
        editor.grid(row=0, column=1, sticky="nsew")
        editor.columnconfigure(1, weight=1)
        self.provider_id_var = tk.StringVar()
        self.provider_label_var = tk.StringVar()
        self.provider_name_var = tk.StringVar()
        self.provider_description_var = tk.StringVar()
        self.provider_base_url_var = tk.StringVar()
        self.provider_wire_api_var = tk.StringVar(value="responses")
        self.auth_mode_var = tk.StringVar(value="environment")
        self.env_key_var = tk.StringVar()
        self.token_var = tk.StringVar()
        self._entry_row(editor, 0, "Provider ID:", self.provider_id_var)
        self._entry_row(editor, 1, "Menu label:", self.provider_label_var)
        self._entry_row(editor, 2, "Display name:", self.provider_name_var)
        self._entry_row(editor, 3, "Description:", self.provider_description_var)
        self._entry_row(editor, 4, "Base URL:", self.provider_base_url_var)
        self._entry_row(editor, 5, "Wire API:", self.provider_wire_api_var)
        tk.Label(
            editor,
            text="Authentication:",
            background=CLASSIC_PANEL,
            foreground=CLASSIC_TEXT,
            anchor="w",
            font=("Segoe UI", 8),
        ).grid(row=6, column=0, sticky="w", padx=(0, 6), pady=2)
        self.auth_mode_menu = self._option_menu(
            editor,
            self.auth_mode_var,
            ("none", "environment", "plaintext"),
        )
        self.auth_mode_menu.grid(row=6, column=1, sticky="w", pady=2)
        self._entry_row(editor, 7, "Environment key:", self.env_key_var)
        self.token_entry = self._entry_row(editor, 8, "Token (masked):", self.token_var, "*")
        self.persist_env_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            editor,
            text="Save environment value for current Windows user",
            variable=self.persist_env_var,
            background=CLASSIC_PANEL,
            foreground=CLASSIC_TEXT,
            activebackground=CLASSIC_PANEL,
            activeforeground=CLASSIC_TEXT,
            selectcolor=CLASSIC_FIELD,
            anchor="w",
            font=("Segoe UI", 8),
        ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(4, 1))
        self.show_token_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            editor,
            text="Show token",
            variable=self.show_token_var,
            command=self._toggle_token_visibility,
            background=CLASSIC_PANEL,
            foreground=CLASSIC_TEXT,
            activebackground=CLASSIC_PANEL,
            activeforeground=CLASSIC_TEXT,
            selectcolor=CLASSIC_FIELD,
            anchor="w",
            font=("Segoe UI", 8),
        ).grid(row=10, column=0, columnspan=2, sticky="w")
        tk.Label(
            editor,
            text=build_classic_ui_spec()["plaintext_warning"],
            background=CLASSIC_FIELD,
            foreground=CLASSIC_YELLOW,
            justify="left",
            wraplength=250,
            anchor="w",
            padx=5,
            pady=4,
            font=("Segoe UI", 8),
        ).grid(row=11, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        self._refresh_provider_list()

    def _build_models_page(self) -> None:
        page = tk.Frame(self.page_frame, background=CLASSIC_BG)
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.columnconfigure(1, weight=2)
        page.rowconfigure(0, weight=1)
        list_panel = self._label_frame(page, "Custom model catalog")
        list_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        list_panel.rowconfigure(0, weight=1)
        list_panel.columnconfigure(0, weight=1)
        self.model_listbox = tk.Listbox(
            list_panel,
            background=CLASSIC_FIELD,
            foreground=CLASSIC_TEXT,
            selectbackground="#8aa8c0",
            selectforeground="#111111",
            height=8,
            exportselection=False,
            relief="sunken",
            borderwidth=1,
            font=("Segoe UI", 8),
        )
        self.model_listbox.grid(row=0, column=0, sticky="nsew")
        self.model_listbox.bind("<<ListboxSelect>>", self._on_model_select)
        model_buttons = tk.Frame(list_panel, background=CLASSIC_PANEL)
        model_buttons.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        self._classic_button(model_buttons, "ADD", self._add_model).pack(side="left")
        self._classic_button(model_buttons, "EDIT", self._edit_model).pack(side="left", padx=4)
        self._classic_button(model_buttons, "REMOVE", self._remove_model).pack(side="left")

        editor = self._label_frame(page, "Model details")
        editor.grid(row=0, column=1, sticky="nsew")
        editor.columnconfigure(1, weight=1)
        self.model_slug_var = tk.StringVar()
        self.model_display_var = tk.StringVar()
        self.model_description_var = tk.StringVar()
        self.model_provider_var = tk.StringVar()
        self.model_template_var = tk.StringVar()
        self._entry_row(editor, 0, "Slug:", self.model_slug_var)
        self._entry_row(editor, 1, "Display name:", self.model_display_var)
        self._entry_row(editor, 2, "Description:", self.model_description_var)
        tk.Label(
            editor,
            text="Provider:",
            background=CLASSIC_PANEL,
            foreground=CLASSIC_TEXT,
            anchor="w",
            font=("Segoe UI", 8),
        ).grid(row=3, column=0, sticky="w", padx=(0, 6), pady=2)
        self.model_provider_menu = self._option_menu(editor, self.model_provider_var, [])
        self.model_provider_menu.grid(row=3, column=1, sticky="w", pady=2)
        tk.Label(
            editor,
            text="Template for new model:",
            background=CLASSIC_PANEL,
            foreground=CLASSIC_TEXT,
            anchor="w",
            font=("Segoe UI", 8),
        ).grid(row=4, column=0, sticky="w", padx=(0, 6), pady=2)
        self.model_template_menu = self._option_menu(editor, self.model_template_var, [])
        self.model_template_menu.grid(row=4, column=1, sticky="w", pady=2)

        advanced = self._label_frame(editor, "Advanced metadata (optional)")
        advanced.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        advanced.columnconfigure(1, weight=1)
        self.model_advanced_vars = {
            "context_window": tk.StringVar(),
            "input_modalities": tk.StringVar(),
            "output_modalities": tk.StringVar(),
            "supported_reasoning_levels": tk.StringVar(),
            "visibility": tk.StringVar(),
            "supports_tools": tk.StringVar(),
            "api_availability": tk.StringVar(),
        }
        self._entry_row(advanced, 0, "Context window:", self.model_advanced_vars["context_window"])
        self._entry_row(advanced, 1, "Input modalities:", self.model_advanced_vars["input_modalities"])
        self._entry_row(advanced, 2, "Output modalities:", self.model_advanced_vars["output_modalities"])
        self._entry_row(advanced, 3, "Reasoning levels:", self.model_advanced_vars["supported_reasoning_levels"])
        self._entry_row(advanced, 4, "Visibility:", self.model_advanced_vars["visibility"])
        self._entry_row(advanced, 5, "Supports tools:", self.model_advanced_vars["supports_tools"])
        self._entry_row(advanced, 6, "API availability:", self.model_advanced_vars["api_availability"])
        tk.Label(
            editor,
            text="New models inherit all other fields from the selected template.",
            background=CLASSIC_PANEL,
            foreground=CLASSIC_MUTED,
            anchor="w",
            font=("Segoe UI", 8),
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(5, 0))
        self._refresh_model_list()

    def _build_provider_menu_page(self) -> None:
        page = tk.Frame(self.page_frame, background=CLASSIC_BG)
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.columnconfigure(1, weight=1)
        page.rowconfigure(0, weight=1)

        menu_frame = self._label_frame(page, "Patched provider menu")
        menu_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        menu_frame.rowconfigure(0, weight=1)
        menu_frame.columnconfigure(0, weight=1)
        self.menu_provider_listbox = tk.Listbox(
            menu_frame,
            background=CLASSIC_FIELD,
            foreground=CLASSIC_TEXT,
            selectbackground="#8aa8c0",
            selectforeground="#111111",
            height=7,
            exportselection=False,
            relief="sunken",
            borderwidth=1,
            font=("Segoe UI", 8),
        )
        self.menu_provider_listbox.grid(row=0, column=0, sticky="nsew")
        self.menu_provider_listbox.bind("<<ListboxSelect>>", self._on_menu_provider_select)
        menu_buttons = tk.Frame(menu_frame, background=CLASSIC_PANEL)
        menu_buttons.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        self._classic_button(menu_buttons, "ADD SELECTED", self._add_menu_provider).pack(side="left")
        self._classic_button(menu_buttons, "APPLY LABEL", self._edit_menu_provider).pack(side="left", padx=4)
        self._classic_button(menu_buttons, "REMOVE", self._remove_menu_provider).pack(side="left")

        details = self._label_frame(page, "Menu settings")
        details.grid(row=0, column=1, sticky="nsew")
        details.columnconfigure(1, weight=1)
        self.menu_label_var = tk.StringVar()
        self.menu_description_var = tk.StringVar()
        self.default_provider_var = tk.StringVar()
        self._entry_row(details, 0, "Menu label:", self.menu_label_var)
        self._entry_row(details, 1, "Description:", self.menu_description_var)
        tk.Label(
            details,
            text="Default provider:",
            background=CLASSIC_PANEL,
            foreground=CLASSIC_TEXT,
            anchor="w",
            font=("Segoe UI", 8),
        ).grid(row=2, column=0, sticky="w", padx=(0, 6), pady=2)
        self.default_provider_menu = self._option_menu(details, self.default_provider_var, [])
        self.default_provider_menu.grid(row=2, column=1, sticky="w", pady=2)

        mapping_frame = self._label_frame(details, "Automatic model mappings")
        mapping_frame.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(7, 0))
        mapping_frame.columnconfigure(0, weight=1)
        mapping_frame.rowconfigure(0, weight=1)
        self.mapping_listbox = tk.Listbox(
            mapping_frame,
            background=CLASSIC_FIELD,
            foreground=CLASSIC_TEXT,
            selectbackground="#8aa8c0",
            selectforeground="#111111",
            height=6,
            exportselection=False,
            relief="sunken",
            borderwidth=1,
            font=("Segoe UI", 8),
        )
        self.mapping_listbox.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.mapping_model_var = tk.StringVar()
        self.mapping_provider_var = tk.StringVar()
        self._entry_row(mapping_frame, 1, "Model slug:", self.mapping_model_var)
        tk.Label(
            mapping_frame,
            text="Provider:",
            background=CLASSIC_PANEL,
            foreground=CLASSIC_TEXT,
            anchor="w",
            font=("Segoe UI", 8),
        ).grid(row=2, column=0, sticky="w", padx=(0, 6), pady=2)
        self.mapping_provider_menu = self._option_menu(mapping_frame, self.mapping_provider_var, [])
        self.mapping_provider_menu.grid(row=2, column=1, sticky="w", pady=2)
        self._classic_button(mapping_frame, "UPDATE MAPPING", self._update_provider_mapping).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(5, 0)
        )
        self._refresh_provider_menu_page()

    def _set_option_values(self, menu, variable, values) -> None:
        values = list(values) or [""]
        if variable.get() not in values:
            variable.set(values[0])
        menu["menu"].delete(0, "end")
        for value in values:
            menu["menu"].add_command(
                label=value or "(none)",
                command=lambda selected=value: variable.set(selected),
            )

    def _browse_codex_home(self) -> None:
        selected = filedialog.askdirectory(title="Choose Codex home")
        if selected:
            self.codex_home_var.set(selected)

    def _browse_config_toml(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="Choose Codex config.toml",
            defaultextension=".toml",
            filetypes=(("TOML files", "*.toml"), ("All files", "*.*")),
        )
        if selected:
            self.config_toml_var.set(selected)

    def _browse_model_catalog(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="Choose model catalog JSON",
            defaultextension=".json",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if selected:
            self.model_catalog_var.set(selected)

    def _toggle_token_visibility(self) -> None:
        self.token_entry.configure(show="" if self.show_token_var.get() else "*")

    def _provider_display(self, provider: dict[str, Any]) -> str:
        return f"{provider.get('id', '')} - {provider.get('label') or provider.get('name', '')}"

    def _all_provider_ids(self) -> list[str]:
        return [BUILTIN_MENU_PROVIDER["id"]] + [
            provider.get("id", "") for provider in self.providers
        ]

    def _refresh_provider_list(self) -> None:
        if not hasattr(self, "provider_listbox"):
            return
        self.provider_listbox.delete(0, "end")
        for provider in self.providers:
            self.provider_listbox.insert("end", self._provider_display(provider))
        if self.providers:
            self.provider_listbox.selection_set(0)
            self._fill_provider_form(self.providers[0])
        else:
            self._clear_provider_form()

    def _on_provider_select(self, _event=None) -> None:
        selection = self.provider_listbox.curselection()
        if selection:
            self._fill_provider_form(self.providers[selection[0]])

    def _clear_provider_form(self) -> None:
        for variable in (
            self.provider_id_var,
            self.provider_label_var,
            self.provider_name_var,
            self.provider_description_var,
            self.provider_base_url_var,
            self.env_key_var,
            self.token_var,
        ):
            variable.set("")
        self.provider_wire_api_var.set("responses")
        self.auth_mode_var.set("environment")

    def _fill_provider_form(self, provider: dict[str, Any]) -> None:
        self.provider_id_var.set(provider.get("id", ""))
        self.provider_label_var.set(provider.get("label") or provider.get("name", ""))
        self.provider_name_var.set(provider.get("name") or provider.get("label", ""))
        self.provider_description_var.set(provider.get("description", ""))
        self.provider_base_url_var.set(provider.get("base_url", ""))
        self.provider_wire_api_var.set(provider.get("wire_api", "responses"))
        self.auth_mode_var.set(provider.get("auth_mode", "none"))
        self.env_key_var.set(provider.get("env_key", ""))
        self.token_var.set(provider.get("token", ""))
        self.persist_env_var.set(False)
        self.show_token_var.set(False)
        self._toggle_token_visibility()

    def _provider_from_form(self) -> dict[str, Any]:
        provider = {
            "id": self.provider_id_var.get().strip(),
            "label": self.provider_label_var.get().strip(),
            "name": self.provider_name_var.get().strip(),
            "description": self.provider_description_var.get().strip(),
            "base_url": self.provider_base_url_var.get().strip(),
            "wire_api": self.provider_wire_api_var.get().strip(),
            "auth_mode": self.auth_mode_var.get().strip() or "none",
            "env_key": self.env_key_var.get().strip(),
            "token": self.token_var.get(),
            "persist_env": self.persist_env_var.get(),
        }
        codex_config.validate_provider_record(provider)
        return provider

    def _add_provider(self) -> None:
        try:
            provider = self._provider_from_form()
            if any(item.get("id") == provider["id"] for item in self.providers):
                raise PatchError(f"Provider id already exists: {provider['id']}")
            self.providers.append(provider)
            self.provider_menu.setdefault("providers", []).append(
                {
                    "id": provider["id"],
                    "label": provider["label"],
                    "description": provider["description"],
                }
            )
            if not self.provider_menu.get("default_provider"):
                self.provider_menu["default_provider"] = provider["id"]
            self._refresh_provider_list()
            self._refresh_provider_menu_page()
            self._write_log("OK", f"Added provider {provider['id']} ({codex_config.credential_summary(provider)}).")
        except PatchError as exc:
            self._write_log("ERROR", str(exc))

    def _edit_provider(self) -> None:
        selection = self.provider_listbox.curselection()
        if not selection:
            self._write_log("ERROR", "Select a provider to edit first.")
            return
        try:
            provider = self._provider_from_form()
            index = selection[0]
            old_id = self.providers[index]["id"]
            if any(item.get("id") == provider["id"] and item is not self.providers[index] for item in self.providers):
                raise PatchError(f"Provider id already exists: {provider['id']}")
            self.providers[index] = provider
            if old_id != provider["id"]:
                if self.provider_menu.get("default_provider") == old_id:
                    self.provider_menu["default_provider"] = provider["id"]
                for item in self.provider_menu.get("providers", []):
                    if item.get("id") == old_id:
                        item["id"] = provider["id"]
                self.provider_menu["model_providers"] = {
                    slug: provider["id"] if provider_id == old_id else provider_id
                    for slug, provider_id in self.provider_menu.get("model_providers", {}).items()
                }
            self._refresh_provider_list()
            self._refresh_provider_menu_page()
            self._write_log("OK", f"Updated provider {provider['id']} ({codex_config.credential_summary(provider)}).")
        except PatchError as exc:
            self._write_log("ERROR", str(exc))

    def _remove_provider(self) -> None:
        selection = self.provider_listbox.curselection()
        if not selection:
            self._write_log("ERROR", "Select a provider to remove first.")
            return
        removed = self.providers.pop(selection[0])
        removed_id = removed["id"]
        self.provider_menu["providers"] = [
            item for item in self.provider_menu.get("providers", []) if item.get("id") != removed_id
        ]
        self.provider_menu["model_providers"] = {
            slug: provider_id
            for slug, provider_id in self.provider_menu.get("model_providers", {}).items()
            if provider_id != removed_id
        }
        if self.provider_menu.get("default_provider") == removed_id:
            self.provider_menu["default_provider"] = self.providers[0]["id"] if self.providers else ""
        self._refresh_provider_list()
        self._refresh_provider_menu_page()
        self._write_log("INFO", f"Removed provider {removed_id}.")

    def _refresh_model_list(self) -> None:
        if not hasattr(self, "model_listbox"):
            return
        self.model_listbox.delete(0, "end")
        for model in self.model_catalog.get("models", []):
            self.model_listbox.insert("end", f"{model.get('slug', '')} - {model.get('display_name', '')}")
        provider_ids = self._all_provider_ids()
        self._set_option_values(self.model_provider_menu, self.model_provider_var, provider_ids)
        model_slugs = [model.get("slug", "") for model in self.model_catalog.get("models", [])]
        self._set_option_values(self.model_template_menu, self.model_template_var, [""] + model_slugs)
        if self.model_catalog.get("models"):
            self.model_listbox.selection_set(0)
            self._fill_model_form(self.model_catalog["models"][0])
        else:
            self._clear_model_form()

    def _on_model_select(self, _event=None) -> None:
        selection = self.model_listbox.curselection()
        if selection:
            self._fill_model_form(self.model_catalog["models"][selection[0]])

    def _clear_model_form(self) -> None:
        for variable in (
            self.model_slug_var,
            self.model_display_var,
            self.model_description_var,
        ):
            variable.set("")
        self.model_provider_var.set(self.providers[0]["id"] if self.providers else "")
        self.model_template_var.set("")
        for variable in self.model_advanced_vars.values():
            variable.set("")

    def _display_advanced_value(self, value: Any) -> str:
        if isinstance(value, list):
            if value and all(isinstance(item, dict) for item in value):
                return ", ".join(str(item.get("effort", "")) for item in value)
            return ", ".join(str(item) for item in value)
        return "" if value is None else str(value)

    def _fill_model_form(self, model: dict[str, Any]) -> None:
        self.model_slug_var.set(model.get("slug", ""))
        self.model_display_var.set(model.get("display_name", ""))
        self.model_description_var.set(model.get("description", ""))
        self.model_provider_var.set(model.get("provider", self.providers[0]["id"] if self.providers else ""))
        self.model_template_var.set("")
        for key, variable in self.model_advanced_vars.items():
            variable.set(self._display_advanced_value(model.get(key, "")))

    def _model_from_form(self, original: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        model = copy.deepcopy(original) if original is not None else {}
        if original is None and self.model_template_var.get().strip():
            model = codex_config.clone_model_template(
                self.model_catalog,
                self.model_template_var.get().strip(),
                self.model_slug_var.get().strip(),
                self.model_display_var.get().strip(),
                self.model_description_var.get(),
            )
        model.update(
            {
                "slug": self.model_slug_var.get().strip(),
                "display_name": self.model_display_var.get().strip(),
                "description": self.model_description_var.get(),
                "provider": self.model_provider_var.get().strip(),
            }
        )
        for key, variable in self.model_advanced_vars.items():
            value = variable.get().strip()
            if not value:
                continue
            if key in {"input_modalities", "output_modalities"}:
                model[key] = [part.strip() for part in value.split(",") if part.strip()]
            elif key == "supported_reasoning_levels":
                model[key] = [
                    {"effort": part.strip(), "description": ""}
                    for part in value.split(",")
                    if part.strip()
                ]
            elif key == "api_availability":
                model[key] = [part.strip() for part in value.split(",") if part.strip()]
            elif key == "context_window":
                try:
                    model[key] = int(value)
                except ValueError as exc:
                    raise PatchError("Context window must be a whole number") from exc
            elif key == "supports_tools" and value.lower() in {"true", "false"}:
                model[key] = value.lower() == "true"
            else:
                model[key] = value
        codex_config.validate_model_catalog({"models": [model]})
        return model

    def _add_model(self) -> None:
        try:
            model = self._model_from_form()
            if any(item.get("slug") == model["slug"] for item in self.model_catalog.get("models", [])):
                raise PatchError(f"Model slug already exists: {model['slug']}")
            self.model_catalog = codex_config.upsert_model(self.model_catalog, model)
            self._refresh_model_list()
            self._refresh_provider_menu_page()
            self._write_log("OK", f"Added model {model['slug']}.")
        except PatchError as exc:
            self._write_log("ERROR", str(exc))

    def _edit_model(self) -> None:
        selection = self.model_listbox.curselection()
        if not selection:
            self._write_log("ERROR", "Select a model to edit first.")
            return
        try:
            original = self.model_catalog["models"][selection[0]]
            model = self._model_from_form(original)
            if any(
                item.get("slug") == model["slug"] and item is not original
                for item in self.model_catalog["models"]
            ):
                raise PatchError(f"Model slug already exists: {model['slug']}")
            self.model_catalog = codex_config.upsert_model(self.model_catalog, model)
            self._refresh_model_list()
            self._refresh_provider_menu_page()
            self._write_log("OK", f"Updated model {model['slug']}.")
        except PatchError as exc:
            self._write_log("ERROR", str(exc))

    def _remove_model(self) -> None:
        selection = self.model_listbox.curselection()
        if not selection:
            self._write_log("ERROR", "Select a model to remove first.")
            return
        slug = self.model_catalog["models"][selection[0]].get("slug", "")
        try:
            self.model_catalog = codex_config.remove_model(self.model_catalog, slug)
            self.provider_menu["model_providers"].pop(slug, None)
            self._refresh_model_list()
            self._refresh_provider_menu_page()
            self._write_log("INFO", f"Removed model {slug}.")
        except PatchError as exc:
            self._write_log("ERROR", str(exc))

    def _refresh_provider_menu_page(self) -> None:
        if not hasattr(self, "menu_provider_listbox"):
            return
        menu_providers = self.provider_menu.setdefault("providers", [])
        self.menu_provider_listbox.delete(0, "end")
        for provider in menu_providers:
            self.menu_provider_listbox.insert("end", self._provider_display(provider))
        provider_ids = self._all_provider_ids()
        self._set_option_values(self.default_provider_menu, self.default_provider_var, provider_ids)
        if self.provider_menu.get("default_provider") in provider_ids:
            self.default_provider_var.set(self.provider_menu["default_provider"])
        self._set_option_values(self.mapping_provider_menu, self.mapping_provider_var, provider_ids)
        model_slugs = [model.get("slug", "") for model in self.model_catalog.get("models", [])]
        mappings = self.provider_menu.setdefault("model_providers", {})
        for slug in list(mappings):
            if slug not in model_slugs or mappings[slug] not in provider_ids:
                mappings.pop(slug, None)
        self.mapping_listbox.delete(0, "end")
        for slug, provider_id in mappings.items():
            self.mapping_listbox.insert("end", f"{slug} -> {provider_id}")
        if menu_providers:
            self.menu_provider_listbox.selection_set(0)
            self._fill_menu_provider_form(menu_providers[0])

    def _on_menu_provider_select(self, _event=None) -> None:
        selection = self.menu_provider_listbox.curselection()
        if selection:
            self._fill_menu_provider_form(self.provider_menu["providers"][selection[0]])

    def _fill_menu_provider_form(self, provider: dict[str, Any]) -> None:
        self.menu_label_var.set(provider.get("label", ""))
        self.menu_description_var.set(provider.get("description", ""))

    def _add_menu_provider(self) -> None:
        existing = {item.get("id") for item in self.provider_menu.get("providers", [])}
        candidate = next((provider for provider in self.providers if provider.get("id") not in existing), None)
        if candidate is None:
            self._write_log("ERROR", "All configured providers are already in the patched menu.")
            return
        self.provider_menu["providers"].append(
            {
                "id": candidate["id"],
                "label": candidate.get("label") or candidate.get("name", candidate["id"]),
                "description": candidate.get("description", ""),
            }
        )
        if not self.provider_menu.get("default_provider"):
            self.provider_menu["default_provider"] = candidate["id"]
        self._refresh_provider_menu_page()

    def _edit_menu_provider(self) -> None:
        selection = self.menu_provider_listbox.curselection()
        if not selection:
            self._write_log("ERROR", "Select a menu provider to edit first.")
            return
        label = self.menu_label_var.get().strip()
        if not label:
            self._write_log("ERROR", "Menu label is required.")
            return
        item = self.provider_menu["providers"][selection[0]]
        item["label"] = label
        item["description"] = self.menu_description_var.get().strip()
        self._refresh_provider_menu_page()

    def _remove_menu_provider(self) -> None:
        selection = self.menu_provider_listbox.curselection()
        if not selection:
            self._write_log("ERROR", "Select a menu provider to remove first.")
            return
        removed = self.provider_menu["providers"].pop(selection[0])
        removed_id = removed["id"]
        self.provider_menu["model_providers"] = {
            slug: provider_id
            for slug, provider_id in self.provider_menu.get("model_providers", {}).items()
            if provider_id != removed_id
        }
        if self.provider_menu.get("default_provider") == removed_id:
            self.provider_menu["default_provider"] = (
                self.provider_menu["providers"][0]["id"] if self.provider_menu["providers"] else ""
            )
        self._refresh_provider_menu_page()

    def _update_provider_mapping(self) -> None:
        model_slug = self.mapping_model_var.get().strip()
        provider_id = self.mapping_provider_var.get().strip()
        if not model_slug or not provider_id:
            self._write_log("ERROR", "Choose both a model slug and a provider for the mapping.")
            return
        if provider_id not in set(self._all_provider_ids()):
            self._write_log("ERROR", f"Unknown provider: {provider_id}")
            return
        if model_slug not in {model.get("slug") for model in self.model_catalog.get("models", [])}:
            self._write_log("ERROR", f"Unknown model slug: {model_slug}")
            return
        self.provider_menu.setdefault("model_providers", {})[model_slug] = provider_id
        self._refresh_provider_menu_page()

    def _path_row(self, parent, row: int, label: str, variable, browse_command):
        field = tk.Frame(parent, background=CLASSIC_PANEL)
        field.grid(row=row, column=0, sticky="ew", pady=(0, 6 if row < 2 else 0))
        field.columnconfigure(0, weight=1)
        tk.Label(
            field,
            text=label,
            background=CLASSIC_PANEL,
            foreground=CLASSIC_TEXT,
            anchor="w",
            font=("Segoe UI", 8),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 2))
        entry = tk.Entry(
            field,
            textvariable=variable,
            background=CLASSIC_FIELD,
            foreground=CLASSIC_FIELD_FG,
            insertbackground=CLASSIC_FIELD_FG,
            disabledbackground="#454545",
            disabledforeground="#9b9b9b",
            relief="sunken",
            borderwidth=1,
            highlightthickness=0,
            font=("Segoe UI", 8),
        )
        entry.grid(row=1, column=0, sticky="ew", padx=(0, 6), ipady=3)
        browse = self._classic_button(field, "Browse...", browse_command)
        browse.grid(row=1, column=1, sticky="e")
        return entry, browse

    def _classic_button(self, parent, text: str, command):
        return tk.Button(
            parent,
            text=text,
            command=command,
            background=CLASSIC_BUTTON,
            foreground=CLASSIC_TEXT,
            activebackground=CLASSIC_BUTTON_ACTIVE,
            activeforeground=CLASSIC_TEXT,
            relief="raised",
            borderwidth=1,
            padx=9,
            pady=2,
            font=("Segoe UI", 8),
        )

    def _browse_root(self) -> None:
        selected = filedialog.askdirectory(title="Choose extracted ChatGPT portable root")
        if selected:
            self.app_root_var.set(selected)
            if not self.backup_dir_var.get().strip():
                self.backup_dir_var.set(str(Path(selected) / "backups"))

    def _browse_config(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="Choose provider-routing JSON",
            defaultextension=".json",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if selected:
            self.config_var.set(selected)

    def _toggle_config_entry(self) -> None:
        """Compatibility hook retained for scripts using the old GUI object."""
        self.config_var.set(self.config_var.get() or str(self._default_config_path))

    def _browse_backup(self) -> None:
        selected = filedialog.askdirectory(title="Choose ASAR backup directory")
        if selected:
            self.backup_dir_var.set(selected)

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _write_log(self, level: str, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", format_log_line(level, message) + "\n", level.upper())
        self.log.see("end")
        self.log.configure(state="disabled")

    def _configuration_paths(self) -> codex_config.ConfigPaths:
        codex_home = Path(self.codex_home_var.get().strip() or _default_codex_home()).expanduser()
        config_toml = Path(self.config_toml_var.get().strip() or codex_home / "config.toml").expanduser()
        provider_menu = Path(self.provider_menu_var.get().strip() or codex_home / "desktop-model-providers.json").expanduser()
        model_catalog = Path(self.model_catalog_var.get().strip() or codex_home / "model-catalogs" / "custom.json").expanduser()
        backup_dir = Path(self.backup_dir_var.get().strip() or codex_home / "backups").expanduser()
        defaults = codex_config.default_config_paths(codex_home)
        return codex_config.ConfigPaths(
            codex_home=codex_home,
            config_toml=config_toml,
            provider_menu=provider_menu,
            model_catalog=model_catalog,
            settings=defaults.settings,
            backup_dir=backup_dir,
        )

    def _commit_menu_controls(self) -> None:
        if hasattr(self, "default_provider_var"):
            self.provider_menu["default_provider"] = self.default_provider_var.get().strip()
        if hasattr(self, "menu_provider_listbox"):
            selection = self.menu_provider_listbox.curselection()
            if selection and self.menu_label_var.get().strip():
                item = self.provider_menu["providers"][selection[0]]
                item["label"] = self.menu_label_var.get().strip()
                item["description"] = self.menu_description_var.get().strip()

    def _configuration_bundle(self, paths: Optional[codex_config.ConfigPaths] = None) -> codex_config.ConfigBundle:
        self._commit_menu_controls()
        paths = paths or self._configuration_paths()
        return codex_config.ConfigBundle(
            paths=paths,
            providers=copy.deepcopy(self.providers),
            provider_menu=copy.deepcopy(self.provider_menu),
            model_catalog=copy.deepcopy(self.model_catalog),
            root_updates=copy.deepcopy(self.root_updates),
        )

    def _provider_records_from_toml(self, managed: dict[str, Any]) -> list[dict[str, Any]]:
        records = []
        for provider_id, values in managed.get("providers", {}).items():
            if not isinstance(values, dict):
                continue
            token = values.get("experimental_bearer_token")
            env_key = values.get("env_key", "")
            if token is not None:
                auth_mode = "plaintext"
            elif env_key:
                auth_mode = "environment"
            else:
                auth_mode = "none"
            records.append(
                {
                    "id": provider_id,
                    "name": values.get("name") or provider_id,
                    "label": values.get("name") or provider_id,
                    "description": "",
                    "base_url": values.get("base_url", ""),
                    "wire_api": values.get("wire_api", "responses"),
                    "auth_mode": auth_mode,
                    "env_key": env_key,
                    "token": token or "",
                    "persist_env": False,
                }
            )
        return records

    def _read_configuration(self, paths: codex_config.ConfigPaths):
        managed = codex_config.read_managed_toml_config(paths.config_toml)
        providers = self._provider_records_from_toml(managed)
        if paths.provider_menu.exists():
            provider_menu = codex_config.load_provider_menu(paths.provider_menu)
            codex_config.validate_provider_menu(
                provider_menu,
                {item["id"] for item in providers} | {BUILTIN_MENU_PROVIDER["id"]},
            )
        elif providers:
            root_default = managed.get("root", {}).get("model_provider")
            configured_ids = {item["id"] for item in providers}
            menu_default = root_default if root_default in configured_ids else providers[0]["id"]
            provider_menu = codex_config.build_provider_menu(
                providers,
                menu_default,
                {},
            )
            provider_menu["providers"].insert(0, copy.deepcopy(BUILTIN_MENU_PROVIDER))
            if root_default == BUILTIN_MENU_PROVIDER["id"]:
                provider_menu["default_provider"] = root_default
        else:
            provider_menu = {
                "version": 1,
                "default_provider": "openai",
                "providers": [copy.deepcopy(BUILTIN_MENU_PROVIDER)],
                "model_providers": {},
            }
        if paths.model_catalog.exists():
            model_catalog = codex_config.load_model_catalog(paths.model_catalog)
        else:
            model_catalog = codex_config.seed_catalog_from_codex()
        return providers, provider_menu, model_catalog, managed.get("root", {})

    def _load_configuration(self, loaded=None) -> None:
        if loaded is None:
            loaded = self._read_configuration(self._configuration_paths())
        self.providers, self.provider_menu, self.model_catalog, self.root_updates = loaded
        self._show_page(self._page)

    def _save_configuration(self, paths: Optional[codex_config.ConfigPaths] = None):
        return codex_config.save_configuration_bundle(self._configuration_bundle(paths))

    def _validate_configuration(self, paths: Optional[codex_config.ConfigPaths] = None) -> None:
        codex_config.validate_configuration_bundle(self._configuration_bundle(paths))

    def _paths(self) -> tuple[Path, Path, Path]:
        root_text = self.app_root_var.get().strip()
        if not root_text:
            raise PatchError("Choose the extracted portable root first")
        root = Path(root_text).expanduser()
        config_text = self.config_var.get().strip()
        config = Path(config_text).expanduser() if config_text else self._default_config_path
        backup_text = self.backup_dir_var.get().strip()
        backup = Path(backup_text).expanduser() if backup_text else root / "backups"
        return root, config, backup

    def _start_load(self) -> None:
        self._start_worker("load")

    def _start_save(self) -> None:
        if not self._confirm_plaintext_credentials():
            return
        self._start_worker("save")

    def _start_validate(self) -> None:
        self._start_worker("validate")

    def _confirm_plaintext_credentials(self) -> bool:
        if not any(provider.get("auth_mode") == "plaintext" for provider in self.providers):
            return True
        return messagebox.askyesno(
            "Experimental plaintext authentication",
            build_classic_ui_spec()["plaintext_warning"]
            + "\n\nSave this plaintext bearer token to config.toml?",
        )

    def _start_check(self) -> None:
        self._start_worker("check")

    def _start_patch(self) -> None:
        if not self._confirm_plaintext_credentials():
            return
        if not messagebox.askyesno(
            "Patch portable ChatGPT",
            "Create a backup and replace app.asar in the selected portable folder?\n\n"
            "The installed MSIX will not be changed.",
        ):
            return
        self._start_worker("patch")

    def _start_worker(self, action: str) -> None:
        if self._running:
            return
        try:
            paths = self._configuration_paths()
            root: Optional[Path] = None
            if action in {"check", "patch"}:
                root, config, backup = self._paths()
                paths = codex_config.ConfigPaths(
                    codex_home=paths.codex_home,
                    config_toml=paths.config_toml,
                    provider_menu=config,
                    model_catalog=paths.model_catalog,
                    settings=paths.settings,
                    backup_dir=backup,
                )
            bundle = self._configuration_bundle(paths) if action in {"save", "validate", "patch"} else None
        except PatchError as exc:
            self._write_log("ERROR", str(exc))
            return
        self._running = True
        self._set_busy(True)
        self.status_var.set(
            {"load": "LOADING", "save": "SAVING", "validate": "VALIDATING", "check": "CHECKING", "patch": "PATCHING"}[action]
        )
        self._worker = threading.Thread(
            target=self._worker_main,
            args=(action, root, paths, bundle),
            daemon=True,
        )
        self._worker.start()

    def _worker_main(
        self,
        action: str,
        root: Optional[Path],
        paths: codex_config.ConfigPaths,
        bundle: Optional[codex_config.ConfigBundle],
    ) -> None:
        try:
            if action == "load":
                loaded = self._read_configuration(paths)
                self._events.put(("loaded", loaded))
                self._events.put(("log", ("OK", "Loaded Codex provider, model, and menu configuration.")))
                return

            if action == "validate":
                if bundle is None:
                    raise PatchError("Configuration bundle was not prepared")
                codex_config.validate_configuration_bundle(bundle)
                self._events.put(("log", ("OK", "Configuration fields, mappings, credentials, and paths are valid.")))
                return

            if action == "save":
                if bundle is None:
                    raise PatchError("Configuration bundle was not prepared")
                result = codex_config.save_configuration_bundle(bundle)
                self._events.put(("saved", result))
                self._events.put(("log", ("OK", f"Saved provider menu: {result.provider_menu}")))
                self._events.put(("log", ("OK", f"Saved model catalog: {result.model_catalog}")))
                self._events.put(("log", ("OK", f"Saved Codex TOML: {result.config_toml}")))
                return

            if root is None:
                raise PatchError("Choose the extracted portable root first")
            self._events.put(("log", ("SCAN", f"Portable root: {root}")))
            app = locate_portable_app(root)
            self._events.put(("log", ("OK", f"Found executable: {app.executable}")))
            self._events.put(("log", ("SCAN", "Inspecting running processes and ASAR bundle markers...")))
            running = find_windows_app_processes(app.root)
            if running:
                pids = ", ".join(str(pid) for pid, _detail in running)
                self._events.put(("error", f"Portable ChatGPT is running (PIDs: {pids}). Close it first."))
                return
            if action == "check":
                patch_portable_app(app, paths.provider_menu, paths.backup_dir, check_only=True)
                self._events.put(("log", ("OK", "Layout and current ASAR patch markers are compatible.")))
                return

            if bundle is None:
                raise PatchError("Configuration bundle was not prepared")
            codex_config.save_configuration_bundle(bundle)
            self._events.put(("log", ("OK", "Configuration saved and validated before archive patch.")))
            self._events.put(("log", ("PATCH", "Creating original app.asar backup...")))
            original_backup = patch_portable_app(app, paths.provider_menu, paths.backup_dir)
            self._events.put(("log", ("OK", f"Patch complete: {app.asar}")))
            self._events.put(("log", ("OK", f"Backup: {original_backup}")))
        except PatchError as exc:
            self._events.put(("error", str(exc)))
        except Exception as exc:  # Keep unexpected GUI-thread failures visible.
            self._events.put(("error", f"Unexpected error: {exc}"))
        finally:
            self._events.put(("finished", None))

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.load_button.configure(state=state)
        self.save_button.configure(state=state)
        self.validate_button.configure(state=state)
        self.check_button.configure(state=state)
        self.patch_button.configure(state=state)
        self.clear_button.configure(state=state)

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "log":
                    level, message = payload
                    self._write_log(level, message)
                elif kind == "loaded":
                    self._load_configuration(payload)
                elif kind == "saved":
                    self._write_log("OK", "Configuration files were written atomically; existing files were backed up.")
                elif kind == "error":
                    self._write_log("ERROR", payload)
                    self.status_var.set("FAILED")
                    messagebox.showerror("Portable patch failed", payload)
                elif kind == "finished":
                    self._running = False
                    self._worker = None
                    self._set_busy(False)
                    if self.status_var.get() not in {"FAILED"}:
                        self.status_var.set("DONE")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _close_window(self) -> None:
        if self._running:
            messagebox.showwarning("Task running", "Wait for the current check or patch to finish.")
            return
        try:
            codex_config.save_gui_settings(
                self._settings_path,
                {
                    "portable_root": self.app_root_var.get().strip(),
                    "codex_home": self.codex_home_var.get().strip(),
                    "config_toml": self.config_toml_var.get().strip(),
                    "provider_menu": self.provider_menu_var.get().strip(),
                    "model_catalog": self.model_catalog_var.get().strip(),
                    "backup_dir": self.backup_dir_var.get().strip(),
                },
            )
        except PatchError as exc:
            self._write_log("ERROR", str(exc))
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_gui_parser().parse_args(argv)
    try:
        TerminalPatcherUi(args.app_root, args.config, args.backup_dir).run()
    except PatchError as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
