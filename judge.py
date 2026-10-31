"""
Group copies into problems, score them, write a spreadsheet.

Usage:
    python judge.py subjects/example.json

Writes:
    data/<id>_ranked.csv     everything, worst first    <- open this
    data/<id>_blindspot.csv  20 random ignored items    <- and this one
"""

import csv
import json
import os
import random
import re
import sys
from datetime import datetime, timedelta

import rules

# ---------------------------------------------------------------------------
# IS THIS EVEN ABOUT OUR PERSON
# ---------------------------------------------------------------------------
# The first real run collected 599 videos and 151 of them were about somebody
# else entirely - a Vijay Deverakonda film, a Sai Pallavi comparison, unrelated
# Bollywood gossip. YouTube ranks by loose relevance and we never checked.
#
# Everything downstream is wasted effort on those, and worse, they can score
# high and push real problems off the top of the list.


def is_about_subject(item, needles):
    """True if any of the subject's names appears in the title or description."""
    blob = ((item.get("title") or "") + " " +
            (item.get("description") or "")).lower()
    return any(n in blob for n in needles)


def subject_needles(subject):
    """What to look for. Falls back to the full name if no aliases given."""
    names = [subject["name"]] + subject.get("aliases", [])
    return [n.lower() for n in names if n]


# ---------------------------------------------------------------------------
# GROUPING COPIES INTO ONE PROBLEM
# ---------------------------------------------------------------------------
# The first version compared whole titles character by character and grouped
# 599 items into 498 problems - 1.2 copies each, so effectively nothing. It
# only looked like it worked on the fake data because that data had identical
# titles by construction.
#
# Real coverage of one incident carries completely different headlines:
#   "Mrunal Thakur Declares War on Deepfakes"
#   "Mrunal Thakur Issues Strong Warning Against Deepfakes"
# Almost no character overlap, obviously the same incident.
#
# So compare the SET of meaningful words instead of the character sequence.
# Crucially, the subject's own name is removed first - it appears in every
# single title, so leaving it in would group the entire dataset together.

SAME_PROBLEM = 0.34   # share of distinctive words that must overlap

STOPWORDS = {
    "the", "and", "for", "with", "his", "her", "was", "are", "you", "this",
    "that", "from", "has", "have", "not", "but", "all", "new", "latest",
    "video", "videos", "full", "watch", "shorts", "viral", "official", "ka",
    "ke", "ki", "hai", "mein", "aur", "par", "kya", "news", "live", "today",
}


def keywords(text, exclude):
    """Distinctive words only. Unicode-aware, so Indic scripts survive."""
    words = re.findall(r"\w+", (text or "").lower(), re.UNICODE)
    return {w for w in words
            if len(w) > 2 and w not in STOPWORDS and w not in exclude}


def overlap(a, b):
    """How much two word-sets share, 0 to 1."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def group(items, needles):
    """Four hundred copies of one thing is one problem, not four hundred."""
    exclude = set()
    for n in needles:
        exclude |= set(re.findall(r"\w+", n.lower(), re.UNICODE))

    problems = []
    for item in items:
        key = keywords(item["title"], exclude)
        placed = False
        for p in problems:
            if overlap(key, p["key"]) >= SAME_PROBLEM:
                p["items"].append(item)
                p["key"] |= key  # the group's vocabulary grows as it absorbs
                if item["views"] > p["lead"]["views"]:
                    p["lead"] = item
                placed = True
                break
        if not placed:
            problems.append({"key": key, "lead": item, "items": [item]})
    return problems


def prepare_events(subject):
    """Turn each event date + window into a start and end date."""
    events = subject.get("events", [])
    for ev in events:
        try:
            d = datetime.strptime(ev["date"], "%Y-%m-%d")
        except Exception:
            continue
        before = ev.get("days_before", 14)
        after = ev.get("days_after", 14)
        ev["_start"] = (d - timedelta(days=before)).strftime("%Y-%m-%d")
        ev["_end"] = (d + timedelta(days=after)).strftime("%Y-%m-%d")
    return events


# ---------------------------------------------------------------------------
# HOW MANY DIFFERENT CHANNELS ARE SAYING THIS SAME THING
# ---------------------------------------------------------------------------
# The discriminator that needs no language. For each problem, count the
# distinct channels posting similar content within a few days of it.
#
# Many channels saying it once  -> journalism
# Few channels saying it often  -> campaign

COHORT_DAYS = 4          # how close in time counts as "the same moment"
COHORT_SHARED_WORDS = 2  # how many distinctive words two items must share


def days_apart(a, b):
    try:
        return abs((datetime.strptime(a, "%Y-%m-%d") -
                    datetime.strptime(b, "%Y-%m-%d")).days)
    except Exception:
        return 999


def cohort_channels(problems):
    """For each problem, how many distinct channels cover the same story."""
    sigs = [(p, p["key"], p["lead"].get("date", ""),
             {i.get("channel_title", "") for i in p["items"]}) for p in problems]

    counts = []
    for p, key, date, own in sigs:
        channels = set(own)
        for q, qkey, qdate, qch in sigs:
            if q is p:
                continue
            if len(key & qkey) >= COHORT_SHARED_WORDS and days_apart(date, qdate) <= COHORT_DAYS:
                channels |= qch
        counts.append(len(channels))
    return counts


# ---------------------------------------------------------------------------
# IS THIS CHANNEL A STUDIO, OR A FARM
# ---------------------------------------------------------------------------
# A real production house makes content about its own films. An exploitation
# channel makes content about whoever is trending - so it features many
# unrelated stars.
#
# Counting distinct stars per channel separates the two, and like the news-
# cycle test it is arithmetic rather than vocabulary, so it works whatever
# language the titles are in.
#
# It also produces the thing you actually want to hand a lawyer: not one video
# but one account, with a list of everything it has done.

FARM_MIN_STARS = 3      # this many unrelated famous names = not a studio
FARM_MIN_UPLOADS = 3


def channel_report(problems, watchlist):
    """Group problems by uploader and work out who is running an operation."""
    by_channel = {}
    for p in problems:
        for item in p["items"]:
            ch = item.get("channel_title", "unknown")
            rec = by_channel.setdefault(ch, {"uploads": [], "stars": set()})
            rec["uploads"].append(item)
            blob = ((item.get("title") or "") + " " +
                    (item.get("description") or "")).lower()
            for star in watchlist:
                if star.lower() in blob:
                    rec["stars"].add(star)

    for ch, rec in by_channel.items():
        rec["is_farm"] = (len(rec["stars"]) >= FARM_MIN_STARS
                          and len(rec["uploads"]) >= FARM_MIN_UPLOADS)
        rec["views"] = sum(i.get("views", 0) or 0 for i in rec["uploads"])
    return by_channel


CHANNEL_COLUMNS = [
    "channel_title", "uploads", "total_views", "distinct_stars", "is_farm",
    "stars_featured", "example_title", "example_url",
]


COLUMNS = [
    "priority", "harm", "disposition", "claims", "selling", "heard", "shape",
    "cohort_channels", "copies", "views", "title", "channel_title", "url",
    "date", "content_harm", "reporting", "spread", "amplified", "context_x",
    "context_why", "removable", "backfire_risk",
    "damage_likeness", "damage_money", "damage_safety", "damage_dignity",
    "damage_business", "my_verdict",
]


def row_for(problem, events, channels, official):
    lead = problem["lead"]
    copies = len(problem["items"])
    verdict = rules.judge(lead, events, copies, channels, official)
    row = {c: "" for c in COLUMNS}
    row.update({
        "copies": copies,
        "views": sum(i["views"] for i in problem["items"]),
        "title": lead["title"],
        "channel_title": lead["channel_title"],
        "url": lead["url"],
        "date": lead["date"],
        "my_verdict": "",  # you fill this in by hand
    })
    row.update({k: v for k, v in verdict.items() if k in COLUMNS})
    return row


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python judge.py subjects/<file>.json")

    subject = json.load(open(sys.argv[1]))
    events = prepare_events(subject)

    path = f"data/{subject['id']}_items.jsonl"
    if not os.path.exists(path):
        sys.exit(f"No data at {path}. Run collect.py first.")

    items = [json.loads(line) for line in open(path) if line.strip()]
    print(f"{len(items)} items collected")

    needles = subject_needles(subject)
    relevant = [i for i in items if is_about_subject(i, needles)]
    dropped = len(items) - len(relevant)
    print(f"{dropped} dropped as not about {subject['name']}, {len(relevant)} kept")
    if not relevant:
        sys.exit("Nothing left. Check the 'name' and 'aliases' in the subject file.")

    problems = group(relevant, needles)
    print(f"{len(problems)} problems after grouping "
          f"({len(relevant) / max(len(problems), 1):.1f} copies each on average)")

    channels = cohort_channels(problems)
    official = subject.get("official_channels", [])
    rows = [row_for(p, events, n, official) for p, n in zip(problems, channels)]
    rows.sort(key=lambda r: r["priority"], reverse=True)

    ranked = f"data/{subject['id']}_ranked.csv"
    write_csv(ranked, rows)

    # The blind-spot check. You will never catch a miss by reading the top
    # of a list you sorted yourself.
    ignored = [r for r in rows if r["disposition"] in ("IGNORE", "WATCH")]
    sample = random.sample(ignored, min(20, len(ignored)))
    blind = f"data/{subject['id']}_blindspot.csv"
    write_csv(blind, sample)

    # Who is doing this, not just what was done. For likeness and IP work the
    # unit of enforcement is the uploader - YouTube strikes accrue to channels,
    # and a lawyer writes to a person, not to a video.
    watchlist = subject.get("watchlist", []) or [subject["name"]]
    report = channel_report(problems, watchlist)
    offenders = sorted(
        [(ch, r) for ch, r in report.items()
         if not rules.is_authorised(ch, official) and len(r["uploads"]) >= 2],
        key=lambda kv: (-len(kv[1]["stars"]), -len(kv[1]["uploads"])))

    ch_rows = []
    for ch, r in offenders:
        lead = max(r["uploads"], key=lambda i: i.get("views", 0) or 0)
        ch_rows.append({
            "channel_title": ch,
            "uploads": len(r["uploads"]),
            "total_views": r["views"],
            "distinct_stars": len(r["stars"]),
            "is_farm": r["is_farm"],
            "stars_featured": ", ".join(sorted(r["stars"])),
            "example_title": lead.get("title", ""),
            "example_url": lead.get("url", ""),
        })

    chan_path = f"data/{subject['id']}_channels.csv"
    with open(chan_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CHANNEL_COLUMNS)
        w.writeheader()
        w.writerows(ch_rows)

    counts = {}
    for r in rows:
        counts[r["disposition"]] = counts.get(r["disposition"], 0) + 1

    print("\nWhat it decided:")
    for label in ["FIX NOW", "FIX THIS WEEK", "JUST TELL HIM",
                  "DO NOT TOUCH", "WATCH", "IGNORE"]:
        if counts.get(label):
            print(f"  {label:<15} {counts[label]}")

    farms = sum(1 for r in ch_rows if r["is_farm"])
    print(f"\n{len(ch_rows)} channels with 2+ uploads, {farms} look like farms "
          f"(3+ unrelated stars)")

    print(f"\nOpen {ranked}      <- is the top of this list right?")
    print(f"Open {blind}   <- is anything nasty hiding in here?")
    print(f"Open {chan_path}    <- WHO is doing it. Start here")
    print("\nFill in the 'my_verdict' column yourself BEFORE reading the scores.")


if __name__ == "__main__":
    main()
