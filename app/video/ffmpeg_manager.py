"""Safe lifecycle management for a single FFmpeg recording process."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import platform
import subprocess
import time
from typing import IO

from app.config import VideoConfig
from .ffmpeg_locator import FFmpegInstallation, FFmpegLocatorError, locate_ffmpeg

LOGGER = logging.getLogger(__name__)


class FFmpegError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeviceDiagnostic:
    command: tuple[str, ...]
    output: str
    executable: str = ""
    version: str = ""


class FFmpegManager:
    def __init__(self, config: VideoConfig, executable: str | None = None) -> None:
        self.config = config
        self.executable = executable
        self._installation: FFmpegInstallation | None = None
        self._process: subprocess.Popen[str] | None = None
        self._log_handle: IO[str] | None = None
        self._current_output: Path | None = None
        self._current_log: Path | None = None

    def check_installed(self) -> Path:
        if self._installation is None:
            try:
                self._installation = locate_ffmpeg(self.executable)
            except FFmpegLocatorError as exc:
                raise FFmpegError(str(exc)) from exc
        return self._installation.executable

    @property
    def is_recording(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start_recording(self, output_path: str | Path) -> Path:
        if self.is_recording:
            raise FFmpegError("Ya existe una grabación FFmpeg en curso.")
        executable = self.check_installed()
        if not self.config.device_name:
            raise FFmpegError(
                "No se configuró video.device_name en config/settings.json."
            )

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        command = self._capture_command(output, executable)
        log_path = output.with_suffix(".ffmpeg.log")
        self._log_handle = log_path.open("a", encoding="utf-8")
        creation_flags = (
            subprocess.CREATE_NO_WINDOW
            if platform.system() == "Windows"
            and hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0
        )
        LOGGER.info("Iniciando FFmpeg: %s", subprocess.list2cmdline(command))
        try:
            self._process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=self._log_handle,
                text=True,
                encoding="utf-8",
                creationflags=creation_flags,
            )
        except OSError as exc:
            self._close_log()
            raise FFmpegError(f"No se pudo iniciar FFmpeg: {exc}") from exc
        self._current_output = output
        self._current_log = log_path
        time.sleep(0.4)
        if self._process.poll() is not None:
            code = self._process.returncode
            self._close_log()
            self._process = None
            raise FFmpegError(
                f"FFmpeg terminó al iniciar (código {code}). "
                f"Revise el dispositivo y el log {log_path}."
            )
        LOGGER.info("Grabación iniciada: %s", output)
        return output

    def stop_recording(self, timeout_seconds: float = 15.0) -> Path:
        process = self._process
        output = self._current_output
        if process is None or output is None:
            raise FFmpegError("No hay una grabación FFmpeg activa.")
        forced = False
        try:
            if process.poll() is None and process.stdin is not None:
                process.stdin.write("q\n")
                process.stdin.flush()
            try:
                return_code = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                forced = True
                LOGGER.warning("FFmpeg no respondió a 'q'; se enviará terminate().")
                process.terminate()
                try:
                    return_code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    return_code = process.wait(timeout=5)
        finally:
            if process.stdin is not None:
                process.stdin.close()
            self._close_log()
            self._process = None
            self._current_output = None

        if forced:
            raise FFmpegError(
                f"FFmpeg debió detenerse forzadamente. El archivo se conserva para "
                f"diagnóstico, pero la captura se marca fallida. Revise {self._current_log}."
            )
        if return_code != 0:
            raise FFmpegError(
                f"FFmpeg terminó con código {return_code}. Revise {self._current_log}."
            )
        if not output.is_file() or output.stat().st_size == 0:
            raise FFmpegError(f"FFmpeg no produjo un MP4 válido en {output}.")
        LOGGER.info("Grabación finalizada: %s (%s bytes)", output, output.stat().st_size)
        return output

    def list_video_devices(self) -> DeviceDiagnostic:
        executable = self.check_installed()
        system = platform.system()
        if system == "Windows":
            command = [
                str(executable),
                "-hide_banner",
                "-list_devices",
                "true",
                "-f",
                "dshow",
                "-i",
                "dummy",
            ]
        elif system == "Darwin":
            command = [
                str(executable),
                "-hide_banner",
                "-f",
                "avfoundation",
                "-list_devices",
                "true",
                "-i",
                "",
            ]
        else:
            command = [str(executable), "-hide_banner", "-sources", "v4l2"]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
        output = (completed.stdout + "\n" + completed.stderr).strip()
        LOGGER.info("Diagnóstico de dispositivos FFmpeg ejecutado")
        installation = self._installation
        return DeviceDiagnostic(
            tuple(command),
            output,
            str(executable),
            installation.version if installation is not None else "",
        )

    def _capture_command(self, output: Path, executable: Path) -> list[str]:
        common_output = [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-b:v",
            self.config.bitrate,
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-y",
            str(output),
        ]
        system = platform.system()
        if system == "Windows":
            input_args = [
                "-f",
                "dshow",
                "-video_size",
                self.config.resolution,
                "-framerate",
                str(self.config.fps),
                "-i",
                f"video={self.config.device_name}",
            ]
        elif system == "Darwin":
            input_args = [
                "-f",
                "avfoundation",
                "-video_size",
                self.config.resolution,
                "-framerate",
                str(self.config.fps),
                "-i",
                f"{self.config.device_name}:none",
            ]
        else:
            input_args = [
                "-f",
                "v4l2",
                "-video_size",
                self.config.resolution,
                "-framerate",
                str(self.config.fps),
                "-i",
                self.config.device_name,
            ]
        return [str(executable), "-hide_banner", *input_args, *common_output]

    def _close_log(self) -> None:
        if self._log_handle is not None:
            self._log_handle.flush()
            self._log_handle.close()
            self._log_handle = None
