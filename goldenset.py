"""
Build the answer key, once, by hand.

Without this, every prompt change is judged by looking at the top twenty and
deciding whether it feels better. That is how the last four iterations went,
and it is why a bug survived three of them.

Sampling is stratified, not random: the most-viewed, the highest-scoring, and
a random tail. Pure random would be almost entirely harmless items and would
teach you nothing about the cases that matter.

Usage:
    python3 goldenset.py subjects/prabhas.json [size]

Writes data/<id>_golden.csv with the label columns empty. Fill them in, save,
then run evaluate.py. Do it once; reuse it forever.
"""

import csv
import json
import os
import random
import sys

import rules

random.seed(11)   # same sample every time, so the set is stable

COLUMNS = [
    "id", "title", "channel_title", "views", "date", "url",
    "description_start",
    "my_category", "my_action", "notes",
]


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 goldenset.py subjects/<file>.json [size]")

    subject = json.load(open(sys.argv[1]))
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 100

    path = f"data/{subject['id']}_items.jsonl"
    if not os.path.exists(path):
        sys.exit(f"No data at {path}")

    items = [json.loads(line) for line in open(path) if line.strip()]
    official = subject.get("official_channels", [])

    # Sample mostly from items that are actually about the client.
    #
    # The first version sampled across everything and 42 of 60 rows turned out
    # to be MrBeast, Spider-Man and unrelated Telugu music - because the broad
    # searches drag in noise. You would have spent an afternoon typing
    # "unrelated" and learned nothing about the cases that matter.
    #
    # A few unrelated rows are kept deliberately, as controls: if the model
    # cannot recognise an obviously irrelevant video, that is worth knowing.
    needles = [subject["name"].lower()] + [a.lower() for a in subject.get("aliases", [])]

    def about_client(item):
        blob = ((item.get("title") or "") + " " +
                (item.get("description") or "")).lower()
        return any(n in blob for n in needles)

    relevant = [i for i in items if about_client(i)]
    irrelevant = [i for i in items if not about_client(i)]
    controls = max(3, size // 10)

    if not relevant:
        sys.exit("Nothing in the data mentions this person. Check name and aliases.")

    print(f"{len(items)} items, {len(relevant)} about {subject['name']}")
    items = relevant

    def score(item):
        text = (item.get("title") or "") + " " + (item.get("description") or "")
        harm, _, _ = rules.content_harm(text, item.get("channel_title", ""),
                                        official, item)
        return harm

    by_views = sorted(items, key=lambda i: -(i.get("views", 0) or 0))
    by_score = sorted(items, key=lambda i: -score(i))

    chosen, seen = [], set()

    def take(pool, n):
        for item in pool:
            if len(chosen) >= size or n <= 0:
                return
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            chosen.append(item)
            n -= 1

    budget = size - controls
    take(by_views, budget // 3)                    # what most people will see
    take(by_score, budget // 3)                    # what the rules think matters
    take(random.sample(items, len(items)), budget) # the long tail

    # Controls: obviously irrelevant videos, to check the model can say so.
    if irrelevant:
        size += controls
        take(random.sample(irrelevant, len(irrelevant)), controls)

    with open(f"data/{subject['id']}_golden.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for item in chosen:
            w.writerow({
                "id": item["id"],
                "title": item.get("title", ""),
                "channel_title": item.get("channel_title", ""),
                "views": item.get("views", 0),
                "date": item.get("date", ""),
                "url": item.get("url", ""),
                "description_start": (item.get("description") or "")[:300].replace("\n", " "),
                "my_category": "",
                "my_action": "",
                "notes": "",
            })

    print(f"wrote {len(chosen)} items to data/{subject['id']}_golden.csv")
    print("\nFill in my_category and my_action for each row.")
    print("\ncategories:", ", ".join(__import__("classify").CATEGORIES))
    print("actions:   ", ", ".join(__import__("classify").ACTIONS))
    print("\nOpen the url when the title is not enough. It is slow, it is")
    print("boring, and it is the only thing that turns this into engineering.")


if __name__ == "__main__":
    main()
