"""Allegro page parsing, target detection and URL helpers."""

import json
import math
import re
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

ALLEGRO_HOST = re.compile(r'(^|\.)allegro\.(pl|cz|sk)$', re.I)
BASE_URL = 'https://allegro.pl'
SCRIPT_RE = re.compile(r'<script[^>]*>([\s\S]*?)</script>', re.I)
BLOCKED_RE = re.compile(
    r'captcha-delivery|geo\.captcha-delivery|Please enable JS and disable any ad blocker'
    r'|Zostałeś zablokowany|datadome',
    re.I,
)


class BlockedError(RuntimeError):
    """Allegro returned an anti-bot challenge."""

    def __init__(self, message='Allegro returned an anti-bot challenge'):
        super().__init__(message)


def is_blocked_html(html=''):
    if not html:
        return True

    has_payload = (
        '__listing_StoreState' in html
        or 'formattedPrice' in html
        or 'application/ld+json' in html
    )
    if has_payload:
        return False

    return bool(BLOCKED_RE.search(html))


# --- URL helpers -----------------------------------------------------------


def _href(parts):
    return urlunsplit((parts.scheme, parts.netloc, parts.path or '/', parts.query, ''))


def url_query_param(url, name):
    for key, value in parse_qsl(urlsplit(url).query, keep_blank_values=True):
        if key == name:
            return value
    return None


def absolute_url(value):
    if not isinstance(value, str):
        return None

    href = value.strip()
    if not href:
        return None

    if href.startswith('//'):
        href = f'https:{href}'
    if href.startswith('/'):
        href = f'{BASE_URL}{href}'

    try:
        parts = urlsplit(urljoin(BASE_URL, href))
        parts.port  # raises ValueError on a malformed port
    except ValueError:
        return None
    if not parts.scheme:
        return None

    if parts.path.startswith('/events/clicks'):
        redirect = url_query_param(urlunsplit(parts), 'redirect')
        if redirect:
            return absolute_url(redirect) or _href(parts)

    return _href(parts)


def extract_offer_id(value):
    if value is None:
        return None

    raw = str(value)
    for pattern in (
        r'/oferta/(?:[^/?#]*-)?(\d{6,})(?:[/?#]|$)',
        r'[?&]offerId=(\d{6,})',
        r'(?:^|-)(\d{6,})$',
        r'^(\d{6,})$',
    ):
        match = re.search(pattern, raw, re.I)
        if match:
            return match.group(1)
    return None


def normalize_allegro_url(raw_url):
    value = str(raw_url or '').strip()
    if not value:
        raise RuntimeError('The start URL is empty.')

    if not re.match(r'^https?://', value, re.I):
        value = f'https://{re.sub(r"^/+", "", value)}'

    try:
        parts = urlsplit(value)
    except ValueError:
        raise RuntimeError(f'Invalid Allegro URL: {raw_url}') from None

    if not parts.netloc:
        raise RuntimeError(f'Invalid Allegro URL: {raw_url}')
    if not ALLEGRO_HOST.search(parts.hostname or ''):
        raise RuntimeError(
            f'Unsupported URL host: {parts.hostname}. '
            'Use an allegro.pl, allegro.cz or allegro.sk URL.'
        )

    return _href(parts)


def build_keyword_url(keyword):
    query = str(keyword or '').strip()
    if not query:
        raise RuntimeError('Provide a keyword or an Allegro URL.')
    return f'{BASE_URL}/listing?string={quote(query, safe="!~*\'()")}'


def detect_target(actor_input):
    start_url = actor_input.get('startUrl')
    keyword = actor_input.get('keyword')

    if start_url and str(start_url).strip():
        url = normalize_allegro_url(start_url)
        is_offer = re.match(r'^/(?:oferta|produkt)/', urlsplit(url).path, re.I)
        return {
            'kind': 'offer' if is_offer else 'listing',
            'url': url,
            'query': url_query_param(url, 'string') or None,
        }

    if keyword and str(keyword).strip():
        return {
            'kind': 'listing',
            'url': build_keyword_url(keyword),
            'query': str(keyword).strip(),
        }

    raise RuntimeError('Provide an Allegro URL in "startUrl" or a "keyword".')


def with_page(url, page):
    parts = urlsplit(url)
    pairs = []
    replaced = False

    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key != 'p':
            pairs.append((key, value))
        elif page > 1 and not replaced:
            pairs.append(('p', str(page)))
            replaced = True

    if page > 1 and not replaced:
        pairs.append(('p', str(page)))

    return urlunsplit((parts.scheme, parts.netloc, parts.path or '/', urlencode(pairs), ''))


def current_page(url):
    match = re.match(r'\s*([+-]?\d+)', str(url_query_param(url, 'p') or '1'))
    if not match:
        return 1
    page = int(match.group(1))
    return page if page > 0 else 1


# --- value helpers ---------------------------------------------------------


def _get(value, key):
    return value.get(key) if isinstance(value, dict) else None


def _coalesce(*values):
    for value in values:
        if value is not None:
            return value
    return None


def number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    if not isinstance(value, str):
        return None

    cleaned = re.sub(r'[\s\u00a0]', '', value)
    cleaned = re.sub(r'[^\d.,-]', '', cleaned)
    if not cleaned:
        return None

    if ',' in cleaned and '.' in cleaned:
        cleaned = cleaned.replace('.', '').replace(',', '.')
    else:
        cleaned = cleaned.replace(',', '.')

    try:
        parsed = float(cleaned)
    except ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    return int(parsed) if parsed.is_integer() else parsed


def text(value):
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r'\s+', ' ', value).strip()
    return cleaned or None


def first_value(*values):
    for value in values:
        if value is not None and value != '':
            return value
    return None


def compact_object(value):
    if not isinstance(value, dict):
        return value

    result = {}
    for key, raw in value.items():
        if raw is None:
            continue
        if isinstance(raw, bool):
            if not raw:
                continue
        elif isinstance(raw, (int, float)):
            if not math.isfinite(raw):
                continue
        elif isinstance(raw, str):
            if not raw.strip():
                continue
        elif isinstance(raw, (list, dict)) and not raw:
            continue

        result[key] = raw.strip() if isinstance(raw, str) else raw

    return result


# --- embedded JSON ---------------------------------------------------------


def read_balanced(input_text, start):
    opener = input_text[start]
    if opener == '{':
        closer = '}'
    elif opener == '[':
        closer = ']'
    else:
        return None

    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(input_text)):
        char = input_text[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue

        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return input_text[start:index + 1]

    return None


def find_json_values(html, key):
    values = []
    needle = f'"{key}"'
    cursor = 0

    while cursor < len(html):
        found = html.find(needle, cursor)
        if found == -1:
            break
        cursor = found + len(needle)

        index = cursor
        while index < len(html) and html[index].isspace():
            index += 1
        if index >= len(html) or html[index] not in (':', '='):
            continue

        index += 1
        while index < len(html) and html[index].isspace():
            index += 1
        if index >= len(html):
            break

        opener = html[index]
        if opener not in ('{', '[', '"'):
            continue

        if opener == '"':
            end = html.find('"', index + 1)
            if end == -1:
                continue
            raw = html[index:end + 1]
        else:
            raw = read_balanced(html, index)
        if not raw:
            continue

        try:
            values.append(json.loads(raw))
        except ValueError:
            continue

    return values


def _first_object(values, predicate=lambda value: True):
    for value in values:
        if isinstance(value, dict) and predicate(value):
            return value
    return None


def get_listing_state(html):
    states = find_json_values(html, '__listing_StoreState')

    direct = _first_object(
        states,
        lambda state: isinstance(state.get('items'), dict)
        and isinstance(state['items'].get('elements'), list),
    )
    if direct:
        return direct

    return _first_object(states, lambda state: isinstance(state.get('elements'), list))


def get_search_meta(html):
    candidates = find_json_values(html, 'searchMeta')
    meta = _first_object(
        candidates,
        lambda candidate: candidate.get('lastAvailablePage') is not None
        or candidate.get('totalCount') is not None
        or candidate.get('availableCount') is not None,
    )
    if meta:
        return {
            'lastAvailablePage': number(meta.get('lastAvailablePage')),
            'totalCount': number(meta.get('totalCount')),
            'availableCount': number(meta.get('availableCount')),
        }

    last_page = re.search(r'"lastAvailablePage"\s*:\s*(\d+)', html)
    total_count = re.search(r'"totalCount"\s*:\s*(\d+)', html)
    available_count = re.search(r'"availableCount"\s*:\s*(\d+)', html)

    return {
        'lastAvailablePage': int(last_page.group(1)) if last_page else None,
        'totalCount': int(total_count.group(1)) if total_count else None,
        'availableCount': int(available_count.group(1)) if available_count else None,
    }


# --- listing pages ---------------------------------------------------------


def collect_parameters(parameters):
    if not isinstance(parameters, list):
        return None

    entries = {}
    for parameter in parameters:
        name = text(_get(parameter, 'name'))
        raw_values = _get(parameter, 'values')
        values = [collected for collected in (text(str(value)) for value in raw_values) if collected] if isinstance(raw_values, list) else []
        if name and values:
            entries[name] = ', '.join(values)

    return entries or None


def map_listing_element(element, context=None):
    context = context or {}
    if not isinstance(element, dict):
        return None

    offer_id = (
        extract_offer_id(element.get('offerId'))
        or extract_offer_id(_get(element.get('eventData'), 'offer_id'))
        or extract_offer_id(element.get('url'))
        or extract_offer_id(element.get('id'))
    )
    title = (
        text(element.get('alt'))
        or text(_get(element.get('title'), 'text'))
        or text(element.get('name'))
    )
    if not offer_id or not title:
        return None

    price_node = _get(element.get('price'), 'mainPrice') or element.get('price') or {}
    if not isinstance(price_node, dict):
        price_node = {}

    price = number(_coalesce(price_node.get('amount'), price_node.get('value')))
    currency = text(price_node.get('currency'))
    crossed = _get(element.get('price'), 'crossedPrice')
    previous = _get(element.get('price'), 'previousPrice')
    original = _get(element.get('price'), 'originalPrice')
    original_price = (
        number(_get(crossed, 'amount'))
        or number(_get(previous, 'amount'))
        or number(_get(original, 'amount'))
    )
    first_photo = element.get('photos')[0] if isinstance(element.get('photos'), list) and element['photos'] else None
    image = (
        text(_get(first_photo, 'medium'))
        or text(_get(first_photo, 'url'))
        or text(element.get('mainThumbnail'))
        or text(element.get('image'))
    )

    discount_percent = None
    if price and original_price and original_price > price:
        discount_percent = int(math.floor(((original_price - price) / original_price) * 100 + 0.5))

    seller = element.get('seller')
    product_review = _get(element.get('productReview'), 'rating')
    rating_node = element.get('rating')

    return {
        'offerId': offer_id,
        'productId': text(element.get('id')),
        'title': title,
        'url': absolute_url(element.get('url')) or f'{BASE_URL}/oferta/{offer_id}',
        'price': price,
        'currency': currency,
        'originalPrice': original_price,
        'discountPercent': discount_percent,
        'image': image,
        'sellerName': text(_get(seller, 'name')) or text(_get(seller, 'login')),
        'sellerLogin': text(_get(seller, 'login')),
        'sellerRating': number(_get(seller, 'positiveFeedbackPercent')),
        'delivery': text(_get(element.get('deliveryInfo'), 'text'))
        or text(_get(element.get('delivery'), 'text')),
        'rating': number(_get(product_review, 'average'))
        or number(_get(rating_node, 'value'))
        or number(element.get('ratingValue')),
        'reviewsCount': number(_get(product_review, 'count'))
        or number(_get(rating_node, 'count'))
        or number(element.get('reviewsCount')),
        'condition': text(element.get('condition')),
        'parameters': collect_parameters(element.get('parameters')),
        'isSponsored': bool(element.get('isSponsored') or element.get('sponsored')),
        'isPromoted': bool(element.get('promoted')) or element.get('context') == 'PROMOTED',
        'page': context.get('page'),
        'query': context.get('query'),
        'listingUrl': context.get('listingUrl'),
    }


def parse_listing_html(html, context=None):
    context = context or {}

    if is_blocked_html(html) and '__listing_StoreState' not in html:
        return {'items': [], 'meta': {}, 'blocked': True}

    state = get_listing_state(html)
    meta = get_search_meta(html)

    elements = []
    if isinstance(state, dict):
        if isinstance(_get(state.get('items'), 'elements'), list):
            elements = state['items']['elements']
        elif isinstance(state.get('elements'), list):
            elements = state['elements']

    items = [item for item in (map_listing_element(element, context) for element in elements) if item]
    return {'items': items, 'meta': meta, 'blocked': False}


# --- offer pages -----------------------------------------------------------


def deep_find(value, keys, depth=0):
    if not isinstance(value, (dict, list)) or depth > 8:
        return None

    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if candidate is not None and not isinstance(candidate, (dict, list)):
                return candidate
        children = value.values()
    else:
        children = value

    for child in children:
        found = deep_find(child, keys, depth + 1)
        if found is not None:
            return found

    return None


def deep_find_value(value, key, depth=0):
    if not isinstance(value, (dict, list)) or depth > 10:
        return None

    if isinstance(value, dict):
        if key in value:
            return value[key]
        children = value.values()
    else:
        children = value

    for child in children:
        found = deep_find_value(child, key, depth + 1)
        if found is not None:
            return found

    return None


def deep_find_parent(value, key, depth=0):
    if not isinstance(value, (dict, list)) or depth > 10:
        return None

    if isinstance(value, dict):
        if key in value:
            return value
        children = value.values()
    else:
        children = value

    for child in children:
        found = deep_find_parent(child, key, depth + 1)
        if found is not None:
            return found

    return None


def parse_json_scripts(html):
    results = []
    for match in SCRIPT_RE.finditer(html):
        body = match.group(1).strip()
        if not body.startswith(('{', '[')):
            continue
        try:
            results.append(json.loads(body))
        except ValueError:
            continue
    return results


def find_product_json_ld(values):
    queue = list(values)
    index = 0

    while index < len(queue):
        candidate = queue[index]
        index += 1

        if isinstance(candidate, list):
            queue.extend(candidate)
            continue
        if not isinstance(candidate, dict):
            continue

        types = candidate.get('@type')
        types = types if isinstance(types, list) else [types]
        if any(str(value).lower() == 'product' for value in types):
            return candidate
        if candidate.get('@graph') is not None:
            queue.append(candidate['@graph'])

    return None


def _entries(items, name_key, value_key):
    entries = []
    for item in items:
        name = text(_get(item, name_key))
        value = text(_get(item, value_key))
        if name and value:
            entries.append((name, value))
    return entries


def parse_offer_html(html, context=None):
    context = context or {}

    if is_blocked_html(html) and 'formattedPrice' not in html and 'application/ld+json' not in html:
        return {'item': None, 'blocked': True}

    scripts = parse_json_scripts(html)

    price_value = deep_find_value(scripts, 'formattedPrice')
    price_parent = deep_find_parent(scripts, 'formattedPrice')
    price_node = price_value if isinstance(price_value, dict) else price_parent
    if not isinstance(price_node, dict):
        price_node = {}

    seller_value = deep_find_value(scripts, 'sellerName')
    seller_parent = deep_find_parent(scripts, 'sellerName')
    seller_data = (
        seller_value
        if seller_value is not None
        else seller_parent if seller_parent is not None else deep_find_value(scripts, 'seller')
    )

    rating_value = deep_find_value(scripts, 'aggregateRating')
    rating_parent = deep_find_parent(scripts, 'aggregateRating')
    rating_data = rating_value if isinstance(rating_value, dict) else rating_parent

    gallery_value = deep_find_value(scripts, 'galleryItems')
    gallery_parent = deep_find_parent(scripts, 'galleryItems')
    gallery_data = (
        gallery_value
        if isinstance(gallery_value, list)
        else _get(gallery_parent, 'galleryItems')
    )

    product = find_product_json_ld(scripts) or {}
    offers = _get(product, 'offers')
    offer = offers[0] if isinstance(offers, list) and offers else offers
    if not isinstance(offer, dict):
        offer = {}

    price = number(
        first_value(
            price_node.get('amount'),
            price_node.get('value'),
            price_node.get('formattedPrice'),
            offer.get('price'),
            offer.get('lowPrice'),
            deep_find(rating_data, ['price']),
        )
    )
    currency = text(
        first_value(
            price_node.get('currency'),
            offer.get('priceCurrency'),
            deep_find(product, ['priceCurrency']),
        )
    )

    gallery = []
    if isinstance(gallery_data, list):
        for entry in gallery_data:
            url = text(_get(entry, 'thumbnail')) or text(_get(entry, 'url'))
            if url:
                gallery.append(url)

    raw_images = _get(product, 'image')
    json_ld_images = raw_images if isinstance(raw_images, list) else [raw_images]
    images = gallery or [
        text(image) if isinstance(image, str) else text(_get(image, 'url'))
        for image in json_ld_images
    ]
    images = [image for image in images if image]

    offer_id = (
        extract_offer_id(context.get('url'))
        or extract_offer_id(_get(product, 'sku'))
        or extract_offer_id(_get(product, 'productID'))
        or extract_offer_id(context.get('offerId'))
    )

    seller_name = text(
        first_value(
            seller_data if isinstance(seller_data, str) else _get(seller_data, 'sellerName'),
            _get(seller_data, 'name'),
            deep_find(seller_data, ['sellerName', 'name']),
            _get(_get(offer, 'seller'), 'name'),
            _get(_get(product, 'brand'), 'name'),
        )
    )

    specifications = deep_find_value(scripts, 'specifications')
    specification_entries = _entries(specifications, 'key', 'value') if isinstance(specifications, list) else []

    additional = _get(product, 'additionalProperty')
    addon_entries = _entries(additional, 'name', 'value') if isinstance(additional, list) else []

    parameter_entries = addon_entries or specification_entries
    condition = text(_get(product, 'itemCondition'))
    aggregate = _get(product, 'aggregateRating')

    item = {
        'offerId': offer_id,
        'title': text(_get(product, 'name'))
        or text(deep_find(price_node, ['offerTitle', 'productName'])),
        'url': context.get('url'),
        'price': price,
        'currency': currency,
        'originalPrice': number(
            first_value(
                price_node.get('originalPrice'),
                price_node.get('crossedPrice'),
                price_node.get('regularPrice'),
                deep_find(price_node, ['originalPrice', 'crossedPrice', 'regularPrice']),
            )
        ),
        'image': images[0] if images else None,
        'images': images if len(images) > 1 else None,
        'sellerName': seller_name,
        'sellerLogin': seller_name,
        'sellerRating': number(
            first_value(_get(seller_data, 'rating'), deep_find(seller_data, ['rating']))
        ),
        'rating': number(
            first_value(
                _get(rating_data, 'ratingValue'),
                _get(aggregate, 'ratingValue'),
                deep_find(rating_data, ['ratingValue']),
            )
        ),
        'reviewsCount': number(
            first_value(
                _get(rating_data, 'reviewCount'),
                _get(rating_data, 'ratingCount'),
                _get(aggregate, 'reviewCount'),
                deep_find(rating_data, ['reviewCount', 'ratingCount']),
            )
        ),
        'condition': condition.replace('https://schema.org/', '') if condition else None,
        'parameters': dict(parameter_entries) if parameter_entries else None,
        'page': 1,
        'query': context.get('query'),
        'listingUrl': context.get('url'),
    }

    return {'item': item if item['title'] else None, 'blocked': False}
