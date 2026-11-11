# In Rotation

Album discovery with personalized recommendations. Portfolio project.

**Stack:** Vite + React + TypeScript (`web/`), FastAPI (`backend/`), PostgreSQL (user data), DuckDB (offline data jobs). Offline packages at the repo root: `recs/` (recommendation engine) and `ingest/` (MusicBrainz catalog).

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

## Test
```
cd backend && pytest               # 145 API tests (plus 1 live Gemini test, skipped unless asked): browse filters, search, artists, sessions, accounts, lists, ratings, dismissals, covers, recommendations, catalog matching, redirects, track lists, the assistant (scripted fake model; no quota used), data migrations (SQLite)
# one real Gemini request (uses quota; needs GEMINI_API_KEY): INROTATION_LIVE_GEMINI=1 pytest tests/test_gemini_live.py
# same tests on Postgres (the database is emptied each test; never point this at real data):
# docker compose exec db psql -U in_rotation -c 'CREATE DATABASE in_rotation_test'
# INROTATION_TEST_DATABASE_URL=postgresql+psycopg://in_rotation:in_rotation_dev@localhost:5432/in_rotation_test pytest
cd recs && pytest                  # 84 tests: cleaning rules, edition merging, weights, matrix, recommender, item kNN, metrics, album map layout, model comparison
cd ingest && pytest                # 7 tests: MusicBrainz dump parsing, refresh (fake mirror: checksum, coverage gate, swap), cover pre-fetch
cd web && npm run build            # type-check and production build
```

## How to check the basics by hand
1. Open the site with the API running. Discover loads albums from the API; the genre chips filter on the server.
2. Search "beyonce" (finds Beyoncé), "hip hop", "r&b", and "zzz" (empty state).
3. Rate and bookmark a few albums, then reload: they persist (stored under an anonymous session).
4. Open the site in a private window: it starts with an empty library, since it is a separate anonymous user.
5. Go to `/start`, rate 5 albums 3 stars or more, and continue to For you.
6. Stop the API and reload: a clear message explains how to start it.

## How to check the recommender offline
1. `cd recs && pytest` and a smoke sweep: `python -m recs.evaluate --users 300 --out data/experiments-smoke` (about 1.5 min). CF should beat popularity by a wide margin.
2. Read `docs/experiments.md`. Check that the numbers match `data/experiments/results.md` and `short_queries.csv`, (beta is set to 0.25).
3. Try your own taste with the Python snippet above (use album keys from `albums.parquet`). Judge whether the lists are good, and how much same-artist repetition you'd accept.

## How to check the catalog and recommendations
1. Build `data/catalog.db` (see "Build the catalog"); it prints match coverage. Expect about 92% of listening and 97% of albums with 1,000+ listeners matched, and read the top unmatched list.
2. `cd backend && pytest`, then start the API: it should log startup in a few seconds.
3. In the browser:
   - Discover shows real covers in the mosaic; albums without archived art show a "No Cover" tile.
   - Search "emotion", "gza", "r&b".
   - Open an album: release year, genres, and "Listeners also love".
4. Go to `/start`, search for and rate 5 albums you know well, then open For you.
   - Judge the list, and check that no artist appears more than twice.
   - Rated albums are never suggested back to you.
5. With no ratings (private window), For you explains it is showing the most-listened albums.

## How to check accounts and lists
1. Start Postgres, run `alembic upgrade head`, then start the API. Stop Postgres (`docker compose stop db`) and restart the API: it should refuse to start and say how to fix it.
2. In the browser, rate a few albums and save a listen-later album. Then open **Sign in** in the header, choose "Create account", and sign up. Your library should be unchanged.
3. Open a private window, save a different album, and sign in there with the same account. Both libraries should now be merged, with no duplicates.
4. Sign out: that window starts with an empty library. Sign in again and everything is back.
5. On an album page, use "Add to list" to create a list and tick it on and off. On Library, rename and delete a list.
   - Check the layout of the list menu, the account form and the list headers at phone width.
6. Albums on any list never appear in For you.

## How to check artist pages and refresh
1. Search "radiohead": an artist chip appears above the albums. Open it.
   - Studio albums come first; EPs, live albums and other releases follow.
   - "Their listeners also play" shows one album per related artist. Judge whether those artists make sense.
2. Artist names on album cards and album pages link to the artist page.
3. `python -m ingest.refresh --check` reports the current and latest dump. Read the swap report of a real refresh (`retired_albums`, coverage before and after), then restart the API.

## How to check ratings
1. `alembic upgrade head` from `backend/` (adds `user_ratings`), then restart the API.
2. On an album page, rate with the stars: the left half of a star gives a half star. Choosing the same value again clears the rating.
   - Check the stars by keyboard (Tab to the stars, then the arrows, 1-5 and Delete) and on a phone (tap the halves).
3. Rated albums show a "★ 4½" badge on their covers. The Library groups them from highest to lowest.
4. Rate an album 2.5 stars or less: it never comes back as a suggestion, but it doesn't steer them either.
5. Move one album from 3 to 5 stars and compare For you before and after. The change is deliberately gentle (docs/experiments.md, run 2).
6. Optional: `python -m recs.ratings --users 300 --seeds 7` reproduces a small version of the experiment (about 1 min).

## How to check rating badges and dismissals
1. `alembic upgrade head` from `backend/` (adds `user_dismissals`).
2. Every cover shows a badge top-left: "☆ Rate" or "★ 4½". Click it, pick a value (left half of a star = half star), and the selector closes with the badge updated.
   - Try it by keyboard too: Tab to the badge, Enter, the arrows, Enter, and Escape to cancel.
   - Check at phone width that the selector doesn't run off the screen.
3. On For you, click the X on an album: it disappears, the list refills, and "Undo" brings it back. Reload: dismissed albums stay gone.

## How to check cover loading
1. Reload Discover and search "radiohead": covers of popular albums appear at once (served from `data/covers`).
2. Open an obscure album: the first view may take a few seconds (fetched once from the archive), then it is instant, including after a reload.
3. In the browser's network panel, `/api/covers/...` responses carry `Cache-Control: public, max-age=2592000`.

## How to check "How well known?" on For you
1. With a few albums rated, open For you and move the slider. Each step reloads the list (the old one dims while it loads).
2. "Less known" drops the big records; "Under the radar" and "Deep cuts" should still sound like your ratings, from smaller artists.
3. Reload the page: the slider keeps its step (stored in this browser only).
4. `curl -H "Authorization: Bearer <token>" "localhost:8000/api/me/recommendations?depth=3"`; `depth=4` is a 422.
5. Rerun the experiments behind the steps: `python -m recs.less_popular --users 2000` (run 3, the earlier user kNN model, about 5 minutes) and `python -m recs.item_checks --users 2000` (run 7, item kNN).

## How to check item kNN
1. With a few albums rated, open For You. Picks should sit close to your ratings, and "Because you rated" should name different albums of yours across the page, not the same one every time.
2. An album page's Listeners Also Love is that album's most similar albums. The match block reads "Most like X and Y of the albums you rated."
3. How Recommendations Work describes comparing albums. Its Technical Details tab marks item kNN as served.
4. Engine: `python -m recs.item_checks --users 2000` (run 7, about 45 minutes) rechecks the weights, star weights, How Well Known caps and match score on item kNN. `python -m recs.compare --users 5000` (run 6, about 1 h 40 min) reruns the comparison.

## How to check Diversify
1. With a few albums rated, open For You and click Diversify. It turns amber, the URL gets `?diverse=1`, a line explains it, and the list reloads on page 1 with more varied picks (fewer near-duplicates, more of your rated albums leading a pick).
2. It combines with How Well Known and Filters. Reload: it stays on. Click again to turn it off.
3. `curl -H "Authorization: Bearer <token>" "localhost:8000/api/me/recommendations?diverse=true"`. `diverse=maybe` is a 422.
4. Experiment: `python -m recs.diversity --users 1000` (run 8, about 30 minutes).

## How to check filters on For You
1. With a few albums rated, open For You and click Filters. The dialog is titled Filter Your Picks and has Genre, Decade, Length and Album Type (no Popularity: the How Well Known slider does that).
2. Choose a genre and a decade, then Show Picks. The list reloads on page 1, the count says how many picks there are, and chips show the filters. Removing a chip or Clear All widens the list again. The URL carries the filters (`?genre=jazz&decade=1960`).
3. Filters combine with the slider. Length: Over an Hour should bring up double albums. A combination nothing close to your taste matches says so and suggests removing a filter.
4. `curl -H "Authorization: Bearer <token>" "localhost:8000/api/me/recommendations?genre=jazz&year_from=1960&year_to=1969&length=30_45"`. `type=vinyl` and `length=forever` are 422.
5. Item kNN scores every album, so a filtered list is the full ranking narrowed to the filter. The run 5 experiment, from the earlier user kNN model, still runs: `cd backend && PYTHONPATH=.:.. python experiments/for_you_filters.py` (about 2 minutes).

## How to check themes
1. Open Account (Sign In in the header). Under the form, Theme offers Charcoal, Gallery and Midnight. Choosing one recolors the whole site at once.
2. Reload: the theme stays, with no flash of the dark default. Another browser keeps its own choice.
3. Signed in, the same picker is in Profile Settings.
4. Look over the home page, an album page, For You, the Album Map and Insights in Gallery, the light theme. Chips on covers, the rating popover and the filter dialog should all be readable.

## How to check track lists
1. Open an album page (OK Computer, The Wall, Lemonade): a Tracks section under the buttons lists numbers, titles and lengths, with the track count and running time on top.
2. Multi-disc albums (The Wall) have "Disc 1" and "Disc 2" headings; guest credits ("Beyoncé feat. Jack White") show under the track title.
3. "Track list from MusicBrainz" links to the release the list was taken from.
4. Catalogs built before this change are refused by the API with the rebuild command (catalog format 3).

## How to check the Album Map
1. Build it once with `python -m ingest.album_map` from the repo root (about a minute), then open **Map** in the header. Until it's built, the page shows the API's message with that command.
2. Fully zoomed out you see gray dots with genre and country names, such as Heavy Metal, Hip Hop, K-Pop and Brazil. Drag to move, scroll or pinch to zoom, double-click to zoom in on a spot, or use +, − and Fit. As you zoom, more labels appear, then covers replace the dots, then titles appear under the bigger covers.
3. Rate a few albums. Your ratings show as amber dots, and your For You picks as teal rings. The legend counts how many are on the map, and Zoom to Yours frames them. Opening the map doesn't change Insights' recommendation counts.
4. Type in Find on the Map and press Enter. The map flies to the album and opens its card. Open Album, then Back, returns to the same view with the card open. On an album page, "See It on the Album Map" does the same. For an album that isn't on the map, a note says so.
5. Highlight a Genre lights up that genre's albums and dims the rest.

## How to check the footer pages
1. Every page ends with the footer: In Rotation © year, then Contact, Data Sources and How Recommendations Work. On a short page (an empty Library) it sits at the bottom of the window. On a phone the links stack.
2. Each link opens its page at the top, and the current one is underlined in amber.
3. Contact: send a message (optionally with an email for a reply), then read it with `python -m app.feedback` from `backend/`. A sixth message within an hour is refused. To show a public address too, set `VITE_CONTACT_EMAIL=you@example.com` in `web/.env` and rebuild.

## How to check match scores
1. Rate a few albums 3 stars or more, then open an album page. Under the genres, a "Match" block shows a score out of 100, a short meter, and a line like "Most like OK Computer and Kid A of the albums you rated." "How Match Works" explains it.
2. Albums close to your taste score in the 90s, and albums far from it score low or get "No match score" with the reason. With no ratings of 3 stars or more, it asks you to rate some.
3. Open an album you rated: the score is the same as before you rated it ("Scored as if you hadn't rated it").
4. Rate another album and come back: the score updates.
5. API: `curl -H "Authorization: Bearer <token>" localhost:8000/api/albums/<id>/match`. Validation: `python -m recs.item_checks --users 2000` (run 7 in `docs/experiments.md`; run 4, `python -m recs.match`, validated the earlier user kNN version).

## How to check profiles
1. Signed out, press **Sign In** and **Create Account**: name, username, email, password, and Public Profile (off by default). An account is a profile; you land on your page at `/u/<username>`.
2. The header's **Profile** link (with your picture) replaced "Account". Your page has Ratings (Newest First / Highest Rated), Insights (from ratings only: no Listen Later, lists or recommendation stats) and, for you only, **Settings**.
3. In Settings, add a picture: any JPEG, PNG, WebP or GIF up to 8 MB. It comes back as a 256 px square; a phone photo's location data is dropped. Sign Out is there too.
4. While private, a private window gets "Profile Not Found" at your link; you see your page with a note. Turn on **Public Profile** and the link works for anyone, without signing in.
5. An account made before profiles: its Profile link opens "Finish Your Profile" to choose a username.
6. API: `curl localhost:8000/api/users/<username>`, `curl localhost:8000/api/users/<username>/insights`.

## How to check Insights
1. Rate and save a few albums, then open **Library** and the **Insights** tab (`/library?tab=insights`). With fewer than 3 it invites you to choose albums.
2. The profile shows your top-rated covers, a one-line summary ("You gravitate toward…"), and your counts; then genres, rating habits, favorite and most-collected artists, eras, highest rated, recently discovered, and recommendations.
3. Hover or tab onto a column to see its numbers; "Show as Table" lists them all.
4. Recommendation stats count from now on: open For You or ask the assistant, then rate, save or dismiss some of what it suggests and reload Insights.
5. API: `curl -H "Authorization: Bearer <token>" localhost:8000/api/me/insights`.

## How to check streaming links
1. Open an album page (OK Computer, Illmatic, Abbey Road). Under the buttons, "Listen On" has Spotify and Apple Music; each opens the regular album on that service in a new tab: OK Computer, not OKNOTOK; Illmatic, not Illmatic XX; Abbey Road's remaster where that is all there is.
2. Both go through the API: `curl -I localhost:8000/api/albums/<id>/listen/spotify` (or `apple-music`) answers 302. The first click checks MusicBrainz's candidate links against the service's own title; later clicks are cached for a week.
3. An album a service only offers as a deluxe or other edition (Apple's "4 (Expanded Edition)") opens that service's search page instead.
4. `sqlite3 data/catalog.db "SELECT service, count(DISTINCT album_id) FROM album_links GROUP BY 1"`: about 141K albums with Spotify candidates and 144K with Apple ones.

## How to check filters
1. On the home page, under "Browse Albums", press **Filters**. A dialog opens: Genre (type to search genres and subgenres together), Decade or Exact Year, Popularity, Country and Album Type. Every filter is optional and they combine.
2. Type "hop": Hip Hop comes first, with its subgenres and Trip Hop after it, each showing its album count and parent genre. A genre includes its subgenres and fusions, so Electronic also lists trip hop and house albums.
3. The main button counts matching albums as you change things ("Show 1,234 Albums"). Esc or a click outside closes without applying; "Clear All" empties the dialog.
4. Filters live in the URL (`/?genre=trip+hop&country=GB`), so Back works and the link can be shared. "Show More" loads 48 more; "Clear Filters" goes back to the most-listened albums. On a phone the dialog fills the screen.
5. API (it also takes `artist` and `sort`, which the page doesn't offer): `curl "localhost:8000/api/albums?genre=electronic&country=GB&year_from=1990&year_to=1999&type=studio&sort=rated"`, `curl localhost:8000/api/browse/options`, `curl "localhost:8000/api/browse/genres?q=hop"`.

## How to check account deletion, sign-in limits and cleanup
1. Sign in, open your profile's Settings and press **Delete Account**. A wrong password says so. The right one deletes everything, shows a toast and leaves this browser with an empty library. Other browsers signed in to it start afresh.
2. On **Sign In**, enter a wrong password 6 times for one email: the sixth says to wait 15 minutes, even with the right password.
3. Cleanup: `python -m app.cleanup --dry-run` from `backend/` counts anonymous users that are empty and unseen 7 days, or unseen 365. Without `--dry-run` it deletes them. Run it once a day once deployed. Accounts are never touched.

## How to check the Ask assistant
Needs `GEMINI_API_KEY` in `backend/.env` (see "Run it"). Each message uses 1-4 model requests.
1. `INROTATION_LIVE_GEMINI=1 pytest tests/test_gemini_live.py` from `backend/`: one real request that must call a tool.
2. Rate a few albums, open **Ask** and try the suggested prompts. Recommendations appear as album cards; the text should explain them from your own ratings ("people who love Visions, which you gave 5 stars") and never quote numbers the cards don't support.
3. Follow up in the same chat: "something less mainstream", "which of those is closest to Grimes?", "only the 1990s". The second answer shouldn't repeat albums from the first.
4. "Add the first three to my listen later list": the reply says what was saved, the bookmarks on the cards turn teal, Undo removes them. "Put them in a new list called Night drives" creates the list; Undo deletes it.
5. Earlier chats lists past conversations; New chat starts over. A second browser can't open your conversation (404).
6. Limits: send 6 messages within a minute (the 6th is refused). With `INROTATION_CHAT_PER_DAY=2`, the third message of the day is refused, and deleting your chats doesn't reset it. With `INROTATION_CHAT_PER_DEVICE_PER_DAY=2`, a third private window on the same computer is refused too. With `GEMINI_DAILY_CALLS=4` the second message says the assistant has reached today's request limit.
7. Remove the key and restart: Ask shows how to turn it on, and the rest of the site is unchanged.
