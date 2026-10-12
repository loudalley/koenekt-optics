"""Koenekt Optics shared codec layer.

Container parsing and FFmpeg orchestration shared by the Koenekt video
products. Nothing in here touches a GUI; callers pass a progress callback and
a cancel event.
"""
from .errors import Cancelled, ConversionError, UnsupportedRecording
from .ffmpeg import find_ffmpeg
from .grec import GrecInfo, unpack_grec
from .convert import FORMATS, ConversionResult, convert_grec

__version__ = "0.1.0"

__all__ = [
    "Cancelled", "ConversionError", "UnsupportedRecording",
    "find_ffmpeg", "GrecInfo", "unpack_grec",
    "FORMATS", "ConversionResult", "convert_grec",
]
