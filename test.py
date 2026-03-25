#!/usr/bin/env python3
"""
Google News Site Checker
Run: python check_google_news_sites.py
"""

import feedparser, time

SITES_TO_CHECK = [
    # ── Bulgarian (already confirmed) ──
    ("haskovo.net",         "bg"),
    ("haskovo.info",        "bg"),
    ("marica.bg",           "bg"),
    ("novinite.bg",         "bg"),
    ("dnevnik.bg",          "bg"),
    ("bta.bg",              "bg"),
    ("btv.bg",              "bg"),
    ("nova.bg",             "bg"),
    ("fakti.bg",            "bg"),
    ("plovdivpress.bg",     "bg"),
    ("mvr.bg",              "bg"),
    ("customs.bg",          "bg"),
    ("flagman.bg",          "bg"),
    ("edna.bg",             "bg"),
    ("24chasa.bg",          "bg"),
    ("trud.bg",             "bg"),
    # ── Turkish (already confirmed) ──
    ("haberler.com",        "tr"),
    ("ntv.com.tr",          "tr"),
    ("hurriyet.com.tr",     "tr"),
    ("sabah.com.tr",        "tr"),
    ("milliyet.com.tr",     "tr"),
    ("cumhuriyet.com.tr",   "tr"),
    ("sozcu.com.tr",        "tr"),
    ("trthaber.com",        "tr"),
    ("aa.com.tr",           "tr"),
    ("iha.com.tr",          "tr"),
    ("sondakika.com",       "tr"),
    ("haberturk.com",       "tr"),
    ("ensonhaber.com",      "tr"),
    ("edirnehaber.com",     "tr"),
    ("tr.euronews.com",     "tr"),
    ("t24.com.tr",          "tr"),
    ("birgun.net",          "tr"),
    ("aydinlik.com.tr",     "tr"),
    ("dha.com.tr",          "tr"),
    ("milligazete.com.tr",  "tr"),
    # ── English ──
    ("reuters.com",         "en"),
    ("bbc.com",             "en"),
    ("apnews.com",          "en"),
]

LOCALE = {
    "bg": {"hl": "bg", "gl": "BG", "ceid": "BG:bg"},
    "tr": {"hl": "tr", "gl": "TR", "ceid": "TR:tr"},
    "en": {"hl": "en", "gl": "US", "ceid": "US:en"},
}

# For Turkish sites, search with "bulgaristan" to confirm border relevance
KEYWORD = {
    "bg": "граница",
    "tr": "bulgaristan",
    "en": "bulgaria border",
}

def check_site(domain, lang):
    loc = LOCALE[lang]
    kw  = KEYWORD[lang]
    url = (
        f"https://news.google.com/rss/search?"
        f"q=site:{domain}+{kw}&hl={loc['hl']}&gl={loc['gl']}&ceid={loc['ceid']}"
    )
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": "Mozilla/5.0"})
        return {
            "domain": domain, "lang": lang,
            "count":  len(feed.entries),
            "titles": [e.get("title", "")[:75] for e in feed.entries[:2]],
        }
    except Exception as e:
        return {"domain": domain, "lang": lang, "count": -1, "error": str(e)}

def main():
    print(f"\n{'='*70}")
    print(f"  Google News Site Checker — {len(SITES_TO_CHECK)} sites")
    print(f"{'='*70}\n")

    found, not_found = [], []

    for domain, lang in SITES_TO_CHECK:
        r    = check_site(domain, lang)
        flag = {"bg": "🇧🇬", "tr": "🇹🇷", "en": "🌐"}.get(lang, "")
        if r["count"] > 0:
            print(f"  ✅ {flag} {domain} — {r['count']} results")
            for t in r["titles"]:
                print(f"       • {t}")
            found.append((domain, lang, r["count"]))
        elif r["count"] == 0:
            print(f"  ❌ {flag} {domain} — no results for keyword")
            not_found.append(domain)
        else:
            print(f"  ⚠️  {flag} {domain} — {r.get('error','?')}")
        time.sleep(0.4)

    print(f"\n{'='*70}")
    print(f"  SUMMARY: {len(found)} with results / {len(not_found)} empty")
    print(f"{'='*70}")
    print("\n✅ ADD THESE TO BOT:")
    for domain, lang, count in found:
        flag = {"bg": "🇧🇬", "tr": "🇹🇷", "en": "🌐"}.get(lang, "")
        print(f"   {flag} {domain} ({lang}) — {count} results")
    if not_found:
        print("\n❌ SKIP THESE:")
        for d in not_found:
            print(f"   {d}")
    print()

if __name__ == "__main__":
    main()