from pathlib import Path

import pytest

from app.config import InstitutionConfig
from app.db.database import Database
from app.db.models import WorkflowStatus
from app.dicom.dicom_builder import DicomBuilder
from app.services.study_service import StudyService, StudyWorkflowError
from app.video.snapshot_manager import SnapshotManager


class FakeCaptureManager:
    def __init__(self, videos_dir: Path, active_output: Path) -> None:
        self.videos_dir = videos_dir
        self.active_output = active_output
        self.is_recording = True
        self.cancel_called = False

    def cancel(self) -> Path:
        self.cancel_called = True
        self.is_recording = False
        return self.active_output


def _study_values() -> dict[str, str]:
    return {
        "patient_name": "TEST^CANCELAR",
        "patient_id": "PID-CANCEL",
        "accession_number": "ACC-CANCEL",
        "study_instance_uid": "1.2.826.0.1.3680043.8.498.9001",
    }


def _service(
    database: Database,
    capture_manager: FakeCaptureManager,
    snapshots_dir: Path,
    dicom_dir: Path,
) -> StudyService:
    return StudyService(
        database,
        capture_manager,  # type: ignore[arg-type]
        SnapshotManager(),
        DicomBuilder(
            InstitutionConfig("Test", "ECAP", "Custom", "ECAP", "1.0")
        ),
        snapshots_dir,
        dicom_dir,
    )


def test_cancel_study_removes_files_and_database_session(tmp_path: Path) -> None:
    videos_dir = tmp_path / "output" / "videos"
    snapshots_dir = tmp_path / "output" / "snapshots"
    dicom_dir = tmp_path / "output" / "dicom"
    for directory in (videos_dir, snapshots_dir, dicom_dir):
        directory.mkdir(parents=True)

    video = videos_dir / "active.mp4"
    log = videos_dir / "active.ffmpeg.log"
    snapshot = snapshots_dir / "snapshot.jpg"
    dicom = dicom_dir / "snapshot.dcm"
    for path in (video, log, snapshot, dicom):
        path.write_bytes(b"temporary study data")

    database = Database(tmp_path / "output" / "ecap.sqlite3")
    database.initialize()
    study = database.create_study(_study_values())
    capture = database.create_capture(study.id, video)
    capture = database.update_capture(
        capture.id,
        snapshot_path=str(snapshot),
        dicom_image_path=str(dicom),
    )
    image = database.create_capture_image(
        capture_id=capture.id,
        snapshot_path=snapshot,
        instance_number=1,
    )
    database.update_capture_image(
        image.id,
        dicom_image_path=str(dicom),
        status=WorkflowStatus.DICOM_CREATED,
    )
    database.create_export(
        capture_id=capture.id,
        image_id=image.id,
        sop_instance_uid="1.2.3.4",
        sop_class_uid="1.2.840.10008.5.1.4.1.1.77.1.1",
        destination_ae="ORTHANC",
        destination_host="127.0.0.1",
        destination_port=4242,
    )
    manager = FakeCaptureManager(videos_dir, video)
    service = _service(database, manager, snapshots_dir, dicom_dir)
    service.selected_study_id = study.id

    outcome = service.cancel_study(capture.id)

    assert manager.cancel_called
    assert outcome.capture_id == capture.id
    assert outcome.study_id == study.id
    assert set(outcome.deleted_files) == {video, log, snapshot, dicom}
    assert not any(path.exists() for path in (video, log, snapshot, dicom))
    assert database.table_count("dicom_exports") == 0
    assert database.table_count("capture_images") == 0
    assert database.table_count("captures") == 0
    assert database.table_count("studies") == 0
    assert service.selected_study_id is None


def test_cancel_study_rejects_files_outside_ecap_storage(tmp_path: Path) -> None:
    videos_dir = tmp_path / "output" / "videos"
    snapshots_dir = tmp_path / "output" / "snapshots"
    dicom_dir = tmp_path / "output" / "dicom"
    for directory in (videos_dir, snapshots_dir, dicom_dir):
        directory.mkdir(parents=True)
    outside = tmp_path / "do-not-delete.mp4"
    outside.write_bytes(b"keep")

    database = Database(tmp_path / "output" / "ecap.sqlite3")
    database.initialize()
    study = database.create_study(_study_values())
    capture = database.create_capture(study.id, outside)
    manager = FakeCaptureManager(videos_dir, outside)
    service = _service(database, manager, snapshots_dir, dicom_dir)

    with pytest.raises(StudyWorkflowError, match="ruta ajena"):
        service.cancel_study(capture.id)

    assert outside.exists()
    assert database.table_count("captures") == 1
    assert database.table_count("studies") == 1
