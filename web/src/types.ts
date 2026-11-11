export interface Album {
  id: string;
  title: string;
  artist: string;
  artistId?: string | null;
  year?: number | null;
  genres: string[];
  mbid?: string;
  coverUrl?: string;
  /** ISO 3166 code of the first credited artist's country (MusicBrainz). */
  country?: string | null;
  /** MusicBrainz community rating, 0-5, when anyone has voted. */
  rating?: number | null;
  ratingVotes?: number;
}
