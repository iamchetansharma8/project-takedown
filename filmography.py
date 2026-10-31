"""
Pull a person's real filmography from TMDb, instead of me writing it from memory.

Every film I forget becomes a false accusation, and every runtime I misremember
becomes a wrong one. That is the worst failure this tool has, and it was being
caused entirely by using me as the database.

TMDb gives three things that fix it:
  - the complete acting credits for a person, kept current by its community
  - the runtime of each film
  - ALTERNATIVE TITLES, which is the real prize. A Hindi dub released under a
    different name was previously flagged as a false attribution, because our
    list only held the original title. Now both names are known.

Setup:
    Sign up at themoviedb.org, then Settings -> API -> request a key. Free.
    export TMDB_API_KEY=...

Usage:
    python3 filmography.py "Prabhas" subjects/prabhas-attribution.json

Rewrites known_films and runtimes in the subject file, and leaves everything
else in it untouched.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.themoviedb.org/3"
KEY = os.environ.get("TMDB_API_KEY", "")

# Which languages of alternative title to keep. A Hindi dub is the case that
# was breaking the check, so Hindi first, then the southern languages.
KEEP_TITLE_LANGS = {"IN", "US", "GB"}


def get(path, tries=4, **params):
    """Retry with backoff.

    The first run silently lost 28 of 36 credits - so Salaar, Saaho, Mirchi
    and Adipurush were simply absent from the filmography, and every video
    naming them would have been reported as a false attribution.

    An ISP that resets TMDb connections intermittently guarantees some calls
    fail. Losing them quietly is far worse here than being slow, because a
    missing film is exactly what turns this tool into an accusation machine.
    """
    params["api_key"] = KEY
    url = f"{API}{path}?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


# ---------------------------------------------------------------------------
# WIKIDATA - the fallback, and arguably the one to prefer
# ---------------------------------------------------------------------------
# TMDb is blocked by several Indian ISPs, Jio and Airtel in particular. It has
# been on and off for years and TMDb's own forums are full of it. The symptom
# is a TLS connection reset, which looks like a broken key but is not.
#
# A product built for India cannot depend on a service Indian ISPs block. So:
# Wikidata. No key, no rate limit worth worrying about, not blocked, and its
# "also known as" labels carry dubbed and regional titles - which is the same
# thing we wanted TMDb's alternative titles for.
#
# Coverage of smaller Indian films is thinner than TMDb's. That trades a miss
# for a false accusation, which is the right way round.

WD_SEARCH = "https://www.wikidata.org/w/api.php"
WD_SPARQL = "https://query.wikidata.org/sparql"
UA = "project-takedown/0.1 (research prototype)"


def wd_request(url, params):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params))
    req.add_header("User-Agent", UA)      # Wikidata rejects requests without one
    req.add_header("Accept", "application/sparql-results+json")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def wd_find_person(name):
    out = wd_request(WD_SEARCH, {
        "action": "wbsearchentities", "search": name, "language": "en",
        "type": "item", "format": "json", "limit": 5,
    })
    for hit in out.get("search", []):
        desc = (hit.get("description") or "").lower()
        if any(w in desc for w in ("actor", "actress", "film", "singer", "cricket")):
            return hit["id"], hit.get("label", name), hit.get("description", "")
    if out.get("search"):
        h = out["search"][0]
        return h["id"], h.get("label", name), h.get("description", "")
    return None, None, None


def wd_filmography(qid):
    """Films where this person is cast member (P161), with duration (P2047)
    and every alternative label the item carries."""
    query = f"""
    SELECT ?film ?filmLabel ?duration ?alt WHERE {{
      ?film wdt:P161 wd:{qid} .
      OPTIONAL {{ ?film wdt:P2047 ?duration . }}
      OPTIONAL {{ ?film skos:altLabel ?alt . FILTER(lang(?alt) IN ("en","hi","te","ta")) }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }}
    """
    out = wd_request(WD_SPARQL, {"query": query, "format": "json"})

    films, runtimes = [], {}
    for row in out.get("results", {}).get("bindings", []):
        names = set()
        if "filmLabel" in row:
            names.add(row["filmLabel"]["value"])
        if "alt" in row:
            names.add(row["alt"]["value"])
        try:
            minutes = round(float(row["duration"]["value"])) if "duration" in row else 0
        except Exception:
            minutes = 0
        for t in names:
            t = t.strip()
            if len(t) > 2 and not t.startswith("Q"):
                if t not in films:
                    films.append(t)
                if minutes:
                    runtimes[t] = minutes
    return films, runtimes


def find_person(name):
    results = get("/search/person", query=name).get("results", [])
    if not results:
        return None
    # Most known-for credits wins, which handles common names reasonably well.
    best = max(results, key=lambda p: len(p.get("known_for", [])))
    return best


def main():
    if len(sys.argv) < 3:
        sys.exit('Usage: python3 filmography.py "Person Name" subjects/<file>.json\n'
                 '       add --wikidata to skip TMDb entirely (no key needed)')

    name, subject_path = sys.argv[1], sys.argv[2]
    forced = "--wikidata" in sys.argv

    if not forced and KEY:
        try:
            return run_tmdb(name, subject_path)
        except (urllib.error.URLError, ConnectionResetError, OSError) as e:
            print(f"TMDb unreachable ({e})")
            print("This is almost certainly your ISP - Jio and Airtel block")
            print("TMDb intermittently. Falling back to Wikidata.\n")

    run_wikidata(name, subject_path)


def run_wikidata(name, subject_path):
    qid, label, desc = wd_find_person(name)
    if not qid:
        sys.exit(f"Wikidata has nobody called {name}")
    print(f"found: {label} ({qid}) - {desc}")

    films, runtimes = wd_filmography(qid)
    if not films:
        sys.exit("No films found. Check the name, or the person may be listed "
                 "under a different spelling on Wikidata.")

    save(subject_path, films, runtimes,
         f"Wikidata {qid}, pulled {time.strftime('%Y-%m-%d')}. "
         f"Includes alternative labels. Re-run filmography.py to refresh.")


def save(subject_path, films, runtimes, source, unreleased=()):
    subject = json.load(open(subject_path))
    subject["known_films"] = sorted(set(films))
    subject["runtimes"] = dict(sorted(runtimes.items()))
    if unreleased:
        subject["unreleased_films"] = sorted(set(unreleased))
    subject["_films_source"] = source
    subject.pop("_comment_known_films", None)
    subject.pop("_comment_runtimes", None)
    with open(subject_path, "w") as f:
        json.dump(subject, f, indent=2, ensure_ascii=False)

    print(f"\n{len(set(films))} titles, {len(runtimes)} with runtimes")
    print(f"updated {subject_path}")
    print("\nSkim the list before trusting a number that comes out of it.")
    print("A film missing here becomes a false accusation.")


def run_tmdb(name, subject_path):
    person = find_person(name)
    if not person:
        sys.exit(f"TMDb has nobody called {name}")

    print(f"found: {person['name']}  (tmdb id {person['id']})")
    for p in person.get("known_for", [])[:3]:
        print(f"  known for: {p.get('title') or p.get('name')}")

    credits = get(f"/person/{person['id']}/movie_credits")
    cast = credits.get("cast", [])
    print(f"\n{len(cast)} acting credits")

    films, runtimes, missing, unreleased = [], {}, [], []

    for n, role in enumerate(cast, 1):
        movie_id = role["id"]
        try:
            details = get(f"/movie/{movie_id}")
            alts = get(f"/movie/{movie_id}/alternative_titles")
        except Exception as e:
            # Name it. A silently dropped film becomes a false accusation.
            missing.append(role.get("title") or role.get("original_title") or movie_id)
            continue

        title = details.get("title") or ""
        original = details.get("original_title") or ""
        runtime = details.get("runtime") or 0
        released = details.get("release_date") or ""
        status = details.get("status") or ""

        names = {title, original}
        for alt in alts.get("titles", []):
            if alt.get("iso_3166_1") in KEEP_TITLE_LANGS and alt.get("title"):
                names.add(alt["title"])

        # An announced but unreleased film is the interesting case. A fake
        # first look for it lands inside the studio's real marketing window
        # and misleads the audience that is actually waiting for it - which
        # is a harm a producer recognises without needing it explained.
        upcoming = status in ("Planned", "In Production", "Post Production") or (
            released > time.strftime("%Y-%m-%d") if released else False)

        for t in names:
            t = t.strip()
            if len(t) > 2 and t not in films:
                films.append(t)
                if runtime:
                    runtimes[t] = runtime
                if upcoming:
                    unreleased.append(t)

        if n % 15 == 0:
            print(f"  {n}/{len(cast)}...")
        time.sleep(0.12)

    if missing:
        print(f"\n⚠️  {len(missing)} of {len(cast)} credits could NOT be fetched:")
        for t in missing:
            print(f"     {t}")
        print("\n  These films are absent from the list, so any video naming")
        print("  them will be reported as a false attribution. Re-run until")
        print("  this is empty, or add them to known_films by hand.")

    if unreleased:
        print(f"\n{len(set(unreleased))} titles are announced but not yet released:")
        for t in sorted(set(unreleased))[:12]:
            print(f"     {t}")
        print("  A fake trailer for one of these pre-empts a real campaign.")

    save(subject_path, films, runtimes,
         f"TMDb person {person['id']}, pulled {time.strftime('%Y-%m-%d')}. "
         f"Includes alternative and dubbed titles."
         + (f" INCOMPLETE - {len(missing)} credits failed to fetch." if missing else ""),
         unreleased)


if __name__ == "__main__":
    main()
