/** A profile picture (ADR 0018), or the name's first letter on a plain tile when there is none. */
export function Avatar({ url, name, size = 40 }: { url: string | null; name: string; size?: number }) {
  const style = { width: size, height: size, fontSize: Math.round(size * 0.42) };
  if (url) return <img className="avatar" src={url} alt="" width={size} height={size} style={style} />;
  return <span className="avatar avatar-initial" aria-hidden="true" style={style}>{[...name.trim()][0]?.toUpperCase() ?? "?"}</span>;
}
