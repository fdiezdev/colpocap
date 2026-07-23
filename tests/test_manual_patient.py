from datetime import datetime, timezone

import pytest

from app.ui.manual_patient_dialog import build_manual_worklist_item


def test_manual_patient_is_normalized_as_a_worklist_item() -> None:
    item = build_manual_worklist_item(
        patient_name="PEREZ^ANA",
        patient_id="PID-MANUAL",
        patient_birth_date="19850312",
        patient_sex="F",
        procedure_description="Colposcopía de control",
        now=datetime(2026, 7, 23, 14, 5, 6, tzinfo=timezone.utc),
    )

    assert item.source == "manual"
    assert item.patient_name == "PEREZ^ANA"
    assert item.patient_id == "PID-MANUAL"
    assert item.accession_number == "MAN-260723140506"
    assert item.scheduled_start_date == "20260723"
    assert item.scheduled_start_time == "140506"
    assert item.modality == "ES"


@pytest.mark.parametrize(
    ("patient_name", "patient_id", "message"),
    [
        ("", "PID-1", "nombre"),
        ("PEREZ^ANA", "", "Patient ID"),
    ],
)
def test_manual_patient_requires_identity(
    patient_name: str, patient_id: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_manual_worklist_item(
            patient_name=patient_name,
            patient_id=patient_id,
        )
