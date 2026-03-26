#!/usr/bin/env python3
"""
Run a single scrape cycle for CI/CD workflows.

Why this exists:
- border_news_monitor.py and customs_scraper.py are daemon-style scripts
  with infinite loops.
- GitHub Actions needs a one-shot execution to continue to build/deploy.
"""

from playwright.sync_api import sync_playwright

import border_news_monitor
import customs_scraper


def run_border_cycle_once() -> None:
    try:
        border_news_monitor.check_and_notify()
    except Exception as exc:
        # Keep CI resilient: customs + dashboard generation should still continue.
        print(f"[ci_collect_once] border cycle error: {exc}")


def run_customs_cycle_once() -> None:
    seen = customs_scraper.load_seen()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            # First-run prime logic from customs_scraper.main()
            if not seen:
                page = browser.new_page()
                try:
                    existing, _ = customs_scraper.discover_news_articles(page)
                    for article in existing:
                        seen.add(article["url"])
                    customs_scraper.save_seen(seen)
                finally:
                    page.close()

            new_news, seen = customs_scraper.scrape_once(seen, browser)
            customs_scraper.save_seen(seen)

            if new_news:
                queue = customs_scraper.load_queue()
                queue.extend(new_news)
                queue = queue[-50:]
                customs_scraper.save_queue(queue)
        finally:
            browser.close()


def main() -> None:
    run_border_cycle_once()
    run_customs_cycle_once()
    print("[ci_collect_once] one-shot scrape cycle complete.")


if __name__ == "__main__":
    main()
