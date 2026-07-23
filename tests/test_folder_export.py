from pathlib import Path

from PIL import Image
from pydicom import dcmread

from app.config import DicomEndpointConfig, InstitutionConfig
from app.db.database import Database
from app.db.models import WorkflowStatus
from app.dicom.dicom_builder import DicomBuilder
from app.services.export_service import ExportService


class UnusedStoreClient:
    endpoint = DicomEndpointConfig("ORTHANC", "127.0.0.1", 4242)


def test_folder_export_copies_a_complete_dicom_study(tmp_path: Path) -> None:
    database = Database(tmp_path / "export.sqlite3")
    database.initialize()
    study = database.create_study(
        {
            "patient_name": "PEREZ^ANA",
            "patient_id": "PID 10",
            "accession_number": "ACC/20",
            "study_instance_uid": "1.2.826.0.1.3680043.8.498.500",
        }
    )
    capture = database.create_capture(study.id, tmp_path / "video.mp4")
    source = tmp_path / "source.jpg"
    Image.new("RGB", (12, 12), color="teal").save(source)
    builder = DicomBuilder(
        InstitutionConfig("Test", "ELECTROCAP", "Custom", "ElectroCap", "1.0")
    )
    series_uid = "1.2.826.0.1.3680043.8.498.501"
    for instance_number in (1, 2):
        dicom_path = tmp_path / f"source-{instance_number}.dcm"
        builder.create_vl_endoscopic_image(
            snapshot_path=source,
            output_path=dicom_path,
            metadata={
                "patient_name": study.patient_name,
                "patient_id": study.patient_id,
                "accession_number": study.accession_number,
                "study_instance_uid": study.study_instance_uid,
            },
            instance_number=instance_number,
            series_instance_uid=series_uid,
        )
        image = database.create_capture_image(
            capture_id=capture.id,
            snapshot_path=source,
            instance_number=instance_number,
        )
        database.update_capture_image(
            image.id,
            dicom_image_path=str(dicom_path),
            status=WorkflowStatus.DICOM_CREATED,
        )

    destination = tmp_path / "pendrive"
    destination.mkdir()
    outcome = ExportService(
        database, UnusedStoreClient()  # type: ignore[arg-type]
    ).export_capture_images(capture.id, destination)

    assert outcome.directory.parent == destination
    assert outcome.directory.name.startswith("ElectroCap_PID_10_ACC_20_")
    assert [path.name for path in outcome.files] == ["IM_0001.dcm", "IM_0002.dcm"]
    assert all(path.is_file() for path in outcome.files)
    assert {
        str(dcmread(path, stop_before_pixels=True).SeriesInstanceUID)
        for path in outcome.files
    } == {series_uid}
    assert database.list_capture_images(capture.id)[0].status == "DICOM_CREATED"
