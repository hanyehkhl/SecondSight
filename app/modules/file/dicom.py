"""DICOM handling: render pixel data to PNG and extract non-identifying metadata."""

import io
from collections.abc import Sequence
from typing import Any

import numpy as np
from PIL import Image

# Only technical, non-identifying tags are kept. Patient/physician/institution tags are never read.
SAFE_TAGS = (
    "Modality",
    "BodyPartExamined",
    "StudyDescription",
    "SeriesDescription",
    "ViewPosition",
    "PhotometricInterpretation",
    "Rows",
    "Columns",
    "NumberOfFrames",
    "SliceThickness",
    "PixelSpacing",
    "Manufacturer",
)


class DicomError(ValueError):
    pass


def is_dicom(data: bytes) -> bool:
    return len(data) >= 132 and data[128:132] == b"DICM"


def _read(data: bytes):
    import pydicom

    try:
        return pydicom.dcmread(io.BytesIO(data), force=True)
    except Exception as exc:
        raise DicomError(f"Unreadable DICOM file: {exc}") from exc


def _apply_luts(pixels: np.ndarray, ds) -> np.ndarray:
    try:
        from pydicom.pixels import apply_modality_lut, apply_voi_lut
    except ImportError:  # pydicom < 3
        from pydicom.pixel_data_handlers.util import apply_modality_lut, apply_voi_lut

    pixels = apply_modality_lut(pixels, ds)
    if "WindowCenter" in ds or "VOILUTSequence" in ds:
        pixels = apply_voi_lut(pixels, ds)
    return pixels


def _to_uint8(pixels: np.ndarray) -> np.ndarray:
    pixels = pixels.astype(np.float64)
    lo, hi = np.percentile(pixels, (0.5, 99.5))
    if hi <= lo:
        lo, hi = float(pixels.min()), float(pixels.max())
    if hi <= lo:
        return np.zeros(pixels.shape, dtype=np.uint8)
    scaled = np.clip((pixels - lo) / (hi - lo), 0.0, 1.0)
    return (scaled * 255).astype(np.uint8)


def dicom_to_png(data: bytes) -> tuple[bytes, dict[str, Any]]:
    """Return (png_bytes, safe_metadata). Multi-frame series use the middle frame."""
    ds = _read(data)
    try:
        pixels = ds.pixel_array
    except Exception as exc:
        raise DicomError(f"Cannot decode DICOM pixel data: {exc}") from exc

    photometric = str(ds.get("PhotometricInterpretation", "MONOCHROME2"))
    is_color = int(ds.get("SamplesPerPixel", 1) or 1) > 1
    frames = int(ds.get("NumberOfFrames", 1) or 1)
    if frames > 1:
        pixels = pixels[frames // 2]

    if is_color:
        rgb = pixels if pixels.dtype == np.uint8 else _to_uint8(pixels)
        image = Image.fromarray(np.ascontiguousarray(rgb[..., :3]))
    else:
        pixels = _to_uint8(_apply_luts(pixels, ds))
        if photometric == "MONOCHROME1":
            pixels = 255 - pixels
        image = Image.fromarray(pixels).convert("RGB")

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue(), extract_safe_metadata(ds)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_jsonable(v) for v in value]
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    return str(value)


def extract_safe_metadata(ds) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for tag in SAFE_TAGS:
        value = ds.get(tag)
        if value is not None and value != "":
            metadata[tag] = _jsonable(value)
    return metadata
