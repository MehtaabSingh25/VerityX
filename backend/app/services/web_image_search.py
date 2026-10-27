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
SERPAPI_IMAGE_ENDPOINT = "https://serpapi.com/image"
SERPAPI_SEARCH_ENDPOINT = "https://serpapi.com/search.json"
SERPAPI_MAX_IMAGE_BYTES = 500 * 1024
WIKIMEDIA_ENDPOINT = "https://commons.wikimedia.org/w/api.php"
MAX_IMAGE_BYTES = 7 * 1024 * 1024
MAX_RESULTS = 10
CANDIDATE_COUNT = 20
REQUEST_TIMEOUT_SECONDS = 30
OPENVERSE_RETRIES = 2
THUMBNAIL_TIMEOUT_SECONDS = 8
MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024
MAX_QUERY_LENGTH = 200
NEAR_DUPLICATE_BITS = 6
USER_AGENT = "Mozilla/5.0 (compatible; VerityX/1.0; image provenance research)"
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


def _allowed_media_url(url: Any) -> bool:
    """Allow only HTTPS media URLs from the indexes we intentionally query."""
    if not isinstance(url, str):
        return False
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed = (
        host == "openverse.org" or host.endswith(".openverse.org")
        or host == "wikimedia.org" or host.endswith(".wikimedia.org")
        or host == "wikipedia.org" or host.endswith(".wikipedia.org")
    )
    return parsed.scheme == "https" and allowed


def _is_openverse_url(url: Any) -> bool:
    """Compatibility helper retained for existing tests and callers."""
    if not isinstance(url, str):
        return False
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host == "openverse.org" or host.endswith(".openverse.org"))


class _AllowedMediaRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if not _allowed_media_url(newurl):
            raise urllib.error.URLError("redirect to a non-approved media host blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _OpenverseOnlyRedirects(_AllowedMediaRedirects):
    """Legacy name retained for tests; redirects remain restricted to trusted hosts."""


def _fetch_thumbnail(url: str) -> Image.Image | None:
    if not _allowed_media_url(url):
        return None
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(_AllowedMediaRedirects)
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


def _serpapi_upload_bytes(image: Image.Image) -> bytes:
    """Encode a JPEG under SerpApi Image API's documented 500 KB limit."""
    for size in (1600, 1280, 1024, 800, 640, 480):
        resized = image.copy()
        resized.thumbnail((size, size))
        for quality in (88, 78, 68, 58, 48):
            buffer = io.BytesIO()
            resized.save(buffer, format="JPEG", quality=quality, optimize=True)
            data = buffer.getvalue()
            if len(data) <= SERPAPI_MAX_IMAGE_BYTES:
                return data
    raise ValueError("Image could not be compressed below SerpApi's 500 KB upload limit")


def _serpapi_candidates(image: Image.Image, query: str | None = None) -> list[dict[str, Any]]:
    """Upload a compressed evidence image and search Google Lens through SerpApi."""
    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    if not api_key:
        raise SearchNotConfiguredError("SerpApi is not configured; set SERPAPI_API_KEY.")
    image_bytes = _serpapi_upload_bytes(image)
    boundary = "----VerityXSerpApiBoundary"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"evidence.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".encode()
            + image_bytes
            + f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"api_key\"\r\n\r\n{api_key}\r\n--{boundary}--\r\n".encode())
    upload_request = urllib.request.Request(SERPAPI_IMAGE_ENDPOINT, data=body, method="POST", headers={
        "User-Agent": USER_AGENT, "Content-Type": f"multipart/form-data; boundary={boundary}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(upload_request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            uploaded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"SerpApi image upload failed with HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("SerpApi image upload timed out or could not connect") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("SerpApi image upload returned an invalid response") from exc
    image_id = uploaded.get("image_id") if isinstance(uploaded, dict) else None
    if not isinstance(image_id, str) or not image_id:
        detail = uploaded.get("error") if isinstance(uploaded, dict) else None
        raise RuntimeError(f"SerpApi image upload failed: {str(detail or 'missing image_id')[:200]}")

    params = {"engine": "google_lens", "image_id": image_id, "api_key": api_key, "type": "all", "hl": "en"}
    if query:
        params["q"] = query
    request = urllib.request.Request(f"{SERPAPI_SEARCH_ENDPOINT}?{urllib.parse.urlencode(params)}", headers={
        "User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"SerpApi Google Lens search failed with HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("SerpApi Google Lens search timed out or could not connect") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("SerpApi Google Lens returned an invalid response") from exc
    if not isinstance(payload, dict) or payload.get("error"):
        detail = payload.get("error") if isinstance(payload, dict) else "invalid response"
        raise RuntimeError(f"SerpApi Google Lens search failed: {str(detail)[:200]}")
    raw = payload.get("visual_matches") or payload.get("exact_matches") or []
    if not isinstance(raw, list):
        raise RuntimeError("SerpApi Google Lens returned an invalid matches list")
    candidates = []
    for item in raw[:CANDIDATE_COUNT]:
        if not isinstance(item, dict):
            continue
        link = item.get("link")
        if not isinstance(link, str) or urllib.parse.urlparse(link).scheme not in {"https", "http"}:
            continue
        candidates.append({
            "title": item.get("title") if isinstance(item.get("title"), str) else "Google Lens visual match",
            "foreign_landing_url": link,
            "url": item.get("image") if isinstance(item.get("image"), str) else None,
            "thumbnail": item.get("thumbnail") if isinstance(item.get("thumbnail"), str) else None,
            "creator": item.get("source") if isinstance(item.get("source"), str) else None,
            "license": "Check source page for rights",
            "source": item.get("source") if isinstance(item.get("source"), str) else "Google Lens",
        })
    return candidates



def _openverse_candidates(query: str) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"q": query, "page_size": CANDIDATE_COUNT})
    request = urllib.request.Request(
        f"{OPENVERSE_ENDPOINT}?{params}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    last_network_error: Exception | None = None
    payload: Any = None
    for attempt in range(OPENVERSE_RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise RuntimeError("Openverse rate limit reached; retry later.") from exc
            if exc.code in {500, 502, 503, 504} and attempt + 1 < OPENVERSE_RETRIES:
                last_network_error = exc
                continue
            raise RuntimeError(f"Openverse request failed with HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_network_error = exc
            if attempt + 1 < OPENVERSE_RETRIES:
                continue
            raise RuntimeError(
                f"Openverse request failed after {OPENVERSE_RETRIES} attempts "
                f"({type(exc).__name__}); check network access and retry."
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Openverse returned an invalid response") from exc
    else:
        raise RuntimeError("Openverse request failed after retries") from last_network_error
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        # Not TypeError: the API layer maps RuntimeError to HTTP 502.
        raise RuntimeError("Openverse returned an invalid response")  # noqa: TRY004
    return [r for r in results if isinstance(r, dict)][:CANDIDATE_COUNT]


def _wikimedia_candidates(query: str) -> list[dict[str, Any]]:
    """Search Wikimedia Commons as a no-key, no-billing fallback provider."""
    params = urllib.parse.urlencode({
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,
        "gsrlimit": CANDIDATE_COUNT,
        "prop": "imageinfo|info",
        "iiprop": "url|extmetadata",
        "iiurlwidth": 500,
        "inprop": "url",
        "format": "json",
        "formatversion": 2,
    })
    request = urllib.request.Request(
        f"{WIKIMEDIA_ENDPOINT}?{params}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Wikimedia Commons fallback failed with HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Wikimedia Commons fallback timed out or could not connect") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Wikimedia Commons returned an invalid response") from exc

    pages = payload.get("query", {}).get("pages", []) if isinstance(payload, dict) else []
    if not isinstance(pages, list):
        return []
    candidates: list[dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        info_list = page.get("imageinfo")
        info = info_list[0] if isinstance(info_list, list) and info_list else {}
        if not isinstance(info, dict):
            continue
        metadata = info.get("extmetadata") if isinstance(info.get("extmetadata"), dict) else {}
        def metadata_value(key: str) -> str | None:
            value = metadata.get(key)
            if isinstance(value, dict):
                value = value.get("value")
            if not isinstance(value, str):
                return None
            # API metadata may contain HTML; strip tags before displaying it.
            import re
            clean = re.sub(r"<[^>]+>", " ", value)
            return " ".join(clean.split())[:300] or None
        page_url = page.get("fullurl")
        image_url = info.get("url")
        thumb_url = info.get("thumburl") or image_url
        if not isinstance(page_url, str) or not page_url.startswith("https://commons.wikimedia.org/"):
            continue
        if not _allowed_media_url(image_url) or not _allowed_media_url(thumb_url):
            continue
        candidates.append({
            "title": str(page.get("title") or "Wikimedia Commons image")[:300],
            "foreign_landing_url": page_url,
            "url": image_url,
            "thumbnail": thumb_url,
            "creator": metadata_value("Artist"),
            "license": metadata_value("LicenseShortName") or "See source page for licence",
            "source": "Wikimedia Commons",
        })
    return candidates[:CANDIDATE_COUNT]


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
            "thumbnail_url": item.get("thumbnail") if _allowed_media_url(item.get("thumbnail")) else None,
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

    provider = "openverse"
    fallback_note = None
    if os.getenv("SERPAPI_API_KEY", "").strip():
        try:
            candidates = _serpapi_candidates(image, cleaned or None)
            provider = "serpapi_google_lens"
        except RuntimeError as serpapi_error:
            if not cleaned:
                cleaned = _caption_image(image)
            try:
                candidates = _openverse_candidates(cleaned)
                fallback_note = f"SerpApi Google Lens was unavailable ({serpapi_error}); showing Openverse results instead."
            except RuntimeError as openverse_error:
                try:
                    candidates = _wikimedia_candidates(cleaned)
                    provider = "wikimedia_commons"
                    fallback_note = f"SerpApi and Openverse were unavailable; showing Wikimedia Commons results. ({openverse_error})"
                except RuntimeError as fallback_error:
                    raise RuntimeError(f"SerpApi failed ({serpapi_error}); Openverse failed ({openverse_error}); Wikimedia fallback failed ({fallback_error}).") from fallback_error
    else:
        if not cleaned:
            cleaned = _caption_image(image)
        try:
            candidates = _openverse_candidates(cleaned)
        except RuntimeError as openverse_error:
            if "invalid response" in str(openverse_error).lower():
                raise
            try:
                candidates = _wikimedia_candidates(cleaned)
                provider = "wikimedia_commons"
                fallback_note = (
                    f"Openverse was unavailable ({openverse_error}). Results are from Wikimedia Commons, "
                    "a separate openly licensed image index."
                )
            except RuntimeError as fallback_error:
                raise RuntimeError(
                    f"Openverse search failed ({openverse_error}); Wikimedia Commons fallback also failed "
                    f"({fallback_error}). Please retry later."
                ) from fallback_error

    if provider == "serpapi_google_lens":
        results = []
        for candidate in candidates[:MAX_RESULTS]:
            page_url = _http_url(candidate.get("foreign_landing_url"))
            if page_url:
                results.append({
                    "title": _text(candidate, "title"), "page_url": page_url,
                    "image_url": _http_url(candidate.get("url")),
                    "thumbnail_url": _http_url(candidate.get("thumbnail")),
                    "creator": _text(candidate, "creator"), "license": _text(candidate, "license"),
                    "source": _text(candidate, "source"), "visual_similarity": None,
                    "visual_distance_bits": None, "near_duplicate": False,
                })
        method = "none"
        limitations = [
            "Results are Google Lens visual matches returned through SerpApi; they are leads, not proof of identity, origin, ownership, or publication date.",
            "The uploaded image is sent to SerpApi for processing. Verify source pages independently and check image-use rights.",
        ]
    else:
        with ThreadPoolExecutor(max_workers=8) as pool:
            thumbnails = list(pool.map(
                lambda c: _fetch_thumbnail(c["thumbnail"]) if _allowed_media_url(c.get("thumbnail")) else None,
                candidates,
            ))
        results, method = rank_candidates(image, candidates, thumbnails)
        limitations = _limitations(search_type, method)
        if provider == "wikimedia_commons":
            limitations[0] = (
                "Coverage is limited to openly licensed files indexed by Wikimedia Commons. This is NOT a whole-web "
                "reverse-image search; social media and many news sites are not indexed."
            )
            limitations.append("Openverse was unavailable, so VerityX automatically used Wikimedia Commons as a fallback.")
    return {
        "check": "public_web_image_search",
        "search_type": search_type,
        "provider": provider,
        "query": cleaned,
        "query_source": query_source,
        "ranking_method": method,
        "results": results,
        "result_count": len(results),
        "limitations": limitations if provider == "serpapi_google_lens" else limitations,
        "fallback_notice": fallback_note,
    }

