from pathlib import Path
from threading import Lock

from PIL import Image
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from pynetdicom import AE, evt
from pynetdicom.sop_class import ModalityWorklistInformationFind, Verification
import pytest

from app.config import DicomEndpointConfig, InstitutionConfig
from app.dicom.dicom_builder import DicomBuilder, VL_ENDOSCOPIC_IMAGE_STORAGE_UID
from app.dicom.store_client import StoreClient
from app.dicom.worklist_client import WorklistClient, WorklistQuery


def test_c_echo_c_store_and_mwl_c_find_roundtrip(tmp_path: Path) -> None:
    stored: list[Dataset] = []
    received_queries: list[Dataset] = []
    lock = Lock()

    def handle_echo(_event: object) -> int:
        return 0x0000

    def handle_store(event: object) -> int:
        with lock:
            stored.append(event.dataset)
        return 0x0000

    def handle_find(event: object):
        with lock:
            received_queries.append(event.identifier)
        response = Dataset()
        response.PatientName = "NETWORK^TEST"
        response.PatientID = "NET-001"
        response.PatientBirthDate = "19850203"
        response.PatientSex = "F"
        response.AccessionNumber = "NET-ACC-1"
        response.StudyInstanceUID = "1.2.826.0.1.3680043.8.498.777"
        response.RequestedProcedureID = "NET-RP"
        response.RequestedProcedureDescription = "COLPOSCOPIA"
        response.ReferringPhysicianName = "DOCTOR^TEST"
        step = Dataset()
        step.ScheduledStationAETitle = "COLPOCAP_MVP"
        step.ScheduledProcedureStepStartDate = "20260714"
        step.ScheduledProcedureStepStartTime = "120000"
        step.Modality = "ES"
        step.ScheduledPerformingPhysicianName = "DOCTOR^TEST"
        step.ScheduledProcedureStepDescription = "COLPOSCOPIA"
        step.ScheduledProcedureStepID = "SPS-NET-1"
        response.ScheduledProcedureStepSequence = Sequence([step])
        yield 0xFF00, response
        yield 0x0000, None

    ae = AE(ae_title="ORTHANC")
    ae.add_supported_context(Verification)
    ae.add_supported_context(VL_ENDOSCOPIC_IMAGE_STORAGE_UID)
    ae.add_supported_context(ModalityWorklistInformationFind)
    try:
        server = ae.start_server(
            ("127.0.0.1", 0),
            block=False,
            evt_handlers=[
                (evt.EVT_C_ECHO, handle_echo),
                (evt.EVT_C_STORE, handle_store),
                (evt.EVT_C_FIND, handle_find),
            ],
        )
    except PermissionError:
        pytest.skip("El sandbox no permite abrir un listener DICOM local")
    port = int(server.server_address[1])
    endpoint = DicomEndpointConfig("ORTHANC", "127.0.0.1", port)
    try:
        source = tmp_path / "network.png"
        Image.new("RGB", (10, 10), color="green").save(source)
        dicom_path = tmp_path / "network.dcm"
        DicomBuilder(
            InstitutionConfig("Test", "COLPO", "Custom", "ECAP", "1.0.0")
        ).create_vl_endoscopic_image(
            snapshot_path=source,
            output_path=dicom_path,
            metadata={
                "patient_name": "NETWORK^TEST",
                "patient_id": "NET-001",
                "accession_number": "NET-ACC-1",
                "study_instance_uid": "1.2.826.0.1.3680043.8.498.777",
                "scheduled_start_date": "20260714",
                "scheduled_start_time": "120000",
            },
        )

        store_client = StoreClient("COLPOCAP_MVP", endpoint)
        assert store_client.echo().success
        store_result = store_client.store(dicom_path)
        assert store_result.success
        assert store_result.status_hex == "0x0000"

        worklist_client = WorklistClient("COLPOCAP_MVP", endpoint)
        results = worklist_client.find(
            WorklistQuery(
                scheduled_date="20260714",
                patient_name="NETWORK",
                patient_id="NET-001",
                accession_number="NET-ACC-1",
            )
        )
        assert len(results) == 1
        assert results[0].patient_id == "NET-001"
        assert results[0].scheduled_procedure_step_id == "SPS-NET-1"
        assert stored[0].PatientID == "NET-001"
        query = received_queries[0]
        assert str(query.PatientName) == "*NETWORK*"
        assert query.ScheduledProcedureStepSequence[0].ScheduledProcedureStepStartDate == "20260714"
    finally:
        server.shutdown()
