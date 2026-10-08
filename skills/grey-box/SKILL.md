---
name: grey-box
description: Block a scene in 3D for Grey Box Studio — a set of plain shapes, characters and vehicles moving through it (running, jumping, sliding, climbing, swinging, following) and a camera per shot — written as a Grey Box script, checked by rendering, and handed to H3 Studio as a control or blocking video. Use when asked to block, stage, previs or lay out a scene, action beat or chase in Grey Box, to build a set or prop for it, or to make the control video an H3 Studio scene follows.
---

# Grey Box scripts

Grey Box Studio is a ComfyUI node for **blocking**: plain grey shapes for the set, simple figures
for the people, and a camera per shot, rendered as grey, depth or edge videos. H3 Studio uses
those videos to follow the layout, staging and camera of a scene (a **Control** reference through
the H3 Fun ControlNet, or a **blocking** reference). The look comes from H3; Grey Box is only
about *where things are and how they move*.

You write a **Grey Box script**: plain text the editor's **Script** panel and the command line both
read. The full format is [references/script-format.md](references/script-format.md); complete
examples are in [examples/](examples/) — read the format and one example before writing.

## The workflow

1. **Know the set.** Most scenes reuse a set from the show (`sets/` in its `greybox/` folder). Get
   its script: the editor's **Script → Set** tab, or `cli.py export` of a scene that uses it, or read
   `sets/NAME.json`. Note its **marks**, its **shape names** (you'll stand people `on` them) and its
   axes (its `notes` say which way is the street, the wall, the run). If there's no set, write one
   (see *Building a set*).
2. **Plan the action** as beats with times, in seconds: who is where, what they do, how long it
   takes at believable speeds (walk 1.4 m/s, run 5–7, a running jump 0.6–0.8 s). Match the H3
   scene's length (H3 scenes are about 5–10 s; 7 s is common).
3. **Write the `## Action`.** Give every actor a first key with a place, then moves for anything
   athletic: `runs on`, `jumps to`, `slides down`, `climbs`, `swings on`, `drops to`, `follows`.
   Use `on SHAPE at [x, z]` for anyone standing on something above the floor — never guess a
   height: the script reads it off the shape (sloped roofs too).
4. **Write the shots.** One `## Shot` per camera, cut where the H3 script's shots start. Frame what
   the shot is *about*: the subject reasonably large (lens and distance), nothing big between the
   camera and them, and enough of the place to read where they are. `tracks @someone` for a camera
   that rides along.
5. **Check it, then look at it.** Save the script as `NAME.gb.txt` inside the show's `greybox/`
   folder (or anywhere under a folder with `sets/`), and run:

   ```
   python nodes/greybox/cli.py check NAME.gb.txt     # errors by line, with suggestions
   python nodes/greybox/cli.py sheet NAME.gb.txt     # renders/NAME.sheet.png: frames of every shot + a plan
   ```

   **Open the sheet and look.** Can you see the subject in every frame? Is anyone inside a wall,
   floating, or hidden behind a sign? Does each shot show what it should? Fix and repeat. (In the
   editor instead: paste into **Script → Apply**, then play it.)
6. **Deliver.** Either paste the script into the editor's **Script** panel (**Apply**; undo puts the
   old scene back), or `cli.py import NAME.gb.txt` to write `scenes/NAME.json`. Then, for H3 Studio:
   **Render → Edges** (or **Depth**, reach Balanced) and give the video to a `(video, control)`
   reference in the scene's H3 script, with the H3 shots starting at the same times as these shots.

## Writing moves that read

- **A move starts where the actor is.** Put a key (or another move) before it. A slide or a run
  `on SHAPE` must start over that shape — hop onto a slope before sliding down it.
- **Landings crouch** automatically; the next `runs` stands them up. A pose-only key changes pose
  on the spot: `5.30 @ren stand`.
- **`follows` and `tracks` offsets are in the target's frame.** "Behind" is behind the way *they*
  face. Someone running out from a wall has the wall behind them — a drone chasing them from the
  front is `ahead`.
- **Swings:** the bar is a `capsule`; positive angles are the way the swinger faces. Catch near
  0 (`-15`), alternate peaks that grow, and let go at the biggest one, then `drops to` the landing.
- **Climbing** keeps the way they faced: key them `facing` the wall first (`facing 180` for a wall
  at their −z).

## Building a set

Keep shapes **few and big** — layout, scale and silhouette, not detail. Build the ground and the
main masses first, then what people touch (ledges, rails, the roof they run on), then a few things
for scale and depth (lamps, signs, buildings behind). Name every shape, mark every spot someone
stands, starts or lands, and add a couple of named cameras for the angles the place is shot from.
Tone: floors darker (0.2–0.4), walls mid (0.45–0.55), things lighter (0.6–0.9). Write in the
set's `notes` which way is which. Check a new set with a simple scene and a sheet before staging
anything on it — a wrong-handed or wrong-scaled set ruins every shot after it.

## Hand-off to H3 Studio

The Grey Box scene and the H3 scene are the same moment: same length, shots at the same times, and
the H3 shot text describing what each Grey Box camera sees (the same angle, the same action). The
H3 script declares the render as `@control_NAME: … (video, control)` with `with: @control_NAME`
under the scene. See the `h3-studio` skill.
