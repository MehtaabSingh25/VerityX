# VerityX AI image detection

VerityX supports the `ai_image_detection` analysis-job type for image assets.
The Celery worker loads the configured Hugging Face image-classification model
locally on CPU and caches it for subsequent jobs in that worker process.

## Default model and attribution

- Model: [Organika/sdxl-detector](https://huggingface.co/Organika/sdxl-detector)
- Attribution: Organika/sdxl-detector, fine-tuned from
  [umm-maybe/AI-image-detector](https://huggingface.co/umm-maybe/AI-image-detector)
- License: the model card identifies CC BY-NC 3.0 / non-commercial use. This
  default is suitable only for non-commercial use unless the model owner grants
  different rights. Replace it with a properly licensed model before commercial
  deployment.

## Configuration

- `VERITYX_AI_DETECTOR_MODEL`: optional Hugging Face model ID; defaults to
  `Organika/sdxl-detector`.
- `VERITYX_AI_DETECTION_THRESHOLD`: optional decision threshold; defaults to
  `0.75` and must be greater than `0.5` and less than `1.0`.

The Docker image installs CPU-only PyTorch to avoid pulling GPU runtime libraries. For a local Windows virtual environment, install CPU PyTorch with `python -m pip install --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple "torch>=2.4,<3"`, then install `requirements-async.txt`.

The model is downloaded from Hugging Face the first time a worker needs it, so
the worker needs outbound internet access and disk space for its cache. The
model is SDXL-focused and can perform worse on images from other generators.
Scores are not calibrated probabilities and are not proof of authenticity.
Use the result as one forensic signal, not as a definitive conclusion.
