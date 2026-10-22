import hashlib

import pytest

from app.tasks.analysis import compute_integrity_result


def test_integrity_check_matches_expected_hash(tmp_path):
    media = tmp_path / "sample.bin"
    media.write_bytes(b"verityx media sample")
    expected = hashlib.sha256(b"verityx media sample").hexdigest()

    result = compute_integrity_result(media, expected)

    assert result["check"] == "sha256_integrity"
    assert result["matches"] is True
    assert result["expected_sha256"] == expected
    assert result["actual_sha256"] == expected


def test_integrity_check_detects_changed_file(tmp_path):
    media = tmp_path / "sample.bin"
    media.write_bytes(b"changed content")

    result = compute_integrity_result(media, "0" * 64)

    assert result["matches"] is False
    assert result["actual_sha256"] == hashlib.sha256(
        b"changed content"
    ).hexdigest()


def test_integrity_check_reports_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        compute_integrity_result(tmp_path / "missing.bin", "0" * 64)


def test_extract_image_metadata_returns_dimensions_and_safe_exif_fields(tmp_path):
    from PIL import Image

    from app.services.media_analysis import extract_image_metadata

    image_path = tmp_path / "sample.png"
    Image.new("RGB", (23, 17), color=(20, 40, 60)).save(image_path)

    result = extract_image_metadata(image_path)

    assert result["check"] == "image_metadata"
    assert result["metadata_schema_version"] == 1
    assert result["format"] == "PNG"
    assert result["width"] == 23
    assert result["height"] == 17
    assert result["mode"] == "RGB"
    assert result["exif"] == {}


def test_difference_hash_is_stable_and_64_bits(tmp_path):
    from PIL import Image

    from app.services.media_analysis import compute_difference_hash

    image_path = tmp_path / "sample.png"
    Image.new("RGB", (32, 24), color=(120, 120, 120)).save(image_path)

    first = compute_difference_hash(image_path)
    second = compute_difference_hash(image_path)

    assert first == second
    assert first["check"] == "difference_hash"
    assert first["algorithm"] == "dhash-64-v1"
    assert len(first["hash"]) == 16
    assert first["bit_length"] == 64


def test_image_analysis_rejects_non_image_file(tmp_path):
    from app.services.media_analysis import extract_image_metadata

    invalid_path = tmp_path / "not-an-image.jpg"
    invalid_path.write_bytes(b"not an image")

    with pytest.raises(ValueError, match="safely readable image"):
        extract_image_metadata(invalid_path)
