import pytest

from app.services.ai_detection import MODEL_ID, detect_ai_image


def _png(tmp_path, size=(128, 128)):
    from PIL import Image

    path = tmp_path / "i.png"
    Image.new("RGB", size, (90, 120, 200)).save(path)
    return path


def test_smaug_score_above_threshold_is_ai_generated(tmp_path, monkeypatch):
    from app.services import ai_detection as ad

    monkeypatch.setenv("VERITYX_AI_DETECTION_THRESHOLD", "0.5")
    monkeypatch.setattr(ad, "_load_detector", lambda: (lambda image: 0.91))
    result = detect_ai_image(_png(tmp_path))

    assert result["model_id"] == MODEL_ID
    assert result["classification"] == "likely_ai_generated"
    assert result["ai_score"] == 0.91
    assert result["model_confidence"] == 0.91
    assert result["score_is_calibrated_probability"] is False
    assert result["model_license"] == "Apache-2.0"


def test_smaug_score_below_threshold_is_likely_real(tmp_path, monkeypatch):
    from app.services import ai_detection as ad

    monkeypatch.setenv("VERITYX_AI_DETECTION_THRESHOLD", "0.5")
    monkeypatch.setattr(ad, "_load_detector", lambda: (lambda image: 0.12))
    result = detect_ai_image(_png(tmp_path))

    assert result["classification"] == "likely_not_ai_generated"
    assert result["ai_score"] == 0.12
    assert result["model_confidence"] == 0.88


def test_threshold_must_be_between_zero_and_one(tmp_path, monkeypatch):
    from app.services import ai_detection as ad

    monkeypatch.setenv("VERITYX_AI_DETECTION_THRESHOLD", "1.0")
    with pytest.raises(ValueError, match="greater than 0 and less than 1"):
        detect_ai_image(_png(tmp_path))


def test_invalid_model_score_fails_closed(tmp_path, monkeypatch):
    from app.services import ai_detection as ad

    monkeypatch.setattr(ad, "_load_detector", lambda: (lambda image: float("nan")))
    with pytest.raises(RuntimeError, match="invalid score"):
        detect_ai_image(_png(tmp_path))


def test_detector_inference_failure_is_reported(tmp_path, monkeypatch):
    from app.services import ai_detection as ad

    def fail(image):
        raise OSError("model failure")

    monkeypatch.setattr(ad, "_load_detector", lambda: fail)
    with pytest.raises(RuntimeError, match="inference failed"):
        detect_ai_image(_png(tmp_path))


def test_non_image_file_is_rejected(tmp_path):
    path = tmp_path / "x.png"
    path.write_bytes(b"not an image")
    with pytest.raises(ValueError, match="safely readable image"):
        detect_ai_image(path)


def test_tiny_image_is_inconclusive_without_loading_model(tmp_path, monkeypatch):
    from app.services import ai_detection as ad

    def must_not_run():
        raise AssertionError("model must not run for tiny image")

    monkeypatch.setattr(ad, "_load_detector", must_not_run)
    result = detect_ai_image(_png(tmp_path, (32, 32)))

    assert result["classification"] == "inconclusive"
    assert result["ai_score"] is None
    assert "smaller than" in result["note"]


def test_python_scalar_like_score_is_supported(tmp_path, monkeypatch):
    from app.services import ai_detection as ad

    class Score:
        def item(self):
            return 0.73

    monkeypatch.setattr(ad, "_load_detector", lambda: (lambda image: Score()))
    result = detect_ai_image(_png(tmp_path))
    assert result["ai_score"] == 0.73
    assert result["classification"] == "likely_ai_generated"
