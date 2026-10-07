// A show's folders: paths like "Main cast/Family", each entry sitting in one (or none). Renaming or
// moving a folder carries its subfolders and entries with it; deleting one hands its contents to
// the folder it was in, so nothing is ever lost by tidying up.
import { cleanFolder, type Show } from "./codex";

export const nameOf = (path: string) => path.split("/").pop() ?? path;
export const parentOf = (path: string) => path.split("/").slice(0, -1).join("/");
const within = (path: string, root: string) => path === root || path.startsWith(`${root}/`);

/** The folder's subfolders, one level down. */
export function childrenOf(show: Show, path: string): string[] {
  return show.folders
    .filter((f) => parentOf(f) === path && f !== path)
    .sort((a, b) => nameOf(a).localeCompare(nameOf(b)));
}

function freeName(show: Show, parent: string, base: string): string {
  const join = (n: string) => (parent ? `${parent}/${n}` : n);
  let name = base;
  for (let n = 2; show.folders.includes(join(name)); n++) name = `${base} ${n}`;
  return join(name);
}

export function addFolder(show: Show, parent: string, name = "New folder"): string {
  const path = freeName(show, parent, cleanFolder(name) || "New folder");
  show.folders.push(path);
  return path;
}

/** Move everything under `from` to `to` (a rename, or a move into another folder). */
function relocate(show: Show, from: string, to: string) {
  const swap = (p: string) => (within(p, from) ? to + p.slice(from.length) : p);
  show.folders = [...new Set(show.folders.map(swap))];
  for (const e of show.entries) if (e.folder && within(e.folder, from)) e.folder = swap(e.folder);
}

export function renameFolder(show: Show, path: string, name: string): string {
  const clean = cleanFolder(name.replace(/\//g, " "));
  if (!clean || clean === nameOf(path)) return path;
  const to = freeName(show, parentOf(path), clean);
  relocate(show, path, to);
  return to;
}

/** Move folder `path` into `into` ("" for the top). Refused into itself or its own subfolders. */
export function moveFolder(show: Show, path: string, into: string): string {
  if (within(into, path) || parentOf(path) === into) return path;
  const to = freeName(show, into, nameOf(path));
  relocate(show, path, to);
  return to;
}

export function deleteFolder(show: Show, path: string) {
  const up = parentOf(path);
  const swap = (p: string) =>
    within(p, path)
      ? p === path
        ? up
        : up
          ? `${up}/${p.slice(path.length + 1)}`
          : p.slice(path.length + 1)
      : p;
  show.folders = [
    ...new Set(
      show.folders
        .filter((f) => f !== path)
        .map(swap)
        .filter(Boolean),
    ),
  ];
  for (const e of show.entries) if (e.folder && within(e.folder, path)) e.folder = swap(e.folder);
}

/** How many entries sit in the folder, its subfolders included. */
export const countIn = (show: Show, path: string) =>
  show.entries.filter((e) => e.folder && within(e.folder, path)).length;
