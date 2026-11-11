import type { ReactNode } from "react";
import { InfoPage, InfoSection } from "../components/InfoPage";

const DATASET = "https://www.kaggle.com/datasets/gabrielkahen/music-listening-data-500k-users";

/** Organized around what a visitor sees on the site, not around the sources (owner choice 2026-11-04, option B). */
const SOURCES: [string, ReactNode][] = [
  ["Recommendations, Match Scores and the Album Map", <>
    About 476,000 anonymous listeners and the 50 albums each played most, from{" "}
    <a href={DATASET}>Music Listening Data (~500k Users)</a> by Gabriel Kahen on Kaggle.
  </>],
  ["Titles, Artists, Years, Genres and Track Lists", <>
    <a href="https://musicbrainz.org">MusicBrainz</a>, the open music encyclopedia, from its{" "}
    <a href="https://musicbrainz.org/doc/MusicBrainz_Database/Download">public data downloads</a>. About 390,000 albums.
  </>],
  ["Album Covers", <>
    The <a href="https://coverartarchive.org">Cover Art Archive</a>, a joint project of MusicBrainz and the{" "}
    <a href="https://archive.org">Internet Archive</a>. Covers belong to their owners.
  </>],
  ["Community Ratings", <>MusicBrainz users' ratings, used by the Highest Rated sort.</>],
  ["Listen On Links", <>
    Spotify and Apple Music addresses recorded in MusicBrainz, checked against each service so they open the regular album.
  </>],
  ["Ask's Replies", <>
    <a href="https://ai.google.dev">Google Gemini</a> writes the words. Every album it shows comes from In Rotation's own
    catalog and recommendations.
  </>],
];

export default function DataSources() {
  return (
    <InfoPage title="Data Sources" lead="Every part of an album page comes from somewhere. Here's where.">
      <InfoSection title="What You See, and Where It's From">
        <dl className="source-list">
          {SOURCES.map(([what, from]) => (
            <div key={what}>
              <dt>{what}</dt>
              <dd>{from}</dd>
            </div>
          ))}
        </dl>
      </InfoSection>

      <InfoSection title="Who's Behind the Numbers">
        <p>
          The listeners in the dataset are anonymous and never shown. You'll only see them through what they add up to,
          like a match score or how many listeners an album has. The data is a snapshot, so albums released after it was collected can't be
          recommended yet.
        </p>
      </InfoSection>

      <InfoSection title="What Leaves This Site">
        <p>
          When you use Ask, your messages and a short summary of your ratings and lists go to Google to write each reply.
          Google doesn't use them to improve its products.
        </p>
        <p>Opening a Listen On link sends nothing about you. Your email is never sent anywhere.</p>
      </InfoSection>

      <InfoSection title="Licenses">
        <p>
          MusicBrainz core data is public domain (<a href="https://creativecommons.org/publicdomain/zero/1.0/">CC0</a>).
          Its genres and tags are <a href="https://creativecommons.org/licenses/by-nc-sa/3.0/">CC BY-NC-SA 3.0</a>. See
          the <a href="https://musicbrainz.org/doc/About/Data_License">MusicBrainz data license</a>.
        </p>
      </InfoSection>
    </InfoPage>
  );
}
