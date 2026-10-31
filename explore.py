"""
Look at what a search actually returns, before building anything around it.

No scoring, no files, no subject config. Type some search terms, see what comes
back. Use this to find real examples first and design the search from those,
rather than guessing at terms and discovering afterwards that the content was
never there.

That mistake has been made three times on this project already.

Usage:
    export YOUTUBE_API_KEY=...
    python3 explore.py "AI ad Amitabh Bachchan" "AI brand ambassador"
    python3 explore.py --days 90 "Shah Rukh Khan jewellery ai"

Options:
    --days N     how far back to look (default 180)
    --sort date  newest first instead of most relevant
    --limit N    results per term (default 25)
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://www.googleapis.com/youtube/v3/"
KEY = os.environ.get("YOUTUBE_API_KEY", "")


def call(endpoint, params):
    params["key"] = KEY
    url = API + endpoint + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode())


def explore(term, days, order, limit):
    after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        found = call("search", {
            "part": "id", "q": term, "type": "video",
            "maxResults": min(limit, 50), "order": order,
            "publishedAfter": after,
        })
    except Exception as e:
        print(f"  search failed: {e}")
        return

    ids = [i["id"]["videoId"] for i in found.get("items", [])
           if i.get("id", {}).get("videoId")]
    if not ids:
        print("  nothing")
        return

    details = call("videos", {"part": "snippet,statistics", "id": ",".join(ids)})

    rows = []
    for v in details.get("items", []):
        s, st = v.get("snippet", {}), v.get("statistics", {})
        rows.append((
            int(st.get("viewCount", 0) or 0),
            s.get("channelTitle", "")[:26],
            (s.get("publishedAt", "") or "")[:10],
            s.get("title", "")[:70],
            v.get("id"),
        ))

    rows.sort(reverse=True)
    for views, channel, date, title, vid in rows:
        print(f"  {views:>9}  {date}  {channel:<26} {title}")
        print(f"             https://youtu.be/{vid}")


def main():
    if not KEY:
        sys.exit("Set YOUTUBE_API_KEY first.")

    args = sys.argv[1:]
    days, order, limit = 180, "relevance", 25

    while args and args[0].startswith("--"):
        flag = args.pop(0)
        if flag == "--days":
            days = int(args.pop(0))
        elif flag == "--sort":
            order = args.pop(0)
        elif flag == "--limit":
            limit = int(args.pop(0))
        else:
            sys.exit(f"unknown option {flag}")

    if not args:
        sys.exit('Give me some search terms:  python3 explore.py "term one" "term two"')

    for term in args:
        print(f"\n=== {term} ===")
        explore(term, days, order, limit)

    print(f"\n(each search costs 100 of your 10,000 daily quota units)")


if __name__ == "__main__":
    main()
