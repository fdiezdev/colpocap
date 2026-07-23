"""Guided live capture screen with snapshot gallery."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.db.models import CaptureImageRecord, StudyRecord


class PreviewLabel(QLabel):
    def __init__(self) -> None:
        super().__init__("La cámara se mostrará aquí al iniciar el estudio")
        self._source = QPixmap()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(680, 382)
        self.setStyleSheet(
            "background: #10171A; color: #D6E0E3; border-radius: 10px; "
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
    snapshot_review_requested = Signal(int)
    cancel_requested = Signal()
    finish_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._latest_frame = b""
        self._recording = False
        self.setObjectName("page")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 26, 30, 26)
        root.setSpacing(16)

        header = QHBoxLayout()
        self.back_button = QPushButton("‹  Volver a Worklist")
        self.back_button.setObjectName("navigationButton")
        title = QLabel("Captura del estudio")
        title.setObjectName("pageTitle")
        header.addWidget(self.back_button)
        header.addWidget(title)
        header.addStretch()
        root.addLayout(header)

        content = QHBoxLayout()
        content.setSpacing(18)

        controls_panel = QFrame()
        controls_panel.setObjectName("studyControlsPanel")
        controls_panel.setMinimumWidth(245)
        controls_panel.setMaximumWidth(285)
        controls = QVBoxLayout(controls_panel)
        controls.setContentsMargins(18, 18, 18, 18)
        controls.setSpacing(12)

        patient_label = QLabel("Paciente")
        patient_label.setObjectName("panelLabel")
        controls.addWidget(patient_label)
        self.selected_patient = QLabel("Ningún estudio seleccionado")
        self.selected_patient.setWordWrap(True)
        self.selected_patient.setObjectName("patientSummary")
        controls.addWidget(self.selected_patient)

        status_label = QLabel("Estado")
        status_label.setObjectName("panelLabel")
        controls.addWidget(status_label)
        self.workflow_status = QLabel("Sin selección")
        self.workflow_status.setObjectName("workflowStatus")
        self.workflow_status.setWordWrap(True)
        controls.addWidget(self.workflow_status)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setObjectName("panelSeparator")
        controls.addWidget(separator)

        self.start_button = QPushButton("Iniciar estudio y cámara")
        self.snapshot_button = QPushButton("Capturar snapshot")
        self.start_button.setObjectName("secondaryButton")
        self.snapshot_button.setObjectName("primaryButton")
        self.start_button.setMinimumHeight(58)
        self.snapshot_button.setMinimumHeight(58)
        controls.addWidget(self.start_button)
        controls.addWidget(self.snapshot_button)
        shortcut_hint = QLabel("Atajo: barra espaciadora")
        shortcut_hint.setObjectName("shortcutHint")
        shortcut_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        controls.addWidget(shortcut_hint)
        controls.addStretch()

        self.cancel_button = QPushButton("Cancelar estudio")
        self.cancel_button.setObjectName("dangerButton")
        self.cancel_button.setMinimumHeight(48)
        self.finish_button = QPushButton("Finalizar estudio")
        self.finish_button.setObjectName("primaryButton")
        self.finish_button.setMinimumHeight(62)
        controls.addWidget(self.cancel_button)
        controls.addWidget(self.finish_button)
        content.addWidget(controls_panel)

        study_area = QVBoxLayout()
        study_area.setSpacing(14)
        self.preview = PreviewLabel()
        study_area.addWidget(self.preview, 1)

        snapshots_panel = QFrame()
        snapshots_panel.setObjectName("snapshotsPanel")
        snapshots_panel.setMaximumHeight(168)
        snapshots_layout = QVBoxLayout(snapshots_panel)
        snapshots_layout.setContentsMargins(12, 10, 12, 8)
        snapshots_layout.setSpacing(6)
        snapshots_header = QHBoxLayout()
        snapshots_header.setSpacing(12)
        self.gallery_title = QLabel("Snapshots (0)")
        self.gallery_title.setObjectName("snapshotsTitle")
        snapshots_header.addWidget(self.gallery_title)
        snapshots_header.addStretch()
        gallery_hint = QLabel("Doble clic para revisar")
        gallery_hint.setObjectName("shortcutHint")
        snapshots_header.addWidget(gallery_hint)
        snapshots_layout.addLayout(snapshots_header)
        self.gallery = QListWidget()
        self.gallery.setViewMode(QListView.IconMode)
        self.gallery.setFlow(QListView.LeftToRight)
        self.gallery.setWrapping(False)
        self.gallery.setResizeMode(QListView.Fixed)
        self.gallery.setMovement(QListView.Static)
        self.gallery.setSelectionMode(QAbstractItemView.SingleSelection)
        self.gallery.setIconSize(QSize(128, 72))
        self.gallery.setGridSize(QSize(145, 94))
        self.gallery.setSpacing(4)
        self.gallery.setUniformItemSizes(True)
        self.gallery.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.gallery.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.gallery.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.gallery.setMinimumHeight(112)
        self.gallery.setMaximumHeight(122)
        snapshots_layout.addWidget(self.gallery)
        study_area.addWidget(snapshots_panel)
        content.addLayout(study_area, 1)
        root.addLayout(content, 1)

        self.back_button.clicked.connect(self.back_requested)
        self.start_button.clicked.connect(self.start_requested)
        self.snapshot_button.clicked.connect(self.snapshot_requested)
        self.gallery.itemDoubleClicked.connect(self._request_snapshot_review)
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.finish_button.clicked.connect(self.finish_requested)
        self.snapshot_shortcut = QShortcut(
            QKeySequence(Qt.Key.Key_Space), self
        )
        self.snapshot_shortcut.setContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
        )
        self.snapshot_shortcut.setAutoRepeat(False)
        self.snapshot_shortcut.activated.connect(
            self._request_snapshot_from_shortcut
        )
        self.set_workflow_state()

    def _request_snapshot_from_shortcut(self) -> None:
        if self._recording and self.snapshot_button.isEnabled():
            self.snapshot_requested.emit()

    @property
    def latest_frame_jpeg(self) -> bytes:
        return self._latest_frame

    def set_selected_study(self, study: StudyRecord) -> None:
        self.selected_patient.setText(
            f"{study.patient_name or '(sin nombre)'}\n"
            f"Patient ID: {study.patient_id or '(vacío)'}\n"
            f"Accession: "
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
        item.setData(Qt.ItemDataRole.UserRole, image.id)
        item.setToolTip("Doble clic para revisar este snapshot")
        self.gallery.addItem(item)
        self.gallery.scrollToItem(item, QAbstractItemView.PositionAtCenter)
        self.gallery_title.setText(f"Snapshots ({self.gallery.count()})")

    def remove_snapshot(self, image_id: int) -> None:
        for row in range(self.gallery.count()):
            item = self.gallery.item(row)
            if int(item.data(Qt.ItemDataRole.UserRole)) == image_id:
                self.gallery.takeItem(row)
                break
        self.gallery_title.setText(f"Snapshots ({self.gallery.count()})")

    def _request_snapshot_review(self, item: QListWidgetItem) -> None:
        image_id = item.data(Qt.ItemDataRole.UserRole)
        if image_id is not None:
            self.snapshot_review_requested.emit(int(image_id))

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
        can_cancel: bool = False,
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
        self.cancel_button.setEnabled(can_cancel and not busy)
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
