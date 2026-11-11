import type { Album } from "./types";

export interface AlbumPage { items: Album[]; total: number }
export interface Track { number: string; title: string; artist: string | null; seconds: number | null }
export interface Disc { position: number; format: string | null; title: string | null; tracks: Track[] }
/** One MusicBrainz release's track list (releaseId is the release MBID). */
export interface Tracklist { releaseId: string; discs: Disc[] }
export interface AlbumDetailResponse { album: Album; similar: Album[]; tracklist: Tracklist | null }
/** albums newest first; added: album id -> ISO time it was added. */
export interface AlbumList { id: number; name: string; albums: Album[]; added?: Record<string, string> }
/** rating: 0.5-5 in half stars */
export interface RatedAlbum { album: Album; rating: number }
export interface LibraryResponse { rated: RatedAlbum[]; later: Album[]; lists: AlbumList[]; laterAdded?: Record<string, string> }
/** Your own profile (ADR 0018); null until you make one. */
export interface MyProfile { username: string; displayName: string; avatarUrl: string | null; public: boolean }
export interface Me { email: string | null; profile: MyProfile | null }
/** /users/{username}: anyone's profile page; ratings newest first. */
export interface PublicProfile {
  username: string; displayName: string; avatarUrl: string | null; memberSince: string;
  isYou: boolean; public: boolean; ratings: RatedAlbum[];
}
export interface Artist { id: string; name: string }
export interface ArtistPage { artist: Artist; albums: Album[]; other: Album[]; related: (Artist & { album: Album })[] }
/** `because`: album id -> up to two of your rated album ids that led to it, strongest first. */
export interface RecommendationsResponse { items: Album[]; source: string; total: number; because?: Record<string, string[]> }
/** GET /albums/{id}/match (ADR 0019): how well an album fits your taste; score 0-100 when status is "ok". */
export interface Match {
  status: "ok" | "few_listeners" | "not_in_data" | "no_taste";
  score: number | null; listeners: number | null; withAlbum: number | null; alongside: Album[];
}
/** GET /me/insights (ADR 0017): a profile from the user's ratings, saves and recommendations. */
export interface ArtistStat { id: string | null; name: string; albums: number; averageRating: number | null; album: Album }
export interface Insights {
  overview: { albumsRated: number; artistsExplored: number; genresExplored: number;
              averageRating: number | null; memberSince: string };
  genres: { name: string; albums: number; share: number; averageRating: number | null }[];
  favoriteArtists: ArtistStat[];
  topArtists: ArtistStat[];
  decades: { decade: number; albums: number; averageRating: number | null }[];
  years: { year: number; albums: number }[];
  ratings: { stars: number; albums: number }[];
  topAlbums: { album: Album; rating: number }[];
  recentAlbums: { album: Album; at: string; rating: number }[];
  newArtists: { id: string | null; name: string; at: string; album: Album }[];
  mainstream: { medianListeners: number; band: string } | null;
  /** null on a public profile, which is built from ratings only */
  recommendations: { shown: number; forYou: number; ask: number; rated: number; liked: number; saved: number;
                     dismissed: number; since: string | null } | null;
}
/** Filters for /albums (ADR 0015); every one is optional and they combine. A genre includes its subgenres. */
export interface AlbumQuery {
  q?: string;
  genre?: string;
  year_from?: number;
  year_to?: number;
  artist?: string;
  country?: string;
  type?: string;
  popularity?: string;
  /** For You only: an album length band (ADR 0026). */
  length?: string;
  sort?: string;
  limit?: number;
  offset?: number;
}
/** A genre or subgenre; albums counts its whole family, parent is set for subgenres. */
export interface GenreMatch { name: string; albums: number; parent: string | null }
export interface BrowseOptions {
  decades: { decade: number; albums: number }[];
  countries: { code: string; albums: number }[];
  types: { key: string; label: string; albums: number }[];
  popularity: { key: string; label: string; min: number | null; max: number | null }[];
  sorts: string[];
  rated: number;
  /** Album length bands, For You only (ADR 0026). */
  lengths: { key: string; label: string }[];
}
/** GET /map (ADR 0022): the Album Map, column by column (album i is id[i], x[i], y[i] ...). Positions run 0-1000.
 *  genres and labels refer to positions in those columns; a label's name is a genre, or a country code. */
export interface AlbumMapData {
  builtAt: string;
  albums: { id: string[]; title: string[]; artist: string[]; year: (number | null)[]; listeners: number[]; x: number[]; y: number[] };
  /** members as gaps between sorted positions: -1 + steps[0], + steps[1] ... */
  genres: { name: string; steps: number[] }[];
  labels: { kind: "genre" | "country"; name: string; x: number; y: number; tier: number }[];
}
export interface ChatStatus { enabled: boolean; provider: string | null; model: string | null; maxChars: number }
/** A save the assistant made; enough to undo it (listId null = Listen later). */
export interface ChatAction { kind: "saved"; listId: number | null; listName: string; albumIds: string[]; createdList: boolean }
export interface ChatMessage { id: number; role: "user" | "assistant"; text: string; albums: Album[]; action: ChatAction | null; createdAt: string }
export interface ConversationSummary { id: string; title: string; updatedAt: string }
export interface Conversation extends ConversationSummary { messages: ChatMessage[] }
export interface ChatAnswer { conversation: ConversationSummary; messages: ChatMessage[] }

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// The start-it-yourself hint is for local development only. Visitors to the deployed site get a plain message.
export const OFFLINE_MESSAGE = import.meta.env.DEV
  ? "Can't reach the In Rotation API. Start it from the backend folder with: uvicorn app.main:app --reload"
  : "In Rotation can't be reached right now. Try again in a few minutes.";

const TOKEN_KEY = "inrotation.token";
let memoryToken: string | null = null;
let pendingSession: Promise<string> | null = null;

function storedToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? memoryToken;
  } catch {
    return memoryToken;
  }
}

function saveToken(token: string) {
  memoryToken = token;
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* storage unavailable: token lives for this tab only */
  }
}

function clearToken() {
  memoryToken = null;
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

async function getToken(): Promise<string> {
  const existing = storedToken();
  if (existing) return existing;
  pendingSession ??= fetch("/api/session", { method: "POST" })
    .then(async (r) => {
      if (r.status === 429) {   // too many new sessions from this network (backend auth.LIMITS)
        const body = await r.json().catch(() => null);
        throw new ApiError(429, body?.detail ?? "Too many new visits from this network. Try again in an hour.");
      }
      if (!r.ok) throw new ApiError(r.status, "Could not start a session");
      return r.json() as Promise<{ token: string }>;
    })
    .then(({ token }) => {
      saveToken(token);
      return token;
    })
    .finally(() => {
      pendingSession = null;
    });
  return pendingSession;
}

/** The API's own message for client errors ("Use a password of at least 8 characters"). */
async function errorMessage(res: Response): Promise<string> {
  if (res.status >= 400 && res.status < 500) {
    const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
    if (typeof body?.detail === "string") return body.detail;
  }
  return res.status === 404 ? "Not found" : `Request failed (${res.status})`;
}

async function request<T>(path: string, init: RequestInit = {}, auth = false, retry = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (auth) headers.set("Authorization", `Bearer ${await getToken()}`);
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, OFFLINE_MESSAGE);
  }
  if (res.status === 401 && auth && retry) {
    clearToken(); // server forgot this session (e.g. database reset): start a new one
    return request<T>(path, init, auth, false);
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

async function jsonRequest<T>(path: string, method: string, body: unknown, auth = true): Promise<T> {
  return request<T>(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }, auth);
}

/** Sign in: sends this browser's anonymous session (if any) so the server can merge it, then switches tokens. */
async function login(email: string, password: string): Promise<void> {
  const headers = new Headers({ "Content-Type": "application/json" });
  const current = storedToken();
  if (current) headers.set("Authorization", `Bearer ${current}`);
  let res: Response;
  try {
    res = await fetch("/api/account/login", { method: "POST", headers, body: JSON.stringify({ email, password }) });
  } catch {
    throw new ApiError(0, OFFLINE_MESSAGE);
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  saveToken(((await res.json()) as { token: string }).token);
}

export const api = {
  albums: (p: AlbumQuery = {}) => {
    const qs = new URLSearchParams();
    for (const [key, value] of Object.entries(p)) {
      if (value !== undefined && value !== null && value !== "") qs.set(key, String(value));
    }
    if (!qs.has("limit")) qs.set("limit", "60");
    return request<AlbumPage>(`/albums?${qs}`);
  },
  browseOptions: () => request<BrowseOptions>("/browse/options"),
  genreSearch: (q: string) => request<GenreMatch[]>(`/browse/genres?${new URLSearchParams({ q, limit: "12" })}`),
  album: (id: string) => request<AlbumDetailResponse>(`/albums/${encodeURIComponent(id)}`),
  match: (id: string) => request<Match>(`/albums/${encodeURIComponent(id)}/match`, {}, true),
  genres: () => request<string[]>("/genres"),
  artists: (q: string) => request<Artist[]>(`/artists?${new URLSearchParams({ q, limit: "6" })}`),
  artist: (id: string) => request<ArtistPage>(`/artists/${encodeURIComponent(id)}`),
  library: () => request<LibraryResponse>("/me/library", {}, true),
  setLater: (id: string, on: boolean) =>
    request<void>(`/me/later/${encodeURIComponent(id)}`, { method: on ? "PUT" : "DELETE" }, true),
  setRating: (id: string, stars: number | null) =>
    stars === null
      ? request<void>(`/me/ratings/${encodeURIComponent(id)}`, { method: "DELETE" }, true)
      : jsonRequest<void>(`/me/ratings/${encodeURIComponent(id)}`, "PUT", { rating: stars }),
  setDismissed: (id: string, on: boolean) =>
    request<void>(`/me/dismissed/${encodeURIComponent(id)}`, { method: on ? "PUT" : "DELETE" }, true),
  insights: () => request<Insights>("/me/insights", {}, true),
  /** For You. `filters` narrows it: genre, years, type and album length (ADR 0026). */
  recommendations: (depth = 0, offset = 0, limit = 24, filters: AlbumQuery = {}, diverse = false) => {
    const qs = new URLSearchParams({ depth: String(depth), offset: String(offset), limit: String(limit) });
    if (diverse) qs.set("diverse", "true");   // Diversify (ADR 0029)
    for (const key of ["genre", "year_from", "year_to", "country", "type", "length"] as const) {
      const value = filters[key];
      if (value !== undefined && value !== null && value !== "") qs.set(key, String(value));
    }
    return request<RecommendationsResponse>(`/me/recommendations?${qs}`, {}, true);
  },

  albumMap: () => request<AlbumMapData>("/map"),
  /** Your For You ranking for marking the map; doesn't count as shown. */
  myMap: () => request<{ recommended: string[] }>("/me/map", {}, true),

  me: () => request<Me>("/me", {}, true),
  profile: (username: string) => request<PublicProfile>(`/users/${encodeURIComponent(username)}`, {}, true),
  profileInsights: (username: string) => request<Insights>(`/users/${encodeURIComponent(username)}/insights`, {}, true),
  saveProfile: (p: { username: string; displayName: string; public: boolean }) => jsonRequest<MyProfile>("/me/profile", "PUT", p),
  /** The image goes as the request body; the server crops, resizes and strips it. */
  uploadPicture: (file: File) =>
    request<MyProfile>("/me/profile/picture", { method: "PUT", headers: { "Content-Type": file.type || "application/octet-stream" }, body: file }, true),
  deletePicture: () => request<MyProfile>("/me/profile/picture", { method: "DELETE" }, true),
  /** An account is a profile (ADR 0018): it comes with a username and a name; public is opt-in. */
  register: (p: { email: string; password: string; username: string; displayName: string; public: boolean }) =>
    jsonRequest<Me>("/account/register", "POST", p),
  login,
  logout: async () => {
    if (storedToken()) await request<void>("/account/logout", { method: "POST" }, true, false).catch(() => undefined);
    clearToken();
  },
  /** Delete the signed-in account and everything in it. This browser then starts a new, empty library. */
  deleteAccount: async (password: string) => {
    await request<void>("/account", { method: "DELETE", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }) }, true, false);
    clearToken();
  },

  createList: (name: string) => jsonRequest<AlbumList>("/me/lists", "POST", { name }),
  renameList: (id: number, name: string) => jsonRequest<AlbumList>(`/me/lists/${id}`, "PATCH", { name }),
  deleteList: (id: number) => request<void>(`/me/lists/${id}`, { method: "DELETE" }, true),
  setInList: (listId: number, albumId: string, on: boolean) =>
    request<void>(`/me/lists/${listId}/albums/${encodeURIComponent(albumId)}`, { method: on ? "PUT" : "DELETE" }, true),

  /** Contact page (ADR 0020). */
  sendFeedback: (f: { topic: string; message: string; replyTo: string | null }) => jsonRequest<void>("/feedback", "POST", f),

  chatStatus: () => request<ChatStatus>("/chat/status"),
  conversations: () => request<ConversationSummary[]>("/chat/conversations", {}, true),
  conversation: (id: string) => request<Conversation>(`/chat/conversations/${encodeURIComponent(id)}`, {}, true),
  deleteConversation: (id: string) => request<void>(`/chat/conversations/${encodeURIComponent(id)}`, { method: "DELETE" }, true),
  ask: (conversationId: string | null, message: string) => jsonRequest<ChatAnswer>("/chat", "POST", { conversationId, message }),
};
