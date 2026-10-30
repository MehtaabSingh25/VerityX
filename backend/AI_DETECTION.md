# VerityX AI image detection

VerityX supports the `ai_image_detection` analysis-job type for image assets. The Celery worker runs the open-weight [Smaug-AI-Image-Detector](https://huggingface.co/abacusai/Smaug-AI-Image-Detector) locally; image bytes are not sent to a hosted inference provider.

## Active model

- **Model:** `abacusai/Smaug-AI-Image-Detector`
- **Publisher:** Abacus.AI
- **License:** Apache-2.0 (review the model and dependency licenses before distribution or commercial deployment)
- **Architecture:** EmbeddingGemma-2 image encoder with a linear classifier; 439M parameters
- **Output:** scalar score in `[0, 1]`, interpreted by the model as the probability that the image is AI-generated
- **Default threshold:** `0.5`, as suggested by the model card

The model card reports average AUC 0.982 across OpenFake Reddit, OpenFake Core and CommunityForensics. These are publisher-reported benchmark results, not an independent evaluation by VerityX. Accuracy can vary with image sources, generator families, edits and compression. Scores are not independently calibrated for VerityX and must not be treated as proof of origin or authenticity.

## Runtime and configuration

- `VERITYX_AI_DETECTION_THRESHOLD`: decision threshold, default `0.5`; valid range is strictly between 0 and 1.
- `HF_HOME`: Hugging Face cache directory. Docker Compose points this at `/app/data/media/.hf_cache`, persisted by the `media_data` volume.
- The worker requires outbound internet access on first startup/inference to download the model files, plus enough disk space for the cache.
- The Docker image installs CPU-only PyTorch. Smaug supports CPU inference, but throughput depends on CPU, memory and image size. Measure production latency and memory before scaling.
- `sentence-transformers[image]` provides the model's documented runtime dependencies.

## Result interpretation

`ai_score` is the model's AI-generation score. At or above the configured threshold, the result is `likely_ai_generated`; below it, `likely_not_ai_generated`. `model_confidence` reflects the score for the selected class but is not a calibrated probability. Images smaller than 64 px on either side are inconclusive. Model load or inference errors fail the analysis job rather than returning a guessed result.

## Limitations

- New or adversarial generators may evade detection.
- A real photograph with a small AI-edited region may be scored as real.
- Real images may still be false positives, and AI images may be false negatives.
- Do not use the result alone for consequential decisions; corroborate with provenance, metadata, reverse-image search and human review.

## Legacy cleanup register (do not delete in the model-integration patch)

The following legacy code/configuration should be reviewed in a separate cleanup patch after the new detector has been validated:

1. `Organika/sdxl-detector` and `capcheck/ai-human-generated-image-detection` model IDs and their old ensemble/label-mapping logic (the active service no longer loads them).
2. Legacy `VERITYX_AI_DETECTOR_MODELS` and `VERITYX_AI_DETECTOR_MODEL` environment-variable support, if any remaining references are found.
3. Old tests that specifically assert the two-model ensemble, old label mappings or legacy model licences.
4. Any model-specific dependency/configuration proven unused after repository-wide import and runtime checks.
5. Separately, the duplicate observability implementations in `backend/app/observability.py` and `backend/app/core/observability.py` should be audited and consolidated only after metrics and health checks are tested.

Do not remove the analysis-job routing, API contract, result display, tests for image validation, or the working SerpApi Google Lens integration as part of this cleanup.
