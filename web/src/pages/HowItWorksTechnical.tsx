import type { ReactNode } from "react";
import { InfoSection } from "../components/InfoPage";
import { Bars } from "../components/TuningCharts";

/**
 * How Recommendations Work, Technical Details tab (owner request 2026-11-09, refocused the same day on testing
 * between models): the model comparison of docs/experiments.md run 6 (recs/compare.py, raw rows in
 * data/experiments/compare.json and compare_tuning.csv) that switched the site to item kNN (owner decision
 * 2026-11-10, ADR 0028), the checks of run 7, then the served model, the data and the feature experiments.
 */

const n = (v: number) => v.toLocaleString("en");
const score = (v: number) => v.toFixed(3);
const signed = (v: number) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(3);

const FAMILIES: [string, string][] = [
  ["Popularity", "The most-listened albums, the same for everyone. The floor every model must clear."],
  ["User kNN", "Cosine similarity between your ratings and every listener's top 50, then a weighted sum over the 100 nearest. What the site ran until this test."],
  ["Item kNN (served)", "Each album scores by its summed cosine similarity to the albums you rated, with similarity measured over listeners. Computed as (q Cᵀ) C with C column-normalized, so no 633K × 633K album matrix is stored. What the site runs now."],
  ["RP3beta", "A three-step random walk, album to listener to album, on the who-has-what matrix, divided by popularity to the power β (Paudel et al. 2017)."],
  ["PureSVD", "A truncated SVD of the weight matrix. Your ratings are projected onto the top k factors and back (Cremonesi et al. 2010)."],
  ["ALS", "Implicit-feedback matrix factorization (Hu, Koren and Volinsky 2008) through the implicit library. A new listener is folded in with one least-squares solve."],
];

// Held-out sample (seed 1), full queries. Paired differences against user kNN (served until run 6), 95% intervals.
const ACCURACY = [
  { label: "Item kNN (served)", value: 0.25946, chosen: true },
  { label: "ALS, 256 factors", value: 0.25107 },
  { label: "User kNN (previous)", value: 0.24050 },
  { label: "RP3beta", value: 0.20555 },
  { label: "PureSVD, 256 factors", value: 0.18232 },
  { label: "Popularity", value: 0.02575 },
];
const DIFF_FULL = [
  { label: "Item kNN", value: 0.01896, spread: 0.00284 },
  { label: "ALS, 256 factors", value: 0.01057, spread: 0.00421 },
  { label: "RP3beta", value: -0.03495, spread: 0.00384 },
  { label: "PureSVD, 256 factors", value: -0.05819, spread: 0.00444 },
];
const DIFF_TEN = [
  { label: "Item kNN", value: 0.00409, spread: 0.00225 },
  { label: "ALS, 256 factors", value: -0.00163, spread: 0.00284 },
  { label: "RP3beta", value: -0.00293, spread: 0.00319 },
  { label: "PureSVD, 256 factors", value: -0.04491, spread: 0.00320 },
];

const RESULTS: string[][] = [
  ["Popularity", "0.026", "0.030", "0.22", "35", "100%", "0 s", "5 ms"],
  ["User kNN, K 100, β 0.25 (previous)", "0.240", "0.228", "0.82", "20,161", "75%", "1 s", "5 ms"],
  ["Item kNN, β 0 (served)", "0.259", "0.251", "0.86", "23,368", "75%", "1 s", "32 ms"],
  ["RP3beta, β 0.1", "0.206", "0.202", "0.78", "19,182", "82%", "0.5 s", "33 ms"],
  ["PureSVD, 256 factors", "0.182", "0.175", "0.70", "2,693", "100%", "47 s", "5 ms"],
  ["ALS, 256 factors, α 20", "0.251", "0.245", "0.83", "6,632", "97%", "12 min", "6 ms"],
];

// Tuning sample (seed 0), NDCG@20 per setting (data/experiments/compare_tuning.csv).
const TUNING: string[][] = [
  ["User kNN", "K 50, 100, 200 × β 0, 0.25", "K 100, β 0.25: 0.238", "K 200, β 0: 0.225", "Flat. The settings chosen in run 1 still come out on top."],
  ["Item kNN", "β 0, 0.1, 0.25", "β 0: 0.260", "β 0.25: 0.136", "Very sensitive to the popularity adjustment. β 0.1 already costs 0.015."],
  ["RP3beta", "β 0.1, 0.25, 0.4", "β 0.1: 0.201", "β 0.4: 0.153", "β 0.25 recommends 2.5× the distinct albums for almost the same score."],
  ["PureSVD", "256 factors, then 128 and 512", "256: 0.183", "128: 0.175", "Peaks in the middle. More factors don't help."],
  ["ALS", "64 to 256 factors × α 20, 40, 15 iterations", "256, α 20: 0.251", "64, α 20: 0.194", "Still rising at the largest size tried, which takes 12 minutes to fit."],
];

const PIPELINE: [string, string, string][] = [
  ["Raw rows", n(23822550), "476,451 listeners, up to 50 albums each, with rank and play count"],
  ["Invalid rows dropped", n(28766), "17 with no album or artist name, 28,749 empty after normalizing"],
  ["Album identity", `${n(1830875)} → ${n(1656172)}`, "Distinct artist and title pairs merged into normalized keys: accents, case and punctuation folded, edition tags (Deluxe, Remastered, Anniversary...) stripped"],
  ["Duplicates within a listener", n(268860), "Rows merged into one, keeping the best rank and summing plays"],
  ["Albums with 1 listener", n(1023118), "Removed: one listener can't link anyone to anyone"],
  ["Listeners with under 5 albums", n(147), "Removed after the album filter"],
  ["Kept", `${n(476304)} × ${n(633053)}`, "22,501,513 listener-album pairs, 0.0075% of the matrix filled, median 49 albums per listener"],
];

const EXPERIMENTS: string[][] = [
  ["1. Parameter sweep", "Which weights, neighbourhood size, aggregator and popularity adjustment?",
    "80 settings in three stages. K 200 → 100 plus β 0.25: +0.0140 ± 0.0023 NDCG@20. Plays-only weights and asymmetric cosine: +0.0012 ± 0.0013, noise.",
    "Linear rank and plays, α 0.5, cosine, K 100, weighted sum, β 0.25"],
  ["2. Rating weights", "Should higher star ratings weigh more in the query?",
    "Ratings simulated from rank buckets, 3 seeds. Gentle +0.0044 ± 0.0009 NDCG@20 over equal weights, steep −0.0020 ± 0.0020.",
    "5★ 1.0, 4★ 0.8, 3★ 0.6, half stars interpolated, under 3★ excluded"],
  ["3. Less popular picks", "How should How Well Known find smaller albums people love?",
    "Recall@20 of loved albums under 1,000 listeners: listener cap without the adjustment 0.161, stronger adjustment (β 0.5) 0.088, uncapped 0.096.",
    "Caps of 5,000, 1,000 and 200 listeners, β 0 inside a cap, 10-listener floor"],
  ["4. Match score", "How many neighbours make a calibrated 0-100 score?",
    "300 neighbours, 2 must hold the album: 64.7% of loved albums scored, median 92, scores of 95-100 are 36× likelier to be loved than scores under 50.",
    "Percentile among albums the 300 nearest listeners hold, no adjustment"],
  ["5. Filtered lists", "Do filters need a wider neighbourhood?",
    "Recall@240 inside the filter, K 100 against K 1,000: jazz 0.54 → 0.73, 1990s electronic 0.54 → 0.91. The first run leaked each listener into their own neighbourhood and scored about 1.0, so it was rerun with them excluded.",
    "Filtered lists rank by K 1,000, fill from K 5,000"],
  ["6. Model comparison", "Is user kNN the right model?",
    "Six families on one split. Item kNN +0.0190 ± 0.0028 NDCG@20, ALS +0.0106 ± 0.0042, RP3beta and PureSVD worse.",
    "Switch to item kNN, no popularity adjustment"],
  ["7. Item kNN checks", "Do the settings chosen for user kNN still hold?", "Rank and plays half and half within 0.003 of the best at both query sizes. Gentle star weights best at both. Caps with the 10-listener floor best at every cap. Match support of 0.1%: 76% of loved albums scored, median 98. With 3 albums, 21% of picks had under 10 listeners, and leaving thinly held albums out raised NDCG@20 from 0.085 to 0.092.",
    "All kept, plus a 0.1% match reference set, and picks limited to albums with 10+ listeners that the match score can score"],
  ["8. Diversify", "How strong should the Diversify button be?",
    "Maximal marginal relevance over the best 500 picks. Strength 0.7: picks 75% less alike, 87% of rated albums lead a pick, NDCG@20 −5% on full queries and −27% with 10 albums. Strength 0.5 kept more accuracy (+7% full, −4% with 10) but left picks closer together.",
    "Strength 0.7, only when the button is on"],
  ["9. Support for smaller albums", "Why was Deep Cuts short of picks?",
    "0.1% of the listeners who have your albums is more than most albums under 200 listeners have in all, so 29% of Deep Cuts lists (10 albums) couldn't fill. Allowing 5% of an album's own listeners: smaller albums found 0.151 → 0.181, 1% short, Anything unchanged or better.",
    "0.1% of those listeners or 5% of the album's own, whichever is fewer"],
];

function Table({ head, rows, caption }: { head: string[]; rows: string[][]; caption: string }) {
  return (
    <div className="table-scroll">
      <table className="info-table tech-table">
        <caption>{caption}</caption>
        <thead><tr>{head.map((h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
        <tbody>{rows.map((r) => <tr key={r[0]}>{r.map((c, i) => i === 0 ? <th key={i} scope="row">{c}</th> : <td key={i}>{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function Chart({ title, why, children }: { title: string; why?: string; children: ReactNode }) {
  return (
    <div className="tune-charts">
      <div className="tune-qa">
        <h3 className="tune-q">{title}</h3>
        {why && <p className="tune-why">{why}</p>}
        <div className="tune-chart">{children}</div>
      </div>
    </div>
  );
}

export default function Technical() {
  return (
    <>
      <InfoSection title="Six Models, One Test">
        <p>
          The site first recommended with user-based collaborative filtering. To check that choice, five other
          recommender families were run through exactly the same test: same listeners, same hidden albums, same weight matrix, same
          metrics. Each had to recommend for listeners it never saw in training, the way the site meets a new user, so
          the factor models fold a new listener in rather than look up a trained row.
        </p>
        <dl className="source-list">
          {FAMILIES.map(([name, what]) => <div key={name}><dt>{name}</dt><dd>{what}</dd></div>)}
        </dl>
        <p>
          EASE, a strong item-based model, was left out: it needs a dense album × album matrix, 633K × 633K here, about
          1.6 TB in float32.
        </p>
      </InfoSection>

      <InfoSection title="How They Were Tested">
        <p>
          Leave-out evaluation on the historical listeners, the only ground truth the data has. For each test listener a
          random 20% of their albums are hidden, the rest form the query, and the hidden albums are the right answers.
          Test listeners are removed from the training matrix first. Each family was tuned on one sample of 5,000
          listeners and then scored once on a different 5,000, so no model was tuned on the listeners it's judged on.
        </p>
        <dl className="source-list">
          <div><dt>NDCG@20</dt><dd>Discounted cumulative gain of the top 20 (relevance 1 for a hidden album, discounted by log2 of its position), divided by the best possible. Rewards finding hidden albums and ranking them high. The main metric.</dd></div>
          <div><dt>Recall and Hit Rate@20</dt><dd>Share of the hidden albums that make the top 20, and share of listeners with at least one there.</dd></div>
          <div><dt>Distinct Albums and Head Share</dt><dd>How many different albums the model recommends across all 5,000 listeners, and the part of its picks taken from the 1% most-listened albums (6,331). Accuracy alone rewards recommending hits.</dd></div>
          <div><dt>Paired Difference</dt><dd>Each model's NDCG@20 minus user kNN's, per listener, averaged, with a 95% interval (1.96 standard errors). Both models face the same listeners, so the pairing removes most of the noise.</dd></div>
          <div><dt>10-Album Check</dt><dd>The same listeners with only 10 albums in the query, closer to a new site user than the full ~38.</dd></div>
        </dl>
      </InfoSection>

      <InfoSection title="Results">
        <Chart title="NDCG@20 on the 5,000 test listeners">
          <Bars rows={ACCURACY} max={0.3} ticks={[0, 0.1, 0.2, 0.3]} format={score} label="NDCG@20 by model" unit="NDCG@20" />
        </Chart>
        <Chart title="Difference from user kNN, full queries"
          why="Per-listener paired differences with 95% intervals. Popularity is left off the scale at −0.215.">
          <Bars rows={DIFF_FULL} min={-0.07} max={0.03} ticks={[-0.06, -0.04, -0.02, 0, 0.02]} format={signed} label="NDCG@20 difference from user kNN, full queries" unit="NDCG@20" />
        </Chart>
        <Chart title="Difference from user kNN, 10-album queries"
          why="With fewer albums to go on, only item kNN stays ahead, and by less.">
          <Bars rows={DIFF_TEN} min={-0.07} max={0.03} ticks={[-0.06, -0.04, -0.02, 0, 0.02]} format={signed} label="NDCG@20 difference from user kNN, 10-album queries" unit="NDCG@20" />
        </Chart>
        <Table caption="Test listeners, full queries. Query time is per listener in batches of 200."
          rows={RESULTS} head={["Model", "NDCG@20", "Recall@20", "Hit Rate@20", "Distinct Albums", "Head Share", "Fit", "Query"]} />
      </InfoSection>

      <InfoSection title="What the Results Say">
        <p>
          <strong>Item kNN won, which is what the site uses.</strong> It came out 7.9% ahead of user kNN on full
          queries (0.019 NDCG@20, give or take 0.003, so not a fluke) and 3% ahead when listeners had only 10 albums.
          It recommended more different albums than user kNN (23,368 against 20,161)
          and leaned on hits no more than before. The price is speed, since each query
          runs through the whole listener matrix twice, about 32 ms a listener against 5 for user kNN, which is still quick enough
          for a page.
        </p>
        <p>
          <strong>ALS looked good until I checked what it was picking.</strong> At 256 factors it beat user kNN on full
          queries and tied it with 10 albums. But 97% of its picks came from the 1% most-listened albums, and it
          covered a third as many albums overall. A list like that is accurate partly because everyone already knows
          those records, which isn't much use on a discovery site. It also took 12 minutes to train and was still
          getting better at the biggest size I tried. PureSVD has the same pull toward hits, with less accuracy.
        </p>
        <p>
          <strong>RP3beta is the adventurous one.</strong> It trailed on full queries by 0.035 but was within the margin
          of error with 10 albums. Turned toward less popular albums (β 0.25), it reached two and a half times as many
          different albums as its best setting, at some cost to accuracy.
        </p>
        <p>
          <strong>User kNN did fine, just not well enough.</strong> It came third for accuracy and was one of the fastest.
          Switching wasn't free, though. Because You Rated, the match score and filtered lists were all built on its
          nearest listeners, so each had to be rebuilt around album similarity and tested again (run 7, below).
        </p>
      </InfoSection>

      <InfoSection title="Tuning Each Model">
        <p>
          Every family got a small grid on the tuning sample, and its best setting went to the test. The popularity
          adjustment that helps user kNN hurts the item-based and factor models, so they were tested without it.
        </p>
        <Table caption="NDCG@20 on the tuning sample" head={["Model", "Grid", "Best", "Worst", "Note"]} rows={TUNING} />
      </InfoSection>

      <InfoSection title="The Served Model">
        <p>Each listener u gives a weight to every album a in their top 50:</p>
        <p className="formula">w(u, a) = α · (1 − (rank − 1) / 50) + (1 − α) · log(1 + plays) / log(1 + max plays of u),  α = 0.5</p>
        <p>An album is the column of those weights across all 476,304 listeners, and two albums are compared by cosine:</p>
        <p className="formula">sim(a, b) = Σ over listeners of w(u, a) · w(u, b)  ÷  (‖w(·, a)‖ ‖w(·, b)‖)</p>
        <p className="formula">score(b) = Σ over your rated albums a of q(a) · sim(a, b)</p>
        <p>
          Your ratings of 3 stars and up form the query q, weighted 1.0 for 5 stars down to 0.6 for 3. Columns are scaled
          to length 1 once at startup, so scoring every album is (q Cᵀ) C: two sparse products through the listeners,
          with no 633K × 633K similarity matrix stored. Albums with under 10 listeners, or held by under 0.1% of the
          listeners who have one of your albums, are left out: with few ratings, cosine otherwise favours albums with
          two or three listeners who all share them (run 7). A smaller album may instead be held by 5% of its own
          listeners (and 3), since 0.1% of a big audience can be more than a Deep Cut's whole audience (run 9). A first page takes about 120-250 ms on the full data and later
          pages about 50, because scores are cached per taste. The list is then re-ranked: rated, saved and dismissed
          albums are removed, no artist gets more than two places, and editions merge. Every album has a score, so a
          For You filter only narrows the ranking, with no wider neighbourhood needed.
        </p>
        <p>
          The same scores drive the rest of the site. Listeners Also Love on an album page is the albums most similar to
          it. Because You Rated names the rated albums that carry the most of a pick's score, first the ones the pick
          stands out as close to. The match score is the percentile of an album's score among the albums held by at
          least 0.1% of the listeners who have one of your albums (and 3 of them). Any album with that support, or 5% of its
          own listeners, gets a score, so every pick has one.
        </p>
      </InfoSection>

      <InfoSection title="Data and Cleaning">
        <p>
          The dataset gives each listener's 50 most-played albums with rank, play count and an optional MusicBrainz id.
          It has no ratings and no dates. Cleaning runs in DuckDB in about 31 seconds and writes Parquet.
        </p>
        <Table caption="Cleaning steps" head={["Step", "Count", "What happened"]} rows={PIPELINE} />
        <p>
          Albums are identified by normalized artist and title, because the MusicBrainz id names an edition and is blank
          on 24% of rows. Matching model albums to the MusicBrainz catalog covers 92.3% of all listening and 97.1% of
          albums with 1,000 or more listeners. Unmatched albums still help find neighbours but are never shown.
        </p>
      </InfoSection>

      <InfoSection title="Experiments Behind Each Feature">
        <p>Each change to ranking was tested the same way before it shipped. Runs 1-5 tested the user kNN model the site originally used. Run 7 checked their settings again on item kNN, and run 8 tuned Diversify.</p>
        <Table caption="Experiments" head={["Run", "Question", "Result", "Decision"]} rows={EXPERIMENTS} />
      </InfoSection>
    </>
  );
}
