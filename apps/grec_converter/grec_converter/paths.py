"""Where bundled resources live and where user data is written.

Installed under Program Files the app folder is read-only, so settings,
reports and logs always go to %LOCALAPPDATA%.
"""
import os
import sys
from pathlib import Path


def resource_dir():
    """Folder holding brand/ (and bin/ when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]  # repo root


def resource(*parts):
    return resource_dir().joinpath(*parts)


def data_dir():
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    folder = Path(base) / "Koenekt" / "GREC Converter"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def reports_dir():
    folder = data_dir() / "Reports"
    folder.mkdir(exist_ok=True)
    return folder


def log_file():
    folder = data_dir() / "Logs"
    folder.mkdir(exist_ok=True)
    return folder / "app.log"
