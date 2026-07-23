from pathlib import Path

from app.config import VideoConfig
from app.video.ffmpeg_manager import FFmpegManager


def test_capture_command_adds_live_jpeg_pipe_after_mp4_output(tmp_path: Path) -> None:
    manager = FFmpegManager(VideoConfig("0", "1280x720", 30, "4M"))
    video = tmp_path / "study.mp4"

    command = manager._capture_command(
        video, Path("/test/ffmpeg"), with_preview=True
    )

    assert str(video) in command
    assert "image2pipe" in command
    assert "pipe:1" in command
    assert command.index(str(video)) < command.index("pipe:1")
    assert command.count("-map") == 2


def test_capture_command_without_preview_has_no_stdout_pipe(tmp_path: Path) -> None:
    manager = FFmpegManager(VideoConfig("0", "1280x720", 30, "4M"))
    command = manager._capture_command(
        tmp_path / "study.mp4", Path("/test/ffmpeg"), with_preview=False
    )

    assert "pipe:1" not in command
    assert "image2pipe" not in command

