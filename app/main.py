"""ElectroCap desktop entry point."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from app.config import ConfigurationError, load_settings
from app.db.database import Database
from app.logging_config import configure_logging
from app.ui.main_window import MainWindow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ElectroCap")
    parser.add_argument(
        "--config",
        type=Path,
        help="Ruta a settings.json (por defecto: config/settings.json)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    qt_app = QApplication(sys.argv[:1])
    qt_app.setApplicationName("ElectroCap")
    qt_app.setApplicationDisplayName("ElectroCap")
    try:
        settings = load_settings(arguments.config)
        settings.prepare_directories()
    except ConfigurationError as exc:
        QMessageBox.critical(None, "Configuración inválida", str(exc))
        return 2

    configure_logging(settings.log_path)
    logger = logging.getLogger(__name__)
    logger.info("Inicio de ElectroCap")
    logger.info("Configuración cargada desde %s", settings.config_path)

    def log_unhandled(
        exception_type: type[BaseException],
        exception: BaseException,
        traceback_object: object,
    ) -> None:
        logger.critical(
            "Excepción no controlada",
            exc_info=(exception_type, exception, traceback_object),
        )

    sys.excepthook = log_unhandled
    try:
        database = Database(settings.storage.database_path)
        database.initialize()
        window = MainWindow(settings, database)
        window.show()
        return qt_app.exec()
    except Exception as exc:
        logger.exception("No se pudo iniciar la aplicación")
        QMessageBox.critical(None, "Error de inicio", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
