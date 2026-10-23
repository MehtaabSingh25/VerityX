import pytest

from app.services.web_image_search import normalize_web_detection


def test_normalizes_page_matches_similar_images_and_entities():
    result = normalize_web_detection({"responses": [{"webDetection": {
        "pagesWithMatchingImages": [{
            "url": "https://example.com/article",
            "pageTitle": "Example image page",
            "fullMatchingImages": [{"url": "https://example.com/image.jpg"}],
        }],
        "visuallySimilarImages": [{"url": "https://example.com/similar.jpg"}],
        "webEntities": [{"description": "mountain", "score": 0.91}],
    }}]})

    assert result["check"] == "public_web_image_search"
    assert result["result_count"] == 1
    assert result["pages_with_matching_images"][0]["page_title"] == "Example image page"
    assert result["visually_similar_image_urls"] == ["https://example.com/similar.jpg"]
    assert result["web_entities"][0]["description"] == "mountain"
    assert result["limitations"]


def test_empty_or_unrecognized_response_is_a_valid_no_match_result():
    result = normalize_web_detection({"responses": [{}]})
    assert result["pages_with_matching_images"] == []
    assert result["result_count"] == 0


def test_provider_error_is_not_silently_reported_as_no_matches():
    with pytest.raises(RuntimeError, match="quota exceeded"):
        normalize_web_detection({"responses": [{"error": {"message": "quota exceeded"}}]})


def test_cloud_vision_http_error_exposes_provider_reason_without_api_key(tmp_path, monkeypatch):
    import io
    import json
    import urllib.error

    from app.services import web_image_search

    api_key = "test-secret-api-key"
    monkeypatch.setenv("GOOGLE_CLOUD_VISION_API_KEY", api_key)
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"image bytes")
    provider_body = json.dumps({
        "error": {"message": "Vision API has not been used in this project"}
    }).encode("utf-8")
    http_error = urllib.error.HTTPError(
        url=f"{web_image_search.VISION_ENDPOINT}?key={api_key}",
        code=403,
        msg="Forbidden",
        hdrs=None,
        fp=io.BytesIO(provider_body),
    )

    def reject_request(*args, **kwargs):
        raise http_error

    monkeypatch.setattr(web_image_search.urllib.request, "urlopen", reject_request)

    with pytest.raises(RuntimeError, match="Vision API has not been used") as error:
        web_image_search.search_public_web_image(image_path)

    assert api_key not in str(error.value)
