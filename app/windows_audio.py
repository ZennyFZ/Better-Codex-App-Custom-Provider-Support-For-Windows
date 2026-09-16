"""Small Windows-native background music controller for the patcher GUI."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Callable, Optional


class AudioError(RuntimeError):
    """Raised when the optional background music cannot be started."""


AudioCommand = Callable[[str], int]


def _send_mci_command(command: str) -> int:
    if os.name != "nt":
        raise AudioError("Background audio is available only on Windows.")
    try:
        return int(ctypes.windll.winmm.mciSendStringW(command, None, 0, 0))
    except AttributeError as exc:  # pragma: no cover - depends on the host OS.
        raise AudioError("Windows multimedia support is unavailable.") from exc


class MciAudioPlayer:
    """Play one file from ``media`` without opening a console or player window."""

    _SUPPORTED_SUFFIXES = (".mp3", ".wav")
    DEFAULT_VOLUME = 250

    def __init__(
        self,
        media_dir: Path,
        send_command: Optional[AudioCommand] = None,
    ) -> None:
        self.media_dir = Path(media_dir)
        self.track = self._find_track()
        self.alias = "better_codex_audio"
        self._send_command = send_command or _send_mci_command
        self._is_open = False
        self.enabled = False

    def _find_track(self) -> Optional[Path]:
        if not self.media_dir.is_dir():
            return None
        tracks = sorted(
            path
            for path in self.media_dir.iterdir()
            if path.is_file() and path.suffix.lower() in self._SUPPORTED_SUFFIXES
        )
        return tracks[0] if tracks else None

    def toggle(self) -> bool:
        if self.enabled:
            self.stop()
            return False
        return self.start()

    def start(self) -> bool:
        if self.track is None:
            raise AudioError(f"No .mp3 or .wav file found in {self.media_dir}")

        if not self._is_open:
            safe_path = str(self.track).replace('"', "")
            media_type = "waveaudio" if self.track.suffix.lower() == ".wav" else "mpegvideo"
            result = self._send_command(
                f'open "{safe_path}" type {media_type} alias {self.alias}'
            )
            if result:
                raise AudioError(f"Windows could not open the audio file (code {result}).")
            self._is_open = True

        result = self._send_command(
            f"setaudio {self.alias} volume to {self.DEFAULT_VOLUME}"
        )
        if result:
            self.stop()
            raise AudioError(f"Windows could not set the audio volume (code {result}).")

        result = self._send_command(f"play {self.alias} repeat")
        if result:
            self.stop()
            raise AudioError(f"Windows could not play the audio file (code {result}).")
        self.enabled = True
        return True

    def stop(self) -> None:
        if self._is_open:
            try:
                self._send_command(f"stop {self.alias}")
            finally:
                try:
                    self._send_command(f"close {self.alias}")
                finally:
                    self._is_open = False
        self.enabled = False

    def close(self) -> None:
        self.stop()
