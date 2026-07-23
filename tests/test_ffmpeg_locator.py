from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from app.video.ffmpeg_locator import (
    BUNDLED_WINDOWS_RELATIVE_PATH,
    FFmpegLocatorError,
    locate_ffmpeg,
    validate_ffmpeg,
)


def _valid_runner(
    command: list[str], **_: object
) -> subprocess.CompletedProcess[str]:
    if command[-1] == "-version":
        return subprocess.CompletedProcess(
            command, 0, "ffmpeg version 8.1.2-essentials_build\n", ""
        )
    if command[-1] == "-devices":
        return subprocess.CompletedProcess(
            command, 0, " D  dshow          DirectShow capture\n", ""
        )
    raise AssertionError(f"Comando inesperado: {command}")


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def test_bundled_windows_ffmpeg_has_priority_over_path(tmp_path: Path) -> None:
    bundled = _touch(tmp_path / BUNDLED_WINDOWS_RELATIVE_PATH)
    path_ffmpeg = _touch(tmp_path / "system" / "ffmpeg.exe")

    installation = locate_ffmpeg(
        system="Windows",
        project_root=tmp_path,
        environ={},
        path_lookup=lambda _: str(path_ffmpeg),
        run_command=_valid_runner,
    )

    assert installation.executable == bundled.resolve()
    assert installation.source == "binario incluido en el proyecto"
    assert installation.version == "ffmpeg version 8.1.2-essentials_build"


def test_environment_override_has_priority_over_bundled(tmp_path: Path) -> None:
    configured = _touch(tmp_path / "custom" / "ffmpeg.exe")
    _touch(tmp_path / BUNDLED_WINDOWS_RELATIVE_PATH)

    installation = locate_ffmpeg(
        system="Windows",
        project_root=tmp_path,
        environ={"ELECTROCAP_FFMPEG": f'"{configured}"'},
        path_lookup=lambda _: None,
        run_command=_valid_runner,
    )

    assert installation.executable == configured.resolve()
    assert installation.source == "variable ELECTROCAP_FFMPEG"


def test_explicit_path_has_priority_over_environment(tmp_path: Path) -> None:
    explicit = _touch(tmp_path / "explicit" / "ffmpeg.exe")
    configured = _touch(tmp_path / "environment" / "ffmpeg.exe")

    installation = locate_ffmpeg(
        explicit,
        system="Windows",
        project_root=tmp_path,
        environ={"ELECTROCAP_FFMPEG": str(configured)},
        path_lookup=lambda _: None,
        run_command=_valid_runner,
    )

    assert installation.executable == explicit.resolve()
    assert installation.source == "parámetro explícito"


def test_path_is_used_as_last_fallback(tmp_path: Path) -> None:
    path_ffmpeg = _touch(tmp_path / "system" / "ffmpeg")

    installation = locate_ffmpeg(
        system="Linux",
        project_root=tmp_path,
        environ={},
        path_lookup=lambda _: str(path_ffmpeg),
        run_command=_valid_runner,
    )

    assert installation.executable == path_ffmpeg.resolve()
    assert installation.source == "PATH del sistema"


def test_windows_validation_rejects_build_without_directshow(tmp_path: Path) -> None:
    executable = _touch(tmp_path / "ffmpeg.exe")

    def runner(
        command: list[str], **_: object
    ) -> subprocess.CompletedProcess[str]:
        if command[-1] == "-version":
            return subprocess.CompletedProcess(command, 0, "ffmpeg version test", "")
        return subprocess.CompletedProcess(command, 0, " D  gdigrab", "")

    with pytest.raises(FFmpegLocatorError, match="DirectShow"):
        validate_ffmpeg(executable, system="Windows", run_command=runner)


def test_missing_ffmpeg_explains_how_to_install_it(tmp_path: Path) -> None:
    with pytest.raises(
        FFmpegLocatorError, match=r"install_ffmpeg_windows\.ps1"
    ):
        locate_ffmpeg(
            system="Windows",
            project_root=tmp_path,
            environ={},
            path_lookup=lambda _: None,
            run_command=_valid_runner,
        )
