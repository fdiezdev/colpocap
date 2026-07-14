"""FFmpeg-backed capture and snapshot utilities."""

from .capture_manager import CaptureManager
from .ffmpeg_manager import FFmpegManager
from .snapshot_manager import SnapshotManager

__all__ = ["CaptureManager", "FFmpegManager", "SnapshotManager"]

