from pathlib import Path

from PIL import Image

from app.config import DicomEndpointConfig, InstitutionConfig
from app.db.database import Database
from app.db.models import WorkflowStatus
from app.dicom.dicom_builder import DicomBuilder
from app.dicom.store_client import EchoResult, StoreResult
from app.services.export_service import ExportService


class FakeBatchStoreClient:
    def __init__(self) -> None:
        self.endpoint = DicomEndpointConfig("ORTHANC", "127.0.0.1", 4242)
        self.batches: list[tuple[Path, ...]] = []

    @staticmethod
    def echo() -> EchoResult:
        return EchoResult(True, 0x0000, "C-ECHO PACS respondió 0x0000")

    def store_many(self, paths) -> tuple[StoreResult, ...]:
        batch = tuple(Path(path) for path in paths)
        self.batches.append(batch)
        return tuple(
            StoreResult(0x0000, "0x0000", True, False, "C-STORE exitoso")
            for _ in batch
        )


def test_export_service_sends_capture_images_as_one_batch(tmp_path: Path) -> None:
    database = Database(tmp_path / "batch.sqlite3")
    database.initialize()
    study = database.create_study(
        {
            "patient_name": "LOTE^PACIENTE",
            "patient_id": "PID-BATCH",
            "accession_number": "ACC-BATCH",
            "study_instance_uid": "1.2.826.0.1.3680043.8.498.400",
        }
    )
    capture = database.create_capture(study.id, tmp_path / "video.mp4")
    builder = DicomBuilder(
        InstitutionConfig("Test", "COLPO", "Custom", "MVP", "0.1")
    )
    series_uid = "1.2.826.0.1.3680043.8.498.401"
    for number, color in ((1, "red"), (2, "blue")):
        snapshot = tmp_path / f"snapshot-{number}.jpg"
        Image.new("RGB", (10, 10), color=color).save(snapshot)
        dicom = tmp_path / f"snapshot-{number}.dcm"
        builder.create_vl_endoscopic_image(
            snapshot_path=snapshot,
            output_path=dicom,
            metadata={
                "patient_name": study.patient_name,
                "patient_id": study.patient_id,
                "accession_number": study.accession_number,
                "study_instance_uid": study.study_instance_uid,
            },
            instance_number=number,
            series_instance_uid=series_uid,
        )
        image = database.create_capture_image(
            capture_id=capture.id,
            snapshot_path=snapshot,
            instance_number=number,
        )
        database.update_capture_image(
            image.id,
            dicom_image_path=str(dicom),
            status=WorkflowStatus.DICOM_CREATED,
        )

    store_client = FakeBatchStoreClient()
    outcome = ExportService(database, store_client).send_capture_images(capture.id)

    assert outcome.success
    assert outcome.sent_count == 2
    assert outcome.total_count == 2
    assert len(store_client.batches) == 1
    assert len(store_client.batches[0]) == 2
    assert all(
        image.status == WorkflowStatus.SENT
        for image in database.list_capture_images(capture.id)
    )
    assert database.table_count("dicom_exports") == 2
    assert database.list_pending_captures() == []

