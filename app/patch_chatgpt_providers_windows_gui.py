"""Classic utility-style GUI for the Windows portable provider patcher."""

from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path
import queue
import threading
from typing import Any, Optional, Sequence

from windows_portable import (
    PatchError,
    find_windows_app_processes,
    locate_portable_app,
    patch_portable_app,
    restore_portable_asar,
)
from windows_audio import AudioError, MciAudioPlayer
from windows_download import PORTABLE_DOWNLOAD_URL, download_and_extract_portable

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

GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020

def format_log_line(level: str, message: str) -> str:
    return f"[{level.upper()}] {message}"


def format_drag_position(x: int, y: int) -> str:
    """Build a position-only update so Tk keeps its current size."""
    return f"+{int(x)}+{int(y)}"


def build_classic_ui_spec() -> dict[str, Any]:
    """Return the small Win32-style layout contract used by the GUI."""
    return {
        "geometry": "620x460",
        "background": CLASSIC_BG,
        "fields": ("Portable root (required):", "Backup directory (optional):"),
        "buttons": (
            "AUDIO: OFF",
            "DOWNLOAD",
            "CHECK ONLY",
            "PATCH",
            "UNDO PATCH",
            "CLEAR LOG",
        ),
        "visible_sections": ("Patch target", "Activity log"),
        "header": {
            "background": CLASSIC_BG,
            "foreground": CLASSIC_TEXT,
            "controls": ("MINIMIZE", "MAXIMIZE", "CLOSE"),
        },
        "action_labels": {
            "AUDIO": "AUDIO: OFF",
            "DOWNLOAD": "DOWNLOAD",
            "CHECK ONLY": "CHECK ONLY",
            "PATCH": "PATCH",
            "UNDO PATCH": "UNDO PATCH",
        },
        "patch_note": "CHECK ONLY scans. PATCH backs up and replaces app.asar.",
    }


def build_gui_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open the classic utility GUI for the Windows portable patcher."
    )
    parser.add_argument("--app-root", type=Path, help="Pre-fill the extracted MSIX root")
    parser.add_argument("--backup-dir", type=Path, help="Pre-fill the ASAR backup directory")
    return parser


def strip_caption_style(window_style: int) -> int:
    """Remove the native caption and resize frame from the window style."""
    return int(window_style) & ~(WS_CAPTION | WS_THICKFRAME)


def _top_level_hwnd(root) -> int:
    hwnd = int(root.winfo_id())
    if os.name != "nt":
        return hwnd
    try:
        get_parent = ctypes.windll.user32.GetParent
        get_parent.argtypes = [ctypes.c_void_p]
        get_parent.restype = ctypes.c_void_p
        return int(get_parent(ctypes.c_void_p(hwnd)) or hwnd)
    except AttributeError:  # pragma: no cover - depends on Windows support.
        return hwnd


def hide_native_title_bar(root) -> bool:
    """Remove the Windows caption so the Tkinter header owns the whole chrome."""
    if os.name != "nt":
        root.overrideredirect(True)
        return True
    try:
        user32 = ctypes.windll.user32
        get_style = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
        set_style = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
        pointer_type = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
        get_style.argtypes = [ctypes.c_void_p, ctypes.c_int]
        get_style.restype = pointer_type
        set_style.argtypes = [ctypes.c_void_p, ctypes.c_int, pointer_type]
        set_style.restype = pointer_type
        set_position = user32.SetWindowPos
        set_position.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        set_position.restype = ctypes.c_int

        hwnd = ctypes.c_void_p(_top_level_hwnd(root))
        current_style = int(get_style(hwnd, GWL_STYLE))
        new_style = strip_caption_style(current_style)
        if new_style != current_style and int(set_style(hwnd, GWL_STYLE, new_style)) == 0:
            return False
        return bool(
            set_position(
                hwnd,
                ctypes.c_void_p(0),
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
            )
        )
    except (AttributeError, OSError):  # pragma: no cover - depends on Windows support.
        return False


class TerminalPatcherUi:
    """A small Tkinter front end that keeps patching off the UI thread."""

    def __init__(
        self,
        app_root: Optional[Path] = None,
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
        self.root.minsize(560, 360)
        self.root.configure(bg=spec["background"])
        self.root.update_idletasks()
        if not hide_native_title_bar(self.root):
            self.root.overrideredirect(True)
        # Tk's geometry is the client size. Reset it after the non-client frame
        # changes so the borderless window does not grow by the old frame size.
        self.root.geometry(spec["geometry"])
        self.root.protocol("WM_DELETE_WINDOW", self._close_window)

        self.app_root_var = tk.StringVar(value=str(app_root or ""))
        initial_backup = backup_dir or (Path(app_root) / "backups" if app_root else "")
        self.backup_dir_var = tk.StringVar(value=str(initial_backup))
        self.status_var = tk.StringVar(value="READY")
        self._events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._running = False
        project_root = Path(__file__).resolve().parent.parent
        self.audio_player = MciAudioPlayer(project_root / "media")
        self._maximized = False
        self._normal_geometry: Optional[str] = None
        self._drag_offset: Optional[tuple[int, int]] = None
        self._drag_pending: Optional[tuple[int, int]] = None
        self._drag_after_id: Optional[str] = None

        self._build_widgets()
        self.root.after(100, self._drain_events)

    def _build_widgets(self) -> None:
        self._build_custom_header()
        outer = tk.Frame(self.root, background=CLASSIC_BG, padx=8, pady=8)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        self.page_frame = tk.Frame(outer, background=CLASSIC_BG)
        self.page_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self._build_setup_page()

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
        log_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 7))
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
            ("UNDO", CLASSIC_YELLOW),
            ("ERROR", CLASSIC_RED),
        ):
            self.log.tag_configure(level, foreground=color)

        footer = tk.Frame(outer, background=CLASSIC_BG)
        footer.grid(row=2, column=0, sticky="ew")
        labels = build_classic_ui_spec()["action_labels"]
        left_controls = tk.Frame(footer, background=CLASSIC_BG)
        right_controls = tk.Frame(footer, background=CLASSIC_BG)
        footer.columnconfigure(0, weight=1)
        footer.columnconfigure(1, weight=1)
        left_controls.grid(row=0, column=0, sticky="w")
        right_controls.grid(row=0, column=1, sticky="e")
        self._footer = footer
        self._left_controls = left_controls
        self._right_controls = right_controls
        self._footer_wrapped = None
        self.audio_button = self._classic_button(
            left_controls, labels["AUDIO"], self._toggle_audio
        )
        self.audio_button.pack(side="left")
        self.download_button = self._classic_button(
            left_controls, labels["DOWNLOAD"], self._start_download
        )
        self.download_button.pack(side="left", padx=(5, 0))
        self.clear_button = self._classic_button(right_controls, "CLEAR LOG", self._clear_log)
        self.clear_button.pack(side="right")
        self.undo_button = self._classic_button(
            right_controls, labels["UNDO PATCH"], self._start_undo
        )
        self.undo_button.pack(side="right", padx=(5, 0))
        self.patch_button = self._classic_button(right_controls, labels["PATCH"], self._start_patch)
        self.patch_button.pack(side="right", padx=(5, 0))
        self.check_button = self._classic_button(
            right_controls, labels["CHECK ONLY"], self._start_check
        )
        self.check_button.pack(side="right", padx=(5, 0))
        footer.bind("<Configure>", self._layout_footer)
        self.root.update_idletasks()
        self._layout_footer()

    def _build_custom_header(self) -> None:
        spec = build_classic_ui_spec()["header"]
        self.header = tk.Frame(
            self.root,
            background=spec["background"],
            height=32,
            padx=8,
        )
        self.header.pack(fill="x", side="top")
        self.header.pack_propagate(False)
        self.header_title = tk.Label(
            self.header,
            text=self.root.title(),
            background=spec["background"],
            foreground=spec["foreground"],
            anchor="w",
            font=("Segoe UI", 9, "bold"),
        )
        self.header_title.pack(side="left", fill="y", expand=True)
        controls = tk.Frame(self.header, background=spec["background"])
        controls.pack(side="right", fill="y")
        self.minimize_button = self._header_button(controls, "—", self._minimize_window)
        self.maximize_button = self._header_button(controls, "□", self._toggle_maximize_window)
        self.close_button = self._header_button(controls, "×", self._close_window)
        for button in (self.minimize_button, self.maximize_button, self.close_button):
            button.pack(side="left", fill="y")
        for widget in (self.header, self.header_title):
            widget.bind("<ButtonPress-1>", self._begin_window_drag)
            widget.bind("<B1-Motion>", self._drag_window)
            widget.bind("<Double-Button-1>", self._toggle_maximize_window)

    def _header_button(self, parent, text: str, command):
        return tk.Button(
            parent,
            text=text,
            command=command,
            background=CLASSIC_BG,
            foreground=CLASSIC_TEXT,
            activebackground=CLASSIC_BUTTON_ACTIVE,
            activeforeground=CLASSIC_TEXT,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=9,
            pady=0,
            font=("Segoe UI Symbol", 10),
        )

    def _minimize_window(self) -> None:
        self.root.iconify()

    def _toggle_maximize_window(self, _event=None) -> None:
        self._cancel_pending_drag()
        self._drag_offset = None
        if self._maximized:
            self.root.state("normal")
            if self._normal_geometry:
                self.root.geometry(self._normal_geometry)
            self._maximized = False
            self.maximize_button.configure(text="□")
            return
        self._normal_geometry = self.root.geometry()
        self.root.state("zoomed")
        self._maximized = True
        self.maximize_button.configure(text="❐")

    def _begin_window_drag(self, event) -> None:
        if self._maximized:
            return
        self._cancel_pending_drag()
        self._drag_offset = (
            event.x_root - self.root.winfo_rootx(),
            event.y_root - self.root.winfo_rooty(),
        )

    def _drag_window(self, event) -> None:
        if self._maximized or self._drag_offset is None:
            return
        x_offset, y_offset = self._drag_offset
        self._drag_pending = (
            event.x_root - x_offset,
            event.y_root - y_offset,
        )
        if self._drag_after_id is None:
            self._drag_after_id = self.root.after(12, self._apply_drag_position)

    def _apply_drag_position(self) -> None:
        self._drag_after_id = None
        pending = self._drag_pending
        self._drag_pending = None
        if pending is None or self._maximized:
            return
        self.root.geometry(format_drag_position(*pending))

    def _cancel_pending_drag(self) -> None:
        if self._drag_after_id is not None:
            try:
                self.root.after_cancel(self._drag_after_id)
            except tk.TclError:
                pass
            self._drag_after_id = None
        self._drag_pending = None

    def _layout_footer(self, _event=None) -> None:
        """Wrap the action group at compact widths instead of clipping buttons."""
        width = self._footer.winfo_width()
        if width <= 1:
            return
        required = self._left_controls.winfo_reqwidth() + self._right_controls.winfo_reqwidth() + 8
        wrapped = width < required
        if wrapped == self._footer_wrapped:
            return
        self._footer_wrapped = wrapped
        if wrapped:
            self._left_controls.grid(row=0, column=0, columnspan=2, sticky="w")
            self._right_controls.grid(row=1, column=0, columnspan=2, sticky="e", pady=(5, 0))
        else:
            self._left_controls.grid(row=0, column=0, columnspan=1, sticky="w")
            self._right_controls.grid(row=0, column=1, columnspan=1, sticky="e", pady=0)

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

    def _build_setup_page(self) -> None:
        page = tk.Frame(self.page_frame, background=CLASSIC_BG)
        page.pack(fill="both", expand=True)

        locations = self._label_frame(page, "Patch target")
        locations.pack(fill="x")
        tk.Label(
            locations,
            text=build_classic_ui_spec()["patch_note"],
            background=CLASSIC_PANEL,
            foreground=CLASSIC_MUTED,
            justify="left",
            anchor="w",
            wraplength=580,
            font=("Segoe UI", 8),
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        locations.columnconfigure(0, weight=1)
        self.app_root_entry, self.app_root_browse = self._path_row(
            locations, 1, "Portable root (required):", self.app_root_var, self._browse_root
        )
        self.backup_entry, self.backup_browse = self._path_row(
            locations, 2, "Backup directory (optional):", self.backup_dir_var, self._browse_backup
        )

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

    def _paths(self) -> tuple[Path, Path]:
        root_text = self.app_root_var.get().strip()
        if not root_text:
            raise PatchError("Choose the extracted portable root first")
        root = Path(root_text).expanduser()
        backup_text = self.backup_dir_var.get().strip()
        backup = Path(backup_text).expanduser() if backup_text else root / "backups"
        return root, backup

    def _start_check(self) -> None:
        self._start_worker("check")

    def _toggle_audio(self) -> None:
        try:
            enabled = self.audio_player.toggle()
        except AudioError as exc:
            self._write_log("ERROR", str(exc))
            self.audio_button.configure(text="AUDIO: OFF")
            return
        self.audio_button.configure(text="AUDIO: ON" if enabled else "AUDIO: OFF")

    def _start_download(self) -> None:
        selected = filedialog.askdirectory(
            title="Choose a folder for portable ChatGPT"
        )
        if selected:
            self._start_worker("download", destination=Path(selected))

    def _start_undo(self) -> None:
        if not messagebox.askyesno(
            "Undo portable patch",
            "Restore the newest original app.asar backup?\n\n"
            "The backup will be kept. The installed MSIX will not be changed.",
        ):
            return
        self._start_worker("undo")

    def _start_patch(self) -> None:
        if not messagebox.askyesno(
            "Patch portable ChatGPT",
            "Create a backup and replace app.asar in the selected portable folder?\n\n"
            "The installed MSIX will not be changed.\n"
            "Provider and model files will not be created or modified.",
        ):
            return
        self._start_worker("patch")

    def _start_worker(self, action: str, destination: Optional[Path] = None) -> None:
        if self._running:
            return
        try:
            if action not in {"check", "patch", "download", "undo"}:
                raise PatchError(f"Unsupported GUI action: {action}")
            if action == "download":
                if destination is None:
                    raise PatchError("Choose a destination folder for portable ChatGPT first")
                root, backup = None, destination / "backups"
            else:
                root, backup = self._paths()
        except PatchError as exc:
            self._write_log("ERROR", str(exc))
            return
        self._running = True
        self._set_busy(True)
        self.status_var.set(
            {
                "check": "CHECKING",
                "patch": "PATCHING",
                "download": "DOWNLOADING",
                "undo": "UNDOING",
            }[action]
        )
        self._worker = threading.Thread(
            target=self._worker_main,
            args=(action, root, backup, destination),
            daemon=True,
        )
        self._worker.start()

    def _worker_main(
        self,
        action: str,
        root: Optional[Path],
        backup: Path,
        destination: Optional[Path] = None,
    ) -> None:
        try:
            if action == "download":
                if destination is None:
                    raise PatchError("Choose a destination folder for portable ChatGPT first")
                self._events.put(("log", ("SCAN", "Downloading ChatGPT-x64.msix...")))
                portable_root = download_and_extract_portable(
                    destination,
                    url=PORTABLE_DOWNLOAD_URL,
                )
                self._events.put(("downloaded", portable_root))
                self._events.put(("log", ("OK", f"Portable folder ready: {portable_root}")))
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
                patch_portable_app(app, backup, check_only=True)
                self._events.put(("log", ("OK", "Layout and current ASAR patch markers are compatible.")))
                return

            if action == "undo":
                self._events.put(("log", ("UNDO", "Restoring the newest original app.asar backup...")))
                restored_backup = restore_portable_asar(app, backup)
                self._events.put(("log", ("OK", f"Undo complete: {app.asar}")))
                self._events.put(("log", ("OK", f"Backup kept: {restored_backup}")))
                return

            self._events.put(("log", ("PATCH", "Creating original app.asar backup...")))
            original_backup = patch_portable_app(app, backup)
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
        self.check_button.configure(state=state)
        self.patch_button.configure(state=state)
        self.clear_button.configure(state=state)
        self.download_button.configure(state=state)
        self.audio_button.configure(state=state)
        self.undo_button.configure(state=state)

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "log":
                    level, message = payload
                    self._write_log(level, message)
                elif kind == "downloaded":
                    portable_root = Path(payload)
                    self.app_root_var.set(str(portable_root))
                    self.backup_dir_var.set(str(portable_root / "backups"))
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
            self._cancel_pending_drag()
        finally:
            try:
                self.audio_player.close()
            finally:
                self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_gui_parser().parse_args(argv)
    try:
        TerminalPatcherUi(args.app_root, args.backup_dir).run()
    except PatchError as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
