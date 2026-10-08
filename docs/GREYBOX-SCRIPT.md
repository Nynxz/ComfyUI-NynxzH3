# Grey Box scripts

A Grey Box scene, set, prop or cast as readable text — the way people and agents write and edit
blocking without JSON. The full format is in
[skills/grey-box/references/script-format.md](../skills/grey-box/references/script-format.md), and
the `grey-box` skill ([skills/grey-box/SKILL.md](../skills/grey-box/SKILL.md)) is the workflow for
writing one; worked examples are in [skills/grey-box/examples](../skills/grey-box/examples).

Where scripts are read and written:

- **The editor:** Grey Box Studio's **Script** button shows the open scene (or its set) as a
  script. Edit it or paste one in and **Apply**: nothing changes while it has errors (each names
  its line); a clean script replaces the scene or set as one undo step.
- **The command line:** `nodes/greybox/cli.py` reads `NAME.gb.txt` scene scripts anywhere it reads
  a scene (`check`, `sheet`, `frame`, `video`…), and `import` / `export` convert between script and
  JSON. The set, props and cast are found in the show folder around the script.
- **The server:** `POST /nynxz/greybox/script/export` `{kind, data}` and
  `POST /nynxz/greybox/script/import` `{kind, text, project}` → `{data, errors}`.

Moves (`runs on`, `jumps to`, `slides down`, `climbs`, `swings on`, `follows`, and cameras that
`track`) expand into ordinary keys when a script is read, so the engine, the renderer and the
editor see the same keys as ever; exporting writes each move back as the line it was written as.
