"""Main desktop window and UI/service coordination."""

from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, QThreadPool, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config import Settings
from app.db.database import Database
from app.db.models import CaptureRecord, StudyRecord
from app.dicom.dicom_builder import DicomBuilder
from app.dicom.store_client import EchoResult, StoreClient
from app.dicom.worklist_client import WorklistClient, WorklistItem, WorklistQuery
from app.services.export_service import ExportOutcome, ExportService
from app.services.study_service import DicomCreationOutcome, StudySelection, StudyService
from app.video.capture_manager import CaptureManager
from app.video.ffmpeg_manager import DeviceDiagnostic
from app.video.snapshot_manager import SnapshotManager
from .capture_view import CaptureView
from .workers import Worker
from .worklist_view import WorklistView

LOGGER = logging.getLogger(__name__)


class LogBridge(QObject):
    message = Signal(str)


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
        # QRunnable is not a QObject and QThreadPool doesn't keep a Python
        # reference alive for queued signal delivery. Retain workers until
        # their finished signal has been handled by the UI thread.
        self._active_workers: set[Worker] = set()
        self.selected_study: StudyRecord | None = None
        self.current_capture: CaptureRecord | None = None

        self.worklist_client = WorklistClient(settings.local_ae_title, settings.worklist)
        self.store_client = StoreClient(settings.local_ae_title, settings.pacs)
        capture_manager = CaptureManager(settings.video, settings.storage.videos_dir)
        self.study_service = StudyService(
            database,
            capture_manager,
            SnapshotManager(),
            DicomBuilder(settings.institution),
            settings.storage.snapshots_dir,
            settings.storage.dicom_dir,
        )
        self.export_service = ExportService(database, self.store_client)

        self.setWindowTitle("ColpoCap MVP - Captura colposcópica DICOM")
        self.resize(1250, 900)
        self._build_ui()
        self._connect_signals()
        self._install_ui_log_handler()
        self.refresh_pending()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        connection_box = QGroupBox("Estado de conexiones")
        connection_layout = QHBoxLayout(connection_box)
        self.worklist_test_button = QPushButton("Probar Worklist")
        self.worklist_status = QLabel("No probado")
        self.pacs_test_button = QPushButton("Probar PACS")
        self.pacs_status = QLabel("No probado")
        connection_layout.addWidget(self.worklist_test_button)
        connection_layout.addWidget(self.worklist_status, 1)
        connection_layout.addWidget(self.pacs_test_button)
        connection_layout.addWidget(self.pacs_status, 1)
        root.addWidget(connection_box)

        splitter = QSplitter(Qt.Vertical)
        worklist_box = QGroupBox("Worklist DICOM")
        worklist_layout = QVBoxLayout(worklist_box)
        self.worklist_view = WorklistView()
        worklist_layout.addWidget(self.worklist_view)
        splitter.addWidget(worklist_box)

        lower = QWidget()
        lower_layout = QHBoxLayout(lower)
        capture_box = QGroupBox("Captura y exportación")
        capture_layout = QVBoxLayout(capture_box)
        self.capture_view = CaptureView()
        capture_layout.addWidget(self.capture_view)
        lower_layout.addWidget(capture_box, 3)

        pending_box = QGroupBox("Pendientes de envío")
        pending_layout = QVBoxLayout(pending_box)
        self.pending_table = QTableWidget(0, 6)
        self.pending_table.setHorizontalHeaderLabels(
            ("Captura", "Paciente", "Patient ID", "Accession", "Estado", "Respuesta")
        )
        self.pending_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.pending_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.pending_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pending_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.pending_table.horizontalHeader().setStretchLastSection(True)
        pending_layout.addWidget(self.pending_table)
        pending_buttons = QHBoxLayout()
        self.retry_button = QPushButton("Reintentar envío")
        self.refresh_pending_button = QPushButton("Actualizar")
        pending_buttons.addWidget(self.retry_button)
        pending_buttons.addWidget(self.refresh_pending_button)
        pending_layout.addLayout(pending_buttons)
        lower_layout.addWidget(pending_box, 2)
        splitter.addWidget(lower)
        splitter.setSizes([430, 420])
        root.addWidget(splitter)
        self.setCentralWidget(central)

    def _connect_signals(self) -> None:
        self.worklist_test_button.clicked.connect(self._test_worklist)
        self.pacs_test_button.clicked.connect(self._test_pacs)
        self.worklist_view.search_requested.connect(self._search_worklist)
        self.worklist_view.selection_requested.connect(self._select_study)
        self.capture_view.start_requested.connect(self._start_recording)
        self.capture_view.stop_requested.connect(self._stop_recording)
        self.capture_view.snapshot_requested.connect(self._create_snapshot)
        self.capture_view.dicom_requested.connect(self._create_dicom)
        self.capture_view.send_requested.connect(self._send_to_pacs)
        self.capture_view.devices_requested.connect(self._diagnose_devices)
        self.retry_button.clicked.connect(self._retry_selected)
        self.refresh_pending_button.clicked.connect(self.refresh_pending)

    def _install_ui_log_handler(self) -> None:
        self._log_bridge = LogBridge()
        self._log_bridge.message.connect(self.capture_view.append_log)
        self._ui_log_handler = QtLogHandler(self._log_bridge)
        self._ui_log_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S")
        )
        logging.getLogger().addHandler(self._ui_log_handler)

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

    def _test_worklist(self) -> None:
        self.worklist_test_button.setEnabled(False)
        self.worklist_status.setText("Probando…")
        self.worklist_status.setStyleSheet("")
        self._run_async(
            self.worklist_client.echo,
            lambda result: self._show_echo(result, self.worklist_status),
            description="Prueba de Worklist",
            on_finished=lambda: self.worklist_test_button.setEnabled(True),
            on_error=lambda: self._show_connection_error(self.worklist_status),
        )

    def _test_pacs(self) -> None:
        self.pacs_test_button.setEnabled(False)
        self.pacs_status.setText("Probando…")
        self.pacs_status.setStyleSheet("")
        self._run_async(
            self.export_service.test_pacs,
            lambda result: self._show_echo(result, self.pacs_status),
            description="Prueba de PACS",
            on_finished=lambda: self.pacs_test_button.setEnabled(True),
            on_error=lambda: self._show_connection_error(self.pacs_status),
        )

    @staticmethod
    def _show_echo(result: EchoResult, label: QLabel) -> None:
        label.setText(("Conectado: " if result.success else "Falló: ") + result.message)
        label.setStyleSheet("color: green" if result.success else "color: red")

    @staticmethod
    def _show_connection_error(label: QLabel) -> None:
        label.setText("Error durante la prueba; revise el detalle mostrado")
        label.setStyleSheet("color: red")

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
        self._sync_capture_state("SELECTED")
        if selection.warnings:
            QMessageBox.warning(
                self, "Metadata incompleta", "\n".join(selection.warnings)
            )

    def _start_recording(self) -> None:
        if self.selected_study is None:
            QMessageBox.warning(self, "Captura", "Seleccione un estudio primero.")
            return
        try:
            self.current_capture = self.study_service.start_recording(
                self.selected_study.id
            )
        except Exception as exc:
            QMessageBox.critical(self, "Iniciar grabación", str(exc))
            self.refresh_pending()
            return
        self._sync_capture_state("RECORDING")

    def _stop_recording(self) -> None:
        if self.current_capture is None:
            return
        capture_id = self.current_capture.id
        self.capture_view.stop_button.setEnabled(False)
        self._run_async(
            lambda: self.study_service.stop_recording(capture_id),
            self._capture_updated,
            description="Detener grabación",
            on_error=self._reload_current_capture,
        )

    def _create_snapshot(self, timestamp_seconds: float) -> None:
        if self.current_capture is None:
            QMessageBox.warning(self, "Snapshot", "No hay una captura seleccionada.")
            return
        capture_id = self.current_capture.id
        self.capture_view.snapshot_button.setEnabled(False)
        self._run_async(
            lambda: self.study_service.create_snapshot(capture_id, timestamp_seconds),
            self._capture_updated,
            description="Crear snapshot",
            on_finished=lambda: self._sync_capture_state(),
            on_error=self._reload_current_capture,
        )

    def _create_dicom(self) -> None:
        if self.current_capture is None:
            return
        capture_id = self.current_capture.id
        self.capture_view.dicom_button.setEnabled(False)
        self._run_async(
            lambda: self.study_service.create_dicom_image(capture_id),
            self._dicom_created,
            description="Generar DICOM",
            on_finished=lambda: self._sync_capture_state(),
            on_error=self._reload_current_capture,
        )

    def _send_to_pacs(self) -> None:
        if self.current_capture is None:
            return
        capture_id = self.current_capture.id
        self.capture_view.send_button.setEnabled(False)
        self._run_async(
            lambda: self.export_service.send_capture(capture_id),
            self._export_completed,
            description="Enviar a PACS",
            on_finished=lambda: self._sync_capture_state(),
            on_error=self._reload_current_capture,
        )

    def _capture_updated(self, capture: CaptureRecord) -> None:
        self.current_capture = capture
        self._sync_capture_state(capture.status)
        self.refresh_pending()

    def _dicom_created(self, outcome: DicomCreationOutcome) -> None:
        self.current_capture = outcome.capture
        self._sync_capture_state(outcome.capture.status)
        self.refresh_pending()
        if outcome.build.warnings:
            QMessageBox.warning(
                self,
                "DICOM creado con advertencias",
                "El archivo fue validado, pero revise:\n\n"
                + "\n".join(outcome.build.warnings),
            )

    def _export_completed(self, outcome: ExportOutcome) -> None:
        self.current_capture = self.database.get_capture(outcome.export.capture_id)
        self._sync_capture_state(self.current_capture.status)
        self.refresh_pending()
        if outcome.export.status == "SENT":
            QMessageBox.information(self, "PACS", outcome.message)
        else:
            QMessageBox.critical(self, "PACS", outcome.message)

    def _retry_selected(self) -> None:
        row = self.pending_table.currentRow()
        item = self.pending_table.item(row, 0) if row >= 0 else None
        if item is None:
            QMessageBox.warning(self, "Reintento", "Seleccione una captura pendiente.")
            return
        capture_id = int(item.data(Qt.UserRole))
        self.retry_button.setEnabled(False)
        self._run_async(
            lambda: self.export_service.retry_capture(capture_id),
            self._export_completed,
            description="Reintentar envío",
            on_finished=lambda: self.retry_button.setEnabled(True),
        )

    def refresh_pending(self) -> None:
        rows = self.database.list_pending_captures()
        self.pending_table.setRowCount(len(rows))
        for row_number, row in enumerate(rows):
            status = row.get("export_status") or row.get("capture_status") or ""
            response = row.get("response_status") or row.get("error_message") or ""
            values = (
                str(row["capture_id"]),
                str(row["patient_name"] or ""),
                str(row["patient_id"] or ""),
                str(row["accession_number"] or ""),
                str(status),
                str(response),
            )
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(value)
                if column == 0:
                    table_item.setData(Qt.UserRole, int(row["capture_id"]))
                self.pending_table.setItem(row_number, column, table_item)

    def _diagnose_devices(self) -> None:
        self.capture_view.devices_button.setEnabled(False)
        self._run_async(
            self.study_service.capture_manager.diagnose_devices,
            self._show_device_diagnostic,
            description="Diagnóstico FFmpeg",
            on_finished=lambda: self.capture_view.devices_button.setEnabled(True),
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
        selected = self.selected_study is not None
        recording = self.study_service.capture_manager.is_recording
        has_video = bool(capture and capture.video_path and capture.ended_at)
        has_snapshot = bool(capture and capture.snapshot_path)
        has_dicom = bool(capture and capture.dicom_image_path)
        self.capture_view.set_workflow_state(
            selected=selected,
            recording=recording,
            has_video=has_video,
            has_snapshot=has_snapshot,
            has_dicom=has_dicom,
            status_text=status_text or (capture.status if capture else None),
        )

    def _reload_current_capture(self) -> None:
        if self.current_capture is not None:
            self.current_capture = self.database.get_capture(self.current_capture.id)
        self._sync_capture_state()
        self.refresh_pending()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.study_service.capture_manager.is_recording:
            answer = QMessageBox.question(
                self,
                "Grabación activa",
                "Hay una grabación activa. ¿Detenerla y cerrar?",
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
