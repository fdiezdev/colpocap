"""Main desktop window and guided UI/service coordination."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QThreadPool, Qt, Signal
from PySide6.QtGui import QCloseEvent, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config import ConfigurationError, Settings, save_runtime_settings
from app.db.database import Database
from app.db.models import CaptureImageRecord, CaptureRecord, StudyRecord
from app.dicom.store_client import EchoResult, StoreClient
from app.dicom.worklist_client import WorklistClient, WorklistItem, WorklistQuery
from app.services.export_service import (
    BatchExportOutcome,
    ExportOutcome,
    ExportService,
    FolderExportOutcome,
)
from app.services.study_service import (
    BatchDicomCreationOutcome,
    StudySelection,
    StudyService,
)
from app.video.capture_manager import CaptureManager
from app.video.ffmpeg_manager import DeviceDiagnostic
from app.video.snapshot_manager import SnapshotManager
from app.dicom.dicom_builder import DicomBuilder
from .capture_view import CaptureView
from .configuration_view import ConfigurationView
from .theme import APP_STYLESHEET
from .workers import Worker
from .worklist_view import WorklistView

LOGGER = logging.getLogger(__name__)
LOGO_PATH = Path(__file__).resolve().parents[2] / "assets" / "electrocap_logo.png"


class LogBridge(QObject):
    message = Signal(str)


class PreviewBridge(QObject):
    frame = Signal(bytes)


class QtLogHandler(logging.Handler):
    def __init__(self, bridge: LogBridge) -> None:
        super().__init__()
        self.bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.bridge.message.emit(self.format(record))
        except Exception:
            self.handleError(record)


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, database: Database) -> None:
        super().__init__()
        self.settings = settings
        self.database = database
        self.thread_pool = QThreadPool.globalInstance()
        self._active_workers: set[Worker] = set()
        self.selected_study: StudyRecord | None = None
        self.current_capture: CaptureRecord | None = None
        self._capture_busy = False

        self._configure_services(settings)
        self.setWindowTitle("ElectroCap - Captura colposcópica DICOM")
        self.resize(1320, 900)
        self.setMinimumSize(1080, 720)
        self.setStyleSheet(APP_STYLESHEET)
        self._build_ui()
        self._connect_signals()
        self._install_bridges()
        self.refresh_pending()
        self._show_home()

    def _configure_services(self, settings: Settings) -> None:
        self.worklist_client = WorklistClient(
            settings.local_ae_title, settings.worklist
        )
        self.store_client = StoreClient(settings.local_ae_title, settings.pacs)
        capture_manager = CaptureManager(
            settings.video, settings.storage.videos_dir
        )
        self.study_service = StudyService(
            self.database,
            capture_manager,
            SnapshotManager(),
            DicomBuilder(settings.institution),
            settings.storage.snapshots_dir,
            settings.storage.dicom_dir,
        )
        self.export_service = ExportService(self.database, self.store_client)

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("appRoot")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        self.home_page = self._build_home_page()
        self.configuration_view = ConfigurationView(self.settings)
        self.worklist_page = self._build_worklist_page()
        self.capture_view = CaptureView()
        for page in (
            self.home_page,
            self.configuration_view,
            self.worklist_page,
            self.capture_view,
        ):
            self.stack.addWidget(page)
        self.setCentralWidget(central)

    def _build_home_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 26, 34, 28)
        layout.setSpacing(18)

        self.logo_label = QLabel()
        self.logo_label.setAlignment(Qt.AlignCenter)
        self.logo_label.setMinimumHeight(118)
        self.logo_label.setToolTip(f"Logo de la aplicación: {LOGO_PATH}")
        logo = QPixmap(str(LOGO_PATH))
        if logo.isNull():
            self.logo_label.setText("ElectroCap")
            self.logo_label.setObjectName("brandFallback")
        else:
            self.logo_label.setPixmap(
                logo.scaled(480, 145, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        layout.addWidget(self.logo_label)

        actions = QHBoxLayout()
        actions.setSpacing(16)
        actions.addStretch()
        self.worklist_button = QPushButton("Leer Worklist e iniciar estudio")
        self.worklist_button.setObjectName("heroPrimaryButton")
        self.configuration_button = QPushButton("Configurar y probar conexiones")
        self.configuration_button.setObjectName("heroSecondaryButton")
        actions.addWidget(self.worklist_button)
        actions.addWidget(self.configuration_button)
        actions.addStretch()
        layout.addLayout(actions)

        pending_box = QGroupBox("Estudios pendientes de envío al PACS")
        pending_layout = QVBoxLayout(pending_box)
        self.pending_table = QTableWidget(0, 7)
        self.pending_table.setHorizontalHeaderLabels(
            (
                "Sesión",
                "Paciente",
                "Patient ID",
                "Accession",
                "Imágenes",
                "Estado",
                "Respuesta",
            )
        )
        self.pending_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.pending_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.pending_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pending_table.setAlternatingRowColors(True)
        self.pending_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.pending_table.horizontalHeader().setStretchLastSection(True)
        pending_layout.addWidget(self.pending_table)
        pending_buttons = QHBoxLayout()
        self.retry_button = QPushButton("Reintentar envío completo")
        self.retry_button.setObjectName("primaryButton")
        self.export_pending_button = QPushButton("Exportar DICOM a carpeta")
        self.export_pending_button.setObjectName("secondaryButton")
        self.refresh_pending_button = QPushButton("Actualizar")
        pending_buttons.addStretch()
        pending_buttons.addWidget(self.retry_button)
        pending_buttons.addWidget(self.export_pending_button)
        pending_buttons.addWidget(self.refresh_pending_button)
        pending_layout.addLayout(pending_buttons)
        layout.addWidget(pending_box, 2)
        return page

    def _build_worklist_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(14)
        header = QHBoxLayout()
        self.worklist_back_button = QPushButton("Menú principal")
        self.worklist_back_button.setObjectName("navigationButton")
        title = QLabel("Worklist y selección del estudio")
        title.setObjectName("pageTitle")
        header.addWidget(self.worklist_back_button)
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        hint = QLabel(
            "Busque el turno o cargue un paciente manualmente, verifique los datos "
            "y luego pulse “Iniciar estudio seleccionado”."
        )
        hint.setWordWrap(True)
        hint.setObjectName("supportingText")
        layout.addWidget(hint)
        self.worklist_view = WorklistView()
        self.worklist_view.select_button.setText("Iniciar estudio seleccionado")
        self.worklist_view.select_button.setMinimumHeight(44)
        layout.addWidget(self.worklist_view, 1)
        return page

    def _connect_signals(self) -> None:
        self.configuration_button.clicked.connect(self._show_configuration)
        self.worklist_button.clicked.connect(self._show_worklist)
        self.worklist_back_button.clicked.connect(self._show_home)
        self.configuration_view.back_requested.connect(self._show_home)
        self.configuration_view.save_requested.connect(self._save_configuration)
        self.configuration_view.test_worklist_requested.connect(
            self._test_worklist
        )
        self.configuration_view.test_pacs_requested.connect(self._test_pacs)
        self.configuration_view.devices_requested.connect(self._diagnose_devices)
        self.worklist_view.search_requested.connect(self._search_worklist)
        self.worklist_view.selection_requested.connect(self._select_study)
        self.worklist_view.manual_patient_added.connect(
            lambda item: self.statusBar().showMessage(
                f"Paciente {item.patient_id} agregado manualmente a la Worklist",
                8000,
            )
        )
        self.capture_view.back_requested.connect(self._show_worklist)
        self.capture_view.start_requested.connect(self._start_recording)
        self.capture_view.snapshot_requested.connect(self._create_live_snapshot)
        self.capture_view.finish_requested.connect(self._finish_and_send)
        self.capture_view.local_export_requested.connect(
            self._finish_and_export_local
        )
        self.retry_button.clicked.connect(self._retry_selected)
        self.export_pending_button.clicked.connect(self._export_pending_selected)
        self.refresh_pending_button.clicked.connect(self.refresh_pending)

    def _install_bridges(self) -> None:
        self._preview_bridge = PreviewBridge()
        self._preview_bridge.frame.connect(self.capture_view.show_preview_frame)
        self._log_bridge = LogBridge()
        self._log_bridge.message.connect(self.capture_view.append_log)
        self._ui_log_handler = QtLogHandler(self._log_bridge)
        self._ui_log_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S")
        )
        logging.getLogger().addHandler(self._ui_log_handler)

    def _show_home(self) -> None:
        self.refresh_pending()
        self.stack.setCurrentWidget(self.home_page)

    def _show_configuration(self) -> None:
        self.configuration_view.load_settings(self.settings)
        self.stack.setCurrentWidget(self.configuration_view)

    def _show_worklist(self) -> None:
        if self.study_service.capture_manager.is_recording:
            return
        self.stack.setCurrentWidget(self.worklist_page)

    def _run_async(
        self,
        function: Callable[[], Any],
        on_result: Callable[[Any], None],
        *,
        description: str,
        on_finished: Callable[[], None] | None = None,
        on_error: Callable[[], None] | None = None,
    ) -> None:
        worker = Worker(function)
        self._active_workers.add(worker)
        worker.signals.result.connect(on_result)

        def handle_error(message: str, trace: str) -> None:
            self._task_error(description, message, trace)
            if on_error:
                on_error()

        def handle_finished() -> None:
            try:
                if on_finished:
                    on_finished()
            finally:
                self._active_workers.discard(worker)

        worker.signals.error.connect(handle_error)
        worker.signals.finished.connect(handle_finished)
        self.thread_pool.start(worker)

    def _task_error(self, description: str, message: str, trace: str) -> None:
        LOGGER.error("%s: %s\n%s", description, message, trace)
        QMessageBox.critical(self, description, message)

    def _editable_configuration(self):
        return self.configuration_view.editable_values()

    def _test_worklist(self) -> None:
        local_ae, worklist, _, _ = self._editable_configuration()
        self.configuration_view.set_test_busy("worklist", True)
        self._run_async(
            WorklistClient(local_ae, worklist).echo,
            lambda result: self._show_echo("worklist", result),
            description="Prueba de Worklist",
            on_finished=lambda: self.configuration_view.set_test_busy(
                "worklist", False
            ),
            on_error=lambda: self.configuration_view.show_connection_result(
                "worklist", False, "error durante la prueba"
            ),
        )

    def _test_pacs(self) -> None:
        local_ae, _, pacs, _ = self._editable_configuration()
        self.configuration_view.set_test_busy("pacs", True)
        self._run_async(
            StoreClient(local_ae, pacs).echo,
            lambda result: self._show_echo("pacs", result),
            description="Prueba de PACS",
            on_finished=lambda: self.configuration_view.set_test_busy("pacs", False),
            on_error=lambda: self.configuration_view.show_connection_result(
                "pacs", False, "error durante la prueba"
            ),
        )

    def _show_echo(self, target: str, result: EchoResult) -> None:
        self.configuration_view.show_connection_result(
            target, result.success, result.message
        )

    def _save_configuration(self) -> None:
        if self.study_service.capture_manager.is_recording:
            QMessageBox.warning(
                self,
                "Configuración",
                "Finalice el estudio activo antes de cambiar la configuración.",
            )
            return
        try:
            local_ae, worklist, pacs, video = self._editable_configuration()
            updated = save_runtime_settings(
                self.settings,
                local_ae_title=local_ae,
                worklist=worklist,
                pacs=pacs,
                video=video,
            )
            updated.prepare_directories()
            self.settings = updated
            self._configure_services(updated)
            self.configuration_view.load_settings(updated)
        except (ConfigurationError, OSError, ValueError) as exc:
            QMessageBox.critical(self, "Configuración inválida", str(exc))
            return
        QMessageBox.information(
            self,
            "Configuración",
            "La configuración fue guardada y ya está activa.",
        )

    def _search_worklist(self, query: WorklistQuery) -> None:
        self.worklist_view.set_busy(True)
        self._run_async(
            lambda: self.worklist_client.find(query),
            self._worklist_results,
            description="Consulta Worklist",
            on_finished=lambda: self.worklist_view.set_busy(False),
        )

    def _worklist_results(self, items: list[WorklistItem]) -> None:
        self.worklist_view.set_results(items)
        self.statusBar().showMessage(f"Worklist: {len(items)} resultado(s)", 8000)

    def _select_study(self, item: WorklistItem) -> None:
        try:
            selection: StudySelection = self.study_service.select_worklist_item(item)
        except Exception as exc:
            QMessageBox.critical(self, "Selección de estudio", str(exc))
            return
        self.selected_study = selection.study
        self.current_capture = None
        self.capture_view.set_selected_study(selection.study)
        self._sync_capture_state("Listo para iniciar la cámara")
        self.stack.setCurrentWidget(self.capture_view)
        if selection.warnings:
            QMessageBox.warning(
                self, "Metadata incompleta", "\n".join(selection.warnings)
            )

    def _start_recording(self) -> None:
        if self.selected_study is None:
            QMessageBox.warning(self, "Captura", "Seleccione un estudio primero.")
            return
        if self.current_capture is not None:
            QMessageBox.warning(
                self,
                "Captura",
                "Esta sesión ya fue iniciada. Finalícela antes de comenzar otra.",
            )
            return
        try:
            self.current_capture = self.study_service.start_recording(
                self.selected_study.id, self._preview_bridge.frame.emit
            )
        except Exception as exc:
            QMessageBox.critical(self, "Iniciar cámara", str(exc))
            self.refresh_pending()
            return
        self._sync_capture_state("Cámara activa: capture los snapshots necesarios")

    def _create_live_snapshot(self) -> None:
        if self.current_capture is None:
            return
        frame = self.capture_view.latest_frame_jpeg
        if not frame:
            QMessageBox.warning(
                self, "Snapshot", "Espere a que aparezca la imagen de la cámara."
            )
            return
        capture_id = self.current_capture.id
        self._capture_busy = True
        self._sync_capture_state("Guardando snapshot…")
        self._run_async(
            lambda: self.study_service.create_live_snapshot(capture_id, frame),
            self._snapshot_created,
            description="Capturar snapshot",
            on_finished=self._capture_task_finished,
            on_error=self._reload_current_capture,
        )

    def _snapshot_created(self, image: CaptureImageRecord) -> None:
        self.capture_view.add_snapshot(image)
        self.statusBar().showMessage(
            f"Snapshot {image.instance_number} capturado", 5000
        )

    def _capture_task_finished(self) -> None:
        self._capture_busy = False
        self._sync_capture_state()

    def _finish_and_send(self) -> None:
        if self.current_capture is None:
            return
        capture_id = self.current_capture.id
        self._capture_busy = True
        self._sync_capture_state("Finalizando video, generando DICOM y enviando…")
        self._run_async(
            lambda: self._finalize_batch(capture_id),
            self._batch_completed,
            description="Finalizar y enviar estudio",
            on_finished=self._capture_task_finished,
            on_error=self._reload_current_capture,
        )

    def _finish_and_export_local(self) -> None:
        if self.current_capture is None:
            return
        destination = self._choose_export_directory()
        if destination is None:
            return
        capture_id = self.current_capture.id
        self._capture_busy = True
        self._sync_capture_state("Finalizando video y preparando la exportación DICOM…")
        self._run_async(
            lambda: self._finalize_local_export(capture_id, destination),
            self._local_capture_export_completed,
            description="Finalizar y exportar estudio",
            on_finished=self._capture_task_finished,
            on_error=self._reload_current_capture,
        )

    def _finalize_batch(
        self, capture_id: int
    ) -> tuple[BatchDicomCreationOutcome, BatchExportOutcome]:
        dicom_outcome = self.study_service.finalize_dicom_images(capture_id)
        export_outcome = self.export_service.send_capture_images(capture_id)
        return dicom_outcome, export_outcome

    def _finalize_local_export(
        self, capture_id: int, destination: Path
    ) -> tuple[BatchDicomCreationOutcome, FolderExportOutcome]:
        dicom_outcome = self.study_service.finalize_dicom_images(capture_id)
        export_outcome = self.export_service.export_capture_images(
            capture_id, destination
        )
        return dicom_outcome, export_outcome

    def _batch_completed(
        self, outcome: tuple[BatchDicomCreationOutcome, BatchExportOutcome]
    ) -> None:
        dicom_outcome, export_outcome = outcome
        self.current_capture = self.database.get_capture(export_outcome.capture_id)
        self.capture_view.mark_finished(
            "Estudio finalizado" if export_outcome.success else "Envío pendiente"
        )
        self.refresh_pending()
        self._show_dicom_warnings(dicom_outcome)
        if export_outcome.success:
            QMessageBox.information(self, "Estudio finalizado", export_outcome.message)
        else:
            QMessageBox.critical(self, "Envío a PACS", export_outcome.message)
        self.selected_study = None
        self.current_capture = None
        self._show_home()

    def _local_capture_export_completed(
        self, outcome: tuple[BatchDicomCreationOutcome, FolderExportOutcome]
    ) -> None:
        dicom_outcome, export_outcome = outcome
        self.current_capture = self.database.get_capture(export_outcome.capture_id)
        self.capture_view.mark_finished("Estudio exportado")
        self.refresh_pending()
        self._show_dicom_warnings(dicom_outcome)
        QMessageBox.information(
            self,
            "Exportación DICOM finalizada",
            export_outcome.message
            + "\n\nEl estudio seguirá disponible para enviarlo al PACS.",
        )
        self.selected_study = None
        self.current_capture = None
        self._show_home()

    def _retry_selected(self) -> None:
        capture_id = self._selected_pending_capture_id("Reintento")
        if capture_id is None:
            return
        self.retry_button.setEnabled(False)
        self._run_async(
            lambda: self.export_service.retry_capture(capture_id),
            self._retry_completed,
            description="Reintentar envío",
            on_finished=lambda: self.retry_button.setEnabled(True),
        )

    def _export_pending_selected(self) -> None:
        capture_id = self._selected_pending_capture_id("Exportación DICOM")
        if capture_id is None:
            return
        destination = self._choose_export_directory()
        if destination is None:
            return
        self.export_pending_button.setEnabled(False)
        self._run_async(
            lambda: self.export_service.export_capture_images(
                capture_id, destination
            ),
            self._pending_folder_export_completed,
            description="Exportar DICOM a carpeta",
            on_finished=lambda: self.export_pending_button.setEnabled(True),
        )

    def _retry_completed(self, outcome: ExportOutcome | BatchExportOutcome) -> None:
        self.refresh_pending()
        if isinstance(outcome, BatchExportOutcome):
            if outcome.success:
                QMessageBox.information(self, "PACS", outcome.message)
            else:
                QMessageBox.critical(self, "PACS", outcome.message)
            return
        if outcome.export.status == "SENT":
            QMessageBox.information(self, "PACS", outcome.message)
        else:
            QMessageBox.critical(self, "PACS", outcome.message)

    def _pending_folder_export_completed(
        self, outcome: FolderExportOutcome
    ) -> None:
        QMessageBox.information(
            self, "Exportación DICOM finalizada", outcome.message
        )
        self.statusBar().showMessage(
            f"Estudio exportado en {outcome.directory}", 10000
        )

    def _selected_pending_capture_id(self, title: str) -> int | None:
        row = self.pending_table.currentRow()
        item = self.pending_table.item(row, 0) if row >= 0 else None
        if item is None:
            QMessageBox.warning(self, title, "Seleccione una sesión pendiente.")
            return None
        return int(item.data(Qt.UserRole))

    def _choose_export_directory(self) -> Path | None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Seleccionar carpeta o unidad para exportar",
            "",
            QFileDialog.ShowDirsOnly,
        )
        return Path(selected) if selected else None

    def _show_dicom_warnings(
        self, outcome: BatchDicomCreationOutcome
    ) -> None:
        warnings = [
            warning for build in outcome.builds for warning in build.warnings
        ]
        if warnings:
            QMessageBox.warning(
                self,
                "DICOM creado con advertencias",
                "\n".join(dict.fromkeys(warnings)),
            )

    def refresh_pending(self) -> None:
        if not hasattr(self, "pending_table"):
            return
        rows = self.database.list_pending_captures()
        self.pending_table.setRowCount(len(rows))
        for row_number, row in enumerate(rows):
            status = row.get("export_status") or row.get("capture_status") or ""
            response = row.get("response_status") or row.get("error_message") or ""
            image_count = int(row.get("image_count") or (1 if row.get("dicom_image_path") else 0))
            sent_count = int(row.get("sent_count") or 0)
            images = f"{sent_count}/{image_count} enviadas"
            values = (
                str(row["capture_id"]),
                str(row["patient_name"] or ""),
                str(row["patient_id"] or ""),
                str(row["accession_number"] or ""),
                images,
                str(status),
                str(response),
            )
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(value)
                if column == 0:
                    table_item.setData(Qt.UserRole, int(row["capture_id"]))
                self.pending_table.setItem(row_number, column, table_item)

    def _diagnose_devices(self) -> None:
        _, _, _, video = self._editable_configuration()
        self.configuration_view.devices_button.setEnabled(False)
        manager = CaptureManager(video, self.settings.storage.videos_dir)
        self._run_async(
            manager.diagnose_devices,
            self._show_device_diagnostic,
            description="Diagnóstico FFmpeg",
            on_finished=lambda: self.configuration_view.devices_button.setEnabled(True),
        )

    def _show_device_diagnostic(self, diagnostic: DeviceDiagnostic) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Dispositivos de video detectados por FFmpeg")
        dialog.resize(850, 550)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(
            "Ejecutable seleccionado:\n"
            + diagnostic.executable
            + "\n\nVersión:\n"
            + diagnostic.version
            + "\n\nComando:\n"
            + " ".join(diagnostic.command)
            + "\n\nSalida:\n"
            + diagnostic.output
        )
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _sync_capture_state(self, status_text: str | None = None) -> None:
        capture = self.current_capture
        images = (
            self.database.list_capture_images(capture.id) if capture is not None else []
        )
        self.capture_view.set_workflow_state(
            selected=self.selected_study is not None,
            can_start=capture is None,
            recording=self.study_service.capture_manager.is_recording,
            snapshot_count=len(images),
            busy=self._capture_busy,
            status_text=status_text,
        )

    def _reload_current_capture(self) -> None:
        if self.current_capture is not None:
            self.current_capture = self.database.get_capture(self.current_capture.id)
        self.refresh_pending()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.study_service.capture_manager.is_recording:
            answer = QMessageBox.question(
                self,
                "Estudio activo",
                "Hay un estudio activo. ¿Detener la grabación y cerrar? Los snapshots "
                "quedarán locales y el estudio no se enviará.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            try:
                if self.current_capture is not None:
                    self.study_service.stop_recording(self.current_capture.id)
            except Exception as exc:
                LOGGER.exception("Error al detener FFmpeg durante el cierre")
                QMessageBox.critical(self, "Cierre", str(exc))
                event.ignore()
                return
        logging.getLogger().removeHandler(self._ui_log_handler)
        event.accept()
