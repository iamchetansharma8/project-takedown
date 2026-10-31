"""
Find videos putting a star's name on films they are not in.

The violation is in the metadata, not the content - which is why nothing
catches it. YouTube's Content ID matches audio and video fingerprints and never
reads a title, so a false star name sits in the open indefinitely. Two were
confirmed by hand on this project, with 39 million views between them, and
neither featured the actor at all.

The test:
    the title claims to be a full film
    AND it names our client
    AND it names no film our client has ever been in
    -> the attribution is unsupported

Deliberately says "unsupported", not "false". A Hindi dub is often retitled for
that market, so a real film can fail this check. The output is a list to verify,
not an accusation - and getting that distinction wrong is the one mistake this
tool cannot afford to make.

Usage:
    python3 attribution.py subjects/prabhas-attribution.json

Writes data/<id>_attribution.csv
"""

import csv
import json
import os
import re
import sys

# Title phrases that assert "this video IS a film", as opposed to a clip,
# a song, a review or a trailer.
MOVIE_CLAIMS = [
    "full movie", "full film", "fullmovie", "full action movie",
    "hindi dubbed movie", "dubbed movie", "blockbuster movie",
    "south movie", "new movie", "latest movie", "movie in hindi",
    "पूरी फिल्म", "పూర్తి సినిమా",
]

# Things that look like a film claim but are not one.
NOT_A_MOVIE = [
    "trailer", "teaser", "review", "reaction", "explained", "interview",
    "song", "lyrical", "making of", "behind the scenes", "shorts",
    "scene", "clip", "first look", "promo", "glimpse", "bgm",
    # Compilations and rankings. "top 5 prabhas movie in Hindi" slipped
    # through and was reported as a false attribution, which it is not - it
    # is a list about him, and lists are allowed to name him.
    "top 5", "top 10", "top5", "top10", "best of", "all movies",
    "movies list", "list of", "evolution", "ranked", "vs",
]

# ---------------------------------------------------------------------------
# DOES IT RUN AS LONG AS THE FILM IT CLAIMS TO BE
# ---------------------------------------------------------------------------
# Catches the other half of the problem: a title naming a real film of his,
# with something else entirely underneath. Content ID never notices, because
# it fingerprints the content it was given - so it checks the film that IS
# there, and the rights holder of the film that ISN'T there is never told.
#
# Runtime will not match exactly and should not be expected to. Channels bolt
# on their own intros and outros, trim end credits, and Hindi dubs are often
# cut for the market. So this measures how far off it is, not whether it is
# equal, and only speaks up when the gap is too big to explain.

CLOSE_ENOUGH = 0.15    # within 15% - intro, outro, trimmed credits. Normal
QUESTIONABLE = 0.35    # 15-35% - a heavily cut dub, or the wrong film
                       # beyond 35% - not the film it says it is


# Films are routinely uploaded split across several videos. Without this, a
# 50-minute "Part 1 of 3" gets compared against a 159-minute runtime and is
# reported as the wrong film - a false accusation caused entirely by our own
# arithmetic.
#
# Splitting is also, incidentally, a known way to make content harder to match
# automatically. Not something to assert about any particular uploader, but a
# reason not to treat a part upload as innocent either.

PART_PATTERNS = [
    r"part\s*[-:]?\s*(\d+)\s*(?:of|/)\s*(\d+)",   # part 1 of 3, part 1/3
    r"part\s*[-:]?\s*(\d+)()",                    # part 2
    r"\bp(\d+)\s*(?:of|/)\s*(\d+)",               # p1/3
    r"\((\d+)\s*/\s*(\d+)\)",                     # (1/3)
    r"भाग\s*(\d+)()",                              # Hindi
    r"\bvol(?:ume)?\s*[-:]?\s*(\d+)()",           # vol 2
]


def part_of(title):
    """Returns (part_number, total_parts_or_None) or None if not a part."""
    t = (title or "").lower()
    for pattern in PART_PATTERNS:
        m = re.search(pattern, t)
        if m:
            part = int(m.group(1))
            total = int(m.group(2)) if m.lastindex >= 2 and m.group(2) else None
            return part, total
    return None


def runtime_verdict(actual, expected, part=None):
    """Returns (verdict, human-readable gap)."""
    if not expected:
        return "no runtime on file", ""
    if not actual:
        return "no duration collected", ""

    if part:
        # No runtime maths on parts, and the earlier version that divided the
        # runtime by the number of parts has been removed.
        #
        # It assumed parts are complete and evenly sized. Neither holds: often
        # only some parts are uploaded, they are cut at whatever point suits
        # the uploader, and plenty of "part" videos are just a comedy sequence
        # or a well-known scene rather than a slice of the film.
        #
        # Any arithmetic here would be inventing precision we do not have.
        number, total = part
        return "part - not checked", f"part {number}{' of ' + str(total) if total else ''}"

    gap = (actual - expected) / expected
    direction = "longer" if gap > 0 else "shorter"
    note = f"{actual}m vs {expected}m expected, {abs(gap) * 100:.0f}% {direction}"

    if abs(gap) <= CLOSE_ENOUGH:
        return "runtime fits", note
    if abs(gap) <= QUESTIONABLE:
        return "runtime off", note
    return "runtime very wrong", note


# A deliberate demotion. Runtime used to produce a verdict in capitals, which
# read like a finding. It is not one - it is a hint that something is worth
# opening, and it is wrong often enough that it should not carry more weight
# than that.
#
# Metadata cannot answer "is this the film it claims to be". Every patch so far
# - dubbed retitles, parts, clips - has been compensating for the fact that we
# are not looking at the video. The next real step is sampling frames, not a
# cleverer sum.


COLUMNS = [
    "verdict", "runtime_check", "runtime_note", "part", "views",
    "channel_title", "title", "matched_film", "url", "date",
    "checked_by_hand", "notes",
]


def squash_title(title):
    """Title with part markers stripped, so the pieces of one film collapse
    onto a single key."""
    t = (title or "").lower()
    for pattern in PART_PATTERNS:
        t = re.sub(pattern, " ", t)
    return re.sub(r"[^a-z0-9]", "", t)


def as_uploads(rows):
    """Three parts of one film is one upload, not three.

    Counting parts separately would inflate the headline number, and the
    headline number is the thing that ends up in front of a lawyer.
    """
    groups = {}
    for r in rows:
        key = (r["channel_title"], squash_title(r["title"]))
        g = groups.setdefault(key, {"rows": [], "views": 0})
        g["rows"].append(r)
        g["views"] += r["views"]
    return groups


def claims_to_be_a_film(title):
    t = (title or "").lower()
    if any(n in t for n in NOT_A_MOVIE):
        return False
    return any(c in t for c in MOVIE_CLAIMS)


def names_subject(text, needles):
    t = (text or "").lower()
    return any(n.lower() in t for n in needles)


def squash(s):
    """Strip punctuation and spacing, keeping letters and digits in ANY script.

    The first version used [^a-z0-9], which is ASCII-only. The Telugu title
    "బాహుబలి 2: ది కన్ క్లూజన్" therefore squashed down to "2" - so every video
    with 2026 or 2025 in its name "matched a real film". Forty of forty-three
    were waved through by a single stray digit.

    Two guards now. Unicode-aware stripping so Indic titles survive intact,
    and a minimum length below, because a two-character key will always match
    something.
    """
    return re.sub(r"[^\w]|_", "", (s or "").lower(), flags=re.UNICODE)


MIN_KEY = 4   # shorter than this and the match is a coincidence


def find_known_film(title, films):
    """Which of the client's real films, if any, does this title name?"""
    flat = squash(title)
    hits = []
    for f in films:
        key = squash(f)
        if len(key) < MIN_KEY:
            continue          # too short to mean anything
        if key.isdigit():
            continue          # a bare number is not a title
        if key in flat:
            hits.append(f)
    # Longest match wins, so "Kalki 2898" beats "Kalki".
    return max(hits, key=len) if hits else ""


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 attribution.py subjects/<file>.json")

    subject = json.load(open(sys.argv[1]))
    films = subject.get("known_films", [])
    runtimes = subject.get("runtimes", {})
    if not films:
        sys.exit("No known_films in the subject file. Nothing to check against.")

    needles = [subject["name"]] + subject.get("aliases", [])

    path = f"data/{subject['id']}_items.jsonl"
    if not os.path.exists(path):
        sys.exit(f"No data at {path}. Run collect.py first.")

    items = [json.loads(line) for line in open(path) if line.strip()]

    rows = []
    for item in items:
        title = item.get("title", "")
        if not claims_to_be_a_film(title):
            continue
        if not names_subject(title, needles):
            continue

        matched = find_known_film(title, films)
        part = part_of(title)
        check, note = runtime_verdict(item.get("duration_min", 0),
                                      runtimes.get(matched, 0) if matched else 0,
                                      part)
        rows.append({
            "part": f"{part[0]}/{part[1] or '?'}" if part else "",
            "verdict": "names a real film" if matched else "UNSUPPORTED",
            "runtime_check": check,
            "runtime_note": note,
            "views": item.get("views", 0),
            "channel_title": item.get("channel_title", ""),
            "title": title,
            "matched_film": matched,
            "url": item.get("url", ""),
            "date": item.get("date", ""),
            "checked_by_hand": "",
            "notes": "",
        })

    def rank(r):
        # Wrong name first, then right name but wrong length, then the rest.
        if r["verdict"] == "UNSUPPORTED":
            return (0, -r["views"])
        if r["runtime_check"] == "runtime very wrong":
            return (1, -r["views"])
        if r["runtime_check"] == "runtime off":
            return (2, -r["views"])
        return (3, -r["views"])

    rows.sort(key=rank)

    out = f"data/{subject['id']}_attribution.csv"

    # Carry forward anything already verified by hand.
    #
    # The first version rewrote this file from scratch on every run, which
    # silently destroyed the verification column - the one part of the output
    # that costs human time and is the only thing that turns a claim into a
    # number. Re-running a script should never lose work.
    previous = {}
    if os.path.exists(out):
        for old in csv.DictReader(open(out, encoding="utf-8")):
            if old.get("checked_by_hand", "").strip() or old.get("notes", "").strip():
                previous[old.get("url", "")] = (old.get("checked_by_hand", ""),
                                                old.get("notes", ""))
    for r in rows:
        if r["url"] in previous:
            r["checked_by_hand"], r["notes"] = previous[r["url"]]

    if previous:
        print(f"carried forward {len(previous)} hand-checked rows")

    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    bad = [r for r in rows if r["verdict"] == "UNSUPPORTED"]
    ok = [r for r in rows if r["verdict"] != "UNSUPPORTED"]
    channels = {r["channel_title"] for r in bad}

    bad_uploads = as_uploads(bad)
    multipart = sum(1 for g in bad_uploads.values() if len(g["rows"]) > 1)

    print(f"{len(items)} items, {len(rows)} claim to be a film naming {subject['name']}")
    print(f"\n  {len(ok):>4} name one of his real films")
    print(f"  {len(bad):>4} name no film he has ever been in")
    print(f"\nThose {len(bad)} videos are {len(bad_uploads)} actual films "
          f"({multipart} were split across parts)")
    print(f"Unsupported: {sum(r['views'] for r in bad):,} views "
          f"across {len(channels)} channels")

    if bad:
        print("\nBiggest:")
        for r in bad[:12]:
            print(f"  {r['views']:>11,}  {r['channel_title'][:22]:<22} | {r['title'][:52]}")

        by_channel = {}
        for r in bad:
            c = by_channel.setdefault(r["channel_title"], [0, 0])
            c[0] += 1
            c[1] += r["views"]
        print("\nWorst channels:")
        for ch, (n, v) in sorted(by_channel.items(), key=lambda kv: -kv[1][1])[:10]:
            print(f"  {n:>2} uploads  {v:>12,} views  {ch[:40]}")

    wrong_len = [r for r in rows if r["runtime_check"] == "runtime very wrong"]
    off_len = [r for r in rows if r["runtime_check"] == "runtime off"]
    unchecked = [r for r in rows
                 if r["verdict"] == "names a real film"
                 and r["runtime_check"] in ("no runtime on file",
                                            "no duration collected")]

    if wrong_len or off_len or unchecked:
        print("\nOf the ones naming a real film:")
        print(f"  {len(wrong_len):>4} run nothing like the right length")
        print(f"  {len(off_len):>4} are off but could be a cut dub")
        print(f"  {len(unchecked):>4} could not be checked - no runtime on file")
        for r in wrong_len[:8]:
            print(f"      {r['views']:>10,}  {r['runtime_note']:<34} "
                  f"{r['title'][:40]}")

    print(f"\nwrote {out}")
    print("\nFill in checked_by_hand with ONE of:")
    print("  absent            not in it at all        <- our violation")
    print("  wrong-film        he IS in it, but it is not the film claimed")
    print("  cameo             brief appearance        <- name is not lying")
    print("  present           genuinely in it         <- our list was wrong")
    print("  different-person  another actor, similar name")
    print("  not-a-film        clip or compilation that slipped the filter")
    print("  dead              removed or private now")
    print("  unclear           could not tell")
    print("\n  wrong-film is a real violation but a DIFFERENT one. The name is")
    print("  truthful, so it is not passing off - the lie is about which film,")
    print("  and a film title belongs to the studio. Worth listing, worth")
    print("  telling a studio about, but it is not the star's claim to bring.")
    print("\nnotes: what the film actually is, if you can tell. That is what")
    print("turns a list into evidence.")
    print("\nQuickest check: open it, drag to 20%, 50%, 80%. A lead actor is")
    print("on screen at all three. Thirty seconds a video.")
    print("\nBefore quoting any of this: open the top rows and confirm he is")
    print("genuinely absent. UNSUPPORTED means the title names no film of his,")
    print("which is a reason to look - not proof. A retitled Hindi dub will")
    print("land here too, and one wrong accusation costs more than ten misses.")


if __name__ == "__main__":
    main()
