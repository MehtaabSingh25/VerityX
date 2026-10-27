import pytest

from app.services.ai_detection import interpret_predictions


def test_ai_label_maps_to_likely_ai_generated():
    result = interpret_predictions(
        [{"label": "artificial", "score": 0.93}, {"label": "human", "score": 0.07}],
        model_id="test-model",
    )
    assert result["classification"] == "likely_ai_generated"
    assert result["ai_score"] == 0.93
    assert result["score_is_calibrated_probability"] is False


def test_human_label_maps_to_likely_not_ai_generated():
    result = interpret_predictions(
        [{"label": "human", "score": 0.91}, {"label": "artificial", "score": 0.09}],
        model_id="test-model",
    )
    assert result["classification"] == "likely_not_ai_generated"
    assert result["ai_score"] == 0.09


def test_unknown_labels_remain_inconclusive():
    result = interpret_predictions(
        [{"label": "LABEL_0", "score": 0.99}], model_id="test-model"
    )
    assert result["classification"] == "inconclusive"
    assert result["ai_score"] is None


def test_threshold_must_be_valid():
    with pytest.raises(ValueError):
        interpret_predictions([], model_id="test-model", threshold=0.5)


def test_negated_label_is_not_treated_as_ai():
    result = interpret_predictions(
        [{"label": "not_ai_generated", "score": 0.95}, {"label": "ai_generated", "score": 0.05}],
        model_id="test-model",
    )
    assert result["classification"] == "likely_not_ai_generated"
    assert result["ai_score"] == 0.05
    assert result["model_confidence"] == 0.95


def test_human_only_label_is_inverted():
    result = interpret_predictions([{"label": "human", "score": 0.2}], model_id="test-model")
    assert result["ai_score"] == 0.8
    assert result["classification"] == "likely_ai_generated"


def test_inconclusive_has_no_confidence():
    result = interpret_predictions(
        [{"label": "artificial", "score": 0.6}, {"label": "human", "score": 0.4}],
        model_id="test-model",
    )
    assert result["classification"] == "inconclusive"
    assert result["model_confidence"] is None


def test_inconsistent_labels_are_inconclusive():
    result = interpret_predictions(
        [{"label": "artificial", "score": 0.9}, {"label": "human", "score": 0.9}],
        model_id="test-model",
    )
    assert result["classification"] == "inconclusive"
    assert result["ai_score"] is None
    assert result["note"]


def test_model_failure_is_reported_as_runtime_error(tmp_path, monkeypatch):
    from PIL import Image

    from app.services import ai_detection

    path = tmp_path / "a.png"
    Image.new("RGB", (128, 128)).save(path)

    def boom(_model_id):
        raise OSError("offline")

    monkeypatch.setattr(ai_detection, "_load_classifier", boom)
    with pytest.raises(RuntimeError, match="No AI detector model"):
        ai_detection.detect_ai_image(path)


def test_non_image_file_is_rejected(tmp_path):
    from app.services.ai_detection import detect_ai_image

    path = tmp_path / "x.png"
    path.write_bytes(b"not an image")
    with pytest.raises(ValueError):
        detect_ai_image(path)


def _png(tmp_path, size=(128, 128)):
    from PIL import Image

    path = tmp_path / "i.png"
    Image.new("RGB", size, (90, 120, 200)).save(path)
    return path


def _fake_loader(table):
    """table: model_id -> list of predictions, or an Exception to raise."""
    def load(model_id):
        value = table[model_id]

        def classify(_image, top_k=5):
            if isinstance(value, Exception):
                raise value
            return value

        return classify

    return load


def test_ensemble_agreement_gives_decisive_result(tmp_path, monkeypatch):
    from app.services import ai_detection as ad

    monkeypatch.setenv("VERITYX_AI_DETECTOR_MODELS", "a,b")
    ai = [{"label": "artificial", "score": 0.9}, {"label": "human", "score": 0.1}]
    ai2 = [{"label": "AI-generated", "score": 0.8}, {"label": "human", "score": 0.2}]
    monkeypatch.setattr(ad, "_load_classifier", _fake_loader({"a": ai, "b": ai2}))
    result = ad.detect_ai_image(_png(tmp_path))
    assert result["classification"] == "likely_ai_generated"
    assert result["agreement"] == "agree"
    assert result["model_confidence"] == 0.8  # weakest model, not the mean
    assert result["ai_score"] == 0.85
    assert len(result["models"]) == 2


def test_ensemble_disagreement_is_inconclusive(tmp_path, monkeypatch):
    from app.services import ai_detection as ad

    monkeypatch.setenv("VERITYX_AI_DETECTOR_MODELS", "a,b")
    ai = [{"label": "artificial", "score": 0.95}, {"label": "human", "score": 0.05}]
    real = [{"label": "human", "score": 0.95}, {"label": "AI-generated", "score": 0.05}]
    monkeypatch.setattr(ad, "_load_classifier", _fake_loader({"a": ai, "b": real}))
    result = ad.detect_ai_image(_png(tmp_path))
    assert result["classification"] == "inconclusive"
    assert result["model_confidence"] is None
    assert "disagreed" in result["note"]


def test_real_image_with_both_models_agreeing(tmp_path, monkeypatch):
    from app.services import ai_detection as ad

    monkeypatch.setenv("VERITYX_AI_DETECTOR_MODELS", "a,b")
    real = [{"label": "human", "score": 0.92}, {"label": "artificial", "score": 0.08}]
    real2 = [{"label": "hum", "score": 0.85}, {"label": "ai", "score": 0.15}]
    monkeypatch.setattr(ad, "_load_classifier", _fake_loader({"a": real, "b": real2}))
    result = ad.detect_ai_image(_png(tmp_path))
    assert result["classification"] == "likely_not_ai_generated"
    assert result["model_confidence"] == 0.85
    assert result["score_is_calibrated_probability"] is False


def test_one_failed_model_is_reported_not_hidden(tmp_path, monkeypatch):
    from app.services import ai_detection as ad

    monkeypatch.setenv("VERITYX_AI_DETECTOR_MODELS", "a,b")
    ai = [{"label": "artificial", "score": 0.9}, {"label": "human", "score": 0.1}]
    monkeypatch.setattr(ad, "_load_classifier", _fake_loader({"a": ai, "b": OSError("offline")}))
    result = ad.detect_ai_image(_png(tmp_path))
    assert result["models_failed"] == [{"model_id": "b", "error": "OSError"}]
    assert result["agreement"] == "single_model"
    assert "failed" in result["note"]


def test_tiny_image_is_inconclusive_without_running_models(tmp_path, monkeypatch):
    from app.services import ai_detection as ad

    def must_not_run(_model_id):
        raise AssertionError("models must not run on tiny images")

    monkeypatch.setattr(ad, "_load_classifier", must_not_run)
    result = ad.detect_ai_image(_png(tmp_path, (32, 32)))
    assert result["classification"] == "inconclusive"
    assert result["ai_score"] is None
    assert "smaller than" in result["note"]


def test_default_models_and_licences_are_declared():
    from app.services import ai_detection as ad

    assert len(ad.DEFAULT_MODEL_IDS) == 2
    assert all(m in ad.MODEL_LICENSES for m in ad.DEFAULT_MODEL_IDS)
