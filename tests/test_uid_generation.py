from pydicom.uid import UID

from app.dicom.uid import (
    new_series_instance_uid,
    new_sop_instance_uid,
    new_study_instance_uid,
)


def test_generated_uids_are_valid_and_unique() -> None:
    values = {
        new_study_instance_uid(),
        new_series_instance_uid(),
        new_sop_instance_uid(),
        new_sop_instance_uid(),
    }
    assert len(values) == 4
    assert all(UID(value).is_valid for value in values)
    assert all(len(value) <= 64 for value in values)

