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
    r = requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}", timeout=20)
    ids = re.findall(r"<yt:videoId>([^<]+)</yt:videoId>", r.text)[:max_n]
    titles = re.findall(r"<media:title>([^<]+)</media:title>", r.text)[:max_n]
    return [{"video_id": v, "title": t, "channel_id": channel_id} for v, t in zip(ids, titles)]

def channel_recent(channel_id, name):
    """Newest uploads from a channel via its RSS feed (with published timestamps). No proxy needed."""
    import requests
    r = requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}", timeout=20)
    out = []
    for e in re.findall(r"<entry>(.*?)</entry>", r.text, re.S):
        vid = re.search(r"<yt:videoId>([^<]+)</yt:videoId>", e)
        title = re.search(r"<media:title>([^<]+)</media:title>", e)
        pub = re.search(r"<published>([^<]+)</published>", e)
        if vid and pub:
            out.append({"video_id": vid.group(1), "title": title.group(1) if title else "",
                        "channel": name, "published": pub.group(1)})
    return out

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

def discover_recent(hours=24, limit=5):
    """Pull the newest uploads from the reputable AI channels (interests.json -> ai_channels)
    published within the last `hours`, dedupe, take the `limit` most recent, queue them."""
    from datetime import datetime, timezone, timedelta
    client = sb()
    seen = load_seen()
    existing = {r["video_id"] for r in client.table("videos").select("video_id").execute().data}
    queued = {r["video_id"] for r in client.table("discovery_queue").select("video_id").execute().data}
    skip = seen | existing | queued
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    cands = []
    for ch in CORPUS.get("ai_channels", []):
        try:
            for v in channel_recent(ch["channel_id"], ch["name"]):
                if v["video_id"] in skip:
                    continue
                pub = datetime.fromisoformat(v["published"].replace("Z", "+00:00"))
                if pub >= cutoff:
                    v["pub"] = pub
                    cands.append(v)
        except Exception:
            continue
    cands.sort(key=lambda x: x["pub"], reverse=True)
    picked = cands[:limit]
    rows = [{"video_id": v["video_id"], "title": v["title"], "source": "ai_channel_recent",
             "found_via": v["channel"], "interest_area": "ai", "seed_score": 1e9} for v in picked]
    if rows:
        client.table("discovery_queue").upsert(rows, on_conflict="video_id").execute()
        for v in picked:
            seen.add(v["video_id"])
        save_seen(seen)
    print(f"[discover_recent] queued {len(picked)} of {len(cands)} candidates from last {hours}h")
    return len(picked)

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

def extract(title, channel, text):
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model="claude-haiku-4-5", max_tokens=4000,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": f"TITLE: {title}\nCHANNEL: {channel}\nTRANSCRIPT:\n{text}"}],
    )
    return json.loads(next(b.text for b in msg.content if b.type == "text"))

# ---------------- write ----------------
def write_video(client, q, data):
    vid = q["video_id"]
    nuggets = [n for n in data["nuggets"] if n.get("quality", 0) >= 5]
    if len(nuggets) < 3:
        client.table("discovery_queue").update({"status": "low_yield"}).eq("video_id", vid).execute()
        return 0
    area = data.get("interest_area") or q.get("interest_area") or "other"
    client.table("videos").upsert({
        "video_id": vid, "title": q["title"], "url": f"https://www.youtube.com/watch?v={vid}",
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
    key = anon_key or os.environ.get("SUPABASE_ANON_KEY")
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

def _process_pending(client, limit):
    pending = client.table("discovery_queue").select("*").eq("status", "pending") \
        .order("seed_score", desc=True).limit(limit).execute().data
    if not ANTHROPIC_KEY:
        print(f"[run] {len(pending)} pending. No ANTHROPIC_API_KEY -> extraction skipped "
              f"(run extraction via the Max routine in PROMPT.md instead).")
        return 0
    total = 0
    def work(q):
        nonlocal total
        try:
            txt = transcript(q["video_id"])
        except Exception:
            client.table("discovery_queue").update({"status": "no_captions"}).eq("video_id", q["video_id"]).execute()
            return
        try:
            data = extract(q["title"], q.get("found_via", ""), txt)
            total += write_video(client, q, data)
        except Exception as e:
            print(f"  ! {q['video_id']}: {str(e)[:80]}")
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(work, pending))
    print(f"[run] extracted ~{total} nuggets from {len(pending)} videos")
    embed_new()  # backfill embeddings for the new nuggets (powers look-alike suppression)
    print("[run] embeddings backfilled")
    return total

def run(limit):
    discover()
    _process_pending(sb(), limit)

def run_recent(limit=5, hours=24):
    """PoC / daily path: newest uploads from reputable AI channels, last `hours`, extract top `limit`."""
    n = discover_recent(hours, limit)
    if n < limit:
        discover_recent(48, limit)  # widen if a strict 24h window is thin
    _process_pending(sb(), limit)

def list_recent(limit=5, hours=24):
    """Print the newest AI-channel uploads as JSON. No Supabase / no API key — used by the $0 Max
    routine to get the day's videos, which it then transcribes + extracts itself."""
    from datetime import datetime, timezone, timedelta
    def pick(hrs):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hrs)
        out = []
        for ch in CORPUS.get("ai_channels", []):
            try:
                for v in channel_recent(ch["channel_id"], ch["name"]):
                    pub = datetime.fromisoformat(v["published"].replace("Z", "+00:00"))
                    if pub >= cutoff:
                        out.append({**v, "pub": pub})
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
    ap.add_argument("cmd", choices=["discover", "run", "recent", "list-recent", "embed", "taste"])
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--hours", type=int, default=24)
    a = ap.parse_args()
    if a.cmd == "discover": discover()
    elif a.cmd == "recent": run_recent(a.limit if a.limit != 20 else 5, a.hours)
    elif a.cmd == "list-recent": list_recent(a.limit if a.limit != 20 else 5, a.hours)
    elif a.cmd == "embed": embed_new()
    elif a.cmd == "taste": taste_digest()
    else: run(a.limit)
