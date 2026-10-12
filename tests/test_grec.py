"""Parser tests on synthetic GREC files (no real recordings in the repo)."""
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))

from koenekt_codecs.grec import (AUDIO, FOOTER, HEVC_START, INTER_FRAME, KEY_FRAME,  # noqa: E402
                                 MAGIC, METADATA, unpack_grec)
from koenekt_codecs.errors import UnsupportedRecording  # noqa: E402


def header(audio_code=17, rate=8000):
    h = bytearray(512)
    h[:8] = MAGIC
    struct.pack_into("<I", h, 180, audio_code)
    struct.pack_into("<I", h, 192, rate)
    return bytes(h)


def pad(data):
    return data + b"\0" * (-len(data) % 8)


def video(marker, stamp, payload):
    h = bytearray(32)
    h[:4] = marker
    struct.pack_into("<I", h, 4, len(payload))
    struct.pack_into("<I", h, 16, stamp)
    return pad(bytes(h) + payload)


def audio(stamp, payload=b"\x55" * 320):
    h = bytearray(16)
    h[:4] = AUDIO
    struct.pack_into("<I", h, 4, len(payload))
    struct.pack_into("<I", h, 8, stamp)
    return pad(bytes(h) + payload)


def meta():
    h = bytearray(16)
    h[:4] = METADATA
    struct.pack_into("<I", h, 4, 5)
    return pad(bytes(h) + b"meta!")


FRAME = HEVC_START + b"\x0c" * 20


def write(tmp_path, *parts, footer=True):
    path = tmp_path / "t.grec"
    path.write_bytes(b"".join(parts) + (FOOTER + b"\0" * 12 if footer else b""))
    return path


def run(tmp_path, path):
    return unpack_grec(path, tmp_path / "v.hevc", tmp_path / "a.alaw")


def test_complete_recording(tmp_path):
    p = write(tmp_path, header(), video(KEY_FRAME, 1000, FRAME), audio(1000), meta(),
              video(INTER_FRAME, 41000, b"\x01" * 9), video(INTER_FRAME, 121000, b"\x02" * 9))
    info = run(tmp_path, p)
    assert info.complete and not info.warnings
    assert [s for s, _ in info.video_stamps] == [1000, 41000, 121000]
    assert info.video_stamps[0][1] is True
    assert info.audio_packets == 1 and info.metadata_packets == 1
    assert (tmp_path / "v.hevc").read_bytes() == FRAME + b"\x01" * 9 + b"\x02" * 9


def test_missing_footer_is_flagged(tmp_path):
    p = write(tmp_path, header(), video(KEY_FRAME, 0, FRAME), footer=False)
    info = run(tmp_path, p)
    assert not info.complete
    assert "cut off" in info.warnings[0]


def test_truncated_packet_keeps_earlier_frames(tmp_path):
    p = write(tmp_path, header(), video(KEY_FRAME, 0, FRAME),
              video(INTER_FRAME, 40000, b"\x01" * 50)[:40], footer=False)
    info = run(tmp_path, p)
    assert info.frames == 1 and info.warnings


def test_video_only_ignores_blank_audio_fields(tmp_path):
    p = write(tmp_path, header(audio_code=0, rate=0), video(KEY_FRAME, 0, FRAME))
    info = run(tmp_path, p)
    assert info.audio_packets == 0 and info.frames == 1


def test_unsupported_audio_rejected(tmp_path):
    p = write(tmp_path, header(audio_code=99), video(KEY_FRAME, 0, FRAME), audio(0))
    with pytest.raises(UnsupportedRecording, match="audio type"):
        run(tmp_path, p)


def test_audio_gap_filled_with_silence(tmp_path):
    p = write(tmp_path, header(), video(KEY_FRAME, 0, FRAME), audio(0), audio(200_000))
    info = run(tmp_path, p)
    assert info.gap_fill_samples == 1280  # 160 ms at 8 kHz, whole packets


def test_bad_header_rejected(tmp_path):
    p = tmp_path / "x.grec"
    p.write_bytes(b"\0" * 600)
    with pytest.raises(UnsupportedRecording, match="header"):
        run(tmp_path, p)


def test_unknown_marker_rejected(tmp_path):
    p = write(tmp_path, header(), video(KEY_FRAME, 0, FRAME), b"ABCD" + b"\x10\0\0\0" + b"\0" * 8)
    with pytest.raises(UnsupportedRecording, match="Unrecognised"):
        run(tmp_path, p)


def test_non_hevc_rejected(tmp_path):
    p = write(tmp_path, header(), video(KEY_FRAME, 0, b"\0\0\0\x01\x67" + b"\0" * 8))
    with pytest.raises(UnsupportedRecording, match="H.265"):
        run(tmp_path, p)


def test_backwards_timestamps_rejected(tmp_path):
    p = write(tmp_path, header(), video(KEY_FRAME, 50000, FRAME), video(INTER_FRAME, 40000, b"\1"))
    with pytest.raises(UnsupportedRecording, match="backwards"):
        run(tmp_path, p)
