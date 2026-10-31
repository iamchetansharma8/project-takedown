"""
Pull YouTube results for one person into a file.

This is plumbing. It is deliberately dumb: one script, run by hand, writes
a file to disk. No pipeline, no database, no scheduling.

Usage:
    export YOUTUBE_API_KEY=...
    python collect.py subjects/example.json

Writes: data/<subject_id>_items.jsonl
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://www.googleapis.com/youtube/v3/"
KEY = os.environ.get("YOUTUBE_API_KEY", "")

# YouTube gives 10,000 free quota units a day. A search costs 100 units, so
# roughly 100 searches, each returning up to 50 videos. Plenty for this.
MAX_PAGES_PER_TERM = 3


def call(endpoint, params):
    params["key"] = KEY
    url = API + endpoint + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode())


def parse_duration(iso):
    """YouTube returns ISO 8601 like PT2H39M12S. Give back whole minutes.

    Worth having for its own sake: a video claiming to be a 159-minute film
    that runs 96 minutes is not that film, whatever its title says.
    """
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(g) if g else 0 for g in m.groups())
    return round(h * 60 + mi + s / 60)


def search(term, published_after, published_before):
    """Return video IDs for one search term."""
    ids, token, pages = [], None, 0
    while pages < MAX_PAGES_PER_TERM:
        params = {
            "part": "id",
            "q": term,
            "type": "video",
            "maxResults": 50,
            "order": "relevance",
            "publishedAfter": published_after,
            "publishedBefore": published_before,
        }
        if token:
            params["pageToken"] = token
        try:
            data = call("search", params)
        except Exception as e:
            print(f"  search failed for '{term}': {e}")
            break
        ids += [i["id"]["videoId"] for i in data.get("items", []) if i.get("id", {}).get("videoId")]
        token = data.get("nextPageToken")
        pages += 1
        if not token:
            break
        time.sleep(0.2)
    return ids


def details(video_ids):
    """Fetch stats for videos, 50 at a time."""
    out = []
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i + 50]
        try:
            data = call("videos", {
                # contentDetails carries licensedContent - YouTube's own flag
                # for "this is claimed by a rights partner", which is a strong
                # hint the upload is authorised rather than rogue.
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(chunk),
            })
        except Exception as e:
            print(f"  details failed: {e}")
            continue
        for v in data.get("items", []):
            snip = v.get("snippet", {})
            stats = v.get("statistics", {})
            published = snip.get("publishedAt", "")
            try:
                pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                age_hours = (datetime.now(timezone.utc) - pub_dt).total_seconds() / 3600
                date_str = pub_dt.strftime("%Y-%m-%d")
            except Exception:
                age_hours, date_str = 1, ""
            out.append({
                "id": v.get("id"),
                "url": f"https://www.youtube.com/watch?v={v.get('id')}",
                "platform": "youtube",
                "title": snip.get("title", ""),
                # 1000 was too short and cost us twice. Disclaimers like
                # "no copyright infringement intended" and any outbound links
                # sit at the BOTTOM of a description, past the hashtags and
                # credits - so the two things we most wanted to read were the
                # two things being cut off. 17 of 50 items hit the old cap.
                "description": (snip.get("description", "") or "")[:5000],
                "channel_title": snip.get("channelTitle", ""),
                "channel_id": snip.get("channelId", ""),
                "thumbnail": snip.get("thumbnails", {}).get("default", {}).get("url", ""),
                "published": published,
                "date": date_str,
                "age_hours": round(age_hours, 1),
                "views": int(stats.get("viewCount", 0) or 0),
                "likes": int(stats.get("likeCount", 0) or 0),
                "comments": int(stats.get("commentCount", 0) or 0),
                "licensed_content": bool(
                    v.get("contentDetails", {}).get("licensedContent", False)),
                "duration_min": parse_duration(
                    v.get("contentDetails", {}).get("duration", "")),
            })
        time.sleep(0.2)
    return out


def main():
    if not KEY:
        sys.exit("Set YOUTUBE_API_KEY first. Get a free key at console.cloud.google.com")
    if len(sys.argv) < 2:
        sys.exit("Usage: python collect.py subjects/<file>.json")

    subject = json.load(open(sys.argv[1]))
    days = subject.get("lookback_days", 30)
    after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    before = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    all_ids = []
    for term in subject["search_terms"]:
        print(f"searching: {term}")
        found = search(term, after, before)
        print(f"  {len(found)} videos")
        all_ids += found

    unique = list(dict.fromkeys(all_ids))
    print(f"\n{len(unique)} unique videos. Fetching details...")
    items = details(unique)

    os.makedirs("data", exist_ok=True)
    out = f"data/{subject['id']}_items.jsonl"
    with open(out, "w") as f:
        for item in items:
            f.write(json.dumps(item) + "\n")

    print(f"wrote {len(items)} items to {out}")
    print(f"\nNext:  python judge.py {sys.argv[1]}")


if __name__ == "__main__":
    main()
