# Grey Box script format

Plain text that reads into a Grey Box scene (or set, or prop) and writes back out of one. The
editor's **Script** panel shows the open scene or set this way; the command line reads
`*.gb.txt` scene scripts anywhere it reads a scene. Lines starting `//` (or the rest of a line
after `//`) are comments.

## Space and time

- Metres. **Y is up**; the floor (the street) is `y = 0`. A point is `[x, y, z]`.
- `yaw` / `facing` is in degrees around Y: **0 faces +z, 90 faces +x**, 180 faces −z.
- Looking down +z, +x is on the **left** of the picture. An actor's **left** is +x when it faces
  +z.
- Times are `m:ss` with decimals as needed (`0:02.5`), or plain seconds (`2.5`). A **span** is
  `START–END` (en dash or hyphen): `1.9–2.45`.

## Scene scripts

```
# Down the neon wall            // the scene's name
set: neon-wall                  // its set (a file in the show's sets/)
fps: 24
drawn on: twos                  // optional: ones (default), twos, threes, fours
notes: one line about it        // optional

## Cast                         // optional: this scene's own cast (the show's cast.json is used too)
@drone: prop drone, height 0.15
@kid: height 1.3, build 0.8, tone 0.95

## Shapes                       // optional: shapes this scene adds to the set (same lines as a set)
box crate at [1, 0.4, 2] size [0.8, 0.8, 0.8]

## Action
…keys and moves, any order…

## Shot 4A (0:00–2.5)
…camera lines…
```

### Keys: one moment

`TIME @someone CLAUSES` — where someone is, which way they face, how they stand, at that moment.
Between keys they move along a smooth path at a steady pace; two keys at the same spot hold still.

| Clause | Means |
|---|---|
| `at [x, y, z]` / `at MARK` / `at @other` | where they stand (a mark from the set; `@other`: where someone else is) |
| `on SHAPE at [x, z]` / `on SHAPE at MARK` | standing on a shape: its top under that point, **including tilted roofs**. Errors if the point isn't over it |
| `facing 90` / `facing path` / `facing @other` / `facing MARK` | which way they face; `path` (the default) faces where they're going |
| `stand` / `sit` / `crouch` | pose, held until changed |
| `ease linear` / `smooth` / `in` / `out` | how the move starting at this key speeds up and slows down |

A key without a place stays where the one before left them: `1.75 @ren crouch`.
**Every actor's first line is a key with a place** — moves start from where they are.

### Moves: a span of time

`START–END @someone VERB …` expands into the keys that make the move, sampled closely enough that
nobody sinks into a roof or cuts a corner. Each starts from wherever the actor is at `START`.

| Move | Does |
|---|---|
| `runs to PLACE` / `walks to …` / `moves to …` | a straight move to `[x, y, z]` or a mark, standing |
| `runs on SHAPE to [x, z]` | along a surface: the feet follow its top (slopes too) |
| `slides down SHAPE to [x, z]` | the same, crouched — a slide down a pitched roof. **Starts on that shape** |
| `jumps to PLACE[, height N]` / `leaps` / `hops` / `drops` / `falls` | an arc, landing crouched. `PLACE` can be `on SHAPE at [x, z]`. Rises `height` above the higher end: jumps and leaps 0.8 m, hops 0.4, drops and falls 0.15 |
| `leaps to BAR` | an arc that catches a bar (a capsule shape) and hangs from it |
| `climbs down to PLACE` / `climbs up to …` | in reaches of about 1.5 m with a pause between, keeping the way they faced (the wall) |
| `swings on BAR: -15 50 -40 72` | hanging from a bar: the angles out from straight down, in degrees — where it catches, then the peaks either way, eased like a pendulum. **Positive is the way they face** |
| `follows @other[, 6 behind][, 4 up][, 2 left]` | keeps that offset from them, facing them (a drone, a car on someone's tail). `behind`/`ahead`/`left`/`right` are **in the other's frame** — behind is behind the way *they* face |

Speeds that read right: walking 1.4 m/s, running 5–7 m/s, sprinting 8. A running jump across a
3–4 m gap takes about 0.6–0.8 s; a drop of a few metres about 0.5–0.8 s.

### Shots

`## Shot NAME (START–END)` — a camera for that stretch of the scene; shots can overlap or skip.

`TIME from PLACE, looking at PLACE, LENSmm[, ease …]` — a camera key. `from` takes `[x, y, z]`, a
mark or a **set camera** (its position, look and lens; then `looking at` is
optional). `looking at @someone` aims at their face and follows them. Lens is 35 mm-equivalent:
22–28 wide, 35 normal, 50–85 close. Cameras ease smoothly between keys.

`START–END tracks @someone[, 5 behind][, 3 up][, 1 left], LENSmm[, looking at …]` — a camera that
rides along with someone, at that offset in *their* frame, looking at them.

## Set scripts

```
# Neon wall
notes: The wall faces +z, its face at z = 0, 30 m tall.

## Shapes
box wall from [-10, 0, -8] to [10, 30, 0] tone 0.5     // from one corner to the other
box ledge-20 at [0, 19.88, 0.22] size [20, 0.25, 0.45] tone 0.62
box c-roof at [0, 9.0, 43] size [10.4, 0.3, 10.64] tilt 20   // leans forward 20°: a slope
cylinder tank at [-3, 11, 30] radius 1 height 2.6       // stands on `at`
cylinder pipe from [4.7, 0, 0.16] to [4.7, 30, 0.16] radius 0.08   // lying (or upright) between two ends
capsule bar from [-2.55, 17.6, 1.5] to [2.55, 17.6, 1.5] radius 0.045
sphere lamp at [0, 2.6, 0] radius 0.2
prop truck-1 of truck at [3, 0, 7.5] yaw 90 scale 1     // a placed prop

## Marks
pipe-top: [4.25, 28, 0.38]
ledge-20: [4.25, 20, 0.3]

## Cameras
up-the-wall: from [-1, 1.4, 15], looking at [0.5, 19, 0], 22mm
```

- Every shape has a **name** (after its kind): marks, `on SHAPE` and masks use it.
- `box … at [centre] size [w, h, d]` or `box … from [corner] to [corner]`. `yaw` turns it; `tilt`
  leans it forward (front edge down) after its yaw.
- `tone` is its grey, 0 black to 1 white (0.7 if not given). Floors darker, walls mid, small
  things lighter, so forms separate.
- A **bar** for `leaps to` / `swings on` is a `capsule`.

## Prop scripts

A prop is shapes built once around its own origin (on the floor under its middle, **+z its
front**) and placed in sets with `prop NAME of PROP at …`:

```
# Prop: Drone
## Shapes
box body at [0, 0.12, 0] size [0.34, 0.14, 0.46] tone 0.3
sphere pod at [0, 0.03, 0.2] radius 0.07 tone 0.15
```

## Cast scripts

The show's `cast.json` as lines: `@ren: height 1.74, build 1, tone 0.9`, or `@van: prop van,
height 1.75` for a vehicle that moves like an actor.

## Errors

Nothing is applied while a script has errors. Each names its line and, for a misspelt mark or
shape, the close matches: `line 7: at: no mark van-strat — did you mean van-start?`.

## Round trips

Export writes a scene back as a script, with each move as the one line it was written as. Editing
any key a move made, in the editor, turns that move into ordinary keys (so the script never drops
the edit); dragging a key off a surface makes it an ordinary `at`.
