# VerityX AI image detection

VerityX supports the `ai_image_detection` analysis-job type for image assets.
The Celery worker loads the configured Hugging Face image-classification model
locally on CPU and caches it for subsequent jobs in that worker process.

## Default models (ensemble)

Two detectors run locally and **must agree** for a decisive verdict:

- [Organika/sdxl-detector](https://huggingface.co/Organika/sdxl-detector) -
  SDXL specialist, fine-tuned from umm-maybe/AI-image-detector. CC BY-NC 3.0:
  **non-commercial only**.
- [capcheck/ai-human-generated-image-detection](https://huggingface.co/capcheck/ai-human-generated-image-detection) -
  general ViT-Base `human` / `AI-generated` classifier, Apache 2.0. Its card
  publishes no benchmark or named training set (not independently verified by us).

Disagreement, an unrecognised label set, a failed model, or an image under
64 px yields `inconclusive` (or a flagged degraded result) rather than a guess.
`model_confidence` is the weakest model's score and is only set when all agree.
Neither model was benchmarked by us (no model access in the build sandbox);
treat accuracy as unknown. Replace the ensemble if licensing or accuracy needs differ.

## Configuration

- `VERITYX_AI_DETECTOR_MODELS`: comma-separated Hugging Face model IDs (legacy
  `VERITYX_AI_DETECTOR_MODEL` still accepted). Unknown models show "unknown licence".
- `VERITYX_AI_DETECTION_THRESHOLD`: per-model decision threshold; default `0.75`,
  must be > `0.5` and < `1.0`.

The Docker image installs CPU-only PyTorch to avoid pulling GPU runtime libraries. For a local Windows virtual environment, install CPU PyTorch with `python -m pip install --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple "torch>=2.4,<3"`, then install `requirements-async.txt`.

The model is downloaded from Hugging Face the first time a worker needs it, so
the worker needs outbound internet access and disk space for its cache. The
specialist model is SDXL-focused and can perform worse on other generators.
Scores are not calibrated probabilities and are not proof of authenticity.
Use the result as one forensic signal, not as a definitive conclusion.

## Interpretation rules

Labels are mapped exactly (`artificial`/`ai-generated`/`fake`/… → AI;
`human`/`real`/`not-…`/`non-…` → real). If the model returns both classes and
their scores do not sum to ~1, or no label is recognised, the result is
`inconclusive` with an explanatory `note`. `model_confidence` is only set for
decisive results. Model download/inference failures fail the job with a clear
message instead of producing a prediction. The worker caches model files in
`HF_HOME` (set in `docker-compose.yml`) so restarts do not re-download.
