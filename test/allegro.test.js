import { describe, expect, it } from 'vitest';

import {
    compactObject,
    detectTarget,
    parseListingHtml,
    parseOfferHtml,
    withPage,
} from '../src/allegro.js';

const listingHtml = `<!doctype html><html><head></head><body>
<script type="application/json">{"__listing_StoreState":{"items":{"elements":[
  {
    "id":"0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
    "offerId":"17456011011",
    "alt":"Tabletki do zmywarki 100 szt.",
    "url":"https://allegro.pl/oferta/tabletki-do-zmywarki-100-szt-17456011011",
    "price":{"mainPrice":{"amount":"29,99","currency":"PLN"},"crossedPrice":{"amount":"39,99"}},
    "photos":[{"medium":"https://a.allegroimg.com/s512/abc"}],
    "seller":{"title":"Firma","login":"sklep_domowy","positiveFeedbackPercent":99.6},
    "deliveryInfo":{"text":"Dostawa od 9,99 zł"},
    "productReview":{"rating":{"average":"4,8","count":"1234"}},
    "parameters":[{"name":"Marka","values":["Domol"]},{"name":"Liczba sztuk","values":["100"]}]
  },
  {
    "offerId":17456011011,
    "alt":"Tabletki do zmywarki 100 szt.",
    "url":"/events/clicks?redirect=https%3A%2F%2Fallegro.pl%2Foferta%2Ftabletki-17456011011",
    "price":{"mainPrice":{"amount":"29,99","currency":"PLN"}},
    "context":"PROMOTED"
  },
  {"alt":"Banner without an offer","url":"https://allegro.pl/listing"}
]}}}</script>
<script data-serialize-box-id="box-1">{"props":{"searchMeta":{"lastAvailablePage":3,"totalCount":120,"availableCount":60}}}</script>
</body></html>`;

const offerHtml = `<!doctype html><html><head></head><body>
<script>{"price":{"formattedPrice":"29,99 zł","amount":"29,99","currency":"PLN"}}</script>
<script>{"sellerName":"Sklep Domowy"}</script>
<script>{"aggregateRating":{"ratingValue":4.8,"reviewCount":123}}</script>
<script>{"galleryItems":[{"thumbnail":"https://a.allegroimg.com/s512/one"},{"thumbnail":"https://a.allegroimg.com/s512/two"}]}</script>
<script type="application/ld+json">{"@type":"Product","name":"Tabletki do zmywarki 100 szt.","itemCondition":"https://schema.org/NewCondition","offers":{"price":"29.99","priceCurrency":"PLN"},"additionalProperty":[{"name":"Marka","value":"Domol"}]}</script>
</body></html>`;

describe('target detection', () => {
    it('gives a start URL priority over a keyword', () => {
        const target = detectTarget({
            startUrl: 'allegro.pl/listing?string=tabletki',
            keyword: 'ignored',
        });

        expect(target.kind).toBe('listing');
        expect(target.url).toBe('https://allegro.pl/listing?string=tabletki');
        expect(target.query).toBe('tabletki');
    });

    it('detects offer URLs', () => {
        const target = detectTarget({
            startUrl: 'https://allegro.pl/oferta/tabletki-do-zmywarki-17456011011',
        });

        expect(target.kind).toBe('offer');
    });

    it('builds a keyword URL when no URL is given', () => {
        const target = detectTarget({ keyword: 'tabletki do zmywarki' });

        expect(target.kind).toBe('listing');
        expect(target.url).toContain('string=tabletki%20do%20zmywarki');
    });

    it('rejects non-Allegro hosts', () => {
        expect(() => detectTarget({ startUrl: 'https://example.com/listing' })).toThrow(
            /Unsupported URL host/,
        );
    });
});

describe('listing parsing', () => {
    it('reads the embedded offer state and search metadata', () => {
        const result = parseListingHtml(listingHtml, {
            page: 2,
            query: 'tabletki do zmywarki',
            listingUrl: 'https://allegro.pl/listing?string=tabletki+do+zmywarki&p=2',
        });

        expect(result.blocked).toBe(false);
        expect(result.meta).toEqual({
            lastAvailablePage: 3,
            totalCount: 120,
            availableCount: 60,
        });
        expect(result.items).toHaveLength(2);
        expect(result.items[0]).toMatchObject({
            offerId: '17456011011',
            title: 'Tabletki do zmywarki 100 szt.',
            price: 29.99,
            currency: 'PLN',
            originalPrice: 39.99,
            discountPercent: 25,
            sellerName: 'sklep_domowy',
            sellerLogin: 'sklep_domowy',
            sellerRating: 99.6,
            rating: 4.8,
            reviewsCount: 1234,
            page: 2,
            query: 'tabletki do zmywarki',
        });
        expect(result.items[0].parameters).toEqual({
            Marka: 'Domol',
            'Liczba sztuk': '100',
        });
        expect(result.items[1].url).toBe(
            'https://allegro.pl/oferta/tabletki-17456011011',
        );
        expect(result.items[1].isPromoted).toBe(true);
    });

    it('flags a DataDome challenge as blocked', () => {
        const result = parseListingHtml('<html><body>Please enable JS and disable any ad blocker</body></html>');

        expect(result.blocked).toBe(true);
        expect(result.items).toEqual([]);
    });
});

describe('offer parsing', () => {
    it('reads structured offer data from JSON blocks and JSON-LD', () => {
        const result = parseOfferHtml(offerHtml, {
            url: 'https://allegro.pl/oferta/tabletki-do-zmywarki-17456011011',
            query: 'tabletki do zmywarki',
        });

        expect(result.blocked).toBe(false);
        expect(result.item).toMatchObject({
            offerId: '17456011011',
            title: 'Tabletki do zmywarki 100 szt.',
            price: 29.99,
            currency: 'PLN',
            sellerName: 'Sklep Domowy',
            rating: 4.8,
            reviewsCount: 123,
            condition: 'NewCondition',
        });
        expect(result.item.images).toEqual([
            'https://a.allegroimg.com/s512/one',
            'https://a.allegroimg.com/s512/two',
        ]);
        expect(result.item.parameters).toEqual({ Marka: 'Domol' });
    });

    it('falls back to formatted prices, seller names and specifications', () => {
        const html = `<script>{"price":{"formattedPrice":"579,00 zł","currency":"PLN"}}</script>
<script>{"seller":{"name":"X-KOM_PL"}}</script>
<script>{"aggregateRating":{"ratingValue":4.92,"ratingCount":37}}</script>
<script>{"specifications":[{"key":"Gniazdo procesora","value":"Socket AM5"}]}</script>
<script type="application/ld+json">{"@type":"Product","name":"ASUS B650E"}</script>`;

        const result = parseOfferHtml(html, { url: 'https://allegro.pl/oferta/18023243417' });

        expect(result.item).toMatchObject({
            offerId: '18023243417',
            title: 'ASUS B650E',
            price: 579,
            currency: 'PLN',
            sellerName: 'X-KOM_PL',
            rating: 4.92,
            reviewsCount: 37,
            parameters: { 'Gniazdo procesora': 'Socket AM5' },
        });
    });
});

describe('pagination and cleaning', () => {
    it('preserves filters and replaces the page parameter', () => {
        const url = 'https://allegro.pl/listing?string=tabletki&order=p&p=4';
        expect(withPage(url, 1)).toBe(
            'https://allegro.pl/listing?string=tabletki&order=p',
        );
        expect(withPage(url, 7)).toContain('p=7');
        expect(withPage(url, 7)).toContain('order=p');
    });

    it('removes empty, null and false values from records', () => {
        const cleaned = compactObject({
            offerId: '1',
            title: 'Offer',
            price: 0,
            sellerName: null,
            delivery: '',
            parameters: {},
            isSponsored: false,
            position: 1,
        });

        expect(cleaned).toEqual({
            offerId: '1',
            title: 'Offer',
            price: 0,
            position: 1,
        });
    });
});
