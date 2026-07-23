"""Orchestrate selection, recording, snapshot and still-image DICOM creation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from pathlib import Path
from typing import Callable
from uuid import uuid4

from app.db.database import Database, local_timestamp
from app.db.models import CaptureImageRecord, CaptureRecord, StudyRecord, WorkflowStatus
from app.dicom.dicom_builder import DicomBuildResult, DicomBuilder
from app.dicom.uid import is_valid_uid, new_series_instance_uid, new_study_instance_uid
from app.dicom.worklist_client import WorklistItem
from app.video.capture_manager import CaptureManager
from app.video.snapshot_manager import SnapshotManager

LOGGER = logging.getLogger(__name__)


class StudyWorkflowError(RuntimeError):
    pass


@dataclass(frozen=True)
class StudySelection:
    study: StudyRecord
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class DicomCreationOutcome:
    capture: CaptureRecord
    build: DicomBuildResult


@dataclass(frozen=True)
class BatchDicomCreationOutcome:
    capture: CaptureRecord
    images: tuple[CaptureImageRecord, ...]
    builds: tuple[DicomBuildResult, ...]


class StudyService:
    def __init__(
        self,
        database: Database,
        capture_manager: CaptureManager,
        snapshot_manager: SnapshotManager,
        dicom_builder: DicomBuilder,
        snapshots_dir: str | Path,
        dicom_dir: str | Path,
    ) -> None:
        self.database = database
        self.capture_manager = capture_manager
        self.snapshot_manager = snapshot_manager
        self.dicom_builder = dicom_builder
        self.snapshots_dir = Path(snapshots_dir)
        self.dicom_dir = Path(dicom_dir)
        self.selected_study_id: int | None = None

    def select_worklist_item(self, item: WorklistItem) -> StudySelection:
        if self.capture_manager.is_recording:
            raise StudyWorkflowError("No se puede cambiar de estudio durante una grabación.")
        values = item.to_mapping()
        source_label = "carga manual" if item.source == "manual" else "Worklist"
        warnings: list[str] = []
        for key, label in (
            ("patient_id", "PatientID"),
            ("accession_number", "AccessionNumber"),
        ):
            if not values.get(key):
                warning = f"El estudio de {source_label} no contiene {label}."
                warnings.append(warning)
                LOGGER.warning(warning)

        incoming_uid = str(values.get("study_instance_uid") or "")
        if not is_valid_uid(incoming_uid):
            generated_uid = new_study_instance_uid()
            reason = "ausente" if not incoming_uid else "inválido"
            warning = (
                f"StudyInstanceUID {reason} en {source_label}; se generó {generated_uid} "
                "y quedó registrado localmente."
            )
            if item.source == "manual":
                LOGGER.info(warning)
            else:
                warnings.append(warning)
                LOGGER.warning(warning)
            values["study_instance_uid"] = generated_uid

        study = self.database.create_study(values)
        self.selected_study_id = study.id
        LOGGER.info(
            "Estudio seleccionado: local_id=%s PatientID=%r AccessionNumber=%r",
            study.id,
            study.patient_id,
            study.accession_number,
        )
        return StudySelection(study, tuple(warnings))

    def start_recording(
        self,
        study_id: int | None = None,
        preview_callback: Callable[[bytes], None] | None = None,
    ) -> CaptureRecord:
        selected_id = study_id or self.selected_study_id
        if selected_id is None:
            raise StudyWorkflowError("Seleccione un estudio antes de iniciar la grabación.")
        if self.capture_manager.is_recording:
            raise StudyWorkflowError("Ya hay una grabación activa.")
        study = self.database.get_study(selected_id)
        output_path = self.capture_manager.build_video_path(
            patient_id=study.patient_id,
            accession_number=study.accession_number,
            study_instance_uid=study.study_instance_uid,
        )
        capture = self.database.create_capture(study.id, output_path)
        self.database.update_study_status(study.id, WorkflowStatus.RECORDING)
        try:
            self.capture_manager.start(output_path, preview_callback)
        except Exception:
            self._mark_failed(capture.id, study.id)
            LOGGER.exception("Falló el inicio de grabación para captura %s", capture.id)
            raise
        LOGGER.info("Captura %s en grabación: %s", capture.id, output_path)
        return capture

    def stop_recording(self, capture_id: int) -> CaptureRecord:
        capture = self.database.get_capture(capture_id)
        try:
            video_path = self.capture_manager.stop()
            updated = self.database.update_capture(
                capture_id,
                video_path=str(video_path),
                ended_at=local_timestamp(),
                status=WorkflowStatus.RECORDED,
            )
            self.database.update_study_status(capture.study_id, WorkflowStatus.RECORDED)
            return updated
        except Exception:
            self._mark_failed(capture_id, capture.study_id, ended=True)
            LOGGER.exception("Falló el cierre de captura %s", capture_id)
            raise

    def create_snapshot(
        self, capture_id: int, timestamp_seconds: float = 1.0
    ) -> CaptureRecord:
        capture = self.database.get_capture(capture_id)
        if not capture.video_path:
            raise StudyWorkflowError("La captura no tiene una ruta de video registrada.")
        video_path = Path(capture.video_path)
        if not video_path.is_file():
            raise StudyWorkflowError(f"No existe el MP4 registrado: {video_path}")
        frame_ms = int(timestamp_seconds * 1000)
        snapshot_path = self.snapshots_dir / (
            f"{video_path.stem}_snapshot_{frame_ms:08d}ms_{uuid4().hex[:8]}.jpg"
        )
        try:
            created = self.snapshot_manager.extract(
                video_path, snapshot_path, timestamp_seconds
            )
            updated = self.database.update_capture(
                capture_id,
                snapshot_path=str(created),
                status=WorkflowStatus.SNAPSHOT_CREATED,
            )
            self.database.update_study_status(
                capture.study_id, WorkflowStatus.SNAPSHOT_CREATED
            )
            return updated
        except Exception:
            self._mark_failed(capture_id, capture.study_id)
            LOGGER.exception("Falló la extracción de snapshot para captura %s", capture_id)
            raise

    def create_live_snapshot(
        self, capture_id: int, jpeg_data: bytes
    ) -> CaptureImageRecord:
        """Persist the exact latest frame displayed during an active study."""
        capture = self.database.get_capture(capture_id)
        if not self.capture_manager.is_recording:
            raise StudyWorkflowError(
                "La cámara no está activa. Inicie el estudio antes de capturar."
            )
        existing = self.database.list_capture_images(capture_id)
        instance_number = len(existing) + 1
        video_stem = Path(capture.video_path or f"capture_{capture.id}").stem
        snapshot_path = self.snapshots_dir / (
            f"{video_stem}_snapshot_{instance_number:03d}_{uuid4().hex[:8]}.jpg"
        )
        try:
            created = self.snapshot_manager.save_live_frame(jpeg_data, snapshot_path)
            image = self.database.create_capture_image(
                capture_id=capture_id,
                snapshot_path=created,
                instance_number=instance_number,
            )
            # Keep legacy columns populated for compatibility with existing
            # installations and recovery tooling; the normalized table is the
            # source of truth for the new multi-image workflow.
            self.database.update_capture(capture_id, snapshot_path=str(created))
            LOGGER.info(
                "Snapshot %s agregado a la captura %s", instance_number, capture_id
            )
            return image
        except Exception:
            LOGGER.exception("Falló el snapshot en vivo para captura %s", capture_id)
            raise

    def finalize_dicom_images(self, capture_id: int) -> BatchDicomCreationOutcome:
        """Stop recording and create one coherent DICOM series for all snapshots."""
        capture = self.database.get_capture(capture_id)
        images = self.database.list_capture_images(capture_id)
        if not images:
            raise StudyWorkflowError(
                "Capture al menos un snapshot antes de finalizar el estudio."
            )
        if self.capture_manager.is_recording:
            capture = self.stop_recording(capture_id)

        study = self.database.get_study(capture.study_id)
        series_uid = new_series_instance_uid()
        updated_images: list[CaptureImageRecord] = []
        builds: list[DicomBuildResult] = []
        try:
            for image in images:
                snapshot = Path(image.snapshot_path)
                if not snapshot.is_file():
                    raise StudyWorkflowError(
                        f"No existe el snapshot {image.instance_number}: {snapshot}"
                    )
                destination = self.dicom_dir / (
                    f"{snapshot.stem}_{uuid4().hex[:8]}.dcm"
                )
                build = self.dicom_builder.create_vl_endoscopic_image(
                    snapshot_path=snapshot,
                    output_path=destination,
                    metadata=asdict(study),
                    instance_number=image.instance_number,
                    series_instance_uid=series_uid,
                )
                if build.study_instance_uid != study.study_instance_uid:
                    self.database.update_study_instance_uid(
                        study.id, build.study_instance_uid
                    )
                    study = self.database.get_study(study.id)
                updated = self.database.update_capture_image(
                    image.id,
                    dicom_image_path=str(build.output_path),
                    status=WorkflowStatus.DICOM_CREATED,
                )
                updated_images.append(updated)
                builds.append(build)
            capture = self.database.update_capture(
                capture_id,
                dicom_image_path=str(builds[-1].output_path),
                status=WorkflowStatus.DICOM_CREATED,
            )
            self.database.update_study_status(
                capture.study_id, WorkflowStatus.DICOM_CREATED
            )
            return BatchDicomCreationOutcome(
                capture, tuple(updated_images), tuple(builds)
            )
        except Exception:
            self._mark_failed(capture_id, capture.study_id, ended=True)
            LOGGER.exception(
                "Falló la creación del lote DICOM para captura %s", capture_id
            )
            raise

    def create_dicom_image(self, capture_id: int) -> DicomCreationOutcome:
        capture = self.database.get_capture(capture_id)
        if not capture.snapshot_path:
            raise StudyWorkflowError("Debe crear un snapshot antes de generar DICOM.")
        snapshot = Path(capture.snapshot_path)
        if not snapshot.is_file():
            raise StudyWorkflowError(f"No existe el snapshot registrado: {snapshot}")
        study = self.database.get_study(capture.study_id)
        destination = self.dicom_dir / f"{snapshot.stem}_{uuid4().hex[:8]}.dcm"
        try:
            result = self.dicom_builder.create_vl_endoscopic_image(
                snapshot_path=snapshot,
                output_path=destination,
                metadata=asdict(study),
            )
            if result.study_instance_uid != study.study_instance_uid:
                self.database.update_study_instance_uid(
                    study.id, result.study_instance_uid
                )
            updated = self.database.update_capture(
                capture_id,
                dicom_image_path=str(result.output_path),
                status=WorkflowStatus.DICOM_CREATED,
            )
            self.database.update_study_status(
                capture.study_id, WorkflowStatus.DICOM_CREATED
            )
            return DicomCreationOutcome(updated, result)
        except Exception:
            self._mark_failed(capture_id, capture.study_id)
            LOGGER.exception("Falló creación DICOM para captura %s", capture_id)
            raise

    def _mark_failed(self, capture_id: int, study_id: int, ended: bool = False) -> None:
        changes: dict[str, object] = {"status": WorkflowStatus.FAILED}
        if ended:
            changes["ended_at"] = local_timestamp()
        self.database.update_capture(capture_id, **changes)
        self.database.update_study_status(study_id, WorkflowStatus.FAILED)
