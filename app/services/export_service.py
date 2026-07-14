"""Audited C-STORE export and retry use cases."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

from pydicom import dcmread

from app.db.database import Database
from app.db.models import ExportRecord, WorkflowStatus
from app.dicom.store_client import EchoResult, StoreClient, StoreError, StoreResult

LOGGER = logging.getLogger(__name__)


class ExportWorkflowError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExportOutcome:
    export: ExportRecord
    store_result: StoreResult | None
    message: str


class ExportService:
    def __init__(self, database: Database, store_client: StoreClient) -> None:
        self.database = database
        self.store_client = store_client

    def test_pacs(self) -> EchoResult:
        return self.store_client.echo()

    def send_capture(self, capture_id: int) -> ExportOutcome:
        capture = self.database.get_capture(capture_id)
        if not capture.dicom_image_path:
            raise ExportWorkflowError("No hay un archivo DICOM generado para esta captura.")
        dicom_path = Path(capture.dicom_image_path)
        if not dicom_path.is_file():
            raise ExportWorkflowError(f"No existe el DICOM registrado: {dicom_path}")
        try:
            dataset = dcmread(dicom_path, stop_before_pixels=True)
            sop_instance_uid = str(dataset.SOPInstanceUID)
            sop_class_uid = str(dataset.SOPClassUID)
        except Exception as exc:
            raise ExportWorkflowError(
                f"El DICOM no puede abrirse antes del envío: {exc}"
            ) from exc

        endpoint = self.store_client.endpoint
        export = self.database.create_export(
            capture_id=capture_id,
            sop_instance_uid=sop_instance_uid,
            sop_class_uid=sop_class_uid,
            destination_ae=endpoint.ae_title,
            destination_host=endpoint.host,
            destination_port=endpoint.port,
        )
        LOGGER.info("Intento de exportación %s para captura %s", export.id, capture_id)
        try:
            echo = self.store_client.echo()
            if not echo.success:
                raise StoreError(f"C-ECHO previo falló: {echo.message}")
            store_result = self.store_client.store(dicom_path)
            accepted = store_result.success or store_result.warning
            status = WorkflowStatus.SENT if accepted else WorkflowStatus.FAILED
            completed = self.database.complete_export(
                export.id,
                status=status,
                response_status=store_result.status_hex,
                error_message=None if accepted else store_result.message,
            )
            self.database.update_capture(capture_id, status=status)
            self.database.update_study_status(capture.study_id, status)
            return ExportOutcome(completed, store_result, store_result.message)
        except Exception as exc:
            LOGGER.exception("Falló exportación %s", export.id)
            completed = self.database.complete_export(
                export.id,
                status=WorkflowStatus.FAILED,
                response_status=None,
                error_message=str(exc),
            )
            self.database.update_capture(capture_id, status=WorkflowStatus.FAILED)
            self.database.update_study_status(
                capture.study_id, WorkflowStatus.FAILED
            )
            return ExportOutcome(completed, None, f"Envío fallido: {exc}")

    def retry_capture(self, capture_id: int) -> ExportOutcome:
        LOGGER.info("Reintentando exportación de captura %s", capture_id)
        return self.send_capture(capture_id)

