"""Operational DICOM and camera configuration screen."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.config import DicomEndpointConfig, Settings, VideoConfig


class ConfigurationView(QWidget):
    back_requested = Signal()
    save_requested = Signal()
    test_worklist_requested = Signal()
    test_pacs_requested = Signal()
    devices_requested = Signal()

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)

        header = QHBoxLayout()
        self.back_button = QPushButton("← Menú principal")
        title = QLabel("Configuración")
        title.setStyleSheet("font-size: 24px; font-weight: 600;")
        header.addWidget(self.back_button)
        header.addWidget(title)
        header.addStretch()
        root.addLayout(header)

        explanation = QLabel(
            "Configure las conexiones DICOM y la cámara. Puede probar cada destino "
            "antes de guardar los cambios."
        )
        explanation.setWordWrap(True)
        root.addWidget(explanation)

        local_box = QGroupBox("Estación local")
        local_form = QFormLayout(local_box)
        self.local_ae_title = QLineEdit()
        self.local_ae_title.setMaxLength(16)
        local_form.addRow("AE Title local:", self.local_ae_title)
        root.addWidget(local_box)

        endpoints = QHBoxLayout()
        worklist_box = QGroupBox("Worklist (MWL)")
        worklist_form = QFormLayout(worklist_box)
        self.worklist_ae = QLineEdit()
        self.worklist_ae.setMaxLength(16)
        self.worklist_host = QLineEdit()
        self.worklist_port = self._port_field()
        self.worklist_status = QLabel("No probado")
        self.worklist_test_button = QPushButton("Probar Worklist")
        worklist_form.addRow("AE Title:", self.worklist_ae)
        worklist_form.addRow("Host / IP:", self.worklist_host)
        worklist_form.addRow("Puerto:", self.worklist_port)
        worklist_form.addRow(self.worklist_test_button, self.worklist_status)
        endpoints.addWidget(worklist_box)

        pacs_box = QGroupBox("PACS (DICOM Store)")
        pacs_form = QFormLayout(pacs_box)
        self.pacs_ae = QLineEdit()
        self.pacs_ae.setMaxLength(16)
        self.pacs_host = QLineEdit()
        self.pacs_port = self._port_field()
        self.pacs_status = QLabel("No probado")
        self.pacs_test_button = QPushButton("Probar PACS")
        pacs_form.addRow("AE Title:", self.pacs_ae)
        pacs_form.addRow("Host / IP:", self.pacs_host)
        pacs_form.addRow("Puerto:", self.pacs_port)
        pacs_form.addRow(self.pacs_test_button, self.pacs_status)
        endpoints.addWidget(pacs_box)
        root.addLayout(endpoints)

        camera_box = QGroupBox("Cámara y grabación local")
        camera_form = QFormLayout(camera_box)
        self.device_name = QLineEdit()
        self.resolution = QLineEdit()
        self.fps = QSpinBox()
        self.fps.setRange(1, 120)
        self.bitrate = QLineEdit()
        self.devices_button = QPushButton("Detectar dispositivos de video")
        camera_form.addRow("Dispositivo:", self.device_name)
        camera_form.addRow("Resolución:", self.resolution)
        camera_form.addRow("FPS:", self.fps)
        camera_form.addRow("Bitrate:", self.bitrate)
        camera_form.addRow("", self.devices_button)
        root.addWidget(camera_box)

        footer = QHBoxLayout()
        footer.addStretch()
        self.save_button = QPushButton("Guardar configuración")
        self.save_button.setMinimumHeight(42)
        footer.addWidget(self.save_button)
        root.addLayout(footer)
        root.addStretch()

        self.back_button.clicked.connect(self.back_requested)
        self.save_button.clicked.connect(self.save_requested)
        self.worklist_test_button.clicked.connect(self.test_worklist_requested)
        self.pacs_test_button.clicked.connect(self.test_pacs_requested)
        self.devices_button.clicked.connect(self.devices_requested)
        self.load_settings(settings)

    @staticmethod
    def _port_field() -> QSpinBox:
        field = QSpinBox()
        field.setRange(1, 65535)
        return field

    def load_settings(self, settings: Settings) -> None:
        self.local_ae_title.setText(settings.local_ae_title)
        self.worklist_ae.setText(settings.worklist.ae_title)
        self.worklist_host.setText(settings.worklist.host)
        self.worklist_port.setValue(settings.worklist.port)
        self.pacs_ae.setText(settings.pacs.ae_title)
        self.pacs_host.setText(settings.pacs.host)
        self.pacs_port.setValue(settings.pacs.port)
        self.device_name.setText(settings.video.device_name)
        self.resolution.setText(settings.video.resolution)
        self.fps.setValue(settings.video.fps)
        self.bitrate.setText(settings.video.bitrate)

    def editable_values(
        self,
    ) -> tuple[str, DicomEndpointConfig, DicomEndpointConfig, VideoConfig]:
        local_ae = self.local_ae_title.text().strip()
        worklist = DicomEndpointConfig(
            self.worklist_ae.text().strip(),
            self.worklist_host.text().strip(),
            self.worklist_port.value(),
        )
        pacs = DicomEndpointConfig(
            self.pacs_ae.text().strip(),
            self.pacs_host.text().strip(),
            self.pacs_port.value(),
        )
        video = VideoConfig(
            self.device_name.text().strip(),
            self.resolution.text().strip(),
            self.fps.value(),
            self.bitrate.text().strip(),
        )
        return local_ae, worklist, pacs, video

    def set_test_busy(self, target: str, busy: bool) -> None:
        button = (
            self.worklist_test_button if target == "worklist" else self.pacs_test_button
        )
        button.setEnabled(not busy)

    def show_connection_result(self, target: str, success: bool, message: str) -> None:
        label = self.worklist_status if target == "worklist" else self.pacs_status
        label.setText(("Conectado: " if success else "Falló: ") + message)
        label.setStyleSheet("color: green" if success else "color: red")

