"""Guided live capture screen with snapshot gallery."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap, QResizeEvent, QTextCursor
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.db.models import CaptureImageRecord, StudyRecord


class PreviewLabel(QLabel):
    def __init__(self) -> None:
        super().__init__("La cámara se mostrará aquí al iniciar el estudio")
        self._source = QPixmap()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(640, 360)
        self.setStyleSheet(
            "background: #16191d; color: #d6d8db; border-radius: 6px; "
            "font-size: 16px;"
        )

    def set_source(self, pixmap: QPixmap) -> None:
        self._source = pixmap
        self._refresh()

    def clear_source(self, message: str) -> None:
        self._source = QPixmap()
        self.clear()
        self.setText(message)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        if not self._source.isNull():
            self.setPixmap(
                self._source.scaled(
                    self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )


class CaptureView(QWidget):
    back_requested = Signal()
    start_requested = Signal()
    snapshot_requested = Signal()
    finish_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._latest_frame = b""
        self._recording = False
        root = QVBoxLayout(self)

        header = QHBoxLayout()
        self.back_button = QPushButton("← Volver a Worklist")
        title = QLabel("Captura del estudio")
        title.setStyleSheet("font-size: 24px; font-weight: 600;")
        header.addWidget(self.back_button)
        header.addWidget(title)
        header.addStretch()
        self.step_label = QLabel("Paso 3 de 3")
        header.addWidget(self.step_label)
        root.addLayout(header)

        form = QFormLayout()
        self.selected_patient = QLabel("Ningún estudio seleccionado")
        self.selected_patient.setWordWrap(True)
        self.workflow_status = QLabel("Sin selección")
        self.workflow_status.setStyleSheet("font-weight: 600;")
        form.addRow("Estudio:", self.selected_patient)
        form.addRow("Estado:", self.workflow_status)
        root.addLayout(form)

        content = QHBoxLayout()
        camera_column = QVBoxLayout()
        self.preview = PreviewLabel()
        camera_column.addWidget(self.preview, 1)

        primary_controls = QHBoxLayout()
        self.start_button = QPushButton("1. Iniciar estudio y cámara")
        self.snapshot_button = QPushButton("2. Capturar snapshot")
        self.finish_button = QPushButton("3. Finalizar y enviar al PACS")
        for button in (self.start_button, self.snapshot_button, self.finish_button):
            button.setMinimumHeight(48)
        self.snapshot_button.setStyleSheet("font-weight: 600;")
        primary_controls.addWidget(self.start_button)
        primary_controls.addWidget(self.snapshot_button)
        primary_controls.addWidget(self.finish_button)
        camera_column.addLayout(primary_controls)

        hint = QLabel(
            "El snapshot guarda exactamente el cuadro visible. Puede tomar todas las "
            "imágenes necesarias; se convierten a DICOM y se envían juntas al finalizar."
        )
        hint.setWordWrap(True)
        camera_column.addWidget(hint)
        content.addLayout(camera_column, 4)

        gallery_column = QVBoxLayout()
        self.gallery_title = QLabel("Snapshots (0)")
        self.gallery_title.setStyleSheet("font-size: 17px; font-weight: 600;")
        gallery_column.addWidget(self.gallery_title)
        self.gallery = QListWidget()
        self.gallery.setViewMode(QListWidget.IconMode)
        self.gallery.setIconSize(QSize(180, 105))
        self.gallery.setGridSize(QSize(200, 145))
        self.gallery.setResizeMode(QListWidget.Adjust)
        self.gallery.setMovement(QListWidget.Static)
        gallery_column.addWidget(self.gallery, 1)
        content.addLayout(gallery_column, 2)
        root.addLayout(content, 1)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(115)
        self.log_view.document().setMaximumBlockCount(1000)
        root.addWidget(self.log_view)

        self.back_button.clicked.connect(self.back_requested)
        self.start_button.clicked.connect(self.start_requested)
        self.snapshot_button.clicked.connect(self.snapshot_requested)
        self.finish_button.clicked.connect(self.finish_requested)
        self.set_workflow_state()

    @property
    def latest_frame_jpeg(self) -> bytes:
        return self._latest_frame

    def set_selected_study(self, study: StudyRecord) -> None:
        self.selected_patient.setText(
            f"{study.patient_name or '(sin nombre)'} | PatientID: "
            f"{study.patient_id or '(vacío)'} | Accession: "
            f"{study.accession_number or '(vacío)'}"
        )
        self.clear_session()

    def show_preview_frame(self, jpeg_data: bytes) -> None:
        pixmap = QPixmap()
        if not pixmap.loadFromData(jpeg_data, "JPEG"):
            return
        self._latest_frame = jpeg_data
        self.preview.set_source(pixmap)
        if self._recording:
            self.snapshot_button.setEnabled(True)

    def add_snapshot(self, image: CaptureImageRecord) -> None:
        pixmap = QPixmap(str(Path(image.snapshot_path)))
        item = QListWidgetItem(
            QIcon(pixmap), f"Snapshot {image.instance_number:02d}"
        )
        item.setToolTip(image.snapshot_path)
        self.gallery.addItem(item)
        self.gallery_title.setText(f"Snapshots ({self.gallery.count()})")

    def clear_session(self) -> None:
        self._latest_frame = b""
        self._recording = False
        self.gallery.clear()
        self.gallery_title.setText("Snapshots (0)")
        self.preview.clear_source("La cámara se mostrará aquí al iniciar el estudio")

    def set_workflow_state(
        self,
        *,
        selected: bool = False,
        can_start: bool = True,
        recording: bool = False,
        snapshot_count: int = 0,
        busy: bool = False,
        status_text: str | None = None,
    ) -> None:
        self._recording = recording
        self.start_button.setEnabled(
            selected and can_start and not recording and not busy
        )
        self.snapshot_button.setEnabled(
            recording and bool(self._latest_frame) and not busy
        )
        self.finish_button.setEnabled(snapshot_count > 0 and not busy)
        self.back_button.setEnabled(not recording and not busy)
        if busy:
            shown_status = status_text or "Finalizando y enviando…"
        elif recording:
            shown_status = status_text or "Cámara activa: capture los snapshots necesarios"
        else:
            shown_status = status_text or ("Listo para iniciar" if selected else "Sin selección")
        self.workflow_status.setText(shown_status)

    def mark_finished(self, message: str) -> None:
        self._recording = False
        self._latest_frame = b""
        self.preview.clear_source(message)

    def append_log(self, message: str) -> None:
        self.log_view.append(message)
        self.log_view.moveCursor(QTextCursor.End)
