"""Application configuration loading and validation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping


DEVELOPMENT_WORKLIST_AE_TITLE = "COLPOCAP_WL"
DEVELOPMENT_WORKLIST_PORT = 11112
LEGACY_DEVELOPMENT_WORKLIST_PORT = 11111
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
APPLICATION_NAME = "ECAP"
LEGACY_APPLICATION_NAME = "ElectroCap"


class ConfigurationError(RuntimeError):
    """Raised when the settings file is missing or invalid."""


@dataclass(frozen=True)
class DicomEndpointConfig:
    ae_title: str
    host: str
    port: int


@dataclass(frozen=True)
class VideoConfig:
    device_name: str
    resolution: str
    fps: int
    bitrate: str


@dataclass(frozen=True)
class InstitutionConfig:
    name: str
    station_name: str
    manufacturer: str
    manufacturer_model_name: str
    software_version: str


@dataclass(frozen=True)
class StorageConfig:
    base_output_dir: Path

    @property
    def videos_dir(self) -> Path:
        return self.base_output_dir / "videos"

    @property
    def snapshots_dir(self) -> Path:
        return self.base_output_dir / "snapshots"

    @property
    def dicom_dir(self) -> Path:
        return self.base_output_dir / "dicom"

    @property
    def database_path(self) -> Path:
        return self.base_output_dir / "colpocap.sqlite3"


@dataclass(frozen=True)
class Settings:
    local_ae_title: str
    worklist: DicomEndpointConfig
    pacs: DicomEndpointConfig
    video: VideoConfig
    institution: InstitutionConfig
    storage: StorageConfig
    config_path: Path
    project_root: Path

    @property
    def log_path(self) -> Path:
        return self.project_root / "logs" / "app.log"

    def prepare_directories(self) -> None:
        """Create only application-owned runtime directories."""
        for directory in (
            self.storage.base_output_dir,
            self.storage.videos_dir,
            self.storage.snapshots_dir,
            self.storage.dicom_dir,
            self.log_path.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def save_runtime_settings(
    current: Settings,
    *,
    local_ae_title: str,
    worklist: DicomEndpointConfig,
    pacs: DicomEndpointConfig,
    video: VideoConfig,
) -> Settings:
    """Persist editable connection/video settings and return validated settings.

    Institution and storage values are intentionally preserved: this screen is
    for operational connectivity and capture setup, not for relocating the
    clinical archive while the application is running.
    """
    try:
        raw = json.loads(current.config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(
            f"No se pudo actualizar {current.config_path}: {exc}"
        ) from exc
    data = dict(_mapping(raw, "raíz"))
    data["local_ae_title"] = local_ae_title.strip()
    data["worklist"] = {
        "ae_title": worklist.ae_title.strip(),
        "host": worklist.host.strip(),
        "port": worklist.port,
    }
    data["pacs"] = {
        "ae_title": pacs.ae_title.strip(),
        "host": pacs.host.strip(),
        "port": pacs.port,
    }
    data["video"] = {
        "device_name": video.device_name.strip(),
        "resolution": video.resolution.strip(),
        "fps": video.fps,
        "bitrate": video.bitrate.strip(),
    }

    # Validate through the same loader before replacing the active file.
    temporary = current.config_path.with_suffix(current.config_path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        validated = load_settings(temporary)
        temporary.replace(current.config_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    # Reload using the real path so project-root and log-path semantics stay
    # identical to application startup.
    return load_settings(current.config_path)


def _mapping(value: Any, key: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"La sección '{key}' debe ser un objeto JSON.")
    return value


def _required_text(data: Mapping[str, Any], key: str, section: str = "raíz") -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(
            f"Falta el texto obligatorio '{section}.{key}' en la configuración."
        )
    return value.strip()


def _endpoint(data: Mapping[str, Any], section: str) -> DicomEndpointConfig:
    raw = _mapping(data.get(section), section)
    port = raw.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ConfigurationError(f"'{section}.port' debe ser un entero entre 1 y 65535.")
    ae_title = _required_text(raw, "ae_title", section)
    if len(ae_title) > 16:
        raise ConfigurationError(f"'{section}.ae_title' no puede superar 16 caracteres.")
    return DicomEndpointConfig(
        ae_title=ae_title,
        host=_required_text(raw, "host", section),
        port=port,
    )


def _normalize_development_worklist(
    endpoint: DicomEndpointConfig,
) -> DicomEndpointConfig:
    """Migrate the legacy endpoint used by the bundled local MWL server.

    Older installations could retain port 11111 in settings.json even though
    the development server has always been launched on 11112. Keep custom and
    remote Worklist endpoints untouched.
    """
    is_bundled_local_server = (
        endpoint.ae_title.upper() == DEVELOPMENT_WORKLIST_AE_TITLE
        and endpoint.host.strip().lower() in LOOPBACK_HOSTS
        and endpoint.port == LEGACY_DEVELOPMENT_WORKLIST_PORT
    )
    if not is_bundled_local_server:
        return endpoint
    return DicomEndpointConfig(
        ae_title=endpoint.ae_title,
        host=endpoint.host,
        port=DEVELOPMENT_WORKLIST_PORT,
    )


def _normalize_legacy_brand(value: str) -> str:
    return APPLICATION_NAME if value.casefold() == LEGACY_APPLICATION_NAME.casefold() else value


def load_settings(path: str | Path | None = None) -> Settings:
    """Load settings from JSON and fail with a user-facing, actionable message."""
    default_path = Path(__file__).resolve().parent.parent / "config" / "settings.json"
    config_path = Path(path).expanduser().resolve() if path else default_path
    if not config_path.is_file():
        raise ConfigurationError(
            f"No existe el archivo de configuración: {config_path}. "
            "Copie config/settings.example.json como config/settings.json y edítelo."
        )

    try:
        raw_data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"JSON inválido en {config_path}, línea {exc.lineno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise ConfigurationError(f"No se pudo leer {config_path}: {exc}") from exc

    data = _mapping(raw_data, "raíz")
    local_ae_title = _required_text(data, "local_ae_title")
    if len(local_ae_title) > 16:
        raise ConfigurationError("'local_ae_title' no puede superar 16 caracteres.")

    video_raw = _mapping(data.get("video"), "video")
    device_name = video_raw.get("device_name")
    if not isinstance(device_name, str):
        raise ConfigurationError("'video.device_name' debe ser texto (puede estar vacío).")
    resolution = _required_text(video_raw, "resolution", "video")
    if not re.fullmatch(r"\d{2,5}x\d{2,5}", resolution):
        raise ConfigurationError("'video.resolution' debe tener formato ANCHOxALTO.")
    fps = video_raw.get("fps")
    if not isinstance(fps, int) or isinstance(fps, bool) or fps <= 0:
        raise ConfigurationError("'video.fps' debe ser un entero positivo.")

    institution_raw = _mapping(data.get("institution"), "institution")
    storage_raw = _mapping(data.get("storage"), "storage")
    configured_output = Path(_required_text(storage_raw, "base_output_dir", "storage"))
    project_root = (
        config_path.parent.parent
        if config_path.parent.name.lower() == "config"
        else config_path.parent
    )
    output_dir = (
        configured_output
        if configured_output.is_absolute()
        else (project_root / configured_output).resolve()
    )

    return Settings(
        local_ae_title=local_ae_title,
        worklist=_normalize_development_worklist(_endpoint(data, "worklist")),
        pacs=_endpoint(data, "pacs"),
        video=VideoConfig(
            device_name=device_name.strip(),
            resolution=resolution,
            fps=fps,
            bitrate=_required_text(video_raw, "bitrate", "video"),
        ),
        institution=InstitutionConfig(
            name=_required_text(institution_raw, "name", "institution"),
            station_name=_required_text(institution_raw, "station_name", "institution"),
            manufacturer=_normalize_legacy_brand(
                _required_text(institution_raw, "manufacturer", "institution")
            ),
            manufacturer_model_name=_normalize_legacy_brand(
                _required_text(
                    institution_raw, "manufacturer_model_name", "institution"
                )
            ),
            software_version=_required_text(
                institution_raw, "software_version", "institution"
            ),
        ),
        storage=StorageConfig(base_output_dir=output_dir),
        config_path=config_path,
        project_root=project_root,
    )
