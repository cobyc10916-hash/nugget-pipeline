#!/usr/bin/env python3
"""
NUGGET — Phase 0 proof-of-concept discovery + transcript pull.

Pulls a representative spread of real videos across the three buckets
(AI / building / STR) PLUS one long podcast, fetches their transcripts via the
proven Webshare rotating proxy, and writes each to nugget/poc/transcripts/<id>.json
for the operator to see real nuggets extracted from real sources.

Reuses the proven patterns from breakout_scan.py (yt-dlp search + proxy) and
morning-brief/fetch/youtube.py (youtube-transcript-api + WebshareProxyConfig).

Run:  .venv/bin/python nugget/poc/discover_poc.py
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TRANSCRIPTS = HERE / "transcripts"
TRANSCRIPTS.mkdir(exist_ok=True)

# ---- proxy (same infra as breakout_scan.py / morning-brief) ----
def load_proxy():
    creds = {}
    env_path = REPO / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.strip().partition("=")
                creds[k] = v.strip().strip('"').strip("'")
    u, p = creds.get("WEBSHARE_PROXY_USERNAME"), creds.get("WEBSHARE_PROXY_PASSWORD")
    return (u, p, f"http://{u}-rotate:{p}@p.webshare.io:80") if u and p else (None, None, None)

WS_USER, WS_PASS, PROXY = load_proxy()

# Buckets → search queries (relevance search, best content regardless of date).
# Each tuple: (bucket, query, min_dur_s, max_dur_s, want_n)
PLAN = [
    ("ai",    "claude code agentic workflow tips",      400, 4000, 2),
    ("ai",    "building ai agents tutorial",            400, 4000, 1),
    ("build", "one person business how to",             400, 4000, 1),
    ("build", "bootstrapped saas first customers",      400, 4000, 1),
    ("str",   "short term rental market analysis",      400, 4000, 1),
    ("str",   "airbnb pricing strategy revenue",        400, 4000, 1),
    ("podcast","my first million AI business ideas",   2400, 9000, 1),  # the long one
]
MIN_VIEWS = 15_000


def ytdlp(args, timeout=180):
    cmd = ["yt-dlp", "--no-warnings"]
    if PROXY:
        cmd += ["--proxy", PROXY]
    r = subprocess.run(cmd + list(args), capture_output=True, text=True, timeout=timeout)
    return r.stdout


def search(query, min_dur, max_dur, _retry=True):
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    out = ytdlp(["--flat-playlist", "-J", "--playlist-end", "20", url])
    if not out.strip():
        if _retry:
            time.sleep(12)
            return search(query, min_dur, max_dur, _retry=False)
        return []
    try:
        data = json.loads(out)
    except Exception:
        return []
    hits = []
    for e in data.get("entries") or []:
        if not e or e.get("ie_key") != "Youtube":
            continue
        vc, dur = e.get("view_count"), e.get("duration")
        if not vc or not dur:
            continue
        if vc >= MIN_VIEWS and min_dur <= dur <= max_dur:
            hits.append({
                "video_id": e.get("id"), "title": e.get("title"),
                "channel": e.get("channel") or e.get("uploader"),
                "channel_id": e.get("channel_id"), "views": vc, "duration": dur,
            })
    return hits


def fetch_transcript(video_id, retries=2):
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api.proxies import WebshareProxyConfig
    api = (YouTubeTranscriptApi(proxy_config=WebshareProxyConfig(
                proxy_username=WS_USER, proxy_password=WS_PASS))
           if WS_USER else YouTubeTranscriptApi())
    last = None
    for _ in range(retries + 1):
        try:
            tr = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
            # keep timestamps so we can deep-link nuggets
            return [{"t": round(s.start), "text": s.text} for s in tr]
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def main():
    print(f"proxy: {'on' if PROXY else 'OFF'}\n")
    selected = []
    seen = set()
    for bucket, query, min_dur, max_dur, want_n in PLAN:
        print(f"[search:{bucket}] {query!r}")
        hits = sorted(search(query, min_dur, max_dur), key=lambda h: h["views"], reverse=True)
        taken = 0
        for h in hits:
            if h["video_id"] in seen:
                continue
            seen.add(h["video_id"])
            h["bucket"] = bucket
            selected.append(h)
            taken += 1
            mins = h["duration"] // 60
            print(f"    + {h['title'][:55]:55} | {mins}m | {h['views']:,} views")
            if taken >= want_n:
                break
        time.sleep(3)

    print(f"\nSelected {len(selected)} videos. Fetching transcripts...\n")
    ok, fail = [], []
    for h in selected:
        vid = h["video_id"]
        try:
            segs = fetch_transcript(vid)
            full = " ".join(s["text"] for s in segs)
            rec = {**h, "transcript_segments": segs, "transcript_chars": len(full)}
            (TRANSCRIPTS / f"{vid}.json").write_text(json.dumps(rec, indent=2))
            ok.append(h)
            print(f"   ✓ [{h['bucket']}] {h['title'][:50]:50} ({len(full):,} chars)")
        except Exception as e:  # noqa: BLE001
            fail.append((h, str(e)[:80]))
            print(f"   ✗ [{h['bucket']}] {h['title'][:50]:50} — {str(e)[:50]}")
        time.sleep(1)

    (HERE / "selected.json").write_text(json.dumps(
        {"ok": ok, "failed": [{"video": h, "error": e} for h, e in fail]}, indent=2))
    print(f"\nDone. {len(ok)} transcripts in {TRANSCRIPTS}/  |  {len(fail)} failed.")
    print("Buckets:", {b: sum(1 for h in ok if h['bucket'] == b)
                       for b in {h['bucket'] for h in ok}})


if __name__ == "__main__":
    main()
