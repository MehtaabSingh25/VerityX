# Public web image search (SerpApi Google Lens + free fallback)

When `SERPAPI_API_KEY` is configured, VerityX compresses the evidence image to a JPEG no larger than 500 KB, uploads it to SerpApi, and uses the returned temporary image ID to search Google Lens. Without the key, it uses Openverse and its Wikimedia Commons fallback. If SerpApi fails, the service attempts the free indexes and includes a fallback notice.

## Configure

Add `SERPAPI_API_KEY=your-key` to the root `.env` used by Docker Compose, then rebuild/restart the API. Never commit the real key or expose it to the frontend. SerpApi image IDs expire after 10 minutes. The uploaded evidence image is sent to SerpApi for processing, so only use images you are authorized to share.

Google Lens results are leads, not proof of identity, source, ownership, or date. Verify source pages independently. Without SerpApi, results are limited to openly indexed images and are not a whole-web reverse-image search.
