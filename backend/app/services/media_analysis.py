"""Lightweight, deterministic image analysis primitives for VerityX."""

from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from PIL.ExifTags import TAGS

EXIF_FIELDS = {
    "Make",
    "Model",
    "Software",
    "Orientation",
    "DateTime",
    "DateTimeOriginal",
    "DateTimeDigitized",
}


def extract_image_metadata(file_path: Path) -> dict[str, Any]:
    """Extract basic image properties and a conservative EXIF allowlist.

    GPS coordinates and arbitrary EXIF fields are intentionally not returned.
    The source file is never modified.
    """
    try:
        with Image.open(file_path) as image:
            image.load()
            exif_values: dict[str, Any] = {}
            exif = image.getexif()
            for tag_id, value in exif.items():
                tag_name = TAGS.get(tag_id, str(tag_id))
                if tag_name not in EXIF_FIELDS:
                    continue
                if isinstance(value, bytes):
                    value = value.decode("utf-8", errors="replace")
                if isinstance(value, (str, int, float, bool)):
                    exif_values[tag_name] = value
                else:
                    exif_values[tag_name] = str(value)[:256]

            return {
                "check": "image_metadata",
                "metadata_schema_version": 1,
                "media_type": "image",
                "format": image.format,
                "width": image.width,
                "height": image.height,
                "mode": image.mode,
                "has_exif": bool(exif),
                "exif": exif_values,
            }
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Stored file is not a safely readable image") from exc


def compute_difference_hash(file_path: Path) -> dict[str, Any]:
    """Compute a 64-bit difference hash (dHash) for coarse image similarity.

    This is a similarity fingerprint, not a cryptographic integrity hash.
    """
    try:
        with Image.open(file_path) as image:
            image.load()
            pixels = list(image.convert("L").resize((9, 8)).get_flattened_data())
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Stored file is not a safely readable image") from exc

    bits = 0
    for row in range(8):
        row_offset = row * 9
        for column in range(8):
            bits = (bits << 1) | int(
                pixels[row_offset + column] > pixels[row_offset + column + 1]
            )

    return {
        "check": "difference_hash",
        "algorithm": "dhash-64-v1",
        "hash": f"{bits:016x}",
        "bit_length": 64,
        "interpretation": (
            "Similarity fingerprint only; not proof of identity or manipulation."
        ),
    }
