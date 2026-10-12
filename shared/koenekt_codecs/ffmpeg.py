"""Locating and running the bundled FFmpeg executable."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .errors import Cancelled, ConversionError

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_ffmpeg():
    """Return the FFmpeg executable shipped with the app.

    Order: KOENEKT_FFMPEG override, ``bin/ffmpeg.exe`` beside a frozen exe,
    then the imageio-ffmpeg binary when running from source.
    """
    override = os.environ.get("KOENEKT_FFMPEG")
    if override and Path(override).is_file():
        return Path(override)
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).resolve().parent / "bin" / "ffmpeg.exe"
        if bundled.is_file():
            return bundled
    try:
        import imageio_ffmpeg
        return Path(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    raise ConversionError(
        "The FFmpeg component is missing. Reinstall the application.")


def run_ffmpeg(ffmpeg, args, cancel=None, on_time=None):
    """Run FFmpeg, reporting output time (seconds) and honouring cancellation.

    ``-progress pipe:1`` makes FFmpeg print a status block about twice a
    second, which is also when the cancel event is checked. Diagnostics go to
    a temporary file so a noisy failure can never block on a full pipe.
    """
    cmd = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
           "-stats_period", "0.5", "-progress", "pipe:1"] + [str(a) for a in args]
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as diagnostics:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=diagnostics,
                                   stdin=subprocess.DEVNULL, text=True,
                                   creationflags=NO_WINDOW)
        try:
            for line in process.stdout:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                if on_time and line.startswith("out_time_us="):
                    value = line.split("=", 1)[1].strip()
                    if value.lstrip("-").isdigit():
                        on_time(max(int(value), 0) / 1_000_000)
            code = process.wait()
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            if code:
                diagnostics.seek(0)
                detail = diagnostics.read().strip()[-2000:]
                raise ConversionError(detail or f"FFmpeg exited with code {code}")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            process.stdout.close()
