"""
Ask Gemini to actually watch the video, and find out how little we can send.

The question these videos raise - "is this person in this film, and which film
is it?" - cannot be answered from a title. It needs the content. Gemini's API
accepts a YouTube URL directly, so nothing is downloaded and there is no
frame extraction on our side; Google decodes it server-side.

That leaves one open question, which is cost. Three ways to ask, and nobody
knows which is sufficient until it is measured:

    transcript   the spoken words only. Near-free
    clips        3 short windows of actual video. About 9k tokens
    full         the entire video. About 300 tokens per second, so a
                 150-minute film is roughly 2.7 MILLION tokens

If transcript answers it, we never send video at all and this scales to
thousands of items. If it does not, we know exactly what the video is buying.

Usage:
    export GEMINI_API_KEY=...
    python3 watch.py subjects/prabhas-attribution.json --methods transcript,clips -n 5

    # only the rows you have already checked by hand, so there is
    # something to score the answers against
    python3 watch.py subjects/prabhas-attribution.json --verified -n 5

Writes data/<id>_watched.csv
"""

import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
API = "https://generativelanguage.googleapis.com/v1beta/models"

# Where to look when sampling clips. Early enough to catch the lead, late
# enough that the opening titles are over. Same idea as scrubbing to 20, 50
# and 80 percent by hand - a lead actor appears at all three.
CLIP_POINTS = [0.20, 0.50, 0.80]
CLIP_SECONDS = 10

# DELIBERATELY DOES NOT NAME THE CLIENT.
#
# The first version opened with "CLIENT: Prabhas. The title claims this is a
# film featuring them", then asked whether he was in it. That is a leading
# question, and it produced exactly the failure you would predict: on a
# historical drama with no Prabhas in it, the model reported "wrong-film,
# this is Saaho" - confidently naming a specific film that was not there.
#
# So the model is now asked, blind, who it can see. We compare the answer to
# the client's name ourselves, afterwards, in code. A witness who has not been
# told which suspect to pick out is worth far more than one who has.
PROMPT = """You are shown three short clips from different points in one video,
taken roughly 20%, 50% and 80% of the way through. They are not continuous.

Report only what is visible or audible. Do not guess.

- Name a performer only if you actually recognise them. If you can see
  someone clearly but cannot name them, say so instead. "unnamed male lead,
  40s" is useful and honest - it tells us a lead exists and who it is not.
- Read any text on screen: title cards, credits, watermarks, channel logos,
  burned-in subtitles. Dubbed uploads often still carry the ORIGINAL title
  card, and that is frequently the only reliable clue to what the film is.
- Genre and period are not enough to identify a film. If you do not
  recognise it, say unclear. That is the right answer more often than not.

Return ONLY JSON:
{{
  "people_recognised": [
    {{"name": "who", "how_sure": "high|medium|low",
      "basis": "face|voice|credits|dialogue"}}
  ],
  "people_unrecognised": "e.g. two unnamed male leads and a female lead, or none",
  "onscreen_text": ["verbatim, any script"],
  "characters_named": ["character names spoken in dialogue"],
  "language": "language of the dialogue",
  "setting": "period and genre, a few words",
  "actual_film": "only if you genuinely recognise it, else unclear",
  "looks_ai_generated": "yes|no|unclear",
  "reason": "one sentence on what you based this on"
}}"""


# ---------------------------------------------------------------------------
# MODE 2: WHAT IS THIS, AND WHAT IS IT FOR
# ---------------------------------------------------------------------------
# The deepfake question, approached from the side that actually works.
#
# Reading titles could never separate "a deepfake of X" from "a news report
# about a deepfake of X", because both say deepfake and both say X. Looking at
# the picture settles it instantly: a news report is a studio, an anchor and
# talking heads. A deepfake is the person doing something. They look nothing
# alike. The confusion only ever existed in the words.
#
# Note what this deliberately does NOT lean on. Deepfake detection runs at
# 61-69% on real content and an LLM eyeballing frames is not obviously better.
# So "is it synthetic" is recorded as a signal, not used as the foundation.
#
# Severity rests on PURPOSE, which is reliably observable. A face selling a
# product without permission is the same harm whether the video was generated
# or cleverly edited - so the tool keeps working even when detection does not.

PURPOSE_PROMPT = """Describe what this video is and what it exists to do.

You are shown three short clips from different points in one video, taken
roughly 20%, 50% and 80% through. They are not continuous.

Report only what is visible or audible. Do not guess from genre or style.

Return ONLY JSON:
{{
  "people_recognised": [
    {{"name": "who", "how_sure": "high|medium|low", "basis": "face|voice|credits"}}
  ],
  "people_unrecognised": "e.g. one unnamed male lead, or none",

  "purpose": "one of: fan_tribute | fake_trailer | episodic_series |
              product_advertisement | news_or_commentary | music_video |
              real_footage | explicit_or_defamatory | unclear",

  "imagery_looks_generated": "yes|no|unclear",
  "generated_evidence": "what made you say that - warped hands, inconsistent
                         faces between shots, unnatural motion, watermark of a
                         generator, or none",

  "sells_something": "a product, brand, app or service being promoted that is
                      SEPARATE from this video itself. A film upload promoting
                      its own film is NOT selling something - say none. A
                      trading app, a supplement, a betting site, a sponsor
                      shown mid-video IS. This is about borrowed endorsement,
                      not self-promotion",
  "claims_to_be_official": "yes|no|unclear",
  "is_episodic": "yes if it presents as part of a numbered series, else no",
  "onscreen_text": ["verbatim, any script"],
  "language": "...",
  "reason": "one sentence"
}}"""


# Purpose decides severity. This is the client's-eye view, not a moderator's:
# most of what a star's face appears in is harmless, and advising them to
# attack their own fans is bad advice.
SEVERITY = {
    "explicit_or_defamatory": ("HIGHEST", "fastest legal route in India, 2 hours"),
    "product_advertisement":  ("HIGH", "endorsement abuse - the case with money behind it"),
    "episodic_series":        ("HIGH", "a business built on the face, with ad revenue"),
    "fake_trailer":           ("MEDIUM", "harmful mainly if it claims to be official"),
    "music_video":            ("MEDIUM", "depends on whether the voice is cloned"),
    "fan_tribute":            ("LOW", "usually free promotion. Leave it alone"),
    "real_footage":           ("NONE", "genuine material"),
    "news_or_commentary":     ("NONE", "reporting about a thing is not the thing"),
    "unclear":                ("UNKNOWN", "needs a human"),
}


def decide_purpose(seen, name, official=()):
    # A studio posting its own film is not a fake trailer. The first run
    # flagged Hombale Films - Prabhas's actual producer - for uploading a
    # Salaar scene, which is the kind of result that ends a sales meeting.
    import rules
    if official and rules.is_authorised(seen.get("_channel", ""), official):
        seen.update(verdict="official", severity="NONE",
                    basis="posted by an authorised channel",
                    actors_line="n/a", subject_seen="n/a")
        return seen
    return _decide_purpose(seen, name)


def _decide_purpose(seen, name):
    people = seen.get("people_recognised") or []
    named = [str(p.get("name", "")) if isinstance(p, dict) else str(p) for p in people]
    seen["actors_line"] = ", ".join(named) or f"unnamed: {seen.get('people_unrecognised','?')}"
    seen["subject_seen"] = "yes" if any(name.lower() in n.lower() for n in named) else "no"

    purpose = str(seen.get("purpose", "unclear")).strip().lower()
    severity, why = SEVERITY.get(purpose, ("UNKNOWN", "unrecognised purpose"))

    # Two things escalate whatever the purpose is.
    sells = str(seen.get("sells_something", "none")).strip().lower()
    if sells not in ("", "none", "nothing", "n/a") and severity in ("LOW", "MEDIUM"):
        severity, why = "HIGH", f"sells something: {sells[:40]}"
    if (str(seen.get("claims_to_be_official", "")).lower() == "yes"
            and severity not in ("HIGHEST", "UNKNOWN")):
        # An unclear purpose escalating to HIGH is just noise wearing a
        # confident label. Kannappa came back unclear and was promoted to HIGH
        # on this rule alone.
        severity, why = "HIGH", "presents itself as official - passing off"

    seen["severity"] = severity
    seen["basis"] = why
    seen["verdict"] = purpose
    return seen


def post(payload):
    url = f"{API}/{MODEL}:generateContent?key={KEY}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code}: {e.read().decode()[:300]}") from None


def parse(raw):
    """Models return a bare object sometimes and a one-element array other
    times, for the same prompt. Accept both."""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
    out = json.loads(raw.strip().removeprefix("json").strip())
    if isinstance(out, list):
        return out[0] if out else {}
    return out


MODE = "attribution"        # set from the command line
OFFICIAL = []               # official channels, for purpose mode


def ask(parts, name, item=None):
    prompt = PROMPT
    if MODE == "purpose":
        # Purpose mode DOES get the packaging, and deliberately so.
        #
        # Withholding the title was right for identity - a face should be
        # recognised, not inferred from a caption. But purpose is a CLAIM the
        # uploader makes, and the claim lives in the title, the channel name
        # and the description. Hiding it left the model guessing intent from
        # three frames of a fight scene.
        meta = ""
        if item:
            meta = (f"\nHow this video is presented to viewers:\n"
                    f"  Title: {item.get('title','')}\n"
                    f"  Channel: {item.get('channel_title','')}\n"
                    f"  Description: {(item.get('description') or '')[:600]}\n\n"
                    f"Judge the PURPOSE from how it is packaged and what the "
                    f"footage shows. Judge WHO APPEARS only from the footage - "
                    f"a name in a title is not evidence that the person is in "
                    f"the video.\n")
        prompt = PURPOSE_PROMPT + meta
    payload = {
        "contents": [{"role": "user", "parts": parts + [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    out = post(payload)
    text = out["candidates"][0]["content"]["parts"][0]["text"]
    tokens = out.get("usageMetadata", {}).get("totalTokenCount", 0)
    verdict = parse(text)
    if MODE == "attribution":
        verdict = decide(verdict, name)
    else:
        verdict["_channel"] = (item or {}).get("channel_title", "")
        verdict = decide_purpose(verdict, name, OFFICIAL)
    return verdict, tokens


def decide(seen, name):
    """WE draw the conclusion, from a blind description. Not the model.

    The model reports who it saw. Whether that includes our client is a string
    comparison, and a string comparison cannot be talked into agreeing with a
    title it was shown.

    Three situations that the first version collapsed into one:
      it named people, ours among them          -> present
      it named people, ours not among them      -> absent, and we can say why
      it named nobody but SAW unnamed leads     -> absent, weaker but real
      it saw nothing identifiable at all        -> unclear, we know nothing
    """
    people = seen.get("people_recognised") or []
    named = []
    for p in people:
        if isinstance(p, dict):
            named.append((str(p.get("name", "")), p.get("how_sure", "?")))
        else:
            named.append((str(p), "?"))

    unnamed = str(seen.get("people_unrecognised") or "").strip().lower()
    saw_someone = unnamed not in ("", "none", "no one", "nobody", "n/a")

    present = any(name.lower() in n.lower() for n, _ in named)

    if present:
        # attribution.py decides wrong-film from the filmography. Not the model.
        verdict, why = "present", "recognised in the footage"
    elif named:
        verdict, why = "absent", "identified other people, none of them ours"
    elif saw_someone:
        verdict, why = "absent", "saw leads it could not name, none recognisable as ours"
    else:
        verdict, why = "unclear", "recognised nobody at all"

    seen["verdict"] = verdict
    seen["basis"] = why
    seen["actors_line"] = (
        ", ".join(f"{n} ({s})" for n, s in named) or f"unnamed: {unnamed or 'none'}")
    return seen


# --- the three ways to ask ---------------------------------------------------

def by_transcript(item, name):
    words = item.get("transcript") or ""
    if not words:
        return {"verdict": "unclear", "reason": "no transcript available",
                "confidence": "low"}, 0
    # No title, no channel. The clips path is asked blind, so this one is too -
    # otherwise the two methods are not comparable and the cheaper one gets an
    # unfair advantage from a clue the expensive one never sees.
    context = f"Transcript of a video:\n{words[:12000]}"
    return ask([{"text": context}], name, item)


def by_clips(item, name):
    """Short windows of real video.

    Where we look depends on the question:

    IDENTITY - who is in this - wants the middle. Openings are titles and
    logos; the lead is on screen at 20, 50 and 80 percent.

    PURPOSE - what is this for - wants the OPENING. A trailer, an ad and an
    episode all announce themselves in the first fifteen seconds. Asking what
    a video is for from three windows in the middle of a film is asking the
    wrong part of the tape, and the first run duly returned nonsense.

    Offsets are also clamped now. With no recorded duration we assumed ten
    minutes and asked for a clip at 480 seconds, which does not exist in a
    30-second Short - ten of twenty calls failed with a server error for
    exactly that reason.
    """
    length = (item.get("duration_min") or 0) * 60

    if MODE == "purpose":
        points = [0.0, 0.45] if length else [0.0]
    else:
        points = CLIP_POINTS if length else [0.0]

    if not length:
        length = 60           # unknown: stay near the start, where it is safe

    parts, used = [], set()
    for point in points:
        start = max(0, int(length * point))
        # never ask for a window that runs past the end
        start = min(start, max(0, int(length) - CLIP_SECONDS))
        if start in used:
            continue
        used.add(start)
        parts.append({
            "file_data": {"file_uri": item["url"]},
            "video_metadata": {
                "start_offset": f"{start}s",
                "end_offset": f"{start + CLIP_SECONDS}s",
                "fps": 0.5,
            },
        })
    return ask(parts, name, item)


def by_full(item, name):
    """Everything. Included so the cost is measured rather than assumed."""
    return ask([{"file_data": {"file_uri": item["url"]}}], name, item)


METHODS = {"transcript": by_transcript, "clips": by_clips, "full": by_full}


def main():
    if not KEY:
        sys.exit("Set GEMINI_API_KEY first.")
    args = sys.argv[1:]
    if not args:
        sys.exit("Usage: python3 watch.py subjects/<file>.json "
                 "[--methods transcript,clips,full] [-n 5] [--verified]")

    global MODE
    subject_path = args[0]
    methods = ["clips"]
    limit, verified_only = 5, False
    for i, a in enumerate(args):
        if a == "--methods":
            methods = args[i + 1].split(",")
        elif a == "-n":
            limit = int(args[i + 1])
        elif a == "--verified":
            verified_only = True
        elif a == "--mode":
            MODE = args[i + 1]

    subject = json.load(open(subject_path))
    name = subject["name"]
    global OFFICIAL
    OFFICIAL = subject.get("official_channels", [])

    items = {i["id"]: i for i in
             (json.loads(l) for l in open(f"data/{subject['id']}_items.jsonl")
              if l.strip())}

    if MODE == "attribution":
        attribution = f"data/{subject['id']}_attribution.csv"
        if not os.path.exists(attribution):
            sys.exit(f"No {attribution}. Run attribution.py first.")
        rows = [r for r in csv.DictReader(open(attribution, encoding="utf-8",
                                               errors="replace"))
                if r["verdict"] == "UNSUPPORTED"]
        if verified_only:
            rows = [r for r in rows if (r.get("checked_by_hand") or "").strip()]
            if not rows:
                sys.exit("No hand-checked rows to compare against.")
    else:
        # Purpose mode looks at everything about the subject, not just film
        # claims. Deliberately includes items the metadata thought were
        # harmless - if watching only ever confirms the keywords, watching is
        # not adding anything and we should know that.
        needles = [name.lower()] + [a.lower() for a in subject.get("aliases", [])]
        pool = [i for i in items.values()
                if any(n in (i.get("title", "") + " " +
                             (i.get("description") or "")).lower() for n in needles)]

        # Watch what the cheap layer already suspects, not what is popular.
        #
        # The first purpose run sorted by views and watched the top 20 - which
        # for any star is official music videos and big movie uploads. AI slop
        # has low view counts; on the Arijit set the median AI hit had 349
        # views. We sorted for the exact opposite of what we were looking for.
        flagged = f"data/{subject['id']}_classified.jsonl"
        if os.path.exists(flagged) and "--by-views" not in args:
            suspect = set()
            for line in open(flagged, encoding="utf-8"):
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("llm", {}).get("ai_likeness") == "yes":
                    suspect.add(rec["id"])
            if suspect:
                narrowed = [i for i in pool if i["id"] in suspect]
                print(f"{len(suspect)} items were flagged as AI by the cheap layer; "
                      f"watching those, not the most-viewed\n")
                pool = narrowed or pool

        import rules as _rules
        counts = _rules.channel_tally(pool)
        pool.sort(key=lambda i: -_rules.priority(i, OFFICIAL, counts))
        rows = [{"title": i.get("title", ""), "url": i.get("url", ""),
                 "views": i.get("views", 0), "channel_title": i.get("channel_title", ""),
                 "checked_by_hand": "", "_ordered": True}
                for i in pool]

    if not (rows and rows[0].get("_ordered")):
        rows.sort(key=lambda r: -int(str(r["views"]).replace(",", "")))
    rows = rows[:limit]

    print(f"{len(rows)} videos x {len(methods)} methods "
          f"= {len(rows) * len(methods)} calls to {MODEL}\n")

    results = []
    for n, row in enumerate(rows, 1):
        vid = row["url"].split("v=")[-1]
        item = items.get(vid)
        if not item:
            continue
        print(f"{n}. {row['title'][:58]}")
        if row.get("checked_by_hand"):
            print(f"   you said: {row['checked_by_hand']}")

        out = {"title": row["title"], "url": row["url"],
               "views": row.get("views", 0),
               "channel_title": row.get("channel_title", ""),
               "yours": row.get("checked_by_hand", "")}

        for method in methods:
            try:
                verdict, tokens = METHODS[method](item, name)
            except Exception as e:
                # Never let one bad video end the run. Losing nine results
                # because the tenth returned odd JSON is not acceptable when
                # each one costs a call.
                print(f"   {method:<11} FAILED  {type(e).__name__}: {str(e)[:80]}")
                out[method] = "failed"
                out[f"{method}_tokens"] = 0
                continue
            out[method] = verdict.get("verdict", "?")
            out[f"{method}_film"] = verdict.get("actual_film", "")
            out[f"{method}_tokens"] = tokens
            if MODE == "purpose":
                for k in ("severity", "subject_seen", "imagery_looks_generated",
                          "sells_something", "claims_to_be_official",
                          "is_episodic", "actors_line", "basis"):
                    out[k] = verdict.get(k, "")
                out["verdict"] = verdict.get("verdict", "?")
            agree = ("=" if out[method].lower() == (out["yours"] or "").lower()
                     else "x" if out["yours"] else " ")
            print(f"   {method:<11} {out[method]:<12} {tokens:>8,} tokens  {agree}")
            if MODE == "purpose":
                print(f"      {verdict.get('severity','?'):<8} {verdict.get('basis','')[:54]}")
                print(f"      saw:  {verdict.get('actors_line','?')[:60]}")
                gen = verdict.get('imagery_looks_generated', '?')
                print(f"      generated: {gen}  ({str(verdict.get('generated_evidence',''))[:44]})")
                sells = verdict.get('sells_something', 'none')
                if str(sells).lower() not in ('none', 'nothing', '', 'n/a'):
                    print(f"      SELLS: {sells}")
                continue
            print(f"      saw:  {verdict.get('actors_line','?')[:62]}")
            print(f"      why:  {verdict.get('basis','')}")
            print(f"      film: {str(verdict.get('actual_film','?'))[:44]}  "
                  f"({str(verdict.get('setting',''))[:30]})")
            text = verdict.get('onscreen_text') or []
            if text:
                print(f"      text: {' | '.join(str(t) for t in text)[:62]}")
            time.sleep(2)

        results.append(out)
        print()

    if MODE == "purpose":
        cols = ["severity", "verdict", "subject_seen", "imagery_looks_generated",
                "sells_something", "claims_to_be_official", "is_episodic",
                "actors_line", "basis", "views", "channel_title", "title",
                "url", "clips_tokens"]
    else:
        cols = ["title", "url", "yours"]
        for m in methods:
            cols += [m, f"{m}_film", f"{m}_tokens"]
    out_path = f"data/{subject['id']}_watched.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)

    print("=" * 66)
    if MODE == "purpose":
        # ROLL UP TO THE CHANNEL.
        #
        # One AI web series produced three different verdicts across three of
        # its own episodes - fan_tribute LOW, episodic_series HIGH, and
        # fake_trailer MEDIUM. Judging uploads independently lets an operation
        # hide behind its mildest video.
        #
        # Same lesson as incidents-not-items and offenders-not-incidents. It
        # keeps recurring because the channel is the unit that matters: a
        # lawyer writes to a person, and YouTube strikes accrue to accounts.
        ops = {}
        for r in results:
            ch = r.get("channel_title", "")
            if not ch:
                continue
            o = ops.setdefault(ch, {"rows": [], "gen": 0, "views": 0})
            o["rows"].append(r)
            o["views"] += int(str(r.get("views", 0)).replace(",", ""))
            if r.get("imagery_looks_generated") == "yes":
                o["gen"] += 1

        rank = ["HIGHEST", "HIGH", "MEDIUM", "LOW", "NONE", "UNKNOWN"]
        operations = []
        for ch, o in ops.items():
            if len(o["rows"]) < 2 or o["gen"] < 2:
                continue
            worst = min((r.get("severity", "UNKNOWN") for r in o["rows"]),
                        key=lambda s: rank.index(s) if s in rank else 9)
            # Repeat fake trailers are an operation. Repeat comedy is a fan
            # with a hobby. The first version promoted anything prolific, and
            # duly lifted a fan comedy channel with 377k views to HIGH - which
            # is exactly the advice a star should never be given.
            #
            # So MEDIUM lifts to HIGH, LOW stays LOW. If every single upload
            # reads as harmless, the channel is harmless however many there are.
            promoted = "HIGH" if worst == "MEDIUM" else worst
            operations.append((ch, len(o["rows"]), o["gen"], o["views"],
                               worst, promoted))
            for r in o["rows"]:
                r["severity"] = promoted
                r["basis"] = f"{o['gen']} generated uploads from this channel"

        if operations:
            print("\n  OPERATIONS - channels with several generated uploads:")
            for ch, n, gen, views, worst, promoted in sorted(
                    operations, key=lambda x: -x[2]):
                print(f"    {ch[:26]:<26} {gen}/{n} generated  "
                      f"{views:>9,} views   {worst} -> {promoted}")
            print()

        order = ["HIGHEST", "HIGH", "MEDIUM", "LOW", "NONE", "UNKNOWN"]
        counts = {}
        for r in results:
            counts.setdefault(r.get("severity", "?"), []).append(r)
        for sev in order:
            got = counts.get(sev, [])
            if got:
                views = sum(int(str(r.get("views", 0)).replace(",", "")) for r in got)
                print(f"  {sev:<8} {len(got):>3} videos  {views:>12,} views")
        tok = sum(r.get("clips_tokens", 0) for r in results)
        print(f"\n  {tok:,} tokens total ({tok // max(len(results),1):,} each)")
        gen = sum(1 for r in results if r.get("imagery_looks_generated") == "yes")
        print(f"  {gen} of {len(results)} judged to look generated")
        sells = [r for r in results
                 if str(r.get("sells_something", "none")).lower()
                 not in ("none", "nothing", "", "n/a")]
        if sells:
            print(f"\n  {len(sells)} are selling something:")
            for r in sells[:8]:
                print(f"     {r['sells_something'][:40]:<40} {r['title'][:34]}")
        print(f"\nwrote {out_path}")
        return
    for m in methods:
        tok = sum(r.get(f"{m}_tokens", 0) for r in results)
        scored = [r for r in results if r.get("yours")]
        hits = sum(1 for r in scored
                   if str(r.get(m, "")).lower() == r["yours"].lower())
        acc = f"{hits}/{len(scored)} agree with you" if scored else "not scored"
        per = tok // max(len(results), 1)
        print(f"  {m:<11} {tok:>10,} tokens total  ({per:,} each)   {acc}")

    print(f"\nwrote {out_path}")
    print("\nIf transcript agrees as often as clips, we never send video and")
    print("this scales to thousands. If it does not, the gap is what the")
    print("video is actually buying - and now you know the price of it.")


if __name__ == "__main__":
    main()
