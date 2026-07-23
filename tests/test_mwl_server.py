from datetime import date
import json
from pathlib import Path

from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
import pytest

from app.config import DicomEndpointConfig
from app.dicom.mwl_server import (
    JsonWorklistRepository,
    MwlServer,
    WorklistDataError,
    dataset_matches_query,
)
from app.dicom.worklist_client import WorklistClient, WorklistQuery


def write_worklists(path: Path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "patient_name": "TEST^ANA",
                    "patient_id": "PID-001",
                    "patient_birth_date": "19850312",
                    "patient_sex": "F",
                    "accession_number": "ACC-001",
                    "study_instance_uid": "1.2.826.0.1.3680043.8.498.1001",
                    "requested_procedure_id": "RP-001",
                    "requested_procedure_description": "COLPOSCOPIA",
                    "referring_physician_name": "DOCTOR^TEST",
                    "scheduled_station_ae_title": "ELECTROCAP",
                    "scheduled_start_date": "TODAY",
                    "scheduled_start_time": "090000",
                    "modality": "ES",
                    "scheduled_performing_physician_name": "DOCTOR^TEST",
                    "scheduled_procedure_step_description": "COLPOSCOPIA",
                    "scheduled_procedure_step_id": "SPS-001",
                },
                {
                    "patient_name": "TEST^BEA",
                    "patient_id": "PID-002",
                    "accession_number": "ACC-002",
                    "scheduled_station_ae_title": "ELECTROCAP",
                    "scheduled_start_date": "20260115",
                    "scheduled_start_time": "100000",
                    "modality": "ES",
                    "scheduled_procedure_step_id": "SPS-002",
                },
            ]
        ),
        encoding="utf-8",
    )


def test_repository_expands_today_and_validates_entries(tmp_path: Path) -> None:
    path = tmp_path / "mwl.json"
    write_worklists(path)

    entries = JsonWorklistRepository(path).load()

    assert len(entries) == 2
    assert entries[0].PatientID == "PID-001"
    assert (
        entries[0].ScheduledProcedureStepSequence[0].ScheduledProcedureStepStartDate
        == date.today().strftime("%Y%m%d")
    )

    path.write_text("{}", encoding="utf-8")
    with pytest.raises(WorklistDataError, match="lista JSON"):
        JsonWorklistRepository(path).load()


def test_matching_supports_wildcards_and_date_ranges(tmp_path: Path) -> None:
    path = tmp_path / "mwl.json"
    write_worklists(path)
    candidate = JsonWorklistRepository(path).load()[0]

    query = Dataset()
    query.PatientName = "*ANA*"
    query.PatientID = "PID-*"
    step = Dataset()
    today = date.today().strftime("%Y%m%d")
    step.ScheduledProcedureStepStartDate = f"{today}-{today}"
    step.Modality = "ES"
    query.ScheduledProcedureStepSequence = Sequence([step])

    assert dataset_matches_query(candidate, query)
    query.PatientID = "OTHER-*"
    assert not dataset_matches_query(candidate, query)


def test_server_answers_real_echo_and_mwl_find(tmp_path: Path) -> None:
    path = tmp_path / "mwl.json"
    write_worklists(path)
    server = MwlServer(JsonWorklistRepository(path), port=0)
    try:
        try:
            server.start()
        except PermissionError:
            pytest.skip("El sandbox no permite abrir un listener DICOM local")

        endpoint = DicomEndpointConfig("ELECTROCAP_WL", "127.0.0.1", server.bound_port)
        client = WorklistClient("ELECTROCAP", endpoint)

        assert client.echo().success
        results = client.find(
            WorklistQuery(
                scheduled_date=date.today().strftime("%Y%m%d"),
                patient_name="ANA",
                patient_id="PID-001",
                accession_number="ACC-001",
            )
        )

        assert len(results) == 1
        assert results[0].patient_id == "PID-001"
        assert results[0].scheduled_procedure_step_id == "SPS-001"
    finally:
        server.shutdown()
