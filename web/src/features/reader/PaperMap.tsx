import { useLayoutEffect, useRef, useState } from "react";

import { ApiError } from "../../api/client";
import { useBuildMap, usePaperMap } from "../../api/hooks";
import type { PaperMapOut } from "../../api/types";
import { Skeleton } from "../../components/ui/Skeleton";
import { branchesOf, curve, layout, type MapItem, toMarkdown } from "./mapLayout";

const errorText = (error: unknown) => (error instanceof ApiError ? error.message : "Could not reach the server.");
type Active = { item: MapItem; branch: string; anchor: Element };

function MapPop({ active }: { active: Active | null }) {
  const pop = useRef<HTMLDivElement>(null);
  // Beside the node (below it, or above when there is no room), positioned through the CSSOM (the CSP allows it)
  useLayoutEffect(() => {
    const node = pop.current;
    const rect = active?.anchor.getBoundingClientRect();
    if (!node || !rect) return;
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - node.offsetWidth - 8));
    const below = rect.bottom + 8;
    const top = below + node.offsetHeight > window.innerHeight - 8 ? Math.max(8, rect.top - node.offsetHeight - 8) : below;
    node.style.left = `${left}px`;
    node.style.top = `${top}px`;
  }, [active]);
  if (!active) return null;
  return (
    <div ref={pop} className="reader-pop map-pop" aria-hidden="true">
      <p className={active.branch === "red_flags" ? "reader-pop__flag" : "reader-pop__claim"}>
        <strong>{active.item.label}</strong>
        <q className="map-pop__quote">{active.item.quote}</q>
        {active.item.by && <span className="map-pop__by">{active.item.by}</span>}
        <span className="map-pop__hint">Click to read it in the text</span>
      </p>
    </div>
  );
}

/** The drawn map (SVG, role="img"). Mouse users hover and click its nodes; the outline below is the
 * accessible equivalent with the same nodes as buttons. */
function MapDrawing({ map, title, onActive, onJump }: { map: PaperMapOut; title: string; onActive: (a: Active | null) => void; onJump: (quote: string) => void }) {
  const drawn = layout(map, title);
  const { root } = drawn;
  const summary = `Paper map of “${title}”: ${branchesOf(map).map((b) => `${b.title}, ${b.items.length ? `${b.items.length} node${b.items.length === 1 ? "" : "s"}` : "not reported"}`).join("; ")}. The same content is in the outline below.`;
  return (
    <svg className="map-svg" viewBox={`0 0 ${drawn.width} ${drawn.height}`} role="img" aria-label={summary} preserveAspectRatio="xMidYMin meet">
      <g className="map-links" aria-hidden="true">
        {drawn.branches.map((b) => {
          const rootX = b.side === "left" ? root.x : root.x + root.w;
          const headIn = b.side === "left" ? b.header.x + b.header.w : b.header.x;
          const headOut = b.side === "left" ? b.header.x : b.header.x + b.header.w;
          return (
            <g key={b.key} className={`map-b map-b--${b.key}`}>
              <path className="map-link map-link--trunk" d={curve(rootX, root.y + root.h / 2, headIn, b.header.y + b.header.h / 2)} />
              {b.nodes.map((n, i) => (
                <path key={i} className={`map-link ${n.item ? "" : "map-link--dashed"}`} d={curve(headOut, b.header.y + b.header.h / 2, b.side === "left" ? n.x + n.w : n.x, n.y + n.h / 2)} />
              ))}
            </g>
          );
        })}
      </g>
      <g className="map-root">
        <rect x={root.x} y={root.y} width={root.w} height={root.h} rx={14} />
        <text x={root.x + root.w / 2} y={root.y + 30} textAnchor="middle">
          {root.lines.map((l, i) => <tspan key={i} x={root.x + root.w / 2} dy={i === 0 ? 0 : 23}>{l}</tspan>)}
        </text>
      </g>
      {drawn.branches.map((b) => (
        <g key={b.key} className={`map-b map-b--${b.key}`}>
          <g className="map-head">
            <rect x={b.header.x} y={b.header.y} width={b.header.w} height={b.header.h} rx={17} />
            <text x={b.header.x + b.header.w / 2} y={b.header.y + 22} textAnchor="middle">{b.key === "red_flags" ? "⚑ " : ""}{b.title}</text>
          </g>
          {b.nodes.map((n, i) => n.item ? (
            <g
              key={i}
              className="map-node"
              onMouseEnter={(e) => onActive({ item: n.item!, branch: b.key, anchor: e.currentTarget })}
              onMouseLeave={() => onActive(null)}
              onClick={() => { onActive(null); onJump(n.item!.quote); }}
            >
              <rect x={n.x} y={n.y} width={n.w} height={n.h} rx={8} />
              <rect className="map-node__rule" x={b.side === "left" ? n.x + n.w - 4 : n.x} y={n.y} width={4} height={n.h} rx={2} />
              <text x={n.x + 14} y={n.y + 24}>
                {n.lines.map((l, j) => <tspan key={j} x={n.x + 14} dy={j === 0 ? 0 : 20}>{l}</tspan>)}
              </text>
            </g>
          ) : (
            <g key={i} className="map-node map-node--empty">
              <rect x={n.x} y={n.y} width={n.w} height={n.h} rx={8} />
              <text x={n.x + 14} y={n.y + 23}>Not reported</text>
            </g>
          ))}
        </g>
      ))}
    </svg>
  );
}

/** The outline: the map as an ordered list of branches and nodes, for keyboard and screen readers (and the
 * only view on a narrow screen). Each node is a button: focus shows its quote, Enter jumps to it in the text. */
function MapOutline({ map, onActive, onJump }: { map: PaperMapOut; onActive: (a: Active | null) => void; onJump: (quote: string) => void }) {
  return (
    <ol className="map-outline" aria-label="Paper map outline">
      {branchesOf(map).map((b) => (
        <li key={b.key} className={`map-outline__branch map-b map-b--${b.key}`}>
          <h3><span className="map-swatch" aria-hidden="true" />{b.title}</h3>
          {b.items.length === 0 ? <p className="map-outline__none">Not reported</p> : (
            <ol>
              {b.items.map((item, i) => (
                <li key={i}>
                  <button
                    type="button"
                    className="map-outline__node"
                    aria-describedby={`map-q-${b.key}-${i}`}
                    onFocus={(e) => onActive({ item, branch: b.key, anchor: e.currentTarget })}
                    onBlur={() => onActive(null)}
                    onMouseEnter={(e) => onActive({ item, branch: b.key, anchor: e.currentTarget })}
                    onMouseLeave={() => onActive(null)}
                    onClick={() => { onActive(null); onJump(item.quote); }}
                  >
                    {item.label}
                  </button>
                  <span id={`map-q-${b.key}-${i}`} className="sr-only">Quote: {item.quote}{item.by ? ` (${item.by})` : ""}. Activate to read it in the text.</span>
                </li>
              ))}
            </ol>
          )}
        </li>
      ))}
    </ol>
  );
}

/** The Reader's Map tab: build / rebuild (members), the stored map (everyone), the outline and the Markdown copy. */
export function PaperMapView({ runId, paperId, title, member, onJump }: { runId: string; paperId: string; title: string; member: boolean; onJump: (quote: string) => void }) {
  const state = usePaperMap(runId, paperId);
  const build = useBuildMap(runId, paperId);
  const [problem, setProblem] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [active, setActive] = useState<Active | null>(null);

  if (state.isLoading) return <Skeleton label="the paper map" rows={6} />;
  if (state.isError || !state.data) return <p role="alert" className="form-error">{errorText(state.error)}</p>;
  const { map, job, stale, stale_reason } = state.data;
  const working = build.isPending || ["queued", "running"].includes(job?.status ?? "");
  const failed = !working && job?.status === "failed" ? job.error ?? "the call failed" : null;
  const start = async () => {
    setProblem(null);
    try {
      await build.mutateAsync();
    } catch (error) {
      setProblem(errorText(error));
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(toMarkdown(map!, title));
      setCopied("Outline copied as Markdown.");
    } catch {
      setCopied("Could not copy: the browser refused access to the clipboard.");
    }
  };

  return (
    <section className="paper-map" aria-labelledby="map-heading">
      <header className="map-head-row">
        <div>
          <h2 id="map-heading">Paper map</h2>
          <p className="sub">Six fixed branches, the same for every paper. Each node is an exact quote from the paper, checked by code; the red flags come from this run's reviewers.</p>
        </div>
        {map && <button type="button" onClick={() => void copy()}>Copy as outline (Markdown)</button>}
      </header>
      <div aria-live="polite">
        {copied && <p role="status" className="sub">{copied}</p>}
        {problem && <p role="alert" className="form-error">{problem}</p>}
        {working && (
          <div role="status" className="map-building">
            <span className="map-building__bar" aria-hidden="true" />
            {map ? "Rebuilding the map…" : "Building the map…"} One AI call; every quote is then checked against the text.
          </div>
        )}
        {failed && (
          <div role="alert" className="banner banner--warn map-failed">
            <p>The map could not be built: {failed}</p>
            {member && <button type="button" onClick={() => void start()}>Retry</button>}
          </div>
        )}
      </div>
      {!map && !working && !failed && (
        member ? (
          <div className="map-empty">
            <button type="button" className="primary" onClick={() => void start()}>Build the paper map</button>
            <p className="sub">Costs one AI call with the Reader's model. Nothing is kept unless every quote matches the paper's text.</p>
          </div>
        ) : <p className="map-empty sub">No map of this paper yet. A member can build one.</p>
      )}
      {map && (
        <>
          {stale && (
            <div className="banner banner--warn map-stale" role="note">
              <p>Out of date: {stale_reason === "model" ? "the Reader's model changed" : "the map's instructions changed"} since it was built.</p>
              {member ? <button type="button" disabled={working} onClick={() => void start()}>Rebuild</button> : <p className="sub">A member can rebuild it.</p>}
            </div>
          )}
          <p className="map-meta sub">
            {map.text_kind === "abstract" && <span className="chip chip--warn">From the abstract only</span>}{" "}
            Built {new Date(map.built_at).toLocaleDateString()}{map.created_by_name ? ` by ${map.created_by_name}` : ""} with {map.model}{map.mode === "demo" ? " (demo map, test data)" : ""}.
          </p>
          <div className="map-canvas"><MapDrawing map={map} title={title} onActive={setActive} onJump={onJump} /></div>
          <MapOutline map={map} onActive={setActive} onJump={onJump} />
          <MapPop active={active} />
        </>
      )}
    </section>
  );
}
