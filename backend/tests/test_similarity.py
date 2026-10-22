from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.similarity import find_similarity_matches, hamming_distance


def _image(hash_value: str, *, status: str = "completed"):
    media = SimpleNamespace(
        id=uuid4(), original_filename="image.png", mime_type="image/png"
    )
    job = SimpleNamespace(
        analysis_type="perceptual_hash", status=status,
        result={"check": "difference_hash", "hash": hash_value},
    )
    return media, job


def _video(hashes: list[str], *, status: str = "completed"):
    media = SimpleNamespace(
        id=uuid4(), original_filename="clip.mp4", mime_type="video/mp4"
    )
    job = SimpleNamespace(
        analysis_type="video_frame_fingerprints", status=status,
        result={"check": "video_frame_fingerprints", "fingerprints": [
            {"hash": value, "frame_index": index, "timestamp_seconds_estimate": float(index)}
            for index, value in enumerate(hashes)
        ]},
    )
    return media, job


def test_hamming_distance_counts_different_bits():
    assert hamming_distance("0000000000000000", "0000000000000003") == 2


def test_finds_cross_media_match_and_returns_best_frame():
    image = _image("0000000000000000")
    video = _video(["ffffffffffffffff", "0000000000000001"])

    matches = find_similarity_matches([image, video], max_distance=2)

    assert len(matches) == 1
    assert matches[0]["hamming_distance"] == 1
    assert matches[0]["right"]["media_type"] == "video"
    assert matches[0]["right"]["frame_index"] == 1
    assert matches[0]["similarity_score"] == pytest.approx(0.9844)


def test_ignores_non_completed_jobs_and_distant_matches():
    image = _image("0000000000000000")
    queued_video = _video(["0000000000000000"], status="queued")
    distant_image = _image("ffffffffffffffff")

    assert find_similarity_matches([image, queued_video], max_distance=64) == []
    assert find_similarity_matches([image, distant_image], max_distance=10) == []


def test_rejects_invalid_distance():
    with pytest.raises(ValueError):
        find_similarity_matches([], max_distance=65)
