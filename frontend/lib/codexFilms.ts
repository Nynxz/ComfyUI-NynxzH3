// H3 Studio ⇄ Codex: a studio's project saved into a show as a film (filed under an episode), and
// opened back into a studio later — to carry on, or to render. A studio remembers which film it
// holds (`project.codex`), so it can save over it and say when it has changed since.
import { episodeName, uid, type Film, type Show } from "./codex";
import { listShows, liveShows, loadShow, withShow } from "./codexStore";
import { toProject, type Project } from "./h3studio";

export interface FilmLink {
  show: string;
  film: string;
  /** "Pilot · Cold open", as the studio shows it. */
  label: string;
  /** The project's fingerprint when it was last saved or opened. */
  saved: string;
}
type Linked = Project & { codex?: FilmLink };

/** The project as a film stores it: without the link, or what's only on screen. */
function filmProject(project: Project): Record<string, unknown> {
  const copy = JSON.parse(JSON.stringify(project)) as Record<string, unknown>;
  delete copy.codex;
  delete copy.renderOnly;
  delete copy.active;
  return copy;
}

/** A short fingerprint of what a film would store. */
export function fingerprint(project: Project): string {
  const text = JSON.stringify(filmProject(project));
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return (h >>> 0).toString(36);
}

export const linkOf = (project: Project) => (project as Linked).codex ?? null;
export const isDirty = (project: Project) => {
  const link = linkOf(project);
  return !!link && link.saved !== fingerprint(project);
};

const labelOf = (show: Show, film: Film) => {
  const ep = show.episodes.find((e) => e.id === film.episode);
  return ep ? `${episodeName(ep)} — ${film.name}` : film.name;
};

/** Save `project` into a show as a film: over `filmId` when given, else as a new one. */
export async function saveFilm(
  project: Project,
  target: { show: string; episode: string; name: string; film?: string },
): Promise<FilmLink> {
  const stored = filmProject(project);
  const link = await withShow(target.show, (show) => {
    let film = target.film ? show.films.find((f) => f.id === target.film) : undefined;
    if (!film) {
      film = { id: uid(), name: "", episode: "", project: {}, updated: 0 };
      show.films.unshift(film);
    }
    film.name = target.name.trim() || "Untitled film";
    film.episode = target.episode;
    film.project = stored;
    film.updated = Date.now();
    return { show: show.id, film: film.id, label: labelOf(show, film), saved: "" };
  });
  link.saved = fingerprint(project);
  (project as Linked).codex = link;
  return link;
}

export interface FilmChoice {
  show: string;
  showName: string;
  film: Film;
  label: string;
}

/** Every film in every show, newest first. */
export async function listFilms(): Promise<FilmChoice[]> {
  const out: FilmChoice[] = [];
  for (const summary of await listShows()) {
    const show = liveShows.get(summary.id)?.show ?? (await loadShow(summary.id))?.show;
    if (!show) continue;
    for (const film of show.films)
      out.push({ show: show.id, showName: show.name, film, label: labelOf(show, film) });
  }
  return out.sort((a, b) => b.film.updated - a.film.updated);
}

/** Replace what's in the studio with a film. */
export function openFilm(project: Project, choice: FilmChoice) {
  const next = toProject(JSON.parse(JSON.stringify(choice.film.project)));
  for (const key of Object.keys(project))
    if (!(key in next)) delete (project as unknown as Record<string, unknown>)[key];
  Object.assign(project, next);
  (project as Linked).codex = {
    show: choice.show,
    film: choice.film.id,
    label: choice.label,
    saved: fingerprint(project),
  };
}

/** Forget which film the studio holds (it becomes a plain project again). */
export function unlink(project: Project) {
  delete (project as Linked).codex;
}
