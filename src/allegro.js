const ALLEGRO_HOST = /(^|\.)allegro\.(pl|cz|sk)$/i;
const BASE_URL = 'https://allegro.pl';

export class BlockedError extends Error {
    constructor(message = 'Allegro returned an anti-bot challenge') {
        super(message);
        this.name = 'BlockedError';
    }
}

export function isBlockedHtml(html = '') {
    if (!html) return true;

    const hasPayload =
        html.includes('__listing_StoreState') ||
        html.includes('formattedPrice') ||
        html.includes('application/ld+json');
    if (hasPayload) return false;

    return /captcha-delivery|geo\.captcha-delivery|Please enable JS and disable any ad blocker|Zostałeś zablokowany|datadome/i.test(
        html,
    );
}

function readBalanced(input, start) {
    const open = input[start];
    let close;
    if (open === '{') close = '}';
    else if (open === '[') close = ']';
    else return null;

    let depth = 0;
    let inString = false;
    let escaped = false;

    for (let i = start; i < input.length; i++) {
        const char = input[i];

        if (inString) {
            if (escaped) {
                escaped = false;
            } else if (char === '\\') {
                escaped = true;
            } else if (char === '"') {
                inString = false;
            }
            continue;
        }

        if (char === '"') {
            inString = true;
            continue;
        }

        if (char === open) {
            depth++;
        } else if (char === close) {
            depth--;
            if (depth === 0) return input.slice(start, i + 1);
        }
    }

    return null;
}

export function findJsonValues(html, key) {
    const values = [];
    const needle = `"${key}"`;
    let cursor = 0;

    while (cursor < html.length) {
        const found = html.indexOf(needle, cursor);
        if (found === -1) break;
        cursor = found + needle.length;

        let i = cursor;
        while (i < html.length && /\s/.test(html[i])) i++;
        if (html[i] !== ':' && html[i] !== '=') continue;
        i++;
        while (i < html.length && /\s/.test(html[i])) i++;

        const opener = html[i];
        if (opener !== '{' && opener !== '[' && opener !== '"') continue;

        let raw;
        if (opener === '"') {
            const end = html.indexOf('"', i + 1);
            if (end === -1) continue;
            raw = html.slice(i, end + 1);
        } else {
            raw = readBalanced(html, i);
        }
        if (!raw) continue;

        try {
            values.push(JSON.parse(raw));
        } catch {
            try {
                const decoded = JSON.parse(raw);
                if (typeof decoded === 'string') values.push(JSON.parse(decoded));
            } catch {
                // Not a complete JSON value at this location.
            }
        }
    }

    return values;
}

function firstObject(values, predicate = () => true) {
    for (const value of values) {
        if (value && typeof value === 'object' && !Array.isArray(value) && predicate(value)) {
            return value;
        }
    }
    return null;
}

export function getListingState(html) {
    const states = findJsonValues(html, '__listing_StoreState');
    const direct = firstObject(states, (state) => Array.isArray(state?.items?.elements));
    if (direct) return direct;
    const nested = firstObject(states, (state) => Array.isArray(state?.elements));
    return nested || null;
}

export function getSearchMeta(html) {
    const candidates = findJsonValues(html, 'searchMeta');
    const meta = firstObject(
        candidates,
        (candidate) =>
            candidate.lastAvailablePage != null ||
            candidate.totalCount != null ||
            candidate.availableCount != null,
    );
    if (meta) {
        return {
            lastAvailablePage: number(meta.lastAvailablePage),
            totalCount: number(meta.totalCount),
            availableCount: number(meta.availableCount),
        };
    }

    const lastPage = html.match(/"lastAvailablePage"\s*:\s*(\d+)/);
    const totalCount = html.match(/"totalCount"\s*:\s*(\d+)/);
    const availableCount = html.match(/"availableCount"\s*:\s*(\d+)/);

    return {
        lastAvailablePage: lastPage ? Number(lastPage[1]) : undefined,
        totalCount: totalCount ? Number(totalCount[1]) : undefined,
        availableCount: availableCount ? Number(availableCount[1]) : undefined,
    };
}

function number(value) {
    if (typeof value === 'number') return Number.isFinite(value) ? value : undefined;
    if (typeof value !== 'string') return undefined;

    let cleaned = value.replace(/[\s\u00a0]/g, '').replace(/[^\d.,-]/g, '');
    if (!cleaned) return undefined;
    if (cleaned.includes(',') && cleaned.includes('.')) {
        cleaned = cleaned.replace(/\./g, '').replace(',', '.');
    } else {
        cleaned = cleaned.replace(',', '.');
    }

    const parsed = Number.parseFloat(cleaned);
    return Number.isFinite(parsed) ? parsed : undefined;
}

function text(value) {
    if (typeof value !== 'string') return undefined;
    const cleaned = value.replace(/\s+/g, ' ').trim();
    return cleaned || undefined;
}

export function absoluteUrl(value) {
    if (!value || typeof value !== 'string') return undefined;
    let href = value.trim();
    if (!href) return undefined;

    if (href.startsWith('//')) href = `https:${href}`;
    if (href.startsWith('/')) href = `${BASE_URL}${href}`;

    try {
        const parsed = new URL(href, BASE_URL);
        if (parsed.pathname.startsWith('/events/clicks')) {
            const redirect = parsed.searchParams.get('redirect');
            if (redirect) {
                const decoded = decodeURIComponent(redirect);
                return absoluteUrl(decoded) || parsed.href;
            }
        }
        return parsed.href;
    } catch {
        return undefined;
    }
}

export function extractOfferId(value) {
    if (value == null) return undefined;
    const raw = String(value);
    const offerPath = raw.match(/\/oferta\/(?:[^/?#]*-)?(\d{6,})(?:[/?#]|$)/i);
    if (offerPath) return offerPath[1];

    const offerQuery = raw.match(/[?&]offerId=(\d{6,})/i);
    if (offerQuery) return offerQuery[1];

    const trailing = raw.match(/(?:^|-)(\d{6,})$/);
    if (trailing) return trailing[1];

    const digits = raw.match(/^(\d{6,})$/);
    return digits ? digits[1] : undefined;
}

export function normalizeAllegroUrl(rawUrl) {
    let value = String(rawUrl || '').trim();
    if (!value) throw new Error('The start URL is empty.');

    if (!/^https?:\/\//i.test(value)) {
        value = `https://${value.replace(/^\/+/, '')}`;
    }

    let parsed;
    try {
        parsed = new URL(value);
    } catch {
        throw new Error(`Invalid Allegro URL: ${rawUrl}`);
    }

    if (!ALLEGRO_HOST.test(parsed.hostname)) {
        throw new Error(`Unsupported URL host: ${parsed.hostname}. Use an allegro.pl, allegro.cz or allegro.sk URL.`);
    }

    parsed.hash = '';
    return parsed.href;
}

export function buildKeywordUrl(keyword) {
    const query = String(keyword || '').trim();
    if (!query) throw new Error('Provide a keyword or an Allegro URL.');
    return `${BASE_URL}/listing?string=${encodeURIComponent(query)}`;
}

export function detectTarget({ startUrl, keyword }) {
    if (startUrl && String(startUrl).trim()) {
        const url = normalizeAllegroUrl(startUrl);
        const parsed = new URL(url);
        const isOffer = /^\/(?:oferta|produkt)\//i.test(parsed.pathname);
        return {
            kind: isOffer ? 'offer' : 'listing',
            url,
            query: parsed.searchParams.get('string') || undefined,
        };
    }

    if (keyword && String(keyword).trim()) {
        const url = buildKeywordUrl(keyword);
        return { kind: 'listing', url, query: String(keyword).trim() };
    }

    throw new Error('Provide an Allegro URL in "startUrl" or a "keyword".');
}

export function withPage(url, page) {
    const parsed = new URL(url);
    if (page <= 1) {
        parsed.searchParams.delete('p');
    } else {
        parsed.searchParams.set('p', String(page));
    }
    return parsed.href;
}

export function currentPage(url) {
    const parsed = new URL(url);
    const page = Number.parseInt(parsed.searchParams.get('p') || '1', 10);
    return Number.isFinite(page) && page > 0 ? page : 1;
}

function collectParameters(parameters) {
    if (!Array.isArray(parameters)) return undefined;

    const entries = [];
    for (const parameter of parameters) {
        const name = text(parameter?.name);
        const values = Array.isArray(parameter?.values)
            ? parameter.values.map((value) => text(String(value))).filter(Boolean)
            : [];
        if (name && values.length) entries.push([name, values.join(', ')]);
    }

    return entries.length ? Object.fromEntries(entries) : undefined;
}

export function mapListingElement(element, context = {}) {
    if (!element || typeof element !== 'object') return null;

    const offerId =
        extractOfferId(element.offerId) ||
        extractOfferId(element.eventData?.offer_id) ||
        extractOfferId(element.url) ||
        extractOfferId(element.id);
    const title = text(element.alt) || text(element.title?.text) || text(element.name);
    if (!offerId || !title) return null;

    const priceNode = element.price?.mainPrice || element.price || {};
    const price = number(priceNode.amount ?? priceNode.value);
    const currency = text(priceNode.currency);
    const originalPrice =
        number(element.price?.crossedPrice?.amount) ||
        number(element.price?.previousPrice?.amount) ||
        number(element.price?.originalPrice?.amount);
    const image =
        text(element.photos?.[0]?.medium) ||
        text(element.photos?.[0]?.url) ||
        text(element.mainThumbnail) ||
        text(element.image);

    const discountPercent =
        price && originalPrice && originalPrice > price
            ? Math.round(((originalPrice - price) / originalPrice) * 100)
            : undefined;

    return {
        offerId,
        productId: text(element.id) || undefined,
        title,
        url: absoluteUrl(element.url) || `${BASE_URL}/oferta/${offerId}`,
        price,
        currency,
        originalPrice,
        discountPercent,
        image,
        sellerName: text(element.seller?.name) || text(element.seller?.login),
        sellerLogin: text(element.seller?.login),
        sellerRating: number(element.seller?.positiveFeedbackPercent),
        delivery: text(element.deliveryInfo?.text) || text(element.delivery?.text),
        rating:
            number(element.productReview?.rating?.average) ||
            number(element.rating?.value) ||
            number(element.ratingValue),
        reviewsCount:
            number(element.productReview?.rating?.count) ||
            number(element.rating?.count) ||
            number(element.reviewsCount),
        condition: text(element.condition),
        parameters: collectParameters(element.parameters),
        isSponsored: Boolean(element.isSponsored || element.sponsored),
        isPromoted: Boolean(element.promoted) || element.context === 'PROMOTED',
        page: context.page,
        query: context.query,
        listingUrl: context.listingUrl,
    };
}

export function parseListingHtml(html, context = {}) {
    if (isBlockedHtml(html) && !html.includes('__listing_StoreState')) {
        return { items: [], meta: {}, blocked: true };
    }

    const state = getListingState(html);
    const meta = getSearchMeta(html);
    const elements = state?.items?.elements || state?.elements || [];

    const items = elements
        .map((element) => mapListingElement(element, context))
        .filter(Boolean);

    return { items, meta, blocked: false };
}

function deepFind(value, keys, depth = 0) {
    if (!value || typeof value !== 'object' || depth > 8) return undefined;

    for (const key of keys) {
        if (value[key] != null && typeof value[key] !== 'object') return value[key];
    }

    for (const child of Object.values(value)) {
        const found = deepFind(child, keys, depth + 1);
        if (found !== undefined) return found;
    }

    return undefined;
}

function parseJsonScripts(html) {
    const results = [];
    const regex = /<script[^>]*>([\s\S]*?)<\/script>/gi;
    let match;

    while ((match = regex.exec(html))) {
        const body = match[1].trim();
        if (!body.startsWith('{') && !body.startsWith('[')) continue;
        try {
            results.push(JSON.parse(body));
        } catch {
            continue;
        }
    }

    return results;
}

function deepFindValue(value, key, depth = 0) {
    if (!value || typeof value !== 'object' || depth > 10) return undefined;
    if (Object.prototype.hasOwnProperty.call(value, key)) return value[key];

    for (const child of Object.values(value)) {
        const found = deepFindValue(child, key, depth + 1);
        if (found !== undefined) return found;
    }

    return undefined;
}

function deepFindParent(value, key, depth = 0) {
    if (!value || typeof value !== 'object' || depth > 10) return undefined;
    if (Object.prototype.hasOwnProperty.call(value, key)) return value;

    for (const child of Object.values(value)) {
        const found = deepFindParent(child, key, depth + 1);
        if (found !== undefined) return found;
    }

    return undefined;
}

function findProductJsonLd(values) {
    const queue = [...values];

    while (queue.length) {
        const candidate = queue.shift();
        if (Array.isArray(candidate)) {
            queue.push(...candidate);
            continue;
        }
        if (!candidate || typeof candidate !== 'object') continue;

        const types = Array.isArray(candidate['@type']) ? candidate['@type'] : [candidate['@type']];
        if (types.some((type) => String(type).toLowerCase() === 'product')) return candidate;
        if (candidate['@graph']) queue.push(candidate['@graph']);
    }

    return null;
}

function firstValue(...values) {
    for (const value of values) {
        if (value !== undefined && value !== null && value !== '') return value;
    }
    return undefined;
}

export function parseOfferHtml(html, context = {}) {
    if (isBlockedHtml(html) && !html.includes('formattedPrice') && !html.includes('application/ld+json')) {
        return { item: null, blocked: true };
    }

    const scripts = parseJsonScripts(html);
    const priceValue = deepFindValue(scripts, 'formattedPrice');
    const priceParent = deepFindParent(scripts, 'formattedPrice');
    const priceNode = (priceValue && typeof priceValue === 'object' ? priceValue : priceParent) || {};

    const sellerValue = deepFindValue(scripts, 'sellerName');
    const sellerParent = deepFindParent(scripts, 'sellerName');
    const sellerData = sellerValue ?? sellerParent ?? deepFindValue(scripts, 'seller');

    const ratingValue = deepFindValue(scripts, 'aggregateRating');
    const ratingParent = deepFindParent(scripts, 'aggregateRating');
    const ratingData = ratingValue && typeof ratingValue === 'object' ? ratingValue : ratingParent;

    const galleryValue = deepFindValue(scripts, 'galleryItems');
    const galleryParent = deepFindParent(scripts, 'galleryItems');
    const galleryData = Array.isArray(galleryValue) ? galleryValue : galleryParent?.galleryItems;

    const product = findProductJsonLd(scripts);
    const offer = Array.isArray(product?.offers) ? product.offers[0] : product?.offers;

    const price = number(
        firstValue(
            priceNode.amount,
            priceNode.value,
            priceNode.formattedPrice,
            offer?.price,
            offer?.lowPrice,
            deepFind(ratingData, ['price']),
        ),
    );
    const currency = text(
        firstValue(priceNode.currency, offer?.priceCurrency, deepFind(product, ['priceCurrency'])),
    );

    const gallery = Array.isArray(galleryData)
        ? galleryData.map((item) => text(item?.thumbnail) || text(item?.url)).filter(Boolean)
        : [];
    const jsonLdImages = Array.isArray(product?.image) ? product.image : [product?.image];
    const images = gallery.length
        ? gallery
        : jsonLdImages.map((image) => (typeof image === 'string' ? text(image) : text(image?.url))).filter(Boolean);

    const offerId =
        extractOfferId(context.url) ||
        extractOfferId(product?.sku) ||
        extractOfferId(product?.productID) ||
        extractOfferId(context.offerId);

    const sellerName = text(
        firstValue(
            typeof sellerData === 'string' ? sellerData : sellerData?.sellerName,
            sellerData?.name,
            deepFind(sellerData, ['sellerName', 'name']),
            offer?.seller?.name,
            product?.brand?.name,
        ),
    );

    const specifications = deepFindValue(scripts, 'specifications');
    const specificationEntries = Array.isArray(specifications)
        ? specifications
              .map((specification) => [text(specification?.key), text(specification?.value)])
              .filter(([name, value]) => name && value)
        : [];

    const addonEntries = Array.isArray(product?.additionalProperty)
        ? product.additionalProperty
              .map((property) => [text(property?.name), text(property?.value)])
              .filter(([name, value]) => name && value)
        : [];

    const parameterEntries = addonEntries.length ? addonEntries : specificationEntries;

    const item = {
        offerId,
        title: text(product?.name) || text(deepFind(priceNode, ['offerTitle', 'productName'])),
        url: context.url,
        price,
        currency,
        originalPrice: number(
            firstValue(
                priceNode.originalPrice,
                priceNode.crossedPrice,
                priceNode.regularPrice,
                deepFind(priceNode, ['originalPrice', 'crossedPrice', 'regularPrice']),
            ),
        ),
        image: images[0],
        images: images.length > 1 ? images : undefined,
        sellerName,
        sellerLogin: sellerName,
        sellerRating: number(firstValue(sellerData?.rating, deepFind(sellerData, ['rating']))),
        rating: number(
            firstValue(
                ratingData?.ratingValue,
                product?.aggregateRating?.ratingValue,
                deepFind(ratingData, ['ratingValue']),
            ),
        ),
        reviewsCount: number(
            firstValue(
                ratingData?.reviewCount,
                ratingData?.ratingCount,
                product?.aggregateRating?.reviewCount,
                deepFind(ratingData, ['reviewCount', 'ratingCount']),
            ),
        ),
        condition: text(product?.itemCondition)?.replace('https://schema.org/', ''),
        parameters: parameterEntries.length ? Object.fromEntries(parameterEntries) : undefined,
        page: 1,
        query: context.query,
        listingUrl: context.url,
    };

    return { item: item.title ? item : null, blocked: false };
}

export function compactObject(value) {
    if (!value || typeof value !== 'object') return value;

    const result = {};
    for (const [key, raw] of Object.entries(value)) {
        if (raw === null || raw === undefined) continue;
        if (typeof raw === 'number' && !Number.isFinite(raw)) continue;
        if (typeof raw === 'boolean' && !raw) continue;
        if (typeof raw === 'string' && !raw.trim()) continue;
        if (Array.isArray(raw) && raw.length === 0) continue;
        if (
            raw &&
            typeof raw === 'object' &&
            !Array.isArray(raw) &&
            Object.keys(raw).length === 0
        ) {
            continue;
        }
        if (typeof raw === 'string') {
            result[key] = raw.trim();
        } else {
            result[key] = raw;
        }
    }

    return result;
}
