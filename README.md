# In Rotation

Album discovery with personalized recommendations, built from real listening behavior. Rate a few albums you know and In Rotation finds the albums that the same listeners love alongside yours, then suggests the ones you haven't heard. Album artwork leads the design. Portfolio project.

**Stack:** Vite + React + TypeScript (`web/`), FastAPI (`backend/`), PostgreSQL (user data), SQLite (read-only album catalog), DuckDB (offline data jobs). Offline packages at the repo root: `recs/` (recommendation engine: pandas, NumPy, SciPy sparse matrices) and `ingest/` (MusicBrainz catalog). Metadata comes from MusicBrainz and artwork from the Cover Art Archive.

## Features

- **Discover:** a home page with a cover collage, Picked for You once you've rated 5 albums, and Browse Albums with filters for genre and subgenre, decade or exact year, popularity, country and album type, plus sorting.
- **Search:** albums and artists, accent- and case-insensitive, with suggestions as you type in the header.
- **Album pages:** large artwork, release year, genres, track list, Listeners Also Love, a personal match score out of 100, and Listen On links that open the regular album (never a deluxe edition) on Spotify and Apple Music.
- **Artist pages:** studio albums, EPs, live albums and compilations, and related artists by listener overlap.
- **Ratings:** half-star ratings from 0.5 to 5, from a badge on any cover. Ratings are the only taste signal.
- **For You:** up to 240 recommendations, with "Because you rated" explanations, a How Well Known slider (Anything, Less Known, Under the Radar, Deep Cuts), filters for genre, decade, length and album type, a Diversify toggle, and dismissals with Undo.
- **Onboarding:** "Rate albums you know" with search and autocomplete to build a taste quickly.
- **Library:** ratings, Listen Later and custom lists, each with its own page and sorting, a "Listened Yet?" nudge for albums saved a week ago and still unrated, and save-to-list from any cover.
- **Library Insights:** a music profile from your ratings: genres, favorite artists, eras, rating habits, highest rated and recent discoveries.
- **Album Map:** the 15,000 most-listened albums laid out by who listens to them, with genre and country labels, zoom, search, and your ratings and picks marked.
- **Ask:** an optional discovery assistant (Google Gemini) that interprets the conversation and calls the recommendation engine, catalog and library, and can save albums to your lists.
- **Accounts and profiles:** anonymous sessions by default, so nothing is required to start. Optional email accounts keep and merge your library across browsers, with a public or private profile page, a picture, and account deletion.
- **Themes:** Charcoal (dark, the default), Gallery (light) and Midnight.
- **Info pages:** How Recommendations Work, Data Sources, Privacy and Contact.

## How recommendations work

1. **Real listening data.** The model learned from 476,304 real listeners and the 50 albums each of them played most. An album's place in someone's list says how much they love it, not just that they have it. Each album in a listener's top 50 gets a weight between 0 and 1, half from its rank and half from its plays:

   `weight = 0.5 × rank score + 0.5 × play score`

   The rank score falls in a straight line from 1.00 at rank 1 to 0.02 at rank 50. The play score compares the album's plays with that listener's most-played album on a logarithmic scale, so a few obsessive replays don't swamp everything else. An album outside someone's top 50 counts as unknown, never as disliked.

   | Rank  | 1    | 10   | 25   | 50   |
   |-------|------|------|------|------|
   | Score | 1.00 | 0.82 | 0.52 | 0.02 |

2. **Your ratings.** Albums you rate 3 stars or more describe your taste, and higher stars count for more. Lower ratings keep an album off your list but don't push you away from similar music.

   | Stars  | 5   | 4.5 | 4   | 3.5 | 3   |
   |--------|-----|-----|-----|-----|-----|
   | Weight | 1.0 | 0.9 | 0.8 | 0.7 | 0.6 |

3. **Finding albums like yours.** Two albums are similar when the same people rank both near the top of their lists. Each album is a list of weights with one slot per listener (476,304 slots, nearly all empty). Cosine similarity compares two albums by the angle between their lists: 1 when the same people love both in the same proportions, 0 when nobody has both. Because it measures direction rather than size, a hit that everyone owns isn't automatically close to everything.

4. **Scoring albums.** An album scores well when it's similar to several of the albums you love, most of all the ones you rated highest:

   `score = sum over your albums of (rating weight × similarity)`

   Albums you've rated, saved or dismissed are left out, and no artist gets more than two places. So are albums too few people have to judge (under 10 listeners, or rarely owned by fans of your albums), so every pick has a match score. "Because you rated" names the albums of yours a pick's score comes from.

5. **A fair chance for smaller albums.** Similarity already allows for how many people own each album, so a famous album only scores well when fans of your albums love it more than everyone else does. Holding famous albums back any further made picks worse. To dig deeper, the How Well Known slider keeps only albums under 5,000, 1,000 or 200 listeners. Diversify picks each album for being unlike the ones above it too, so more corners of your taste show up.

**Match scores.** Album pages show how well an album fits your taste, out of 100. Its score is compared with the albums that at least 0.1% of the listeners who have your albums also have, and a 92 means it beats 92% of them. Your own rating of that album is left out, so it can't inflate the score.

**How well it works.** For 5,000 listeners, a fifth of their albums were hidden and the rest used as their taste. In Rotation's top 20 found the hidden albums about ten times as well as a list of the most popular albums, and about six times as well with only 10 albums to go on. Six ways of recommending were tested, and comparing albums beat comparing listeners, the method In Rotation used before, by 8%.

**Limits.** The data is a snapshot, so new releases aren't in it. Albums very few people listed can't be recommended with confidence. And it can only find albums that fans of your albums already found. For something different, there's Ask.

### How each setting was chosen

Every setting was picked by testing: some of each test listener's albums were hidden, recommendations were made from the rest, and the setting that found the hidden albums best won. Scores below are NDCG@20, a ranking score from 0 to 1 that rewards finding hidden albums near the top of the first 20.

| Question | Answer | Evidence |
|---|---|---|
| Compare you with other listeners, or compare albums? | Compare albums. | Item kNN 0.260, ALS 0.251 (but 97% of picks from the most famous 1% of albums), user kNN 0.241, most popular 0.026. Comparing albums also recommended a wider range of albums and stayed ahead with only 10 albums. |
| Rank in someone's top 50, or how often they play it? | Both count equally. | Rank alone was 1% ahead with full queries but 3% behind with 10 albums, where plays alone came out ahead. Counting both stays close to the best either way. |
| Should a 5-star album count for more than a 3-star one? | Yes, a little more. | Equal weights 0.257, a little more for higher stars 0.263, much more 0.256. 3-star albums still say something about your taste. |
| Should famous albums be held back? | No. | No adjustment 0.260, gentle (β 0.1) 0.245, moderate (β 0.25) 0.136. |
| How does How Well Known find smaller albums? | It leaves out albums over the listener limit. | Loved albums under 1,000 listeners found in the top 20: normal list 0.104, leaving out albums over the limit 0.234, also leaving out albums under 10 listeners 0.240. |
| Which albums is a match score measured against? | Albums enough fans of your albums have. | Requiring 0.1% of the listeners who have your albums scores 77% of loved albums (typical score 98). 0.3%: 66%, 1%: 49%, 3%: 31%. A score of 95+ is over 200 times likelier to be a loved album than a score under 50. |

## Technical details

### Six models, one test

The site first recommended with user-based collaborative filtering. To check that choice, five other recommender families were run through exactly the same test: same listeners, same hidden albums, same weight matrix, same metrics. Each had to recommend for listeners it never saw in training, the way the site meets a new user, so the factor models fold a new listener in rather than look up a trained row.

- **Popularity:** the most-listened albums, the same for everyone. The floor every model must clear.
- **User kNN:** cosine similarity between your ratings and every listener's top 50, then a weighted sum over the 100 nearest. What the site ran first.
- **Item kNN (served):** each album scores by its summed cosine similarity to the albums you rated, with similarity measured over listeners. Computed as (q Cᵀ) C with C column-normalized, so no 633K × 633K album matrix is stored.
- **RP3beta:** a three-step random walk, album to listener to album, divided by popularity to the power β (Paudel et al. 2017).
- **PureSVD:** a truncated SVD of the weight matrix. Your ratings are projected onto the top k factors and back (Cremonesi et al. 2010).
- **ALS:** implicit-feedback matrix factorization (Hu, Koren and Volinsky 2008) through the `implicit` library. A new listener is folded in with one least-squares solve.

EASE, a strong item-based model, was left out: it needs a dense album × album matrix, 633K × 633K here, about 1.6 TB in float32.

### How they were tested

Leave-out evaluation on the historical listeners, the only ground truth the data has. For each test listener a random 20% of their albums are hidden, the rest form the query, and the hidden albums are the right answers. Test listeners are removed from the training matrix first. Each family was tuned on one sample of 5,000 listeners and then scored once on a different 5,000, so no model was tuned on the listeners it's judged on.

- **NDCG@20:** discounted cumulative gain of the top 20 (relevance 1 for a hidden album, discounted by log2 of its position), divided by the best possible. The main metric.
- **Recall and Hit Rate@20:** share of the hidden albums that make the top 20, and share of listeners with at least one there.
- **Distinct Albums and Head Share:** how many different albums the model recommends across all 5,000 listeners, and the part of its picks taken from the 1% most-listened albums (6,331). Accuracy alone rewards recommending hits.
- **Paired difference:** each model's NDCG@20 minus user kNN's, per listener, averaged, with a 95% interval. Both models face the same listeners, so the pairing removes most of the noise.
- **10-album check:** the same listeners with only 10 albums in the query, closer to a new site user than the full ~38.

### Results

Test listeners, full queries. Query time is per listener in batches of 200.

| Model | NDCG@20 | Recall@20 | Hit Rate@20 | Distinct Albums | Head Share | Fit | Query |
|---|---|---|---|---|---|---|---|
| Popularity | 0.026 | 0.030 | 0.22 | 35 | 100% | 0 s | 5 ms |
| User kNN, K 100, β 0.25 (previous) | 0.240 | 0.228 | 0.82 | 20,161 | 75% | 1 s | 5 ms |
| **Item kNN, β 0 (served)** | **0.259** | **0.251** | **0.86** | **23,368** | **75%** | **1 s** | **32 ms** |
| RP3beta, β 0.1 | 0.206 | 0.202 | 0.78 | 19,182 | 82% | 0.5 s | 33 ms |
| PureSVD, 256 factors | 0.182 | 0.175 | 0.70 | 2,693 | 100% | 47 s | 5 ms |
| ALS, 256 factors, α 20 | 0.251 | 0.245 | 0.83 | 6,632 | 97% | 12 min | 6 ms |

Paired NDCG@20 difference from user kNN, with 95% intervals:

| Model | Full queries | 10-album queries |
|---|---|---|
| Item kNN | +0.0190 ± 0.0028 | +0.0041 ± 0.0023 |
| ALS, 256 factors | +0.0106 ± 0.0042 | −0.0016 ± 0.0028 |
| RP3beta | −0.0350 ± 0.0038 | −0.0029 ± 0.0032 |
| PureSVD, 256 factors | −0.0582 ± 0.0044 | −0.0449 ± 0.0032 |

### What the results say

- **Item kNN won, and it's what the site serves.** It came out 7.9% ahead of user kNN on full queries and 3% ahead when listeners had only 10 albums. It recommended more different albums than user kNN (23,368 against 20,161) and leaned on hits no more than before. The price is speed: about 32 ms a listener against 5 for user kNN, still quick enough for a page.
- **ALS looked good until its picks were checked.** At 256 factors it beat user kNN on full queries and tied it with 10 albums, but 97% of its picks came from the 1% most-listened albums and it covered a third as many albums overall. That isn't much use on a discovery site. It also took 12 minutes to train and was still improving at the biggest size tried. PureSVD has the same pull toward hits, with less accuracy.
- **RP3beta is the adventurous one.** It trailed on full queries but was within the margin of error with 10 albums. Turned toward less popular albums (β 0.25), it reached two and a half times as many different albums, at some cost to accuracy.
- **User kNN did fine, just not well enough.** Switching meant rebuilding Because You Rated, the match score and filtered lists around album similarity and testing them again.

### Tuning each model

Every family got a small grid on the tuning sample, and its best setting went to the test. The popularity adjustment that helps user kNN hurts the item-based and factor models, so they were tested without it.

| Model | Grid | Best | Worst | Note |
|---|---|---|---|---|
| User kNN | K 50, 100, 200 × β 0, 0.25 | K 100, β 0.25: 0.238 | K 200, β 0: 0.225 | Flat. The settings chosen in the first sweep still come out on top. |
| Item kNN | β 0, 0.1, 0.25 | β 0: 0.260 | β 0.25: 0.136 | Very sensitive to the popularity adjustment. β 0.1 already costs 0.015. |
| RP3beta | β 0.1, 0.25, 0.4 | β 0.1: 0.201 | β 0.4: 0.153 | β 0.25 recommends 2.5× the distinct albums for almost the same score. |
| PureSVD | 256 factors, then 128 and 512 | 256: 0.183 | 128: 0.175 | Peaks in the middle. More factors don't help. |
| ALS | 64 to 256 factors × α 20, 40, 15 iterations | 256, α 20: 0.251 | 64, α 20: 0.194 | Still rising at the largest size tried. |

### The served model

Each listener u gives a weight to every album a in their top 50:

```
w(u, a) = α · (1 − (rank − 1) / 50) + (1 − α) · log(1 + plays) / log(1 + max plays of u),  α = 0.5
```

An album is the column of those weights across all 476,304 listeners, and two albums are compared by cosine:

```
sim(a, b)  = Σ over listeners of w(u, a) · w(u, b)  ÷  (‖w(·, a)‖ ‖w(·, b)‖)
score(b)   = Σ over your rated albums a of q(a) · sim(a, b)
```

Your ratings of 3 stars and up form the query q, weighted 1.0 for 5 stars down to 0.6 for 3. Columns are scaled to length 1 once at startup, so scoring every album is (q Cᵀ) C: two sparse products through the listeners, with no 633K × 633K similarity matrix stored. Albums with under 10 listeners, or held by under 0.1% of the listeners who have one of your albums, are left out: with few ratings, cosine otherwise favours albums with two or three listeners who all share them. A smaller album may instead be held by 5% of its own listeners (and 3), since 0.1% of a big audience can be more than a Deep Cut's whole audience. A first page takes about 120-250 ms on the full data and later pages about 50 ms, because scores are cached per taste. The list is then re-ranked: rated, saved and dismissed albums are removed, no artist gets more than two places, and editions merge. Every album has a score, so a For You filter only narrows the ranking.

The same scores drive the rest of the site. Listeners Also Love on an album page is the albums most similar to it. Because You Rated names the rated albums that carry the most of a pick's score. The match score is the percentile of an album's score among the albums held by at least 0.1% of the listeners who have one of your albums (and 3 of them).

### Data and cleaning

The dataset ([Music Listening Data, ~500k users](https://www.kaggle.com/datasets/gabrielkahen/music-listening-data-500k-users)) gives each listener's 50 most-played albums with rank, play count and an optional MusicBrainz id. It has no ratings and no dates. Cleaning runs in DuckDB in about 31 seconds and writes Parquet.

| Step | Count | What happened |
|---|---|---|
| Raw rows | 23,822,550 | 476,451 listeners, up to 50 albums each, with rank and play count |
| Invalid rows dropped | 28,766 | 17 with no album or artist name, 28,749 empty after normalizing |
| Album identity | 1,830,875 → 1,656,172 | Distinct artist and title pairs merged into normalized keys: accents, case and punctuation folded, edition tags (Deluxe, Remastered, Anniversary...) stripped |
| Duplicates within a listener | 268,860 | Rows merged into one, keeping the best rank and summing plays |
| Albums with 1 listener | 1,023,118 | Removed: one listener can't link anyone to anyone |
| Listeners with under 5 albums | 147 | Removed after the album filter |
| Kept | 476,304 × 633,053 | 22,501,513 listener-album pairs, 0.0075% of the matrix filled, median 49 albums per listener |

Albums are identified by normalized artist and title, because the MusicBrainz id names an edition and is blank on 24% of rows. Matching model albums to the MusicBrainz catalog covers 92.3% of all listening and 97.1% of albums with 1,000 or more listeners. Unmatched albums still help find similar albums but are never shown.

### Experiments behind each feature

Each change to ranking was tested the same way before it shipped. Runs 1-5 tested the user kNN model the site originally used. Run 7 checked their settings again on item kNN. Full write-ups are in [docs/experiments.md](docs/experiments.md).

| Run | Question | Result | Decision |
|---|---|---|---|
| 1. Parameter sweep | Which weights, neighbourhood size, aggregator and popularity adjustment? | 80 settings in three stages. K 200 → 100 plus β 0.25: +0.0140 ± 0.0023 NDCG@20. Plays-only weights and asymmetric cosine: +0.0012 ± 0.0013, noise. | Linear rank and plays, α 0.5, cosine, K 100, weighted sum, β 0.25 |
| 2. Rating weights | Should higher star ratings weigh more in the query? | Ratings simulated from rank buckets, 3 seeds. Gentle +0.0044 ± 0.0009 NDCG@20 over equal weights, steep −0.0020 ± 0.0020. | 5★ 1.0, 4★ 0.8, 3★ 0.6, half stars interpolated, under 3★ excluded |
| 3. Less popular picks | How should How Well Known find smaller albums people love? | Recall@20 of loved albums under 1,000 listeners: listener cap without the adjustment 0.161, stronger adjustment (β 0.5) 0.088, uncapped 0.096. | Caps of 5,000, 1,000 and 200 listeners, β 0 inside a cap, 10-listener floor |
| 4. Match score | How many neighbours make a calibrated 0-100 score? | 300 neighbours, 2 must hold the album: 64.7% of loved albums scored, median 92, scores of 95-100 are 36× likelier to be loved than scores under 50. | Percentile among albums the 300 nearest listeners hold, no adjustment |
| 5. Filtered lists | Do filters need a wider neighbourhood? | Recall@240 inside the filter, K 100 against K 1,000: jazz 0.54 → 0.73, 1990s electronic 0.54 → 0.91. | Filtered lists rank by K 1,000, fill from K 5,000 |
| 6. Model comparison | Is user kNN the right model? | Six families on one split. Item kNN +0.0190 ± 0.0028 NDCG@20, ALS +0.0106 ± 0.0042, RP3beta and PureSVD worse. | Switch to item kNN, no popularity adjustment |
| 7. Item kNN checks | Do the settings chosen for user kNN still hold? | Rank and plays half and half within 0.003 of the best at both query sizes. Gentle star weights best at both. Caps with the 10-listener floor best at every cap. Match support of 0.1%: 76% of loved albums scored, median 98. With 3 albums, 21% of picks had under 10 listeners, and leaving thinly held albums out raised NDCG@20 from 0.085 to 0.092. | All kept, plus a 0.1% match reference set, and picks limited to albums with 10+ listeners that the match score can score |
| 8. Diversify | How strong should the Diversify button be? | Maximal marginal relevance over the best 500 picks. Strength 0.7: picks 75% less alike, 87% of rated albums lead a pick, NDCG@20 −5% on full queries and −27% with 10 albums. Strength 0.5 kept more accuracy but left picks closer together. | Strength 0.7, only when the button is on |
| 9. Support for smaller albums | Why was Deep Cuts short of picks? | 0.1% of the listeners who have your albums is more than most albums under 200 listeners have in all, so 29% of Deep Cuts lists (10 albums) couldn't fill. Allowing 5% of an album's own listeners: smaller albums found 0.151 → 0.181, 1% short. | 0.1% of those listeners or 5% of the album's own, whichever is fewer |

## First run
The API needs two data products before it starts: the model (`data/model/`) and the catalog (`data/catalog.db`). Build them once, in this order:
1. Model: see "Build the model data" below (the dataset file, about 1 minute).
2. Catalog: see "Build the catalog" below (MusicBrainz dumps, about 1 hour the first time, mostly downloading).

It also needs PostgreSQL for user data (step 1 below). If anything is missing, the API stops at startup and says which command to run.

## Run it (two terminals)

**1. Database** (once per machine; Docker Desktop must be running)
```
cp .env.example .env && docker compose up -d db    # Postgres 16 on localhost:5432, dev-only credentials
```

**2. API**
```
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # also installs recs/ and ingest/ from the repo root
alembic upgrade head                  # create or update the user-data tables (rerun after pulling new migrations)
uvicorn app.main:app --reload         # http://localhost:8000/docs; loads the model at startup (a few seconds, ~2.6 GB RAM)
```
`INROTATION_MODEL_DIR` and `INROTATION_CATALOG` override the default `data/model` and `data/catalog.db`; `INROTATION_DATABASE_URL` overrides the Postgres URL (any SQLAlchemy URL, e.g. `sqlite:///data/dev.db` to run without Docker).

**Optional: the Ask assistant**. It uses the paid Gemini API. Without a key the rest of the site works and Ask says it is off.
1. Create a key at https://aistudio.google.com/apikey, in the Google Cloud project that has **billing on** (a key from another project stays on the free tier). Add a budget alert in Google Cloud billing as a backstop.
2. `cp backend/.env.example backend/.env` (already done once), then set `GEMINI_API_KEY=` in `backend/.env`. The file is git-ignored and the key never leaves the backend.
3. `GEMINI_DAILY_CALLS` (default 200) caps the model requests the whole site makes per day, which caps spending: roughly a dollar a day at most with `gemini-3.5-flash-lite`. Each person gets 25 messages a day (`INROTATION_CHAT_PER_DAY`) and each device 40 (`INROTATION_CHAT_PER_DEVICE_PER_DAY`, counted by network address). Set `INROTATION_SECRET` to any long random text so device counts survive restarts.
4. Restart the API. On the paid tier Google doesn't use prompts to improve its products.
5. Deployed behind a proxy or load balancer, run uvicorn with `--proxy-headers --forwarded-allow-ips=<the proxy's address>`. Otherwise every visitor looks like the proxy and shares one device limit.

**3. Web**
```
cd web
npm install
npm run dev                        # http://localhost:5173 (proxies /api to port 8000)
```

## Build the model data
```
pip install -r recs/requirements.txt
python -m recs.preprocess --db data/your_file.duckdb --out data/model   # cleans, writes Parquet and report.md
python -m recs.matrix --model-dir data/model                           # builds user_album.npz
python -m recs.probe_mbids --albums data/model/albums.parquet --contact you@example.com   # optional: which MBID type?
```
Read `data/model/report.md` first. For a dry run without the real file: `python -m recs.synthetic --out data/synthetic.duckdb --users 20000`.

## Build the catalog (MusicBrainz)
Bulk metadata comes from the MusicBrainz dumps (refreshed twice a week), never the live API. From the repo root:
```
D=$(curl -s https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/LATEST)
curl -o data/musicbrainz/release-group.tar.xz https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/$D/release-group.tar.xz   # 1.2 GB
python -m ingest.musicbrainz            # -> data/musicbrainz/release_groups.parquet, artists.parquet (about 6 min)

# Optional but recommended: release -> release-group links (MBID and edition-title matching) and track lists
F=$(curl -s https://data.metabrainz.org/pub/musicbrainz/data/fullexport/LATEST)
curl -o data/musicbrainz/mbdump.tar.bz2 https://data.metabrainz.org/pub/musicbrainz/data/fullexport/$F/mbdump.tar.bz2   # 7.7 GB
mkdir -p data/musicbrainz/core && tar -xjf data/musicbrainz/mbdump.tar.bz2 -C data/musicbrainz/core mbdump/release mbdump/release_group mbdump/artist_credit mbdump/release_group_gid_redirect mbdump/medium mbdump/track mbdump/medium_format mbdump/genre mbdump/l_genre_genre mbdump/link mbdump/link_type mbdump/url mbdump/l_release_url mbdump/l_release_group_url   # about 10 min, 13 GB extracted

python -m ingest.catalog                # -> data/catalog.db, prints match coverage (about 2 min)
python -m ingest.covers --top 5000      # pre-fetch covers for the most-listened albums into data/covers
python -m ingest.album_map              # the Album Map: 15,000 albums laid out by listeners (about 1 min, data/album_map.json)
```
Check each download against the `SHA256SUMS` file in the same folder. Rebuild the catalog, then the Album Map, whenever the model changes (the API refuses a catalog built from a different model or an older catalog format).

### Refresh from newer dumps
```
python -m ingest.refresh --check   # exit 0 = up to date, 10 = a newer dump is out
python -m ingest.refresh           # download (1.2 GB, checksum-verified), rebuild, sanity-check, swap; about 10 min
python -m ingest.refresh --core    # also refresh the core tables (7.7 GB); monthly is plenty
```
The previous catalog is kept as `data/catalog.db.prev`. The swap is refused, leaving the live catalog untouched, if listening coverage drops by more than 1 point or the catalog shrinks by more than 2% (`--force` overrides). **Restart the API afterwards** to serve the new catalog. Saved albums survive MusicBrainz merges through redirects.

To schedule it weekly (Monday 04:00), add a line with `crontab -e`; nothing is installed for you:
```
0 4 * * 1 cd /path/to/in-rotation && .venv/bin/python -m ingest.refresh >> data/refresh.log 2>&1 && .venv/bin/python -m ingest.covers --top 5000 >> data/refresh.log 2>&1
```

## Evaluate the recommender
```
python -m recs.evaluate --model-dir data/model --users 5000 --out data/experiments   # about 25 min on 12 cores
pip install -r recs/requirements-experiments.txt   # adds implicit (ALS), only for the comparison
python -m recs.compare --model-dir data/model --users 5000 --out data/experiments    # six model families, about 1 h 40 min (docs/experiments.md run 6)
python -m recs.item_checks --model-dir data/model --users 2000 --out data/experiments   # served item kNN settings (run 7)
```
Tunes on 5,000 historical users and reports on 5,000 different ones, next to a popularity baseline. Writes `results.md`, `sweep.csv`, `final.csv` and `chosen_config.json` to `data/experiments/`; conclusions are in `docs/experiments.md`. Use `--users 300` for a quick run (about 1.5 min).

In Python, with the served model, item kNN (`recs.recommender.Recommender` is the earlier user kNN, same `recommend` call):
```python
from recs.item_knn import ItemKNN
from recs.query import AlbumLookup, query_vector
rec = ItemKNN.from_model_dir("data/model")
idx, _ = AlbumLookup.from_model_dir("data/model").resolve(["radiohead | in rainbows", "radiohead | kid a"])
albums, scores = rec.recommend(query_vector(idx, rec.n_albums), n=20)
```

Put your dataset in `data/` (git-ignored).

## Run the test suites
```
cd backend && pytest     # API tests on SQLite; set INROTATION_TEST_DATABASE_URL to run them on Postgres
cd recs && pytest        # recommendation engine
cd ingest && pytest      # catalog jobs
cd web && npm run build  # type-check and production build
```
