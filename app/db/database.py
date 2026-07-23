"""SQLite persistence with one connection per operation for thread safety."""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from .models import (
    CaptureImageRecord,
    CaptureRecord,
    ExportRecord,
    StudyRecord,
    WorkflowStatus,
)

LOGGER = logging.getLogger(__name__)


def local_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Database:
    """Small explicit repository around the local audit database."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS studies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_name TEXT NOT NULL DEFAULT '',
                    patient_id TEXT NOT NULL DEFAULT '',
                    patient_birth_date TEXT NOT NULL DEFAULT '',
                    patient_sex TEXT NOT NULL DEFAULT '',
                    accession_number TEXT NOT NULL DEFAULT '',
                    study_instance_uid TEXT NOT NULL DEFAULT '',
                    requested_procedure_id TEXT NOT NULL DEFAULT '',
                    requested_procedure_description TEXT NOT NULL DEFAULT '',
                    referring_physician_name TEXT NOT NULL DEFAULT '',
                    scheduled_station_ae_title TEXT NOT NULL DEFAULT '',
                    modality TEXT NOT NULL DEFAULT '',
                    scheduled_performing_physician_name TEXT NOT NULL DEFAULT '',
                    scheduled_procedure_step_description TEXT NOT NULL DEFAULT '',
                    scheduled_procedure_step_id TEXT NOT NULL DEFAULT '',
                    scheduled_start_date TEXT NOT NULL DEFAULT '',
                    scheduled_start_time TEXT NOT NULL DEFAULT '',
                    selected_at TEXT NOT NULL,
                    status TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS captures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    study_id INTEGER NOT NULL,
                    video_path TEXT,
                    snapshot_path TEXT,
                    dicom_image_path TEXT,
                    dicom_video_path TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    status TEXT NOT NULL,
                    FOREIGN KEY (study_id) REFERENCES studies(id)
                );

                CREATE TABLE IF NOT EXISTS dicom_exports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    capture_id INTEGER NOT NULL,
                    sop_instance_uid TEXT NOT NULL,
                    sop_class_uid TEXT NOT NULL,
                    destination_ae TEXT NOT NULL,
                    destination_host TEXT NOT NULL,
                    destination_port INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    response_status TEXT,
                    attempted_at TEXT NOT NULL,
                    error_message TEXT,
                    image_id INTEGER,
                    FOREIGN KEY (capture_id) REFERENCES captures(id)
                );

                CREATE TABLE IF NOT EXISTS capture_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    capture_id INTEGER NOT NULL,
                    snapshot_path TEXT NOT NULL,
                    dicom_image_path TEXT,
                    instance_number INTEGER NOT NULL,
                    captured_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    FOREIGN KEY (capture_id) REFERENCES captures(id),
                    UNIQUE (capture_id, instance_number)
                );

                CREATE INDEX IF NOT EXISTS idx_captures_study_id
                    ON captures(study_id);
                CREATE INDEX IF NOT EXISTS idx_exports_capture_id
                    ON dicom_exports(capture_id);
                CREATE INDEX IF NOT EXISTS idx_exports_status
                    ON dicom_exports(status);
                CREATE INDEX IF NOT EXISTS idx_capture_images_capture_id
                    ON capture_images(capture_id);
                """
            )
            export_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(dicom_exports)")
            }
            if "image_id" not in export_columns:
                connection.execute("ALTER TABLE dicom_exports ADD COLUMN image_id INTEGER")
        LOGGER.info("Base SQLite inicializada en %s", self.path)

    def create_study(self, values: Mapping[str, Any]) -> StudyRecord:
        columns = (
            "patient_name",
            "patient_id",
            "patient_birth_date",
            "patient_sex",
            "accession_number",
            "study_instance_uid",
            "requested_procedure_id",
            "requested_procedure_description",
            "referring_physician_name",
            "scheduled_station_ae_title",
            "modality",
            "scheduled_performing_physician_name",
            "scheduled_procedure_step_description",
            "scheduled_procedure_step_id",
            "scheduled_start_date",
            "scheduled_start_time",
        )
        payload = [str(values.get(column) or "") for column in columns]
        payload.extend([local_timestamp(), WorkflowStatus.SELECTED.value])
        with self._connect() as connection:
            cursor = connection.execute(
                f"INSERT INTO studies ({', '.join(columns)}, selected_at, status) "
                f"VALUES ({', '.join('?' for _ in payload)})",
                payload,
            )
            study_id = int(cursor.lastrowid)
        LOGGER.info("Estudio local %s seleccionado", study_id)
        return self.get_study(study_id)

    def get_study(self, study_id: int) -> StudyRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM studies WHERE id = ?", (study_id,)
            ).fetchone()
        if row is None:
            raise LookupError(f"No existe el estudio local {study_id}.")
        return StudyRecord.from_row(row)

    def update_study_status(self, study_id: int, status: WorkflowStatus | str) -> None:
        status_value = status.value if isinstance(status, WorkflowStatus) else status
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE studies SET status = ? WHERE id = ?", (status_value, study_id)
            )
        if cursor.rowcount != 1:
            raise LookupError(f"No existe el estudio local {study_id}.")

    def update_study_instance_uid(self, study_id: int, study_instance_uid: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE studies SET study_instance_uid = ? WHERE id = ?",
                (study_instance_uid, study_id),
            )
        if cursor.rowcount != 1:
            raise LookupError(f"No existe el estudio local {study_id}.")

    def create_capture(
        self,
        study_id: int,
        video_path: str | Path,
        status: WorkflowStatus = WorkflowStatus.RECORDING,
    ) -> CaptureRecord:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO captures (study_id, video_path, started_at, status)
                VALUES (?, ?, ?, ?)
                """,
                (study_id, str(video_path), local_timestamp(), status.value),
            )
            capture_id = int(cursor.lastrowid)
        return self.get_capture(capture_id)

    def get_capture(self, capture_id: int) -> CaptureRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM captures WHERE id = ?", (capture_id,)
            ).fetchone()
        if row is None:
            raise LookupError(f"No existe la captura local {capture_id}.")
        return CaptureRecord.from_row(row)

    def update_capture(self, capture_id: int, **changes: Any) -> CaptureRecord:
        allowed = {
            "video_path",
            "snapshot_path",
            "dicom_image_path",
            "dicom_video_path",
            "started_at",
            "ended_at",
            "status",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"Campos de captura no permitidos: {sorted(unknown)}")
        if not changes:
            return self.get_capture(capture_id)
        if isinstance(changes.get("status"), WorkflowStatus):
            changes["status"] = changes["status"].value
        assignment = ", ".join(f"{key} = ?" for key in changes)
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE captures SET {assignment} WHERE id = ?",
                (*changes.values(), capture_id),
            )
        if cursor.rowcount != 1:
            raise LookupError(f"No existe la captura local {capture_id}.")
        return self.get_capture(capture_id)

    def create_capture_image(
        self,
        *,
        capture_id: int,
        snapshot_path: str | Path,
        instance_number: int,
    ) -> CaptureImageRecord:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO capture_images (
                    capture_id, snapshot_path, instance_number, captured_at, status
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    capture_id,
                    str(snapshot_path),
                    instance_number,
                    local_timestamp(),
                    WorkflowStatus.SNAPSHOT_CREATED.value,
                ),
            )
            image_id = int(cursor.lastrowid)
        return self.get_capture_image(image_id)

    def get_capture_image(self, image_id: int) -> CaptureImageRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM capture_images WHERE id = ?", (image_id,)
            ).fetchone()
        if row is None:
            raise LookupError(f"No existe la imagen local {image_id}.")
        return CaptureImageRecord.from_row(row)

    def list_capture_images(self, capture_id: int) -> list[CaptureImageRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM capture_images
                WHERE capture_id = ?
                ORDER BY instance_number, id
                """,
                (capture_id,),
            ).fetchall()
        return [CaptureImageRecord.from_row(row) for row in rows]

    def update_capture_image(
        self, image_id: int, **changes: Any
    ) -> CaptureImageRecord:
        allowed = {"snapshot_path", "dicom_image_path", "instance_number", "status"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"Campos de imagen no permitidos: {sorted(unknown)}")
        if not changes:
            return self.get_capture_image(image_id)
        if isinstance(changes.get("status"), WorkflowStatus):
            changes["status"] = changes["status"].value
        assignment = ", ".join(f"{key} = ?" for key in changes)
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE capture_images SET {assignment} WHERE id = ?",
                (*changes.values(), image_id),
            )
        if cursor.rowcount != 1:
            raise LookupError(f"No existe la imagen local {image_id}.")
        return self.get_capture_image(image_id)

    def delete_capture_image(self, image_id: int) -> CaptureImageRecord:
        """Delete one snapshot row and refresh the capture compatibility path."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM capture_images WHERE id = ?", (image_id,)
            ).fetchone()
            if row is None:
                raise LookupError(f"No existe la imagen local {image_id}.")
            image = CaptureImageRecord.from_row(row)
            connection.execute(
                "DELETE FROM dicom_exports WHERE image_id = ?", (image_id,)
            )
            connection.execute("DELETE FROM capture_images WHERE id = ?", (image_id,))
            latest = connection.execute(
                """
                SELECT snapshot_path FROM capture_images
                WHERE capture_id = ?
                ORDER BY instance_number DESC, id DESC
                LIMIT 1
                """,
                (image.capture_id,),
            ).fetchone()
            latest_path = str(latest["snapshot_path"]) if latest is not None else None
            connection.execute(
                "UPDATE captures SET snapshot_path = ? WHERE id = ?",
                (latest_path, image.capture_id),
            )
        LOGGER.info(
            "Snapshot local eliminado: captura=%s imagen=%s",
            image.capture_id,
            image.id,
        )
        return image

    def delete_capture_session(self, capture_id: int) -> int:
        """Delete one capture and its dependent audit rows atomically.

        The parent study is also removed when this was its only capture. File
        deletion is deliberately handled by StudyService before this method so
        the database is retained if the filesystem cleanup cannot complete.
        """
        with self._connect() as connection:
            row = connection.execute(
                "SELECT study_id FROM captures WHERE id = ?", (capture_id,)
            ).fetchone()
            if row is None:
                raise LookupError(f"No existe la captura local {capture_id}.")
            study_id = int(row["study_id"])
            connection.execute(
                "DELETE FROM dicom_exports WHERE capture_id = ?", (capture_id,)
            )
            connection.execute(
                "DELETE FROM capture_images WHERE capture_id = ?", (capture_id,)
            )
            connection.execute("DELETE FROM captures WHERE id = ?", (capture_id,))
            remaining = connection.execute(
                "SELECT 1 FROM captures WHERE study_id = ? LIMIT 1", (study_id,)
            ).fetchone()
            if remaining is None:
                connection.execute("DELETE FROM studies WHERE id = ?", (study_id,))
        LOGGER.info(
            "Sesión local eliminada: estudio=%s captura=%s", study_id, capture_id
        )
        return study_id

    def create_export(
        self,
        *,
        capture_id: int,
        sop_instance_uid: str,
        sop_class_uid: str,
        destination_ae: str,
        destination_host: str,
        destination_port: int,
        image_id: int | None = None,
    ) -> ExportRecord:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO dicom_exports (
                    capture_id, sop_instance_uid, sop_class_uid,
                    destination_ae, destination_host, destination_port,
                    status, attempted_at, image_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capture_id,
                    sop_instance_uid,
                    sop_class_uid,
                    destination_ae,
                    destination_host,
                    destination_port,
                    "PENDING",
                    local_timestamp(),
                    image_id,
                ),
            )
            export_id = int(cursor.lastrowid)
        return self.get_export(export_id)

    def get_export(self, export_id: int) -> ExportRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM dicom_exports WHERE id = ?", (export_id,)
            ).fetchone()
        if row is None:
            raise LookupError(f"No existe la exportación local {export_id}.")
        return ExportRecord.from_row(row)

    def complete_export(
        self,
        export_id: int,
        *,
        status: WorkflowStatus,
        response_status: str | None,
        error_message: str | None,
    ) -> ExportRecord:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE dicom_exports
                SET status = ?, response_status = ?, error_message = ?
                WHERE id = ?
                """,
                (status.value, response_status, error_message, export_id),
            )
        if cursor.rowcount != 1:
            raise LookupError(f"No existe la exportación local {export_id}.")
        return self.get_export(export_id)

    def list_pending_captures(self) -> list[dict[str, Any]]:
        """Return capture sessions that still contain unsent DICOM images."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    c.id AS capture_id,
                    c.dicom_image_path,
                    c.status AS capture_status,
                    s.patient_name,
                    s.patient_id,
                    s.accession_number,
                    de.status AS export_status,
                    de.response_status,
                    de.attempted_at,
                    de.error_message,
                    COUNT(ci.id) AS image_count,
                    SUM(CASE WHEN ci.status = 'SENT' THEN 1 ELSE 0 END) AS sent_count
                FROM captures c
                JOIN studies s ON s.id = c.study_id
                LEFT JOIN capture_images ci ON ci.capture_id = c.id
                LEFT JOIN dicom_exports de ON de.id = (
                    SELECT MAX(de2.id)
                    FROM dicom_exports de2
                    WHERE de2.capture_id = c.id
                )
                WHERE (
                    EXISTS (
                        SELECT 1 FROM capture_images pending_ci
                        WHERE pending_ci.capture_id = c.id
                          AND pending_ci.dicom_image_path IS NOT NULL
                          AND pending_ci.status <> ?
                    )
                    OR (
                        NOT EXISTS (
                            SELECT 1 FROM capture_images any_ci
                            WHERE any_ci.capture_id = c.id
                        )
                        AND c.dicom_image_path IS NOT NULL
                        AND COALESCE(de.status, c.status) <> ?
                    )
                )
                GROUP BY c.id
                ORDER BY COALESCE(de.attempted_at, c.started_at) DESC
                """,
                (WorkflowStatus.SENT.value, WorkflowStatus.SENT.value),
            ).fetchall()
        return [dict(row) for row in rows]

    def table_count(self, table: str) -> int:
        if table not in {"studies", "captures", "capture_images", "dicom_exports"}:
            raise ValueError("Tabla no permitida.")
        with self._connect() as connection:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
