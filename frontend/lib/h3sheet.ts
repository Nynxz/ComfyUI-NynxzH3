// A reference sheet: the project's references packed onto one board, each with its @name and what
// it is — to look the cast over, share, or hand an LLM. Rows are justified (every row scaled to
// fill the width), so pictures keep their own shape and nothing is cropped: tall characters and wide
// places sit side by side. Placeholders and audio, having nothing to see, are small cards of their
// descriptions in a strip at the end.

import { mediaKind } from "@/framework";
import { stableUrl, thumbUrl, type Project, type Ref } from "./h3studio";

export interface SheetOptions {
  width: number;
  /** References to show, in order. */
  refs: Ref[];
  labels: boolean;
  notes: boolean;
  gutter: "light" | "dark";
  /** Names and descriptions at this multiple of their usual size. */
  text: number;
}

interface Cell {
  ref: Ref;
  image: HTMLImageElement | null;
  aspect: number;
}

const CARD_ASPECT = 1.4;
const FONT = 'ui-monospace, "SF Mono", Menlo, Consolas, monospace';

/** The references worth a sheet: those with a picture or video first, as H3 numbers them, then
 *  audio and placeholders. */
export function sheetRefs(project: Project, sceneId?: string, inScene?: (r: Ref) => boolean): Ref[] {
  const refs = sceneId && inScene ? project.refs.filter(inScene) : project.refs;
  const rank = (r: Ref) => (!r.media ? 3 : r.kind === "image" ? 0 : r.kind === "video" ? 1 : 2);
  return [...refs].sort((a, b) => rank(a) - rank(b));
}

function load(url: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const img = new Image();
    img.decoding = "async";
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

async function cells(refs: Ref[]): Promise<Cell[]> {
  return Promise.all(
    refs.map(async (ref) => {
      const visual = ref.media && mediaKind(ref.media) !== "audio";
      const url = !visual ? "" : ref.kind === "video" ? thumbUrl(ref.media, 768) : stableUrl(ref.media);
      const image = url ? await load(url) : null;
      const aspect = image && image.naturalHeight ? image.naturalWidth / image.naturalHeight : CARD_ASPECT;
      return { ref, image, aspect };
    }),
  );
}

/** Justified rows, balanced: the references are split into runs (keeping their order) so every
 *  row's height comes out as close to `target` as it can — trying a row count either side of what
 *  the total width suggests — so no row is left with one straggler. Each row is then scaled to
 *  fill the width, unless that would make it much taller than `target` (too few to fill it): then it
 *  keeps a capped height, centred. */
export function pack(aspects: number[], width: number, gap: number, target: number) {
  const n = aspects.length;
  if (!n) return [];
  const ideal = width / target;
  const prefix = [0];
  for (const a of aspects) prefix.push(prefix[prefix.length - 1]! + a);
  // How far a row's height is from the target, as a ratio either way: a row twice too tall is as
  // bad as one half too short.
  // Plus how much narrower than a fifth of the sheet any picture in it comes out: a portrait
  // squeezed into a short row of wide places is hard to see, so it earns its row more height.
  const narrowest = width / 5;
  const cost = (i: number, j: number) => {
    const sum = prefix[j]! - prefix[i]!;
    const height = (width - gap * (j - i - 1)) / sum;
    let c = Math.log(sum / ideal) ** 2;
    for (let t = i; t < j; t++) {
      const w = aspects[t]! * Math.min(height, target * 1.4);
      if (w < narrowest) c += Math.log(narrowest / w) ** 2;
    }
    return c;
  };
  /** The best split into `k` rows: its cost, and the rows. */
  function split(k: number): { total: number; runs: number[][] } {
    // best[r][j]: the least cost of putting the first j references into r rows.
    const best = Array.from({ length: k + 1 }, () => new Array<number>(n + 1).fill(Infinity));
    const cut = Array.from({ length: k + 1 }, () => new Array<number>(n + 1).fill(0));
    best[0]![0] = 0;
    for (let r = 1; r <= k; r++)
      for (let j = r; j <= n; j++)
        for (let i = r - 1; i < j; i++) {
          const c = best[r - 1]![i]! + cost(i, j);
          if (c < best[r]![j]!) {
            best[r]![j] = c;
            cut[r]![j] = i;
          }
        }
    const runs: number[][] = [];
    for (let r = k, j = n; r > 0; r--) {
      const i = cut[r]![j]!;
      runs.unshift(Array.from({ length: j - i }, (_, t) => i + t));
      j = i;
    }
    return { total: best[k]![n]!, runs };
  }
  // Around as many rows as the total width suggests; whichever split comes out most even.
  const guess = Math.round(prefix[n]! / ideal);
  const tries = [guess - 1, guess, guess + 1].filter((k) => k >= 1 && k <= n);
  const { runs } = tries.map(split).reduce((a, b) => (b.total < a.total ? b : a));
  const cap = target * 1.4;
  return runs.map((items) => {
    const sum = items.reduce((s, i) => s + aspects[i]!, 0);
    const fill = (width - gap * (items.length - 1)) / sum;
    if (fill <= cap) return { items, height: fill, x0: 0 };
    return { items, height: cap, x0: (width - sum * cap - gap * (items.length - 1)) / 2 };
  });
}

function wrap(ctx: CanvasRenderingContext2D, text: string, max: number): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const next = line ? `${line} ${word}` : word;
    if (ctx.measureText(next).width > max && line) {
      lines.push(line);
      line = word;
    } else line = next;
  }
  if (line) lines.push(line);
  return lines;
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
  ctx.fill();
}

/** One cell: the picture (or a card), then the @name chip and the description under it. */
function drawCell(ctx: CanvasRenderingContext2D, cell: Cell, x: number, y: number, w: number, h: number, opts: SheetOptions) {
  // One text size across the sheet (set by its width), smaller only where a cell is too narrow.
  const base = (opts.width / 1536) * opts.text;
  const scale = base * Math.min(1, w / (300 * base));
  ctx.save();
  ctx.beginPath();
  ctx.rect(x, y, w, h);
  ctx.clip();
  if (cell.image) ctx.drawImage(cell.image, x, y, w, h);
  else {
    const g = ctx.createLinearGradient(x, y, x + w, y + h);
    g.addColorStop(0, "#1d2433");
    g.addColorStop(1, "#141821");
    ctx.fillStyle = g;
    ctx.fillRect(x, y, w, h);
    ctx.fillStyle = "rgba(255,255,255,0.08)";
    ctx.font = `${Math.round(Math.min(w, h) * 0.38)}px ${FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const mark = cell.ref.kind === "audio" ? "♪" : cell.ref.name.charAt(0).toUpperCase();
    ctx.fillText(mark, x + w / 2, y + h * 0.58);
    ctx.textAlign = "left";
  }

  const pad = Math.round(10 * scale);
  let cy = y + pad;
  if (opts.labels) {
    const size = Math.round(17 * scale);
    ctx.font = `600 ${size}px ${FONT}`;
    ctx.textBaseline = "middle";
    const label = `@${cell.ref.name}`;
    const lw = ctx.measureText(label).width + size * 0.9;
    const lh = size * 1.6;
    ctx.fillStyle = "rgba(10,12,18,0.82)";
    roundRect(ctx, x + pad, cy, lw, lh, size * 0.3);
    ctx.fillStyle = "#f2f3f7";
    ctx.fillText(label, x + pad + size * 0.45, cy + lh / 2 + 1);
    cy += lh + size * 0.35;
  }
  const note = cell.ref.note.trim() || (!cell.ref.media ? "(a placeholder, no picture yet)" : "");
  if (opts.notes && note) {
    const size = Math.round(12.5 * scale);
    ctx.font = `${size}px ${FONT}`;
    ctx.textBaseline = "top";
    const maxW = Math.min(w - pad * 2, cell.image ? Math.max(0.62 * w, 220 * scale) : w, 380 * scale);
    const line = size * 1.32;
    const lines = wrap(ctx, note, maxW - size).slice(0, Math.max(1, Math.floor((h - (cy - y) - pad) / line) - 1));
    const bw = Math.max(...lines.map((l) => ctx.measureText(l).width)) + size;
    ctx.fillStyle = "rgba(10,12,18,0.62)";
    roundRect(ctx, x + pad, cy, bw, lines.length * line + size * 0.7, size * 0.3);
    ctx.fillStyle = "#e3e5ec";
    lines.forEach((l, i) => ctx.fillText(l, x + pad + size / 2, cy + size * 0.35 + i * line));
  }
  ctx.restore();
}

/** The sheet, drawn. */
export async function drawSheet(opts: SheetOptions): Promise<HTMLCanvasElement> {
  const all = await cells(opts.refs);
  // Like shapes together: portraits share rows with portraits, so a row of characters stands tall
  // instead of squeezing between wide places.
  const shape = (c: Cell) => (c.aspect < 0.85 ? 0 : c.aspect <= 1.25 ? 1 : 2);
  const pictures = all.filter((c) => c.image).sort((x, y) => shape(x) - shape(y));
  const cards = all.filter((c) => !c.image);
  const list = [...pictures, ...cards];
  const gap = Math.round(opts.width / 160);
  const inner = opts.width - gap * 2;
  const offset = (rows: ReturnType<typeof pack>, by: number) =>
    rows.map((r) => ({ ...r, items: r.items.map((i) => i + by) }));
  const rows = [
    ...pack(pictures.map((c) => c.aspect), inner, gap, opts.width / 3.1),
    ...offset(pack(cards.map((c) => c.aspect), inner, gap, opts.width / 7.5), pictures.length),
  ];
  const height = Math.round(rows.reduce((s, r) => s + r.height, 0) + gap * (rows.length + 1));
  const canvas = document.createElement("canvas");
  canvas.width = opts.width;
  canvas.height = Math.max(height, gap * 2 + 1);
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = opts.gutter === "light" ? "#f4f4f6" : "#0d0f14";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  let y = gap;
  for (const row of rows) {
    let x = gap + row.x0;
    for (const i of row.items) {
      const w = list[i]!.aspect * row.height;
      drawCell(ctx, list[i]!, Math.round(x), Math.round(y), Math.round(w), Math.round(row.height), opts);
      x += w + gap;
    }
    y += row.height + gap;
  }
  return canvas;
}

export const sheetBlob = (canvas: HTMLCanvasElement) =>
  new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
