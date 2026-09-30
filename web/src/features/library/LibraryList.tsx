import type { LibraryItemOut } from "../../api/types";
import { StatusMark } from "../../components/ui/StatusMark";

type Props = { items: LibraryItemOut[]; openId: string | null; cursorId: string | null; onOpen: (id: string) => void };

/** The list side of the library: one card per paper; j/k move the cursor, Enter or o opens. */
export function LibraryList({ items, openId, cursorId, onOpen }: Props) {
  return (
    <ul className="library-list" aria-label="Saved papers">
      {items.map((item) => (
        <li key={item.id} className={`${openId === item.id ? "is-open" : ""} ${cursorId === item.id ? "is-cursor" : ""}`}>
          <button type="button" className="library-card" data-item={item.id} aria-current={openId === item.id ? "true" : undefined} onClick={() => onOpen(item.id)}>
            <span className="card-top">
              <StatusMark status={item.status} />
              {item.score != null && <span className="score tnum">score {Math.round(item.score)}</span>}
              {item.red_flag_count ? <span className="flag-word"><span aria-hidden="true">⚑</span> {item.red_flag_count} red flag{item.red_flag_count === 1 ? "" : "s"}</span> : null}
            </span>
            <span className="card-title">{item.paper.title}</span>
            <span className="card-meta">
              {[item.paper.year, item.field?.name, item.added_by_name && `saved by ${item.added_by_name}`].filter(Boolean).join(" · ")}
            </span>
            {(item.collections.length > 0 || item.tags.length > 0 || item.note) && (
              <span className="card-tags">
                {item.collections.map((c) => <span key={c.id} className="coll-chip">{c.name}</span>)}
                {item.tags.map((t) => <span key={t} className="tag-chip">#{t}</span>)}
                {item.note && <span className="note-mark"><span aria-hidden="true">✎</span> note</span>}
              </span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}
