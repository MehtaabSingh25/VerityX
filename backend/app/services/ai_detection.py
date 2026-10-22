"""Local AI-image detection using a configurable Hugging Face classifier.

The default model is SDXL-focused. Its output is a forensic signal, not proof.
"""

from functools import lru_cache
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

DEFAULT_MODEL_ID = "Organika/sdxl-detector"
MODEL_LICENSE = "CC BY-NC 3.0; non-commercial use only"
MODEL_ATTRIBUTION = (
    "Organika/sdxl-detector, fine-tuned from umm-maybe/AI-image-detector"
)


@lru_cache(maxsize=1)
def _load_classifier(model_id: str):
    """Load the model once per worker process; inference runs locally on CPU."""
    try:
        from transformers import pipeline
    except ImportError as exc:  # pragma: no cover - depends on optional runtime setup
        raise RuntimeError(
            "AI image detection dependencies are missing. Install backend/requirements-async.txt."
        ) from exc

    return pipeline("image-classification", model=model_id, device=-1)


def interpret_predictions(
    predictions: list[dict[str, Any]], *, model_id: str, threshold: float = 0.75
) -> dict[str, Any]:
    """Convert model labels into a conservative, explainable result."""
    if not 0.5 < threshold < 1.0:
        raise ValueError("threshold must be greater than 0.5 and less than 1.0")

    normalized = []
    ai_score = None
    for prediction in predictions:
        label = str(prediction.get("label", "")).strip()
        try:
            score = float(prediction.get("score"))
        except (TypeError, ValueError):
            continue
        if not label or not 0.0 <= score <= 1.0:
            continue
        normalized.append({"label": label, "score": round(score, 6)})
        label_key = label.casefold().replace("_", "-").replace(" ", "-")
        if any(token in label_key for token in ("artificial", "synthetic", "generated", "ai-generated")):
            ai_score = score
        elif label_key in {"fake", "ai", "ai-image", "ai-art"}:
            ai_score = score
        elif label_key in {"human", "real", "natural", "photograph", "photo"} or label_key.startswith("human-"):
            if ai_score is None:
                ai_score = 1.0 - score

    if ai_score is None:
        classification = "inconclusive"
        confidence = None
    elif ai_score >= threshold:
        classification = "likely_ai_generated"
        confidence = max(ai_score, 1.0 - ai_score)
    elif ai_score <= 1.0 - threshold:
        classification = "likely_not_ai_generated"
        confidence = max(ai_score, 1.0 - ai_score)
    else:
        classification = "inconclusive"
        confidence = max(ai_score, 1.0 - ai_score)

    return {
        "check": "ai_image_detection",
        "model_id": model_id,
        "model_license": MODEL_LICENSE,
        "model_attribution": MODEL_ATTRIBUTION,
        "classification": classification,
        "ai_score": round(ai_score, 6) if ai_score is not None else None,
        "model_confidence": round(confidence, 6) if confidence is not None else None,
        "threshold": threshold,
        "score_is_calibrated_probability": False,
        "predictions": normalized,
        "limitations": [
            "The default detector is primarily tuned for SDXL-generated images and may miss other generators.",
            "Image manipulation, compression, resizing, or domain shifts can affect results.",
            "This score is a model signal, not proof of origin or authenticity.",
            "The default model is licensed for non-commercial use only; review its license before commercial deployment.",
        ],
    }


def detect_ai_image(file_path: Path) -> dict[str, Any]:
    """Run local image classification against a stored image file."""
    model_id = os.getenv("VERITYX_AI_DETECTOR_MODEL", DEFAULT_MODEL_ID).strip()
    if not model_id:
        raise ValueError("VERITYX_AI_DETECTOR_MODEL must not be empty")
    try:
        with Image.open(file_path) as source:
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Stored file is not a safely readable image") from exc

    threshold = float(os.getenv("VERITYX_AI_DETECTION_THRESHOLD", "0.75"))
    classifier = _load_classifier(model_id)
    predictions = classifier(image, top_k=5)
    if not isinstance(predictions, list):
        raise RuntimeError("AI detector returned an unexpected response")
    return interpret_predictions(predictions, model_id=model_id, threshold=threshold)
