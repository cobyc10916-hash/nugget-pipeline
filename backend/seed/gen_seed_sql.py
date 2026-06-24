#!/usr/bin/env python3
"""Generate escaped INSERT SQL from seed.json for the Supabase MCP to apply."""
import json, pathlib

HERE = pathlib.Path(__file__).resolve().parent
data = json.loads((HERE / "seed.json").read_text())

def q(s):
    if s is None:
        return "null"
    return "'" + str(s).replace("'", "''") + "'"

def arr(xs):
    if not xs:
        return "'{}'"
    inner = ",".join('"' + str(x).replace('"', '\\"') + '"' for x in xs)
    return "'{" + inner + "}'"

lines = []
chans = {}
for v in data["videos"]:
    chans[v["channel_id"]] = v["channel_name"]

lines.append("-- channels")
for cid, name in chans.items():
    lines.append(f"insert into channels (channel_id, name) values ({q(cid)}, {q(name)}) on conflict (channel_id) do nothing;")

lines.append("-- videos")
for v in data["videos"]:
    vid = v["video_id"]
    url = f"https://www.youtube.com/watch?v={vid}"
    thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
    nc = len(v["nuggets"])
    lines.append(
        "insert into videos (video_id, title, channel_id, channel_name, url, thumbnail_url, "
        "duration_s, interest_area, worth_full_watch, watch_reason, nugget_count) values ("
        f"{q(vid)}, {q(v['title'])}, {q(v['channel_id'])}, {q(v['channel_name'])}, {q(url)}, {q(thumb)}, "
        f"{v['duration_s']}, {q(v['interest_area'])}, {str(v['worth_full_watch']).lower()}, "
        f"{q(v.get('watch_reason'))}, {nc}) on conflict (video_id) do nothing;"
    )

lines.append("-- nuggets")
for v in data["videos"]:
    vid = v["video_id"]
    for i, n in enumerate(v["nuggets"]):
        lines.append(
            "insert into nuggets (video_id, channel_id, hook, context, payload, timestamp_hint, "
            "order_in_video, interest_area, topic_tags, nugget_type, quality) values ("
            f"{q(vid)}, {q(v['channel_id'])}, {q(n['hook'])}, {q(n.get('context'))}, {q(n['payload'])}, "
            f"{n.get('timestamp_hint') if n.get('timestamp_hint') is not None else 'null'}, {i}, "
            f"{q(v['interest_area'])}, {arr(n.get('topic_tags'))}, {q(n.get('nugget_type'))}, {n.get('quality',5)});"
        )

sql = "\n".join(lines)
(HERE / "seed.sql").write_text(sql)
n_nug = sum(len(v["nuggets"]) for v in data["videos"])
print(f"wrote seed.sql: {len(chans)} channels, {len(data['videos'])} videos, {n_nug} nuggets")
