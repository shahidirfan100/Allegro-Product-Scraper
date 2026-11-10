import unittest

from src.allegro import (
    compact_object,
    detect_target,
    parse_listing_html,
    parse_offer_html,
    with_page,
)

LISTING_HTML = """<!doctype html><html><head></head><body>
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
</body></html>"""

OFFER_HTML = """<!doctype html><html><head></head><body>
<script>{"price":{"formattedPrice":"29,99 zł","amount":"29,99","currency":"PLN"}}</script>
<script>{"sellerName":"Sklep Domowy"}</script>
<script>{"aggregateRating":{"ratingValue":4.8,"reviewCount":123}}</script>
<script>{"galleryItems":[{"thumbnail":"https://a.allegroimg.com/s512/one"},{"thumbnail":"https://a.allegroimg.com/s512/two"}]}</script>
<script type="application/ld+json">{"@type":"Product","name":"Tabletki do zmywarki 100 szt.","itemCondition":"https://schema.org/NewCondition","offers":{"price":"29.99","priceCurrency":"PLN"},"additionalProperty":[{"name":"Marka","value":"Domol"}]}</script>
</body></html>"""


class TargetDetectionTest(unittest.TestCase):
    def test_start_url_has_priority_over_keyword(self):
        target = detect_target({'startUrl': 'allegro.pl/listing?string=tabletki', 'keyword': 'ignored'})

        self.assertEqual(target['kind'], 'listing')
        self.assertEqual(target['url'], 'https://allegro.pl/listing?string=tabletki')
        self.assertEqual(target['query'], 'tabletki')

    def test_detects_offer_urls(self):
        target = detect_target({'startUrl': 'https://allegro.pl/oferta/tabletki-do-zmywarki-17456011011'})
        self.assertEqual(target['kind'], 'offer')

    def test_builds_keyword_url_when_no_url_given(self):
        target = detect_target({'keyword': 'tabletki do zmywarki'})

        self.assertEqual(target['kind'], 'listing')
        self.assertIn('string=tabletki%20do%20zmywarki', target['url'])

    def test_rejects_non_allegro_hosts(self):
        with self.assertRaisesRegex(RuntimeError, 'Unsupported URL host'):
            detect_target({'startUrl': 'https://example.com/listing'})


class ListingParsingTest(unittest.TestCase):
    def test_reads_embedded_offer_state_and_search_metadata(self):
        result = parse_listing_html(
            LISTING_HTML,
            {
                'page': 2,
                'query': 'tabletki do zmywarki',
                'listingUrl': 'https://allegro.pl/listing?string=tabletki+do+zmywarki&p=2',
            },
        )

        self.assertFalse(result['blocked'])
        self.assertEqual(
            result['meta'],
            {'lastAvailablePage': 3, 'totalCount': 120, 'availableCount': 60},
        )
        self.assertEqual(len(result['items']), 2)

        first = result['items'][0]
        for key, value in {
            'offerId': '17456011011',
            'title': 'Tabletki do zmywarki 100 szt.',
            'price': 29.99,
            'currency': 'PLN',
            'originalPrice': 39.99,
            'discountPercent': 25,
            'sellerName': 'sklep_domowy',
            'sellerLogin': 'sklep_domowy',
            'sellerRating': 99.6,
            'rating': 4.8,
            'reviewsCount': 1234,
            'page': 2,
            'query': 'tabletki do zmywarki',
        }.items():
            self.assertEqual(first[key], value, key)

        self.assertEqual(first['parameters'], {'Marka': 'Domol', 'Liczba sztuk': '100'})
        self.assertEqual(
            result['items'][1]['url'],
            'https://allegro.pl/oferta/tabletki-17456011011',
        )
        self.assertTrue(result['items'][1]['isPromoted'])

    def test_flags_a_datadome_challenge_as_blocked(self):
        result = parse_listing_html(
            '<html><body>Please enable JS and disable any ad blocker</body></html>'
        )

        self.assertTrue(result['blocked'])
        self.assertEqual(result['items'], [])


class OfferParsingTest(unittest.TestCase):
    def test_reads_structured_offer_data_from_json_blocks_and_json_ld(self):
        result = parse_offer_html(
            OFFER_HTML,
            {
                'url': 'https://allegro.pl/oferta/tabletki-do-zmywarki-17456011011',
                'query': 'tabletki do zmywarki',
            },
        )

        self.assertFalse(result['blocked'])
        item = result['item']
        for key, value in {
            'offerId': '17456011011',
            'title': 'Tabletki do zmywarki 100 szt.',
            'price': 29.99,
            'currency': 'PLN',
            'sellerName': 'Sklep Domowy',
            'rating': 4.8,
            'reviewsCount': 123,
            'condition': 'NewCondition',
        }.items():
            self.assertEqual(item[key], value, key)

        self.assertEqual(
            item['images'],
            ['https://a.allegroimg.com/s512/one', 'https://a.allegroimg.com/s512/two'],
        )
        self.assertEqual(item['parameters'], {'Marka': 'Domol'})

    def test_falls_back_to_formatted_prices_seller_names_and_specifications(self):
        html = """<script>{"price":{"formattedPrice":"579,00 zł","currency":"PLN"}}</script>
<script>{"seller":{"name":"X-KOM_PL"}}</script>
<script>{"aggregateRating":{"ratingValue":4.92,"ratingCount":37}}</script>
<script>{"specifications":[{"key":"Gniazdo procesora","value":"Socket AM5"}]}</script>
<script type="application/ld+json">{"@type":"Product","name":"ASUS B650E"}</script>"""

        result = parse_offer_html(html, {'url': 'https://allegro.pl/oferta/18023243417'})

        item = result['item']
        for key, value in {
            'offerId': '18023243417',
            'title': 'ASUS B650E',
            'price': 579,
            'currency': 'PLN',
            'sellerName': 'X-KOM_PL',
            'rating': 4.92,
            'reviewsCount': 37,
            'parameters': {'Gniazdo procesora': 'Socket AM5'},
        }.items():
            self.assertEqual(item[key], value, key)


class PaginationAndCleaningTest(unittest.TestCase):
    def test_preserves_filters_and_replaces_the_page_parameter(self):
        url = 'https://allegro.pl/listing?string=tabletki&order=p&p=4'

        self.assertEqual(
            with_page(url, 1),
            'https://allegro.pl/listing?string=tabletki&order=p',
        )
        self.assertIn('p=7', with_page(url, 7))
        self.assertIn('order=p', with_page(url, 7))

    def test_removes_empty_null_and_false_values_from_records(self):
        cleaned = compact_object(
            {
                'offerId': '1',
                'title': 'Offer',
                'price': 0,
                'sellerName': None,
                'delivery': '',
                'parameters': {},
                'isSponsored': False,
                'position': 1,
            }
        )

        self.assertEqual(
            cleaned,
            {'offerId': '1', 'title': 'Offer', 'price': 0, 'position': 1},
        )


if __name__ == '__main__':
    unittest.main()
