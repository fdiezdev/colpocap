"""Extract a deterministic still frame from a locally recorded MP4."""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
import subprocess

from PIL import Image, UnidentifiedImageError

from .ffmpeg_locator import FFmpegInstallation, FFmpegLocatorError, locate_ffmpeg

LOGGER = logging.getLogger(__name__)


class SnapshotError(RuntimeError):
    pass


class SnapshotManager:
    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable
        self._installation: FFmpegInstallation | None = None

    def check_installed(self) -> Path:
        if self._installation is None:
            try:
                self._installation = locate_ffmpeg(self.executable)
            except FFmpegLocatorError as exc:
                raise SnapshotError(str(exc)) from exc
        return self._installation.executable

    def extract(
        self,
        video_path: str | Path,
        output_path: str | Path,
        timestamp_seconds: float = 1.0,
    ) -> Path:
        video = Path(video_path)
        output = Path(output_path)
        if not video.is_file() or video.stat().st_size == 0:
            raise SnapshotError(f"El MP4 no existe o está vacío: {video}")
        if timestamp_seconds < 0:
            raise SnapshotError("El timestamp del snapshot no puede ser negativo.")
        executable = self.check_installed()
        output.parent.mkdir(parents=True, exist_ok=True)
        command = [
            str(executable),
            "-hide_banner",
            "-y",
            "-ss",
            f"{timestamp_seconds:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output),
        ]
        LOGGER.info("Extrayendo snapshot: %s", subprocess.list2cmdline(command))
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        if completed.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            output.unlink(missing_ok=True)
            tail = completed.stderr[-1500:].strip()
            raise SnapshotError(
                f"FFmpeg no pudo extraer el snapshot (código {completed.returncode}): {tail}"
            )
        LOGGER.info("Snapshot creado: %s", output)
        return output

    def save_live_frame(self, jpeg_data: bytes, output_path: str | Path) -> Path:
        """Validate and persist the exact JPEG frame shown in the live preview."""
        if not jpeg_data:
            raise SnapshotError("La cámara todavía no entregó una imagen para capturar.")
        try:
            with Image.open(BytesIO(jpeg_data)) as image:
                image.verify()
                if image.format != "JPEG":
                    raise SnapshotError("El frame de cámara recibido no es JPEG.")
        except SnapshotError:
            raise
        except (OSError, UnidentifiedImageError) as exc:
            raise SnapshotError(f"El frame de cámara no es una imagen válida: {exc}") from exc

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        try:
            temporary.write_bytes(jpeg_data)
            temporary.replace(output)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise SnapshotError(f"No se pudo guardar el snapshot {output}: {exc}") from exc
        LOGGER.info("Snapshot en vivo creado: %s", output)
        return output
