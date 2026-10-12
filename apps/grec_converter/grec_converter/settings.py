import json
import logging

from .paths import data_dir

DEFAULTS = {"output_dir": "", "format": "mp4", "include_subfolders": True}

log = logging.getLogger(__name__)


def _file():
    return data_dir() / "settings.json"


def load():
    settings = dict(DEFAULTS)
    try:
        settings.update(json.loads(_file().read_text(encoding="utf-8")))
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as error:
        log.warning("Could not read settings: %s", error)
    return settings


def save(settings):
    try:
        _file().write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except OSError as error:
        log.warning("Could not save settings: %s", error)
