import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { InfoPage, InfoSection } from "../components/InfoPage";
import { Tabs, useTab } from "../components/Tabs";
import Technical from "./HowItWorksTechnical";
import { Bars, DotPlot, TuneQuestion } from "../components/TuningCharts";

const RANK_EXAMPLES = [[1, "1.00"], [10, "0.82"], [25, "0.52"], [50, "0.02"]];
const STAR_WEIGHTS = [[5, "1.0"], [4.5, "0.9"], [4, "0.8"], [3.5, "0.7"], [3, "0.6"]];

// Test results behind each setting (docs/experiments.md runs 3, 6 and 7; raw rows in data/experiments). Each chart
// shows a few telling options, not every one tested (owner choice C, 2026-11-09). Since the switch to item kNN
// (ADR 0028), settings chosen for the earlier model were tested again on it (run 7).
const score = (v: number) => v.toFixed(3);
const share = (v: number) => `${Math.round(v * 100)}%`;
const MODELS = [   // run 6, 5,000 test listeners
  { label: "Albums like yours (item kNN)", value: 0.2595, chosen: true },
  { label: "Hidden patterns (ALS)", value: 0.2511, detail: "97% of picks from the most famous 1% of albums" },
  { label: "Listeners like you (user kNN)", value: 0.2405, detail: "What In Rotation used before" },
  { label: "Most popular albums", value: 0.0258 },
];
// Run 7, item kNN: change in ranking score against the chosen half and half (0.2569 with all of a listener's
// albums, 0.1406 with 10). Each option at both query sizes, since the winner flips between them.
const WEIGHTS = [
  { label: "Rank only, all albums", value: 1.05, detail: "0.2596 against 0.2569" },
  { label: "Rank only, 10 albums", value: -3.19, detail: "0.1361 against 0.1406" },
  { label: "Plays only, all albums", value: -1.89, detail: "0.2520 against 0.2569" },
  { label: "Plays only, 10 albums", value: 0.32, detail: "0.1411 against 0.1406" },
];
const change = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`;
const RATINGS = [   // run 7, item kNN, simulated stars as in run 2, all of a listener's albums
  { label: "Every rating the same", value: 0.2569, detail: "0.141 with 10 albums" },
  { label: "A little more for higher stars", value: 0.2633, chosen: true, detail: "0.144 with 10 albums" },
  { label: "Much more for higher stars", value: 0.2564, detail: "0.134 with 10 albums" },
];
const ADJUSTMENT = [   // run 6 tuning, item kNN
  { label: "None", value: 0.2595, chosen: true, detail: "76% of picks from the most famous 1% of albums" },
  { label: "Gentle (0.1)", value: 0.2446, detail: "58% of picks from the most famous 1%" },
  { label: "Moderate (0.25)", value: 0.1364, detail: "24% of picks from the most famous 1%" },
];
const UNDER_THE_RADAR = [   // run 7, under 1,000 listeners, all of a listener's albums as the query
  { label: "Normal list", value: 0.1038 },
  { label: "Leaving out albums over the limit", value: 0.234 },
  { label: "Also leaving out albums under 10 listeners", value: 0.2401, chosen: true },
];
const MATCH = [   // run 7, 10 rated albums: the least share of the listeners who have your albums that must have it
  { label: "0.1% of them", value: 0.765, chosen: true, detail: "Typical score of a loved album 98" },
  { label: "0.3%", value: 0.656, detail: "Typical score 96" },
  { label: "1%", value: 0.488, detail: "Typical score 94" },
  { label: "3%", value: 0.309, detail: "Typical score 89" },
];

/** Each step is said plainly first. The formulas and tables wait behind this toggle (owner choice 2026-11-04, option C). */
function Numbers({ children }: { children: ReactNode }) {
  return (
    <details className="info-numbers">
      <summary>The Numbers</summary>
      {children}
    </details>
  );
}

// Overview for everyone, Technical Details for readers who want the method and evidence (?tab=technical).
const TABS = [{ key: "overview", label: "Overview" }, { key: "technical", label: "Technical Details" }];

export default function HowItWorks() {
  const [tab, select] = useTab(TABS);
  return (
    <InfoPage title="How Recommendations Work"
      lead="In Rotation finds the albums that the same listeners love alongside yours, then suggests the ones you haven't heard.">
      <Tabs tabs={TABS} tab={tab} select={select} label="How Recommendations Work" />
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "technical" ? <Technical /> : <Overview />}
      </div>
    </InfoPage>
  );
}

function Overview() {
  return (
    <>
      <InfoSection step={1} title="Real Listening Data">
        <p>
          It learned from 476,304 real listeners and the 50 albums each of them played most. An album's place in
          someone's list says how much they love it, not just that they have it.
        </p>
        <Numbers>
          <p>Each album in a listener's top 50 gets a weight between 0 and 1, half from its rank and half from its plays.</p>
          <p className="formula">weight = 0.5 × rank score + 0.5 × play score</p>
          <p>
            The rank score falls in a straight line from 1.00 at rank 1 to 0.02 at rank 50. The play score compares the
            album's plays with that listener's most-played album on a logarithmic scale, so a few obsessive replays
            don't swamp everything else. An album outside someone's top 50 counts as unknown, never as disliked. The
            data comes from <Link to="/data-sources">a public dataset</Link>.
          </p>
          <table className="info-table">
            <caption>Rank score</caption>
            <thead><tr><th scope="col">Rank</th>{RANK_EXAMPLES.map(([r]) => <th key={r} scope="col">{r}</th>)}</tr></thead>
            <tbody><tr><th scope="row">Score</th>{RANK_EXAMPLES.map(([r, s]) => <td key={r}>{s}</td>)}</tr></tbody>
          </table>
        </Numbers>
      </InfoSection>

      <InfoSection step={2} title="Your Ratings">
        <p>
          Albums you rate 3 stars or more describe your taste, and higher stars count for more. Lower ratings keep an
          album off your list but don't push you away from similar music.
        </p>
        <Numbers>
          <table className="info-table">
            <caption>Weight of a rating</caption>
            <thead><tr><th scope="col">Stars</th>{STAR_WEIGHTS.map(([s]) => <th key={s} scope="col">{s}</th>)}</tr></thead>
            <tbody><tr><th scope="row">Weight</th>{STAR_WEIGHTS.map(([s, w]) => <td key={s}>{w}</td>)}</tr></tbody>
          </table>
        </Numbers>
      </InfoSection>

      <InfoSection step={3} title="Finding Albums Like Yours">
        <p>
          Two albums are similar when the same people rank both near the top of their lists. Every album is compared
          with the ones you rated across all 476,304 listeners, in a fraction of a second.
        </p>
        <Numbers>
          <p>
            Each album is a list of weights with one slot per listener: 476,304 slots, nearly all empty. Cosine
            similarity compares two albums by the angle between their lists. It's 1 when the same people love both in
            the same proportions and 0 when nobody has both. Because it measures direction rather than size, a hit that
            everyone owns isn't automatically close to everything.
          </p>
        </Numbers>
      </InfoSection>

      <InfoSection step={4} title="Scoring Albums">
        <p>
          An album scores well when it's similar to several of the albums you love, most of all the ones you rated
          highest. Albums you've rated, saved or dismissed are left out, and no artist gets more than two places.
          So are albums too few people have to judge, under 10 listeners or rarely owned by fans of your albums, so
          every pick has a match score.
          "Because you rated" on <Link to="/for-you">For You</Link> names the albums of yours a pick's score comes from.
        </p>
        <Numbers>
          <p className="formula">score = sum over your albums of (rating weight × similarity)</p>
        </Numbers>
      </InfoSection>

      <InfoSection step={5} title="A Fair Chance for Smaller Albums">
        <p>
          Similarity already allows for how many people own each album, so a famous album only scores well when fans of
          your albums love it more than everyone else does. Holding famous albums back any further made picks worse. To
          dig deeper, the How Well Known slider on <Link to="/for-you">For You</Link> keeps only albums under 5,000, 1,000
          or 200 listeners. Diversify, next to the filters, picks each album for being unlike the ones above it too, so
          more corners of your taste show up.
        </p>
      </InfoSection>

      <InfoSection title="Match Scores">
        <p>
          Album pages show how well an album fits your taste, out of 100. Its score is compared with the albums that at
          least 0.1% of the listeners who have your albums also have, and a 92 means it beats 92% of them. Your own
          rating of that album is left out, so it can't inflate the score.
        </p>
      </InfoSection>

      <InfoSection title="How Well It Works">
        <p>
          The method was chosen by testing. For 5,000 listeners, a fifth of their albums were hidden and the rest used as
          their taste. In Rotation's top 20 found the hidden albums about ten times as well as a list of the most popular
          albums, and about six times as well with only 10 albums to go on. Six ways of recommending were tested, and
          comparing albums beat comparing listeners, the method In Rotation used before, by 8%.
        </p>
        <p>
          It has limits. The data is a snapshot, so new releases aren't in it. Albums very few people listed can't be
          recommended with confidence. And it can only find albums that fans of your albums already found. For something
          different, try <Link to="/ask">Ask</Link>.
        </p>
      </InfoSection>

      <InfoSection title="How Each Setting Was Chosen">
        <p>
          Every setting was picked by testing. Some of each test listener's albums were hidden, recommendations were
          made from the rest, and the setting that found the hidden albums best won. Most charts use a ranking score
          from 0 to 1 that rewards finding hidden albums near the top of the first 20. Hover over a bar or dot for its
          exact value. The full method and results are under <Link to="/how-recommendations-work?tab=technical">Technical Details</Link>.
        </p>
        <div className="tune-charts">
          <TuneQuestion question="Should it compare you with other listeners, or compare albums?" answer="Compare albums."
            chart={<Bars rows={MODELS} max={0.3} ticks={[0, 0.1, 0.2, 0.3]} format={score} label="Ranking score by way of recommending" unit="ranking score" />}>
            Six methods were tested on the same listeners. Comparing albums found 8% more of what people love than
            comparing listeners, recommended a wider range of albums, and stayed ahead with only 10 albums to go on.
          </TuneQuestion>

          <TuneQuestion question="What matters more, where an album sits in someone's top 50 or how often they play it?" answer="Both count equally."
            chart={<Bars rows={WEIGHTS} min={-4} max={2} ticks={[-4, -2, 0, 2]} format={change} label="Change in ranking score against counting both equally" unit="against counting both" />}>
            Rank alone did best when a listener had all their albums to go on, 1% ahead. With only 10 albums it did
            worst, 3% behind, and plays alone came out ahead instead. Most people here rate far fewer than 50 albums, so
            the 10-album result matters more, and counting both stays close to the best either way.
          </TuneQuestion>

          <TuneQuestion question="Should a 5-star album count for more than a 3-star one?" answer="Yes, a little more."
            chart={<DotPlot rows={RATINGS} min={0.254} max={0.266} ticks={[0.254, 0.258, 0.262, 0.266]} format={score} label="Ranking score by rating weights" unit="ranking score" />}>
            Counting higher ratings a little more found the most of what people love, with a full list and with only 10
            albums. Counting 3-star albums for almost nothing found less, because they still say something about your
            taste.
          </TuneQuestion>

          <TuneQuestion question="Should famous albums be held back?" answer="No."
            chart={<Bars rows={ADJUSTMENT} max={0.3} ticks={[0, 0.1, 0.2, 0.3]} format={score} label="Ranking score by popularity adjustment" unit="ranking score" />}>
            Comparing albums already allows for how many people own them. Holding famous albums back on top of that found
            less of what people love, and a moderate push cut it in half.
          </TuneQuestion>

          <TuneQuestion question="How does How Well Known find smaller albums you'll like?" answer="It leaves out albums with more listeners than the limit."
            chart={<Bars rows={UNDER_THE_RADAR} max={0.25} ticks={[0, 0.1, 0.2]} format={score} label="Loved albums under 1,000 listeners found in the top 20" unit="of loved smaller albums found" />}>
            Leaving out albums over the limit and ranking the rest as usual finds more than twice as many of the smaller
            albums people love. Also leaving out albums with under 10 listeners helps a little more. The chart shows Under
            the Radar, and the other steps behaved the same.
          </TuneQuestion>

          <TuneQuestion question="Which albums is a match score measured against?" answer="Albums enough fans of your albums have."
            chart={<Bars rows={MATCH} max={1} ticks={[0, 0.25, 0.5, 0.75, 1]} format={share} label="Loved albums that get a match score" unit="of loved albums scored" />}>
            An album needs at least 0.1% of the listeners who have your albums to have it as well. That scores three in four
            of the albums people love, and a score of 95 or more is over 200 times likelier to be one than a score under
            50. Stricter limits leave more of them without a score.
          </TuneQuestion>
        </div>
      </InfoSection>
    </>
  );
}
