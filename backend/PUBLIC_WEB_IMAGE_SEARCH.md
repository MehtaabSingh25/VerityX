# Free image search (Openverse + local models)

No paid, billing-enabled or key-gated service is used or required. Google Cloud
Vision support was removed.

## Why this is not Google Lens

No legitimate free API offers Google-Lens-style whole-web reverse-image search.
Google Lens, TinEye and Bing need paid plans/billing; Yandex and similar sites
have no official API and scraping them violates their terms. Free tiers that
exist (e.g. SerpApi) need a publicly reachable image URL, which would mean
publishing evidence images, so they are not implemented.

## What VerityX does instead

`POST /api/v1/media/{media_asset_id}/web-image-search` (requires
`X-Investigation-Token`; images only, max 7 MiB):

| Body | `search_type` | How it works |
|------|---------------|--------------|
| none | `visual_similarity_search` | A local BLIP model describes the image; that text is searched on [Openverse](https://openverse.org); result thumbnails are ranked by local CLIP embedding similarity to the upload |
| `{"query": "keywords"}` | `keyword_image_search` | Openverse is searched with your keywords; the same local ranking is applied. This is a keyword search, **not** reverse-image search |

Results include `visual_similarity` (CLIP cosine, not a probability),
`visual_distance_bits` (64-bit dHash distance) and `near_duplicate`
(distance <= 6). `ranking_method` is `clip_cosine`, or `dhash` if CLIP could not
run. If the captioning model is unavailable and no keywords are given, the API
returns 503 asking for keywords; nothing is fabricated.

## Setup and costs

- Free. Openverse anonymous access has rate limits (HTTP 429 is surfaced).
- First use downloads Salesforce/blip-image-captioning-base (BSD-3-Clause) and
  openai/clip-vit-base-patch32 (MIT) into `HF_HOME` (set in `docker-compose.yml`
  to a path in the media volume). The API needs outbound access to
  huggingface.co and api.openverse.org, plus a few GB of disk; first request is slow.
- Override models with `VERITYX_CAPTION_MODEL` / `VERITYX_CLIP_MODEL`.

## Limitations

- Coverage is only openly licensed images indexed by Openverse; it cannot match
  most of the web, news, or social media. Absence of results proves nothing.
- Auto-generated search text can be wrong; results are leads, not proof of
  origin, ownership or date. Verify independently.
- Only the image text query is sent to Openverse; image bytes stay on your
  server. Thumbnails are fetched only from `*.openverse.org` over https.
