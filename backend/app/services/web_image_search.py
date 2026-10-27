"""Free image search with no paid or billing-enabled provider.

No free Google-Lens-style reverse-image API exists (TinEye/Google/Bing need paid
plans, billing, or ToS-violating scraping), so this module does the honest
alternative, entirely free and self-hosted apart from the public Openverse API:

* ``visual_similarity_search`` (no query): a local captioning model describes the
  uploaded image, the caption is searched on Openverse, and candidate thumbnails
  are ranked by local CLIP image-embedding similarity to the upload.
* ``keyword_image_search`` (user query): the same Openverse search using the
  user's keywords; ranking by visual similarity is still applied locally.

Coverage is limited to openly licensed images indexed by Openverse. This is NOT
a whole-web reverse-image search; results are leads, never proof of origin.
"""

import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

OPENVERSE_ENDPOINT = "https://api.openverse.org/v1/images/"
MAX_IMAGE_BYTES = 7 * 1024 * 1024
MAX_RESULTS = 10
CANDIDATE_COUNT = 20
REQUEST_TIMEOUT_SECONDS = 20
THUMBNAIL_TIMEOUT_SECONDS = 8
MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024
MAX_QUERY_LENGTH = 200
NEAR_DUPLICATE_BITS = 6
USER_AGENT = "VerityX/1.0 (image provenance research)"
DEFAULT_CAPTION_MODEL = "Salesforce/blip-image-captioning-base"  # BSD-3-Clause
DEFAULT_CLIP_MODEL = "openai/clip-vit-base-patch32"  # MIT


class SearchNotConfiguredError(RuntimeError):
    """The requested search needs something that is unavailable (e.g. local models)."""


# ---------------------------------------------------------------- local models
@lru_cache(maxsize=1)
def _load_captioner(model_id: str):
    try:
        from transformers import pipeline
    except ImportError as exc:  # pragma: no cover - optional runtime dependency
        raise SearchNotConfiguredError("Local captioning needs transformers/torch (requirements-async.txt).") from exc
    return pipeline("image-to-text", model=model_id, device=-1)


@lru_cache(maxsize=1)
def _load_clip(model_id: str):
    try:
        from transformers import CLIPModel, CLIPProcessor
    except ImportError as exc:  # pragma: no cover - optional runtime dependency
        raise SearchNotConfiguredError("CLIP ranking needs transformers/torch (requirements-async.txt).") from exc
    return CLIPModel.from_pretrained(model_id).eval(), CLIPProcessor.from_pretrained(model_id)


def _caption_image(image: Image.Image) -> str:
    model_id = os.getenv("VERITYX_CAPTION_MODEL", DEFAULT_CAPTION_MODEL).strip() or DEFAULT_CAPTION_MODEL
    try:
        output = _load_captioner(model_id)(image, max_new_tokens=30)
        caption = str(output[0]["generated_text"]).strip()
    except SearchNotConfiguredError:
        raise
    except Exception as exc:
        raise SearchNotConfiguredError(
            "The local captioning model could not be loaded or run. Enter keywords to search instead."
        ) from exc
    if not caption:
        raise SearchNotConfiguredError("The local model could not describe this image. Enter keywords instead.")
    return caption[:MAX_QUERY_LENGTH]


def _clip_similarities(image: Image.Image, candidates: list[Image.Image]) -> list[float]:
    """Cosine similarity (-1..1) between the upload and each candidate image."""
    import torch

    model_id = os.getenv("VERITYX_CLIP_MODEL", DEFAULT_CLIP_MODEL).strip() or DEFAULT_CLIP_MODEL
    model, processor = _load_clip(model_id)
    with torch.no_grad():
        inputs = processor(images=[image, *candidates], return_tensors="pt")
        features = model.get_image_features(**inputs)
        features = features / features.norm(dim=-1, keepdim=True)
    return [float(v) for v in (features[1:] @ features[0]).tolist()]


# ------------------------------------------------------------------ helpers
def _dhash(image: Image.Image) -> int:
    pixels = ImageOps.grayscale(image).resize((9, 8)).tobytes()
    bits = 0
    for row in range(8):
        for col in range(8):
            offset = row * 9 + col
            bits = (bits << 1) | int(pixels[offset] > pixels[offset + 1])
    return bits


def _is_openverse_url(url: Any) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    return parsed.scheme == "https" and (host == "openverse.org" or host.endswith(".openverse.org"))


class _OpenverseOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if not _is_openverse_url(newurl):
            raise urllib.error.URLError("redirect to a non-Openverse host blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_thumbnail(url: str) -> Image.Image | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(_OpenverseOnlyRedirects)
    try:
        with opener.open(request, timeout=THUMBNAIL_TIMEOUT_SECONDS) as response:
            data = response.read(MAX_THUMBNAIL_BYTES + 1)
        if not 0 < len(data) <= MAX_THUMBNAIL_BYTES:
            return None
        with Image.open(io.BytesIO(data)) as thumb:
            thumb.load()
            return thumb.convert("RGB")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        return None


def _openverse_candidates(query: str) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"q": query, "page_size": CANDIDATE_COUNT})
    request = urllib.request.Request(
        f"{OPENVERSE_ENDPOINT}?{params}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RuntimeError("Openverse anonymous rate limit reached; retry later.") from exc
        raise RuntimeError(f"Openverse request failed with HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Openverse request timed out or could not connect") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Openverse returned an invalid response") from exc
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        # Not TypeError: the API layer maps RuntimeError to HTTP 502.
        raise RuntimeError("Openverse returned an invalid response")  # noqa: TRY004
    return [r for r in results if isinstance(r, dict)][:CANDIDATE_COUNT]


def _text(item: dict[str, Any], key: str) -> str | None:
    value = item.get(key)
    return value[:300] if isinstance(value, str) and value.strip() else None


def _http_url(value: Any) -> str | None:
    return value if isinstance(value, str) and value.startswith(("https://", "http://")) else None


def rank_candidates(
    image: Image.Image, candidates: list[dict[str, Any]], thumbnails: list[Image.Image | None]
) -> tuple[list[dict[str, Any]], str]:
    """Attach visual scores and sort best-first. Returns (results, ranking_method)."""
    results: list[dict[str, Any]] = []
    for item, thumb in zip(candidates, thumbnails, strict=True):
        page_url = _http_url(item.get("foreign_landing_url"))
        if page_url is None:
            continue
        results.append({
            "title": _text(item, "title"),
            "page_url": page_url,
            "image_url": _http_url(item.get("url")),
            "thumbnail_url": item.get("thumbnail") if _is_openverse_url(item.get("thumbnail")) else None,
            "creator": _text(item, "creator"),
            "license": _text(item, "license"),
            "source": _text(item, "source"),
            "visual_similarity": None,
            "visual_distance_bits": None,
            "near_duplicate": False,
            "_thumb": thumb,
        })
    scored = [r for r in results if r["_thumb"] is not None]
    method = "none"
    if scored:
        query_hash = _dhash(image)
        for r in scored:
            r["visual_distance_bits"] = (query_hash ^ _dhash(r["_thumb"])).bit_count()
            r["near_duplicate"] = r["visual_distance_bits"] <= NEAR_DUPLICATE_BITS
        method = "dhash"
        try:
            sims = _clip_similarities(image, [r["_thumb"] for r in scored])
            for r, sim in zip(scored, sims, strict=True):
                r["visual_similarity"] = round(sim, 4)
            method = "clip_cosine"
        except Exception:  # noqa: BLE001, S110 - CLIP unavailable (no torch/model): honest dHash fallback
            pass
    for r in results:
        r.pop("_thumb")
    if method == "clip_cosine":
        results.sort(key=lambda r: (r["visual_similarity"] is None, -(r["visual_similarity"] or 0)))
    elif method == "dhash":
        results.sort(key=lambda r: (r["visual_distance_bits"] is None, r["visual_distance_bits"] or 0))
    return results[:MAX_RESULTS], method


def _limitations(search_type: str, method: str) -> list[str]:
    items = [
        (
            "Coverage is limited to openly licensed images indexed by Openverse. This is NOT a whole-web "
            "reverse-image search and cannot match images outside that index (most of the web, social media, news)."
        ),
        "A result is a lead, not proof of origin, ownership, or publication date. No result proves nothing.",
    ]
    if search_type == "visual_similarity_search":
        items.append(
            "The search text was auto-generated by a local captioning model and may be wrong or generic; "
            "enter your own keywords if results look unrelated."
        )
    else:
        items.append("Results are retrieved by your keywords, not by image content.")
    if method == "clip_cosine":
        items.append(
            "Ranking uses local CLIP embedding similarity (higher is more similar; scores are not probabilities). "
            "near_duplicate uses a 64-bit dHash distance of 6 or less."
        )
    elif method == "dhash":
        items.append(
            "CLIP was unavailable, so results are ranked by coarse dHash distance only "
            "(0 = identical, 64 = maximally different)."
        )
    else:
        items.append("Result thumbnails could not be retrieved, so results are unranked by image content.")
    return items


def search_public_web_image(file_path: Path, query: str | None = None) -> dict[str, Any]:
    """Free image search: visual similarity (no query) or keyword search (query)."""
    cleaned = " ".join((query or "").split())
    if len(cleaned) > MAX_QUERY_LENGTH:
        raise ValueError(f"Search keywords must be at most {MAX_QUERY_LENGTH} characters")
    try:
        data = file_path.read_bytes()
    except OSError as exc:
        raise ValueError("Image file could not be read") from exc
    if not data:
        raise ValueError("Image file is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds the 7 MiB limit for image search")
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.load()
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Stored file is not a safely readable image") from exc

    if cleaned:
        search_type, query_source = "keyword_image_search", "user_keywords"
    else:
        search_type, query_source = "visual_similarity_search", "auto_caption"
        cleaned = _caption_image(image)

    candidates = _openverse_candidates(cleaned)
    with ThreadPoolExecutor(max_workers=8) as pool:
        thumbnails = list(pool.map(
            lambda c: _fetch_thumbnail(c["thumbnail"]) if _is_openverse_url(c.get("thumbnail")) else None,
            candidates,
        ))
    results, method = rank_candidates(image, candidates, thumbnails)
    return {
        "check": "public_web_image_search",
        "search_type": search_type,
        "provider": "openverse",
        "query": cleaned,
        "query_source": query_source,
        "ranking_method": method,
        "results": results,
        "result_count": len(results),
        "limitations": _limitations(search_type, method),
    }
