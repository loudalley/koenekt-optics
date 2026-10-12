"""Koenekt GREC Converter entry point.

Normally opens the window. For scripted checks of an installed build:

    GrecConverter.exe --convert FILE [FILE ...] --out DIR [--format mp4|avi] --report OUT.json
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    root = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(root / "shared"), str(Path(__file__).resolve().parent)]

from grec_converter import APP_NAME  # noqa: E402
from grec_converter.paths import log_file  # noqa: E402


def setup_logging():
    try:
        logging.basicConfig(filename=log_file(), level=logging.INFO, encoding="utf-8",
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    except OSError:
        logging.basicConfig(level=logging.INFO)


def headless(args):
    from koenekt_codecs import convert_grec
    results = [convert_grec(f, args.out, args.format).to_dict() for f in args.convert]
    Path(args.report).write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0 if all(r["status"] in ("converted", "skipped") for r in results) else 1


def main():
    setup_logging()
    parser = argparse.ArgumentParser(prog="GrecConverter")
    parser.add_argument("--convert", nargs="+")
    parser.add_argument("--out")
    parser.add_argument("--format", default="mp4", choices=["mp4", "avi"])
    parser.add_argument("--report")
    args, _unknown = parser.parse_known_args()
    if args.convert:
        if not (args.out and args.report):
            return 2
        return headless(args)
    try:
        from grec_converter.app import run
        run()
    except Exception as error:
        logging.exception("Startup failed")
        try:
            from tkinter import messagebox
            messagebox.showerror(APP_NAME, f"{APP_NAME} could not start:\n{error}\n\n"
                                 f"Details: {log_file()}")
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
