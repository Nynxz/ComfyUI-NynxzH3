# Grey box

Simple 3D blocking for shots: a **set** made of plain shapes, the **cast** as labelled figures
moving between marks, and a **camera** per shot — rendered as grey video. MiniMax H3 takes that
video as a reference, so a shot's layout, staging and camera move stay put instead of being
re-imagined every time.

Everything is plain JSON, written by people or agents. Nothing to install: rendering is torch,
with exact ray–shape intersection (no meshes), on the GPU in ComfyUI or the CPU from the command
line.

Scenes, sets and props can also be written as **Grey Box scripts** — readable text with moves
like `runs on`, `jumps to` and `swings on` — in the editor's Script panel or from the command
line: see [GREYBOX-SCRIPT.md](GREYBOX-SCRIPT.md) and the `grey-box` skill.

## Grey Box Studio (the editor)

The **Grey Box Studio** node is the editor: pick a project (a Codex show; its grey box lives in
`nynxz-codex/<show>/greybox/`) and a scene. It pops out into a ZenKit panel like H3 Studio, and
the node and its panel share one session — undo history and the view carry across.

- **Outliner** (left): shots, characters, the set's shapes, marks and set cameras; + adds one.
- **View** (middle): *Free* orbits the set, *Shot* looks through the current shot's camera
  (framed to the node's width × height, with only what the render will show), *Plan* is from
  above. Click to select; W / E / R move, turn and resize what's selected; F frames it (the
  whole set when nothing is).
- **Inspector** (right): every value of what's selected.
- **Timeline** (bottom): the shots, a track of keys per character and the camera's keys; drag to
  retime. Space plays; the cut button switches between following cuts and staying on one shot.
- **Still** renders the current moment exactly; **Render** writes the shot's grey video to
  `output/greybox/`.

Every edit is a named action (the same ones agents use, below) and one undo step (a gizmo drag
is one step). Changes save to the files half a second later; edits made to the files outside the
editor are picked up within a few seconds.

The node renders the shot it's left on, like Grey Box Shot.

## Agent tools (ZenAgent)

ZenAgent sees these as tools; they work whether or not an editor is open. When a Grey Box Studio
shows the scene, changes go through it — live on screen and undoable — otherwise to the files.

- `greybox.projects` — the projects with their scenes and sets.
- `greybox.read {project?, scene?}` — the scene, its set and the cast as JSON. Read first.
- `greybox.act {project?, scene?, actions: [{action, ...args}]}` — run actions in order; it stops
  at the first that fails and says why (`done` lists what worked). Anywhere a point goes, a
  mark's name or `"@actor"` works too. The actions (each tool description lists their arguments):
  `shape.add/update/remove/duplicate`, `mark.set/rename/remove`, `setcam.set/remove`,
  `set.update`, `cast.set`, `actor.add/remove`, `key.set/move/remove`,
  `shot.add/update/remove`, `camkey.set/move/remove`, `scene.update`.
- `greybox.look {project?, scene?, what: "sheet"|"still", shot?, t?}` — an image: the contact
  sheet with the plan, or one exact frame. Look after every few changes — the sheet shows when a
  move has walked someone out of frame or behind the counter.
- `greybox.new_scene {project?, name, set}` — a new scene, on an existing set or a fresh floor.

Project and scene can be left out when there's only one, or when an editor has one open.

## The loop (command line)

Build a set and a scene, look, fix, look again:

```bash
cd ComfyUI
.venv/bin/python custom_nodes/ComfyUI-NynxzH3Studio/nodes/greybox/cli.py check  path/to/scenes/scene.json
.venv/bin/python custom_nodes/ComfyUI-NynxzH3Studio/nodes/greybox/cli.py sheet  path/to/scenes/scene.json
.venv/bin/python custom_nodes/ComfyUI-NynxzH3Studio/nodes/greybox/cli.py frame  path/to/scenes/scene.json --shot 1A --at 2.4
.venv/bin/python custom_nodes/ComfyUI-NynxzH3Studio/nodes/greybox/cli.py plan   path/to/scenes/scene.json --at 3
.venv/bin/python custom_nodes/ComfyUI-NynxzH3Studio/nodes/greybox/cli.py video  path/to/scenes/scene.json --shot 1A
```

- `check` validates and summarises: shapes, marks, set cameras, actors, shots.
- `sheet` is the main view: every shot as a row of frames from its camera, plus the **plan** —
  the set from above with its marks, each actor's path (dot at the start, a tick for where it
  faces at the end) and each shot's camera. Read both: the frames say what the shot looks like,
  the plan says why.
- `frame` is one large still of a shot at a time, for checking details (is she in the doorway?).
- `video` writes the shot as an mp4 (`--depth` for its depth instead).

Outputs land in `renders/` beside the scene. A sheet takes about a second on a CPU.

In ComfyUI, the **Grey Box Shot** node renders a shot: its frames, depth, one character's mask and
the contact sheet, and saves the grey video to `output/greybox/` (its `video_ref` is a media ref
that H3 Studio can take as a reference).

## Folder layout

```
greybox/
  cast.json          everyone's figure: height, build, grey
  sets/<set>.json    places, built once, reused by every scene there
  props/<prop>.json  objects built once from shapes (a truck, a table), placed in sets
  scenes/<scene>.json
```

A scene names its set (`"set": "midnight-spoon"`) and finds it in `sets/` beside its folder; the
cast comes from `cast.json` there. A worked example ships in
`nodes/greybox/examples/midnight-spoon/`.

## Space

- Metres. **Y is up**, the floor is `y = 0`.
- A point is `[x, y, z]`; on the floor, `y` is 0.
- `yaw` is the way something faces, in degrees around Y: **0 faces +Z, 90 faces +X**, 180 faces −Z.
- Looking toward +Z, +X is on the **left** of the picture. When a layout reads mirrored, check the
  plan rather than guessing.
- Pick a convention per set and write it in its `notes` (e.g. "street at +Z, kitchen at −Z").

## Sets — `sets/<name>.json`

```json
{
  "name": "Midnight Spoon",
  "notes": "Street (and the door) at +z, kitchen along the back wall at -z.",
  "shapes": [
    { "id": "floor",   "type": "box",      "at": [0, -0.05, 0], "size": [4.4, 0.1, 9], "tone": 0.42 },
    { "id": "counter", "type": "box",      "at": [0, 0.52, -2.2], "size": [3.4, 1.04, 0.6], "yaw": 0, "tone": 0.74 },
    { "id": "stool-1", "type": "cylinder", "at": [-1.5, 0, -1.45], "radius": 0.19, "height": 0.72 },
    { "id": "lamp",    "type": "sphere",   "at": [0, 2.6, 0], "radius": 0.2 },
    { "id": "pipe",    "type": "capsule",  "a": [-2, 2.8, -4], "b": [-2, 2.8, 4], "radius": 0.05 }
  ],
  "marks":   { "stove": [-0.9, 0, -3.65], "door": [1.3, 0, 4.2] },
  "cameras": { "wide-from-door": { "at": [1.5, 1.65, 4.2], "look": [-0.4, 1.1, -3.4], "lens": 24 } }
}
```

Shapes:

| type       | where                                                     | size                         |
| ---------- | --------------------------------------------------------- | ---------------------------- |
| `box`      | `at`: its centre                                          | `size`: [w, h, d]; `yaw`     |
| `cylinder` | `at`: the middle of its base (it stands on `at`)          | `radius`, `height`           |
| `sphere`   | `at`: its centre                                          | `radius`                     |
| `cylinder` | from `a` to `b` when they're given: lying down, any way   | `radius`                     |
| `capsule`  | from `a` to `b` (any direction), rounded ends             | `radius`                     |
| `prop`     | `at`: the spot on the floor its origin goes               | `prop`: its name; `yaw`, `scale` |

- `tone`: its grey, 0 (black) to 1 (white); default 0.7. Keep floors darker, walls mid, furniture
  lighter, so forms separate. Characters are lighter still.
- `id`: name it (walls, counter, stool-3) — the plan and masks use it.
- **No ceiling**: the key light comes from above, through where a ceiling would be.
- **Walls with openings** are built from pieces around the gap (a low wall under a window, a beam
  over a door).
- `marks` are named spots on the floor that actors and cameras can use by name. Mark every place a
  character stands, sits or enters from.
- `cameras` are named set-ups (`at`, `look`, `lens`) for the angles the place is usually shot from.

## Props — `props/<name>.json`

A prop is an object built once from shapes and placed as often as needed: a truck, a booth, a
lamp post. Change the prop and every place it stands follows.

```json
{
  "name": "Box truck",
  "notes": "Origin on the ground under the middle; +z is the front.",
  "shapes": [
    { "id": "cargo",      "type": "box", "at": [0, 1.75, -0.9], "size": [2.2, 2.3, 4.2], "tone": 0.82 },
    { "id": "cab",        "type": "box", "at": [0, 1.3, 2.05],  "size": [2.1, 1.7, 1.7], "tone": 0.7 },
    { "id": "windscreen", "type": "box", "at": [0, 1.7, 2.91],  "size": [1.8, 0.7, 0.04], "tone": 0.18 },
    { "id": "wheel-fl",   "type": "cylinder", "a": [1.0, 0.45, 1.9], "b": [1.2, 0.45, 1.9], "radius": 0.45, "tone": 0.15 }
  ]
}
```

Placed in a set:

```json
{ "id": "truck-1", "type": "prop", "prop": "truck", "at": [3, 0, 7.5], "yaw": 90, "scale": 1 }
```

- Build it around its own origin: the spot on the floor it's placed at, with **+z its front**.
- Dark shapes read as glass and openings: windows a little proud of the body at `tone` ~0.2.
- `yaw` turns it like a box; `scale` grows or shrinks all of it. A prop can place other props.
- A placed prop is **one object**: it moves as one in the editor and has one mask.
- In the editor: **Props** in the outliner places a prop (+) or opens it (✎); while it's open,
  the shape tools build it, and **Done** goes back to the set. Agents use `prop.new`, `prop.edit`,
  `prop.make` (shapes already in the set become a prop, placed where they were) and `prop.done`.

## Cast — `cast.json`

```json
{ "@ren": { "height": 1.74, "build": 1.0, "tone": 0.9 } }
```

A figure is a body, a head and a small block on the face — which way it faces reads at a glance.
`build` scales its width; `tone` tells characters apart. A scene can override with its own `cast`.

A cast member can be a **prop** instead — a vehicle that moves through the scene with keys like
anyone else, facing where it's going:

```json
{ "@van": { "prop": "van", "height": 1.75 } }
```

`height` is then where a camera told to look at it aims (for a van, about the windscreen). The
example ships a van, a sedan and a street lamp (`build_props.py`), a night street
(`build_street.py`) and a two-scene chase on it (`build_chase.py`).

## Scenes — `scenes/<name>.json`

```json
{
  "name": "Mika arrives",
  "set": "midnight-spoon",
  "fps": 24,
  "actors": [
    { "id": "@mika", "keys": [
      { "t": 0,   "at": "street", "face": "path" },
      { "t": 2.0, "at": "door" },
      { "t": 4.5, "at": [0.6, 0, -0.9] },
      { "t": 5.5, "at": "stool-3", "face": 180, "pose": "sit" }
    ] }
  ],
  "shots": [
    { "name": "1A", "start": 0, "end": 2.5, "camera": [
      { "t": 0,   "at": "wide-from-kitchen", "look": "@mika" },
      { "t": 2.5, "at": "wide-from-kitchen", "look": "@mika", "lens": 30 }
    ] }
  ]
}
```

`"on": 2` draws the scene **on twos** (`3` on threes; `1`, the default, on ones): every actor
holds each pose for that many frames, so motion steps the way limited animation does instead of
gliding. The camera holds on the same frames: a camera moving on ones past actors on twos slides
them back across the frame during each hold and jumps them forward at the next, a judder. Renders, depth renders (the
ControlNet's) and the editor's playback all follow it; in the editor it's **Drawn on** in the
scene's settings.

### Actor keys

- `t`: seconds from the start of the scene. Keys are sorted by time.
- `at`: where it stands — `[x, y, z]`, a mark's name, or `"@other"` (where they stand).
  Between keys it moves along a smooth curve through all its keys, at a steady pace; before its
  first key and after its last it holds still. To stand somewhere for a while, give two keys with
  the same `at`.
- `face`: a yaw in degrees; `"path"` (the way it's moving — the default); an actor (`"@ren"`) or a
  mark to face it. It holds from its key until another key changes it. Between two numeric keys
  it turns smoothly.
- `pose`: `"stand"` (default) or `"sit"` — held until another key changes it.
- `ease` (per key, for the move that starts there): `linear` (default), `smooth`, `in`, `out`.

### Shots

- `name`, `start`, `end` (seconds in the scene). Shots can overlap or skip time.
- `camera`: keys, like an actor's, with times in scene seconds:
  - `at`: `[x, y, z]`, a mark (at 1.6 m eye height), or a **set camera's name** (its position,
    look and lens, which the key can override).
  - `look`: where it points — `[x, y, z]`, a mark (at 1.2 m), or `"@actor"` (their face, so the
    camera follows them).
  - `lens`: mm, 35 mm-equivalent (24 wide, 35 normal, 50–85 close). Default 35.
  - Camera moves ease `smooth` unless a key says otherwise.

Errors name what's wrong (an unknown mark lists the set's marks).

## Blocking well

- Build the set from the place's reference first, then `sheet` it with a simple scene before
  staging anything: a wrong-handed or wrong-scaled set ruins every shot after it.
- Stage the people, then the cameras. Check the plan: does each camera see what the shot is
  about? Is anyone walking through furniture?
- Use the place's marks and cameras for recurring angles, so episodes agree with each other.
- A grey box is about layout, scale and motion — not looks. Keep shapes few and big.
