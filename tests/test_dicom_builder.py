from datetime import datetime, timezone
from pathlib import Path

from PIL import Image
from pydicom import dcmread
from pydicom.uid import ExplicitVRLittleEndian

from app.config import InstitutionConfig
from app.dicom.dicom_builder import (
    DicomBuilder,
    VL_ENDOSCOPIC_IMAGE_STORAGE_UID,
)


def metadata() -> dict[str, str]:
    return {
        "patient_name": "PÉREZ^ANA",
        "patient_id": "PID-123",
        "patient_birth_date": "19900102",
        "patient_sex": "F",
        "accession_number": "ACC-2026-001",
        "study_instance_uid": "1.2.826.0.1.3680043.8.498.100",
        "requested_procedure_id": "RP-42",
        "requested_procedure_description": "COLPOSCOPIA DIAGNÓSTICA",
        "scheduled_procedure_step_description": "COLPOSCOPIA PROGRAMADA",
        "scheduled_procedure_step_id": "SPS-42",
        "referring_physician_name": "MÉDICO^PRUEBA",
        "scheduled_start_date": "20260714",
        "scheduled_start_time": "103000",
    }


def institution() -> InstitutionConfig:
    return InstitutionConfig(
        name="Instituto de Prueba",
        station_name="COLPOSCOPY_CAPTURE_01",
        manufacturer="Custom",
        manufacturer_model_name="ECAP",
        software_version="0.1.0",
    )


def test_builder_creates_valid_uncompressed_rgb_vl_image(tmp_path: Path) -> None:
    source = tmp_path / "snapshot.jpg"
    Image.new("RGB", (32, 24), color=(10, 120, 230)).save(source, quality=95)
    destination = tmp_path / "snapshot.dcm"

    result = DicomBuilder(institution()).create_vl_endoscopic_image(
        snapshot_path=source,
        output_path=destination,
        metadata=metadata(),
        now=datetime(2026, 7, 14, 11, 0, 1, tzinfo=timezone.utc),
    )
    dataset = dcmread(destination)

    assert result.output_path == destination
    assert dataset.SOPClassUID == VL_ENDOSCOPIC_IMAGE_STORAGE_UID
    assert dataset.PatientName == "PÉREZ^ANA"
    assert dataset.PatientID == "PID-123"
    assert dataset.AccessionNumber == "ACC-2026-001"
    assert dataset.StudyInstanceUID == metadata()["study_instance_uid"]
    assert dataset.Modality == "ES"
    assert dataset.BodyPartExamined == "CERVIX"
    assert dataset.SeriesDescription == "COLPOSCOPIA - IMAGEN FIJA"
    assert dataset.StudyID == ""
    assert dataset.RequestAttributesSequence[0].RequestedProcedureID == "RP-42"
    assert dataset.RequestAttributesSequence[0].ScheduledProcedureStepID == "SPS-42"
    assert (
        dataset.RequestAttributesSequence[0].ScheduledProcedureStepDescription
        == "COLPOSCOPIA PROGRAMADA"
    )
    assert dataset.PhotometricInterpretation == "RGB"
    assert dataset.SamplesPerPixel == 3
    assert dataset.PlanarConfiguration == 0
    assert dataset.BitsAllocated == 8
    assert dataset.Rows == 24
    assert dataset.Columns == 32
    assert len(dataset.PixelData) == 24 * 32 * 3
    assert dataset.file_meta.TransferSyntaxUID == ExplicitVRLittleEndian
    assert dataset.LossyImageCompression == "01"
    assert dataset.LossyImageCompressionMethod == "ISO_10918_1"
    assert any("StationName" in warning for warning in result.warnings)


def test_builder_generates_new_study_and_sop_uids_when_needed(tmp_path: Path) -> None:
    source = tmp_path / "snapshot.png"
    Image.new("RGB", (8, 8), color="red").save(source)
    incomplete = metadata()
    incomplete["study_instance_uid"] = ""

    builder = DicomBuilder(institution())
    first = builder.create_vl_endoscopic_image(
        snapshot_path=source,
        output_path=tmp_path / "first.dcm",
        metadata=incomplete,
    )
    second = builder.create_vl_endoscopic_image(
        snapshot_path=source,
        output_path=tmp_path / "second.dcm",
        metadata=incomplete,
    )

    assert first.study_instance_uid
    assert first.study_instance_uid != second.study_instance_uid
    assert first.series_instance_uid != second.series_instance_uid
    assert first.sop_instance_uid != second.sop_instance_uid
    assert any("StudyInstanceUID ausente" in warning for warning in first.warnings)


def test_builder_pads_odd_length_rgb_pixel_data(tmp_path: Path) -> None:
    source = tmp_path / "odd.png"
    Image.new("RGB", (7, 7), color="blue").save(source)
    destination = tmp_path / "odd.dcm"

    DicomBuilder(institution()).create_vl_endoscopic_image(
        snapshot_path=source,
        output_path=destination,
        metadata=metadata(),
    )
    dataset = dcmread(destination)

    assert dataset.Rows == 7
    assert dataset.Columns == 7
    assert len(dataset.PixelData) == 148  # 7 * 7 * 3 plus one DICOM padding byte
    assert dataset.PixelData[-1] == 0
    assert dataset.LossyImageCompression == "00"


def test_builder_reuses_series_uid_and_numbers_batch_instances(tmp_path: Path) -> None:
    source = tmp_path / "batch.png"
    Image.new("RGB", (12, 10), color="purple").save(source)
    builder = DicomBuilder(institution())
    series_uid = "1.2.826.0.1.3680043.8.498.200"

    first = builder.create_vl_endoscopic_image(
        snapshot_path=source,
        output_path=tmp_path / "batch-1.dcm",
        metadata=metadata(),
        instance_number=1,
        series_instance_uid=series_uid,
    )
    second = builder.create_vl_endoscopic_image(
        snapshot_path=source,
        output_path=tmp_path / "batch-2.dcm",
        metadata=metadata(),
        instance_number=2,
        series_instance_uid=series_uid,
    )

    first_dataset = dcmread(first.output_path, stop_before_pixels=True)
    second_dataset = dcmread(second.output_path, stop_before_pixels=True)
    assert first_dataset.SeriesInstanceUID == series_uid
    assert second_dataset.SeriesInstanceUID == series_uid
    assert first_dataset.InstanceNumber == 1
    assert second_dataset.InstanceNumber == 2
    assert first_dataset.SOPInstanceUID != second_dataset.SOPInstanceUID


def test_video_dicom_is_explicitly_not_implemented() -> None:
    builder = DicomBuilder(institution())
    try:
        builder.create_video_endoscopic()
    except NotImplementedError as exc:
        assert "no forma parte de esta versión" in str(exc)
    else:
        raise AssertionError("La encapsulación de video no debe simularse")
