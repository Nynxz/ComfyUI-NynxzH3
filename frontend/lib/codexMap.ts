// The Codex map's layout: a small force simulation — everything pushes apart, links pull together,
// a weak pull keeps it all near the middle. Nodes already placed (dragged, or laid out before) stay
// put; only new ones move, so the map doesn't reshuffle every time something is added.

export interface MapNode {
  id: string;
  /** Where nodes of the same group start out near each other. */
  group: number;
}
export interface MapEdge {
  from: string;
  to: string;
}
export type Point = { x: number; y: number };

const REPEL = 26000;
const SPRING = 0.02;
const LENGTH = 170;
const GRAVITY = 0.004;

export function layout(
  nodes: MapNode[],
  edges: MapEdge[],
  placed: Record<string, Point>,
  iterations = 260,
): Record<string, Point> {
  const groups = Math.max(1, ...nodes.map((n) => n.group + 1));
  const pos = new Map<string, Point>();
  const free = new Set<string>();
  nodes.forEach((n, i) => {
    const at = placed[n.id];
    if (at) pos.set(n.id, { ...at });
    else {
      // Start each group in its own direction from the middle, spread a little.
      const angle = (n.group / groups) * Math.PI * 2 + (i % 7) * 0.15;
      const r = 220 + (i % 5) * 30;
      pos.set(n.id, { x: Math.cos(angle) * r, y: Math.sin(angle) * r });
      free.add(n.id);
    }
  });
  if (!free.size) return Object.fromEntries(pos);
  const ids = nodes.map((n) => n.id);
  for (let step = 0; step < iterations; step++) {
    const cool = 1 - step / iterations;
    const force = new Map<string, Point>(ids.map((id) => [id, { x: 0, y: 0 }]));
    for (let i = 0; i < ids.length; i++)
      for (let j = i + 1; j < ids.length; j++) {
        const a = pos.get(ids[i]!)!;
        const b = pos.get(ids[j]!)!;
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) {
          dx = Math.random() - 0.5;
          dy = Math.random() - 0.5;
          d2 = 1;
        }
        const f = REPEL / d2;
        const d = Math.sqrt(d2);
        const fa = force.get(ids[i]!)!;
        const fb = force.get(ids[j]!)!;
        fa.x += (dx / d) * f;
        fa.y += (dy / d) * f;
        fb.x -= (dx / d) * f;
        fb.y -= (dy / d) * f;
      }
    for (const e of edges) {
      const a = pos.get(e.from);
      const b = pos.get(e.to);
      if (!a || !b) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const d = Math.max(1, Math.hypot(dx, dy));
      const f = (d - LENGTH) * SPRING;
      force.get(e.from)!.x += (dx / d) * f * d * 0.05;
      force.get(e.from)!.y += (dy / d) * f * d * 0.05;
      force.get(e.to)!.x -= (dx / d) * f * d * 0.05;
      force.get(e.to)!.y -= (dy / d) * f * d * 0.05;
    }
    for (const id of free) {
      const p = pos.get(id)!;
      const f = force.get(id)!;
      f.x -= p.x * GRAVITY * 10;
      f.y -= p.y * GRAVITY * 10;
      const len = Math.hypot(f.x, f.y);
      const max = 30 * cool + 1;
      const k = len > max ? max / len : 1;
      p.x += f.x * k;
      p.y += f.y * k;
    }
  }
  return Object.fromEntries(
    [...pos].map(([id, p]) => [id, { x: Math.round(p.x), y: Math.round(p.y) }]),
  );
}
