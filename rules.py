"""
THE JUDGING RULES — this is the thing we are testing.
Everything else in this folder exists to feed this file.

Three questions, in order:
  1. How bad is this content on its own?          -> content_harm()
  2. How bad is it for THIS person, RIGHT NOW?    -> context_multiplier()
  3. Can we do anything, and would trying backfire? -> removability(), action_risk()

Edit the word lists and numbers freely. That is the point.

IMPORTANT: decide what you think a rule should be BEFORE you look at the
results it produces. Otherwise you will tune this until it agrees with you
and learn nothing.
"""

import re


# ---------------------------------------------------------------------------
# 1. HOW BAD IS THE CONTENT ON ITS OWN
# ---------------------------------------------------------------------------
# Four kinds of damage, because each needs a different fix.
# Each entry: word or phrase -> how strongly it indicates that kind of damage.
# Words are matched against the lowercased title + description.
# Romanised Hindi is included deliberately: attacks arrive as "paisa" not "पैसा",
# and no foreign tool looks for that.

MONEY_HARM = {
    # investment / endorsement fraud — the documented Indian attack pattern
    "investment": 3, "trading": 3, "guaranteed return": 5, "guaranteed profit": 5,
    "double your money": 5, "paisa double": 5, "profit": 2, "earn daily": 4,
    "crypto": 2, "bitcoin": 2, "stock tip": 4, "share market tip": 4,
    "join telegram": 3, "join whatsapp": 3, "limited seats": 3, "free demat": 3,
    "loan": 2, "lottery": 4, "giveaway": 2, "recommends": 2, "endorsed by": 2,
    "kamao": 4, "kamai": 3, "paise kamaye": 5, "nivesh": 3, "muft": 2,
}

SAFETY_HARM = {
    "home address": 5, "house address": 5, "lives at": 4, "residence": 3,
    "school": 3, "daily routine": 4, "car number": 4,
    "location revealed": 5, "ghar ka pata": 5, "house tour": 3,
    # "spotted at", "flight" and "airport" were here and had to come out.
    # They fired on ordinary paparazzi and dating-gossip videos, which is not
    # a safety problem. Real location exposure names a place you can go to.
}

# Dating rumours, paparazzi sightings and relationship gossip. Unpleasant,
# occasionally untrue, but not something you take to a platform or a court.
# These pull the score down so they stop crowding out real problems.
GOSSIP_SIGNALS = {
    "spotted": -3, "spotted together": -4, "dating": -3, "girlfriend": -3,
    "boyfriend": -3, "rumour": -2, "rumor": -2, "link up": -3, "linkup": -3,
    "relationship": -2, "wedding rumour": -3, "romance": -2, "affair": -2,
}

DIGNITY_HARM = {
    # sexual / morphed imagery and caste-communal abuse.
    # NOTE: this list is deliberately thin. It needs an Indian-language
    # expansion before it means anything. Treat low scores here as
    # "we did not look", not "nothing was found".
    "nude": 8, "nudes": 8, "obscene": 6, "mms": 7, "leaked video": 6,
    "leaked photo": 6, "morphed": 7, "private video": 6, "bikini": 2,
    "viral video": 2, "bedroom": 3, "hot video": 3,
    "caste": 4, "casteist": 6, "communal": 4, "jihad": 5, "anti national": 4,
    "deshdrohi": 5,
}

BUSINESS_HARM = {
    "fraud": 4, "scam": 4, "cheated": 4, "arrested": 4, "case filed": 3,
    "fir": 3, "raid": 4, "ed notice": 4, "income tax raid": 4, "exposed": 3,
    "black money": 4, "banned": 3, "controversy": 2, "dhokha": 4, "ghotala": 4,
    # the polite words the press actually uses - added after the sample data
    # showed real news coverage scoring zero
    "allegation": 4, "allegations": 4, "scrutiny": 3, "probe": 4, "summoned": 4,
    "accused": 4, "lawsuit": 3, "defamation": 3, "complaint": 2, "questioned": 3,
    "under investigation": 4, "notice issued": 3, "tax notice": 4,
}

# ---------------------------------------------------------------------------
# 5th axis: UNAUTHORISED LIKENESS USE
# ---------------------------------------------------------------------------
# Different problem from the four above, and the one YouTube is actually full
# of. Nobody gets hurt exactly - somebody is using a performer's voice or face
# without permission, usually to make money.
#
# It suits a title-based system unusually well, because this content ADVERTISES
# ITSELF. The uploader wants to be found, so they write "AI cover" in the title.
# Scam deepfakes hide; likeness exploitation markets itself.
#
# The legal test comes from Arijit Singh v. Codible Ventures (Bombay HC,
# 26 July 2024), India's first AI voice-cloning ruling. The court protected his
# voice, vocal style, technique, arrangements and mannerisms - and required the
# use to be FOR COMMERCIAL GAIN. So scale matters legally, not just morally.

LIKENESS_SIGNALS = {
    "ai cover": 7, "ai song": 7, "ai voice": 7, "ai version": 6,
    "ai generated": 5, "ai model": 5, "voice clone": 8, "cloned voice": 8,
    "ai mashup": 6, "ai remix": 6, "sung by ai": 8, "ai singing": 7,
    "rvc": 6, "so-vits": 6, "ai cover song": 7, "ai music": 5,
    "ai trailer": 6, "ai edit": 4, "face swap": 7, "faceswap": 7,
    "deepfake cover": 8, "what if": 3, "reimagined": 3,
    "sora": 4, "veo 3": 4, "kling ai": 4, "midjourney": 3, "elevenlabs": 5,
    # Hindi / romanised
    "ai gaana": 6, "ai awaaz": 7,
    # Long-form AI content built on a star's face. Worse than a cover, because
    # it is a catalogue with an ad-revenue stream rather than a single upload -
    # which is exactly the commercial gain the Bombay HC asked for.
    "ai web series": 8, "ai series": 7, "ai movie": 7, "ai film": 7,
    "ai short film": 6, "ai cinema": 7, "ai episode": 7, "ai story": 5,
    "ai teaser": 6, "ai concept trailer": 6, "ai universe": 6,
}

# ---------------------------------------------------------------------------
# THE ONE RIGHTS OWNERS ACTUALLY PAY TO REMOVE
# ---------------------------------------------------------------------------
# Using someone's face, voice or a copyrighted character TO SELL SOMETHING.
# Not a tribute, not a parody - a sales pitch wearing a famous person.
#
# It is mostly invisible in the title. A video called "Motivational speech"
# spends four minutes telling you to deposit 22,000 rupees in a trading app.
# That is why enrich.py fetches transcripts, and why these words are matched
# against the spoken text as well as the title.

SELLING_SIGNALS = {
    # the call to action
    "click the link": 4, "link in description": 4, "link in bio": 4,
    "download the app": 4, "download now": 3, "register now": 4,
    "sign up now": 4, "join now": 3, "use my code": 4, "promo code": 4,
    "referral code": 4, "limited time": 3, "limited seats": 4,
    "offer ends": 3, "hurry": 2, "dm me": 3, "whatsapp me": 5,
    "message me on telegram": 5, "join our telegram": 5,
    # the promise
    "guaranteed": 4, "guaranteed profit": 6, "guaranteed return": 6,
    "risk free": 4, "double your": 5, "minimum deposit": 5,
    "withdraw anytime": 4, "daily income": 5, "monthly income": 4,
    "earn from home": 4, "no investment needed": 3, "100% working": 4,
    # romanised Hindi, which is how most of this is actually spoken
    "abhi download": 4, "link description mein": 4, "paisa kamaye": 5,
    "ghar baithe": 4, "guarantee ke saath": 5, "muft mein": 3,
    "jaldi karo": 3, "abhi join": 4,
}

# What is being sold. Some categories are far more likely to be fraudulent
# and are also the ones a rights owner is most damaged by being associated
# with. These raise the score when selling language is already present.
RISKY_PRODUCTS = {
    "trading": 3, "forex": 4, "binary option": 5, "crypto": 3, "bitcoin": 3,
    "betting": 4, "satta": 5, "casino": 4, "rummy": 3, "fantasy app": 2,
    "loan app": 4, "instant loan": 4, "weight loss": 3, "hair growth": 3,
    "stamina": 3, "sexual wellness": 3, "ayurvedic cure": 3, "miracle cure": 5,
    "stock tips": 4, "sure shot": 4, "jackpot": 4,
}


def is_selling(text):
    """Returns (score, is_a_sales_pitch)."""
    text = (text or "").lower()
    pitch = sum(w for word, w in SELLING_SIGNALS.items() if word in text)
    if pitch >= 4:
        pitch += sum(w for word, w in RISKY_PRODUCTS.items() if word in text)
    return pitch, pitch >= 4


# ---------------------------------------------------------------------------
# THE CONFESSION IN THE DESCRIPTION
# ---------------------------------------------------------------------------
# Channels posting AI content built on somebody else's face very often say so
# themselves, in a disclaimer nobody reads. It is the cheapest and most
# reliable authorisation signal available - a licensed production never writes
# "no copyright infringement intended", because it holds the copyright.
#
# Two flavours, and the difference decides how strong the case is.

# "I know this isn't mine." An admission, and it makes the takedown easy.
DISCLAIMER_ADMISSIONS = [
    "no copyright infringement intended", "not affiliated", "not associated",
    "fan made", "fanmade", "fan-made", "for entertainment purposes only",
    "purely for entertainment", "we do not own", "all rights belong to",
    "credit to the rightful owner", "this is a fan", "unofficial",
    "no infringement intended", "belongs to their respective owners",
]

# "This was made with AI." Honest labelling. Also what IT Rules 2026 require.
AI_LABELS = [
    "ai generated", "ai-generated", "generated using ai", "made with ai",
    "created with ai", "ai tool", "artificial intelligence", "ai concept",
    "veo 3", "sora", "kling", "runway", "midjourney", "hailuo", "pika labs",
]

# Words that assert this IS the real thing. Combined with AI content and no
# authorisation, this stops being a fan tribute and becomes passing off -
# which is a far stronger case, and the one worth bringing.
OFFICIAL_CLAIMS = [
    "official trailer", "official teaser", "official video", "official audio",
    "official movie", "first look", "exclusive", "new movie", "new film",
    "full movie", "leaked", "confirmed", "announcement",
]


def provenance(text, channel_title=""):
    """What is this thing claiming to be?

    Returns one of:
      "official_claim" - AI content presenting itself as the genuine article
      "admitted"       - carries a disclaimer conceding it is not authorised
      "ai_labelled"    - openly says it was made with AI
      "unmarked"       - says nothing either way
    """
    blob = ((text or "") + " " + (channel_title or "")).lower()

    admitted = any(p in blob for p in DISCLAIMER_ADMISSIONS)
    labelled = any(p in blob for p in AI_LABELS)
    claiming = any(p in blob for p in OFFICIAL_CLAIMS)

    # Order matters. Claiming to be official while being AI is the worst case,
    # and a disclaimer buried in the description does not undo a title that
    # says "OFFICIAL TRAILER".
    if claiming and (labelled or admitted):
        return "official_claim"
    if admitted:
        return "admitted"
    if labelled:
        return "ai_labelled"
    return "unmarked"


# How each of those changes the score. Passing off is the case worth bringing;
# an honest fan film is a licensing conversation, not a lawsuit.
PROVENANCE_WEIGHT = {
    "official_claim": 1.6,
    "admitted": 1.2,
    "ai_labelled": 1.0,
    "unmarked": 1.0,
}

# Passing off is the case worth bringing, so it gets a floor rather than a
# multiplier. See the note in content_harm for why.
PASSING_OFF_FLOOR = 14


# Signals the uploader is making money from it. The Bombay HC required
# commercial gain, so these strengthen the legal case, not just the score.
COMMERCIAL_SIGNALS = {
    "buy": 2, "stream now": 3, "out now": 2, "available on": 2,
    "spotify": 3, "apple music": 3, "jiosaavn": 3, "download": 2,
    "subscribe for more": 1, "link in description": 2, "merch": 3,
    "sponsored": 3, "promo code": 3, "presave": 2, "pre save": 2,
}


# Signals that the content is synthetic or pretending to be the person.
# These raise harm regardless of which of the four kinds it is.
FAKE_SIGNALS = {
    "deepfake": 3, "ai generated": 2, "ai video": 2, "edited video": 2,
    "fake video": 3, "impersonat": 3, "official account": 2, "verified": 1,
}

# Words that suggest ordinary, lawful coverage. These pull the score DOWN.
# Getting these right matters more than the harm words — most of what you
# find will be harmless, and wrongly flagging it is the expensive mistake.
BENIGN_SIGNALS = {
    "trailer": -3, "teaser": -3, "song": -3, "interview": -2, "press conference": -2,
    "review": -2, "box office": -2, "behind the scenes": -3, "making of": -3,
    "award": -2, "red carpet": -2, "highlights": -2, "full movie": -2,
    "episode": -2, "promo": -2, "birthday": -2, "throwback": -2,
}


# ---------------------------------------------------------------------------
# WHAT GETS LOOKED AT FIRST
# ---------------------------------------------------------------------------
# The most expensive mistake on this project, made twice.
#
# Both the classifier and the video check sorted candidates by VIEW COUNT and
# took the top N. But the things worth finding are not popular. A genuine
# multi-episode AI web series using two stars' faces sat in the data with
# 158,000 views and was never once examined, because comedy shorts with
# millions of views filled every slot ahead of it.
#
# So ordering is by SUSPICION, not popularity. None of these signals decide
# anything - they only decide what a human or a model looks at first, which
# for a rare target is the whole game.

# A real series, which is the HIGH severity case: a catalogue with a revenue
# stream, built on someone's face.
SERIES_MARKERS = [
    "episode", "ep 1", "ep 2", "ep1", "ep2", "web series", "webseries",
    "season", "s01", "e01", "series",
]

# "Part 2" is NOT this. Salaar: Part 2 and Kalki 2898-AD: Part 2 are film
# titles, and treating them as episodic gave every fake trailer the series
# bonus - which is how a one-off trailer outranked a genuine three-part AI
# web series using two stars' faces.
SEQUEL_IN_A_TITLE = re.compile(r"part\s*[-:]?\s*\d", re.I)

MONEY_MARKERS = [
    "sponsor", "sponsored", "link in", "download", "app", "use code",
    "promo", "join", "sign up", "register", "offer", "buy",
]


def priority(item, official_channels=(), channel_counts=None):
    """How much this deserves an expensive look. Higher goes first.

    Deliberately crude. It is a queue order, not a verdict.
    """
    title = (item.get("title") or "")
    text = (title + " " + (item.get("description") or "")).lower()
    channel = item.get("channel_title", "")

    if is_authorised(channel, official_channels):
        return -1                       # their own channel, never a priority

    score = 0.0

    # Episodic is the strongest single signal we have. A series is a business
    # with a catalogue and a revenue stream, which is the HIGH severity case.
    episodic = any(m in text for m in SERIES_MARKERS)
    if episodic:
        score += 6
        # A numbered episode beyond the first proves the catalogue exists.
        if re.search(r"(episode|ep)\s*[-:]?\s*[2-9]", text):
            score += 4
        # And a channel running several of them is an operation.
        if channel_counts and channel_counts.get(channel, 0) >= 2:
            score += 3
    elif SEQUEL_IN_A_TITLE.search(text):
        score += 1          # a sequel's name, not an episode. Worth a little

    # Synthetic, and saying so.
    if any(w in text for w in ("ai ", " ai", "deepfake", "veo", "sora",
                               "kling", "generated", "ai-")):
        score += 3

    # Someone is selling something.
    if any(m in text for m in MONEY_MARKERS):
        score += 3

    # Claiming to be the real thing.
    if any(c in text for c in ("official trailer", "official teaser",
                               "official video", "first look", "leaked")):
        score += 3

    # A channel doing this repeatedly is an operation, not a fan.
    if channel_counts:
        n = channel_counts.get(channel, 0)
        if n >= 5:
            score += 3
        elif n >= 2:
            score += 1

    # Reach breaks ties. It does not lead - that was the whole mistake.
    score += min((item.get("views", 0) or 0) / 1_000_000, 1.0)

    return score


def channel_tally(items):
    counts = {}
    for i in items:
        c = i.get("channel_title", "")
        counts[c] = counts.get(c, 0) + 1
    return counts


def is_authorised(channel_title, official_channels, item=None):
    """Is this use permitted?

    The single most important question for likeness use. T-Series posting an
    Arijit Singh song is business as usual. A random channel posting an AI
    clone of his voice is not. Same words in the title, opposite meaning.

    Three tests, cheapest first:
      1. The person's own channel, or a label or brand on their list
      2. YouTube says the content is claimed by a rights partner
         (contentDetails.licensedContent) - a real signal that somebody with a
         content deal owns it, so it is very unlikely to be a rogue upload
      3. A genuine ad campaign names the brand in the channel itself

    What is deliberately NOT here: paid-promotion disclosure. YouTube shows
    "Includes paid promotion" in the player, but I could not confirm it is
    exposed through the Data API. Rather than invent a field, this is left as
    a known gap - if it turns out to be available it is the single best
    authorisation signal there is.
    """
    ch = (channel_title or "").lower()
    return any(o.lower() in ch for o in official_channels if o)


# licensedContent turned out to be a much weaker signal than I assumed.
# On the Narayana Murthy run it was set on 65 of the 78 most-viewed items,
# including TV9, NDTV Profit and Sakshi TV - it means "some rights partner
# claimed this", not "this person authorised it". Using it as a veto silently
# suppressed 29 scoring items.
#
# It is still worth something: a claimed video is likelier to be a legitimate
# operation than a rogue upload. So it discounts rather than excludes.
LICENSED_DISCOUNT = 0.6


def content_harm(text, channel_title="", official_channels=(), item=None):
    """Question 1. Returns (score 0-10, dict of the damage types)."""
    text = (text or "").lower()

    def tally(word_map):
        return sum(weight for word, weight in word_map.items() if word in text)

    authorised = is_authorised(channel_title, official_channels, item)

    # Unauthorised likeness use only counts if it is, in fact, unauthorised.
    likeness = 0
    claim = "unmarked"
    if not authorised:
        likeness = tally(LIKENESS_SIGNALS)
        if likeness:
            # Commercial gain is a legal element, not a nice-to-have.
            likeness += tally(COMMERCIAL_SIGNALS)
            # And what it claims to be decides how strong the case is.
            claim = provenance(text, channel_title)
            likeness *= PROVENANCE_WEIGHT[claim]

            # A multiplier alone was not enough, and the test showed why:
            # an honest "Prabhas AI Web Series" is stuffed with AI keywords
            # and scored 7.0, while "PRABHAS NEW MOVIE OFFICIAL TRAILER"
            # generated with Veo 3 mentioned AI only once and scored 2.4.
            # Exactly backwards - the one pretending to be real is the
            # serious case and the honest fan film is a licensing chat.
            #
            # So passing off sets a floor rather than scaling a keyword count.
            # How loudly it advertises the technique should not decide how
            # badly it behaves.
            if claim == "official_claim":
                likeness = max(likeness, PASSING_OFF_FLOOR)

    money = tally(MONEY_HARM)

    # THE COMBINATION THAT MATTERS MOST.
    #
    # Their face or voice, plus a sales pitch, minus permission. Not a tribute
    # and not a parody - somebody borrowing a reputation to move a product.
    # This is the thing rights owners actually pay to have removed, and it is
    # far more serious than either half on its own.
    pitch, selling = is_selling(text)
    if selling and not authorised and (likeness > 0 or money > 0):
        money += pitch + 4

    axes = {
        "money": money,
        "safety": tally(SAFETY_HARM),
        "dignity": tally(DIGNITY_HARM),
        "business": tally(BUSINESS_HARM),
        "likeness": likeness,
    }

    if item and item.get("licensed_content"):
        axes = {k: v * LICENSED_DISCOUNT for k, v in axes.items()}

    fake_bonus = tally(FAKE_SIGNALS)
    benign_penalty = tally(BENIGN_SIGNALS) + tally(GOSSIP_SIGNALS)  # both negative

    # Rank on the worst single axis, not the sum. A serious problem of one
    # kind is worse than mild problems of four kinds.
    worst = max(axes.values()) if axes else 0

    # Small bonus when more than one kind of damage is present at once.
    lit = sum(1 for v in axes.values() if v >= 3)
    multi_bonus = 1 if lit >= 2 else 0

    score = worst + fake_bonus + multi_bonus + benign_penalty
    return max(0.0, min(10.0, float(score))), axes, claim


# ---------------------------------------------------------------------------
# 1b. IS THIS THE ATTACK, OR A REPORT ABOUT THE ATTACK
# ---------------------------------------------------------------------------
# The single biggest error in the first real run. Searching for a person who
# has just been deepfaked returns overwhelmingly NEWS ABOUT the deepfake -
# "Actress issues stern warning to deepfake creators" - and because "deepfake"
# is a harm word, every one of those reports scored like a deepfake.
#
# Talking about a harm is not the harm. Usually it is the opposite: sympathetic
# coverage that helps the client.
#
# Neither signal is reliable alone. "Warns" appears in clickbait; "deepfake"
# appears in the fakes themselves. It is the COMBINATION - a harm word plus
# somebody reporting on it - that identifies coverage.

REPORTING_VERBS = [
    "warns", "warning", "slams", "issues", "condemns", "reacts", "responds",
    "speaks out", "breaks silence", "legal action", "takes action",
    "demands action", "targeted by", "victim of", "falls victim", "falls prey",
    "hits out", "calls out", "lashes out", "files complaint", "files fir",
    "fir against", "case against", "furious", "angry over", "outrage",
    "declares war", "cracks down", "flags", "alerts", "denies", "clarifies",
    "statement", "opens up about", "raises alarm", "criticises", "criticizes",
    # romanised Hindi, because half of Indian YouTube writes this way
    "bhadki", "bhadke", "chetavani", "naraz", "gusse", "kanoon",
]

# NEEDS A NATIVE SPEAKER'S REVIEW.
#
# The English list above caught only 32 of 360 problems in the first real run,
# because most coverage of an Indian actress is in Telugu, Tamil, Bengali and
# Devanagari. This is precisely the language gap the research called our moat -
# here it is, measured, on day one.
#
# Every term below was read directly off titles in the collected data, not
# translated by me. I do not read these languages. Treat the list as a
# starting point, not as correct.
REPORTING_VERBS += [
    # Telugu
    "ఫైర్", "వార్నింగ్", "హెచ్చరిక", "సీరియస్", "ఆగ్రహం", "లీగల్",
    # Devanagari Hindi/Marathi
    "चेतावनी", "भड़कीं", "भड़के", "कानूनी", "नाराज", "गुस्सा",
    # Bengali
    "হুঁশিয়ারি", "ক্ষুব্ধ",
    # Tamil
    "சட்டம்", "எச்சரிக்கை", "கொந்தளித்த",
]

# Same problem on the harm side: "deepfake" only matches in Latin script.
FAKE_SIGNALS.update({
    "deep fake": 3,          # the spaced spelling, very common
    "डीपफेक": 3, "डीप फेक": 3,
    "డీప్‌ఫేక్": 3, "డీప్ ఫేక్": 3,
    "ডিপফেক": 3,
    "மார்பிங்": 3, "மார்ஃபிங்": 3,
    "morphing": 3, "మార్ఫింగ్": 3, "मॉर्फिंग": 3,
})


def is_reporting(text, channel_title=""):
    """True if this looks like coverage OF an incident, not the incident."""
    blob = ((text or "") + " " + (channel_title or "")).lower()

    mentions_harm = any(w in blob for w in FAKE_SIGNALS) or "scam" in blob
    if not mentions_harm:
        return False

    if any(v in blob for v in REPORTING_VERBS):
        return True

    # A recognised news outlet talking about a harm is reporting it, not doing it.
    if any(hint in (channel_title or "").lower() for hint in NEWS_CHANNEL_HINTS):
        return True

    return False


# How much to knock the score down when something is coverage rather than the
# thing itself. Not zero - a hostile write-up can still damage a client, and
# occasionally the "report" is itself the attack.
REPORTING_DISCOUNT = 0.2


# ---------------------------------------------------------------------------
# 1c. NEWS CYCLE OR ATTACK CAMPAIGN - decided by arithmetic, not vocabulary
# ---------------------------------------------------------------------------
# Measured on the first real run. Of 100 items mentioning a deepfake term:
# 95 different channels, 92 posted within four days of her public statement,
# median 767 views. Every one of them was coverage. Not a single attack.
#
# The shapes are opposites, and you can tell them apart without reading a word:
#
#   Many channels, each posting once   -> journalism. Everyone reports news.
#   Few channels, posting many times   -> campaign. Someone is pushing this.
#
# This works identically in Telugu, Tamil, Bengali or English, which is why it
# beats adding more keywords. Vocabulary does not scale across six languages.
# Arithmetic does.

NEWS_CYCLE_CHANNELS = 8      # distinct channels covering the same thing
NEWS_CYCLE_DISCOUNT = 0.15   # harsher than the keyword-based discount, because
                             # the evidence is stronger

CAMPAIGN_COPIES = 5          # near-identical uploads...
CAMPAIGN_MAX_CHANNELS = 3    # ...from very few sources
CAMPAIGN_BOOST = 1.5


def cohort_shape(copies, cohort_channels):
    """Is this a news cycle, a coordinated campaign, or neither?

    cohort_channels = how many DISTINCT channels posted similar content in the
    same few days. Computed across the whole dataset, not from this item alone.
    """
    if cohort_channels >= NEWS_CYCLE_CHANNELS:
        return "news_cycle"
    if copies >= CAMPAIGN_COPIES and cohort_channels <= CAMPAIGN_MAX_CHANNELS:
        return "campaign"
    return "normal"


# ---------------------------------------------------------------------------
# 2. HOW BAD IS IT FOR THIS PERSON, RIGHT NOW
# ---------------------------------------------------------------------------
# Read from the subject file. Each event has a date, a type and a window in
# days. An event only counts while it is inside its window — nothing here
# is allowed to go stale silently.

EVENT_WEIGHTS = {
    "film_release": 1.8,
    "trailer_drop": 1.4,
    "award_show": 1.3,
    "tournament": 1.5,
    "tour": 1.3,
    "live_controversy": 2.0,
    "legal_matter": 1.7,
    "brand_campaign": 1.4,
    "election": 1.8,
    "other": 1.2,
}

MAX_CONTEXT_MULTIPLIER = 3.0  # hard cap. A big multiplier on stale data is
                              # worse than no multiplier at all.


def context_multiplier(item_date, events):
    """Question 2. Returns (multiplier, list of the events that fired)."""
    if not events:
        return 1.0, []

    multiplier = 1.0
    fired = []
    for ev in events:
        start = ev.get("_start")
        end = ev.get("_end")
        if start and end and start <= item_date <= end:
            weight = EVENT_WEIGHTS.get(ev.get("type", "other"), 1.2)
            # Multiply, but each additional event adds less than the last.
            multiplier *= 1 + (weight - 1) * (0.6 ** len(fired))
            fired.append(ev.get("label") or ev.get("type"))

    return min(multiplier, MAX_CONTEXT_MULTIPLIER), fired


# ---------------------------------------------------------------------------
# 3a. CAN WE ACTUALLY REMOVE IT
# ---------------------------------------------------------------------------
# 0 = no chance, 1 = near certain. On YouTube most things are removable,
# so the interesting cases are the exceptions.

NEWS_CHANNEL_HINTS = [
    "news", "tv18", "aaj tak", "ndtv", "abp", "zee", "india today",
    "times now", "republic", "the hindu", "indian express", "mirror now",
    "wion", "bbc", "reuters", "ani", "pti",
]


def removability(item, harm_axes):
    """Question 3, part one."""
    channel = (item.get("channel_title") or "").lower()

    # A real news outlet reporting something true is not removable, and
    # trying is how you turn a story into a bigger story.
    if any(hint in channel for hint in NEWS_CHANNEL_HINTS):
        return 0.1

    # Sexual or morphed imagery has the fastest legal route in India.
    # Unauthorised AI use of a performer's voice or face. Arijit Singh v.
    # Codible Ventures gives a direct Indian precedent, and YouTube's own
    # copyright and likeness processes apply on top. Very winnable.
    if harm_axes.get("likeness", 0) >= 6:
        return 0.9

    if harm_axes.get("dignity", 0) >= 6:
        return 0.95

    # Investment fraud breaches platform ad and fraud policy.
    if harm_axes.get("money", 0) >= 5:
        return 0.8

    # An account pretending to be the person.
    text = ((item.get("title") or "") + " " + (item.get("channel_title") or "")).lower()
    if "official" in text or "impersonat" in text:
        return 0.75

    return 0.6  # ordinary YouTube upload, platform policy route


# ---------------------------------------------------------------------------
# 3b. WOULD ACTING MAKE IT WORSE
# ---------------------------------------------------------------------------
# 0 = safe to act, 1 = do not touch. In version 1 this is close to a
# checkbox, and it is described honestly as one.

CRITIC_HINTS = ["journalist", "podcast", "opinion", "debate", "analysis", "investigat"]


def action_risk(item, harm_axes):
    """Question 3, part two."""
    views = item.get("views", 0) or 0
    channel = (item.get("channel_title") or "").lower()
    text = ((item.get("title") or "") + " " + (item.get("description") or "")).lower()

    risk = 0.0

    # EXCEPTION, and an important one: the "acting draws attention" logic does
    # not apply to physical safety. If someone has published the family's home
    # address, low reach is exactly WHY you take it down now, quietly, before
    # anyone notices. The sample data caught this - an address leak with 352
    # views was being marked 'do not touch', which is the opposite of right.
    if harm_axes.get("safety", 0) >= 4:
        return 0.0

    # Likeness use is a commercial matter, not a reputational one, so the
    # "you will draw attention to it" logic does not apply. Nobody thinks worse
    # of an artist because their label enforced a copyright.
    #
    # The exception is scale: going after a tiny fan tribute reads as bullying,
    # and the Bombay HC required commercial gain anyway - so a hobbyist with
    # 200 views is both bad PR and a weak case.
    if harm_axes.get("likeness", 0) >= 4:
        return 0.6 if views < 1000 else 0.0

    # Almost nobody has seen it. Acting is how people find out.
    if views < 500:
        risk += 0.5
    elif views < 5000:
        risk += 0.2

    # A journalist or a critic. Attacking them becomes the story.
    if any(hint in channel or hint in text for hint in CRITIC_HINTS):
        risk += 0.4
    if any(hint in channel for hint in NEWS_CHANNEL_HINTS):
        risk += 0.4

    # The claim may simply be true — a court case proves it in public.
    if harm_axes.get("business", 0) >= 4 and harm_axes.get("dignity", 0) < 4:
        risk += 0.2

    return min(risk, 1.0)


# ---------------------------------------------------------------------------
# SPREAD — is it travelling
# ---------------------------------------------------------------------------
# The only part of this file that could one day become a real model, because
# reality tells you the answer for free. Log every prediction from day one.

def spread_score(item, copies):
    """0-10. Velocity matters more than total views."""
    views = item.get("views", 0) or 0
    hours = max(item.get("age_hours", 1), 1)
    per_hour = views / hours

    if per_hour > 5000:
        s = 10
    elif per_hour > 1000:
        s = 8
    elif per_hour > 200:
        s = 6
    elif per_hour > 50:
        s = 4
    elif per_hour > 10:
        s = 2
    else:
        s = 1

    # Many copies of the same thing means somebody is pushing it.
    if copies >= 20:
        s += 3
    elif copies >= 5:
        s += 2
    elif copies >= 2:
        s += 1

    # People sharing it, not just watching it.
    if views > 0:
        engagement = (item.get("comments", 0) or 0) / views
        if engagement > 0.02:
            s += 1

    return min(float(s), 10.0)


def is_amplified(item, copies):
    """Already confirmed to be travelling. This OVERRIDES everything else."""
    views = item.get("views", 0) or 0
    channel = (item.get("channel_title") or "").lower()
    return (
        views > 100_000
        or copies >= 15
        or any(hint in channel for hint in NEWS_CHANNEL_HINTS)
    )


# ---------------------------------------------------------------------------
# PUTTING IT TOGETHER — two scores, not one
# ---------------------------------------------------------------------------
# HARM tells the client how much this will cost them.
# ACTION PRIORITY tells the team what to work on.
# They are different on purpose: a true, damaging newspaper story is maximum
# harm and near-zero action priority. The client must be told. The team must
# not chase it.

AMPLIFIED_BONUS = 0.3


def judge(item, events, copies, cohort_channels=1, official_channels=()):
    # The transcript is where the sales pitch lives, so it is scored alongside
    # the title rather than separately.
    text = " ".join([
        item.get("title") or "",
        item.get("description") or "",
        item.get("transcript") or "",
    ])

    harm_raw, axes, claim = content_harm(
        text, item.get("channel_title", ""), official_channels, item)

    # Is this the attack, or somebody reporting the attack?
    # Two independent tests: what the words say, and what the crowd looks like.
    reporting = is_reporting(text, item.get("channel_title", ""))
    shape = cohort_shape(copies, cohort_channels)

    if shape == "news_cycle":
        harm_raw *= NEWS_CYCLE_DISCOUNT
        axes = {k: v * NEWS_CYCLE_DISCOUNT for k, v in axes.items()}
        reporting = True
    elif reporting:
        harm_raw *= REPORTING_DISCOUNT
        axes = {k: v * REPORTING_DISCOUNT for k, v in axes.items()}
    elif shape == "campaign":
        harm_raw = min(harm_raw * CAMPAIGN_BOOST, 10.0)

    spread = spread_score(item, copies)
    amplified = is_amplified(item, copies)
    ctx, fired = context_multiplier(item.get("date"), events)
    remove = removability(item, axes)
    backfire = action_risk(item, axes)

    # Spread MULTIPLIES harm, it does not add to it.
    #
    # This was wrong in the first version and the sample data caught it: a film
    # trailer with 500,000 views was scoring as high harm purely because it was
    # spreading fast. How far something travels only matters if it is damaging
    # in the first place. Harmless content going viral is just a popular video.
    #
    # But the floor is 0.5, not 0, so a catastrophic item nobody has seen yet
    # still scores about half - it must not disappear from the list just
    # because it hasn't spread. That failure has a name in the cybersecurity
    # version of this: score masking.
    spread_factor = 0.5 + (spread / 20.0) + (AMPLIFIED_BONUS if amplified else 0)

    harm = min(harm_raw * spread_factor * ctx, 10.0)
    priority = harm * remove * (1 - backfire)

    _, selling = is_selling(text)

    return {
        "harm": round(harm, 2),
        "priority": round(priority, 2),
        "selling": selling,
        "claims": claim,
        "heard": bool(item.get("transcript")),
        "content_harm": round(harm_raw, 1),
        "reporting": reporting,
        "shape": shape,
        "cohort_channels": cohort_channels,
        "spread": round(spread, 1),
        "amplified": amplified,
        "context_x": round(ctx, 2),
        "context_why": ", ".join(fired),
        "removable": round(remove, 2),
        "backfire_risk": round(backfire, 2),
        "damage_likeness": axes["likeness"],
        "damage_money": axes["money"],
        "damage_safety": axes["safety"],
        "damage_dignity": axes["dignity"],
        "damage_business": axes["business"],
        "disposition": disposition(harm, remove, backfire, amplified),
    }


def disposition(harm, remove, backfire, amplified):
    """The one label a human puts on each problem.

    Order matters. 'Just tell him' comes before 'don't touch' because when
    something genuinely cannot be removed, telling the client IS the action.
    'Don't touch' is reserved for things we COULD remove but shouldn't.
    """
    if harm < 2:
        return "IGNORE"
    if remove < 0.25:
        return "JUST TELL HIM"
    if backfire >= 0.5:
        return "DO NOT TOUCH"
    if harm >= 6 and amplified:
        return "FIX NOW"
    if harm >= 4:
        return "FIX THIS WEEK"
    return "WATCH"
