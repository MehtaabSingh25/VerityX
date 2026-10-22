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
