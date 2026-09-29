"""
updater.py

Checks GitHub Releases for a newer build, downloads the attached
.exe, and replaces the currently-running one.

Windows can't overwrite a running .exe, so the "install" step writes
a tiny batch script that waits for this process to exit, swaps the
file, relaunches the app, then deletes itself.

Uses only the standard library (urllib/json) so no extra dependency
is needed in the frozen build.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from core.version import GITHUB_OWNER, GITHUB_REPO, RELEASE_ASSET_NAME

API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
USER_AGENT = "SourceMaterialFetcher-UpdateChecker"


class UpdateCheckError(Exception):
    pass


@dataclass
class UpdateInfo:
    tag: str
    version: tuple
    download_url: str
    notes: str


def _parse_version(tag: str) -> tuple:
    """'v1.2.3' or '1.2.3' -> (1, 2, 3). Non-numeric parts are ignored."""
    nums = re.findall(r"\d+", tag)
    return tuple(int(n) for n in nums) if nums else (0,)


def check_for_update(current_version: str) -> UpdateInfo | None:
    """Returns UpdateInfo if a newer release is available, else None.
    Raises UpdateCheckError on network/parse failure.
    """
    req = urllib.request.Request(API_URL, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        raise UpdateCheckError(f"Could not reach GitHub: {e}") from e
    except json.JSONDecodeError as e:
        raise UpdateCheckError(f"Unexpected response from GitHub: {e}") from e

    tag = data.get("tag_name", "")
    if not tag:
        raise UpdateCheckError("GitHub response had no release tag.")

    remote_version = _parse_version(tag)
    local_version = _parse_version(current_version)

    if remote_version <= local_version:
        return None

    asset_url = None
    for asset in data.get("assets", []):
        if asset.get("name") == RELEASE_ASSET_NAME:
            asset_url = asset.get("browser_download_url")
            break

    if not asset_url:
        raise UpdateCheckError(
            f"Release {tag} exists but has no '{RELEASE_ASSET_NAME}' attached."
        )

    return UpdateInfo(
        tag=tag,
        version=remote_version,
        download_url=asset_url,
        notes=data.get("body", "") or "",
    )


def download_update(info: UpdateInfo, progress_cb=None) -> Path:
    """Downloads the new exe to a temp file and returns its path.
    progress_cb(bytes_read, total_bytes) is called periodically if given.
    """
    req = urllib.request.Request(info.download_url, headers={"User-Agent": USER_AGENT})
    tmp_dir = Path(tempfile.mkdtemp(prefix="smf_update_"))
    dest = tmp_dir / RELEASE_ASSET_NAME

    with urllib.request.urlopen(req, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        read = 0
        chunk_size = 1024 * 256
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                read += len(chunk)
                if progress_cb:
                    progress_cb(read, total)

    return dest


def is_frozen() -> bool:
    """True when running as a PyInstaller-built .exe."""
    return bool(getattr(sys, "frozen", False))


def apply_update_and_restart(new_exe_path: Path) -> None:
    """Only valid when running as a frozen .exe. Writes a helper batch
    script that waits for this process to exit, replaces the current
    exe with new_exe_path, relaunches it, and cleans up after itself.
    Does NOT exit the app itself -- the caller should quit right after
    calling this so the batch script's wait succeeds quickly.
    """
    if not is_frozen():
        raise RuntimeError("apply_update_and_restart() only works in a built .exe, not `python main.py`.")

    current_exe = Path(sys.executable)
    bat_path = Path(tempfile.gettempdir()) / "smf_apply_update.bat"

    script = f"""@echo off
:wait
tasklist /fi "PID eq {_current_pid()}" | find "{_current_pid()}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait
)
move /y "{new_exe_path}" "{current_exe}" >nul
start "" "{current_exe}"
del "%~f0"
"""
    bat_path.write_text(script, encoding="utf-8")

    subprocess.Popen(
        ["cmd", "/c", str(bat_path)],
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        close_fds=True,
    )


def _current_pid() -> int:
    import os
    return os.getpid()
