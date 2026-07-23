"""Development-only DICOM Modality Worklist SCP backed by a JSON file.

This server is intentionally small and deterministic.  It lets ElectroCap exercise
the same C-FIND workflow used against an institutional MWL without making
Orthanc responsible for appointments.
"""

from __future__ import annotations

import argparse
from datetime import date
import fnmatch
import json
import logging
from pathlib import Path
import re
import time
from typing import Any, Iterable, Mapping

from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from pynetdicom import AE, evt
from pynetdicom.sop_class import ModalityWorklistInformationFind, Verification


LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_PATH = PROJECT_ROOT / "config" / "mwl.sample.json"

TOP_LEVEL_FIELDS = {
    "PatientName": "patient_name",
    "PatientID": "patient_id",
    "PatientBirthDate": "patient_birth_date",
    "PatientSex": "patient_sex",
    "AccessionNumber": "accession_number",
    "StudyInstanceUID": "study_instance_uid",
    "RequestedProcedureID": "requested_procedure_id",
    "RequestedProcedureDescription": "requested_procedure_description",
    "ReferringPhysicianName": "referring_physician_name",
}

SCHEDULED_STEP_FIELDS = {
    "ScheduledStationAETitle": "scheduled_station_ae_title",
    "ScheduledProcedureStepStartDate": "scheduled_start_date",
    "ScheduledProcedureStepStartTime": "scheduled_start_time",
    "Modality": "modality",
    "ScheduledPerformingPhysicianName": "scheduled_performing_physician_name",
    "ScheduledProcedureStepDescription": "scheduled_procedure_step_description",
    "ScheduledProcedureStepID": "scheduled_procedure_step_id",
}


class WorklistDataError(RuntimeError):
    """Raised when the development worklist JSON is invalid."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _expand_date(value: str) -> str:
    return date.today().strftime("%Y%m%d") if value.upper() == "TODAY" else value


class JsonWorklistRepository:
    """Read worklist entries from JSON on each query so edits apply immediately."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()

    def load(self) -> list[Dataset]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise WorklistDataError(f"No existe el archivo MWL: {self.path}") from exc
        except json.JSONDecodeError as exc:
            raise WorklistDataError(
                f"JSON MWL inválido en {self.path}, línea {exc.lineno}: {exc.msg}"
            ) from exc
        except OSError as exc:
            raise WorklistDataError(f"No se pudo leer {self.path}: {exc}") from exc

        if not isinstance(raw, list):
            raise WorklistDataError("El archivo MWL debe contener una lista JSON.")

        datasets: list[Dataset] = []
        for index, item in enumerate(raw, start=1):
            if not isinstance(item, Mapping):
                raise WorklistDataError(f"La entrada MWL {index} debe ser un objeto JSON.")
            datasets.append(self._to_dataset(item, index))
        return datasets

    @staticmethod
    def _to_dataset(item: Mapping[str, Any], index: int) -> Dataset:
        values = {key: _text(value) for key, value in item.items()}
        patient_id = values.get("patient_id", "")
        accession_number = values.get("accession_number", "")
        scheduled_date = _expand_date(values.get("scheduled_start_date", ""))

        if not patient_id:
            raise WorklistDataError(f"La entrada MWL {index} no tiene patient_id.")
        if not accession_number:
            raise WorklistDataError(f"La entrada MWL {index} no tiene accession_number.")
        if not re.fullmatch(r"\d{8}", scheduled_date):
            raise WorklistDataError(
                f"La entrada MWL {index} debe tener scheduled_start_date "
                "en formato AAAAMMDD o TODAY."
            )

        station_ae = values.get("scheduled_station_ae_title", "")
        if len(station_ae) > 16:
            raise WorklistDataError(
                f"La entrada MWL {index} tiene un ScheduledStationAETitle "
                "de más de 16 caracteres."
            )

        dataset = Dataset()
        dataset.SpecificCharacterSet = "ISO_IR 192"
        for dicom_keyword, json_key in TOP_LEVEL_FIELDS.items():
            setattr(dataset, dicom_keyword, values.get(json_key, ""))

        step = Dataset()
        for dicom_keyword, json_key in SCHEDULED_STEP_FIELDS.items():
            value = values.get(json_key, "")
            if json_key == "scheduled_start_date":
                value = scheduled_date
            setattr(step, dicom_keyword, value)
        dataset.ScheduledProcedureStepSequence = Sequence([step])
        return dataset


def _matches_date(candidate: str, expression: str) -> bool:
    if "-" not in expression:
        return candidate == expression
    start, end = expression.split("-", maxsplit=1)
    return (not start or candidate >= start) and (not end or candidate <= end)


def _matches_text(candidate: str, expression: str, *, is_date: bool = False) -> bool:
    expression = expression.strip()
    if not expression:
        return True
    alternatives = expression.split("\\")
    for option in alternatives:
        option = option.strip()
        if is_date and _matches_date(candidate, option):
            return True
        if not is_date and fnmatch.fnmatchcase(candidate.casefold(), option.casefold()):
            return True
    return False


def dataset_matches_query(candidate: Dataset, query: Dataset) -> bool:
    """Apply the common MWL matching keys used by ElectroCap and findscu."""

    for dicom_keyword in TOP_LEVEL_FIELDS:
        expression = _text(getattr(query, dicom_keyword, ""))
        candidate_value = _text(getattr(candidate, dicom_keyword, ""))
        is_date = dicom_keyword == "PatientBirthDate"
        if not _matches_text(candidate_value, expression, is_date=is_date):
            return False

    query_steps = getattr(query, "ScheduledProcedureStepSequence", None)
    if not query_steps:
        return True
    candidate_steps = getattr(candidate, "ScheduledProcedureStepSequence", None)
    if not candidate_steps:
        return False

    query_step = query_steps[0]
    candidate_step = candidate_steps[0]
    for dicom_keyword in SCHEDULED_STEP_FIELDS:
        expression = _text(getattr(query_step, dicom_keyword, ""))
        candidate_value = _text(getattr(candidate_step, dicom_keyword, ""))
        is_date = dicom_keyword == "ScheduledProcedureStepStartDate"
        if not _matches_text(candidate_value, expression, is_date=is_date):
            return False
    return True


class MwlServer:
    """Small MWL SCP suitable for local development and automated tests."""

    def __init__(
        self,
        repository: JsonWorklistRepository,
        *,
        ae_title: str = "COLPOCAP_WL",
        host: str = "127.0.0.1",
        port: int = 11112,
        allowed_calling_aes: Iterable[str] = ("COLPOCAP_MVP",),
    ) -> None:
        if not ae_title or len(ae_title) > 16:
            raise ValueError("El AE Title del servidor debe tener entre 1 y 16 caracteres.")
        if not 0 <= port <= 65535:
            raise ValueError("El puerto debe estar entre 0 y 65535.")
        allowed = tuple(value.strip() for value in allowed_calling_aes if value.strip())
        if any(len(value) > 16 for value in allowed):
            raise ValueError("Los Calling AE Titles no pueden superar 16 caracteres.")

        self.repository = repository
        self.ae_title = ae_title
        self.host = host
        self.port = port
        self.allowed_calling_aes = allowed
        self._server: Any | None = None

    @property
    def bound_port(self) -> int:
        if self._server is None:
            return self.port
        return int(self._server.server_address[1])

    def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("El servidor MWL ya está iniciado.")

        # Validate the file before opening the listening socket.
        entries = self.repository.load()
        ae = AE(ae_title=self.ae_title)
        ae.add_supported_context(Verification)
        ae.add_supported_context(ModalityWorklistInformationFind)
        ae.require_called_aet = True
        ae.require_calling_aet = list(self.allowed_calling_aes)
        ae.acse_timeout = 10
        ae.dimse_timeout = 30
        ae.network_timeout = 10

        LOGGER.info(
            "Iniciando MWL de desarrollo %s en %s:%s con %s turno(s)",
            self.ae_title,
            self.host,
            self.port,
            len(entries),
        )
        self._server = ae.start_server(
            (self.host, self.port),
            block=False,
            evt_handlers=[
                (evt.EVT_C_ECHO, self._handle_echo),
                (evt.EVT_C_FIND, self._handle_find),
            ],
        )

    def shutdown(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server = None

    @staticmethod
    def _handle_echo(_event: Any) -> int:
        LOGGER.info("C-ECHO MWL recibido")
        return 0x0000

    def _handle_find(self, event: Any):
        try:
            entries = self.repository.load()
            matches = [entry for entry in entries if dataset_matches_query(entry, event.identifier)]
            LOGGER.info(
                "C-FIND MWL recibido desde %s: %s de %s turno(s) coinciden",
                _text(event.assoc.requestor.ae_title),
                len(matches),
                len(entries),
            )
            for entry in matches:
                if event.is_cancelled:
                    yield 0xFE00, None
                    return
                yield 0xFF00, entry
            yield 0x0000, None
        except WorklistDataError:
            LOGGER.exception("No se pudo procesar el archivo de turnos MWL")
            yield 0xC000, None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Servidor DICOM MWL local para desarrollo de ElectroCap."
    )
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--ae-title", default="COLPOCAP_WL")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11112)
    parser.add_argument(
        "--allow-calling-ae",
        action="append",
        dest="allowed_calling_aes",
        help="Calling AE permitido; puede repetirse. Por defecto: COLPOCAP_MVP.",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    server = MwlServer(
        JsonWorklistRepository(args.data),
        ae_title=args.ae_title,
        host=args.host,
        port=args.port,
        allowed_calling_aes=args.allowed_calling_aes or ("COLPOCAP_MVP",),
    )
    try:
        server.start()
        LOGGER.info(
            "MWL listo. Called AE=%s, host=%s, puerto=%s. Ctrl+C para detener.",
            server.ae_title,
            server.host,
            server.bound_port,
        )
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        LOGGER.info("Deteniendo servidor MWL")
    except (OSError, ValueError, WorklistDataError) as exc:
        LOGGER.error("No se pudo iniciar el servidor MWL: %s", exc)
        return 1
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
