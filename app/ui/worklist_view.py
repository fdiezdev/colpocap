"""Worklist filters and result table."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDateEdit,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.dicom.worklist_client import WorklistItem, WorklistQuery


class WorklistView(QWidget):
    search_requested = Signal(object)
    selection_requested = Signal(object)

    COLUMNS = (
        "Paciente",
        "Patient ID",
        "Nacimiento",
        "Sexo",
        "Accession Number",
        "Procedimiento",
        "Fecha/hora programada",
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[WorklistItem] = []
        layout = QVBoxLayout(self)

        filter_row = QHBoxLayout()
        form = QFormLayout()
        self.use_date = QCheckBox("Filtrar por fecha")
        self.use_date.setChecked(True)
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd/MM/yyyy")
        date_row = QHBoxLayout()
        date_row.addWidget(self.use_date)
        date_row.addWidget(self.date)
        form.addRow("Fecha:", date_row)
        self.patient_id = QLineEdit()
        self.patient_name = QLineEdit()
        self.accession = QLineEdit()
        form.addRow("Patient ID:", self.patient_id)
        form.addRow("Patient Name:", self.patient_name)
        form.addRow("Accession Number:", self.accession)
        filter_row.addLayout(form, 1)
        self.search_button = QPushButton("Buscar")
        self.search_button.clicked.connect(self._emit_search)
        filter_row.addWidget(self.search_button, alignment=Qt.AlignBottom)
        layout.addLayout(filter_row)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self._emit_selection)
        layout.addWidget(self.table)

        self.select_button = QPushButton("Seleccionar estudio")
        self.select_button.clicked.connect(self._emit_selection)
        layout.addWidget(self.select_button)

    def set_results(self, items: list[WorklistItem]) -> None:
        self._items = items
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            procedure = (
                item.scheduled_procedure_step_description
                or item.requested_procedure_description
            )
            scheduled = " ".join(
                part for part in (item.scheduled_start_date, item.scheduled_start_time) if part
            )
            values = (
                item.patient_name,
                item.patient_id,
                item.patient_birth_date,
                item.patient_sex,
                item.accession_number,
                procedure,
                scheduled,
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        if items:
            self.table.selectRow(0)

    def set_busy(self, busy: bool) -> None:
        self.search_button.setEnabled(not busy)
        self.select_button.setEnabled(not busy)

    def _emit_search(self) -> None:
        scheduled_date = (
            self.date.date().toString("yyyyMMdd") if self.use_date.isChecked() else ""
        )
        self.search_requested.emit(
            WorklistQuery(
                scheduled_date=scheduled_date,
                patient_name=self.patient_name.text().strip(),
                patient_id=self.patient_id.text().strip(),
                accession_number=self.accession.text().strip(),
            )
        )

    def _emit_selection(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._items):
            self.selection_requested.emit(self._items[row])

