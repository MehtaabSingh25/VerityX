"""Local AI-image detection using Abacus.AI's Smaug image detector.

The model runs inside the Celery worker; image bytes are not sent to a hosted
inference provider. Its score is a model output, not proof of image provenance.
"""

from functools import lru_cache
import importlib
import math
import os
from pathlib import Path
import sys
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

MODEL_ID = "abacusai/Smaug-AI-Image-Detector"
MODEL_LICENSE = "Apache-2.0"
MODEL_ATTRIBUTION = "Smaug-AI-Image-Detector by Abacus.AI; based on EmbeddingGemma-2"
MIN_IMAGE_SIDE = 64
DEFAULT_THRESHOLD = 0.5


@lru_cache(maxsize=1)
def _load_detector():
    """Download/cache the model source and load the detector once per worker."""
    try:
        from huggingface_hub import snapshot_download

        model_path = snapshot_download(repo_id=MODEL_ID)
        # The model repository ships its inference wrapper as Python source.
        # This import follows the model card's documented loading procedure.
        if model_path not in sys.path:
            sys.path.insert(0, model_path)
        module = importlib.import_module("smaug_image_detect")
        detector_class = getattr(module, "SmaugImageDetect")
        return detector_class.from_pretrained(model_path)
    except Exception as exc:
        raise RuntimeError(
            "Could not load Smaug AI image detector. Check worker internet access, "
            "disk space, Hugging Face cache permissions and model dependencies."
        ) from exc


def _threshold() -> float:
    try:
        value = float(os.getenv("VERITYX_AI_DETECTION_THRESHOLD", str(DEFAULT_THRESHOLD)))
    except ValueError as exc:
        raise ValueError("VERITYX_AI_DETECTION_THRESHOLD must be a number between 0 and 1") from exc
    if not math.isfinite(value) or not 0.0 < value < 1.0:
        raise ValueError("VERITYX_AI_DETECTION_THRESHOLD must be greater than 0 and less than 1")
    return value


def detect_ai_image(file_path: Path) -> dict[str, Any]:
    """Score a stored image with Smaug and preserve VerityX's result contract."""
    try:
        with Image.open(file_path) as source:
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Stored file is not a safely readable image") from exc

    threshold = _threshold()
    if min(image.size) < MIN_IMAGE_SIDE:
        return {
            "check": "ai_image_detection",
            "model_id": MODEL_ID,
            "model_license": MODEL_LICENSE,
            "model_attribution": MODEL_ATTRIBUTION,
            "classification": "inconclusive",
            "ai_score": None,
            "model_confidence": None,
            "threshold": threshold,
            "score_is_calibrated_probability": False,
            "note": f"Image is smaller than {MIN_IMAGE_SIDE}px on one side; detector results are unreliable at this size.",
            "limitations": [
                "Smaug's score is evidence, not proof of image origin or authenticity.",
                "New or adversarial generators and AI-edited real photographs may be misclassified.",
                "The score is not independently calibrated for VerityX's user population.",
            ],
        }

    detector = _load_detector()
    try:
        raw_score = detector(image)
        # The documented API returns one float in [0, 1] for one image.
        if hasattr(raw_score, "item"):
            raw_score = raw_score.item()
        ai_score = float(raw_score)
    except Exception as exc:
        raise RuntimeError("Smaug AI image detector inference failed") from exc

    if not math.isfinite(ai_score) or not 0.0 <= ai_score <= 1.0:
        raise RuntimeError("Smaug AI image detector returned an invalid score")

    classification = "likely_ai_generated" if ai_score >= threshold else "likely_not_ai_generated"
    confidence = ai_score if classification == "likely_ai_generated" else 1.0 - ai_score
    return {
        "check": "ai_image_detection",
        "model_id": MODEL_ID,
        "model_license": MODEL_LICENSE,
        "model_attribution": MODEL_ATTRIBUTION,
        "classification": classification,
        "ai_score": round(ai_score, 6),
        "model_confidence": round(confidence, 6),
        "threshold": threshold,
        "score_is_calibrated_probability": False,
        "agreement": "single_model",
        "models": [{
            "model_id": MODEL_ID,
            "model_license": MODEL_LICENSE,
            "classification": classification,
            "ai_score": round(ai_score, 6),
            "model_confidence": round(confidence, 6),
            "threshold": threshold,
            "score_is_calibrated_probability": False,
        }],
        "models_failed": [],
        "predictions": [{"label": "AI-generated", "score": round(ai_score, 6)},
                        {"label": "Real", "score": round(1.0 - ai_score, 6)}],
        "note": "Smaug returns an AI-generation score. This is a forensic signal, not proof; review other evidence before drawing conclusions.",
        "limitations": [
            "Benchmark results reported by the model publisher are not an independent evaluation of VerityX.",
            "New or adversarial generators may evade detection; AI-edited real photographs may be scored as real.",
            "The score is not independently calibrated for VerityX and must not be treated as proof of origin or authenticity.",
            "Do not use this result alone for consequential decisions; seek corroborating evidence and human review.",
        ],
    }
