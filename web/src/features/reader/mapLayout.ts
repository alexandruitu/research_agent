import type { MapBranchOut, MapFlagOut, PaperMapOut } from "../../api/types";

/** A node of the drawn map: a branch node, a red flag, or the "Not reported" placeholder. */
export type MapItem = { label: string; quote: string; by?: string };
export type DrawnNode = { item: MapItem | null; x: number; y: number; w: number; h: number; lines: string[] };
export type DrawnBranch = {
  key: string; title: string; side: "left" | "right"; notReported: boolean;
  header: { x: number; y: number; w: number; h: number };
  nodes: DrawnNode[];
};
export type Drawn = { width: number; height: number; root: { x: number; y: number; w: number; h: number; lines: string[] }; branches: DrawnBranch[] };

export const FLAGS_KEY = "red_flags";
export const FLAGS_TITLE = "Reviewer red flags";

/** Greedy word wrap to at most `max` lines of about `chars` characters (the last line ends in … when cut). */
export function wrap(text: string, chars: number, max: number): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    if (line && (line + " " + word).length > chars) {
      lines.push(line);
      line = word;
    } else line = line ? `${line} ${word}` : word;
  }
  if (line) lines.push(line);
  if (lines.length <= max) return lines;
  const kept = lines.slice(0, max);
  kept[max - 1] = `${kept[max - 1]!.replace(/[.,;:]?$/, "")}…`;
  return kept;
}

const W = 1000;
const NODE_W = 214;
const HEAD_W = 136;
const HEAD_H = 34;
const ROOT_W = 190;
const GAP = 10;
const BLOCK_GAP = 28;
const LINE = 20;

type Branchish = { key: string; title: string; items: MapItem[] };

export function branchesOf(map: PaperMapOut): Branchish[] {
  const six = map.branches.map((b: MapBranchOut) => ({ key: b.key, title: b.title, items: b.nodes.map((n) => ({ label: n.label, quote: n.quote })) }));
  const flags = map.red_flags.map((f: MapFlagOut) => ({ label: f.label, quote: f.quote, by: f.by }));
  return flags.length ? [...six, { key: FLAGS_KEY, title: FLAGS_TITLE, items: flags }] : six;
}

/**
 * The map's geometry, by hand (no layout library): the title in the middle, the six branches in two columns
 * (Task, Data, Method on the left; Validation, Results, Limitations on the right) with their nodes on the
 * outside, and the red flags under the shorter column.
 */
export function layout(map: PaperMapOut, title: string): Drawn {
  const all = branchesOf(map);
  const sides: Record<"left" | "right", Branchish[]> = { left: all.slice(0, 3), right: all.slice(3, 6) };
  const blockHeight = (b: Branchish) => {
    const nodes = b.items.length ? b.items.map((i) => wrap(i.label, 25, 3).length * LINE + 18) : [36];
    return Math.max(HEAD_H, nodes.reduce((a, h) => a + h, 0) + GAP * (nodes.length - 1));
  };
  const total = (list: Branchish[]) => list.reduce((a, b) => a + blockHeight(b), 0) + BLOCK_GAP * Math.max(0, list.length - 1);
  const flags = all[6];
  if (flags) (total(sides.left) <= total(sides.right) ? sides.left : sides.right).push(flags);
  const top = 24;
  const branches: DrawnBranch[] = [];
  for (const side of ["left", "right"] as const) {
    let y = top;
    for (const b of sides[side]) {
      const h = blockHeight(b);
      const headX = side === "left" ? W / 2 - ROOT_W / 2 - 24 - HEAD_W : W / 2 + ROOT_W / 2 + 24;
      const nodeX = side === "left" ? 12 : W - 12 - NODE_W;
      const items: (MapItem | null)[] = b.items.length ? b.items : [null];
      let ny = y + (h - (items.reduce((a, i) => a + (i ? wrap(i.label, 25, 3).length * LINE + 18 : 36), 0) + GAP * (items.length - 1))) / 2;
      const nodes = items.map((item) => {
        const lines = item ? wrap(item.label, 25, 3) : ["Not reported"];
        const nh = item ? lines.length * LINE + 18 : 36;
        const node = { item, x: nodeX, y: ny, w: NODE_W, h: nh, lines };
        ny += nh + GAP;
        return node;
      });
      branches.push({ key: b.key, title: b.title, side, notReported: b.items.length === 0, header: { x: headX, y: y + h / 2 - HEAD_H / 2, w: HEAD_W, h: HEAD_H }, nodes });
      y += h + BLOCK_GAP;
    }
  }
  const height = Math.max(total(sides.left), total(sides.right)) + top * 2;
  const lines = wrap(title, 17, 6);
  const rh = lines.length * 23 + 36;
  return { width: W, height: Math.max(height, rh + top * 2), root: { x: W / 2 - ROOT_W / 2, y: Math.max(height, rh + top * 2) / 2 - rh / 2, w: ROOT_W, h: rh, lines }, branches };
}

/** A smooth horizontal connector from (x1, y1) to (x2, y2). */
export function curve(x1: number, y1: number, x2: number, y2: number): string {
  const mid = (x1 + x2) / 2;
  return `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`;
}

/** "Copy as outline (Markdown)": the same content as the outline, every node with its quote. */
export function toMarkdown(map: PaperMapOut, title: string): string {
  const out = [`# ${title}`, ""];
  if (map.text_kind === "abstract") out.push("_From the abstract only._", "");
  for (const b of branchesOf(map)) {
    out.push(`## ${b.title}`);
    if (!b.items.length) out.push("- Not reported");
    for (const i of b.items) out.push(`- ${i.label}${i.by ? ` (${i.by})` : ""}\n  > ${i.quote.replace(/\s+/g, " ")}`);
    out.push("");
  }
  out.push(`_Paper map ${map.prompt_version}, ${map.model}. Every quote checked against the paper's text by code._`);
  return out.join("\n");
}
