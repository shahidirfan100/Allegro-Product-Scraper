import { Actor, log } from 'apify';

import {
    BlockedError,
    compactObject,
    currentPage,
    detectTarget,
    parseListingHtml,
    parseOfferHtml,
    withPage,
} from './allegro.js';
import { AllegroFetcher } from './fetcher.js';

function integer(value, fallback, min, max) {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.min(max, Math.max(min, parsed));
}

function pageQuery(target) {
    if (target.query?.trim()) return target.query.trim();

    try {
        const parsed = new URL(target.url);
        const search = parsed.searchParams.get('string');
        if (search) return search;
        const segment = parsed.pathname.split('/').filter(Boolean).pop();
        return segment && segment !== 'listing' ? decodeURIComponent(segment) : undefined;
    } catch {
        return undefined;
    }
}

async function runListing(fetcher, target, { resultsWanted, maxPages, query }) {
    const startPage = currentPage(target.url);
    const endPage = startPage + maxPages - 1;
    const seen = new Set();
    const scrapedAt = new Date().toISOString();

    let saved = 0;
    let position = 0;
    let pagesFetched = 0;
    let lastAvailablePage;
    let availableCount;
    let stoppedEarly = false;

    for (let page = startPage; page <= endPage; page++) {
        const pageUrl = withPage(target.url, page);
        let html;
        let via;

        try {
            ({ html, via } = await fetcher.fetch(pageUrl));
        } catch (error) {
            if (pagesFetched === 0) throw error;
            log.warning(`Page ${page} failed: ${error.message}. Keeping the results collected so far.`);
            stoppedEarly = true;
            break;
        }

        const parsed = parseListingHtml(html, { page, query, listingUrl: pageUrl });

        if (parsed.blocked) {
            log.warning(`Page ${page} returned an anti-bot challenge. Keeping the results collected so far.`);
            stoppedEarly = true;
            break;
        }

        pagesFetched++;
        lastAvailablePage = parsed.meta.lastAvailablePage ?? lastAvailablePage;
        availableCount = parsed.meta.availableCount ?? availableCount;

        const organicIds = new Set(
            parsed.items.filter((item) => !item.isPromoted && !item.isSponsored).map((item) => item.offerId),
        );
        const batch = [];

        for (const item of parsed.items) {
            if (saved >= resultsWanted) break;
            if (item.isPromoted && organicIds.has(item.offerId)) continue;
            if (seen.has(item.offerId)) continue;

            seen.add(item.offerId);
            position++;

            batch.push(
                compactObject({
                    ...item,
                    position,
                    page,
                    query,
                    listingUrl: pageUrl,
                    scrapedAt,
                }),
            );
            saved++;
        }

        if (batch.length) await Actor.pushData(batch);
        log.info(`Page ${page}: ${batch.length} new offers (${saved}/${resultsWanted}) via ${via}.`);

        if (saved >= resultsWanted) break;
        if (parsed.items.length === 0) break;
        if (lastAvailablePage && page >= lastAvailablePage) break;
    }

    if (saved === 0 && availableCount !== 0) {
        throw new Error('No offers were extracted. Allegro may have returned an unexpected page or a challenge.');
    }

    const stopNote = stoppedEarly ? ' (stopped after a challenge)' : '';
    await Actor.setStatusMessage(`Saved ${saved} offers from ${pagesFetched} page(s)${stopNote}.`);
    log.info(`Finished. Saved ${saved} offers from ${pagesFetched} page(s)${stopNote}.`);
}

async function runOffer(fetcher, target, { query }) {
    const { html, via } = await fetcher.fetch(target.url);
    const parsed = parseOfferHtml(html, { url: target.url, query });

    if (parsed.blocked || !parsed.item) {
        throw new BlockedError(`Could not read offer data from ${target.url}.`);
    }

    const record = compactObject({
        ...parsed.item,
        position: 1,
        page: 1,
        query,
        listingUrl: target.url,
        scrapedAt: new Date().toISOString(),
    });

    await Actor.pushData(record);
    await Actor.setStatusMessage(`Saved offer ${record.offerId || ''} via ${via}.`);
    log.info(`Saved offer ${record.offerId || ''} via ${via}.`);
}

async function main() {
    await Actor.init();

    const input = (await Actor.getInput()) ?? {};
    const resultsWanted = integer(input.results_wanted, 20, 1, 5_000);
    const maxPages = integer(input.max_pages, 10, 1, 100);
    const target = detectTarget(input);
    const query = target.kind === 'offer' ? target.query : pageQuery(target);

    const proxyConfiguration =
        input.proxyConfiguration && Object.keys(input.proxyConfiguration).length
            ? await Actor.createProxyConfiguration(input.proxyConfiguration)
            : undefined;
    const proxyGroups =
        input.proxyConfiguration?.apifyProxyGroups || input.proxyConfiguration?.groups || [];
    const usesUnblocker = proxyGroups.includes('UNBLOCKER');

    const fetcher = new AllegroFetcher(proxyConfiguration, { useSession: !usesUnblocker });

    try {
        await fetcher.init();
        log.info(`Scraping ${target.kind} target with priority ${input.startUrl ? 'URL' : 'keyword'}.`);

        if (target.kind === 'offer') {
            await runOffer(fetcher, target, { query });
        } else {
            await runListing(fetcher, target, { resultsWanted, maxPages, query });
        }
    } finally {
        await fetcher.close();
    }
}

main()
    .then(async () => {
        await Actor.exit();
    })
    .catch(async (error) => {
        log.error(error.stack || error.message);
        await Actor.exit({ exitCode: 1 });
    });
