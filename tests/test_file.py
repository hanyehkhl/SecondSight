import io

import numpy as np
from PIL import Image

from app.modules.file.dicom import dicom_to_png, is_dicom
from tests.conftest import API, make_png


def make_dicom() -> bytes:
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.PatientName = "Doe^Jane"
    ds.PatientID = "123456"
    ds.Modality = "CT"
    ds.BodyPartExamined = "CHEST"
    ds.Rows, ds.Columns = 32, 32
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit = 16, 16, 15
    ds.PixelRepresentation = 1
    ds.RescaleIntercept, ds.RescaleSlope = -1024, 1
    ds.WindowCenter, ds.WindowWidth = 40, 400
    ds.PixelData = (np.arange(32 * 32, dtype=np.int16).reshape(32, 32) * 2).tobytes()

    buffer = io.BytesIO()
    ds.save_as(buffer, enforce_file_format=True)
    return buffer.getvalue()


def test_dicom_conversion_strips_phi():
    data = make_dicom()
    assert is_dicom(data)
    png, metadata = dicom_to_png(data)
    image = Image.open(io.BytesIO(png))
    assert image.size == (32, 32)
    assert metadata["Modality"] == "CT"
    assert metadata["BodyPartExamined"] == "CHEST"
    assert "PatientName" not in metadata and "PatientID" not in metadata


async def test_dicom_upload_sets_modality(client, auth_headers):
    response = await client.post(
        f"{API}/files", headers=auth_headers, files={"file": ("scan.dcm", make_dicom(), "application/dicom")}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "dicom"
    assert body["modality"] == "CT"
    assert "Doe" not in response.text

    preview = await client.get(f"{API}/files/{body['id']}/preview", headers=auth_headers)
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"


async def test_files_are_encrypted_at_rest(client, auth_headers, storage_root):
    png = make_png()
    response = await client.post(f"{API}/files", headers=auth_headers, files={"file": ("a.png", png, "image/png")})
    file_id = response.json()["id"]
    stored = next(storage_root.rglob(f"{file_id}/original")).read_bytes()
    assert stored != png
    assert b"PNG" not in stored[:16]
