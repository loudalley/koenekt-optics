"""GREC -> MP4 / AVI conversion pipeline.

1. Split the GREC wrapper into raw HEVC + A-law, keeping every timestamp.
2. FFmpeg stream-copies the HEVC into a template MP4 (codec config, packet
   boundaries). Its assumed 25 fps is thrown away in the next step.
3. PyAV remuxes each packet with the original microsecond timestamps.
4. FFmpeg encodes the timed video plus aligned audio to the target format.
5. The whole output is decoded and checked before it gets its final name.

Originals are only ever opened read-only, existing outputs are never
overwritten, and a failed or cancelled run leaves no partial file behind.
"""
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path

from .errors import Cancelled, ConversionError
from .ffmpeg import find_ffmpeg, run_ffmpeg
from .grec import unpack_grec

MICROSECONDS = Fraction(1, 1_000_000)

# Output profiles. MP4 keeps the recording's variable frame timing; AVI cannot
# carry that, so it is resampled to a constant 25 fps (frames are repeated,
# never dropped, and the duration is unchanged).
FORMATS = {
    "mp4": {
        "label": "MP4 (H.264 / AAC)",
        "video": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                  "-pix_fmt", "yuv420p", "-fps_mode", "vfr"],
        "audio": ["-c:a", "aac", "-b:a", "64k", "-ar", "16000"],
        "extra": ["-movflags", "+faststart"],
        "output_factor": 3.2,
    },
    "avi": {
        "label": "AVI (Xvid / MP3)",
        "video": ["-c:v", "libxvid", "-q:v", "4", "-vtag", "XVID",
                  "-pix_fmt", "yuv420p", "-fps_mode", "cfr", "-r", "25"],
        "audio": ["-c:a", "libmp3lame", "-b:a", "64k", "-ar", "44100"],
        "extra": [],
        "output_factor": 4.0,
    },
}
TEMP_FACTOR = 2.2   # raw HEVC + template MP4 coexist briefly; then template + timed

# Share of the progress bar given to each stage.
STAGES = {"unpack": (0.00, 0.15), "remux": (0.15, 0.22),
          "encode": (0.22, 0.90), "verify": (0.90, 1.00)}


@dataclass
class ConversionResult:
    source: str
    status: str                      # converted | skipped | failed | cancelled
    output: str = ""
    message: str = ""
    warnings: list = field(default_factory=list)
    seconds: float = 0.0
    video_frames: int = 0
    audio_packets: int = 0
    audio_gap_fill_seconds: float = 0.0

    def to_dict(self):
        return asdict(self)


def output_path(source, output_dir, fmt):
    return Path(output_dir) / (Path(source).stem + "." + fmt)


def _check_space(source, output_dir, temp_root, fmt):
    size = source.stat().st_size
    need_temp = size * TEMP_FACTOR
    need_out = size * FORMATS[fmt]["output_factor"]
    temp_drive = Path(temp_root).resolve().anchor.lower()
    out_drive = Path(output_dir).resolve().anchor.lower()
    checks = [(output_dir, need_out + (need_temp if temp_drive == out_drive else 0))]
    if temp_drive != out_drive:
        checks.append((temp_root, need_temp))
    for folder, need in checks:
        free = shutil.disk_usage(folder).free
        if free < need:
            raise ConversionError(
                f"Not enough free disk space on {Path(folder).resolve().anchor} "
                f"(about {need / 1e9:.1f} GB needed, {free / 1e9:.1f} GB free).")


def _remux_with_timestamps(template, timed, info, cancel, report):
    import av  # imported lazily so the GUI can start and report a missing component

    stamps = info.video_stamps
    first = stamps[0][0]
    with av.open(str(template)) as original, av.open(str(timed), "w") as out:
        stream = out.add_stream_from_template(original.streams.video[0])
        stream.time_base = MICROSECONDS
        n = 0
        for packet in original.demux(video=0):
            if not packet.size:
                continue
            if n >= len(stamps):
                raise ConversionError("Unexpected extra video frame; refusing to guess timing.")
            stamp, key = stamps[n]
            if bool(packet.is_keyframe) != key:
                raise ConversionError("Video frames do not match the recording index.")
            packet.stream = stream
            packet.time_base = MICROSECONDS
            packet.pts = packet.dts = stamp - first
            packet.duration = stamps[n + 1][0] - stamp if n + 1 < len(stamps) else 40_000
            out.mux(packet)
            n += 1
            if n % 500 == 0:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                report(n / len(stamps))
        if n != len(stamps):
            raise ConversionError("Frame count does not match the recording.")


def _verify(ffmpeg, working, fmt, info, cancel, on_time):
    import av

    run_ffmpeg(ffmpeg, ["-xerror", "-i", working, "-map", "0:v:0", "-map", "0:a?",
                        "-f", "null", "NUL"], cancel, on_time)
    with av.open(str(working)) as checked:
        if not checked.streams.video:
            raise ConversionError("The converted file has no video stream.")
        duration = (checked.duration or 0) / 1_000_000
        if fmt == "mp4":
            if checked.streams.video[0].frames != info.frames:
                raise ConversionError("The converted video has an unexpected frame count.")
        elif abs(duration - info.duration) > max(1.0, info.duration * 0.01):
            raise ConversionError(
                f"The converted video lasts {duration:.1f} s instead of {info.duration:.1f} s.")
        if info.audio_packets and not checked.streams.audio:
            raise ConversionError("The converted file is missing its audio track.")
    return duration


def convert_grec(source, output_dir, fmt="mp4", progress=None, cancel=None,
                 ffmpeg=None, temp_root=None):
    """Convert one recording. Never raises for per-file problems: the outcome
    is in the returned ConversionResult. Only ``Cancelled`` is re-raised as a
    'cancelled' result so the caller can stop the batch.

    ``progress(fraction, stage_text)`` is called from this thread.
    """
    source = Path(source)
    output_dir = Path(output_dir)
    if fmt not in FORMATS:
        raise ValueError(f"Unknown format {fmt!r}")
    profile = FORMATS[fmt]
    destination = output_path(source, output_dir, fmt)
    result = ConversionResult(source=str(source), status="failed", output=str(destination))

    def report(stage, fraction, text):
        if progress:
            lo, hi = STAGES[stage]
            progress(lo + (hi - lo) * min(max(fraction, 0.0), 1.0), text)

    if destination.exists():
        result.status = "skipped"
        result.message = f"{destination.name} already exists in the output folder."
        return result

    working = output_dir / f"{source.stem}.working-{uuid.uuid4().hex[:8]}.{fmt}"
    temp_root = Path(temp_root or tempfile.gettempdir())
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        ffmpeg = Path(ffmpeg) if ffmpeg else find_ffmpeg()
        _check_space(source, output_dir, temp_root, fmt)

        with tempfile.TemporaryDirectory(prefix="koenekt-grec-", dir=temp_root) as folder:
            temp = Path(folder)
            hevc, alaw = temp / "video.hevc", temp / "audio.alaw"
            template, timed = temp / "template.mp4", temp / "timed.mp4"

            info = unpack_grec(source, hevc, alaw, cancel,
                               lambda f: report("unpack", f, "Reading recording"))
            result.warnings = list(info.warnings)
            result.video_frames = info.frames
            result.audio_packets = info.audio_packets

            report("remux", 0, "Restoring original frame timing")
            run_ffmpeg(ffmpeg, ["-r", "25", "-i", hevc, "-c:v", "copy", "-tag:v", "hvc1",
                                template], cancel)
            hevc.unlink()
            _remux_with_timestamps(template, timed, info, cancel,
                                   lambda f: report("remux", f, "Restoring original frame timing"))
            template.unlink()

            args = ["-i", timed]
            if info.audio_packets:
                offset = (info.audio_base - info.video_stamps[0][0]) / 1_000_000
                args += ["-itsoffset", f"{offset:.6f}", "-f", "alaw",
                         "-ar", str(info.audio_rate), "-ac", "1", "-i", alaw]
            args += ["-map", "0:v:0"]
            if info.audio_packets:
                args += ["-map", "1:a:0"] + profile["audio"]
            args += profile["video"] + profile["extra"] + [working]
            total = info.duration or 1
            run_ffmpeg(ffmpeg, args, cancel,
                       lambda t: report("encode", t / total, f"Encoding {fmt.upper()}"))

            report("verify", 0, "Checking the whole file")
            result.seconds = _verify(ffmpeg, working, fmt, info, cancel,
                                     lambda t: report("verify", t / total, "Checking the whole file"))

        if destination.exists():  # appeared while we were working; never overwrite
            result.status = "skipped"
            result.message = f"{destination.name} appeared in the output folder during conversion."
            return result
        working.rename(destination)
        result.status = "converted"
        if info.audio_rate:
            result.audio_gap_fill_seconds = round(info.gap_fill_samples / info.audio_rate, 3)
        result.message = "Converted" + (" with warnings" if result.warnings else "")
        report("verify", 1, "Done")
        return result
    except Cancelled:
        result.status = "cancelled"
        result.message = "Cancelled"
        return result
    except ConversionError as error:
        result.message = str(error)
        return result
    except OSError as error:
        result.message = f"{error.strerror or error}: {error.filename or ''}".strip(": ")
        return result
    except Exception as error:  # unexpected: keep the batch going, surface the detail
        result.message = f"Unexpected error: {type(error).__name__}: {error}"
        return result
    finally:
        try:
            if working.exists():
                working.unlink()
        except OSError:
            pass
