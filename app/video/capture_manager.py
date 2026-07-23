"""Clinical capture naming and FFmpeg orchestration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import unicodedata
from typing import Callable

from app.config import VideoConfig
from .ffmpeg_manager import DeviceDiagnostic, FFmpegManager


def safe_filename_component(value: str, fallback: str = "SIN_DATO") -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", normalized).strip("._-")
    return (sanitized or fallback)[:48]


class CaptureManager:
    def __init__(
        self,
        config: VideoConfig,
        videos_dir: str | Path,
        ffmpeg_executable: str | None = None,
    ) -> None:
        self.videos_dir = Path(videos_dir)
        self.ffmpeg = FFmpegManager(config, ffmpeg_executable)

    @property
    def is_recording(self) -> bool:
        return self.ffmpeg.is_recording

    def build_video_path(
        self,
        *,
        patient_id: str,
        accession_number: str,
        study_instance_uid: str,
        when: datetime | None = None,
    ) -> Path:
        # Microseconds prevent a repeated capture from overwriting another one.
        moment = (when or datetime.now().astimezone()).strftime("%Y%m%d_%H%M%S_%f")
        uid_short = safe_filename_component(study_instance_uid[-12:], "SIN_UID")
        filename = "_".join(
            (
                safe_filename_component(patient_id, "SIN_PATIENT_ID"),
                safe_filename_component(accession_number, "SIN_ACCESSION"),
                moment,
                uid_short,
            )
        )
        return self.videos_dir / f"{filename}.mp4"

    def start(
        self,
        output_path: str | Path,
        preview_callback: Callable[[bytes], None] | None = None,
    ) -> Path:
        return self.ffmpeg.start_recording(output_path, preview_callback)

    def stop(self) -> Path:
        return self.ffmpeg.stop_recording()

    def cancel(self) -> Path | None:
        return self.ffmpeg.cancel_recording()

    def diagnose_devices(self) -> DeviceDiagnostic:
        return self.ffmpeg.list_video_devices()
