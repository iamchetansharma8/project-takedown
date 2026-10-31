"""
Ask a model what each item actually is.

The keyword rules could not tell an AI web series from a fan edit from a news
report about AI, because all three use the same words. Four attempts at better
vocabulary all failed the same way. Reading is the job, so use something that
reads.

The rules are not deleted. They are demoted: they now decide what is worth
spending a call on, and the model decides what it is. Cheap doorman, expensive
judge - which is the architecture the research called consensus, and the one we
arrived at the long way round.

Usage:
    export PROVIDER=gemini
    export GEMINI_API_KEY=...
    python3 classify.py subjects/prabhas.json [max_items]

Reads  data/<id>_items.jsonl
Writes data/<id>_classified.jsonl
"""

import json
import os
import sys
import time

import providers
import rules

BATCH = 8          # items per call. Small enough that one bad item cannot
                   # poison a whole batch's output.
PAUSE = 1.0        # free tiers rate-limit aggressively


# ---------------------------------------------------------------------------
# THE TAXONOMY
# ---------------------------------------------------------------------------
# Fixed, not free text. A label you cannot count is a label you cannot measure,
# and measuring is the only thing that separates this from guessing.

CATEGORIES = {
    "official": "Published by the rights holder, their studio, label or licensee",
    "news_or_commentary": "Reporting on, reviewing, reacting to or explaining something. Includes videos ABOUT AI or ABOUT a controversy",
    "fan_edit": "Transformative fan work using existing footage - compilations, edits, mashups, tributes",
    "ai_recreation": "AI-generated content depicting the person, openly presented as AI or fan-made",
    "fake_announcement": "AI or fabricated content presented as a genuine release, trailer, first look or news",
    "impersonation": "An account or content pretending to BE the person",
    "endorsement_abuse": "Uses the person's face, voice or name to sell a product or service",
    "music_derivative": "AI voice cover, remix or cloned-vocal song",
    "unrelated": "Not actually about this person",
}

ACTIONS = {
    "ignore": "Harmless. No action",
    "watch": "Not worth acting on yet, may escalate",
    "licence_opportunity": "Unauthorised but not damaging - this uploader is a potential licensee, not a defendant",
    "request_removal": "Should be taken down through platform process",
    "urgent_removal": "Legal clock running or serious active harm",
    "tell_client_only": "Client must know, but nothing can be done",
    "do_not_touch": "Acting would make it worse",
}

SYSTEM = """You review online content on behalf of a person or rights holder and decide what each item is.

You are not a content moderator looking for rule breaches. You are advising a client on what is worth their lawyer's time, so be sparing: most of what you see is harmless, and telling a famous person to attack their own fans is bad advice.

Judge only what the evidence supports. If the metadata does not tell you, say unclear rather than guessing.

Two distinctions matter more than the rest:

1. Content ABOUT a thing is not the thing. A news report about a deepfake is journalism. A video explaining AI is commentary. Neither is an attack, however alarming the words in the title.

2. Being honest changes everything. Content that says "fan made" or "AI generated" is transformative work - usually harmless, sometimes a licensing opportunity. Content that presents the same thing as an official release is passing off, and that is the serious case.

Return ONLY a JSON array. One object per item, in the order given, each with:
  "id"                  the item's id, copied exactly
  "ai_likeness"         "yes" | "no" | "unclear" - see below. THE MAIN QUESTION
  "category"            one of the listed categories
  "subject_depicted"    "yes" | "no" | "unclear"
  "likely_authorised"   "yes" | "no" | "unclear"
  "commercial"          "yes" | "no" | "unclear" - is someone making money from it
  "action"              one of the listed actions
  "confidence"          "low" | "medium" | "high"
  "reason"              one short sentence, plain English, citing what you saw

ai_likeness is the question that matters most. Answer "yes" only when the
content appears to be ARTIFICIALLY GENERATED OR MANIPULATED and depicts this
person's face or voice. That covers AI video, AI images, voice cloning, face
swaps and synthetic trailers.

It does NOT cover: real footage edited or recut, fan compilations of genuine
clips, thumbnails made in Photoshop, or anything merely discussing AI. Editing
real footage is not synthesising a person.

If the metadata does not let you tell whether the imagery is generated or
filmed, say "unclear". That will be common and it is the honest answer."""


def build_prompt(subject, items):
    cats = "\n".join(f"  {k}: {v}" for k, v in CATEGORIES.items())
    acts = "\n".join(f"  {k}: {v}" for k, v in ACTIONS.items())
    official = ", ".join(subject.get("official_channels", [])) or "none listed"

    lines = [
        f"CLIENT: {subject['name']}",
        f"Also known as: {', '.join(subject.get('aliases', [])) or 'n/a'}",
        f"Channels authorised to publish their work: {official}",
        "",
        "CATEGORIES:", cats, "",
        "ACTIONS:", acts, "",
        f"ITEMS ({len(items)}):",
    ]

    for item in items:
        desc = (item.get("description") or "")[:600].replace("\n", " ")
        line = [
            f"\n- id: {item['id']}",
            f"  title: {item.get('title','')}",
            f"  channel: {item.get('channel_title','')}",
            f"  views: {item.get('views',0)}   posted: {item.get('date','')}",
            f"  description: {desc}",
        ]
        if item.get("transcript"):
            line.append(f"  spoken words: {item['transcript'][:800]}")
        lines.append("\n".join(line))

    return "\n".join(lines)


def worth_a_call(item, subject):
    """The doorman. Rules decide what deserves an expensive judgement.

    Deliberately loose - the whole reason for using a model is that keywords
    were bad at this, so a tight filter here would reintroduce the problem it
    is meant to solve. It only removes what is certainly irrelevant.
    """
    needles = [subject["name"].lower()] + [a.lower() for a in subject.get("aliases", [])]
    blob = ((item.get("title") or "") + " " +
            (item.get("description") or "")).lower()
    return any(n in blob for n in needles)


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 classify.py subjects/<file>.json [max_items]")

    subject = json.load(open(sys.argv[1]))
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else 400

    path = f"data/{subject['id']}_items.jsonl"
    if not os.path.exists(path):
        sys.exit(f"No data at {path}. Run collect.py first.")

    items = [json.loads(line) for line in open(path) if line.strip()]
    candidates = [i for i in items if worth_a_call(i, subject)]

    # Order by suspicion, not by views. Sorting by popularity and taking the
    # top N meant 134 of 160 episodic items were never even classified - and
    # episodic is the strongest signal of the harm we are looking for.
    official = subject.get("official_channels", [])
    counts = rules.channel_tally(candidates)
    candidates.sort(key=lambda i: -rules.priority(i, official, counts))
    candidates = candidates[:cap]

    calls = (len(candidates) + BATCH - 1) // BATCH
    print(f"{len(items)} items, {len(candidates)} passed the filter, "
          f"{calls} calls to {providers.PROVIDER}")

    results = {}
    for n in range(0, len(candidates), BATCH):
        batch = candidates[n:n + BATCH]
        try:
            raw = providers.complete(SYSTEM, build_prompt(subject, batch))
            for verdict in providers.parse_json(raw):
                results[verdict.get("id")] = verdict
        except Exception as e:
            print(f"  batch {n // BATCH + 1} failed: {e}")
        done = n // BATCH + 1
        if done % 5 == 0 or done == calls:
            print(f"  {done}/{calls} calls, {len(results)} judged")
        time.sleep(PAUSE)

    out = f"data/{subject['id']}_classified.jsonl"
    with open(out, "w") as f:
        for item in candidates:
            verdict = results.get(item["id"])
            if verdict:
                f.write(json.dumps({**item, "llm": verdict},
                                   ensure_ascii=False) + "\n")

    print(f"\nwrote {len(results)} judgements to {out}")

    # The headline number. Everything else is detail.
    by_id = {i["id"]: i for i in candidates}
    hits = [v for v in results.values() if v.get("ai_likeness") == "yes"]
    maybe = [v for v in results.values() if v.get("ai_likeness") == "unclear"]
    unauth = [v for v in hits if v.get("likely_authorised") != "yes"]
    hit_views = sum((by_id.get(v["id"], {}).get("views") or 0) for v in unauth)

    print(f"\nAI-generated content using {subject['name']}'s likeness:")
    print(f"  {len(hits):>4} yes")
    print(f"  {len(maybe):>4} unclear from metadata alone")
    print(f"  {len(unauth):>4} of the yeses look unauthorised "
          f"({hit_views:,} views)")

    tally = {}
    for v in results.values():
        tally[v.get("category", "?")] = tally.get(v.get("category", "?"), 0) + 1
    print("\nBy category:")
    for cat, count in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {cat:<22} {count}")

    print(f"\nNext:  python3 evaluate.py {sys.argv[1]}")


if __name__ == "__main__":
    main()
