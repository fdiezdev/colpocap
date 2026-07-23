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
