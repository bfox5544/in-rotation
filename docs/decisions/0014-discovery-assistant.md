# 0014: Discovery assistant (Ask)

Status: accepted (2026-11-03, owner request and plan approval).
- **Request:** "an AI chatbot assistant that will allow the user to search for recommendations and create lists based on prompts", using the Gemini API free tier.
- **Owner decisions:** the mappings below. Public deployment must handle the EEA/UK/Switzerland rule. The free daily request limit for the model was not known when this was written.

## What it is
An **Ask** page where the user chats about music. A language model reads the conversation and asks the backend to run a few narrow tools; the backend does the work:
- **Recommendations:** the existing engine (ADR 0004/0008/0012) with the same settings, exclusions and 2-per-artist cap as For you.
- **Facts:** the catalog.
- **Saves:** the existing library code.

The model never invents albums, and the album cards on the page are built only from ids the tools returned.

## Stack change: Gemini through `google-genai`
- **Provider:** Google Gemini API, free tier via Google AI Studio.
- **SDK:** the official `google-genai` Python package, pinned `>=2.34,<3`. Version 3 changes function calling.
- **Model:** `gemini-3.5-flash-lite` by default, set with `GEMINI_MODEL`. Checked against Google's docs on 2026-11-03:
  - It is a stable free-tier model, described as the fastest and most cost-effective 3.5 model.
  - `gemini-3.8-flash` is also free and may handle tools better. It is the first thing to try if answers disappoint.
  - `gemini-2.5-flash` is deprecated: from 2026-12-01 its requests go to `gemini-3.5-flash-lite`.
- **API:** `generate_content` with a manual tool loop, not the newer Interactions API that the docs now lead with.
  - Its request and response types are fully typed in the pinned SDK.
  - It keeps no conversation state on Google's servers. The Interactions API stores state by default, and its stateless Python form wasn't clearly documented.
  - Automatic function calling is off. Each round's model content is passed back unchanged, which carries Gemini 3's thought signatures.
- **No paid features:** no grounding, search, caching or other paid features. Thinking level defaults to `low` (`GEMINI_THINKING_LEVEL`).
- **Swappable:** only `backend/app/chat/gemini.py` knows about Gemini. `provider.py` defines the interface (`ChatProvider.respond`, `ProviderError` kinds), so another provider is one more module.

## Tools (`backend/app/chat/tools.py`)

| Tool | Does |
|---|---|
| `search_catalog` | Albums and artists by title, name or genre. This is how the model gets ids |
| `get_album_details` | Year, genres, up to 25 track titles, listener count, the user's rating and lists, and "listeners also love" |
| `get_taste_profile` | Favorites, likes, dislikes, top genres and artists, and lists with counts |
| `recommend_albums` | The engine. Options: count 1-20; popularity = the four For you steps; genre; year range; `like_album_ids` / `like_artist_ids` seeds; `outside_my_taste` |
| `compare_listeners` | How many listeners of each album also have a reference album or artist |
| `save_albums` | Add albums to Listen later or a named list, creating it only when asked |

- **Validation:** each tool validates its arguments. Errors go back to the model as `{"error": ...}` so it can correct itself. An unknown id is an error, never a guess.
- **Ownership:** everything acts for the session's user. Lists are looked up among that user's own lists only.
- **No raw access:** there is no SQL and no access to other users' data.

### Mapping requests onto the engine
- **Taste labels:**
  - "Favorites" = 4.5-5★.
  - "Disliked" = 2★ or less.
  - Dismissals stay "not interested", which is exclusion only (ADR 0010).
  - Favorites were removed in ADR 0009.
- **Default query:** the For you query, ratings of 3★ and up weighted by stars (`routes.liked_seeds`). The exclusions are rated, listed and dismissed albums (`routes.excluded`), plus albums already recommended in this conversation, so refinements bring new ones.
- **"Less mainstream":** a later popularity step (ADR 0012 caps).
- **"Like Radiohead" / "like this album":** those albums, or the artist's 5 most-listened albums, become the query. They and all the artist's albums are excluded, so the result is other artists.
- **Genre and year:** the engine has no filters, so the top 250 candidates are filtered by catalog genre and year.
  - If a genre leaves too few, its 10 best-known albums are added to the query.
  - Those seeds are then excluded, so the well-known classics of a genre don't come back.
  - If it is still short, the reply says so.
- **"Something different":** the query is the best-known albums of the 3 most-listened site genres that aren't among the user's top 6. Results tagged with the user's top genres are dropped. This is exploration, and the reply describes it that way, not as taste-matched.
- **No usable ratings:** the most-listened albums, as on For you, labelled as such.

### Explanations (`Engine.explain`, `Engine.listeners_of`)
For each recommended album, the "why" fields are:
- how many of the query's 100 nearest historical listeners have it
- which seed albums those same listeners have, most shared first, with the user's own rating
- the engine score
- the album's listener count

`compare_listeners` counts overlap with a reference album or artist. Historical users only ever appear as counts. The ranking itself is unchanged: `recommend` was only refactored to share `_seeds`. The prompt tells the model to explain only from these fields and never to invent counts, scores or listeners.

Measured on the full data, a tool call takes 2-30 ms, or up to about 350 ms for capped, artist or "different" queries and listener comparisons.

## What is sent to Google
Each request carries:
- the instructions
- a short taste summary: up to 12 favorites, 6 likes and 5 dislikes (titles, artists, stars), top genres, and list names with counts
- the last 10 messages, with the titles and ids of albums each answer showed
- the user's new message
- tool results: catalog facts, listener counts and the user's own ratings

Never sent: emails, user or session ids, conversation ids, or historical user ids.

### Free-tier terms (checked 2026-11-03, superseded 2026-11-07: the owner moved to the paid tier, see Revision below)
- **Data use:** Google may use free-tier prompts and responses to improve its products, and human reviewers may read them. The terms say not to submit sensitive, confidential or personal information. The Ask page says this under the input box.
- **Age:** users must be 18+, and the app must not be aimed at under-18s.
- **Region:** apps offered to users in the **EEA, Switzerland or the UK may use only paid services**. Local development is fine. A public deployment (M9) must either keep Ask away from those users or move to the paid tier.
- **Licensing review:** album metadata goes to Google, and genres are CC BY-NC-SA (ADR 0005). Listener counts come from the dataset, whose licensing is still unverified. Both join the pre-deployment licensing review.
- **Billing:** create the key in a Google Cloud project without billing, so usage can't move to paid.

## Limits and errors (`backend/app/chat/service.py`, `gemini.py`)
- **Messages:** up to 1,000 characters. Up to 4 model requests per message: 3 tool rounds, then a final request with tools off. Output is capped at 1,500 tokens (`GEMINI_MAX_OUTPUT_TOKENS`).
- **Per user:** 5 messages a minute, 50 a day (25 since 2026-11-07, plus a per-device limit: see Revision), one reply in progress at a time. Set with `INROTATION_CHAT_PER_MINUTE` and `_PER_DAY`. Counts come from Postgres, so they hold with several server processes; the one-at-a-time guard is per process.
- **Site daily budget:** `GEMINI_DAILY_CALLS` (default 200) model requests per Pacific day, counted from stored messages. A message is refused when it might not fit. **Set it under the requests-per-day figure AI Studio shows for the project.** Google's docs no longer publish the numbers, and limits are per project, resetting at midnight Pacific.
- **Google's 429 errors:**
  - A daily-quota 429 (`...PerDay...` quota id) closes the assistant until the next Pacific midnight, with no retries.
  - A per-minute 429 is retried once if Google asks for a wait of 10 s or less. Otherwise the user sees "busy, try in a minute".
- **Server and network errors** get 2 retries with backoff. The SDK's own retries are off, so every request is counted.
- **Other errors:** a rejected key or unknown model, a safety block, or an empty answer each give a specific message (503, 422 or 502).
- **Failed turns:** a failed turn keeps the user's message, which counts toward the limits, and drops anything its tools saved, because the user never saw a confirmation. It is left out of later history.

## Conversations (migration 0005)
- **Tables:**
  - `conversations(id, user_id, title, created_at, updated_at)`
  - `chat_messages(id, conversation_id, role, content, albums JSON, action JSON, model_calls, created_at)`
- **Privacy:** only the owner can read, post to or delete a conversation; anyone else gets 404.
- **Sign-in:** signing in moves an anonymous browser's conversations into the account, like the rest of the library.
- **No summary:** there is no running conversation summary, because producing one would cost an extra request. The 10-message window plus the list of albums already shown cover follow-ups like "those" and "the second one".
- **Where the shown albums go (fixed 2026-11-03):** at first, each earlier answer in the history had an "(Albums shown: ... [id ...])" note appended. Gemini copied that format into a new reply, and the ids reached the page. Now the history holds exactly what was said. The albums each answer showed go in the system prompt as a numbered list, marked as reference only. As a safeguard, `clean_reply` strips any such note or "(id ...)" from answers before they are stored or shown, which also cleans answers saved before the fix.

## API
- `GET /api/chat/status`: `{enabled, provider, model, maxChars}`. Disabled when `GEMINI_API_KEY` is empty.
- `POST /api/chat`: send `{conversationId | null, message}`, get back `{conversation, messages: [user, assistant]}`. Messages are `{id, role, text, albums: [Album], action, createdAt}`.
- `GET /api/chat/conversations` lists the 30 most recent conversations.
- `GET` and `DELETE /api/chat/conversations/{id}`.

## Page (`web/src/pages/Ask.tsx`)
- **Navigation:** an "Ask" link in the header.
- **Empty state:** suggested prompts.
- **Messages:**
  - User messages are right-aligned bubbles. Assistant messages have an amber rule.
  - The assistant's text supports paragraphs, "-" lists and bold, rendered without HTML.
  - Albums appear as the existing cards, with cover, rating badge, listen later and a link to the album, plus the year.
- **While waiting:** a typing indicator, honouring reduced motion.
- **Saves:** a save shows "Saved to X" with **Undo**. Undo uses the existing list routes and deletes the list if the assistant created it.
- **Conversations:** "Earlier chats" and "New chat". The current conversation is remembered in `localStorage` (`inrotation.chat`).
- **Errors:** errors and limits show the API's message, with Try again for temporary failures.
- **Notices:** the free-tier data-use note sits under the input box. When no key is set, the page shows setup instructions.

## Revision: making lists (2026-11-03, owner report)
Ask showed albums for "Make a 1980s playlist" but saved nothing, and "Save these albums to a list" saved only the three albums the reply named, to Listen Later. Fixes:
- `recommend_albums` takes `save_to_list`: when the user asks to make or fill a list or playlist, the recommendations are saved to that list (created if needed) in the same step, so the model can't stop after showing them.
- The prompt and `save_albums` description say that "these" or "those" means every album in the latest answer, that "a list" means a new custom list with a fitting name, and that only "listen later" means Listen Later.
- Checked live: "Make a 1980s playlist" created "1980s Playlist" with all 10 albums, and "Save these albums to a list" after a 90s hip hop request created "90s Hip Hop" with all 10. Undo still removes a list the assistant made.

## Known limits
- **Saves rely on instructions:** the model is told to save only when the user explicitly asks. The backend can't verify intent, so every save is shown with Undo.
- **Answer quality depends on the model.** Nothing has been checked against Gemini at the time of writing: all tests use a scripted fake, and one live test (`tests/test_gemini_live.py`) runs only on request.
- **Narrow requests can come back short:** genre and year filters work on the engine's top 250, so requests like "1990s dream pop" may return fewer albums than asked.
- **"Something different" is weakly personal:** collaborative filtering can't model "unlike me".

## Revision (2026-11-07): paid tier and per-device limits
- **Paid tier:** the owner turned on billing. The model stays `gemini-3.5-flash-lite` ($0.30 / $2.50 per million input / output tokens). On the paid tier Google doesn't use prompts or responses to improve its products, so the free-tier notes above (data use, 18+, EEA/UK/Switzerland) no longer apply. The Ask page and Data Sources say so. `GEMINI_DAILY_CALLS` is now a spending cap, not a quota guard.
- **Daily limits (owner request):** each account, or anonymous browser, gets `INROTATION_CHAT_PER_DAY` (25) messages per Pacific day, and each device gets `INROTATION_CHAT_PER_DEVICE_PER_DAY` (40) across all its browsers and accounts. Before, the daily count came from stored messages, so deleting a chat or opening a private window started it again. Now counts live in `chat_usage` (migration 0011), one row per day and key, deleted after a day.
- **Device = network address.** It's the only device signal the server has that a visitor can't simply clear. The address is never stored: the key is an HMAC with `INROTATION_SECRET`, and IPv6 counts by /64. Without the secret, a random key is made at each start. A household or office behind one address shares the device limit, which is why it's higher than the per-account one. A visitor who switches networks (phone data, VPN) gets a new device count. That gap is accepted: the site-wide `GEMINI_DAILY_CALLS` still caps total spending.
- **Behind a proxy** the API must trust the proxy's forwarded address (uvicorn `--proxy-headers --forwarded-allow-ips`), or every visitor shares one device count. This is a deployment step for M9.

## Revision (2026-11-10): item kNN (ADR 0028)
`recommend_albums`' `why` now carries the listeners who have a query album and also have the pick, plus each query album's share of its score (`most_similar_query_albums`), instead of the 100 nearest listeners. The prompt says to explain picks by which of the user's albums they are most similar to.
