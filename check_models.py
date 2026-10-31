"""
Find out which Gemini models your key can actually call for free.

The list endpoint shows everything that exists, not everything you are allowed
to use. A model can be listed and still return "limit: 0", meaning your project
has no free allocation for it. The only way to know is to try.

Sends a two-token request to each candidate. Costs nothing where it works, and
fails instantly where it does not.

Usage:
    export GEMINI_API_KEY=...
    python3 check_models.py
"""

import json
import os
import sys
import urllib.error
import urllib.request

KEY = os.environ.get("GEMINI_API_KEY", "")

# Cheapest first. The lite variants are the ones that usually carry free quota.
CANDIDATES = [
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
]


def probe(model):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={KEY}")
    payload = {
        "contents": [{"role": "user", "parts": [{"text": "reply with: ok"}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 5},
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            json.loads(r.read().decode())
        return True, "works"
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if e.code == 429:
            return False, ("no free quota" if '"limit": 0' in body
                           else "rate limited - has quota, just busy")
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)[:60]


def main():
    if not KEY:
        sys.exit("Set GEMINI_API_KEY first.")

    usable = []
    for model in CANDIDATES:
        ok, note = probe(model)
        print(f"  {'OK  ' if ok else 'no  '} {model:<28} {note}")
        if ok:
            usable.append(model)

    print()
    if usable:
        print(f"Use this:  export GEMINI_MODEL={usable[0]}")
    else:
        print("None of them will run for free on this key.")
        print("Either enable billing on the Google project - your call, your")
        print("money - or switch to a local model:")
        print("  brew install ollama && ollama pull llama3.1")
        print("  export PROVIDER=ollama")


if __name__ == "__main__":
    main()
