from pydantic import BaseModel


class Album(BaseModel):
    id: str                       # release-group MBID
    title: str
    artist: str                   # artist credit as displayed
    artistId: str | None = None   # first credited artist's MBID, for the artist page
    year: int | None = None       # first release year; unknown for some MusicBrainz entries
    genres: list[str] = []
    mbid: str | None = None
    coverUrl: str | None = None   # /api/covers/{id}, the local cover cache; 404 when the archive has no front image
    country: str | None = None    # ISO 3166 code of the first credited artist's country (MusicBrainz)
    rating: float | None = None   # MusicBrainz community rating, 0-5, when anyone has voted
    ratingVotes: int = 0


class Track(BaseModel):
    number: str                   # as printed: "3", "A1"
    title: str
    artist: str | None = None     # only when it differs from the release's credit
    seconds: int | None = None


class Disc(BaseModel):
    position: int                 # 1-based among the release's audio media
    format: str | None = None     # "CD", "12\" Vinyl", "Digital Media"
    title: str | None = None
    tracks: list[Track]


class Tracklist(BaseModel):
    releaseId: str                # the MusicBrainz release the list comes from (ingest.catalog.tracklists)
    discs: list[Disc]
