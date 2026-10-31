"""
Make fake data so you can see the whole thing work before getting an API key.

    python make_sample_data.py
    python judge.py subjects/example.json
"""

import json
import os
import random

random.seed(7)

HARMFUL = [
    ("Person Name reveals SECRET investment plan - double your money in 30 days", "MoneyGuru India"),
    ("PERSON NAME recommends this trading app | guaranteed profit daily", "Fast Earning Tips"),
    ("Person Name deepfake video - AI generated investment scam", "Scam Alert Daily"),
    ("Leaked private video of Person Name goes viral", "Viral Masala"),
    ("Person Name morphed photo controversy", "Filmy Buzz 24"),
    ("Person Name paisa double scheme - join telegram now", "Nivesh Wala"),
    ("Person Name ka ghar ka pata revealed", "Star Tracker"),
    ("Person Name arrested? FIR filed, ED raid latest news", "Khabar Express"),
]

BENIGN = [
    ("Person Name new film TRAILER out now", "T-Series"),
    ("Person Name full interview | behind the scenes", "Film Companion"),
    ("Person Name at award show red carpet highlights", "Bollywood Now"),
    ("Person Name new song promo teaser", "Sony Music India"),
    ("Person Name box office review", "Movie Review Hub"),
    ("Person Name birthday special throwback", "Fan Club Edits"),
    ("Person Name press conference full video", "NDTV"),
    ("Person Name making of the movie", "Netflix India"),
]

NEWS = [
    ("Person Name responds to allegations: full report", "India Today"),
    ("Person Name business dealings under scrutiny - investigation", "The Indian Express"),
]

items = []
n = 0


def add(title, channel, views, age_hours, date, copies=1):
    global n
    for c in range(copies):
        n += 1
        suffix = "" if c == 0 else f" | part {c+1}"
        items.append({
            "id": f"vid{n}",
            "url": f"https://www.youtube.com/watch?v=vid{n}",
            "platform": "youtube",
            "title": title + suffix,
            "description": title,
            "channel_title": channel if c == 0 else f"{channel} {c}",
            "channel_id": f"ch{n}",
            "thumbnail": "",
            "published": date + "T10:00:00Z",
            "date": date,
            "age_hours": age_hours,
            "views": max(1, int(views * random.uniform(0.3, 1.4))),
            "likes": int(views * 0.02),
            "comments": int(views * 0.005),
        })


# a coordinated scam campaign - many copies, high velocity, during release week
add(HARMFUL[0][0], HARMFUL[0][1], 40000, 20, "2026-08-10", copies=25)
add(HARMFUL[1][0], HARMFUL[1][1], 15000, 30, "2026-08-12", copies=8)
add(HARMFUL[2][0], HARMFUL[2][1], 90000, 48, "2026-08-11", copies=3)
add(HARMFUL[3][0], HARMFUL[3][1], 200000, 60, "2026-08-09")
add(HARMFUL[4][0], HARMFUL[4][1], 5000, 100, "2026-08-05")
add(HARMFUL[5][0], HARMFUL[5][1], 800, 200, "2026-07-28", copies=4)
add(HARMFUL[6][0], HARMFUL[6][1], 300, 400, "2026-07-15")
add(HARMFUL[7][0], HARMFUL[7][1], 60000, 72, "2026-08-08")

# a genuine news outlet - real damage, but not removable, and suing backfires
for title, ch in NEWS:
    add(title, ch, 250000, 90, "2026-08-07")

# the ordinary noise, which is most of what you will actually find
for i in range(120):
    title, ch = random.choice(BENIGN)
    add(f"{title} #{i}", ch, random.randint(500, 500000),
        random.randint(10, 700), f"2026-0{random.choice([7,8])}-{random.randint(10,28):02d}")

os.makedirs("data", exist_ok=True)
with open("data/example_items.jsonl", "w") as f:
    for item in items:
        f.write(json.dumps(item) + "\n")

print(f"wrote {len(items)} fake items to data/example_items.jsonl")
print("now run:  python judge.py subjects/example.json")
