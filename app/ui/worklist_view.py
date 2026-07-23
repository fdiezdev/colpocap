"""Worklist filters and result table."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDateEdit,
    QFormLayout,
    QGroupBox,
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
from .manual_patient_dialog import ManualPatientDialog


class WorklistView(QWidget):
    search_requested = Signal(object)
    selection_requested = Signal(object)
    manual_patient_added = Signal(object)

    COLUMNS = (
        "Origen",
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
        self._manual_items: list[WorklistItem] = []
        self.setObjectName("page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(14)

        filter_box = QGroupBox("Filtros de búsqueda")
        filter_row = QHBoxLayout(filter_box)
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
        self.patient_id.setPlaceholderText("Patient ID")
        self.patient_name = QLineEdit()
        self.patient_name.setPlaceholderText("Nombre o apellido")
        self.accession = QLineEdit()
        self.accession.setPlaceholderText("Accession Number")
        form.addRow("Patient ID:", self.patient_id)
        form.addRow("Patient Name:", self.patient_name)
        form.addRow("Accession Number:", self.accession)
        filter_row.addLayout(form, 1)
        action_column = QVBoxLayout()
        self.search_button = QPushButton("Buscar en Worklist")
        self.search_button.setObjectName("primaryButton")
        self.search_button.clicked.connect(self._emit_search)
        self.manual_button = QPushButton("Cargar paciente manualmente")
        self.manual_button.setObjectName("secondaryButton")
        self.manual_button.clicked.connect(self._open_manual_patient)
        action_column.addStretch()
        action_column.addWidget(self.search_button)
        action_column.addWidget(self.manual_button)
        filter_row.addLayout(action_column)
        layout.addWidget(filter_box)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self._emit_selection)
        layout.addWidget(self.table)

        self.select_button = QPushButton("Seleccionar estudio")
        self.select_button.setObjectName("primaryButton")
        self.select_button.clicked.connect(self._emit_selection)
        layout.addWidget(self.select_button, alignment=Qt.AlignRight)

    def set_results(self, items: list[WorklistItem]) -> None:
        self._items = [*self._manual_items, *items]
        self._refresh_table()

    def add_manual_item(self, item: WorklistItem) -> None:
        self._manual_items.insert(0, item)
        network_items = [item for item in self._items if item.source != "manual"]
        self._items = [*self._manual_items, *network_items]
        self._refresh_table()
        self.table.selectRow(0)
        self.table.scrollToTop()
        self.manual_patient_added.emit(item)

    def _refresh_table(self) -> None:
        self.table.setRowCount(len(self._items))
        for row, item in enumerate(self._items):
            procedure = (
                item.scheduled_procedure_step_description
                or item.requested_procedure_description
            )
            scheduled = " ".join(
                part for part in (item.scheduled_start_date, item.scheduled_start_time) if part
            )
            values = (
                "Carga manual" if item.source == "manual" else "Worklist",
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
        if self._items:
            self.table.selectRow(0)

    def set_busy(self, busy: bool) -> None:
        self.search_button.setEnabled(not busy)
        self.manual_button.setEnabled(not busy)
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

    def _open_manual_patient(self) -> None:
        dialog = ManualPatientDialog(self)
        if dialog.exec() != ManualPatientDialog.Accepted:
            return
        if dialog.worklist_item is not None:
            self.add_manual_item(dialog.worklist_item)
