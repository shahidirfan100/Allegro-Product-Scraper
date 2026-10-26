## What does Allegro Product Scraper do?

Allegro Product Scraper collects product offers from Allegro.pl, a large Polish online marketplace. Add an Allegro listing, category, or offer URL, or enter a keyword, and receive a structured dataset with titles, prices, sellers, ratings, images, delivery details, and offer links. The Actor is built for price monitoring, assortment research, seller analysis, and product data pipelines.

## Why use Allegro Product Scraper?

- **Offer-level data** - Collect title, price, seller, rating, image, delivery text, and parameters in one dataset.
- **URL or keyword input** - Start from an existing Allegro search, category page, or single offer, or let the Actor build a search from a phrase.
- **Pagination built in** - Follow listing pages until the requested result count or page cap is reached.
- **No empty fields** - Empty and unavailable fields are left out instead of filling the dataset with null values.
- **Apify exports and schedules** - Download CSV, Excel, JSON, or XML, run the Actor on a schedule, and call it through the API.

## What data can you extract from Allegro?

| Field | Description |
|-------|-------------|
| `offerId` | Allegro offer identifier |
| `productId` | Allegro catalogue product identifier when available |
| `title` | Offer title |
| `url` | Direct offer URL |
| `price` | Current price as a number |
| `currency` | Price currency, usually PLN |
| `originalPrice` | Earlier or crossed-out price when shown |
| `discountPercent` | Calculated discount percentage |
| `image` | Main product image URL |
| `images` | Additional product image URLs from offer pages |
| `sellerName` | Seller or shop name |
| `sellerLogin` | Seller account login |
| `sellerRating` | Seller positive feedback percentage |
| `delivery` | Delivery text shown on the listing |
| `rating` | Product or seller rating when available |
| `reviewsCount` | Rating or review count when available |
| `condition` | Item condition from offer data |
| `parameters` | Product parameters such as brand, model, or size |
| `isSponsored` | Marks sponsored offers |
| `isPromoted` | Marks promoted offers |
| `position` | Position in the saved result set |
| `page` | Listing page where the offer was found |
| `query` | Search phrase or category tied to the result |
| `listingUrl` | Listing page URL where the offer appeared |
| `scrapedAt` | ISO timestamp for the run |

## How to use Allegro Product Scraper

1. Open the Actor on Apify Store.
2. Paste an Allegro listing, category, or offer URL in **Allegro URL**, or leave it empty and enter a **Keyword**.
3. Set **Maximum results** and **Maximum pages** for the run.
4. Leave the proxy field empty for a normal run. Add an Apify Proxy group or your own proxy URLs only if Allegro challenges the run.
5. Run the Actor and open the dataset when the run finishes.

When both an Allegro URL and a keyword are present, the URL wins. The keyword is ignored.

## Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `startUrl` | String | No | - | Allegro listing, category, or offer URL. Takes priority over `keyword`. |
| `keyword` | String | No | `tabletki do zmywarki` | Search phrase used when no URL is provided. |
| `results_wanted` | Integer | No | `20` | Maximum number of offers to save. |
| `max_pages` | Integer | No | `10` | Maximum listing pages to request, starting from the page in the URL. |
| `proxyConfiguration` | Object | No | No proxy | Optional proxy settings for challenged runs. |

## Output Data

| Field | Type | Description |
|-------|------|-------------|
| `offerId` | String | Allegro offer identifier |
| `productId` | String | Catalogue product identifier |
| `title` | String | Offer title |
| `url` | String | Direct offer URL |
| `price` | Number | Current price |
| `currency` | String | Price currency |
| `originalPrice` | Number | Price before a discount |
| `discountPercent` | Number | Discount percentage |
| `image` | String | Main image URL |
| `images` | Array | Additional image URLs |
| `sellerName` | String | Seller or shop name |
| `sellerLogin` | String | Seller account login |
| `sellerRating` | Number | Seller positive feedback percentage |
| `delivery` | String | Delivery information |
| `rating` | Number | Product or seller rating |
| `reviewsCount` | Number | Rating or review count |
| `condition` | String | Item condition |
| `parameters` | Object | Product parameter names and values |
| `isSponsored` | Boolean | Sponsored offer marker |
| `isPromoted` | Boolean | Promoted offer marker |
| `position` | Number | Position in the saved result set |
| `page` | Number | Listing page |
| `query` | String | Search phrase or category |
| `listingUrl` | String | Listing page URL |
| `scrapedAt` | String | ISO timestamp for the run |

## Usage Examples

### Scrape a keyword

Collect offers for a product phrase. The Actor starts from page one and saves up to 20 offers.

```json
{
  "keyword": "tabletki do zmywarki",
  "results_wanted": 20,
  "max_pages": 2
}
```

### Scrape an existing listing URL

Keep the filters, sorting, and search phrase from an Allegro listing URL. The URL takes priority over the keyword.

```json
{
  "startUrl": "https://allegro.pl/listing?string=tabletki%20do%20zmywarki&order=p",
  "results_wanted": 60,
  "max_pages": 3
}
```

### Scrape a single offer

Use an offer URL to collect one product with its current price, images, seller, rating, and specifications.

```json
{
  "startUrl": "https://allegro.pl/oferta/plyta-glowna-socket-am5-asus-b650e-max-gaming-wifi-atx-18023243417",
  "results_wanted": 1,
  "max_pages": 1
}
```

### Use your own proxy

Add custom proxy URLs only when a run needs a different exit IP.

```json
{
  "keyword": "tabletki do zmywarki",
  "results_wanted": 40,
  "max_pages": 2,
  "proxyConfiguration": {
    "useApifyProxy": false,
    "proxyUrls": ["http://username:password@proxy.example.com:8080"]
  }
}
```

## Sample Output

```json
{
  "offerId": "17456011011",
  "productId": "86dd1453-ad25-496e-a968-f5e220cccad6",
  "title": "Tabletki do zmywarki 100 szt.",
  "url": "https://allegro.pl/oferta/tabletki-do-zmywarki-100-szt-17456011011",
  "price": 29.99,
  "currency": "PLN",
  "originalPrice": 39.99,
  "discountPercent": 25,
  "image": "https://a.allegroimg.com/s512/11994d/2eb7c6664a76a996a4212c358bc9/tabletki-do-zmywarki",
  "sellerName": "sklep_domowy",
  "sellerLogin": "sklep_domowy",
  "sellerRating": 99.6,
  "delivery": "Dostawa od 9,99 zł",
  "rating": 4.8,
  "reviewsCount": 1234,
  "parameters": {
    "Marka": "Domol",
    "Liczba sztuk": "100"
  },
  "position": 1,
  "page": 1,
  "query": "tabletki do zmywarki",
  "listingUrl": "https://allegro.pl/listing?string=tabletki%20do%20zmywarki",
  "scrapedAt": "2026-10-25T18:30:00.000Z"
}
```

## Tips for Best Results

- Start with a small `results_wanted` value to confirm the URL and page settings.
- Use a complete Allegro listing URL when you need exact filters, sorting, or a category.
- Allegro returns about 60 offers per listing page and limits deep pagination, so very large runs should use several narrower searches.
- The Actor runs without a proxy by default. Add a proxy group only if Allegro challenges the run.
- If a run is challenged, switch to another proxy group in your Apify account before increasing the result limit.
- Some fields are missing when the source page does not publish them. Check several offers before assuming a field is broken.
- Use the URL of the listing page, not a browser-specific or shortened link.

## Integrations

- **Google Sheets** - Export results to a spreadsheet for price tracking.
- **Webhooks** - Trigger a workflow when a run finishes.
- **Make or Zapier** - Send offers to no-code automations.
- **API** - Read datasets from your own application or dashboard.
- **CSV, Excel, JSON, XML** - Download the dataset in the format your team uses.

## Frequently Asked Questions

### Can I scrape an Allegro search by keyword?

Yes. Leave **Allegro URL** empty and enter a keyword. The Actor builds a listing search, follows pages, and saves the requested number of offers.

### Does an Allegro URL override the keyword?

Yes. When both fields contain a value, the URL wins and the keyword is ignored. Clear the URL field to run a keyword search.

### How many offers can one run collect?

Each Allegro listing page contains about 60 offers. `results_wanted` caps the saved records, and `max_pages` caps how many pages the Actor requests. Allegro also limits how deep its listing pagination goes.

### Can I collect a single product offer?

Yes. Paste an offer URL such as `https://allegro.pl/oferta/...` and run the Actor. It returns one detailed record for that offer.

### Why are some fields missing?

Allegro does not publish every field on every page. For example, a listing card may not show a rating, and an offer may not have a catalogue product ID. Missing fields are omitted from the record.

### Why do I get fewer results than requested?

The search may have fewer matching offers, the page cap may be reached, or Allegro may challenge some requests. Check the run log and try a narrower search. If a challenge repeats, add a proxy group and run again.

### Can I run this Actor on a schedule?

Yes. Create a schedule in Apify Console to refresh prices daily, hourly, or at another interval.

### Can I export the dataset to CSV or Excel?

Yes. Apify datasets can be downloaded as CSV, Excel, JSON, XML, and other supported formats.

### Do I need a proxy?

No. The Actor runs without a proxy by default and handles Allegro's challenge in the browser. Add an Apify Proxy group or your own proxy URLs if a run is challenged repeatedly.

### Do I need to write code to run the Actor?

No. Run it from Apify Console with a URL or keyword, a result limit, and a page limit. You can download the dataset when the run finishes.

## Support

For issues, feature requests, or custom Actor work, use the Issues tab on the Actor page or contact the developer through Apify.

## Legal Notice

This Actor is designed for legitimate collection of publicly available product data. Users are responsible for complying with applicable laws, Allegro's terms, and data protection rules. Do not use the Actor to overload the website or to collect personal data without a lawful basis.
