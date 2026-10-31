"""
One thin adapter per model provider. Nothing else in the project should know
which one is in use.

The point is not portability for its own sake. It is that the model will be
replaced - by a cheaper one, a better one, or a local one once real client data
is involved and it stops being acceptable to send it to a third party.

Set PROVIDER to choose: gemini (default), anthropic, openai, ollama.

    export PROVIDER=gemini
    export GEMINI_API_KEY=...          # free tier: aistudio.google.com/apikey

No SDKs. Plain HTTP through the standard library, so there is nothing to
install and nothing to keep up to date.
"""

import json
import os
import urllib.error
import urllib.request

PROVIDER = os.environ.get("PROVIDER", "gemini").lower()


def _post(url, payload, headers=None):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code}: {e.read().decode()[:400]}") from None


# ---------------------------------------------------------------------------

def _gemini(system, user):
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY. Free key: aistudio.google.com/apikey")

    # Model names move around. If this one 404s, list what your key can see at
    # https://generativelanguage.googleapis.com/v1beta/models?key=YOUR_KEY
    # and set GEMINI_MODEL to one of them.
    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")

    out = _post(url, {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": 0,          # judgements should not vary run to run
            "responseMimeType": "application/json",
        },
    })
    return out["candidates"][0]["content"]["parts"][0]["text"]


def _anthropic(system, user):
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("Set ANTHROPIC_API_KEY")
    out = _post(
        "https://api.anthropic.com/v1/messages",
        {
            "model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
            "max_tokens": 8000,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        {"x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    return out["content"][0]["text"]


def _openai(system, user):
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("Set OPENAI_API_KEY")
    out = _post(
        "https://api.openai.com/v1/chat/completions",
        {
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        {"Authorization": f"Bearer {key}"},
    )
    return out["choices"][0]["message"]["content"]


def _ollama(system, user):
    """Local. Nothing leaves the machine - which is what you will want the day
    this touches a real client's data."""
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    out = _post(f"{host}/api/chat", {
        "model": os.environ.get("OLLAMA_MODEL", "llama3.1"),
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    })
    return out["message"]["content"]


BACKENDS = {
    "gemini": _gemini,
    "anthropic": _anthropic,
    "openai": _openai,
    "ollama": _ollama,
}


def complete(system, user):
    if PROVIDER not in BACKENDS:
        raise RuntimeError(f"Unknown PROVIDER '{PROVIDER}'. "
                           f"Choose one of: {', '.join(BACKENDS)}")
    return BACKENDS[PROVIDER](system, user)


def parse_json(raw):
    """Models wrap JSON in markdown fences no matter what you ask."""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()
    if raw.startswith("json"):
        raw = raw[4:].strip()
    return json.loads(raw)
