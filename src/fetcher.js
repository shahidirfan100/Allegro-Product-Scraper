import { mkdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { log } from 'apify';
import { Impit } from 'impit';
import { chromium } from 'patchright';

import { BlockedError, isBlockedHtml, parseListingHtml } from './allegro.js';

const ACCEPT_LANGUAGE = 'pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7';
const PAGE_TIMEOUT_MS = 60_000;
const CHALLENGE_WAIT_MS = 20_000;

function sessionId() {
    return `allegro_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

function proxyOption(proxyUrl) {
    if (!proxyUrl) return undefined;

    const parsed = new URL(proxyUrl);
    return {
        server: `${parsed.protocol}//${parsed.host}`,
        ...(parsed.username ? { username: decodeURIComponent(parsed.username) } : {}),
        ...(parsed.password ? { password: decodeURIComponent(parsed.password) } : {}),
    };
}

export class AllegroFetcher {
    constructor(proxyConfiguration, { useSession = true } = {}) {
        this.proxyConfiguration = proxyConfiguration;
        this.useSession = useSession;
        this.session = sessionId();
        this.proxyUrl = undefined;
        this.http = null;
        this.httpDisabled = false;
        this.httpFailures = 0;
        this.context = null;
        this.page = null;
        this.profileDir = null;
        this.browserProxyUrl = undefined;
    }

    async resolveProxyUrl() {
        if (!this.proxyConfiguration) return undefined;
        return this.useSession
            ? this.proxyConfiguration.newUrl(this.session)
            : this.proxyConfiguration.newUrl();
    }

    async init() {
        this.proxyUrl = await this.resolveProxyUrl();
        this.httpDisabled = !this.proxyUrl;

        if (!this.proxyUrl) {
            log.info('No proxy configured. Using the browser fetcher directly.');
        }
    }

    async rotate() {
        this.session = sessionId();
        this.proxyUrl = await this.resolveProxyUrl();
        this.http = null;
        this.httpFailures = 0;
        this.httpDisabled = !this.proxyUrl;
        await this.closeBrowser();
        log.info(this.proxyUrl ? 'Rotated the proxy session and browser profile.' : 'Rotated the browser profile.');
    }

    ensureHttpClient() {
        if (this.http) return this.http;
        this.http = new Impit({
            browser: 'chrome',
            timeout: 30_000,
            ...(this.proxyUrl ? { proxyUrl: this.proxyUrl } : {}),
        });
        return this.http;
    }

    async fetchHttp(url) {
        try {
            const response = await this.ensureHttpClient().fetch(url, {
                headers: { 'accept-language': ACCEPT_LANGUAGE },
            });
            const html = await response.text();
            const hasPayload =
                html.includes('__listing_StoreState') ||
                html.includes('formattedPrice') ||
                html.includes('application/ld+json');

            if (response.status !== 200 || !hasPayload || isBlockedHtml(html)) {
                log.warning(`HTTP response did not contain page data (status ${response.status}).`);
                return null;
            }

            return html;
        } catch (error) {
            log.warning(`HTTP fetch failed: ${error.message}`);
            return null;
        }
    }

    async ensureBrowser() {
        if (this.context && this.browserProxyUrl === this.proxyUrl) return;

        await this.closeBrowser();

        this.profileDir = join(tmpdir(), `allegro-profile-${this.session}`);
        await mkdir(this.profileDir, { recursive: true });

        this.context = await chromium.launchPersistentContext(this.profileDir, {
            headless: false,
            noViewport: true,
            locale: 'pl-PL',
            timezoneId: 'Europe/Warsaw',
            extraHTTPHeaders: { 'accept-language': ACCEPT_LANGUAGE },
            args: ['--disable-blink-features=AutomationControlled'],
            ...(this.proxyUrl ? { proxy: proxyOption(this.proxyUrl) } : {}),
        });

        this.page = this.context.pages()[0] || (await this.context.newPage());
        this.browserProxyUrl = this.proxyUrl;
        log.info('Started the browser fetcher.');
    }

    async readPage(page) {
        const deadline = Date.now() + CHALLENGE_WAIT_MS;
        await page.waitForTimeout(2_000);

        while (Date.now() < deadline) {
            try {
                const html = await page.content();
                if (html.length < 5_000) return null;

                if (html.includes('__listing_StoreState')) {
                    const parsed = parseListingHtml(html, { listingUrl: page.url() });
                    if (parsed.items.length > 0 || parsed.meta.availableCount === 0) return html;
                }

                const offerReady =
                    html.includes('formattedPrice') || html.includes('application/ld+json');
                if (offerReady && !isBlockedHtml(html)) return html;
            } catch {
                // The challenge may still be navigating.
            }

            await page.waitForTimeout(2_000);
        }

        return null;
    }

    async fetchBrowser(url) {
        try {
            await this.ensureBrowser();

            if (!this.page || this.page.isClosed()) {
                this.page = await this.context.newPage();
            }

            const { page } = this;
            const requestedQuery = new URL(url).searchParams.get('string');
            let action = 'goto';

            for (let attempt = 1; attempt <= 4; attempt++) {
                try {
                    if (action === 'reload') {
                        await page.reload({ waitUntil: 'commit', timeout: PAGE_TIMEOUT_MS });
                    } else {
                        await page.goto(url, { waitUntil: 'commit', timeout: PAGE_TIMEOUT_MS });
                    }
                } catch (error) {
                    log.warning(`Browser navigation failed: ${error.message}`);
                }

                const html = await this.readPage(page);
                if (!html) {
                    action = 'reload';
                    continue;
                }

                const finalQuery = new URL(page.url()).searchParams.get('string');
                if (!requestedQuery || requestedQuery === finalQuery) return html;

                log.info('Allegro rewrote the search phrase after the challenge. Reloading the requested URL.');
                action = 'goto';
            }

            log.warning('Browser fetch still received a challenge.');
            return null;
        } catch (error) {
            log.warning(`Browser fetch failed: ${error.message}`);
            return null;
        }
    }

    async fetch(url) {
        const maxAttempts = 4;
        const deadline = Date.now() + 240_000;

        for (let attempt = 1; attempt <= maxAttempts; attempt++) {
            if (Date.now() > deadline) break;

            if (!this.httpDisabled) {
                const html = await this.fetchHttp(url);
                if (html) return { html, via: 'http' };

                this.httpFailures++;
                if (this.httpFailures >= 2) {
                    this.httpDisabled = true;
                    log.info('Switching to the browser fetcher for the rest of this run.');
                }
            }

            const html = await this.fetchBrowser(url);
            if (html) {
                this.httpDisabled = true;
                return { html, via: 'browser' };
            }

            if (attempt < maxAttempts) await this.rotate();
        }

        throw new BlockedError(`Unable to load ${url} after ${maxAttempts} attempts.`);
    }

    async closeBrowser() {
        await this.context?.close().catch(() => {});
        this.context = null;
        this.page = null;
        this.browserProxyUrl = undefined;

        if (this.profileDir) {
            await rm(this.profileDir, { recursive: true, force: true }).catch(() => {});
            this.profileDir = null;
        }
    }

    async close() {
        await this.closeBrowser();
    }
}
