import io
import json
import urllib.error
from pathlib import Path

import pytest
from PIL import Image

from app.services import web_image_search as ws


def _img(color=(200, 10, 10), left=(10, 10, 200)):
    image = Image.new("RGB", (32, 32), color)
    for x in range(16):
        for y in range(32):
            image.putpixel((x, y), left)
    return image


def _png_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _setup(tmp_path, monkeypatch, *, clip=None, caption="a red and blue square"):
    path = tmp_path / "q.png"
    path.write_bytes(_png_bytes(_img()))
    api = json.dumps({"results": [
        {"title": "Far", "foreign_landing_url": "https://example.com/a", "url": "https://example.com/a.jpg",
         "thumbnail": "https://api.openverse.org/v1/images/far/thumb/", "license": "by", "source": "flickr"},
        {"title": "Same", "foreign_landing_url": "https://example.com/b", "url": "https://example.com/b.jpg",
         "thumbnail": "https://api.openverse.org/v1/images/same/thumb/", "license": "cc0", "source": "wikimedia"},
        {"title": "Unsafe", "foreign_landing_url": "javascript:alert(1)"},
    ]}).encode()
    seen = {}

    class Opener:
        def open(self, request, timeout=None):
            url = request.full_url
            return _Resp(_png_bytes(Image.new("RGB", (32, 32), (120, 120, 120)))) if "/far/" in url else _Resp(path.read_bytes())

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        return _Resp(api)

    monkeypatch.setattr(ws.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ws.urllib.request, "build_opener", lambda *a: Opener())
    monkeypatch.setattr(ws, "_caption_image", lambda image: caption)
    monkeypatch.setattr(ws, "_clip_similarities", clip or (lambda image, c: (_ for _ in ()).throw(RuntimeError("no clip"))))
    return path, seen


def test_visual_search_uses_caption_and_clip_ranking(tmp_path, monkeypatch):
    path, seen = _setup(tmp_path, monkeypatch, clip=lambda image, cands: [0.31, 0.97])
    result = ws.search_public_web_image(path)
    assert result["search_type"] == "visual_similarity_search"
    assert result["query_source"] == "auto_caption"
    assert "q=a+red+and+blue+square" in seen["url"]
    assert result["ranking_method"] == "clip_cosine"
    assert [r["title"] for r in result["results"]] == ["Same", "Far"]
    assert result["results"][0]["visual_similarity"] == 0.97
    assert result["results"][0]["near_duplicate"] is True
    assert result["results"][1]["near_duplicate"] is False
    assert all(r["page_url"].startswith("https://") for r in result["results"])  # unsafe URL dropped
    assert any("NOT a whole-web" in text for text in result["limitations"])


def test_clip_failure_falls_back_to_dhash_and_says_so(tmp_path, monkeypatch):
    path, _ = _setup(tmp_path, monkeypatch)
    result = ws.search_public_web_image(path)
    assert result["ranking_method"] == "dhash"
    assert result["results"][0]["title"] == "Same"
    assert result["results"][0]["visual_distance_bits"] == 0
    assert result["results"][0]["visual_similarity"] is None
    assert any("CLIP was unavailable" in text for text in result["limitations"])


def test_keyword_query_skips_captioning_and_is_labelled_keyword(tmp_path, monkeypatch):
    path, seen = _setup(tmp_path, monkeypatch)

    def no_caption(image):
        raise AssertionError("captioning must not run when keywords are given")

    monkeypatch.setattr(ws, "_caption_image", no_caption)
    result = ws.search_public_web_image(path, "  sunset   beach ")
    assert result["search_type"] == "keyword_image_search"
    assert result["query"] == "sunset beach"
    assert result["query_source"] == "user_keywords"
    assert "q=sunset+beach" in seen["url"]
    assert any("not by image content" in text for text in result["limitations"])


def test_missing_caption_model_is_a_clear_error_not_fake_results(tmp_path, monkeypatch):
    path = tmp_path / "q.png"
    path.write_bytes(_png_bytes(_img()))

    def unavailable(image):
        raise ws.SearchNotConfiguredError("Enter keywords to search instead.")

    monkeypatch.setattr(ws, "_caption_image", unavailable)
    with pytest.raises(ws.SearchNotConfiguredError, match="keywords"):
        ws.search_public_web_image(path)


def test_no_results_is_valid_empty_result(tmp_path, monkeypatch):
    path = tmp_path / "q.png"
    path.write_bytes(_png_bytes(_img()))
    monkeypatch.setattr(ws.urllib.request, "urlopen", lambda r, timeout=None: _Resp(b'{"results": []}'))
    result = ws.search_public_web_image(path, "zzzz")
    assert result["results"] == [] and result["result_count"] == 0


def test_rate_limit_and_bad_payload_are_errors(tmp_path, monkeypatch):
    path = tmp_path / "q.png"
    path.write_bytes(_png_bytes(_img()))

    def limited(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many", None, io.BytesIO(b""))

    monkeypatch.setattr(ws.urllib.request, "urlopen", limited)
    with pytest.raises(RuntimeError, match="rate limit"):
        ws.search_public_web_image(path, "cat")
    monkeypatch.setattr(ws.urllib.request, "urlopen", lambda r, timeout=None: _Resp(b"[]"))
    with pytest.raises(RuntimeError, match="invalid response"):
        ws.search_public_web_image(path, "cat")


def test_invalid_inputs(tmp_path):
    bad = tmp_path / "x.png"
    bad.write_bytes(b"not an image")
    with pytest.raises(ValueError, match="readable image"):
        ws.search_public_web_image(bad, "cat")
    empty = tmp_path / "e.png"
    empty.write_bytes(b"")
    with pytest.raises(ValueError, match="empty"):
        ws.search_public_web_image(empty)
    with pytest.raises(ValueError, match="at most"):
        ws.search_public_web_image(bad, "x" * 201)


def test_thumbnail_hosts_and_redirects_are_restricted():
    assert ws._is_openverse_url("https://api.openverse.org/v1/images/1/thumb/")
    assert not ws._is_openverse_url("https://evil.example.com/thumb")
    assert not ws._is_openverse_url("http://api.openverse.org/x")
    assert not ws._is_openverse_url("https://openverse.org.evil.com/x")
    handler = ws._OpenverseOnlyRedirects()
    with pytest.raises(urllib.error.URLError):
        handler.redirect_request(None, None, 302, "Found", {}, "https://169.254.169.254/")


def test_no_google_cloud_vision_dependency():
    assert not hasattr(ws, "VISION_ENDPOINT")
    assert "GOOGLE_CLOUD_VISION_API_KEY" not in Path(ws.__file__).read_text()


def test_clip_similarity_path_with_real_transformers_tiny_model(monkeypatch):
    """Exercises the real torch/transformers call path with a tiny random CLIP (no downloads)."""
    pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    config = transformers.CLIPConfig(
        text_config_dict={"hidden_size": 32, "intermediate_size": 64, "num_hidden_layers": 1,
                          "num_attention_heads": 2, "vocab_size": 100},
        vision_config_dict={"hidden_size": 32, "intermediate_size": 64, "num_hidden_layers": 1,
                            "num_attention_heads": 2, "image_size": 224, "patch_size": 32},
        projection_dim=16,
    )
    model = transformers.CLIPModel(config).eval()
    image_processor = transformers.CLIPImageProcessor()

    def processor(images, return_tensors):
        return image_processor(images=images, return_tensors=return_tensors)

    monkeypatch.setattr(ws, "_load_clip", lambda model_id: (model, processor))
    red, blue = Image.new("RGB", (64, 64), (255, 0, 0)), Image.new("RGB", (64, 64), (0, 0, 255))
    sims = ws._clip_similarities(red, [red.copy(), blue])
    assert sims[0] == pytest.approx(1.0, abs=1e-4)
    assert sims[1] < sims[0]
