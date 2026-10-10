// Contact sheets of renders (nodes/h3studio/sheet.py): frames evenly through a clip in one picture,
// marked with their time and shot — to look a scene over, or hand it to a chat or an agent.
import { FPS, type Scene } from "./h3studio";

export interface ContactSheet {
  ref: string;
  /** The PNG on the server's disk, for agents that read files. */
  path: string;
  /** Each frame's time in the clip, in seconds. */
  frames: number[];
  seconds: number;
}

export interface ContactRequest {
  ref: string;
  count?: number;
  columns?: number;
  /** Each shot's first frame, to mark the shot every frame is from. */
  shots?: number[];
  title?: string;
}

export async function contactSheet(req: ContactRequest): Promise<ContactSheet> {
  const res = await fetch("/nynxz/h3studio/sheet", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  const data = (await res.json().catch(() => ({}))) as ContactSheet & { error?: string };
  if (!res.ok) throw new Error(data.error ?? "Couldn't make the contact sheet.");
  return data;
}

/** Each of a scene's shots' first frame in its clip. */
export const shotStarts = (scene: Scene): number[] =>
  scene.shots.map((s) => Math.round(s.at * FPS));

/** What a scene's clip is called on its sheet. */
export const sceneTitle = (scene: Scene, index: number) =>
  `Scene ${index + 1}${scene.title ? ` — ${scene.title}` : ""}`;
