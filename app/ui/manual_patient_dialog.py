"""Manual patient entry used during Worklist downtime."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app.dicom.worklist_client import WorklistItem


def build_manual_worklist_item(
    *,
    patient_name: str,
    patient_id: str,
    accession_number: str = "",
    patient_birth_date: str = "",
    patient_sex: str = "",
    procedure_description: str = "",
    referring_physician_name: str = "",
    now: datetime | None = None,
) -> WorklistItem:
    """Validate manual values and normalize them as a regular Worklist item."""
    name = patient_name.strip()
    identifier = patient_id.strip()
    if not name:
        raise ValueError("Ingrese el nombre del paciente.")
    if not identifier:
        raise ValueError("Ingrese el Patient ID.")

    current = now or datetime.now().astimezone()
    accession = accession_number.strip() or f"MAN-{current:%y%m%d%H%M%S}"
    procedure = procedure_description.strip() or "Colposcopía"
    short_timestamp = current.strftime("%y%m%d%H%M%S")
    return WorklistItem(
        patient_name=name,
        patient_id=identifier,
        patient_birth_date=patient_birth_date.strip(),
        patient_sex=patient_sex.strip(),
        accession_number=accession[:16],
        requested_procedure_id=f"MAN-{short_timestamp}"[:16],
        requested_procedure_description=procedure,
        referring_physician_name=referring_physician_name.strip(),
        scheduled_start_date=current.strftime("%Y%m%d"),
        scheduled_start_time=current.strftime("%H%M%S"),
        modality="ES",
        scheduled_procedure_step_description=procedure,
        scheduled_procedure_step_id=f"MAN-{short_timestamp}"[:16],
        source="manual",
    )


class ManualPatientDialog(QDialog):
    """Collect the minimum safe metadata for an offline patient entry."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Carga manual de paciente")
        self.setModal(True)
        self.setMinimumWidth(560)
        self._worklist_item: WorklistItem | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(16)

        explanation = QLabel(
            "Use esta opción cuando la Worklist no esté disponible. Verifique los "
            "datos antes de iniciar el estudio."
        )
        explanation.setObjectName("supportingText")
        explanation.setWordWrap(True)
        root.addWidget(explanation)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)

        self.patient_name = QLineEdit()
        self.patient_name.setPlaceholderText("APELLIDO^NOMBRE o nombre completo")
        self.patient_id = QLineEdit()
        self.patient_id.setPlaceholderText("Identificador institucional")
        self.accession_number = QLineEdit()
        self.accession_number.setMaxLength(16)
        self.accession_number.setPlaceholderText(
            "Opcional; se genera uno si queda vacío"
        )

        birth_row = QHBoxLayout()
        self.birth_date_known = QCheckBox("Conocida")
        self.birth_date = QDateEdit(QDate.currentDate())
        self.birth_date.setCalendarPopup(True)
        self.birth_date.setDisplayFormat("dd/MM/yyyy")
        self.birth_date.setEnabled(False)
        self.birth_date_known.toggled.connect(self.birth_date.setEnabled)
        birth_row.addWidget(self.birth_date_known)
        birth_row.addWidget(self.birth_date, 1)

        self.patient_sex = QComboBox()
        self.patient_sex.addItem("Sin especificar", "")
        self.patient_sex.addItem("Femenino", "F")
        self.patient_sex.addItem("Masculino", "M")
        self.patient_sex.addItem("Otro", "O")

        self.procedure_description = QLineEdit("Colposcopía")
        self.referring_physician = QLineEdit()
        self.referring_physician.setPlaceholderText("Opcional")

        form.addRow("Nombre del paciente *", self.patient_name)
        form.addRow("Patient ID *", self.patient_id)
        form.addRow("Accession Number", self.accession_number)
        form.addRow("Fecha de nacimiento", birth_row)
        form.addRow("Sexo", self.patient_sex)
        form.addRow("Procedimiento", self.procedure_description)
        form.addRow("Médico referente", self.referring_physician)
        root.addLayout(form)

        required = QLabel("* Campos obligatorios")
        required.setObjectName("supportingText")
        root.addWidget(required)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        save_button = self.buttons.button(QDialogButtonBox.Save)
        save_button.setText("Agregar a la Worklist")
        save_button.setObjectName("primaryButton")
        self.buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons, alignment=Qt.AlignRight)

    @property
    def worklist_item(self) -> WorklistItem | None:
        return self._worklist_item

    def accept(self) -> None:
        birth_date = (
            self.birth_date.date().toString("yyyyMMdd")
            if self.birth_date_known.isChecked()
            else ""
        )
        try:
            self._worklist_item = build_manual_worklist_item(
                patient_name=self.patient_name.text(),
                patient_id=self.patient_id.text(),
                accession_number=self.accession_number.text(),
                patient_birth_date=birth_date,
                patient_sex=str(self.patient_sex.currentData() or ""),
                procedure_description=self.procedure_description.text(),
                referring_physician_name=self.referring_physician.text(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Datos incompletos", str(exc))
            return
        super().accept()
