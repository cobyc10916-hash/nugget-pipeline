#!/usr/bin/env python3
"""
Apify-backed adapters for the sources free methods can't reliably reach from CI:
  - Reddit full-text (post selftext + top comments) -> FEED mining (deep nuggets)
  - X/Twitter -> PULSE (the one source whose free syndication blocks datacenter IPs)

Used WISELY (cost scales with results): small curated source lists, hard item caps, dedup happens
upstream, and these run only on the crons that need depth. Parsing is intentionally defensive and
env-overridable (actor field names differ between actors/versions) so a schema drift degrades to
"fewer items", never a crash.

Env:
  APIFY_TOKEN            (required)
  APIFY_REDDIT_ACTOR    (default trudax~reddit-scraper-lite)
  APIFY_X_ACTOR         (default apidojo~tweet-scraper)
"""
from __future__ import annotations
import json, os, time, urllib.request, urllib.error

APIFY_TOKEN = os.environ.get("APIFY_TOKEN")
REDDIT_ACTOR = os.environ.get("APIFY_REDDIT_ACTOR", "trudax~reddit-scraper-lite")
X_ACTOR = os.environ.get("APIFY_X_ACTOR", "apidojo~tweet-scraper")

class ApifyError(Exception):
    pass

def _http(url: str, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        raise ApifyError(f"HTTP {e.code}: {body}")
    except Exception as e:
        raise ApifyError(f"{type(e).__name__}: {str(e)[:160]}")

def _run(actor: str, inp: dict, run_timeout: int = 420, wall: int = 480, poll: int = 6) -> list:
    """Start an actor run async, poll to completion, return its dataset items. Avoids the run-sync
    HTTP cap that kills longer multi-source scrapes, and tolerates a partial / TIMED-OUT run by
    returning whatever items the dataset already holds (recall over abort)."""
    if not APIFY_TOKEN:
        raise ApifyError("APIFY_TOKEN not set")
    start = _http(f"https://api.apify.com/v2/acts/{actor}/runs?token={APIFY_TOKEN}&timeout={run_timeout}", inp)
    d = (start or {}).get("data") or {}
    run_id, ds, status = d.get("id"), d.get("defaultDatasetId"), d.get("status")
    if not run_id:
        raise ApifyError(f"no run id: {str(start)[:160]}")
    waited = 0
    while status in (None, "READY", "RUNNING") and waited < wall:
        time.sleep(poll); waited += poll
        d = (_http(f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_TOKEN}") or {}).get("data") or {}
        status, ds = d.get("status"), (d.get("defaultDatasetId") or ds)
    if not ds:
        raise ApifyError(f"no dataset (status={status})")
    items = _http(f"https://api.apify.com/v2/datasets/{ds}/items?token={APIFY_TOKEN}&clean=true")
    if not isinstance(items, list):
        raise ApifyError(f"dataset not a list (status={status})")
    if not items and status != "SUCCEEDED":
        raise ApifyError(f"run {status}, no items")
    return items  # partial items from a TIMED-OUT run are acceptable

def _g(d: dict, *keys, default=None):
    """First non-empty value among keys (actors name fields inconsistently)."""
    if not isinstance(d, dict):
        return default
    for k in keys:
        v = d.get(k)
        if v not in (None, "", []):
            return v
    return default

# ---------------- Reddit: posts + top comments -> feed-mining text ----------------
def reddit_posts(subreddits, per_sub=4, max_comments=6, sort="top", t="day") -> list[dict]:
    start = [{"url": f"https://www.reddit.com/r/{s}/{sort}/?t={t}"} for s in subreddits]
    inp = {
        "startUrls": start,
        "skipComments": False, "skipUserPosts": True, "skipCommunity": True,
        "searchPosts": True, "searchComments": False, "searchCommunities": False, "searchUsers": False,
        "sort": sort, "includeNSFW": False,
        "maxItems": per_sub * len(subreddits) * (max_comments + 1) + 10,
        "maxPostCount": per_sub, "maxComments": max_comments,
        "maxCommunitiesCount": 0, "maxUserCount": 0,
        "proxy": {"useApifyProxy": True},
    }
    items = _run(REDDIT_ACTOR, inp)
    posts, comments = {}, {}
    for it in items:
        dt = (_g(it, "dataType", "type", default="") or "").lower()
        is_comment = dt == "comment" or (_g(it, "body", "comment") and not _g(it, "title"))
        if is_comment:
            pid = _g(it, "postId", "parentId", "postUrl", "url")
            comments.setdefault(pid, []).append(it)
        else:
            url = _g(it, "url", "link", "postUrl")
            if url:
                posts[url] = it
    out = []
    for url, p in posts.items():
        title = _g(p, "title", default="")
        body = _g(p, "body", "selftext", "text", "content", default="") or ""
        sub = (_g(p, "communityName", "parsedCommunityName", "subreddit", default="") or "").replace("r/", "").strip()
        score = _g(p, "upVotes", "score", "numberOfVotes")
        created = _g(p, "createdAt", "created", "date", "parsedCreatedAt")
        cs = comments.get(url) or comments.get(_g(p, "id", "postId")) or []
        ctxt = "\n".join("- " + (_g(c, "body", "comment", "text", default="") or "")[:600] for c in cs[:max_comments])
        text = (title + "\n\n" + body + (("\n\nTOP COMMENTS:\n" + ctxt) if ctxt else "")).strip()
        if not title or len(text) < 120:   # skip empty / link-only posts (nothing to mine)
            continue
        out.append({"title": title, "url": url, "subreddit": sub, "score": score,
                    "created": created, "text": text[:18000]})
    return out

# ---------------- X/Twitter -> pulse items ----------------
def x_tweets(handles, per=3, max_items=30) -> list[dict]:
    inp = {"twitterHandles": list(handles), "maxItems": min(max_items, per * len(handles) + 5),
           "sort": "Latest", "tweetLanguage": "en"}
    items = _run(X_ACTOR, inp)
    out = []
    for it in items:
        txt = _g(it, "text", "full_text", "content")
        if not txt:
            continue
        author = ""
        auth = it.get("author")
        if isinstance(auth, dict):
            author = _g(auth, "userName", "screen_name", "username", default="")
        author = author or _g(it, "username", "userName", "authorUsername", default="")
        url = _g(it, "url", "twitterUrl", "tweetUrl")
        likes = _g(it, "likeCount", "favoriteCount", "likes")
        created = _g(it, "createdAt", "created_at", "date")
        head = (txt.replace("\n", " "))[:180]
        out.append({
            "title": (f"@{author}: {head}" if author else head),
            "link": url, "date": created or "",
            "summary": (f"{likes} likes" if isinstance(likes, int) else ""),
            "velocity": likes if isinstance(likes, int) else None,
            "source": (f"X: @{author}" if author else "X/Twitter"),
            "source_key": f"x_{(author or 'x').lower()}", "category": "social",
        })
    return out
