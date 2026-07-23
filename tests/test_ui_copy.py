from pathlib import Path
import re


UI_DIRECTORY = Path(__file__).resolve().parents[1] / "app" / "ui"


def test_ui_copy_has_no_legacy_brand_arrows_emojis_or_numbered_steps() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(UI_DIRECTORY.glob("*.py"))
    )

    assert "ColpoCap" not in source
    assert not re.search(r"\bPasos?\s+\d", source, flags=re.IGNORECASE)
    assert not re.search(r'QPushButton\(\s*["\']\d+[.)]\s', source)
    assert not any(symbol in source for symbol in ("⚙", "→", "←", "➡", "➜", "➔"))


def test_capture_layout_keeps_video_controls_and_technical_log_separate() -> None:
    capture_source = (UI_DIRECTORY / "capture_view.py").read_text(encoding="utf-8")
    configuration_source = (UI_DIRECTORY / "configuration_view.py").read_text(
        encoding="utf-8"
    )
    theme_source = (UI_DIRECTORY / "theme.py").read_text(encoding="utf-8")

    assert 'QPushButton("Finalizar estudio")' in capture_source
    assert "ScrollBarAlwaysOn" in capture_source
    assert "setWrapping(False)" in capture_source
    assert "log_view" not in capture_source
    assert "local_export_button" not in capture_source
    assert 'QPushButton("Ver consola técnica")' in configuration_source
    assert "min-height: 24px" in theme_source
