#!/usr/bin/env python3
"""
radar_fetch.py — the deterministic, no-AI, no-key fetcher for the /radar skill.

Pulls every free clean feed/API in one shot (parallel), dedupes against seen.json,
captures velocity where the source exposes it (GitHub stars-today, HF trendingScore),
writes the full structured pull to cache/pull-YYYY-MM-DD.json, and prints a compact,
Claude-readable summary to stdout for the skill to filter + synthesize.

Pure standard library (urllib + xml.etree). No pip installs, no API keys.

Usage:
  python3 radar_fetch.py [--out DIR] [--max-per-source N] [--since-days N] [--no-dedup]
"""
import argparse, concurrent.futures as cf, glob, gzip, hashlib, json, os, re, time
import urllib.request, urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
DEFAULT_OUT = os.path.expanduser("~/Downloads/maybeworthbuilding/radar")
TIMEOUT = 20

# ── Source catalog (free, no key). category + route feed the skill's routing. ──
# route: SI=startup-ideas, MWB=mwb-research, CAP=capability-map
RSS_SOURCES = [
    # key, name, url, category, route
    ("smol",        "Smol AI News",        "https://news.smol.ai/rss.xml",                       "newsletter", "MWB+SI+CAP"),
    ("alphasignal", "AlphaSignal",         "https://alphasignalai.substack.com/feed",            "newsletter", "SI+CAP"),
    ("importai",    "Import AI",           "https://importai.substack.com/feed",                 "newsletter", "CAP"),
    ("latentspace", "Latent Space",        "https://www.latent.space/feed",                      "newsletter", "CAP+SI"),
    ("theneuron",   "The Neuron",          "https://rss.beehiiv.com/feeds/N4eCstxvgX.xml",       "newsletter", "MWB"),
    ("rundown",     "The Rundown AI",      "https://rss.beehiiv.com/feeds/2R3C6Bt5wj.xml",       "newsletter", "MWB"),
    ("lastweek",    "Last Week in AI",     "https://lastweekin.ai/feed",                         "newsletter", "CAP"),
    ("bensbites",   "Ben's Bites",         "https://www.bensbites.com/feed",                     "newsletter", "SI"),
    ("arxiv",       "arXiv cs.AI/CL/LG",   "https://rss.arxiv.org/rss/cs.AI+cs.CL+cs.LG",        "research",   "CAP"),
    ("hfpapers",    "HF Daily Papers",     "https://papers.takara.ai/api/feed",                  "research",   "CAP"),
    ("producthunt", "Product Hunt",        "https://www.producthunt.com/feed",                   "market",     "SI"),
    ("yc",          "YC Launches",         "https://hnrss.org/launches",                         "market",     "SI"),
    ("dwarkesh",    "Dwarkesh (pod)",      "https://www.dwarkesh.com/feed",                      "longform",   "CAP"),

    # ── PRIMARY SOURCES (wired 2026-06-05) ────────────────────────────────────
    # The point: stop being downstream of the aggregators competitors also read.
    # These are the labs/press/analyst AT THE SOURCE, so we can catch a release or a
    # raise hours before Smol AI re-reports it, and collapse duplicates to the primary.
    # All verified free / no-key / clean RSS on 2026-06-05.
    ("openai",      "OpenAI (blog)",       "https://openai.com/news/rss.xml",                    "lab",        "CAP+MWB+SI"),
    ("deepmind",    "Google DeepMind (blog)", "https://deepmind.google/blog/rss.xml",            "lab",        "CAP"),
    ("hfblog",      "Hugging Face (blog)", "https://huggingface.co/blog/feed.xml",               "lab",        "CAP+SI"),
    ("tcventure",   "TechCrunch Venture",  "https://techcrunch.com/category/venture/feed/",      "funding",    "SI+MWB"),
    ("tcai",        "TechCrunch AI",       "https://techcrunch.com/category/artificial-intelligence/feed/", "market", "MWB+SI+CAP"),
    ("simonw",      "Simon Willison (blog)", "https://simonwillison.net/atom/everything/",       "longform",   "CAP+SI"),
    # NOTE: Anthropic has no clean public RSS (404 on the obvious paths) — covered via
    # @AnthropicAI in TWITTER_ACCOUNTS + the Claude Code changelog fetcher.
    # STILL A GAP (paid/brittle, v2): Artificial Analysis cost API + the LMArena/SWE-bench
    # leaderboard diff (the "frontier moving / price dropping" derivative). Until those are
    # wired, capability-trajectory.md is the manual stand-in — refresh it on each radar run.
]

# YouTube uploads — fetched sequentially in one task (YouTube throttles concurrent feed
# hits from one IP as 404). AI Explained dropped: its channel feed returns a hard 404.
YOUTUBE = [
    ("Fireship",        "UCsBjURrPoezykLs9EqgamOA", "MWB"),
    ("Matthew Berman",  "UCawZsQWqfGSbCI5yjkdVkTA", "MWB"),
    ("Matt Wolfe",      "UChpleBmo18P08aKCIgti38g", "MWB+SI"),
]

# Free Reddit (native subreddit top/day RSS — vote-ranked, no key, no Apify).
# Reddit's JSON (with raw scores) is 403-blocked unauthenticated; top/day ORDER is the magnitude proxy.
SUBREDDITS = [
    ("LocalLLaMA", "CAP+SI"), ("MachineLearning", "CAP"), ("StableDiffusion", "CAP+MWB"),
    ("OpenAI", "CAP+MWB"), ("ClaudeAI", "CAP"), ("singularity", "MWB"),
    ("SideProject", "SI+MWB"), ("Entrepreneur", "SI"),
]

# Free Twitter/X (syndication timeline endpoint — no login, no key, no Apify; curated watchlist only).
# X can kill this anytime; FETCH STATUS will flag it. Skewed to MWB's founder/builder + frontier mix.
TWITTER_ACCOUNTS = [
    "OpenAI", "AnthropicAI", "GoogleDeepMind", "MistralAI",
    "sama", "karpathy", "swyx", "levelsio", "AravSrinivas",
    "alexalbert__", "simonw", "garrytan", "emollick", "_akhaliq",
]

# ── HTTP ──────────────────────────────────────────────────────────────────────
# Optional rotating residential proxy (Webshare) for SOURCE fetches only. Set RADAR_PROXY to dodge the
# datacenter-IP 403/429 blocks some feeds (AlphaSignal, Import AI, Reddit, X) apply. Scoped to a
# dedicated env var (NOT HTTP_PROXY) so it never touches the Supabase / Anthropic clients.
_RADAR_PROXY = os.environ.get("RADAR_PROXY")
_OPENER = (urllib.request.build_opener(urllib.request.ProxyHandler({"http": _RADAR_PROXY, "https": _RADAR_PROXY}))
           if _RADAR_PROXY else urllib.request.build_opener())

def http_get(url, timeout=TIMEOUT, retries=2):
    # Retry transient errors with backoff. YouTube throttles bursts as 404, so 404 is
    # retried too (no source in the catalog returns a *persistent* 404 anymore).
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip", "Accept": "*/*"})
            with _OPENER.open(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw
        except Exception as e:
            last = e
        if attempt < retries:
            time.sleep(1.2 * (attempt + 1))
    raise last

def http_json(url, timeout=TIMEOUT):
    return json.loads(http_get(url, timeout).decode("utf-8", "replace"))

# ── RSS / Atom parsing (tolerant, namespace-agnostic) ────────────────────────
def _tag(el):
    return el.tag.split("}", 1)[-1].lower()

def parse_feed(raw, max_items):
    txt = raw.decode("utf-8", "replace")
    root = ET.fromstring(txt)
    nodes = [el for el in root.iter() if _tag(el) in ("item", "entry")]
    items = []
    for node in nodes[:max_items]:
        title = link = date = summary = ""
        for c in node:
            t = _tag(c)
            if t == "title" and not title:
                title = (c.text or "").strip()
            elif t == "link" and not link:
                link = (c.get("href") or c.text or "").strip()
            elif t in ("pubdate", "published", "updated", "date") and not date:
                date = (c.text or "").strip()
            elif t in ("description", "summary") and not summary:
                summary = re.sub("<[^>]+>", "", (c.text or "")).strip()
        if title:
            items.append({"title": title, "link": link, "date": date, "summary": summary[:300]})
    return items

# ── Per-source fetchers ──────────────────────────────────────────────────────
def fetch_rss(src, max_items):
    key, name, url, cat, route = src
    items = parse_feed(http_get(url), max_items)
    return [dict(it, source=name, source_key=key, category=cat, route=route) for it in items]

def fetch_hn(max_items):
    out = []
    for tag, label in (("front_page", "HN front page"), ("show_hn", "HN Show HN")):
        api = ("https://hn.algolia.com/api/v1/search?tags=%s&hitsPerPage=%d" % (tag, max_items)
               if tag == "front_page"
               else "https://hn.algolia.com/api/v1/search_by_date?tags=%s&hitsPerPage=%d" % (tag, max_items))
        try:
            d = http_json(api)
            for h in d.get("hits", []):
                title = h.get("title") or h.get("story_title") or ""
                if not title:
                    continue
                link = h.get("url") or ("https://news.ycombinator.com/item?id=%s" % h.get("objectID"))
                pts, cmts = h.get("points") or 0, h.get("num_comments") or 0
                out.append({"title": title, "link": link, "date": h.get("created_at", ""),
                            "summary": "%d points · %d comments" % (pts, cmts),
                            "velocity": pts, "source": label, "source_key": "hn",
                            "category": "social", "route": "SI+MWB"})
        except Exception as e:
            out.append({"_error": "%s: %s" % (label, e), "source": label, "source_key": "hn"})
    return out

def fetch_hf(max_items):
    out = []
    for kind, label in (("models", "HF trending models"), ("spaces", "HF trending spaces")):
        try:
            d = http_json("https://huggingface.co/api/%s?sort=trendingScore&limit=%d&full=false" % (kind, max_items))
            for m in d:
                mid = m.get("id") or m.get("modelId") or ""
                if not mid:
                    continue
                score = m.get("trendingScore")
                out.append({"title": mid, "link": "https://huggingface.co/%s" % mid,
                            "date": m.get("lastModified", ""),
                            "summary": ("trendingScore %s" % score) if score is not None else "",
                            "velocity": score, "source": label, "source_key": "hf",
                            "category": "models", "route": "CAP+SI"})
        except Exception as e:
            out.append({"_error": "%s: %s" % (label, e), "source": label, "source_key": "hf"})
    return out

def fetch_mcp(max_items):
    last_err = None
    for path in ("v0.1/servers", "v0/servers"):
        try:
            d = http_json("https://registry.modelcontextprotocol.io/%s?limit=%d" % (path, max_items))
            servers = d.get("servers") or d.get("data") or []
            out = []
            for e in servers[:max_items]:
                srv = e.get("server", e) if isinstance(e, dict) else {}
                nm = srv.get("name", "")
                if not nm:
                    continue
                repo = srv.get("repository")
                link = repo.get("url", "") if isinstance(repo, dict) else ""
                if not link:
                    rem = srv.get("remotes") or []
                    if rem and isinstance(rem[0], dict):
                        link = rem[0].get("url", "")
                meta = e.get("_meta", {}) if isinstance(e, dict) else {}
                off = meta.get("io.modelcontextprotocol.registry/official", {}) if isinstance(meta, dict) else {}
                date = off.get("updatedAt") or off.get("publishedAt", "")
                out.append({"title": nm, "link": link, "date": date,
                            "summary": (srv.get("description") or "")[:200],
                            "source": "MCP Registry", "source_key": "mcp",
                            "category": "claude", "route": "CAP"})
            return out
        except Exception as e:
            last_err = e
    return [{"_error": "MCP Registry: %s" % last_err, "source": "MCP Registry", "source_key": "mcp"}]

def fetch_claude_changelog():
    try:
        raw = http_get("https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md").decode("utf-8", "replace")
        blocks = re.split(r"\n##\s+", raw)
        head = blocks[1] if len(blocks) > 1 else raw[:1200]
        ver = head.splitlines()[0].strip()
        body = "\n".join(head.splitlines()[1:])[:1200].strip()
        return [{"title": "Claude Code %s" % ver,
                 "link": "https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md",
                 "date": "", "summary": body, "source": "Claude Code changelog",
                 "source_key": "claudecode", "category": "claude", "route": "CAP"}]
    except Exception as e:
        return [{"_error": "Claude Code changelog: %s" % e, "source": "Claude Code changelog", "source_key": "claudecode"}]

def fetch_github_trending(max_items):
    try:
        html = http_get("https://github.com/trending?since=daily").decode("utf-8", "replace")
        out = []
        for chunk in re.split(r'class="Box-row"', html)[1:]:
            m = re.search(r'<h2[^>]*>\s*<a[^>]*href="/([^"]+)"', chunk)
            if not m:
                continue
            repo = re.sub(r"\s+", "", m.group(1))
            sm = re.search(r'([\d,]+)\s+stars today', chunk)
            stars_today = int(sm.group(1).replace(",", "")) if sm else None
            dm = re.search(r'<p class="col-9[^"]*"[^>]*>\s*(.*?)</p>', chunk, re.S)
            desc = re.sub(r"<[^>]+>", "", dm.group(1)).strip()[:200] if dm else ""
            summ = (("%s stars today" % stars_today) + ((" — " + desc) if desc else "")) if stars_today else desc
            out.append({"title": repo, "link": "https://github.com/%s" % repo, "date": "",
                        "summary": summ, "velocity": stars_today,
                        "source": "GitHub Trending (daily)", "source_key": "ghtrend",
                        "category": "repos", "route": "SI+CAP"})
            if len(out) >= max_items:
                break
        if not out:
            return [{"_error": "GitHub Trending: parsed 0 rows (markup changed?)", "source": "GitHub Trending (daily)", "source_key": "ghtrend"}]
        return out
    except Exception as e:
        return [{"_error": "GitHub Trending: %s" % e, "source": "GitHub Trending (daily)", "source_key": "ghtrend"}]

def fetch_youtube(max_items, out_dir):
    # Same persistent-cache pattern as Twitter: YouTube throttles concurrent/rapid feed hits
    # from one IP (as 404), so we refresh stalest-first, stop on throttle, and serve the rest
    # from youtube_cache.json. Cache-served videos are marked stale (never counted as new).
    per = max(4, max_items)
    cache_path = os.path.join(out_dir, "youtube_cache.json")
    try:
        cache = json.load(open(cache_path))
    except Exception:
        cache = {}
    now = datetime.now(timezone.utc).isoformat()
    order = sorted(YOUTUBE, key=lambda c: cache.get(c[1], {}).get("fetched", ""))  # stalest first
    refreshed, throttled, errs = set(), False, []
    for name, cid, route in order:
        if throttled:
            break
        try:
            raw = http_get("https://www.youtube.com/feeds/videos.xml?channel_id=%s" % cid)
            items = [{"title": it["title"], "link": it["link"], "date": it.get("date", ""),
                      "summary": "", "source": "YouTube: %s" % name,
                      "source_key": "yt_%s" % cid[-6:], "category": "longform", "route": route}
                     for it in parse_feed(raw, per)]
            cache[cid] = {"fetched": now, "items": items}
            refreshed.add(cid)
            time.sleep(1.5)
        except Exception as e:
            code = str(getattr(e, "code", type(e).__name__))
            errs.append("%s (%s)" % (name, code))
            if code in ("404", "429"):
                throttled = True  # burst-throttle; stop and serve rest from cache
    try:
        json.dump(cache, open(cache_path, "w"))
    except Exception:
        pass
    out = []
    for name, cid, route in YOUTUBE:
        entry = cache.get(cid)
        if not entry:
            continue
        for it in entry.get("items", []):
            it2 = dict(it)
            if cid not in refreshed:
                it2["stale"] = True
            out.append(it2)
    if not out:
        out.append({"_error": "YouTube: 0 channels reachable and no cache yet", "source": "YouTube", "source_key": "youtube"})
    return out

def fetch_reddit(max_items):
    out, failed = [], []
    per = max(3, max_items // 2)
    for sub, route in SUBREDDITS:
        try:
            raw = http_get("https://www.reddit.com/r/%s/top/.rss?t=day" % sub)
            for it in parse_feed(raw, per):
                out.append({"title": it["title"], "link": it["link"], "date": it.get("date", ""),
                            "summary": "r/%s · top today (vote-ranked)" % sub,
                            "source": "Reddit r/%s" % sub, "source_key": "reddit_%s" % sub.lower(),
                            "category": "social", "route": route})
            time.sleep(0.4)  # be polite to Reddit
        except Exception as e:
            failed.append("%s (%s)" % (sub, getattr(e, "code", type(e).__name__)))
    if failed:
        out.append({"_error": "Reddit partial: %d/%d subs ok; failed: %s"
                    % (len(SUBREDDITS) - len(failed), len(SUBREDDITS), ", ".join(failed)),
                    "source": "Reddit", "source_key": "reddit"})
    return out

def _parse_syndication(html, screen_name):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return []
    data = json.loads(m.group(1))
    tweets, seen_ids = [], set()
    def walk(o):
        if isinstance(o, dict):
            if "full_text" in o and "created_at" in o and o.get("id_str"):
                tweets.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    out = []
    for t in tweets:
        tid = t.get("id_str")
        if tid in seen_ids:
            continue
        seen_ids.add(tid)
        sn = (t.get("user") or {}).get("screen_name") or screen_name
        favs = t.get("favorite_count")
        out.append({"title": "@%s: %s" % (sn, (t.get("full_text") or "").replace("\n", " ")[:180]),
                    "link": "https://twitter.com/%s/status/%s" % (sn, tid),
                    "date": t.get("created_at", ""),
                    "summary": ("%s likes" % favs) if isinstance(favs, int) else "",
                    "velocity": favs if isinstance(favs, int) else None,
                    "source": "X: @%s" % screen_name, "source_key": "x_%s" % screen_name.lower(),
                    "category": "social", "route": "SI+MWB+CAP"})
    return out

def fetch_twitter(max_items, out_dir):
    # The syndication endpoint is a tight per-IP token bucket: a handful of requests, then a
    # multi-minute cooldown. So we keep a PERSISTENT rotating cache (social_cache.json):
    # each run refreshes the stalest accounts first, STOPS the moment it hits a 429 (no point
    # hammering), and serves every other account from cache. Over a couple of daily runs the
    # whole watchlist stays warm. Freshly-refreshed tweets are eligible as "new"; cache-served
    # tweets are marked stale (never counted as new).
    per = max(2, max_items // 4)
    cache_path = os.path.join(out_dir, "social_cache.json")
    try:
        cache = json.load(open(cache_path))
    except Exception:
        cache = {}
    now = datetime.now(timezone.utc).isoformat()
    order = sorted(TWITTER_ACCOUNTS, key=lambda a: cache.get(a, {}).get("fetched", ""))  # stalest first
    REFRESH_CAP = 8        # cap per run so interactive runtime stays bounded (~CAP*6s)
    SPACING = 6.0          # the bucket refills ~1 req / several sec; 6s keeps under it
    refreshed, throttled, errs = set(), None, []
    for sn in order[:REFRESH_CAP]:
        if throttled:
            break
        try:
            html = http_get("https://syndication.twitter.com/srv/timeline-profile/screen-name/%s" % sn).decode("utf-8", "replace")
            cache[sn] = {"fetched": now, "items": _parse_syndication(html, sn)[:per]}
            refreshed.add(sn)
            time.sleep(SPACING)
        except Exception as e:
            code = str(getattr(e, "code", type(e).__name__))
            errs.append("%s (%s)" % (sn, code))
            if code == "429":
                throttled = sn  # bucket empty; stop and serve the rest from cache
    try:
        json.dump(cache, open(cache_path, "w"))
    except Exception:
        pass
    out = []
    for sn in TWITTER_ACCOUNTS:
        entry = cache.get(sn)
        if not entry:
            continue
        for it in entry.get("items", []):
            it2 = dict(it)
            if sn not in refreshed:
                it2["stale"] = True
            out.append(it2)
    if not out:  # truly nothing (no cache yet AND throttled) — surface it
        out.append({"_error": "X: 0 accounts reachable and no cache yet; throttled on %s" % (throttled or "n/a"),
                    "source": "X/Twitter", "source_key": "x"})
    return out

# ── Dedup ────────────────────────────────────────────────────────────────────
def fingerprint(it):
    norm = re.sub(r"\W+", "", (it.get("source_key", "") + (it.get("title", "")).lower()))
    return hashlib.sha1(norm.encode()).hexdigest()[:16]

def load_seen(path):
    try:
        return json.load(open(path))
    except Exception:
        return {}

def prune_seen(seen, days=30):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    return {k: v for k, v in seen.items() if v >= cutoff}

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--max-per-source", type=int, default=15)
    ap.add_argument("--since-days", type=int, default=30, help="seen.json retention window")
    ap.add_argument("--no-dedup", action="store_true")
    ap.add_argument("--no-social", action="store_true", help="skip free Reddit + Twitter (use if they start blocking)")
    args = ap.parse_args()

    out_dir = os.path.expanduser(args.out)
    cache_dir = os.path.join(out_dir, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    mx = args.max_per_source

    tasks = [(src[1], (lambda s=src: fetch_rss(s, mx))) for src in RSS_SOURCES]
    tasks += [
        ("HN", lambda: fetch_hn(mx)),
        ("HuggingFace", lambda: fetch_hf(mx)),
        ("MCP Registry", lambda: fetch_mcp(mx)),
        ("Claude Code changelog", fetch_claude_changelog),
        ("GitHub Trending", lambda: fetch_github_trending(mx)),
    ]
    tasks.append(("YouTube", lambda: fetch_youtube(mx, out_dir)))
    if not args.no_social:
        tasks += [
            ("Reddit", lambda: fetch_reddit(mx)),
            ("X/Twitter", lambda: fetch_twitter(mx, out_dir)),
        ]

    results, status = [], []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(fn): name for name, fn in tasks}
        for fut in cf.as_completed(futs):
            name = futs[fut]
            try:
                items = fut.result()
                errs = [it for it in items if it.get("_error")]
                good = [it for it in items if not it.get("_error")]
                results.extend(good)
                if errs:
                    for e in errs:
                        status.append(("FAIL", e.get("source", name), e["_error"]))
                else:
                    status.append(("OK", name, "%d items" % len(good)))
            except Exception as e:
                status.append(("FAIL", name, str(e)))

    # Cache-fallback: if a flaky social source (Twitter/Reddit/YouTube) got throttled this
    # run, reuse its items from the most recent prior pull so the source doesn't vanish.
    # Stale items are NEVER counted as new (they were already seen).
    present = {it.get("source_key") for it in results}
    prev_files = sorted(glob.glob(os.path.join(cache_dir, "pull-*.json")))
    if prev_files:
        try:
            prev_items = json.load(open(prev_files[-1])).get("items", [])
        except Exception:
            prev_items = []
        for it in prev_items:
            sk = it.get("source_key", "")
            if sk and sk not in present and sk.startswith(("x_", "reddit_", "yt_")):
                clean = {k: v for k, v in it.items() if not k.startswith("_") and k not in ("is_new", "stale")}
                clean["stale"] = True
                results.append(clean)

    seen = {} if args.no_dedup else load_seen(os.path.join(out_dir, "seen.json"))
    for it in results:
        fp = fingerprint(it)
        it["_fp"] = fp
        it["is_new"] = (fp not in seen) and not it.get("stale")
    new_items = [it for it in results if it["is_new"]]

    pull_path = os.path.join(cache_dir, "pull-%s.json" % today)
    json.dump({"date": today, "items": results, "status": status}, open(pull_path, "w"), indent=1)

    if not args.no_dedup:
        for it in new_items:
            seen[it["_fp"]] = today
        seen = prune_seen(seen, args.since_days)
        json.dump(seen, open(os.path.join(out_dir, "seen.json"), "w"))

    p = print
    p("# RADAR PULL %s" % today)
    p("total_items=%d  new_items=%d  sources_ok=%d  sources_failed=%d"
      % (len(results), len(new_items),
         sum(1 for s in status if s[0] == "OK"), sum(1 for s in status if s[0] == "FAIL")))
    p("full_pull_json=%s" % pull_path)
    p("")
    p("## FETCH STATUS (no silent gaps)")
    for st, name, msg in sorted(status):
        p("- [%s] %s — %s" % (st, name, msg))
    p("")

    x_items = [it for it in results if it.get("source_key", "").startswith("x_")]
    if x_items:
        x_fresh = sum(1 for it in x_items if not it.get("stale"))
        p("X/Twitter freshness: %d tweets in pull · %d refreshed this run · %d from rotating cache"
          % (len(x_items), x_fresh, len(x_items) - x_fresh))
        p("")

    vel = [it for it in new_items if isinstance(it.get("velocity"), (int, float))]
    vel.sort(key=lambda x: x["velocity"], reverse=True)
    if vel:
        p("## VELOCITY HIGHLIGHTS (the derivative = the signal)")
        for it in vel[:20]:
            p("- [%s] %s (%s) %s" % (it["source"], it["title"], it.get("velocity"), it.get("link", "")))
        p("")

    p("## NEW SINCE LAST RUN (grouped by source)")
    bysrc = {}
    for it in new_items:
        bysrc.setdefault(it["source"], []).append(it)
    for srcname in sorted(bysrc):
        rows = bysrc[srcname]
        p("### %s  [route: %s]  (%d new)" % (srcname, rows[0].get("route", ""), len(rows)))
        for it in rows[:mx]:
            line = "- %s" % it["title"]
            if it.get("link"):
                line += "  <%s>" % it["link"]
            if it.get("summary"):
                line += "\n    %s" % it["summary"]
            p(line)
        p("")

    if not new_items:
        p("(No new items since last run. Re-run with --no-dedup to see everything.)")

if __name__ == "__main__":
    main()
