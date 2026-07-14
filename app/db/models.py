"""Typed records shared by persistence and services."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from sqlite3 import Row
from typing import Any, Mapping


class WorkflowStatus(StrEnum):
    SELECTED = "SELECTED"
    RECORDING = "RECORDING"
    RECORDED = "RECORDED"
    SNAPSHOT_CREATED = "SNAPSHOT_CREATED"
    DICOM_CREATED = "DICOM_CREATED"
    SENT = "SENT"
    FAILED = "FAILED"


@dataclass(frozen=True)
class StudyRecord:
    id: int
    patient_name: str
    patient_id: str
    patient_birth_date: str
    patient_sex: str
    accession_number: str
    study_instance_uid: str
    requested_procedure_id: str
    requested_procedure_description: str
    referring_physician_name: str
    scheduled_station_ae_title: str
    modality: str
    scheduled_performing_physician_name: str
    scheduled_procedure_step_description: str
    scheduled_procedure_step_id: str
    scheduled_start_date: str
    scheduled_start_time: str
    selected_at: str
    status: str

    @classmethod
    def from_row(cls, row: Row | Mapping[str, Any]) -> "StudyRecord":
        return cls(**{field: row[field] for field in cls.__dataclass_fields__})


@dataclass(frozen=True)
class CaptureRecord:
    id: int
    study_id: int
    video_path: str | None
    snapshot_path: str | None
    dicom_image_path: str | None
    dicom_video_path: str | None
    started_at: str | None
    ended_at: str | None
    status: str

    @classmethod
    def from_row(cls, row: Row | Mapping[str, Any]) -> "CaptureRecord":
        return cls(**{field: row[field] for field in cls.__dataclass_fields__})


@dataclass(frozen=True)
class ExportRecord:
    id: int
    capture_id: int
    sop_instance_uid: str
    sop_class_uid: str
    destination_ae: str
    destination_host: str
    destination_port: int
    status: str
    response_status: str | None
    attempted_at: str
    error_message: str | None

    @classmethod
    def from_row(cls, row: Row | Mapping[str, Any]) -> "ExportRecord":
        return cls(**{field: row[field] for field in cls.__dataclass_fields__})
