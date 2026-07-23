from io import BytesIO
from pathlib import Path

from PIL import Image

from app.config import InstitutionConfig
from app.db.database import Database
from app.dicom.dicom_builder import DicomBuilder
from app.services.study_service import StudyService
from app.video.snapshot_manager import SnapshotManager


class ActiveCaptureManager:
    def __init__(self, videos_dir: Path) -> None:
        self.videos_dir = videos_dir
        self.is_recording = True


def _jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (32, 18), (70, 100, 145)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _service(
    database: Database,
    manager: ActiveCaptureManager,
    snapshots_dir: Path,
    dicom_dir: Path,
) -> StudyService:
    return StudyService(
        database,
        manager,  # type: ignore[arg-type]
        SnapshotManager(),
        DicomBuilder(
            InstitutionConfig("Test", "ECAP", "Custom", "ECAP", "1.0")
        ),
        snapshots_dir,
        dicom_dir,
    )


def _study_values() -> dict[str, str]:
    return {
        "patient_name": "TEST^SNAPSHOT",
        "patient_id": "PID-SNAPSHOT",
        "accession_number": "ACC-SNAPSHOT",
        "study_instance_uid": "1.2.826.0.1.3680043.8.498.9101",
    }


def test_delete_snapshot_removes_file_and_refreshes_capture_reference(
    tmp_path: Path,
) -> None:
    videos_dir = tmp_path / "output" / "videos"
    snapshots_dir = tmp_path / "output" / "snapshots"
    dicom_dir = tmp_path / "output" / "dicom"
    for directory in (videos_dir, snapshots_dir, dicom_dir):
        directory.mkdir(parents=True)

    database = Database(tmp_path / "output" / "ecap.sqlite3")
    database.initialize()
    study = database.create_study(_study_values())
    capture = database.create_capture(study.id, videos_dir / "active.mp4")
    first_path = snapshots_dir / "first.jpg"
    second_path = snapshots_dir / "second.jpg"
    first_path.write_bytes(_jpeg_bytes())
    second_path.write_bytes(_jpeg_bytes())
    first = database.create_capture_image(
        capture_id=capture.id,
        snapshot_path=first_path,
        instance_number=1,
    )
    second = database.create_capture_image(
        capture_id=capture.id,
        snapshot_path=second_path,
        instance_number=2,
    )
    database.update_capture(capture.id, snapshot_path=str(second_path))
    service = _service(
        database,
        ActiveCaptureManager(videos_dir),
        snapshots_dir,
        dicom_dir,
    )

    outcome = service.delete_snapshot(capture.id, second.id)

    assert outcome.image.id == second.id
    assert outcome.deleted_files == (second_path,)
    assert not second_path.exists()
    assert first_path.exists()
    assert [item.id for item in database.list_capture_images(capture.id)] == [first.id]
    assert database.get_capture(capture.id).snapshot_path == str(first_path)


def test_snapshot_number_does_not_collide_after_deleting_a_middle_image(
    tmp_path: Path,
) -> None:
    videos_dir = tmp_path / "output" / "videos"
    snapshots_dir = tmp_path / "output" / "snapshots"
    dicom_dir = tmp_path / "output" / "dicom"
    for directory in (videos_dir, snapshots_dir, dicom_dir):
        directory.mkdir(parents=True)

    database = Database(tmp_path / "output" / "ecap.sqlite3")
    database.initialize()
    study = database.create_study(_study_values())
    capture = database.create_capture(study.id, videos_dir / "active.mp4")
    manager = ActiveCaptureManager(videos_dir)
    service = _service(database, manager, snapshots_dir, dicom_dir)

    created = [
        service.create_live_snapshot(capture.id, _jpeg_bytes())
        for _ in range(3)
    ]
    service.delete_snapshot(capture.id, created[1].id)

    replacement = service.create_live_snapshot(capture.id, _jpeg_bytes())

    assert replacement.instance_number == 4
    assert [
        image.instance_number
        for image in database.list_capture_images(capture.id)
    ] == [1, 3, 4]
