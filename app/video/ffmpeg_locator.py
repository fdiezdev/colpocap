"""Locate and validate the FFmpeg executable used by ElectroCap."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Callable, Mapping, Sequence

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUNDLED_WINDOWS_RELATIVE_PATH = (
    Path("third_party") / "ffmpeg" / "windows-x64" / "ffmpeg.exe"
)


class FFmpegLocatorError(RuntimeError):
    """Raised when no usable FFmpeg installation can be selected."""


@dataclass(frozen=True)
class FFmpegInstallation:
    executable: Path
    source: str
    version: str


RunCommand = Callable[..., subprocess.CompletedProcess[str]]
PathLookup = Callable[[str], str | None]


def locate_ffmpeg(
    executable: str | Path | None = None,
    *,
    system: str | None = None,
    project_root: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    path_lookup: PathLookup = shutil.which,
    run_command: RunCommand = subprocess.run,
) -> FFmpegInstallation:
    """Select one deterministic FFmpeg binary and verify that it is usable.

    Selection order is: explicit constructor argument, ``ELECTROCAP_FFMPEG``,
    the project-owned Windows binary, and finally the operating system PATH.
    A configured or bundled binary that exists but is invalid is reported
    instead of silently selecting a different installation.
    """

    active_system = system or platform.system()
    active_root = Path(project_root) if project_root is not None else PROJECT_ROOT
    active_environment = environ if environ is not None else os.environ

    configured: tuple[str, str] | None = None
    if executable is not None and str(executable).strip():
        configured = (_clean_configured_path(str(executable)), "parámetro explícito")
    elif active_environment.get("ELECTROCAP_FFMPEG", "").strip():
        configured = (
            _clean_configured_path(active_environment["ELECTROCAP_FFMPEG"]),
            "variable ELECTROCAP_FFMPEG",
        )

    if configured is not None:
        value, source = configured
        selected = _find_configured_executable(value, path_lookup)
        if selected is None:
            raise FFmpegLocatorError(
                f"La ruta de FFmpeg indicada mediante {source} no existe o no es "
                f"ejecutable: {value}"
            )
        return _validated_installation(selected, source, active_system, run_command)

    if active_system == "Windows":
        bundled = active_root / BUNDLED_WINDOWS_RELATIVE_PATH
        if bundled.is_file():
            return _validated_installation(
                bundled.resolve(),
                "binario incluido en el proyecto",
                active_system,
                run_command,
            )

    system_ffmpeg = path_lookup("ffmpeg")
    if system_ffmpeg:
        return _validated_installation(
            Path(system_ffmpeg).resolve(), "PATH del sistema", active_system, run_command
        )

    bundled_hint = active_root / BUNDLED_WINDOWS_RELATIVE_PATH
    raise FFmpegLocatorError(
        "No se encontró FFmpeg. Ejecute "
        ".\\scripts\\install_ffmpeg_windows.ps1 desde la raíz del proyecto. "
        f"Se esperaba el binario en {bundled_hint}. También puede definir "
        "ELECTROCAP_FFMPEG con una ruta completa válida."
    )


def validate_ffmpeg(
    executable: str | Path,
    *,
    system: str | None = None,
    run_command: RunCommand = subprocess.run,
) -> str:
    """Return the FFmpeg version line after checking required capabilities."""

    active_system = system or platform.system()
    executable_path = Path(executable)
    version_result = _run_probe(
        [str(executable_path), "-hide_banner", "-version"], run_command
    )
    version_output = _combined_output(version_result)
    if version_result.returncode != 0:
        raise FFmpegLocatorError(
            f"FFmpeg devolvió código {version_result.returncode} al consultar su "
            f"versión: {executable_path}. {_output_tail(version_output)}"
        )
    version_lines = [line.strip() for line in version_output.splitlines() if line.strip()]
    if not version_lines or not any(
        "ffmpeg version" in line.lower() for line in version_lines
    ):
        raise FFmpegLocatorError(
            f"El ejecutable no respondió como una instalación válida de FFmpeg: "
            f"{executable_path}. {_output_tail(version_output)}"
        )
    version = next(
        line for line in version_lines if "ffmpeg version" in line.lower()
    )

    if active_system == "Windows":
        devices_result = _run_probe(
            [str(executable_path), "-hide_banner", "-devices"], run_command
        )
        devices_output = _combined_output(devices_result)
        if devices_result.returncode != 0 or "dshow" not in devices_output.lower():
            raise FFmpegLocatorError(
                "La compilación de FFmpeg seleccionada no ofrece DirectShow (dshow), "
                "necesario para capturar la cámara en Windows. "
                f"Ejecutable: {executable_path}. {_output_tail(devices_output)}"
            )

    return version


def _validated_installation(
    executable: Path,
    source: str,
    system: str,
    run_command: RunCommand,
) -> FFmpegInstallation:
    version = validate_ffmpeg(executable, system=system, run_command=run_command)
    installation = FFmpegInstallation(executable, source, version)
    LOGGER.info(
        "FFmpeg seleccionado desde %s: %s | %s",
        installation.source,
        installation.executable,
        installation.version,
    )
    return installation


def _find_configured_executable(value: str, path_lookup: PathLookup) -> Path | None:
    path = Path(value).expanduser()
    if path.is_file():
        return path.resolve()
    resolved = path_lookup(value)
    return Path(resolved).resolve() if resolved else None


def _clean_configured_path(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "'\"":
        return stripped[1:-1]
    return stripped


def _run_probe(
    command: Sequence[str], run_command: RunCommand
) -> subprocess.CompletedProcess[str]:
    creation_flags = (
        subprocess.CREATE_NO_WINDOW
        if platform.system() == "Windows" and hasattr(subprocess, "CREATE_NO_WINDOW")
        else 0
    )
    try:
        return run_command(
            list(command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
            creationflags=creation_flags,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise FFmpegLocatorError(
            f"No se pudo ejecutar FFmpeg ({command[0]}): {exc}"
        ) from exc


def _combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return f"{result.stdout or ''}\n{result.stderr or ''}".strip()


def _output_tail(output: str, maximum: int = 800) -> str:
    if not output:
        return "No produjo salida."
    return f"Última salida: {output[-maximum:].strip()}"
