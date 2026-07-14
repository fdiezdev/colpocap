"""Capture workflow controls and local log view."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.db.models import StudyRecord


class CaptureView(QWidget):
    start_requested = Signal()
    stop_requested = Signal()
    snapshot_requested = Signal(float)
    dicom_requested = Signal()
    send_requested = Signal()
    devices_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.selected_patient = QLabel("Ningún estudio seleccionado")
        self.selected_patient.setWordWrap(True)
        self.workflow_status = QLabel("Sin selección")
        form.addRow("Estudio:", self.selected_patient)
        form.addRow("Estado:", self.workflow_status)
        layout.addLayout(form)

        controls = QGridLayout()
        self.start_button = QPushButton("Iniciar grabación")
        self.stop_button = QPushButton("Detener grabación")
        self.snapshot_button = QPushButton("Crear snapshot")
        self.dicom_button = QPushButton("Generar DICOM")
        self.send_button = QPushButton("Enviar a PACS")
        self.devices_button = QPushButton("Listar dispositivos de video")
        self.timestamp = QDoubleSpinBox()
        self.timestamp.setRange(0.0, 86_400.0)
        self.timestamp.setDecimals(1)
        self.timestamp.setValue(1.0)
        self.timestamp.setSuffix(" s")
        controls.addWidget(self.start_button, 0, 0)
        controls.addWidget(self.stop_button, 0, 1)
        controls.addWidget(QLabel("Frame en:"), 1, 0)
        controls.addWidget(self.timestamp, 1, 1)
        controls.addWidget(self.snapshot_button, 1, 2)
        controls.addWidget(self.dicom_button, 2, 0)
        controls.addWidget(self.send_button, 2, 1)
        controls.addWidget(self.devices_button, 2, 2)
        layout.addLayout(controls)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.document().setMaximumBlockCount(1000)
        layout.addWidget(self.log_view)

        self.start_button.clicked.connect(self.start_requested)
        self.stop_button.clicked.connect(self.stop_requested)
        self.snapshot_button.clicked.connect(
            lambda: self.snapshot_requested.emit(self.timestamp.value())
        )
        self.dicom_button.clicked.connect(self.dicom_requested)
        self.send_button.clicked.connect(self.send_requested)
        self.devices_button.clicked.connect(self.devices_requested)
        self.set_workflow_state()

    def set_selected_study(self, study: StudyRecord) -> None:
        self.selected_patient.setText(
            f"{study.patient_name or '(sin nombre)'} | PatientID: "
            f"{study.patient_id or '(vacío)'} | Accession: "
            f"{study.accession_number or '(vacío)'}"
        )

    def set_workflow_state(
        self,
        *,
        selected: bool = False,
        recording: bool = False,
        has_video: bool = False,
        has_snapshot: bool = False,
        has_dicom: bool = False,
        status_text: str | None = None,
    ) -> None:
        self.start_button.setEnabled(selected and not recording)
        self.stop_button.setEnabled(recording)
        self.snapshot_button.setEnabled(has_video and not recording)
        self.dicom_button.setEnabled(has_snapshot and not recording)
        self.send_button.setEnabled(has_dicom and not recording)
        self.workflow_status.setText(status_text or ("Seleccionado" if selected else "Sin selección"))

    def append_log(self, message: str) -> None:
        self.log_view.append(message)
        self.log_view.moveCursor(QTextCursor.End)

