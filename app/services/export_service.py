"""Audited C-STORE export and retry use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
import re
import shutil
import unicodedata
from uuid import uuid4

from pydicom import dcmread

from app.db.database import Database
from app.db.models import CaptureImageRecord, ExportRecord, WorkflowStatus
from app.dicom.store_client import EchoResult, StoreClient, StoreError, StoreResult

LOGGER = logging.getLogger(__name__)


class ExportWorkflowError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExportOutcome:
    export: ExportRecord
    store_result: StoreResult | None
    message: str


@dataclass(frozen=True)
class BatchExportOutcome:
    capture_id: int
    exports: tuple[ExportRecord, ...]
    store_results: tuple[StoreResult, ...]
    sent_count: int
    total_count: int
    success: bool
    message: str


@dataclass(frozen=True)
class FolderExportOutcome:
    capture_id: int
    directory: Path
    files: tuple[Path, ...]
    message: str


class ExportService:
    def __init__(self, database: Database, store_client: StoreClient) -> None:
        self.database = database
        self.store_client = store_client

    def test_pacs(self) -> EchoResult:
        return self.store_client.echo()

    def export_capture_images(
        self, capture_id: int, destination_directory: str | Path
    ) -> FolderExportOutcome:
        """Copy a complete DICOM study to a new folder on local/removable media."""
        capture = self.database.get_capture(capture_id)
        study = self.database.get_study(capture.study_id)
        images = self.database.list_capture_images(capture_id)
        if images:
            missing = [
                image.instance_number
                for image in images
                if not image.dicom_image_path
            ]
            if missing:
                shown = ", ".join(str(number) for number in missing)
                raise ExportWorkflowError(
                    f"Las imágenes {shown} todavía no tienen un DICOM generado."
                )
            source_paths = [
                Path(str(image.dicom_image_path))
                for image in sorted(images, key=lambda item: item.instance_number)
            ]
        elif capture.dicom_image_path:
            source_paths = [Path(capture.dicom_image_path)]
        else:
            raise ExportWorkflowError(
                "No hay imágenes DICOM preparadas para exportar en este estudio."
            )

        for source in source_paths:
            if not source.is_file():
                raise ExportWorkflowError(f"No existe el DICOM registrado: {source}")
            try:
                dataset = dcmread(source, stop_before_pixels=True)
                str(dataset.SOPClassUID)
                str(dataset.SOPInstanceUID)
            except Exception as exc:
                raise ExportWorkflowError(
                    f"El archivo no es un DICOM válido: {source.name}: {exc}"
                ) from exc

        destination_root = Path(destination_directory).expanduser()
        if not destination_root.is_dir():
            raise ExportWorkflowError(
                f"La carpeta de destino no existe: {destination_root}"
            )

        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        patient = self._safe_path_part(study.patient_id, "SIN_ID")
        accession = self._safe_path_part(study.accession_number, "SIN_ACCESSION")
        base_name = f"ECAP_{patient}_{accession}_{timestamp}"
        final_directory = self._available_directory(destination_root, base_name)
        staging_directory = destination_root / (
            f".ecap-export-{uuid4().hex}.tmp"
        )

        exported_files: list[Path] = []
        try:
            staging_directory.mkdir()
            for number, source in enumerate(source_paths, start=1):
                destination = staging_directory / f"IM_{number:04d}.dcm"
                shutil.copy2(source, destination)
                exported_files.append(destination)
            staging_directory.rename(final_directory)
        except Exception as exc:
            shutil.rmtree(staging_directory, ignore_errors=True)
            raise ExportWorkflowError(
                f"No se pudo exportar el estudio a {destination_root}: {exc}"
            ) from exc

        final_files = tuple(final_directory / path.name for path in exported_files)
        LOGGER.info(
            "Captura %s exportada a %s con %s DICOM",
            capture_id,
            final_directory,
            len(final_files),
        )
        return FolderExportOutcome(
            capture_id=capture_id,
            directory=final_directory,
            files=final_files,
            message=(
                f"Estudio exportado: {len(final_files)} "
                f"{'archivo' if len(final_files) == 1 else 'archivos'} DICOM en "
                f"{final_directory}."
            ),
        )

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

    def send_capture_images(self, capture_id: int) -> BatchExportOutcome:
        """Send all unsent images from a capture in one C-STORE association."""
        capture = self.database.get_capture(capture_id)
        all_images = self.database.list_capture_images(capture_id)
        images = [
            image
            for image in all_images
            if image.dicom_image_path and image.status != WorkflowStatus.SENT
        ]
        if not images:
            if all_images and all(
                image.status == WorkflowStatus.SENT for image in all_images
            ):
                return BatchExportOutcome(
                    capture_id,
                    (),
                    (),
                    len(all_images),
                    len(all_images),
                    True,
                    "Todas las imágenes de este estudio ya fueron enviadas.",
                )
            raise ExportWorkflowError(
                "No hay imágenes DICOM preparadas para enviar en este estudio."
            )

        paths: list[Path] = []
        attempts: list[tuple[CaptureImageRecord, ExportRecord]] = []
        endpoint = self.store_client.endpoint
        for image in images:
            path = Path(str(image.dicom_image_path))
            if not path.is_file():
                raise ExportWorkflowError(f"No existe el DICOM registrado: {path}")
            try:
                dataset = dcmread(path, stop_before_pixels=True)
                sop_instance_uid = str(dataset.SOPInstanceUID)
                sop_class_uid = str(dataset.SOPClassUID)
            except Exception as exc:
                raise ExportWorkflowError(
                    f"El DICOM no puede abrirse antes del envío: {exc}"
                ) from exc
            export = self.database.create_export(
                capture_id=capture_id,
                image_id=image.id,
                sop_instance_uid=sop_instance_uid,
                sop_class_uid=sop_class_uid,
                destination_ae=endpoint.ae_title,
                destination_host=endpoint.host,
                destination_port=endpoint.port,
            )
            attempts.append((image, export))
            paths.append(path)

        completed_exports: list[ExportRecord] = []
        try:
            echo = self.store_client.echo()
            if not echo.success:
                raise StoreError(f"C-ECHO previo falló: {echo.message}")
            results = self.store_client.store_many(paths)
            for (image, export), result in zip(attempts, results, strict=True):
                accepted = result.success or result.warning
                status = WorkflowStatus.SENT if accepted else WorkflowStatus.FAILED
                completed_exports.append(
                    self.database.complete_export(
                        export.id,
                        status=status,
                        response_status=result.status_hex,
                        error_message=None if accepted else result.message,
                    )
                )
                self.database.update_capture_image(image.id, status=status)
        except Exception as exc:
            LOGGER.exception("Falló el envío por lote de captura %s", capture_id)
            completed_ids = {export.id for export in completed_exports}
            for image, export in attempts:
                if export.id in completed_ids:
                    continue
                completed_exports.append(
                    self.database.complete_export(
                        export.id,
                        status=WorkflowStatus.FAILED,
                        response_status=None,
                        error_message=str(exc),
                    )
                )
                self.database.update_capture_image(
                    image.id, status=WorkflowStatus.FAILED
                )
            self.database.update_capture(capture_id, status=WorkflowStatus.FAILED)
            self.database.update_study_status(
                capture.study_id, WorkflowStatus.FAILED
            )
            sent_count = sum(
                image.status == WorkflowStatus.SENT
                for image in self.database.list_capture_images(capture_id)
            )
            return BatchExportOutcome(
                capture_id,
                tuple(completed_exports),
                (),
                sent_count,
                len(all_images),
                False,
                f"Envío del estudio fallido: {exc}",
            )

        refreshed = self.database.list_capture_images(capture_id)
        sent_count = sum(image.status == WorkflowStatus.SENT for image in refreshed)
        success = sent_count == len(refreshed)
        final_status = WorkflowStatus.SENT if success else WorkflowStatus.FAILED
        self.database.update_capture(capture_id, status=final_status)
        self.database.update_study_status(capture.study_id, final_status)
        message = (
            f"Estudio enviado: {sent_count} de {len(refreshed)} imágenes aceptadas "
            "por el PACS en un único envío."
            if success
            else f"Envío incompleto: {sent_count} de {len(refreshed)} imágenes aceptadas."
        )
        return BatchExportOutcome(
            capture_id,
            tuple(completed_exports),
            results,
            sent_count,
            len(refreshed),
            success,
            message,
        )

    def retry_capture(self, capture_id: int) -> ExportOutcome | BatchExportOutcome:
        LOGGER.info("Reintentando exportación de captura %s", capture_id)
        if self.database.list_capture_images(capture_id):
            return self.send_capture_images(capture_id)
        return self.send_capture(capture_id)

    @staticmethod
    def _safe_path_part(value: str, fallback: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_value).strip("._-")
        return (safe or fallback)[:40]

    @staticmethod
    def _available_directory(root: Path, base_name: str) -> Path:
        candidate = root / base_name
        suffix = 2
        while candidate.exists():
            candidate = root / f"{base_name}_{suffix:02d}"
            suffix += 1
        return candidate
