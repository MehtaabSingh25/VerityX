"""Bounded, lightweight video inspection using OpenCV.

These functions inspect media; they do not modify the original evidence file.
OpenCV's reported metadata can be incomplete or approximate depending on codec.
"""

from pathlib import Path
from typing import Any
import math

MAX_SAMPLED_FRAMES = 12


def _open_capture(file_path: Path):
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise RuntimeError(
            "Video analysis dependency missing; install requirements-async.txt"
        ) from exc

    capture = cv2.VideoCapture(str(file_path))
    if not capture.isOpened():
        capture.release()
        raise ValueError("Stored file is not a readable video")
    return cv2, capture


def _stream_properties(cv2: Any, capture: Any) -> dict[str, Any]:
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    frame_count_value = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps_value = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    frame_count = max(0, int(frame_count_value)) if math.isfinite(frame_count_value) else 0
    fps = fps_value if math.isfinite(fps_value) and fps_value > 0 else None
    duration = frame_count / fps if fps and frame_count else None
    return {
        "width": width or None,
        "height": height or None,
        "fps": round(fps, 4) if fps else None,
        "frame_count": frame_count or None,
        "duration_seconds_estimate": round(duration, 3) if duration else None,
    }


def extract_video_metadata(file_path: Path) -> dict[str, Any]:
    """Return basic video properties reported by OpenCV."""
    cv2, capture = _open_capture(file_path)
    try:
        properties = _stream_properties(cv2, capture)
        if not properties["width"] or not properties["height"]:
            raise ValueError("Video stream did not report valid frame dimensions")
        return {
            "check": "video_metadata",
            "metadata_schema_version": 1,
            "media_type": "video",
            "metadata_provider": "opencv",
            **properties,
            "limitations": [
                "Codec and container details may be incomplete.",
                "Duration is estimated from reported frame count and FPS.",
            ],
        }
    finally:
        capture.release()


def _dhash_frame(cv2: Any, frame: Any) -> str:
    grayscale = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(grayscale, (9, 8), interpolation=cv2.INTER_AREA)
    bits = 0
    for row in range(8):
        for column in range(8):
            bits = (bits << 1) | int(resized[row, column] > resized[row, column + 1])
    return f"{bits:016x}"


def sample_video_frame_fingerprints(
    file_path: Path, max_frames: int = MAX_SAMPLED_FRAMES
) -> dict[str, Any]:
    """Sample evenly spaced frames and return frame-indexed 64-bit dHashes."""
    if not 1 <= max_frames <= MAX_SAMPLED_FRAMES:
        raise ValueError(f"max_frames must be between 1 and {MAX_SAMPLED_FRAMES}")

    cv2, capture = _open_capture(file_path)
    try:
        properties = _stream_properties(cv2, capture)
        frame_count = properties["frame_count"] or 0
        fps = properties["fps"]
        if frame_count < 1:
            raise ValueError("Video stream did not report a usable frame count")

        sample_count = min(frame_count, max_frames)
        if sample_count == 1:
            indices = [0]
        else:
            indices = sorted({round(i * (frame_count - 1) / (sample_count - 1)) for i in range(sample_count)})

        fingerprints = []
        for frame_index in indices:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            timestamp = round(frame_index / fps, 3) if fps else None
            fingerprints.append({
                "frame_index": frame_index,
                "timestamp_seconds_estimate": timestamp,
                "algorithm": "dhash-64-v1",
                "hash": _dhash_frame(cv2, frame),
            })

        if not fingerprints:
            raise ValueError("Could not decode any sampled video frames")

        return {
            "check": "video_frame_fingerprints",
            "algorithm": "dhash-64-v1",
            "requested_sample_count": len(indices),
            "decoded_sample_count": len(fingerprints),
            "frame_count_reported": frame_count,
            "fingerprints": fingerprints,
            "interpretation": (
                "Sampled-frame similarity cues only; not proof of identity, authenticity, or manipulation."
            ),
        }
    finally:
        capture.release()
