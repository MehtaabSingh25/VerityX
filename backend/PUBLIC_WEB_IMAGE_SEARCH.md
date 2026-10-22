# Public-web image search

VerityX can query Google Cloud Vision's Web Detection feature for indexed pages
containing a matching image, exact/partial image matches, visually similar
image URLs, and associated web entities. This is an external provider integration;
it is not a crawl of the entire internet and results depend on provider indexing.

## Configuration

1. Enable the Cloud Vision API in a Google Cloud project.
2. Create an API key restricted to the Cloud Vision API and configure billing/quota.
3. Set `GOOGLE_CLOUD_VISION_API_KEY` in the API container's environment.
4. Restart the API container.

Example `.env` entry (keep the real value private):

```dotenv
GOOGLE_CLOUD_VISION_API_KEY=replace-with-your-restricted-key
```

## API

`POST /api/v1/media/{media_asset_id}/web-image-search`

Supply the `X-Investigation-Token` header for the investigation that owns the
media. The endpoint accepts stored images only; the image must be at most 7 MiB.
The response contains `pages_with_matching_images`, `visually_similar_image_urls`,
`full_matching_image_urls`, `partial_matching_image_urls`, and `web_entities`.

## Evidence limitations and privacy

- Search results are leads, not proof of authorship, first publication, copyright,
  or authenticity. Preserve and independently verify any candidate source.
- A no-match result means only that the provider returned no indexed match.
- Image bytes are sent to Google Cloud Vision for processing. Do not submit
  sensitive or restricted media unless your policies permit that transfer.
- API usage may incur charges and is subject to Google Cloud quotas and terms.
