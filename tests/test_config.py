import json
from pathlib import Path

from app.config import load_settings


def _settings_payload(worklist_port: int) -> dict[str, object]:
    return {
        "local_ae_title": "COLPOCAP_MVP",
        "worklist": {
            "ae_title": "COLPOCAP_WL",
            "host": "127.0.0.1",
            "port": worklist_port,
        },
        "pacs": {
            "ae_title": "ORTHANC",
            "host": "127.0.0.1",
            "port": 4242,
        },
        "video": {
            "device_name": "",
            "resolution": "1920x1080",
            "fps": 30,
            "bitrate": "8M",
        },
        "institution": {
            "name": "Institución",
            "station_name": "ELECTROCAP",
            "manufacturer": "ECAP",
            "manufacturer_model_name": "ECAP",
            "software_version": "1.0",
        },
        "storage": {"base_output_dir": "output"},
    }


def _write_settings(tmp_path: Path, payload: dict[str, object]) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    path = config_dir / "settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_legacy_bundled_worklist_port_is_migrated(tmp_path: Path) -> None:
    path = _write_settings(tmp_path, _settings_payload(worklist_port=11111))

    settings = load_settings(path)

    assert settings.worklist.port == 11112


def test_custom_worklist_endpoint_is_not_migrated(tmp_path: Path) -> None:
    payload = _settings_payload(worklist_port=11111)
    worklist = payload["worklist"]
    assert isinstance(worklist, dict)
    worklist["host"] = "10.1.2.3"
    path = _write_settings(tmp_path, payload)

    settings = load_settings(path)

    assert settings.worklist.port == 11111


def test_legacy_brand_in_dicom_metadata_is_migrated(tmp_path: Path) -> None:
    payload = _settings_payload(worklist_port=11112)
    institution = payload["institution"]
    assert isinstance(institution, dict)
    institution["manufacturer"] = "ElectroCap"
    institution["manufacturer_model_name"] = "ElectroCap"
    path = _write_settings(tmp_path, payload)

    settings = load_settings(path)

    assert settings.institution.manufacturer == "ECAP"
    assert settings.institution.manufacturer_model_name == "ECAP"
