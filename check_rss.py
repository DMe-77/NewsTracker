#!/usr/bin/env python3
"""
Direct RSS Feed Checker
Tests whether sites have their own RSS feeds, bypassing Google News indexing delay.
Run: python check_rss_feeds.py
"""

import feedparser, requests, time
from urllib.parse import urljoin

# Common RSS path patterns to try
RSS_PATHS = [
    "/rss",
    "/rss.xml",
    "/feed",
    "/feed.xml",
    "/feed/rss",
    "/feeds/posts/default",
    "/rss/news",
    "/news/rss",
    "/rss/all",
    "/atom.xml",
    "/index.xml",
]

SITES = [
    ("https://iha.com.tr",       "tr"),
    ("https://sondakika.com",    "tr"),
    ("https://haberturk.com",    "tr"),
    ("https://ensonhaber.com",   "tr"),
    ("https://tr.euronews.com",  "tr"),
    ("https://t24.com.tr",       "tr"),
    ("https://dha.com.tr",       "tr"),
    ("https://milligazete.com.tr","tr"),
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RSSChecker/1.0)"}
TIMEOUT  = 8


def find_rss(base_url: str) -> list[dict]:
    """Try common RSS paths and return working ones."""
    found = []

    # First try to autodiscover from homepage <link rel="alternate">
    try:
        resp = requests.get(base_url, headers=HEADERS, timeout=TIMEOUT)
        html = resp.text.lower()
        # Look for RSS/Atom link tags
        import re
        links = re.findall(r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>', html)
        for link in links:
            href = re.search(r'href=["\']([^"\']+)["\']', link)
            if href:
                url = href.group(1)
                if not url.startswith("http"):
                    url = urljoin(base_url, url)
                feed = feedparser.parse(url, request_headers=HEADERS)
                if feed.entries:
                    found.append({"url": url, "count": len(feed.entries), "method": "autodiscover"})
    except Exception:
        pass

    if found:
        return found

    # Try common paths
    for path in RSS_PATHS:
        url = base_url.rstrip("/") + path
        try:
            feed = feedparser.parse(url, request_headers=HEADERS)
            if feed.entries and len(feed.entries) > 0:
                found.append({"url": url, "count": len(feed.entries), "method": "path"})
                break  # Found one, stop trying
        except Exception:
            pass
        time.sleep(0.1)

    return found


def main():
    print(f"\n{'='*70}")
    print(f"  Direct RSS Feed Checker — {len(SITES)} sites")
    print(f"{'='*70}\n")

    has_rss     = []
    no_rss      = []

    for base_url, lang in SITES:
        domain = base_url.replace("https://", "").replace("http://", "")
        flag   = {"bg": "🇧🇬", "tr": "🇹🇷"}.get(lang, "🌐")
        print(f"  Checking {flag} {domain}...", end=" ", flush=True)

        feeds = find_rss(base_url)
        if feeds:
            best = feeds[0]
            print(f"✅ {best['url']} ({best['count']} items)")
            has_rss.append({"domain": domain, "lang": lang, "url": best["url"], "count": best["count"]})
        else:
            print("❌ no RSS found")
            no_rss.append(domain)

        time.sleep(0.5)

    print(f"\n{'='*70}")
    print(f"  SUMMARY: {len(has_rss)} have RSS / {len(no_rss)} don't")
    print(f"{'='*70}")

    if has_rss:
        print("\n✅ DIRECT RSS AVAILABLE (faster than Google News):")
        for s in has_rss:
            flag = {"bg": "🇧🇬", "tr": "🇹🇷"}.get(s["lang"], "🌐")
            print(f"   {flag} {s['domain']}")
            print(f"      {s['url']}")

    if no_rss:
        print("\n❌ NO DIRECT RSS (keep using Google News):")
        for d in no_rss:
            print(f"   {d}")
    print()


if __name__ == "__main__":
    main()