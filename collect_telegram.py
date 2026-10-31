"""
Pull Telegram public-channel results for one person into a file.

Why Telegram: the first YouTube run collected 599 videos about a woman who had
just been publicly deepfaked, and found zero pieces of harmful content. Every
single hit was news coverage. YouTube's moderation had already removed the rest.
Telegram is barely moderated, which is exactly why the harmful content survives
there - and why it's a real test of the judging.

Output is the SAME shape as collect.py, so judge.py needs no changes. That's
deliberate: sources are plumbing, the judging is the product.

Setup (one time):
    pip3 install telethon
    Go to my.telegram.org -> API development tools -> create an app
    It gives you an api_id (a number) and an api_hash (a long string)

    export TELEGRAM_API_ID=1234567
    export TELEGRAM_API_HASH=abcdef...

Usage:
    python3 collect_telegram.py subjects/mrunal-thakur.json

First run asks for your phone number and a login code. After that it remembers
you in a local .session file (which is gitignored - it is a credential).

Writes: data/<subject_id>_telegram_items.jsonl
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

try:
    from telethon.sync import TelegramClient
    from telethon.tl.functions.messages import SearchGlobalRequest
    from telethon.tl.types import InputMessagesFilterEmpty, InputPeerEmpty
except ImportError:
    sys.exit("Telethon not installed. Run:  pip3 install telethon")

API_ID = os.environ.get("TELEGRAM_API_ID", "")
API_HASH = os.environ.get("TELEGRAM_API_HASH", "")

PAGES = 4          # each page returns up to 100 messages
PER_PAGE = 100


def to_item(msg, chat_title, chat_id):
    """Reshape a Telegram message into the same record collect.py produces."""
    text = (msg.message or "").strip()
    if not text:
        return None

    # Telegram has no titles. Use the first line, which is how channels write.
    first_line = text.split("\n")[0][:200]

    published = msg.date.astimezone(timezone.utc)
    age_hours = (datetime.now(timezone.utc) - published).total_seconds() / 3600

    reactions = 0
    if getattr(msg, "reactions", None) and msg.reactions.results:
        reactions = sum(r.count for r in msg.reactions.results)

    username = getattr(getattr(msg, "chat", None), "username", None)
    url = f"https://t.me/{username}/{msg.id}" if username else f"telegram://{chat_id}/{msg.id}"

    return {
        "id": f"tg{chat_id}_{msg.id}",
        "url": url,
        "platform": "telegram",
        "title": first_line,
        "description": text[:1000],
        "channel_title": chat_title or "unknown channel",
        "channel_id": str(chat_id),
        "thumbnail": "",
        "published": published.isoformat(),
        "date": published.strftime("%Y-%m-%d"),
        "age_hours": round(max(age_hours, 1), 1),
        "views": int(getattr(msg, "views", 0) or 0),
        "likes": reactions,
        "comments": int(getattr(getattr(msg, "replies", None), "replies", 0) or 0),
    }


def search(client, term, since=None):
    """Search every public channel Telegram will let us see.

    Note on dates: the first version passed min_date into the request and got
    zero results for every single term, including a bare first name that must
    have thousands of matches. Telegram's date bounds on global search are
    unreliable, so the filtering now happens here in Python instead. Slower,
    but it actually returns things.
    """
    found, offset_rate, offset_id = [], 0, 0

    for _ in range(PAGES):
        result = client(SearchGlobalRequest(
            q=term,
            filter=InputMessagesFilterEmpty(),
            min_date=None,
            max_date=None,
            offset_rate=offset_rate,
            offset_peer=InputPeerEmpty(),
            offset_id=offset_id,
            limit=PER_PAGE,
        ))

        chats = {c.id: getattr(c, "title", None) for c in result.chats}
        if not result.messages:
            break

        for msg in result.messages:
            peer = getattr(msg, "peer_id", None)
            cid = getattr(peer, "channel_id", None) or getattr(peer, "chat_id", None) or 0
            item = to_item(msg, chats.get(cid), cid)
            if not item:
                continue
            if since and msg.date < since:
                continue          # filtered here, not in the request
            found.append(item)

        offset_rate = getattr(result, "next_rate", 0) or 0
        offset_id = result.messages[-1].id
        if len(result.messages) < PER_PAGE:
            break

    return found


def read_channel(client, username, terms, since):
    """Read one named public channel directly.

    This is the mode that actually works. Telegram's "global" search only
    covers channels your account can already reach - the self-test returned
    job boards and a travel group, because that is what this account had
    joined. Naming a channel bypasses that entirely, and works for public
    channels without joining them.

    Which is the real lesson: on Telegram you cannot discover, only monitor.
    You learn the channel from the victim, then you watch it.
    """
    found = []
    try:
        entity = client.get_entity(username)
    except Exception as e:
        print(f"  {username}: cannot open - {e}")
        return found

    title = getattr(entity, "title", username)
    cid = getattr(entity, "id", 0)

    for term in terms:
        try:
            for msg in client.iter_messages(entity, search=term, limit=200):
                if since and msg.date < since:
                    break            # messages arrive newest first
                item = to_item(msg, title, cid)
                if item:
                    found.append(item)
        except Exception as e:
            print(f"  {username} / '{term}': {e}")
    return found


def selftest():
    """Prove the plumbing works before blaming the data.

    Searches for words that must exist on Telegram. If these come back empty,
    global search is not available to this account and no subject file will
    ever return anything.
    """
    with TelegramClient("telegram.session", int(API_ID), API_HASH) as client:
        for term in ["india", "news", "bollywood"]:
            try:
                hits = search(client, term)
                print(f"  '{term}': {len(hits)} messages")
                if hits:
                    print(f"     e.g. [{hits[0]['channel_title']}] "
                          f"{hits[0]['title'][:60]}")
            except Exception as e:
                print(f"  '{term}': FAILED - {e}")
    print("\nIf all three are 0, global search is not working for this account.")
    print("Telegram restricts it, and new or sparsely-used accounts often get")
    print("nothing back. The fallback is to name specific public channels.")


def main():
    if not API_ID or not API_HASH:
        sys.exit("Set TELEGRAM_API_ID and TELEGRAM_API_HASH first. "
                 "Get them free at my.telegram.org")
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 collect_telegram.py subjects/<file>.json\n"
                 "       python3 collect_telegram.py --selftest")

    if sys.argv[1] == "--selftest":
        selftest()
        return

    subject = json.load(open(sys.argv[1]))
    since = datetime.now(timezone.utc) - timedelta(days=subject.get("lookback_days", 30))

    all_items = {}
    channels = subject.get("telegram_channels", [])

    with TelegramClient("telegram.session", int(API_ID), API_HASH) as client:
        # Search the aliases too - Telegram content is heavily non-English and
        # the native-script spelling often finds what the Latin one misses.
        terms = subject["search_terms"] + subject.get("aliases", [])

        # Named channels first. This is the mode that actually returns things.
        for username in channels:
            print(f"reading channel: {username}")
            hits = read_channel(client, username, terms, since)
            print(f"  {len(hits)} messages")
            for item in hits:
                all_items[item["id"]] = item

        # Then the account-wide search, which only covers what this account
        # can already reach. Kept because it costs nothing and occasionally
        # surfaces a channel worth adding to the list above.
        for term in terms:
            print(f"searching own reach: {term}")
            try:
                hits = search(client, term, since)
            except Exception as e:
                print(f"  failed: {e}")
                continue
            print(f"  {len(hits)} messages")
            for item in hits:
                all_items[item["id"]] = item

    items = list(all_items.values())
    os.makedirs("data", exist_ok=True)
    out = f"data/{subject['id']}_telegram_items.jsonl"
    with open(out, "w") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"\nwrote {len(items)} unique messages to {out}")
    print(f"\nTo judge these instead of the YouTube set:")
    print(f"  cp {out} data/{subject['id']}_items.jsonl")
    print(f"  python3 judge.py {sys.argv[1]}")


if __name__ == "__main__":
    main()
