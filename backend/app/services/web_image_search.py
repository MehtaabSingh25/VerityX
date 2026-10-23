"""Optional public-web image matching via Google Cloud Vision Web Detection.

This reports indexed matches and visually similar images; it does not prove
original authorship, publication date, or that a result is the source image.
"""

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

VISION_ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"
MAX_IMAGE_BYTES = 7 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 20
MAX_RESULTS = 10


def _strings(items: Any, key: str | None = None) -> list[str]:
    if not isinstance(items, list):
        return []
    values: list[str] = []
    for item in items:
        value = item.get(key) if key and isinstance(item, dict) else item
        if isinstance(value, str) and value.startswith(("https://", "http://")):
            values.append(value)
    return values[:MAX_RESULTS]


def normalize_web_detection(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize Vision API output into a small, stable response schema."""
    responses = payload.get("responses")
    response = responses[0] if isinstance(responses, list) and responses else {}
    if not isinstance(response, dict):
        response = {}
    if response.get("error"):
        message = response["error"].get("message", "Vision API request failed")
        raise RuntimeError(str(message)[:500])

    web = response.get("webDetection") or {}
    if not isinstance(web, dict):
        web = {}
    pages = web.get("pagesWithMatchingImages") or []
    page_matches = []
    if isinstance(pages, list):
        for page in pages[:MAX_RESULTS]:
            if not isinstance(page, dict):
                continue
            url = page.get("url")
            if isinstance(url, str) and url.startswith(("https://", "http://")):
                page_matches.append({
                    "url": url,
                    "page_title": page.get("pageTitle") if isinstance(page.get("pageTitle"), str) else None,
                    "full_matching_image_urls": _strings(page.get("fullMatchingImages"), "url"),
                    "partial_matching_image_urls": _strings(page.get("partialMatchingImages"), "url"),
                })

    entities = []
    raw_entities = web.get("webEntities") or []
    if isinstance(raw_entities, list):
        for entity in raw_entities[:MAX_RESULTS]:
            if not isinstance(entity, dict):
                continue
            description = entity.get("description")
            if isinstance(description, str) and description.strip():
                entities.append({
                    "description": description[:300],
                    "score": entity.get("score") if isinstance(entity.get("score"), (int, float)) else None,
                })

    return {
        "check": "public_web_image_search",
        "provider": "google_cloud_vision_web_detection",
        "pages_with_matching_images": page_matches,
        "visually_similar_image_urls": _strings(web.get("visuallySimilarImages"), "url"),
        "full_matching_image_urls": _strings(web.get("fullMatchingImages"), "url"),
        "partial_matching_image_urls": _strings(web.get("partialMatchingImages"), "url"),
        "web_entities": entities,
        "result_count": len(page_matches),
        "limitations": [
            "Only content indexed by the provider can be found.",
            "A match is a lead, not proof of origin, ownership, or publication date.",
            "No matches does not mean the image has never appeared online.",
        ],
    }


def search_public_web_image(file_path: Path) -> dict[str, Any]:
    """Submit image bytes to Cloud Vision Web Detection and normalize results."""
    api_key = os.getenv("GOOGLE_CLOUD_VISION_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "Public-web image search is not configured. Set GOOGLE_CLOUD_VISION_API_KEY."
        )

    image_bytes = file_path.read_bytes()
    if not image_bytes:
        raise ValueError("Image file is empty")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds the 7 MiB limit for public-web search")

    request_body = {
        "requests": [{
            "image": {"content": base64.b64encode(image_bytes).decode("ascii")},
            "features": [{"type": "WEB_DETECTION", "maxResults": MAX_RESULTS}],
        }]
    }
    request = urllib.request.Request(
        f"{VISION_ENDPOINT}?key={api_key}",
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # The request URL contains the API key; never include it in diagnostics.
        try:
            error_payload = json.loads(exc.read().decode("utf-8"))
            provider_error = error_payload.get("error", {}) if isinstance(error_payload, dict) else {}
            provider_message = provider_error.get("message") if isinstance(provider_error, dict) else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            provider_message = None

        detail = str(provider_message).strip().replace(api_key, "[redacted]")[:300] if provider_message else ""
        if exc.code in (401, 403):
            suffix = f" Provider detail: {detail}" if detail else ""
            raise RuntimeError(
                "Cloud Vision rejected the request. Check that the Vision API is enabled, "
                "billing is active, and API-key restrictions allow this server." + suffix
            ) from exc
        if exc.code == 429:
            suffix = f" Provider detail: {detail}" if detail else ""
            raise RuntimeError(f"Cloud Vision quota exceeded; retry later.{suffix}") from exc
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"Cloud Vision request failed with HTTP {exc.code}{suffix}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Cloud Vision request timed out or could not connect") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Cloud Vision returned an invalid response") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("Cloud Vision returned an invalid response")
    return normalize_web_detection(payload)
