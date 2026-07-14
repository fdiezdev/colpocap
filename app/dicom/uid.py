"""DICOM UID generation helpers."""

from __future__ import annotations

from pydicom.uid import UID, generate_uid


def new_uid() -> str:
    """Return a standards-compliant, globally unique DICOM UID."""
    return str(generate_uid())


def new_study_instance_uid() -> str:
    return new_uid()


def new_series_instance_uid() -> str:
    return new_uid()


def new_sop_instance_uid() -> str:
    return new_uid()


def is_valid_uid(value: str) -> bool:
    """Validate syntax without treating an empty string as a UID."""
    return bool(value) and UID(value).is_valid

