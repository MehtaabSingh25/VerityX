"""Local AI-image detection using an ensemble of Hugging Face classifiers.

Independently trained detectors must agree before a decisive verdict is
reported; disagreement is reported as inconclusive. Output is a forensic signal,
never proof, and scores are not calibrated probabilities.
"""

from functools import lru_cache
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

# Ensemble default: the SDXL specialist plus a general ViT human-vs-AI detector.
DEFAULT_MODEL_IDS = ("Organika/sdxl-detector", "capcheck/ai-human-generated-image-detection")
DEFAULT_MODEL_ID = DEFAULT_MODEL_IDS[0]  # kept for backwards compatibility
MIN_IMAGE_SIDE = 64
# Licences as stated on the model cards; unknown models must be reviewed by the operator.
MODEL_LICENSES = {
    "Organika/sdxl-detector": "CC BY-NC 3.0; non-commercial use only",
    "capcheck/ai-human-generated-image-detection": "Apache 2.0",
}
MODEL_LICENSE = "; ".join(f"{m}: {MODEL_LICENSES[m]}" for m in DEFAULT_MODEL_IDS)
MODEL_ATTRIBUTION = (
    "Organika/sdxl-detector (fine-tuned from umm-maybe/AI-image-detector); "
    "capcheck/ai-human-generated-image-detection (ViT-Base fine-tune)"
)


@lru_cache(maxsize=4)
def _load_classifier(model_id: str):
    """Load the model once per worker process; inference runs locally on CPU."""
    try:
        from transformers import pipeline
    except ImportError as exc:  # pragma: no cover - depends on optional runtime setup
        raise RuntimeError(
            "AI image detection dependencies are missing. Install backend/requirements-async.txt."
        ) from exc

    return pipeline("image-classification", model=model_id, device=-1)


_AI_EXACT = {
    "artificial", "ai", "ai-image", "ai-art", "ai-generated", "ai-generated-image",
    "fake", "synthetic", "generated", "deepfake", "sdxl",
}
_REAL_PREFIXES = ("hum", "human", "real", "natural", "authentic", "genuine", "photograph", "photo", "not-", "non-")


def _label_kind(label: str) -> str | None:
    """Return "ai", "real" or None. Negated labels ("not-ai-generated") are real."""
    key = label.casefold().replace("_", "-").replace(" ", "-")
    if key.startswith(_REAL_PREFIXES):
        return "real"
    if key in _AI_EXACT or any(t in key for t in ("artificial", "synthetic", "generated", "fake")):
        return "ai"
    return None


def interpret_predictions(
    predictions: list[dict[str, Any]], *, model_id: str, threshold: float = 0.75
) -> dict[str, Any]:
    """Convert model labels into a conservative, explainable result."""
    if not 0.5 < threshold < 1.0:
        raise ValueError("threshold must be greater than 0.5 and less than 1.0")

    normalized = []
    ai_label_score: float | None = None
    real_label_score: float | None = None
    for prediction in predictions:
        label = str(prediction.get("label", "")).strip()
        try:
            score = float(prediction.get("score"))
        except (TypeError, ValueError):
            continue
        if not label or not 0.0 <= score <= 1.0:
            continue
        normalized.append({"label": label, "score": round(score, 6)})
        kind = _label_kind(label)
        if kind == "ai":
            ai_label_score = max(score, ai_label_score or 0.0)
        elif kind == "real":
            real_label_score = max(score, real_label_score or 0.0)

    # The AI-label score is authoritative; a real-label score is only used when no
    # AI label was returned. If both exist they must roughly sum to 1 (two-class
    # softmax), otherwise the label mapping is not trustworthy.
    note = None
    if ai_label_score is not None:
        ai_score: float | None = ai_label_score
        if real_label_score is not None and abs(ai_label_score + real_label_score - 1.0) > 0.1:
            ai_score = None
            note = "Model labels were inconsistent; no assessment was made."
    elif real_label_score is not None:
        ai_score = 1.0 - real_label_score
    else:
        ai_score = None
        note = "Model labels were not recognised; no assessment was made."

    confidence = None
    if ai_score is None:
        classification = "inconclusive"
    elif ai_score >= threshold:
        classification = "likely_ai_generated"
        confidence = ai_score
    elif ai_score <= 1.0 - threshold:
        classification = "likely_not_ai_generated"
        confidence = 1.0 - ai_score
    else:
        classification = "inconclusive"

    return {
        "check": "ai_image_detection",
        "model_id": model_id,
        "model_license": MODEL_LICENSES.get(model_id, "unknown - review before use"),
        "model_attribution": MODEL_ATTRIBUTION,
        "classification": classification,
        "ai_score": round(ai_score, 6) if ai_score is not None else None,
        # Only set for decisive results: the model's score for the winning class.
        "model_confidence": round(confidence, 6) if confidence is not None else None,
        "threshold": threshold,
        "score_is_calibrated_probability": False,
        "predictions": normalized,
        "note": note,
        "limitations": [
            "The default detector is primarily tuned for SDXL-generated images and may miss other generators.",
            "Image manipulation, compression, resizing, or domain shifts can affect results.",
            "This score is a model signal, not proof of origin or authenticity.",
            "The default model is licensed for non-commercial use only; review its license before commercial deployment.",
        ],
    }


def _model_ids() -> list[str]:
    raw = os.getenv("VERITYX_AI_DETECTOR_MODELS") or os.getenv("VERITYX_AI_DETECTOR_MODEL") or ""
    ids = [m.strip() for m in raw.split(",") if m.strip()] or list(DEFAULT_MODEL_IDS)
    return list(dict.fromkeys(ids))


def combine_results(per_model: list[dict[str, Any]], failures: list[dict[str, str]]) -> dict[str, Any]:
    """Merge per-model results. A decisive verdict needs every model to agree."""
    classes = [r["classification"] for r in per_model]
    scores = [r["ai_score"] for r in per_model if r["ai_score"] is not None]
    if classes and all(c == "likely_ai_generated" for c in classes):
        classification = "likely_ai_generated"
    elif classes and all(c == "likely_not_ai_generated" for c in classes):
        classification = "likely_not_ai_generated"
    else:
        classification = "inconclusive"
    decisive = classification != "inconclusive"
    notes = []
    if len(per_model) == 1:
        agreement = "single_model"
        notes.append("Only one model produced a result, so no cross-check was possible.")
    else:
        agreement = "agree" if decisive else "disagree_or_inconclusive"
    if failures:
        notes.append("Some configured models failed: " + "; ".join(f["model_id"] for f in failures))
    if classification == "inconclusive" and len(per_model) > 1 and any(c != "inconclusive" for c in classes):
        notes.append("Models disagreed or were not decisive; no verdict is offered.")
    ids = [r["model_id"] for r in per_model]
    return {
        "check": "ai_image_detection",
        "model_id": ", ".join(ids),
        "model_license": "; ".join(f"{i}: {MODEL_LICENSES.get(i, 'unknown - review before use')}" for i in ids),
        "model_attribution": MODEL_ATTRIBUTION,
        "classification": classification,
        # Mean of per-model AI-label scores; a signal, not a probability.
        "ai_score": round(sum(scores) / len(scores), 6) if scores else None,
        # Weakest per-model score for the winning class, only for decisive agreement.
        "model_confidence": round(min(r["model_confidence"] for r in per_model), 6) if decisive else None,
        "threshold": per_model[0]["threshold"] if per_model else None,
        "score_is_calibrated_probability": False,
        "agreement": agreement,
        "models": per_model,
        "models_failed": failures,
        "predictions": [p for r in per_model for p in r["predictions"]],
        "note": " ".join(notes) or None,
        "limitations": [
            "No public detector is reliable across all generators; new or unseen generators are often missed.",
            (
                "Real photos that are heavily edited, upscaled or compressed can be flagged, and AI images that "
                "were screenshotted, resized or re-compressed can pass as real. Both error types occur."
            ),
            "The default SDXL detector is specialised; the second model is general-purpose with no published benchmark.",
            "Scores are model signals, not calibrated probabilities, and are not proof of origin or authenticity.",
            "Do not use this result alone for consequential decisions; seek corroborating evidence and human review.",
            "The default ensemble includes a non-commercial (CC BY-NC) model; review licences before commercial use.",
        ],
    }


def detect_ai_image(file_path: Path) -> dict[str, Any]:
    """Run every configured local classifier on a stored image and combine the results."""
    model_ids = _model_ids()
    try:
        with Image.open(file_path) as source:
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Stored file is not a safely readable image") from exc

    try:
        threshold = float(os.getenv("VERITYX_AI_DETECTION_THRESHOLD", "0.75"))
    except ValueError as exc:
        raise ValueError("VERITYX_AI_DETECTION_THRESHOLD must be a number between 0.5 and 1.0") from exc
    if not 0.5 < threshold < 1.0:
        raise ValueError("threshold must be greater than 0.5 and less than 1.0")

    if min(image.size) < MIN_IMAGE_SIDE:
        result = combine_results([], [])
        result.update(
            model_id=", ".join(model_ids),
            note=f"Image is smaller than {MIN_IMAGE_SIDE}px on one side; detectors are unreliable at this size.",
        )
        return result

    per_model: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for model_id in model_ids:
        try:
            predictions = _load_classifier(model_id)(image, top_k=5)
            if not isinstance(predictions, list):
                raise TypeError("unexpected response")
            per_model.append(interpret_predictions(predictions, model_id=model_id, threshold=threshold))
        except Exception as exc:  # noqa: BLE001 - download/offline/inference failures are per model
            failures.append({"model_id": model_id, "error": type(exc).__name__})
    if not per_model:
        raise RuntimeError(
            "No AI detector model could be loaded or run "
            f"({', '.join(model_ids)}); check worker internet access, disk space and model IDs."
        )
    return combine_results(per_model, failures)
