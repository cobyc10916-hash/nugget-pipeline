#!/usr/bin/env python3
"""
NUGGET pipeline — discover → fetch transcript → extract nuggets → write to Supabase.

Runs ~2x/day (cron on the VPS, or a Claude Max routine — see PROMPT.md). Reuses the
proven discovery (yt-dlp topic search), transcript (Webshare proxy), and anti-slip state
patterns from the repo's morning-brief / breakout_scan code.

Env (.env in this dir):
  WEBSHARE_PROXY_USERNAME, WEBSHARE_PROXY_PASSWORD   (transcript proxy — already in repo .env)
  SUPABASE_URL, SUPABASE_SERVICE_KEY                 (service-role; bypasses RLS to write content)
  ANTHROPIC_API_KEY                                  (Haiku extraction; OR run via Max routine, PROMPT.md)

Usage:
  python pipeline.py discover            # find videos -> discovery_queue
  python pipeline.py run --limit 20      # discover + extract N pending -> Supabase
"""
from __future__ import annotations

import argparse, json, os, re, subprocess, sys, time, urllib.parse, hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "state"; STATE.mkdir(exist_ok=True)
SEEN = STATE / "seen.json"

try:
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
    load_dotenv(HERE.parents[1] / ".env")  # fall back to repo .env for proxy creds
except Exception:
    pass

WS_USER = os.environ.get("WEBSHARE_PROXY_USERNAME")
WS_PASS = os.environ.get("WEBSHARE_PROXY_PASSWORD")
PROXY = f"http://{WS_USER}-rotate:{WS_PASS}@p.webshare.io:80" if WS_USER and WS_PASS else None
# Route plain HTTP discovery (RSS) through the proxy too: cloud runners (GitHub Actions
# Azure IPs) get throttled/blocked by YouTube otherwise. None locally falls back to direct.
RPROXIES = {"http": PROXY, "https": PROXY} if PROXY else None
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY")

CORPUS = json.loads((HERE / "interests.json").read_text())
F = CORPUS["filters"]

# ---------------- state ----------------
def load_seen() -> set[str]:
    return set(json.loads(SEEN.read_text())) if SEEN.exists() else set()
def save_seen(s: set[str]):
    SEEN.write_text(json.dumps(sorted(s)[-8000:]))

# ---------------- supabase (service role) ----------------
def sb():
    from supabase import create_client
    if not (SUPABASE_URL and SUPABASE_KEY):
        sys.exit("Set SUPABASE_URL + SUPABASE_SERVICE_KEY in nugget/backend/.env")
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------- discovery (yt-dlp) ----------------
def ytdlp(args, timeout=180):
    cmd = ["yt-dlp", "--no-warnings"] + (["--proxy", PROXY] if PROXY else [])
    return subprocess.run(cmd + list(args), capture_output=True, text=True, timeout=timeout).stdout

def search(query, _retry=True):
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    out = ytdlp(["--flat-playlist", "-J", "--playlist-end", "20", url])
    if not out.strip():
        if _retry:
            time.sleep(12); return search(query, _retry=False)
        return []
    try:
        entries = (json.loads(out).get("entries") or [])
    except Exception:
        return []
    hits = []
    for e in entries:
        if not e or e.get("ie_key") != "Youtube":
            continue
        vc, dur = e.get("view_count"), e.get("duration")
        if vc and dur and vc >= F["min_views"] and F["min_duration_s"] <= dur <= F["max_duration_s"]:
            hits.append({"video_id": e.get("id"), "title": e.get("title"),
                         "channel": e.get("channel") or e.get("uploader"),
                         "channel_id": e.get("channel_id"), "views": vc, "duration": dur})
    return hits

def rss(channel_id, max_n=6):
    import xml.etree.ElementTree as ET
    import requests
    r = requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}", timeout=30, proxies=RPROXIES, headers=RSS_HEADERS)
    ids = re.findall(r"<yt:videoId>([^<]+)</yt:videoId>", r.text)[:max_n]
    titles = re.findall(r"<media:title>([^<]+)</media:title>", r.text)[:max_n]
    return [{"video_id": v, "title": t, "channel_id": channel_id} for v, t in zip(ids, titles)]

# YouTube's RSS endpoint soft-rate-limits PER IP: identical requests intermittently 404/500 once an
# IP gets warm, then recover. (Confirmed 2026-06-25 — not a User-Agent issue; every UA behaves the
# same.) The real defenses are below: hit the rotating Webshare proxy FIRST (fresh IP per request),
# retry with backoff, and throttle between channels. The browser UA is just hygiene.
RSS_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

class FeedFetchError(Exception):
    """A channel's RSS could not be fetched after all retries. Distinct from 'fetched fine, no new
    uploads' so callers can tell a YouTube/proxy OUTAGE apart from a simply-quiet channel."""

def channel_recent(channel_id, name, tries=2):
    """Newest uploads from a channel via its RSS feed (with published timestamps). Hits the rotating
    Webshare proxy FIRST (a fresh residential IP each attempt dodges YouTube's per-IP RSS rate-limit),
    falling back to a DIRECT fetch (GitHub's datacenter IP, usually blocked), and retries the whole
    pair with backoff. RAISES FeedFetchError if every attempt fails, so an outage surfaces loudly
    instead of looking like 'no new videos'."""
    import requests
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    paths = ([("proxy", RPROXIES)] if RPROXIES else []) + [("direct", None)]
    last = "no attempt"
    for attempt in range(tries):
        for how, proxies in paths:
            try:
                # 15s timeout keeps worst-case runtime bounded (29 channels x tries x paths) under
                # the 25-min job cap even when every request hangs.
                r = requests.get(url, timeout=15, proxies=proxies, headers=RSS_HEADERS)
                if r.status_code == 200 and "<yt:videoId>" in r.text:
                    out = []
                    for e in re.findall(r"<entry>(.*?)</entry>", r.text, re.S):
                        vid = re.search(r"<yt:videoId>([^<]+)</yt:videoId>", e)
                        title = re.search(r"<media:title>([^<]+)</media:title>", e)
                        pub = re.search(r"<published>([^<]+)</published>", e)
                        if vid and pub:
                            out.append({"video_id": vid.group(1), "title": title.group(1) if title else "",
                                        "channel": name, "published": pub.group(1)})
                    return out
                last = f"{how} status={r.status_code} bytes={len(r.text)}"
            except Exception as ex:
                last = f"{how} {type(ex).__name__}: {str(ex)[:80]}"
        if attempt < tries - 1:
            time.sleep(1.5 * (attempt + 1))  # 1.5s, 3s between full direct+proxy rounds
    print(f"  [rss] {name}: FAILED ({last})")
    raise FeedFetchError(f"{name}: {last}")

def published_date(vid):
    """Best-effort upload date (YYYY-MM-DD) via yt-dlp; None on failure (proxy-aware)."""
    try:
        out = ytdlp(["--skip-download", "--print", "%(upload_date)s",
                     f"https://www.youtube.com/watch?v={vid}"], timeout=60).strip()
        if len(out) == 8 and out.isdigit():
            return f"{out[0:4]}-{out[4:6]}-{out[6:8]}"
    except Exception:
        pass
    return None

def discover():
    client = sb()
    seen = load_seen()
    existing = {r["video_id"] for r in client.table("videos").select("video_id").execute().data}
    queued = {r["video_id"] for r in client.table("discovery_queue").select("video_id").execute().data}
    skip = seen | existing | queued
    rows = []
    for area, cfg in CORPUS["areas"].items():
        for q in cfg["queries"]:
            for h in search(q):
                vid = h["video_id"]
                if not vid or vid in skip:
                    continue
                skip.add(vid); seen.add(vid)
                rows.append({"video_id": vid, "source": "daily_search", "found_via": q,
                             "interest_area": area, "raw_views": h["views"],
                             "duration_s": h["duration"], "seed_score": float(h["views"])})
            time.sleep(3)
    for ch in CORPUS.get("promoted_channels", []):
        for h in rss(ch["channel_id"]):
            vid = h["video_id"]
            if vid in skip:
                continue
            skip.add(vid); seen.add(vid)
            rows.append({"video_id": vid, "source": "rss", "found_via": ch["name"],
                         "interest_area": None, "seed_score": 1e9})  # curated -> top priority
    if rows:
        client.table("discovery_queue").upsert(rows, on_conflict="video_id").execute()
    save_seen(seen)
    print(f"[discover] queued {len(rows)} new videos")
    return len(rows)

def monitored_channels():
    """All channels we monitor daily, tagged by area. Merges the three vertical lists in
    interests.json (ai_channels / build_channels / str_channels)."""
    out = []
    for area, key in (("ai", "ai_channels"), ("build", "build_channels"), ("str", "str_channels")):
        for ch in CORPUS.get(key, []):
            out.append({"channel_id": ch["channel_id"], "name": ch["name"], "area": area})
    return out

CHANNEL_ID_BY_NAME = {c["name"]: c["channel_id"] for c in monitored_channels()}

ONLY_YEAR = 2026  # hard rule: every video pulled (daily or backfill) must be published in 2026

def discover_recent(hours=24):
    """Queue EVERY new upload from the monitored channels published within the last `hours` (and in
    2026) that we have not already seen / queued / extracted. No per-run cap: each run picks up all
    the new in-window posts. The Supabase dedupe (existing videos + already-queued) persists across
    runs, so this is exactly 'whatever the channels posted since the last run'."""
    from datetime import datetime, timezone, timedelta
    client = sb()
    seen = load_seen()
    existing = {r["video_id"] for r in client.table("videos").select("video_id").execute().data}
    queued = {r["video_id"] for r in client.table("discovery_queue").select("video_id").execute().data}
    skip = seen | existing | queued
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    cands = []
    ok = failed = 0
    chans = monitored_channels()
    for i, ch in enumerate(chans):
        if i:
            time.sleep(1.0)  # throttle between channels: stay under YouTube's per-IP RSS rate-limit
        try:
            feed = channel_recent(ch["channel_id"], ch["name"])
            ok += 1
        except Exception:
            failed += 1
            continue
        for v in feed:
            if v["video_id"] in skip:
                continue
            pub = datetime.fromisoformat(v["published"].replace("Z", "+00:00"))
            if pub.year != ONLY_YEAR:
                continue
            if pub >= cutoff:
                v["pub"] = pub; v["area"] = ch["area"]
                cands.append(v)
                skip.add(v["video_id"])  # guard against the same id across two channels in one run
    # Fail LOUD on a total outage: queued==0 is normal (no new uploads), but every channel failing to
    # fetch is a YouTube/proxy outage and must exit non-zero so the green checkmark can't hide it.
    if ok == 0 and failed:
        sys.exit(f"[discover_recent] ABORT: all {failed} channels failed RSS -- YouTube/proxy outage, nothing fetched")
    print(f"[discover_recent] fetched {ok} channels ok, {failed} failed")
    cands.sort(key=lambda x: x["pub"], reverse=True)
    rows = [{"video_id": v["video_id"], "title": v["title"], "source": "channel_recent",
             "found_via": v["channel"], "interest_area": v["area"], "seed_score": 1e9} for v in cands]
    if rows:
        client.table("discovery_queue").upsert(rows, on_conflict="video_id").execute()
        for v in cands:
            seen.add(v["video_id"])
        save_seen(seen)
    print(f"[discover_recent] queued {len(cands)} new videos posted in the last {hours}h")
    return len(cands)

# ---------------- transcript ----------------
def transcript(video_id, retries=2):
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api.proxies import WebshareProxyConfig
    api = (YouTubeTranscriptApi(proxy_config=WebshareProxyConfig(proxy_username=WS_USER, proxy_password=WS_PASS))
           if WS_USER else YouTubeTranscriptApi())
    last = None
    for _ in range(retries + 1):
        try:
            tr = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
            return " ".join(s.text for s in tr)[:18000]
        except Exception as e:
            last = e
    raise last

# ---------------- extraction (Haiku, structured output) ----------------
SYSTEM = (HERE.parent / "poc" / "EXTRACTION_PROMPT.md").read_text() if (HERE.parent / "poc" / "EXTRACTION_PROMPT.md").exists() else \
    "Extract non-obvious, tactical, educational nuggets (hook, context, payload). Reject motivational filler. Return JSON."

# Coby's living taste model is the curation brain — apply it when deciding what to keep/score.
_taste = HERE.parent / "TASTE.md"
if _taste.exists():
    SYSTEM += "\n\n---\n# COBY'S TASTE — apply this; drop what he dislikes, score what he likes high\n\n" + _taste.read_text()

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["interest_area", "worth_full_watch", "watch_reason", "gist", "cover_bullets", "nuggets"],
    "properties": {
        "interest_area": {"type": "string", "enum": ["ai", "build", "str", "other"]},
        "worth_full_watch": {"type": "boolean"},
        "watch_reason": {"type": ["string", "null"]},
        "gist": {"type": "string"},
        "cover_bullets": {"type": "array", "items": {"type": "string"}},
        "nuggets": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["hook", "context", "payload", "timestamp_hint", "topic_tags", "quality", "type", "actionability", "scope"],
            "properties": {
                "hook": {"type": "string"}, "context": {"type": ["string", "null"]},
                "payload": {"type": "string"}, "timestamp_hint": {"type": ["integer", "null"]},
                "topic_tags": {"type": "array", "items": {"type": "string"}},
                "quality": {"type": "integer"},
                "type": {"type": "string", "enum": ["tactic", "mental-model", "counterintuitive-fact", "framework", "example"]},
                "actionability": {"type": "integer"},
                "scope": {"type": "string", "enum": ["tactical", "macro", "mixed"]},
            }}},
    }}

# Default = Gemini 3.1 Flash-Lite: strong judgment, reliable capacity, ~$0.004/video (still ~3x
# cheaper than Haiku). Levers:
#   EXTRACT_MODEL=gemini-2.5-flash-lite   -> cheapest (~$0.0012/video) WHEN not capacity-throttled
#   EXTRACT_MODEL=claude-haiku-4-5         -> back to Anthropic
#   EXTRACT_MODEL=claude-sonnet-4-6        -> Anthropic, top quality
# A "gemini*" model routes to Google (needs GEMINI_API_KEY); anything else routes to Anthropic.
EXTRACT_MODEL = os.environ.get("EXTRACT_MODEL", "gemini-3.1-flash-lite")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
USER_MSG = "TITLE: {t}\nCHANNEL: {c}\nTRANSCRIPT:\n{x}"

def _gemini_schema(s):
    """Convert our strict JSON-Schema to Gemini's responseSchema dialect: drop additionalProperties,
    and rewrite {"type":["string","null"]} as {"type":"string","nullable":true}."""
    if isinstance(s, dict):
        out = {}
        for k, v in s.items():
            if k == "additionalProperties":
                continue
            if k == "type" and isinstance(v, list):
                out["type"] = next(t for t in v if t != "null")
                if "null" in v:
                    out["nullable"] = True
            else:
                out[k] = _gemini_schema(v)
        return out
    if isinstance(s, list):
        return [_gemini_schema(x) for x in s]
    return s

GEMINI_SCHEMA = _gemini_schema(SCHEMA)

def extract(title, channel, text):
    if EXTRACT_MODEL.startswith("gemini"):
        return _extract_gemini(title, channel, text)
    return _extract_anthropic(title, channel, text)

def _extract_anthropic(title, channel, text):
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model=EXTRACT_MODEL, max_tokens=8000,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": USER_MSG.format(t=title, c=channel, x=text)}],
    )
    return json.loads(next(b.text for b in msg.content if b.type == "text"))

def _extract_gemini(title, channel, text):
    import requests
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{EXTRACT_MODEL}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": USER_MSG.format(t=title, c=channel, x=text)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": GEMINI_SCHEMA,
            "maxOutputTokens": 8192,
            "temperature": 0.4,
        },
    }
    # Flash-Lite gets transient 503 "high demand" / 429 spikes; retry with backoff.
    last = ""
    for attempt in range(6):
        r = requests.post(url, params={"key": GEMINI_KEY}, json=body, timeout=120)
        if r.status_code == 200:
            cand = r.json()["candidates"][0]
            txt = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
            if not txt:
                raise RuntimeError(f"gemini empty (finishReason={cand.get('finishReason')})")
            return json.loads(txt)
        last = f"{r.status_code}: {r.text[:140]}"
        if r.status_code in (429, 500, 503):
            time.sleep(2 * (attempt + 1) ** 2)  # 2, 8, 18, 32, 50s
            continue
        break
    raise RuntimeError(f"gemini failed after retries -> {last}")

# ---------------- write ----------------
def write_video(client, q, data):
    vid = q["video_id"]
    nuggets = [n for n in data["nuggets"] if n.get("quality", 0) >= 5]
    if len(nuggets) < 3:
        client.table("discovery_queue").update({"status": "low_yield"}).eq("video_id", vid).execute()
        return 0
    # The channel's curated vertical is AUTHORITATIVE for the feed filter (we hand-sorted every
    # channel into ai/build/str). Gemini's per-video guess is only a fallback for un-tagged sources.
    area = q.get("interest_area") or data.get("interest_area") or "other"
    # Set channel_id (and ensure the channels row exists, to satisfy the FK) so per-channel
    # ranking boosts in taste_weights actually apply to this and all future uploads.
    cid = CHANNEL_ID_BY_NAME.get(q.get("found_via"))
    if cid:
        client.table("channels").upsert({"channel_id": cid, "name": q.get("found_via")}, on_conflict="channel_id").execute()
    client.table("videos").upsert({
        "video_id": vid, "title": q["title"], "channel_name": q.get("found_via"), "channel_id": cid,
        "url": f"https://www.youtube.com/watch?v={vid}",
        "thumbnail_url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        "duration_s": q.get("duration_s"), "views_at_fetch": q.get("raw_views"),
        "published_at": published_date(vid),
        "interest_area": area, "worth_full_watch": data.get("worth_full_watch", False),
        "watch_reason": data.get("watch_reason"),
        "gist": data.get("gist"), "cover_bullets": data.get("cover_bullets"),
        "nugget_count": len(nuggets),
    }, on_conflict="video_id").execute()
    client.table("nuggets").insert([{
        "video_id": vid, "hook": n["hook"], "context": n.get("context"), "payload": n["payload"],
        "timestamp_hint": n.get("timestamp_hint"), "order_in_video": i, "interest_area": area,
        "topic_tags": n.get("topic_tags", []), "nugget_type": n.get("type"), "quality": n.get("quality", 5),
        "actionability": n.get("actionability"), "scope": n.get("scope"),
        "dedup_hash": hashlib.md5(re.sub(r"\W+", " ", n["payload"].lower()).encode()).hexdigest()[:16],
    } for i, n in enumerate(nuggets)]).execute()
    client.table("discovery_queue").update({"status": "extracted"}).eq("video_id", vid).execute()
    return len(nuggets)


def embed_new(anon_key=None):
    """Generate embeddings for any nuggets missing them (server-side gte-small edge function).
    Safe to call repeatedly; processes a small batch per call. Look-alike suppression depends on this."""
    import requests
    key = anon_key or os.environ.get("SUPABASE_ANON_KEY") or SUPABASE_KEY  # service key is a valid bearer
    if not (SUPABASE_URL and key):
        return
    url = f"{SUPABASE_URL}/functions/v1/embed-nuggets"
    for _ in range(50):
        try:
            r = requests.post(url, headers={"Authorization": f"Bearer {key}"}, timeout=60)
            if r.json().get("remaining", 0) == 0:
                break
        except Exception:
            break

def taste_digest():
    """Print Coby's free-write NOTES (the primary feedback signal) joined to the nugget they're on,
    so the daily routine can refine TASTE.md's 'Learned specifics' and re-tune the feed. The notes
    are the evidence; TASTE.md is the working knowledge that governs extraction."""
    client = sb()
    fb = client.table("feedback").select("note_text,nugget_id,video_id,created_at") \
        .eq("action", "note").order("created_at", desc=True).limit(200).execute().data
    ids = [f["nugget_id"] for f in fb if f.get("nugget_id")]
    nugs = {}
    if ids:
        nugs = {n["id"]: n for n in client.table("nuggets")
                .select("id,hook,scope,actionability,interest_area,topic_tags").in_("id", ids).execute().data}
    print("# Coby's free-write notes — refine TASTE.md 'Learned specifics' from the patterns below.\n"
          "# Then optionally re-score: nudge taste_weights and/or re-grade nuggets that violate the new taste.\n")
    for f in fb:
        n = nugs.get(f.get("nugget_id"), {})
        on = f"on nugget: \"{n.get('hook','?')}\" ({n.get('interest_area','?')}, scope={n.get('scope')}, act={n.get('actionability')})" \
            if f.get("nugget_id") else f"on video: {f.get('video_id')}"
        print(f"- NOTE: \"{(f.get('note_text') or '').strip()}\"\n  {on}")
    if not fb:
        print("(no notes yet)")

def learn():
    """THE feedback loop. Read Coby's un-digested free-write notes, distill them into durable
    'Learned specifics' bullets in TASTE.md (which the extractor reads on every run), mark the notes
    learned, and report whether TASTE.md changed. Run daily; costs nothing when there are no new
    notes. This is what makes future videos' nuggets reflect Coby's stated taste."""
    import requests
    from datetime import datetime, timezone
    client = sb()
    notes = client.table("feedback").select("id,note_text,nugget_id,video_id") \
        .eq("action", "note").is_("learned_at", "null").execute().data
    notes = [n for n in notes if (n.get("note_text") or "").strip()]
    if not notes:
        print("[learn] no new notes — TASTE.md unchanged"); return
    ids = [n["nugget_id"] for n in notes if n.get("nugget_id")]
    hooks = {}
    if ids:
        hooks = {r["id"]: r["hook"] for r in client.table("nuggets").select("id,hook").in_("id", ids).execute().data}
    lines = [f'- "{n["note_text"].strip()}"  (on: {hooks.get(n.get("nugget_id"), n.get("video_id","a video"))})' for n in notes]
    taste_path = HERE.parent / "TASTE.md"
    current = taste_path.read_text()
    existing_learned = current.split("## Learned specifics")[-1][:1800]
    prompt = (
        "Coby leaves free-write notes on nuggets in his personal learning feed. Distill his NEW notes "
        "into 1-3 concise, DURABLE bullets for the 'Learned specifics' section of his taste file, so the "
        "extractor pulls better nuggets for FUTURE videos. Capture the generalizable preference (what to "
        "pull back on or lean into), not the single nugget. Read each note for its underlying reason. "
        "NO em dashes. Output ONLY the bullet line(s), each starting with '- ', nothing else. If the notes "
        "contain no generalizable signal, output the single word NONE.\n\n"
        "NEW NOTES:\n" + "\n".join(lines) +
        "\n\nExisting learned bullets (do NOT duplicate these):\n" + existing_learned
    )
    model = "gemini-3.1-flash-lite"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    r = requests.post(url, params={"key": GEMINI_KEY},
                      json={"contents": [{"parts": [{"text": prompt}]}],
                            "generationConfig": {"maxOutputTokens": 700, "temperature": 0.3}}, timeout=90)
    out = ""
    if r.status_code == 200:
        out = "".join(p.get("text", "") for p in r.json()["candidates"][0].get("content", {}).get("parts", [])).strip()
    bullets = "\n".join(l for l in out.splitlines() if l.strip().startswith("- "))
    now = datetime.now(timezone.utc)
    if bullets and out.strip().upper() != "NONE":
        stamp = now.date().isoformat()
        taste_path.write_text(current.rstrip() + f"\n- {stamp} (from notes):\n" + bullets + "\n")
        print(f"[learn] appended {len(bullets.splitlines())} bullet(s) to TASTE.md from {len(notes)} note(s)")
    else:
        print(f"[learn] {len(notes)} note(s) had no generalizable signal; TASTE.md unchanged")
    for n in notes:
        client.table("feedback").update({"learned_at": now.isoformat()}).eq("id", n["id"]).execute()

def _process_pending(client, limit):
    pending = client.table("discovery_queue").select("*").eq("status", "pending") \
        .order("seed_score", desc=True).limit(limit).execute().data
    need_key = GEMINI_KEY if EXTRACT_MODEL.startswith("gemini") else ANTHROPIC_KEY
    if not need_key:
        print(f"[run] {len(pending)} pending. Missing API key for EXTRACT_MODEL={EXTRACT_MODEL} -> extraction skipped.")
        return 0
    print(f"[run] extracting with {EXTRACT_MODEL}")
    total = 0
    print(f"[run] processing {len(pending)} pending: " + ", ".join(f"{q['video_id']}({q.get('found_via','?')})" for q in pending))
    def work(q):
        nonlocal total
        try:
            txt = transcript(q["video_id"])
        except Exception as e:
            print(f"  [transcript] {q['video_id']} FAILED: {type(e).__name__}: {str(e)[:120]}")
            client.table("discovery_queue").update({"status": "no_captions"}).eq("video_id", q["video_id"]).execute()
            return
        try:
            data = extract(q["title"], q.get("found_via", ""), txt)
            n = write_video(client, q, data)
            total += n
            print(f"  [ok] {q['video_id']} ({q.get('found_via','?')}): {n} nuggets")
        except Exception as e:
            print(f"  ! {q['video_id']}: {type(e).__name__}: {str(e)[:120]}")
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(work, pending))
    print(f"[run] extracted ~{total} nuggets from {len(pending)} videos")
    embed_new()  # backfill embeddings for the new nuggets (powers look-alike suppression)
    print("[run] embeddings backfilled")
    return total

def run(limit):
    discover()
    _process_pending(sb(), limit)

def run_recent(hours=24, max_extract=200):
    """Daily path: queue EVERY new monitored-channel upload from the strict last-`hours` window, then
    extract them. No 48h widen (the window is exactly what was asked for) and no per-run cap on
    discovery, so each run picks up precisely the videos posted since the previous run. `max_extract`
    is only a runaway-cost backstop on how many pending videos one run will transcribe + extract."""
    discover_recent(hours)
    _process_pending(sb(), max_extract)

def list_recent(limit=5, hours=24):
    """Print the newest AI-channel uploads as JSON. No Supabase / no API key — used by the $0 Max
    routine to get the day's videos, which it then transcribes + extracts itself."""
    from datetime import datetime, timezone, timedelta
    def pick(hrs):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hrs)
        out = []
        for ch in monitored_channels():
            try:
                for v in channel_recent(ch["channel_id"], ch["name"]):
                    pub = datetime.fromisoformat(v["published"].replace("Z", "+00:00"))
                    if pub.year == ONLY_YEAR and pub >= cutoff:
                        out.append({**v, "pub": pub, "area": ch["area"]})
            except Exception:
                continue
        out.sort(key=lambda x: x["pub"], reverse=True)
        return out
    cands = pick(hours)
    if len(cands) < limit:
        cands = pick(48)  # widen if a strict window is thin
    picked = [{"video_id": v["video_id"], "title": v["title"], "channel": v["channel"],
               "published": v["published"]} for v in cands[:limit]]
    print(json.dumps(picked, indent=2))
    return picked

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["discover", "run", "recent", "list-recent", "embed", "taste", "learn"])
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--hours", type=int, default=24)
    a = ap.parse_args()
    if a.cmd == "discover": discover()
    elif a.cmd == "recent": run_recent(a.hours, a.limit)
    elif a.cmd == "list-recent": list_recent(a.limit, a.hours)
    elif a.cmd == "embed": embed_new()
    elif a.cmd == "taste": taste_digest()
    elif a.cmd == "learn": learn()
    else: run(a.limit)
