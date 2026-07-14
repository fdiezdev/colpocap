"""DICOM Verification and Storage SCU client."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

from pydicom import dcmread
from pynetdicom import AE
from pynetdicom.sop_class import Verification

from app.config import DicomEndpointConfig

LOGGER = logging.getLogger(__name__)


class StoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class EchoResult:
    success: bool
    status_code: int | None
    message: str


@dataclass(frozen=True)
class StoreResult:
    status_code: int
    status_hex: str
    success: bool
    warning: bool
    message: str


class StoreClient:
    def __init__(self, local_ae_title: str, endpoint: DicomEndpointConfig) -> None:
        self.local_ae_title = local_ae_title
        self.endpoint = endpoint

    @staticmethod
    def _configure_timeouts(ae: AE) -> None:
        ae.acse_timeout = 10
        ae.dimse_timeout = 30
        ae.network_timeout = 10

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
            message = (
                f"No se pudo asociar con PACS {self.endpoint.ae_title} "
                f"({self.endpoint.host}:{self.endpoint.port})."
            )
            LOGGER.error(message)
            return EchoResult(False, None, message)
        try:
            status = association.send_c_echo()
            code = int(status.Status) if status is not None else None
            success = code == 0x0000
            message = f"C-ECHO PACS respondió {self._hex(code)}"
            (LOGGER.info if success else LOGGER.error)(message)
            return EchoResult(success, code, message)
        finally:
            association.release()

    def store(self, dicom_path: str | Path) -> StoreResult:
        path = Path(dicom_path)
        if not path.is_file():
            raise StoreError(f"No existe el archivo DICOM: {path}")
        try:
            dataset = dcmread(path)
            sop_class_uid = str(dataset.SOPClassUID)
        except Exception as exc:
            raise StoreError(f"No se pudo abrir el DICOM {path}: {exc}") from exc

        ae = AE(ae_title=self.local_ae_title)
        ae.add_requested_context(sop_class_uid)
        self._configure_timeouts(ae)
        LOGGER.info(
            "Intentando C-STORE de %s a %s@%s:%s",
            path,
            self.endpoint.ae_title,
            self.endpoint.host,
            self.endpoint.port,
        )
        association = ae.associate(
            self.endpoint.host,
            self.endpoint.port,
            ae_title=self.endpoint.ae_title,
        )
        if not association.is_established:
            raise StoreError("El PACS rechazó o no estableció la asociación DICOM.")
        try:
            response = association.send_c_store(dataset)
            if response is None or not hasattr(response, "Status"):
                raise StoreError("C-STORE no devolvió un status DICOM.")
            code = int(response.Status)
            warning = 0xB000 <= code <= 0xBFFF
            success = code == 0x0000
            status_hex = self._hex(code)
            if success:
                message = f"C-STORE exitoso, respuesta {status_hex}."
                LOGGER.info(message)
            elif warning:
                message = f"C-STORE almacenado con advertencia {status_hex}."
                LOGGER.warning(message)
            else:
                message = f"C-STORE falló con respuesta {status_hex}."
                LOGGER.error(message)
            return StoreResult(code, status_hex, success, warning, message)
        finally:
            association.release()

    @staticmethod
    def _hex(code: int | None) -> str:
        return "sin status" if code is None else f"0x{code:04X}"

