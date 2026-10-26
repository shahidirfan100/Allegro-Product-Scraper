# Allegro API discovery

## Selected source

- Target: `allegro.pl` listing, category, and offer pages.
- Listing data: `__listing_StoreState` JSON embedded in the search page, plus `searchMeta`.
- Offer data: `formattedPrice`, `sellerName`, `aggregateRating`, and `galleryItems` JSON blocks, with JSON-LD `Product` as a fallback.
- Method: `GET` the public page URL.
- Auth: none.
- Pagination: `p` query parameter, `searchMeta.lastAvailablePage`, about 60 offers per page.
- Fields available: offer ID, product ID, title, URL, price, currency, original price, image, seller login, seller rating, delivery, rating, review count, parameters, sponsored and promoted flags.
- Fields missing in the old actor: all of the above. The old template collected jobs from Remote.co.

The page ships its listing state as JSON. The Actor reads that JSON directly. It does not parse visible listing markup or CSS classes.

## Evidence matrix

| Candidate | Result | Decision |
|---|---|---|
| Official `GET https://api.allegro.pl/offers/listing` | `406 Not Acceptable` without the vendor media type; `403 VerificationRequired` with it. Allegro has suspended access for new applications. | Rejected. No usable token path. |
| Direct `impit` request without a proxy | `403` DataDome block page | Rejected. |
| `impit` through Polish residential sessions | `403` DataDome block page across 12 sessions | Rejected as the only path. |
| `impit` through `UNBLOCKER` | `407 Proxy authentication required`; the group is not provisioned on this account | Rejected. |
| `impit` through `StaticUS3` | `200` with `__listing_StoreState` on keyword and offer URLs; intermittent body timeouts on long pages | Optional fast path when a proxy is configured. |
| Playwright Firefox, headless and headful | `403` DataDome interstitial or captcha | Rejected. |
| Camoufox Firefox with residential proxy | `403` DataDome block page, with and without image blocking | Rejected. |
| Patchright Chrome, headful, no proxy, on Apify | `200` with 200 offers across four listing pages in one run | Selected default path. |
| Patchright Chrome, headful, bundled Chromium, StaticUS3 | `200` with 73 to 97 offers; listing, category, pagination, and offer pages all returned data | Optional path when a proxy is configured. |

## Why Patchright

Patchright passed DataDome from the Apify run without a proxy and with the optional `StaticUS3` group, while Playwright Firefox, Camoufox, direct HTTP, and residential sessions did not. The browser runs headful under the Apify Playwright Chrome image, which starts Xvfb through its entrypoint. The browser is used to obtain the page response and its embedded JSON, not to scrape DOM selectors.

## Request context

- No proxy is used by default. The browser fetcher runs directly, which is the tested Apify path.
- When a proxy is configured, one proxy session is bound to one browser context so the DataDome cookie and IP stay aligned.
- `impit` is tried first only when a proxy is configured. It has a 30 second timeout.
- When HTTP is blocked or no proxy is configured, the browser loads the URL. A hard block page is reloaded in the same context. If DataDome rewrites the search phrase from `%20` to `%2B`, the requested URL is loaded again and the page is accepted only when the decoded `string` parameter matches.
- The actor rotates the browser profile after a failed browser attempt and retries up to four times. If a proxy is configured, it rotates both the proxy session and the browser profile. No-proxy runs can receive an intermittent DataDome challenge, and a fresh profile usually clears it.
- Listing pages are accepted only when mapped offers exist, or when `availableCount` is zero.
- If no offers are saved while `availableCount` is above zero, the run fails instead of returning an empty successful dataset.
