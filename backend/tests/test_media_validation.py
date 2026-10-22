from app.api.media_ingestion import allowed_extension, detect_media_type


def test_detects_jpeg_signature():
    assert detect_media_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"


def test_detects_png_signature():
    assert detect_media_type(b"\x89PNG\r\n\x1a\nrest") == "image/png"


def test_detects_webp_signature():
    assert detect_media_type(b"RIFF\x00\x00\x00\x00WEBPrest") == "image/webp"


def test_detects_mp4_signature():
    assert detect_media_type(b"\x00\x00\x00\x18ftypisom") == "video/mp4"


def test_detects_webm_signature():
    assert detect_media_type(b"\x1a\x45\xdf\xa3rest") == "video/webm"


def test_rejects_unknown_signature():
    assert detect_media_type(b"this is not media") is None


def test_extension_must_match_detected_type():
    assert allowed_extension("photo.jpg", "image/jpeg")
    assert not allowed_extension("photo.png", "image/jpeg")
    assert not allowed_extension("clip.exe", "video/mp4")
