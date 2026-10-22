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
