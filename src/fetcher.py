"""Stealthy fetch layer for Allegro using Scrapling.

Order of attempts for every page:

1. Scrapling HTTP fetcher (curl_cffi with a Chrome TLS fingerprint).
2. A rotating list of stealth browser profiles: Patchright Chromium (headful),
   real Chrome (headful), then Chromium headless. A profile that gets a hard
   DataDome block is closed, so the next attempt starts another profile.

A hard block is an exit-IP decision (403 + DataDome block page), not something
a browser fingerprint can clear. When every attempt is blocked the run fails
with a message that names the missing proxy configuration.
"""

import asyncio
import logging
import time
from uuid import uuid4

from apify import Actor
from scrapling.fetchers import AsyncFetcher, AsyncStealthySession

from .allegro import BlockedError, is_blocked_html, parse_listing_html, url_query_param

# Scrapling logs one INFO line per fetch; the actor reports its own progress.
logging.getLogger('scrapling').setLevel(logging.CRITICAL)

ACCEPT_LANGUAGE = 'pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7'
PAGE_TIMEOUT_MS = 60_000
CHALLENGE_WAIT_MS = 20_000
MAX_ATTEMPTS = 4
RUN_DEADLINE_SECONDS = 240
HTTP_TIMEOUT = 30
UNBLOCKER_TIMEOUT = 90

# Patchright's bundled Chromium carries the stealth patches, so it is tried first.
PROFILES = (
    ('chromium-headful', {'headless': False, 'real_chrome': False}),
    ('chrome-headful', {'headless': False, 'real_chrome': True}),
    ('chromium-headless', {'headless': True, 'real_chrome': False}),
)


def session_id():
    return f'allegro_{uuid4().hex}'


class AllegroFetcher:
    def __init__(self, proxy_configuration, use_session=True, unblocker=False):
        self.proxy_configuration = proxy_configuration
        self.use_session = use_session
        # Apify Unblocker terminates TLS to solve challenges, so its certificate cannot be verified.
        self.unblocker = unblocker
        self.session = session_id()
        self.proxy_url = None
        self.http_failures = 0
        self.http_disabled = False
        self.browser = None
        self.browser_proxy_url = None
        self.profile_name = None
        self.profile_index = 0
        self.profiles_tried = []
        self.last_status = None

    async def resolve_proxy_url(self):
        if not self.proxy_configuration:
            return None
        if self.use_session:
            return await self.proxy_configuration.new_url(self.session)
        return await self.proxy_configuration.new_url()

    async def init(self):
        self.proxy_url = await self.resolve_proxy_url()
        self.http_disabled = not self.proxy_url
        if not self.proxy_url:
            Actor.log.info('No proxy configured. Using the stealth browser fetcher directly.')

    async def rotate(self):
        self.session = session_id()
        if self.proxy_configuration:
            self.proxy_url = await self.resolve_proxy_url()
        self.http_failures = 0
        self.http_disabled = not self.proxy_url
        await self.close_browser()

    # --- HTTP fast path ----------------------------------------------------

    async def fetch_http(self, url):
        try:
            response = await AsyncFetcher.get(
                url,
                proxy=self.proxy_url,
                impersonate='chrome',
                stealthy_headers=True,
                timeout=UNBLOCKER_TIMEOUT if self.unblocker else HTTP_TIMEOUT,
                retries=0,
                verify=not self.unblocker,
                headers={'accept-language': ACCEPT_LANGUAGE},
            )
            html = response.body.decode('utf-8', 'replace')
        except Exception as exc:
            Actor.log.warning(f'HTTP fetch failed: {exc}')
            return None

        has_payload = (
            '__listing_StoreState' in html
            or 'formattedPrice' in html
            or 'application/ld+json' in html
        )
        self.last_status = response.status
        if response.status != 200 or not has_payload or is_blocked_html(html):
            Actor.log.warning(f'HTTP response did not contain page data (status {response.status}).')
            return None

        return html

    # --- stealth browser ---------------------------------------------------

    def next_profile(self):
        name, options = PROFILES[self.profile_index % len(PROFILES)]
        self.profile_index += 1
        return name, options

    async def ensure_browser(self):
        if self.browser and self.browser_proxy_url == self.proxy_url:
            return self.browser

        await self.close_browser()
        name, options = self.next_profile()

        browser = AsyncStealthySession(
            **options,
            hide_canvas=True,
            block_webrtc=True,
            block_ads=True,
            locale='pl-PL',
            timezone_id='Europe/Warsaw',
            timeout=PAGE_TIMEOUT_MS,
            retries=1,
            max_pages=1,
            proxy=self.proxy_url,
            extra_headers={'accept-language': ACCEPT_LANGUAGE},
        )
        try:
            await browser.start()
        except Exception as exc:
            Actor.log.warning(f'Could not start the {name} profile: {exc}')
            self.profiles_tried.append(f'{name} (unavailable)')
            return None

        self.browser = browser
        self.browser_proxy_url = self.proxy_url
        self.profile_name = name
        self.profiles_tried.append(name)
        Actor.log.debug(f'Started the {name} browser profile.')
        return browser

    @staticmethod
    def page_ready(html, page_url):
        if len(html) < 5_000:
            return False

        if '__listing_StoreState' in html:
            parsed = parse_listing_html(html, {'listingUrl': page_url})
            if parsed['items'] or parsed['meta'].get('availableCount') == 0:
                return True

        offer_ready = 'formattedPrice' in html or 'application/ld+json' in html
        return offer_ready and not is_blocked_html(html)

    @staticmethod
    def hard_block(status, html):
        return status in (401, 403) or (len(html) < 5_000 and is_blocked_html(html))

    async def wait_for_payload(self, page):
        """Poll a loaded page until the embedded data or a challenge verdict appears."""
        deadline = time.monotonic() + CHALLENGE_WAIT_MS / 1000
        await page.wait_for_timeout(2_000)

        while time.monotonic() < deadline:
            try:
                html = await page.content()
                if self.page_ready(html, page.url):
                    return
                # A small DataDome block page is final; polling cannot clear it.
                if len(html) < 5_000 and is_blocked_html(html):
                    return
            except Exception:
                # The challenge may still be navigating.
                pass
            await page.wait_for_timeout(2_000)

    async def fetch_browser(self, url):
        requested_query = url_query_param(url, 'string')

        for _ in range(2):
            browser = await self.ensure_browser()
            if not browser:
                return None

            try:
                response = await browser.fetch(
                    url,
                    page_action=self.wait_for_payload,
                    timeout=PAGE_TIMEOUT_MS,
                    wait=1_000,
                    load_dom=True,
                    network_idle=False,
                )
            except Exception as exc:
                Actor.log.warning(f'Browser navigation failed on the {self.profile_name} profile: {exc}')
                await asyncio.sleep(2)
                continue

            html = response.body.decode('utf-8', 'replace')
            self.last_status = response.status

            if self.hard_block(response.status, html):
                Actor.log.debug(f'{self.profile_name} profile blocked (status {response.status}).')
                await self.close_browser()
                return None

            if response.status != 200 or not self.page_ready(html, response.url):
                await asyncio.sleep(2)
                continue

            if not requested_query or requested_query == url_query_param(response.url, 'string'):
                return html

            Actor.log.info(
                'Allegro rewrote the search phrase after the challenge. Reloading the requested URL.'
            )

        return None

    # --- retries -----------------------------------------------------------

    async def fetch(self, url):
        deadline = time.monotonic() + RUN_DEADLINE_SECONDS

        for attempt in range(1, MAX_ATTEMPTS + 1):
            if time.monotonic() > deadline:
                break

            if not self.http_disabled:
                html = await self.fetch_http(url)
                if html:
                    return html

                self.http_failures += 1
                if self.http_failures >= 2:
                    self.http_disabled = True
                    Actor.log.debug('Switching to the browser fetcher for the rest of this run.')

            html = await self.fetch_browser(url)
            if html:
                self.http_disabled = True
                return html

            if attempt < MAX_ATTEMPTS:
                await self.rotate()

        if self.proxy_url:
            hint = (
                ' Check the proxy group in the run log. On the Free plan use the UNBLOCKER group '
                'in proxyConfiguration.apifyProxyGroups, or set your own proxy URLs.'
            )
        else:
            hint = (
                ' Allegro blocks every exit of this run. Add proxyConfiguration with an Apify Proxy '
                'group (StaticUS3 works) or your own proxy URLs and run it again.'
            )
        profiles = ', '.join(self.profiles_tried) or 'http'
        raise BlockedError(
            f'Unable to load {url} after {MAX_ATTEMPTS} attempts '
            f'(last status {self.last_status}, tried: {profiles}).{hint}'
        )

    async def close_browser(self):
        browser, self.browser = self.browser, None
        self.browser_proxy_url = None
        self.profile_name = None

        if browser:
            try:
                await browser.close()
            except Exception:
                pass

    async def close(self):
        await self.close_browser()
