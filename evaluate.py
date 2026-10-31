"""
Score the model against your hand labels.

Every prompt change gets measured here. If a change does not move these
numbers, it did not do anything, however much better it feels.

Usage:
    python3 evaluate.py subjects/prabhas.json

Needs data/<id>_golden.csv filled in, and data/<id>_classified.jsonl.
"""

import collections
import csv
import json
import os
import sys


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 evaluate.py subjects/<file>.json")

    subject = json.load(open(sys.argv[1]))
    gold_path = f"data/{subject['id']}_golden.csv"
    pred_path = f"data/{subject['id']}_classified.jsonl"

    for p in (gold_path, pred_path):
        if not os.path.exists(p):
            sys.exit(f"Missing {p}")

    gold = {r["id"]: r for r in csv.DictReader(open(gold_path, encoding="utf-8"))
            if r.get("my_category", "").strip()}
    pred = {}
    for line in open(pred_path, encoding="utf-8"):
        if line.strip():
            item = json.loads(line)
            pred[item["id"]] = item["llm"]

    overlap = [i for i in gold if i in pred]
    if not overlap:
        sys.exit("No overlap. Did you label rows that were actually classified?")

    print(f"{len(gold)} labelled, {len(pred)} classified, {len(overlap)} comparable\n")

    cat_hits = sum(1 for i in overlap
                   if gold[i]["my_category"].strip() == pred[i].get("category"))
    act_hits = sum(1 for i in overlap
                   if gold[i].get("my_action", "").strip() == pred[i].get("action"))

    print(f"category agreement:  {cat_hits}/{len(overlap)} "
          f"({cat_hits / len(overlap) * 100:.0f}%)")
    print(f"action agreement:    {act_hits}/{len(overlap)} "
          f"({act_hits / len(overlap) * 100:.0f}%)")

    # The two errors are not equally bad, so they are counted separately.
    # Calling something harmless when it is not is a miss you never see.
    # Calling something harmful when it is not wastes a lawyer's afternoon.
    quiet = {"ignore", "watch", ""}
    missed = [i for i in overlap
              if gold[i].get("my_action") not in quiet
              and pred[i].get("action") in quiet]
    noisy = [i for i in overlap
             if gold[i].get("my_action") in quiet
             and pred[i].get("action") not in quiet]

    print(f"\nmissed (you said act, it said ignore):   {len(missed)}")
    print(f"noisy  (it said act, you said ignore):   {len(noisy)}")

    if missed:
        print("\nThe misses matter most - these are the ones you never see:")
        for i in missed[:8]:
            print(f"  you={gold[i]['my_action']:<20} it={pred[i].get('action','?'):<20} "
                  f"{gold[i]['title'][:48]}")

    confusion = collections.Counter(
        (gold[i]["my_category"].strip(), pred[i].get("category"))
        for i in overlap
        if gold[i]["my_category"].strip() != pred[i].get("category"))
    if confusion:
        print("\nMost common category confusions:")
        for (mine, theirs), n in confusion.most_common(8):
            print(f"  {n:>3}x  you said {mine:<20} it said {theirs}")

    by_conf = collections.defaultdict(lambda: [0, 0])
    for i in overlap:
        c = pred[i].get("confidence", "?")
        by_conf[c][1] += 1
        if gold[i]["my_category"].strip() == pred[i].get("category"):
            by_conf[c][0] += 1
    print("\nIs it right when it says it is sure?")
    for c in ("high", "medium", "low"):
        if c in by_conf:
            hit, total = by_conf[c]
            print(f"  {c:<8} {hit}/{total} ({hit / total * 100:.0f}%)")
    print("\n(If high confidence is not clearly better than low, the confidence")
    print(" field is decoration and should not be used to route work.)")


if __name__ == "__main__":
    main()
