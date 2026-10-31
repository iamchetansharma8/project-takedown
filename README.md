# Project Takedown — proof of concept

Finds online content that misuses a person's name, face or voice, and works out which of it is worth doing something about.

No server, no database, no interface. A few scripts and some spreadsheets.

---

## 1. What this actually does

You give it a person. It gives you back a short list of things worth a lawyer's time, and a much longer list of things to leave alone.

The second list matters as much as the first. Most of what a famous person's face appears in is harmless, and telling a star to attack their own fans is bad advice.

---

## 2. What it found

### 2.1 False film attribution — verified by hand

**20 videos carry Prabhas's name on films he is not in. 51.5 million views. 16 channels.**

Eleven were opened and checked by hand. Ten had no trace of him. One was a different film to the one named. **Zero false positives.**

Two examples, both confirmed:

- *"SHOOTER Full Movie \| Prabhas"* — is actually **Dishoom**, with John Abraham and Varun Dhawan
- *"Prabhas & Sreeleela Latest Full Action Movie"* — is actually **Bhagavanth Kesari**, with Balakrishna

**Why nobody catches this:** YouTube's Content ID matches audio and video fingerprints. It never reads a title. A false name on the label is invisible to every automated system the platform runs.

### 2.2 AI content operations — found by the pipeline

Five channels producing AI-generated content built on his likeness:

Channel names are left out on purpose.

| Channel | Uploads | What it is |
|---|---|---|
| Channel A | 4 of 4 generated | "Swayambhu" — a whole AI film with teaser, songs, scenes |
| Channel B | 3 of 3 generated | Prabhas & Anushka AI web series, numbered episodes |
| Channel C | 3 of 3 generated | Fake concept trailers |
| Channel D | 2 of 2 generated | Fake concept trailers |

19 of 20 videos watched were confirmed generated, with specific evidence — generator watermarks, faces that change between shots, unnatural motion.

---

## 3. How the system works, stage by stage

### 3.1 Collect

`collect.py` searches YouTube and saves what it finds to a file. That is all it does. No pipeline, no schedule — you run it, it writes a file.

Search terms live in the subject file and come in three layers:

1. **Star plus format** — "Prabhas AI web series". Finds videos about him
2. **Format alone** — "AI web series telugu". Finds the *channels*, which matter more
3. **Tool names** — "Veo 3 telugu". People brag about what they generated with

**Never search the bare name.** During a news cycle a name returns only news coverage, and no amount of scoring can separate the reporting from the thing afterwards.

### 3.2 Rank by suspicion

This is the stage that was broken longest, and the one that matters most.

`rules.py` scores each item on **how much it deserves an expensive look**. Not on how bad it is — on whether it is worth examining.

What raises the score:

- Episodic markers — "episode 2", "web series", "season"
- AI markers — "AI", "Veo", "Sora", "generated"
- Selling language — "download", "link in bio", "use code"
- Official claims — "official trailer", "first look", "leaked"
- The same channel appearing repeatedly

Views only break ties. **They never lead** — see section 5.1 for why that nearly sank the project.

### 3.3 Cheap sort with a model

`classify.py` sends batches of eight items to a language model with just their titles and descriptions. It asks: is this AI content using this person's likeness, and what kind of thing is it?

It puts everything into a fixed list of categories. A label you cannot count is a label you cannot measure.

Roughly 45 calls for 350 items. Cheap enough to run on everything.

### 3.4 Watch the video

`watch.py` is the expensive step, and it only runs on what stage 3.3 flagged.

It sends the YouTube URL straight to Gemini along with two or three ten-second windows. **Nothing is downloaded.** Google fetches and decodes the video on its own servers.

Around **1,400 tokens per video** — because we are not sending a film, we are sending roughly fifteen frames. See section 4.

Two modes:

- `--mode attribution` — *who is in this, and what film is it really?*
- `--mode purpose` — *what is this video for?*

### 3.5 Decide severity

Severity comes from **purpose**, not from technology. A face selling a product without permission is the same harm whether the video was generated or cleverly edited.

| What it is | Severity | Why |
|---|---|---|
| Sexual or defamatory | **HIGHEST** | Fastest legal route in India — 2 hours |
| Promotes a product | **HIGH** | Endorsement abuse. The case with money behind it |
| Numbered series | **HIGH** | A business built on the face, with ad revenue |
| Claims to be official | **HIGH** | Passing off |
| Fake trailer, honest about it | MEDIUM | Harmful mainly if it pretends to be real |
| Fan tribute | LOW | Usually free promotion. Leave it alone |
| News or commentary | NONE | Reporting about a thing is not the thing |
| Their own channel | NONE | A studio posting its own film |

### 3.6 Roll up to the channel

The last step, and the one that turns a list into a case.

If a channel has several generated uploads, they stop being separate videos and become **one operation** with one severity. A lawyer writes to a person, and YouTube strikes accrue to accounts.

A repeat fake-trailer producer gets promoted to HIGH. A repeat *comedy* producer does not — if every upload reads as harmless, the channel is harmless however many there are.

---

## 4. Why watching a video is so cheap

**We are not sending a video. We are sending about fifteen photographs.**

Gemini turns video into frames and reads those. One frame a second by default, each costing about what an image costs. That is where "300 tokens per second" comes from.

A 150-minute film would be 9,000 pictures. So we do two things:

| | Effect |
|---|---|
| Three ten-second windows instead of the whole film | **300× fewer** |
| Half a frame per second instead of one | **2× fewer again** |

Fifteen frames. About 1,400 tokens. A model looking at fifteen photographs is completely ordinary — the only clever part is that Google does the extraction, so nothing is downloaded and no video files are ever stored.

It is also exactly what a person does by hand: drag to 20%, 50%, 80% and look.

---

## 5. Mistakes worth remembering

Every one of these produced results that looked fine and were wrong.

### 5.1 Sorting by popularity when the target is unpopular

Both the classifier and the video checker sorted by view count and took the top N. **The things worth finding are not popular.** A genuine three-part AI web series sat in the data with 188,000 views and was never once examined, because comedy shorts with millions of views filled every slot.

134 of 160 episodic items were never even classified.

**Fixed by:** ranking on suspicion. Views only break ties.

### 5.2 Judging the upload instead of the account

One AI web series returned LOW, MEDIUM and HIGH — for three episodes of itself. Judging uploads independently lets an operation hide behind its mildest video.

**Fixed by:** rolling up to the channel.

### 5.3 Asking a leading question

The first prompt said *"CLIENT: Prabhas — is he in this video?"* On a historical drama with no Prabhas in it, the model replied *"wrong-film, this is Saaho"* — naming a specific film that was not there.

**Fixed by:** asking who it can see without saying who we are looking for, then comparing in code. A witness who has not been told which suspect to pick out is worth far more than one who has.

### 5.4 Hiding the packaging when the question was about packaging

Then we over-corrected. Purpose was judged from three windows in the middle of a film, with the title hidden — so almost everything came back "fake trailer".

**Identity is in the pixels. Purpose is in the packaging.** A trailer, an ad and an episode all announce themselves in the first fifteen seconds and in their titles.

**Fixed by:** two standards of evidence in one call. Judge who appears from the footage only. Judge what it is from the title, the channel and the opening.

### 5.5 Treating "about a thing" as "the thing"

Searching for a person who has just been deepfaked returns overwhelmingly *news about the deepfake*. Because "deepfake" was a harm word, every report scored like an attack.

Of 100 items mentioning a deepfake term: **95 different channels, 92 posted within four days of a public statement, median 767 views.** That shape is journalism, not 100 attacks — and counting channels works identically in Telugu, Tamil and English, where keyword lists do not.

### 5.6 One stray character

A Telugu title collapsed to the digit `2` because the text handling was ASCII-only. Every video with "2026" in its name matched a real film. **40 of 43 waved through by one character.**

---

## 6. Where things live

| File | What it does |
|---|---|
| `rules.py` | Keyword scoring **and the suspicion ranking**. The doorman |
| `classify.py` | Cheap model sort over titles and descriptions |
| `providers.py` | One adapter each for Gemini, Anthropic, OpenAI, Ollama. Plain HTTP |
| `watch.py` | **Watches the video.** Both modes, severity, channel rollup |
| `attribution.py` | Films carrying a name without cause |
| `filmography.py` | Real filmography from TMDb, falling back to Wikidata |
| `judge.py` | Grouping, ranked queue, offending-channel report |
| `enrich.py` | Transcripts, for pitches that are spoken not written |
| `explore.py` | Raw search results, no scoring. Check terms before building on them |
| `goldenset.py` / `evaluate.py` | The answer key, and scoring the model against it |
| `check_models.py` | Which Gemini models your key can call for free |
| `subjects/*.json` | One per person: who they are, what is authorised, what to search |

---

## 7. Keys you need

| For | Where | Cost |
|---|---|---|
| `YOUTUBE_API_KEY` | console.cloud.google.com → YouTube Data API v3 | Free. 10k units/day ≈ 100 searches |
| `GEMINI_API_KEY` | aistudio.google.com/apikey | Free tier. Run `check_models.py` to see which models work |
| `TMDB_API_KEY` | themoviedb.org → Settings → API | Free |
| `TELEGRAM_API_ID` / `_HASH` | my.telegram.org | Free |

**If TMDb resets the connection, that is not your key.** Indian ISPs block it intermittently — Jio and Airtel especially. Switch DNS to `1.1.1.1`, or run `filmography.py ... --wikidata` and skip it entirely.

---

## 8. Running it

### 8.1 Try it with no keys at all

```bash
python3 make_sample_data.py
python3 judge.py subjects/example.json
```

Fake data, so you can see the shape of the output before setting anything up.

### 8.2 Find false film attribution

```bash
export YOUTUBE_API_KEY=...
python3 collect.py subjects/prabhas-attribution.json

export TMDB_API_KEY=...
python3 filmography.py "Prabhas" subjects/prabhas-attribution.json
python3 attribution.py subjects/prabhas-attribution.json
```

Read `data/<id>_attribution.csv`. One column matters: **`verdict`**.

- `UNSUPPORTED` — claims to be a full film, names the person, names **no film they have been in**
- `names a real film` — probably fine

### 8.3 Verify it by machine instead of by hand

```bash
export GEMINI_API_KEY=...
python3 watch.py subjects/prabhas-attribution.json --verified -n 11 --methods clips
```

Scored against eleven hand verdicts: **agreed on ten, declined on one, no false positives.** It also named Bhagavanth Kesari, Dishoom and Saaho unprompted.

### 8.4 Find AI likeness operations

```bash
python3 collect.py subjects/prabhas.json
python3 classify.py subjects/prabhas.json 200
python3 watch.py subjects/prabhas.json --mode purpose -n 20
```

Read the **OPERATIONS** block first — it names channels. The per-video rows are supporting detail.

---

## 9. What is not built

- **No takedowns.** Detection only
- **No court packs or evidence chain**
- **No scheduling.** You run it by hand
- **No interface.** CSV files
- **Ads are unreachable.** Meta's Ad Library API returns political ads only; Indian commercial ads are not in it
- **Telegram needs channel names.** Its "global" search only covers channels your account can already reach, so you cannot discover — only monitor
- **Transcripts are blocked.** YouTube refuses the scraping library by IP. The official captions API with OAuth is the durable route

---

## 10. What we still do not know

**Whether anyone will pay for this.** Nothing found today establishes it.

Enforcement in India is real and funded, but it targets piracy websites and Telegram — not YouTube channels. No reported case of a YouTube channel banned in India for this. The industry's ₹22,000 crore piracy concern is about box office, which is not what we found.

**One conversation with a star's manager or a studio's legal team answers this.** More code will not.

---

## 11. Conventions

See `CONTRIBUTING.md`. Branch and pull request for every change, atomic commits, and any change to scoring must say what behaviour changed and what evidence prompted it.

**Never commit `data/`.** It holds real people's content, and the Telegram session file is a credential.
