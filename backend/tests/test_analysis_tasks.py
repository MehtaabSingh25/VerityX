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
