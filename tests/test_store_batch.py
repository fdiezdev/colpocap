from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from app.config import DicomEndpointConfig, InstitutionConfig
from app.dicom.dicom_builder import DicomBuilder
from app.dicom.store_client import StoreClient


def _metadata() -> dict[str, str]:
    return {
        "patient_name": "LOTE^PRUEBA",
        "patient_id": "BATCH-1",
        "accession_number": "BATCH-ACC",
        "study_instance_uid": "1.2.826.0.1.3680043.8.498.300",
    }


def test_store_many_uses_one_association_for_all_instances(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (8, 8), color="orange").save(source)
    builder = DicomBuilder(
        InstitutionConfig("Test", "COLPO", "Custom", "MVP", "0.1")
    )
    paths = []
    for instance_number in (1, 2):
        path = tmp_path / f"image-{instance_number}.dcm"
        builder.create_vl_endoscopic_image(
            snapshot_path=source,
            output_path=path,
            metadata=_metadata(),
            instance_number=instance_number,
        )
        paths.append(path)

    class FakeAssociation:
        is_established = True

        def __init__(self) -> None:
            self.sent = []
            self.released = False

        def send_c_store(self, dataset):
            self.sent.append(str(dataset.SOPInstanceUID))
            return SimpleNamespace(Status=0x0000)

        def release(self) -> None:
            self.released = True

    class FakeAE:
        instances = []

        def __init__(self, ae_title: str) -> None:
            self.ae_title = ae_title
            self.contexts = []
            self.association = FakeAssociation()
            self.associate_calls = 0
            self.__class__.instances.append(self)

        def add_requested_context(self, context: str) -> None:
            self.contexts.append(str(context))

        def associate(self, *_args, **_kwargs):
            self.associate_calls += 1
            return self.association

    monkeypatch.setattr("app.dicom.store_client.AE", FakeAE)
    client = StoreClient(
        "COLPOCAP", DicomEndpointConfig("ORTHANC", "127.0.0.1", 4242)
    )
    results = client.store_many(paths)

    fake_ae = FakeAE.instances[0]
    assert fake_ae.associate_calls == 1
    assert len(fake_ae.association.sent) == 2
    assert fake_ae.association.released
    assert all(result.success for result in results)

