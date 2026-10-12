"""Parser for the SureCam / CMSV6 ``.grec`` wrapper.

The layout below was inferred from real recordings (12 October 2026); there
is no vendor specification. Anything unfamiliar is rejected rather than
guessed, so a wrong file can never become a wrong-looking MP4.

- 512-byte file header starting ``78 56 34 12 08 00 00 00``.
- uint32 LE audio codec at offset 180 (17 = G.711 A-law observed).
- uint32 LE audio sample rate at offset 192 (8000 observed).
- Packets from byte 512, each starting on an 8-byte boundary:
    video ``00 30 64 63`` (key) / ``00 31 64 63`` (inter): 32-byte header,
        payload length at +4, timestamp (microseconds) at +16. H.265 Annex B.
    audio ``00 31 77 62``: 16-byte header, length at +4, timestamp at +8.
    metadata ``00 39 64 63``: 16-byte header, payload skipped.
- Footer / index begins ``21 06 07 08``; parsing stops there.
"""
import struct
from dataclasses import dataclass, field

from .errors import Cancelled, UnsupportedRecording

MAGIC = bytes.fromhex("7856341208000000")
FOOTER = bytes.fromhex("21060708")
KEY_FRAME = b"\x000dc"
INTER_FRAME = b"\x001dc"
AUDIO = b"\x001wb"
METADATA = b"\x009dc"
VIDEO_MARKERS = {KEY_FRAME, INTER_FRAME}
KNOWN_MARKERS = VIDEO_MARKERS | {AUDIO, METADATA}
HEVC_START = bytes.fromhex("000000014001")
ALAW = 17
ALAW_SILENCE = b"\xd5"
SUPPORTED_RATES = (8000, 16000)
MAX_PACKET = 4 * 1024 * 1024
WRAP_TOLERANCE = 1_000_000  # a jump back of more than 1 s is a uint32 wrap
MAX_AUDIO_GAP_SECONDS = 30


@dataclass
class GrecInfo:
    video_stamps: list = field(default_factory=list)  # (microseconds, is_key)
    audio_packets: int = 0
    audio_rate: int = 0
    audio_base: int = None
    gap_fill_samples: int = 0
    metadata_packets: int = 0
    complete: bool = False
    warnings: list = field(default_factory=list)

    @property
    def frames(self):
        return len(self.video_stamps)

    @property
    def duration(self):
        """Seconds from the first frame to the end of the last one."""
        if not self.video_stamps:
            return 0.0
        return (self.video_stamps[-1][0] - self.video_stamps[0][0] + 40_000) / 1_000_000


def _unwrap(raw, last, wrap):
    if last is not None and raw < last - WRAP_TOLERANCE:
        wrap += 2 ** 32
    return raw + wrap, wrap


def unpack_grec(source, video_out, audio_out, cancel=None, progress=None):
    """Split ``source`` into raw HEVC (``video_out``) and A-law (``audio_out``).

    ``progress(fraction)`` is called as the file is read. Returns GrecInfo.
    A recording that ends early (power loss, copy cut short) is converted up
    to the last whole packet and flagged in ``warnings``.
    """
    info = GrecInfo()
    total = source.stat().st_size
    last_video = last_audio = None
    video_wrap = audio_wrap = 0
    audio_samples = 0
    next_report = 0

    def truncated(where):
        info.warnings.append(
            f"The recording ends unexpectedly ({where}); it may have been cut "
            "off. Everything up to that point was converted.")

    with source.open("rb") as inp, video_out.open("wb") as video, audio_out.open("wb") as audio:
        header = inp.read(512)
        if len(header) != 512 or header[:8] != MAGIC:
            raise UnsupportedRecording(
                "This file does not have the GREC header this converter supports.")
        audio_code = struct.unpack_from("<I", header, 180)[0]
        rate = struct.unpack_from("<I", header, 192)[0]

        while True:
            position = inp.tell()
            if position >= next_report:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                if progress:
                    progress(position / total)
                next_report = position + 4 * 1024 * 1024

            block = inp.read(16)
            if not block:
                truncated("no end-of-recording index")
                break
            if block[:4] == FOOTER:
                info.complete = True
                break
            if len(block) < 16:
                truncated(f"partial packet header at byte {position:,}")
                break
            marker = block[:4]
            if marker not in KNOWN_MARKERS:
                raise UnsupportedRecording(
                    f"Unrecognised data at byte {position:,}. This GREC variant is "
                    "not supported yet; the original is unchanged.")
            size = struct.unpack_from("<I", block, 4)[0]
            if not 0 < size <= MAX_PACKET:
                raise UnsupportedRecording(f"Invalid packet size at byte {position:,}.")
            if marker in VIDEO_MARKERS:
                block += inp.read(16)
                if len(block) != 32:
                    truncated(f"partial video header at byte {position:,}")
                    break
            payload = inp.read(size)
            if len(payload) != size:
                truncated(f"partial packet at byte {position:,}")
                break

            if marker in VIDEO_MARKERS:
                if not info.video_stamps and not payload.startswith(HEVC_START):
                    raise UnsupportedRecording(
                        "This recording's video is not the H.265 variant this "
                        "converter supports yet.")
                raw = struct.unpack_from("<I", block, 16)[0]
                stamp, video_wrap = _unwrap(raw, last_video, video_wrap)
                if info.video_stamps and stamp <= info.video_stamps[-1][0]:
                    raise UnsupportedRecording(
                        f"Video timestamps go backwards at byte {position:,}; "
                        "refusing to guess playback timing.")
                info.video_stamps.append((stamp, marker == KEY_FRAME))
                last_video = raw
                video.write(payload)
            elif marker == AUDIO:
                if info.audio_base is None:
                    # Only judge the audio fields once audio actually exists;
                    # video-only recordings may leave them blank.
                    if audio_code != ALAW:
                        raise UnsupportedRecording(
                            f"Unsupported audio type {audio_code}; the original is unchanged.")
                    if rate not in SUPPORTED_RATES:
                        raise UnsupportedRecording(f"Unrecognised audio sample rate {rate}.")
                    info.audio_rate = rate
                raw = struct.unpack_from("<I", block, 8)[0]
                stamp, audio_wrap = _unwrap(raw, last_audio, audio_wrap)
                if info.audio_base is None:
                    info.audio_base = stamp
                expected = round((stamp - info.audio_base) * rate / 1_000_000)
                if expected - audio_samples > rate * 0.02:
                    gap = round((expected - audio_samples) / size) * size
                    if gap > rate * MAX_AUDIO_GAP_SECONDS:
                        raise UnsupportedRecording(
                            f"Audio has a gap longer than {MAX_AUDIO_GAP_SECONDS} "
                            "seconds; this needs manual inspection.")
                    audio.write(ALAW_SILENCE * gap)
                    audio_samples += gap
                    info.gap_fill_samples += gap
                audio.write(payload)
                audio_samples += size
                info.audio_packets += 1
                last_audio = raw
            else:
                info.metadata_packets += 1

            aligned = (inp.tell() + 7) // 8 * 8
            if aligned > total:
                truncated("missing packet padding at the end of the file")
                break
            inp.seek(aligned)

    if not info.video_stamps:
        raise UnsupportedRecording("No video frames were found in this recording.")
    if progress:
        progress(1.0)
    return info
