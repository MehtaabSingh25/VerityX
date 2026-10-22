import sys
from types import SimpleNamespace

import numpy as np
import pytest

from app.services import video_analysis


class FakeCapture:
    def __init__(self, _path):
        self.position = 0
        self.released = False

    def isOpened(self):
        return True

    def get(self, property_id):
        values = {
            1: 320,  # width
            2: 240,  # height
            3: 30.0,  # fps
            4: 90,  # frame count
        }
        return values[property_id]

    def set(self, _property_id, frame_index):
        self.position = int(frame_index)
        return True

    def read(self):
        frame = np.full((8, 9, 3), self.position, dtype=np.uint8)
        return True, frame

    def release(self):
        self.released = True


@pytest.fixture
def fake_cv2(monkeypatch):
    module = SimpleNamespace(
        CAP_PROP_FRAME_WIDTH=1,
        CAP_PROP_FRAME_HEIGHT=2,
        CAP_PROP_FPS=3,
        CAP_PROP_FRAME_COUNT=4,
        CAP_PROP_POS_FRAMES=5,
        COLOR_BGR2GRAY=6,
        INTER_AREA=7,
        VideoCapture=FakeCapture,
        cvtColor=lambda frame, _code: frame[:, :, 0],
        resize=lambda frame, size, interpolation=None: np.resize(frame, (size[1], size[0])),
    )
    monkeypatch.setitem(sys.modules, "cv2", module)
    return module


def test_extract_video_metadata_returns_basic_stream_properties(tmp_path, fake_cv2):
    result = video_analysis.extract_video_metadata(tmp_path / "sample.mp4")

    assert result["check"] == "video_metadata"
    assert result["width"] == 320
    assert result["height"] == 240
    assert result["fps"] == 30.0
    assert result["frame_count"] == 90
    assert result["duration_seconds_estimate"] == 3.0


def test_sample_video_fingerprints_is_bounded_and_deterministic(tmp_path, fake_cv2):
    result = video_analysis.sample_video_frame_fingerprints(
        tmp_path / "sample.mp4", max_frames=4
    )

    assert result["check"] == "video_frame_fingerprints"
    assert result["requested_sample_count"] == 4
    assert result["decoded_sample_count"] == 4
    assert [item["frame_index"] for item in result["fingerprints"]] == [0, 30, 59, 89]
    assert all(len(item["hash"]) == 16 for item in result["fingerprints"])


def test_sample_video_fingerprints_rejects_unbounded_sample_count(tmp_path):
    with pytest.raises(ValueError, match="max_frames"):
        video_analysis.sample_video_frame_fingerprints(
            tmp_path / "sample.mp4", max_frames=MAX_FRAMES_PLUS_ONE
        )


MAX_FRAMES_PLUS_ONE = video_analysis.MAX_SAMPLED_FRAMES + 1
