// H3 Studio for agents: ZenKit capabilities (ZenAgent sees them as tools) to list a studio's scenes
// and see what one rendered — its clip as a contact sheet (lib/h3contact.ts), frames evenly through
// it marked with time and shot — or the whole film's.
import { app } from "@comfy/app";
import { registerZenCapability } from "@/framework";
import { contactSheet, sceneTitle, shotStarts } from "./h3contact";
import { toProject, type Project } from "./h3studio";

const STUDIO = "nynxz.H3.Studio";

interface GraphNode {
  id: number | string;
  type?: string;
  title?: string;
  widgets?: { name: string; value: unknown }[];
}

/** Every H3 Studio on the open workflow, with its project as saved on the node. */
function studios(): { id: string; title: string; project: Project }[] {
  const nodes = ((app.graph as unknown as { nodes?: GraphNode[] })?.nodes ?? []).filter(
    (n) => n.type === STUDIO,
  );
  return nodes.map((n) => ({
    id: String(n.id),
    title: n.title ?? "H3 Studio",
    project: toProject(n.widgets?.find((w) => w.name === "project")?.value),
  }));
}

function studio(args: Record<string, unknown>) {
  const all = studios();
  if (!all.length) throw new Error("There's no H3 Studio node on the open workflow.");
  const want = args.studio === undefined ? "" : String(args.studio);
  const hit = want ? all.find((s) => s.id === want) : all[0];
  if (!hit)
    throw new Error(
      `No H3 Studio with node id ${want}. Studios: ${all.map((s) => s.id).join(", ")}.`,
    );
  return hit;
}

/** The scene meant: by number (1-based) or by title. */
function sceneOf(project: Project, which: unknown): number {
  const n = Number(which);
  if (Number.isInteger(n) && n >= 1 && n <= project.scenes.length) return n - 1;
  const text = typeof which === "string" ? which.trim().toLowerCase() : "";
  const i = text ? project.scenes.findIndex((s) => s.title.toLowerCase() === text) : -1;
  if (i < 0)
    throw new Error(
      `Which scene? Give its number (1–${project.scenes.length}) or title (h3studio_scenes lists them).`,
    );
  return i;
}

const STUDIO_PARAM = {
  studio: {
    type: "string",
    description: "The H3 Studio's node id. Leave out for the first one on the workflow.",
  },
};

export function registerH3StudioCapabilities() {
  void registerZenCapability({
    id: "h3studio.scenes",
    effect: "read",
    description:
      "List the scenes of the H3 Studio on the open workflow: number, title, length, shots and whether " +
      "it has a rendered clip (its media ref).",
    params: { type: "object", properties: STUDIO_PARAM },
    run: async (args) => {
      const s = studio(args);
      return {
        studio: s.id,
        scenes: s.project.scenes.map((scene, i) => ({
          scene: i + 1,
          title: scene.title || undefined,
          seconds: scene.seconds,
          shots: scene.shots.length,
          clip: scene.render ?? null,
        })),
      };
    },
  });

  void registerZenCapability({
    id: "h3studio.look",
    effect: "read",
    description:
      "See what an H3 Studio scene rendered: its clip as a contact sheet — `count` frames evenly through " +
      "it in a grid, each marked with its time and shot. film: true sheets the latest saved film " +
      "instead. Returns the sheet's media ref (use look_at on it), its file path, and each frame's time.",
    params: {
      type: "object",
      properties: {
        ...STUDIO_PARAM,
        scene: { type: "string", description: "The scene's number (1-based) or title." },
        film: { type: "boolean" },
        count: { type: "number", description: "Frames on the sheet, 4 to 48. Default 12." },
      },
    },
    run: async (args) => {
      const { project } = studio(args);
      const count = typeof args.count === "number" ? args.count : 12;
      if (args.film) {
        const res = await fetch("/nynxz/h3studio/films", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ scenes: project.scenes.map((s) => s.id) }),
        });
        const film = ((await res.json()) as { films?: { ref: string }[] }).films?.[0];
        if (!film) throw new Error("This studio has no saved film yet.");
        const sheet = await contactSheet({ ref: film.ref, count, title: "Film" });
        return { image: sheet.ref, path: sheet.path, frames: sheet.frames, seconds: sheet.seconds };
      }
      const i = sceneOf(project, args.scene ?? 1);
      const scene = project.scenes[i]!;
      if (!scene.render) throw new Error(`Scene ${i + 1} hasn't rendered yet.`);
      const sheet = await contactSheet({
        ref: scene.render,
        count,
        shots: shotStarts(scene),
        title: sceneTitle(scene, i),
      });
      return {
        image: sheet.ref,
        path: sheet.path,
        clip: scene.render,
        frames: sheet.frames,
        seconds: sheet.seconds,
      };
    },
  });
}
