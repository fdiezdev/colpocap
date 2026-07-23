"""DICOM Modality Worklist C-FIND client."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from typing import Any

from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from pynetdicom import AE
from pynetdicom.sop_class import ModalityWorklistInformationFind, Verification

from app.config import (
    DEVELOPMENT_WORKLIST_AE_TITLE,
    DEVELOPMENT_WORKLIST_PORT,
    DicomEndpointConfig,
    LOOPBACK_HOSTS,
)
from .store_client import EchoResult

LOGGER = logging.getLogger(__name__)


class WorklistError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorklistQuery:
    scheduled_date: str = ""
    patient_name: str = ""
    patient_id: str = ""
    accession_number: str = ""


@dataclass(frozen=True)
class WorklistItem:
    patient_name: str = ""
    patient_id: str = ""
    patient_birth_date: str = ""
    patient_sex: str = ""
    accession_number: str = ""
    study_instance_uid: str = ""
    requested_procedure_id: str = ""
    requested_procedure_description: str = ""
    referring_physician_name: str = ""
    scheduled_station_ae_title: str = ""
    scheduled_start_date: str = ""
    scheduled_start_time: str = ""
    modality: str = ""
    scheduled_performing_physician_name: str = ""
    scheduled_procedure_step_description: str = ""
    scheduled_procedure_step_id: str = ""
    source: str = "worklist"

    def to_mapping(self) -> dict[str, str]:
        return asdict(self)


class WorklistClient:
    def __init__(self, local_ae_title: str, endpoint: DicomEndpointConfig) -> None:
        self.local_ae_title = local_ae_title
        self.endpoint = endpoint

    @staticmethod
    def _configure_timeouts(ae: AE) -> None:
        ae.acse_timeout = 10
        ae.dimse_timeout = 30
        ae.network_timeout = 10

    def _association_error(self) -> str:
        message = (
            f"No se pudo conectar con Worklist {self.endpoint.ae_title} "
            f"en {self.endpoint.host}:{self.endpoint.port}. "
            "Verifique que el servicio esté iniciado y que el host y el puerto coincidan."
        )
        is_local_development_server = (
            self.endpoint.ae_title.upper() == DEVELOPMENT_WORKLIST_AE_TITLE
            and self.endpoint.host.strip().lower() in LOOPBACK_HOSTS
        )
        if (
            is_local_development_server
            and self.endpoint.port != DEVELOPMENT_WORKLIST_PORT
        ):
            message += (
                " El servidor MWL local incluido con ECAP usa el puerto "
                f"{DEVELOPMENT_WORKLIST_PORT} por defecto."
            )
        return message

    def echo(self) -> EchoResult:
        ae = AE(ae_title=self.local_ae_title)
        ae.add_requested_context(Verification)
        self._configure_timeouts(ae)
        association = ae.associate(
            self.endpoint.host,
            self.endpoint.port,
            ae_title=self.endpoint.ae_title,
        )
        if not association.is_established:
            message = self._association_error()
            LOGGER.error(message)
            return EchoResult(False, None, message)
        try:
            response = association.send_c_echo()
            code = int(response.Status) if response is not None else None
            success = code == 0x0000
            status = "sin status" if code is None else f"0x{code:04X}"
            message = f"C-ECHO Worklist respondió {status}"
            (LOGGER.info if success else LOGGER.error)(message)
            return EchoResult(success, code, message)
        finally:
            association.release()

    def find(self, query: WorklistQuery) -> list[WorklistItem]:
        request = self._build_query(query)
        ae = AE(ae_title=self.local_ae_title)
        ae.add_requested_context(ModalityWorklistInformationFind)
        self._configure_timeouts(ae)
        LOGGER.info(
            "C-FIND Worklist: fecha=%r PatientID=%r PatientName=%r Accession=%r",
            query.scheduled_date,
            query.patient_id,
            query.patient_name,
            query.accession_number,
        )
        association = ae.associate(
            self.endpoint.host,
            self.endpoint.port,
            ae_title=self.endpoint.ae_title,
        )
        if not association.is_established:
            raise WorklistError(self._association_error())

        results: list[WorklistItem] = []
        try:
            for status, identifier in association.send_c_find(
                request, ModalityWorklistInformationFind
            ):
                if status is None:
                    raise WorklistError("C-FIND terminó sin status DICOM.")
                code = int(status.Status)
                if code in (0xFF00, 0xFF01) and identifier is not None:
                    results.append(self._to_item(identifier))
                elif code == 0x0000:
                    continue
                elif code == 0xFE00:
                    LOGGER.warning("C-FIND Worklist cancelado por el peer.")
                else:
                    raise WorklistError(f"C-FIND falló con status 0x{code:04X}.")
        finally:
            association.release()
        LOGGER.info("C-FIND Worklist devolvió %s resultado(s)", len(results))
        return results

    @staticmethod
    def _build_query(query: WorklistQuery) -> Dataset:
        dataset = Dataset()
        name = query.patient_name.strip()
        if name and "*" not in name and "?" not in name:
            name = f"*{name}*"
        dataset.PatientName = name
        dataset.PatientID = query.patient_id.strip()
        dataset.PatientBirthDate = ""
        dataset.PatientSex = ""
        dataset.AccessionNumber = query.accession_number.strip()
        dataset.StudyInstanceUID = ""
        dataset.RequestedProcedureID = ""
        dataset.RequestedProcedureDescription = ""
        dataset.ReferringPhysicianName = ""

        step = Dataset()
        step.ScheduledStationAETitle = ""
        step.ScheduledProcedureStepStartDate = query.scheduled_date.strip()
        step.ScheduledProcedureStepStartTime = ""
        step.Modality = ""
        step.ScheduledPerformingPhysicianName = ""
        step.ScheduledProcedureStepDescription = ""
        step.ScheduledProcedureStepID = ""
        dataset.ScheduledProcedureStepSequence = Sequence([step])
        return dataset

    @classmethod
    def _to_item(cls, dataset: Dataset) -> WorklistItem:
        sequence: Any = getattr(dataset, "ScheduledProcedureStepSequence", None)
        step = sequence[0] if sequence and len(sequence) else Dataset()
        return WorklistItem(
            patient_name=cls._text(dataset, "PatientName"),
            patient_id=cls._text(dataset, "PatientID"),
            patient_birth_date=cls._text(dataset, "PatientBirthDate"),
            patient_sex=cls._text(dataset, "PatientSex"),
            accession_number=cls._text(dataset, "AccessionNumber"),
            study_instance_uid=cls._text(dataset, "StudyInstanceUID"),
            requested_procedure_id=cls._text(dataset, "RequestedProcedureID"),
            requested_procedure_description=cls._text(
                dataset, "RequestedProcedureDescription"
            ),
            referring_physician_name=cls._text(dataset, "ReferringPhysicianName"),
            scheduled_station_ae_title=cls._text(step, "ScheduledStationAETitle"),
            scheduled_start_date=cls._text(
                step, "ScheduledProcedureStepStartDate"
            ),
            scheduled_start_time=cls._text(
                step, "ScheduledProcedureStepStartTime"
            ),
            modality=cls._text(step, "Modality"),
            scheduled_performing_physician_name=cls._text(
                step, "ScheduledPerformingPhysicianName"
            ),
            scheduled_procedure_step_description=cls._text(
                step, "ScheduledProcedureStepDescription"
            ),
            scheduled_procedure_step_id=cls._text(
                step, "ScheduledProcedureStepID"
            ),
        )

    @staticmethod
    def _text(dataset: Dataset, keyword: str) -> str:
        return str(getattr(dataset, keyword, "") or "")
