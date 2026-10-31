"""
Fetch transcripts for the videos worth listening to.

Why this exists: the sales pitch is spoken, not written. A video titled
"Motivational speech" can spend four minutes telling you to deposit 22,000
rupees into a trading app. Title-only judging is blind to exactly the thing
rights owners most want removed.

Why it is a separate step: transcripts are slow and get rate-limited. So we
use the cheap signals first and only pay the expensive cost on survivors -
which is how the real product should work too. Cheap filter, then expensive
check, never expensive check on everything.

Setup:
    pip3 install youtube-transcript-api

Usage:
    python3 enrich.py subjects/<file>.json [max_videos]

Reads  data/<id>_items.jsonl
Writes data/<id>_items.jsonl  (in place, adding a "transcript" field)
"""

import json
import os
import sys
import time

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    sys.exit("Not installed. Run:  pip3 install youtube-transcript-api")

import rules

# Indian content is rarely in English, so ask for the common ones and let it
# fall back to whatever exists, including auto-generated captions.
LANGUAGES = ["en", "hi", "bn", "ta", "te", "kn", "ml", "mr", "gu", "pa"]

TRANSCRIPT_CHARS = 4000   # enough to catch a pitch, small enough to stay cheap
PAUSE = 0.4               # be polite, this is an unofficial endpoint


def worth_listening_to(item, official):
    """Which videos justify the cost of a transcript.

    Deliberately generous - we are trying to find things the title missed, so
    a strict filter here defeats the purpose. Excludes only what is clearly
    authorised or clearly irrelevant.
    """
    if rules.is_authorised(item.get("channel_title", ""), official):
        return False

    text = (item.get("title") or "") + " " + (item.get("description") or "")
    harm, axes, _ = rules.content_harm(text, item.get("channel_title", ""), official)

    # Anything already suspicious, anything mentioning AI or money, or anything
    # with real reach - reach alone is a reason to check.
    return (
        harm >= 2
        or axes.get("likeness", 0) > 0
        or axes.get("money", 0) > 0
        or (item.get("views", 0) or 0) > 20000
    )


def fetch(video_id, report=False):
    """Get a transcript, and say why if you cannot.

    The first version caught every exception and returned "". So a genuine
    absence of captions, a broken library version, and YouTube blocking the
    endpoint from this IP all looked exactly the same - and a run that got
    zero transcripts out of thirty gave no clue which had happened.
    """
    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=LANGUAGES)
        return " ".join(s.text for s in fetched)[:TRANSCRIPT_CHARS], ""
    except AttributeError:
        # Older versions of the library used a static method instead.
        try:
            parts = YouTubeTranscriptApi.get_transcript(video_id, languages=LANGUAGES)
            return " ".join(p["text"] for p in parts)[:TRANSCRIPT_CHARS], ""
        except Exception as e:
            return "", f"{type(e).__name__}: {str(e)[:160]}"
    except Exception as e:
        return "", f"{type(e).__name__}: {str(e)[:160]}"


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 enrich.py subjects/<file>.json [max_videos]")

    subject = json.load(open(sys.argv[1]))
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else 150
    official = subject.get("official_channels", [])

    path = f"data/{subject['id']}_items.jsonl"
    if not os.path.exists(path):
        sys.exit(f"No data at {path}. Run collect.py first.")

    items = [json.loads(line) for line in open(path) if line.strip()]

    candidates = [i for i in items
                  if i.get("platform") == "youtube"
                  and "transcript" not in i
                  and worth_listening_to(i, official)]
    candidates.sort(key=lambda i: -(i.get("views", 0) or 0))
    candidates = candidates[:cap]

    print(f"{len(items)} items, {len(candidates)} worth listening to "
          f"(capped at {cap})")

    got = 0
    reasons = {}
    for n, item in enumerate(candidates, 1):
        text, why = fetch(item["id"])
        item["transcript"] = text
        if text:
            got += 1
        elif why:
            reasons[why.split(":")[0]] = why
        if n % 20 == 0:
            print(f"  {n}/{len(candidates)}... {got} transcripts so far")
        time.sleep(PAUSE)

    with open(path, "w") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    missing = len(candidates) - got
    print(f"\ngot {got} transcripts, {missing} without")

    if reasons:
        print("\nWhy they failed:")
        for kind, example in reasons.items():
            print(f"  {example}")
        print("\n  TranscriptsDisabled / NoTranscriptFound -> genuinely no")
        print("     captions. Nothing to fix; transcripts are not an option")
        print("     for this content.")
        print("  IpBlocked / RequestBlocked / TooManyRequests -> YouTube is")
        print("     refusing this IP. Try a different network or a VPN.")
        print("  AttributeError / TypeError -> library version mismatch.")
        print("     Try: pip3 install -U youtube-transcript-api")

    if got:
        print(f"\nNext:  python3 judge.py {sys.argv[1]}")


if __name__ == "__main__":
    main()
