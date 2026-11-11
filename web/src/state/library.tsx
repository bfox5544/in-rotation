import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError, OFFLINE_MESSAGE, type AlbumList, type MyProfile, type RatedAlbum } from "../api";
import type { Album } from "../types";

interface Library {
  later: Album[];
  /** Album id -> ISO time it was saved to Listen Later. */
  laterAdded: Record<string, string>;
  lists: AlbumList[];
  /** Rated albums, newest first. */
  rated: RatedAlbum[];
  /** Signed-in email, or null for an anonymous library. */
  email: string | null;
  /** Your profile (ADR 0018), or null. */
  profile: MyProfile | null;
  /** After the profile is saved on the server. */
  setProfile: (profile: MyProfile | null) => void;
  error: string | null;
  /** True once the library has loaded from the server. */
  loaded: boolean;
  isLater: (id: string) => boolean;
  toggleLater: (album: Album) => void;
  ratingOf: (id: string) => number | null;
  /** 0.5-5 in half stars, or null to clear. */
  rate: (album: Album, stars: number | null) => void;
  /** Keep an album off For you (or undo that); resolves once the server has it. */
  setDismissed: (album: Album, on: boolean) => Promise<void>;
  /** Albums that shape recommendations: those rated 3 stars or more. */
  queryCount: number;
  inList: (listId: number, albumId: string) => boolean;
  toggleInList: (listId: number, album: Album) => void;
  /** Creates a list (optionally starting with one album); resolves once the server has it. */
  createList: (name: string, first?: Album) => Promise<void>;
  renameList: (listId: number, name: string) => void;
  deleteList: (listId: number) => void;
  /** Recreates a deleted list with its albums, newest first as before (Undo). */
  restoreList: (name: string, albums: Album[]) => Promise<void>;
  /** Reloads everything from the server, after pending saves (used when signing in or out). */
  reload: () => Promise<void>;
  /** Resolves once every pending save has reached the server. */
  whenSynced: () => Promise<void>;
}

const Ctx = createContext<Library | null>(null);
const SAVE_FAILED = "Your last change couldn't be saved. The list has been reset to what is stored.";

const flip = (list: Album[], album: Album) =>
  list.some((a) => a.id === album.id) ? list.filter((a) => a.id !== album.id) : [album, ...list];

export function LibraryProvider({ children }: { children: ReactNode }) {
  const [later, setLater] = useState<Album[]>([]);
  const [laterAdded, setLaterAdded] = useState<Record<string, string>>({});
  const [lists, setLists] = useState<AlbumList[]>([]);
  const [rated, setRated] = useState<RatedAlbum[]>([]);
  const [email, setEmail] = useState<string | null>(null);
  const [profile, setProfile] = useState<MyProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const chain = useRef<Promise<void>>(Promise.resolve());

  const refresh = useCallback(async () => {
    try {
      const [lib, me] = await Promise.all([api.library(), api.me()]);
      setLater(lib.later);
      setLaterAdded(lib.laterAdded ?? {});
      setLists(lib.lists);
      setRated(lib.rated);
      setEmail(me.email);
      setProfile(me.profile);
      setLoaded(true);
      setError(null);
    } catch (e) {
      // A refusal from the server (too many new visits from one network) says why. Anything else is a connection problem.
      setError(e instanceof ApiError && e.status === 429 ? e.message : OFFLINE_MESSAGE);
    }
  }, []);

  useEffect(() => {
    chain.current = chain.current.then(refresh);
  }, [refresh]);

  // Saves run one at a time so a quick add-then-remove can't arrive out of order.
  const save = useCallback(
    (call: () => Promise<void>) => {
      const next = chain.current.then(async () => {
        await call();
        setError(null);
      });
      chain.current = next.catch(async () => {
        await refresh();
        setError(SAVE_FAILED);
      });
      return next;
    },
    [refresh],
  );

  const value = useMemo<Library>(() => {
    const editList = (listId: number, edit: (l: AlbumList) => AlbumList) =>
      setLists((ls) => ls.map((l) => (l.id === listId ? edit(l) : l)));
    const inList = (listId: number, albumId: string) =>
      lists.some((l) => l.id === listId && l.albums.some((a) => a.id === albumId));
    const ratingOf = (id: string) => rated.find((r) => r.album.id === id)?.rating ?? null;
    const stamp = (added: Record<string, string> | undefined, id: string, on: boolean) => {
      const next = { ...added };
      if (on) next[id] = new Date().toISOString(); else delete next[id];
      return next;
    };
    return {
      later,
      laterAdded,
      lists,
      rated,
      email,
      profile,
      setProfile,
      error,
      loaded,
      isLater: (id) => later.some((a) => a.id === id),
      toggleLater: (album) => {
        const on = !later.some((a) => a.id === album.id);
        setLater((l) => flip(l, album));
        setLaterAdded((d) => stamp(d, album.id, on));
        save(() => api.setLater(album.id, on));
      },
      ratingOf,
      rate: (album, stars) => {
        setRated((rs) => [...(stars ? [{ album, rating: stars }] : []), ...rs.filter((r) => r.album.id !== album.id)]);
        save(() => api.setRating(album.id, stars));
      },
      setDismissed: (album, on) => save(() => api.setDismissed(album.id, on)),
      queryCount: rated.filter((r) => r.rating >= 3).length,
      inList,
      toggleInList: (listId, album) => {
        const on = !inList(listId, album.id);
        editList(listId, (l) => ({ ...l, albums: flip(l.albums, album), added: stamp(l.added, album.id, on) }));
        save(() => api.setInList(listId, album.id, on));
      },
      createList: (name, first) =>
        save(async () => {
          const created = await api.createList(name);
          if (first) await api.setInList(created.id, first.id, true);
          setLists((ls) => [...ls, { ...created, albums: first ? [first] : [], added: first ? stamp({}, first.id, true) : {} }]);
        }),
      restoreList: (name, albums) =>
        save(async () => {
          const created = await api.createList(name);
          // Oldest first, so the newest album is added last and stays first.
          for (const a of [...albums].reverse()) await api.setInList(created.id, a.id, true);
          setLists((ls) => [...ls, { ...created, albums, added: Object.fromEntries(albums.map((a) => [a.id, new Date().toISOString()])) }]);
        }),
      renameList: (listId, name) => {
        editList(listId, (l) => ({ ...l, name }));
        save(async () => void (await api.renameList(listId, name)));
      },
      deleteList: (listId) => {
        setLists((ls) => ls.filter((l) => l.id !== listId));
        save(() => api.deleteList(listId));
      },
      reload: () => (chain.current = chain.current.then(refresh)),
      whenSynced: () => chain.current,
    };
  }, [later, laterAdded, lists, rated, email, profile, error, loaded, save, refresh]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLibrary(): Library {
  const v = useContext(Ctx);
  if (!v) throw new Error("useLibrary must be used inside LibraryProvider");
  return v;
}
