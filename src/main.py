"""Allegro Product Scraper actor entrypoint."""

import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

from apify import Actor

from .allegro import (
    BlockedError,
    compact_object,
    current_page,
    detect_target,
    parse_listing_html,
    parse_offer_html,
    url_query_param,
    with_page,
)
from .fetcher import AllegroFetcher

INTEGER_PREFIX = re.compile(r'\s*([+-]?\d+)')


def integer(value, fallback, minimum, maximum):
    match = INTEGER_PREFIX.match(str(value)) if value is not None else None
    if not match:
        return fallback
    return min(maximum, max(minimum, int(match.group(1))))


def page_query(target):
    query = target.get('query')
    if query and query.strip():
        return query.strip()

    search = url_query_param(target['url'], 'string')
    if search:
        return search

    segments = [segment for segment in urlsplit(target['url']).path.split('/') if segment]
    if not segments:
        return None

    segment = segments[-1]
    if segment == 'listing':
        return None
    try:
        return unquote(segment)
    except ValueError:
        return None


def scraped_at():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


async def run_listing(fetcher, target, results_wanted, max_pages, query):
    start_page = current_page(target['url'])
    end_page = start_page + max_pages - 1
    seen = set()
    timestamp = scraped_at()

    saved = 0
    position = 0
    pages_fetched = 0
    last_available_page = None
    available_count = None
    stopped_early = False
    stop_reason = None

    for page in range(start_page, end_page + 1):
        page_url = with_page(target['url'], page)

        try:
            html = await fetcher.fetch(page_url)
        except Exception as exc:
            if pages_fetched == 0:
                raise
            Actor.log.warning(
                f'Page {page} failed: {exc}. Keeping the results collected so far.'
            )
            stopped_early = True
            break

        parsed = parse_listing_html(html, {'page': page, 'query': query, 'listingUrl': page_url})

        if parsed['blocked']:
            Actor.log.warning(
                f'Page {page} returned an anti-bot challenge. Keeping the results collected so far.'
            )
            stopped_early = True
            break

        pages_fetched += 1
        last_page_seen = parsed['meta'].get('lastAvailablePage')
        if last_page_seen is not None:
            last_available_page = last_page_seen
        available_seen = parsed['meta'].get('availableCount')
        if available_seen is not None:
            available_count = available_seen

        organic_ids = {
            item['offerId']
            for item in parsed['items']
            if not item['isPromoted'] and not item['isSponsored']
        }
        batch = []

        for item in parsed['items']:
            if saved >= results_wanted:
                break
            if item['isPromoted'] and item['offerId'] in organic_ids:
                continue
            if item['offerId'] in seen:
                continue

            seen.add(item['offerId'])
            position += 1

            batch.append(
                compact_object(
                    {
                        **item,
                        'position': position,
                        'page': page,
                        'query': query,
                        'listingUrl': page_url,
                        'scrapedAt': timestamp,
                    }
                )
            )
            saved += 1

        if batch:
            await Actor.push_data(batch)
        Actor.log.info(f'Page {page}: {len(batch)} new offers ({saved}/{results_wanted}).')

        if saved >= results_wanted:
            stop_reason = 'the result limit was reached'
            break
        if not parsed['items']:
            stop_reason = 'the page returned no offers'
            break
        if last_available_page and page >= last_available_page:
            stop_reason = (
                f'Allegro reports only {last_available_page} available page(s) for this search'
            )
            break

    if saved == 0 and available_count != 0:
        raise RuntimeError(
            'No offers were extracted. Allegro may have returned an unexpected page or a challenge.'
        )

    if stopped_early:
        summary = f'Saved {saved} offers from {pages_fetched} page(s) (stopped after a challenge).'
    elif saved >= results_wanted:
        summary = f'Saved {saved} offers from {pages_fetched} page(s).'
    else:
        reason = stop_reason or (
            f'the max_pages limit ({max_pages}) stopped the run, raise it to collect more'
        )
        summary = (
            f'Saved {saved} of {results_wanted} requested offers from {pages_fetched} page(s): {reason}.'
        )

    await Actor.set_status_message(summary)
    Actor.log.info(summary)


async def run_offer(fetcher, target, query):
    html = await fetcher.fetch(target['url'])
    parsed = parse_offer_html(html, {'url': target['url'], 'query': query})

    if parsed['blocked'] or not parsed['item']:
        raise BlockedError(f'Could not read offer data from {target["url"]}.')

    record = compact_object(
        {
            **parsed['item'],
            'position': 1,
            'page': 1,
            'query': query,
            'listingUrl': target['url'],
            'scrapedAt': scraped_at(),
        }
    )

    await Actor.push_data(record)
    offer_id = record.get('offerId', '')
    await Actor.set_status_message(f'Saved offer {offer_id}.')
    Actor.log.info(f'Saved offer {offer_id}.')


DEFAULT_PROXY = {'useApifyProxy': True, 'apifyProxyGroups': ['StaticUS3']}


async def main() -> None:
    async with Actor:
        actor_input = (await Actor.get_input()) or {}
        results_wanted = integer(actor_input.get('results_wanted'), 20, 1, 5_000)
        max_pages = integer(actor_input.get('max_pages'), 10, 1, 100)
        target = detect_target(actor_input)
        query = target.get('query') if target['kind'] == 'offer' else page_query(target)

        # Allegro blocks direct and datacenter exits, so the residential group is the default.
        proxy_input = actor_input.get('proxyConfiguration') or DEFAULT_PROXY
        try:
            proxy_configuration = await Actor.create_proxy_configuration(
                actor_proxy_input=proxy_input
            )
        except Exception as exc:
            Actor.log.warning(f'Could not create the proxy configuration ({exc}). Trying without a proxy.')
            proxy_input = {}
            proxy_configuration = None

        groups = proxy_input.get('apifyProxyGroups') or proxy_input.get('groups') or []
        uses_unblocker = 'UNBLOCKER' in groups

        fetcher = AllegroFetcher(proxy_configuration, use_session=not uses_unblocker)

        try:
            await fetcher.init()
            Actor.log.info(
                f'Scraping {target["kind"]} target with priority '
                f'{"URL" if actor_input.get("startUrl") else "keyword"}.'
            )

            if target['kind'] == 'offer':
                await run_offer(fetcher, target, query)
            else:
                await run_listing(fetcher, target, results_wanted, max_pages, query)
        finally:
            await fetcher.close()


if __name__ == '__main__':
    asyncio.run(main())
