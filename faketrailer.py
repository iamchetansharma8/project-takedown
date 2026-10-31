"""
Find fake trailers for films that are genuinely in production.

Most AI content about a star is harmless. A fan edit is a tribute, an openly
labelled AI short is a hobby, and telling a famous person to attack their own
fans is bad advice.

One case is different. A "first look" or "trailer" for a film that is actually
announced and unreleased lands inside the studio's real marketing window, and
misleads the exact audience that is waiting for it. That is commercial harm a
producer recognises without it being explained - unlike everything else we have
looked at on this project.

Two signals we already have make it precise:
  - TMDb knows which films are announced but unreleased
  - the title says trailer, teaser or first look, and the channel is not theirs

Unlike the false-attribution work, there is external evidence anyone cares
about this one: YouTube demonetised Screen Culture and Kh Studio, the largest
fake-AI-trailer channels, and the trade press covered it.

Usage:
    python3 filmography.py "Prabhas" subjects/prabhas.json    # gets release dates
    python3 faketrailer.py subjects/prabhas.json

Writes data/<id>_faketrailers.csv
"""

import csv
import json
import os
import re
import sys

import rules

# Claims to be promotional material for a film.
TRAILER_CLAIMS = [
    "trailer", "teaser", "first look", "firstlook", "glimpse", "promo",
    "announcement", "motion poster", "title reveal", "concept trailer",
    "official video", "sneak peek", "ट्रेलर", "టీజర్", "ట్రైలర్",
]

# Says openly that it is not real. Still worth listing, far less serious -
# and going after honest fan work is how a star loses their own fandom.
HONEST = [
    "concept", "fan made", "fanmade", "fan-made", "unofficial", "ai generated",
    "ai-generated", "made with ai", "not official", "imagination", "what if",
    "fan trailer", "spoof", "parody",
]

# Claims to be the real thing.
PRETENDING = [
    "official trailer", "official teaser", "official first look",
    "official announcement", "leaked", "exclusive", "real trailer",
    "released", "out now",
]

COLUMNS = [
    "severity", "film", "released_yet", "presents_as", "views",
    "channel_title", "title", "url", "date", "checked_by_hand", "notes",
]


def squash(s):
    return re.sub(r"[^\w]|_", "", (s or "").lower(), flags=re.UNICODE)


# Talks about a trailer rather than being one. "The RajaSaab Official Trailer
# Reaction" is commentary, and the word "official" in it refers to the real
# trailer being reacted to - the same class of error as news about a deepfake
# scoring as a deepfake.
ABOUT_NOT_IS = [
    "reaction", "review", "breakdown", "explained", "analysis", "discussion",
    "my thoughts", "first impression", "vs ", "comparison", "top 5", "top 10",
]


def claims_trailer(title):
    t = (title or "").lower()
    if any(a in t for a in ABOUT_NOT_IS):
        return False
    return any(c in t for c in TRAILER_CLAIMS)


def presents_as(text):
    t = (text or "").lower()
    if any(p in t for p in PRETENDING) and not any(h in t for h in HONEST):
        return "as real"
    if any(h in t for h in HONEST):
        return "admits it is not"
    return "says nothing"


def which_film(title, films):
    flat = squash(title)
    hits = [f for f in films if len(squash(f)) >= 4 and not squash(f).isdigit()
            and squash(f) in flat]
    return max(hits, key=len) if hits else ""


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 faketrailer.py subjects/<file>.json")

    subject = json.load(open(sys.argv[1]))
    films = subject.get("known_films", [])
    unreleased = set(subject.get("unreleased_films", []))
    official = subject.get("official_channels", [])
    needles = [subject["name"]] + subject.get("aliases", [])

    if not unreleased:
        print("No unreleased_films in the subject file.")
        print("Run filmography.py first - it records which films are announced")
        print("but not yet out, and that is the whole basis of this check.\n")

    path = f"data/{subject['id']}_items.jsonl"
    if not os.path.exists(path):
        sys.exit(f"No data at {path}. Run collect.py first.")

    items = [json.loads(line) for line in open(path) if line.strip()]

    rows = []
    for item in items:
        title = item.get("title", "")
        blob = title + " " + (item.get("description", "") or "")

        if not claims_trailer(title):
            continue
        if not any(n.lower() in blob.lower() for n in needles):
            continue
        if rules.is_authorised(item.get("channel_title", ""), official):
            continue          # the studio is allowed to trail its own film

        film = which_film(title, films)
        pretending = presents_as(blob)
        upcoming = film in unreleased

        # Worst case first: pretending to be the official trailer for a film
        # that is genuinely coming. That is the one inside the real campaign.
        if upcoming and pretending == "as real":
            severity = "PRE-EMPTS A REAL CAMPAIGN"
        elif upcoming:
            severity = "about an unreleased film"
        elif pretending == "as real":
            severity = "presents itself as official"
        else:
            severity = "ordinary fan work"

        rows.append({
            "severity": severity,
            "film": film or "(none named)",
            "released_yet": "not yet" if upcoming else ("released" if film else "?"),
            "presents_as": pretending,
            "views": item.get("views", 0),
            "channel_title": item.get("channel_title", ""),
            "title": title,
            "url": item.get("url", ""),
            "date": item.get("date", ""),
            "checked_by_hand": "",
            "notes": "",
        })

    order = ["PRE-EMPTS A REAL CAMPAIGN", "about an unreleased film",
             "presents itself as official", "ordinary fan work"]
    rows.sort(key=lambda r: (order.index(r["severity"]), -r["views"]))

    out = f"data/{subject['id']}_faketrailers.csv"

    previous = {}
    if os.path.exists(out):
        for old in csv.DictReader(open(out, encoding="utf-8")):
            if old.get("checked_by_hand", "").strip():
                previous[old.get("url", "")] = (old.get("checked_by_hand", ""),
                                                old.get("notes", ""))
    for r in rows:
        if r["url"] in previous:
            r["checked_by_hand"], r["notes"] = previous[r["url"]]

    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    print(f"{len(items)} items, {len(rows)} unofficial trailers naming {subject['name']}")
    counts = {}
    for r in rows:
        counts[r["severity"]] = counts.get(r["severity"], 0) + 1
    for s in order:
        if counts.get(s):
            views = sum(r["views"] for r in rows if r["severity"] == s)
            print(f"  {counts[s]:>3}  {s:<28} {views:>12,} views")

    top = [r for r in rows if r["severity"] == order[0]]
    if top:
        print("\nInside a live campaign:")
        for r in top[:10]:
            print(f"  {r['views']:>10,}  {r['film']:<18} {r['channel_title'][:18]:<18} | {r['title'][:40]}")

    print(f"\nwrote {out}")
    print("\nOrdinary fan work is listed last on purpose. It is not the target,")
    print("and advising a star to go after their own fans is bad advice.")


if __name__ == "__main__":
    main()
