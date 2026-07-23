"""Build uncompressed VL Endoscopic Image Storage instances."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
import re
from typing import Any, Mapping

from PIL import Image, UnidentifiedImageError
from pydicom import dcmread, dcmwrite
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian, PYDICOM_IMPLEMENTATION_UID

from app.config import InstitutionConfig
from .uid import (
    is_valid_uid,
    new_series_instance_uid,
    new_sop_instance_uid,
    new_study_instance_uid,
)

LOGGER = logging.getLogger(__name__)

VL_ENDOSCOPIC_IMAGE_STORAGE_UID = "1.2.840.10008.5.1.4.1.1.77.1.1"
VIDEO_ENDOSCOPIC_IMAGE_STORAGE_UID = "1.2.840.10008.5.1.4.1.1.77.1.1.1"


class DicomBuildError(RuntimeError):
    """Raised when a source image cannot be converted into a valid DICOM file."""


@dataclass(frozen=True)
class DicomBuildResult:
    output_path: Path
    study_instance_uid: str
    series_instance_uid: str
    sop_instance_uid: str
    sop_class_uid: str
    warnings: tuple[str, ...]


class DicomBuilder:
    def __init__(self, institution: InstitutionConfig) -> None:
        self.institution = institution

    def create_vl_endoscopic_image(
        self,
        *,
        snapshot_path: str | Path,
        output_path: str | Path,
        metadata: Mapping[str, Any],
        instance_number: int = 1,
        series_instance_uid: str | None = None,
        now: datetime | None = None,
    ) -> DicomBuildResult:
        """Create and re-open an uncompressed RGB VL Endoscopic DICOM instance."""
        source = Path(snapshot_path)
        destination = Path(output_path)
        if not source.is_file():
            raise DicomBuildError(f"No existe el snapshot: {source}")
        if instance_number < 1:
            raise DicomBuildError("InstanceNumber debe ser mayor o igual a 1.")

        warnings: list[str] = []
        patient_name = str(metadata.get("patient_name") or "")
        patient_id = str(metadata.get("patient_id") or "")
        accession = str(metadata.get("accession_number") or "")
        for field_name, value in (
            ("PatientName", patient_name),
            ("PatientID", patient_id),
            ("AccessionNumber", accession),
        ):
            if not value:
                self._warn(
                    warnings,
                    f"Metadata crítica ausente: {field_name}. El atributo quedará vacío.",
                )

        study_uid = str(metadata.get("study_instance_uid") or "")
        if not is_valid_uid(study_uid):
            reason = "ausente" if not study_uid else "inválido"
            study_uid = new_study_instance_uid()
            self._warn(
                warnings,
                f"StudyInstanceUID {reason}; se generó uno nuevo: {study_uid}",
            )
        series_uid = series_instance_uid or new_series_instance_uid()
        if not is_valid_uid(series_uid):
            raise DicomBuildError("SeriesInstanceUID provisto es inválido.")
        sop_uid = new_sop_instance_uid()

        acquisition_time = now or datetime.now().astimezone()
        current_date = acquisition_time.strftime("%Y%m%d")
        current_time = acquisition_time.strftime("%H%M%S.%f")
        scheduled_date = self._dicom_date(
            str(metadata.get("scheduled_start_date") or ""), current_date, warnings
        )
        scheduled_time = self._dicom_time(
            str(metadata.get("scheduled_start_time") or ""), current_time, warnings
        )

        try:
            with Image.open(source) as image:
                rgb_image = image.convert("RGB")
                columns, rows = rgb_image.size
                pixel_data = rgb_image.tobytes()
        except (OSError, UnidentifiedImageError) as exc:
            raise DicomBuildError(f"No se pudo leer el snapshot {source}: {exc}") from exc
        if rows < 1 or columns < 1 or len(pixel_data) != rows * columns * 3:
            raise DicomBuildError("El snapshot produjo PixelData RGB inconsistente.")
        # All DICOM value fields have even length. A trailing null byte is padding,
        # not an additional pixel sample, and is ignored using Rows/Columns.
        if len(pixel_data) % 2:
            pixel_data += b"\0"

        file_meta = FileMetaDataset()
        file_meta.FileMetaInformationVersion = b"\x00\x01"
        file_meta.MediaStorageSOPClassUID = VL_ENDOSCOPIC_IMAGE_STORAGE_UID
        file_meta.MediaStorageSOPInstanceUID = sop_uid
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        file_meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
        file_meta.ImplementationVersionName = "ELECTROCAP_1_0"

        dataset = FileDataset(
            str(destination), {}, file_meta=file_meta, preamble=b"\0" * 128
        )
        dataset.SpecificCharacterSet = "ISO_IR 192"
        dataset.SOPClassUID = VL_ENDOSCOPIC_IMAGE_STORAGE_UID
        dataset.SOPInstanceUID = sop_uid
        dataset.StudyInstanceUID = study_uid
        dataset.SeriesInstanceUID = series_uid

        dataset.PatientName = self._fit(patient_name, 64, "PatientName", warnings)
        dataset.PatientID = self._fit(patient_id, 64, "PatientID", warnings)
        dataset.PatientBirthDate = str(metadata.get("patient_birth_date") or "")
        dataset.PatientSex = str(metadata.get("patient_sex") or "")
        dataset.AccessionNumber = self._fit(accession, 16, "AccessionNumber", warnings)
        dataset.ReferringPhysicianName = self._fit(
            str(metadata.get("referring_physician_name") or ""),
            64,
            "ReferringPhysicianName",
            warnings,
        )

        dataset.StudyDate = scheduled_date
        dataset.StudyTime = scheduled_time
        dataset.SeriesDate = current_date
        dataset.SeriesTime = current_time
        dataset.ContentDate = current_date
        dataset.ContentTime = current_time
        dataset.InstanceCreationDate = current_date
        dataset.InstanceCreationTime = current_time
        dataset.AcquisitionDateTime = current_date + current_time
        # StudyID and RequestedProcedureID are not interchangeable. Keep the
        # former empty when MWL doesn't provide it and preserve request data in
        # the standard Request Attributes Sequence.
        dataset.StudyID = ""
        requested_procedure_id = str(metadata.get("requested_procedure_id") or "")
        scheduled_step_id = str(metadata.get("scheduled_procedure_step_id") or "")
        requested_description = str(
            metadata.get("requested_procedure_description") or ""
        )
        scheduled_description = str(
            metadata.get("scheduled_procedure_step_description") or ""
        )
        if (
            requested_procedure_id
            or scheduled_step_id
            or requested_description
            or scheduled_description
        ):
            request_attributes = Dataset()
            request_attributes.RequestedProcedureID = self._fit(
                requested_procedure_id, 16, "RequestedProcedureID", warnings
            )
            request_attributes.ScheduledProcedureStepID = self._fit(
                scheduled_step_id, 16, "ScheduledProcedureStepID", warnings
            )
            request_attributes.RequestedProcedureDescription = self._fit(
                requested_description, 64, "RequestedProcedureDescription", warnings
            )
            request_attributes.ScheduledProcedureStepDescription = self._fit(
                scheduled_description,
                64,
                "ScheduledProcedureStepDescription",
                warnings,
            )
            request_attributes.AccessionNumber = self._fit(
                accession, 16, "RequestAttributes.AccessionNumber", warnings
            )
            dataset.RequestAttributesSequence = Sequence([request_attributes])
        dataset.SeriesNumber = 1
        dataset.InstanceNumber = instance_number

        dataset.Modality = "ES"
        dataset.InstitutionName = self._fit(
            self.institution.name, 64, "InstitutionName", warnings
        )
        dataset.StationName = self._fit(
            self.institution.station_name, 16, "StationName", warnings
        )
        dataset.Manufacturer = self._fit(
            self.institution.manufacturer, 64, "Manufacturer", warnings
        )
        dataset.ManufacturerModelName = self._fit(
            self.institution.manufacturer_model_name,
            64,
            "ManufacturerModelName",
            warnings,
        )
        dataset.SoftwareVersions = self._fit(
            self.institution.software_version, 64, "SoftwareVersions", warnings
        )
        dataset.SeriesDescription = "COLPOSCOPIA - IMAGEN FIJA"
        study_description = requested_description or scheduled_description
        if study_description:
            dataset.StudyDescription = self._fit(
                study_description, 64, "StudyDescription", warnings
            )
        dataset.BodyPartExamined = "CERVIX"
        dataset.ImageType = ["ORIGINAL", "PRIMARY"]
        dataset.ConversionType = "WSD"
        dataset.BurnedInAnnotation = "NO"
        if source.suffix.lower() in {".jpg", ".jpeg"}:
            # PixelData is uncompressed, but the source snapshot has already
            # undergone JPEG lossy compression and DICOM requires recording that.
            dataset.LossyImageCompression = "01"
            dataset.LossyImageCompressionMethod = "ISO_10918_1"
        else:
            dataset.LossyImageCompression = "00"
        dataset.PatientOrientation = ["", ""]
        dataset.Laterality = ""
        dataset.PositionReferenceIndicator = ""

        dataset.SamplesPerPixel = 3
        dataset.PhotometricInterpretation = "RGB"
        dataset.PlanarConfiguration = 0
        dataset.Rows = rows
        dataset.Columns = columns
        dataset.BitsAllocated = 8
        dataset.BitsStored = 8
        dataset.HighBit = 7
        dataset.PixelRepresentation = 0
        dataset.PixelData = pixel_data

        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            dcmwrite(destination, dataset, enforce_file_format=True)
            self._validate_written_file(destination, rows, columns, sop_uid)
        except Exception as exc:
            destination.unlink(missing_ok=True)
            if isinstance(exc, DicomBuildError):
                raise
            raise DicomBuildError(f"No se pudo escribir DICOM {destination}: {exc}") from exc

        LOGGER.info(
            "DICOM VL Endoscopic creado: %s (SOPInstanceUID=%s)", destination, sop_uid
        )
        return DicomBuildResult(
            output_path=destination,
            study_instance_uid=study_uid,
            series_instance_uid=series_uid,
            sop_instance_uid=sop_uid,
            sop_class_uid=VL_ENDOSCOPIC_IMAGE_STORAGE_UID,
            warnings=tuple(warnings),
        )

    def create_video_endoscopic(self, *_args: Any, **_kwargs: Any) -> None:
        """Reserved for a future, validated MPEG/H.264 DICOM encapsulation path."""
        raise NotImplementedError(
            "Video Endoscopic Image Storage es experimental y no forma parte de esta "
            "versión. "
            "El MP4 permanece local y trazable; no se realizará encapsulación insegura."
        )

    @staticmethod
    def _validate_written_file(
        path: Path, expected_rows: int, expected_columns: int, expected_sop_uid: str
    ) -> None:
        validated = dcmread(path)
        if str(validated.SOPClassUID) != VL_ENDOSCOPIC_IMAGE_STORAGE_UID:
            raise DicomBuildError("SOPClassUID inesperado al releer el DICOM.")
        if str(validated.SOPInstanceUID) != expected_sop_uid:
            raise DicomBuildError("SOPInstanceUID cambió al releer el DICOM.")
        if validated.Rows != expected_rows or validated.Columns != expected_columns:
            raise DicomBuildError("Dimensiones inconsistentes al releer el DICOM.")
        expected_length = expected_rows * expected_columns * 3
        expected_padded_length = expected_length + (expected_length % 2)
        if len(validated.PixelData) != expected_padded_length:
            raise DicomBuildError("PixelData inconsistente al releer el DICOM.")

    @staticmethod
    def _warn(warnings: list[str], message: str) -> None:
        warnings.append(message)
        LOGGER.warning(message)

    @classmethod
    def _fit(
        cls, value: str, maximum: int, field: str, warnings: list[str]
    ) -> str:
        if len(value) <= maximum:
            return value
        cls._warn(
            warnings,
            f"{field} supera {maximum} caracteres; se truncó en el DICOM generado.",
        )
        return value[:maximum]

    @classmethod
    def _dicom_date(
        cls, value: str, fallback: str, warnings: list[str]
    ) -> str:
        if not value:
            cls._warn(
                warnings,
                "Fecha programada ausente; StudyDate usa la fecha real de la captura.",
            )
            return fallback
        if re.fullmatch(r"\d{8}", value):
            return value
        cls._warn(
            warnings,
            "Fecha programada inválida; StudyDate usa la fecha real de la captura.",
        )
        return fallback

    @classmethod
    def _dicom_time(
        cls, value: str, fallback: str, warnings: list[str]
    ) -> str:
        if not value:
            cls._warn(
                warnings,
                "Hora programada ausente; StudyTime usa la hora real de la captura.",
            )
            return fallback
        if re.fullmatch(r"\d{2,6}(?:\.\d{1,6})?", value):
            return value
        cls._warn(
            warnings,
            "Hora programada inválida; StudyTime usa la hora real de la captura.",
        )
        return fallback
