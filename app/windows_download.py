"""Download and extract the official ChatGPT MSIX as a portable folder."""

from __future__ import annotations

import os
import shutil
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Optional
import zipfile


PORTABLE_DOWNLOAD_URL = "https://persistent.oaistatic.com/codex-app-prod/ChatGPT-x64.msix"
_CHUNK_SIZE = 1024 * 1024
DownloadProgress = Callable[[int, Optional[int]], None]


class DownloadError(RuntimeError):
    """Raised when the MSIX cannot be downloaded or safely extracted."""


def _unique_directory(parent: Path, name: str) -> Path:
    candidate = parent / name
    counter = 2
    while candidate.exists():
        candidate = parent / f"{name}-{counter}"
        counter += 1
    return candidate


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    base = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        try:
            target.relative_to(base)
        except ValueError as exc:
            raise DownloadError(
                f"The downloaded package contains an unsafe path: {member.filename}"
            ) from exc
    archive.extractall(destination)


def download_msix(
    destination_dir: Path,
    url: str = PORTABLE_DOWNLOAD_URL,
    progress: Optional[DownloadProgress] = None,
) -> Path:
    """Stream the MSIX to a temporary file inside ``destination_dir``."""
    destination = Path(destination_dir).expanduser()
    if not destination.is_dir():
        raise DownloadError(f"Download destination does not exist: {destination}")

    fd, temp_name = tempfile.mkstemp(
        prefix=".ChatGPT-x64-", suffix=".msix.download", dir=str(destination)
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Better-Codex-Windows-Portable-Patcher"},
        )
        with urllib.request.urlopen(request, timeout=120) as response, temp_path.open("wb") as target:
            raw_total = response.headers.get("Content-Length")
            try:
                total = int(raw_total) if raw_total else None
            except ValueError:
                total = None
            downloaded = 0
            while True:
                chunk = response.read(_CHUNK_SIZE)
                if not chunk:
                    break
                target.write(chunk)
                downloaded += len(chunk)
                if progress is not None:
                    progress(downloaded, total)
        if temp_path.stat().st_size == 0:
            raise DownloadError("The downloaded MSIX is empty.")
        return temp_path
    except DownloadError:
        temp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise DownloadError(f"Could not download ChatGPT-x64.msix: {exc}") from exc


def extract_msix(
    msix_path: Path,
    destination_dir: Path,
    folder_name: str = "ChatGPT-x64-portable",
) -> Path:
    """Extract an MSIX/ZIP into a new portable folder without installing AppX."""
    source = Path(msix_path).expanduser()
    destination = Path(destination_dir).expanduser()
    if not source.is_file():
        raise DownloadError(f"Downloaded MSIX does not exist: {source}")
    if not destination.is_dir():
        raise DownloadError(f"Portable destination does not exist: {destination}")

    staging = Path(tempfile.mkdtemp(prefix=f".{folder_name}.extract-", dir=str(destination)))
    try:
        with zipfile.ZipFile(source) as archive:
            _safe_extract(archive, staging)
        from windows_portable import PatchError, locate_portable_app

        try:
            locate_portable_app(staging)
        except PatchError as exc:
            raise DownloadError(
                "The downloaded package does not contain a supported portable ChatGPT layout."
            ) from exc
        final_path = _unique_directory(destination, folder_name)
        os.replace(staging, final_path)
        return final_path
    except zipfile.BadZipFile as exc:
        raise DownloadError("The downloaded file is not a valid MSIX/ZIP package.") from exc
    except DownloadError:
        raise
    except Exception as exc:
        raise DownloadError(f"Could not extract the downloaded MSIX: {exc}") from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def download_and_extract_portable(
    destination_dir: Path,
    url: str = PORTABLE_DOWNLOAD_URL,
    progress: Optional[DownloadProgress] = None,
) -> Path:
    """Download, extract, and remove the temporary MSIX package."""
    package = download_msix(destination_dir, url=url, progress=progress)
    try:
        return extract_msix(package, destination_dir)
    finally:
        package.unlink(missing_ok=True)
