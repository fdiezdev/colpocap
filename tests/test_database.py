from pathlib import Path

from app.db.database import Database
from app.db.models import WorkflowStatus


def study_values() -> dict[str, str]:
    return {
        "patient_name": "TEST^PACIENTE",
        "patient_id": "PID-001",
        "patient_birth_date": "19800101",
        "patient_sex": "F",
        "accession_number": "ACC-001",
        "study_instance_uid": "1.2.826.0.1.3680043.8.498.1",
        "requested_procedure_id": "RP-1",
        "requested_procedure_description": "Colposcopía",
        "referring_physician_name": "MEDICO^REFERENTE",
        "scheduled_station_ae_title": "COLPOCAP_MVP",
        "modality": "ES",
        "scheduled_performing_physician_name": "MEDICO^OPERADOR",
        "scheduled_procedure_step_description": "Colposcopía programada",
        "scheduled_procedure_step_id": "SPS-1",
        "scheduled_start_date": "20260714",
        "scheduled_start_time": "100000",
    }


def test_database_tracks_capture_and_each_export_attempt(tmp_path: Path) -> None:
    database = Database(tmp_path / "local.sqlite3")
    database.initialize()
    study = database.create_study(study_values())
    assert study.status == WorkflowStatus.SELECTED

    capture = database.create_capture(study.id, tmp_path / "video.mp4")
    capture = database.update_capture(
        capture.id,
        ended_at="2026-07-14T10:05:00-03:00",
        snapshot_path=str(tmp_path / "snapshot.jpg"),
        dicom_image_path=str(tmp_path / "snapshot.dcm"),
        status=WorkflowStatus.DICOM_CREATED,
    )
    assert capture.status == WorkflowStatus.DICOM_CREATED
    assert len(database.list_pending_captures()) == 1

    first = database.create_export(
        capture_id=capture.id,
        sop_instance_uid="1.2.3.4.1",
        sop_class_uid="1.2.840.10008.5.1.4.1.1.77.1.1",
        destination_ae="ORTHANC",
        destination_host="127.0.0.1",
        destination_port=4242,
    )
    database.complete_export(
        first.id,
        status=WorkflowStatus.FAILED,
        response_status="0xA700",
        error_message="Out of resources",
    )
    assert database.list_pending_captures()[0]["export_status"] == "FAILED"

    second = database.create_export(
        capture_id=capture.id,
        sop_instance_uid="1.2.3.4.1",
        sop_class_uid="1.2.840.10008.5.1.4.1.1.77.1.1",
        destination_ae="ORTHANC",
        destination_host="127.0.0.1",
        destination_port=4242,
    )
    database.complete_export(
        second.id,
        status=WorkflowStatus.SENT,
        response_status="0x0000",
        error_message=None,
    )
    database.update_capture(capture.id, status=WorkflowStatus.SENT)

    assert database.table_count("studies") == 1
    assert database.table_count("captures") == 1
    assert database.table_count("dicom_exports") == 2
    assert database.list_pending_captures() == []


def test_foreign_keys_reject_unknown_study(tmp_path: Path) -> None:
    database = Database(tmp_path / "local.sqlite3")
    database.initialize()
    try:
        database.create_capture(999, tmp_path / "video.mp4")
    except Exception as exc:
        assert "FOREIGN KEY" in str(exc).upper()
    else:
        raise AssertionError("SQLite debía rechazar un study_id inexistente")
