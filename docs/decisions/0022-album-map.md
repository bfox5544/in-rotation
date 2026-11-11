# 0022: Album Map

Status: accepted (2026-11-04). The owner picked it from a list of major feature ideas ("Do 8").

## What it is
A page at `/map` that lays out the most-listened albums on a plane. Albums sit close together when the same people listen to them. Fully zoomed out, the map is gray dots with genre and country names on their regions. Zoomed in, covers replace the dots and the bigger covers get their titles. Your rated albums are marked in amber and your For You picks with teal rings. You can highlight one genre, find an album on the map, and click or tap an album to open a card with a link to its page. Album pages link to the map with that album selected.

## How positions are made (offline: `python -m ingest.album_map`, maths in `recs/album_map.py`)
1. **Which albums.** The 15,000 catalog albums with the most listeners, and at least 20. The full map goes down to 181 listeners. The cover cache already holds the top 20,000, so zoomed-in covers load from disk.
2. **Vectors.** Each album is its column of the user x album weight matrix, with the same weights the engine uses (`recs.weights` defaults). The columns of model albums that map to one catalog album (editions, aliases) are summed, then L2-normalized, so a dot product is the cosine similarity of two albums' listeners.
3. **Embedding.** Truncated SVD to 64 dimensions, then rows normalized again: a denoised cosine space.
4. **Layout.** t-SNE (cosine metric, perplexity 40, PCA start, fixed seed), scaled into a 0-1000 square.

On the full data this takes about a minute: about 25 s for the SVD and 30 s for t-SNE. The output is `data/album_map.json` at about 1 MB. It holds album ids, positions, genre memberships and label spots only. It contains no user data and no historical user ids.

### Why t-SNE and not UMAP
UMAP usually keeps the global layout better, but it would add `umap-learn`, `numba` and `pynndescent`. scikit-learn was already part of the documented stack ("scikit-learn where useful"). It is now a dependency of the offline jobs (`pyproject.toml`, `recs/requirements.txt`), and the API never imports it. With t-SNE, local neighbourhoods are reliable but the distance between far-apart regions means little. The page copy only claims that close albums share listeners.

### Why SVD before t-SNE
Running t-SNE on the raw 476K-user columns would be slow and noisy. The 64-dimensional SVD keeps the main structure and makes t-SNE's neighbour search cheap.

## Labels
For each genre with 30 or more map albums (a genre includes its subgenres and fusions, ADR 0015), and each country with 30 or more, the job finds the grid cell (40 x 40, smoothed 3 x 3) with the highest **count x share**. The genre must hold at least half of the albums there, and at least 8 of its own. The label sits on the most crowded of its albums near that peak, never in the gap between two groups. Labels are placed strongest first, in three tiers 110, 55 and 28 map units apart. Tier 0 shows when fully zoomed out, and tiers 1 and 2 appear as you zoom in. On screen, labels that would overlap are skipped.

- **Countries** label regions no genre explains. Brazilian albums of every genre cluster together, for example, as do Japanese, Argentinian and Swedish ones. The two most common countries (the US and the UK) are everywhere, so they are never labels. A country's score is weighted 0.6, so a genre wins a close call for the same spot ("K-Pop" over "South Korea").
- **One trial on the full data** gave 48 labels. They included Heavy Metal, Power Metal, Grunge, Emo, Punk, Hip Hop, Trap, Cloud Rap, K-Pop, J-Pop, Reggaeton, Brazil and Japan, each on its own cluster.

## Colour and marks
The map is a scatter, so a categorical palette would have to pass every pair, not just neighbours. Eight genre colours can't pass that, so genres are shown through emphasis instead. The highlighted genre's dots turn light and the rest dim. Your marks use the site's two accents: amber for rated (a filled dot) and teal for For You (a hollow ring). Shape differs as well as colour, so colour never carries the meaning alone. The palette validator passes the pair for colour-blind separation (ΔE 14.5) and normal vision (20.8) on the page background. Both accents are lighter than the validator's band for categorical series. That is deliberate here: they are highlights on a field of dim gray dots.

## API
- `GET /api/map` returns the albums as columns (id, title, artist, year, listeners, x, y), the offered genres and the labels. Genre members are sent as gaps between sorted positions, which is a third of the size gzipped. Titles come from the catalog when the file is read, after resolving MusicBrainz redirects. Albums no longer in the catalog are dropped with a warning, so a catalog refresh doesn't need a map rebuild. The response is built and gzipped once, has an ETag and is cached for a day. It is about 690 KB gzipped, mostly the 15,000 album ids, which don't compress. Without the file it returns 404 with the build command.
- `GET /api/me/map` returns your For You ranking (the top 240 ids). Unlike `/me/recommendations`, it doesn't record impressions: marking the map isn't showing you recommendations, so Insights' recommendation stats stay honest.

## Not done
- No table view. A list of 15,000 albums isn't a useful equivalent. Keyboard users reach albums through Find on the Map, and the canvas takes arrow keys, + and −, 0 and Escape.
- The layout isn't stable across rebuilds. A different model or catalog moves regions around.
