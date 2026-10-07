---
name: h3-studio
description: Write a short film for MiniMax H3 as an H3 Studio script — scenes, shots, timing, transitions, dialogue and placeholder references — that pastes straight into the H3 Studio node (Script → Paste). Use when asked to plan, write, revise or break down a film, ad, short or scene for H3 Studio, or to turn a story or brief into H3 scenes.
---

# H3 Studio scripts

H3 Studio is a ComfyUI node for making films with MiniMax H3, which turns a written description
into video *with* sound. A film is a list of **scenes**; each scene is one H3 generation. The
studio's **Script** dialog reads a plain-text format, so an agent's whole job is to produce a
script in that format. The user pastes it into **Script → Paste**, then adds pictures and renders.

You don't touch the workflow, the node or any files. You write text. The full format is in
[references/script-format.md](references/script-format.md); a complete example is
[examples/night-train.txt](examples/night-train.txt). Read both before writing a script.

## The workflow

1. **Get the brief.** What happens, how long the film is, and the look. Ask only what you can't
   reasonably decide yourself; a strong first draft beats a questionnaire.
2. **Plan the scenes.** Split the film into scenes of **2–15 seconds** (H3's trained range; 5–10 is
   the sweet spot). Each scene is a separate generation:
   - `(continues)` starts a scene from the end of the one before. Use it for continuous action.
   - `(same place)` keeps the place and light of the scene before as `@setting`, in a new shot.
     Use it to cut to another angle or a later moment in the same location.
   - `(from last frame)` opens exactly on the last picture of the scene before.
   - `(cut)` starts it fresh. Use it for a new place or time.
3. **Cast it with references.** Every character, place or object that appears in more than one shot
   gets an `@name` in `## References`, with a concrete visual description. Until the user adds a
   picture, H3 reads that description in place of the `@name` (a *placeholder*). So make it specific
   enough to keep the character consistent across scenes: age, build, hair, clothes, colours.
   Write each description as **one noun phrase** ("a lean young man with messy black hair, a black
   sleeveless shirt and a chrome right arm"), with no semicolons or full sentences: it's pasted into
   the shot sentence in place of the `@name`, and its first comma clause ("the lean young man with
   messy black hair") stands in for it on later mentions.
   Characters who speak also go in `## Cast`, linked to their reference.
   **Blocking.** If the user has grey-box renders (Grey Box Studio) or an animatic for a scene,
   declare each as `@name: … (video, blocking)` and put `with: @name` under that scene's heading.
   Make the scene the same length as the render, and put its shots at the render's cuts. H3 takes
   only staging, timing and camera from it, so still describe the people, place, light and camera
   move in words. Never use a plain `(video)` for blocking: H3 would copy its grey look.
4. **Write the shots.** In each scene, `### m:ss` starts a shot at that time. **Every new shot is a
   camera cut.** For continuous motion, describe it in one shot, or continue it with `(no cut)`.
   Write what the camera *sees and hears*, in order, in the present tense.
5. **Write the dialogue** as `NAME: words` under the shot it's spoken in. Keep each shot's speech
   short enough to say in it, about **2.5 words a second**.
6. **Deliver** the script in one fenced block, then list:
   - the placeholders the user should give pictures to (`@anna`, `@platform`, …);
   - anything you assumed.

   Tell them to paste it with **Script → Paste → Replace the project** (or **Add after the scenes**).

To **revise** an existing film, ask the user for **Script → Copy**. Edit that text and hand back the
whole script; reference names that already exist keep their pictures.

## Writing for H3

H3 learned from prompts written a particular way. Follow it:

- **Concrete and visible.** Composition, who is where, light, materials, how things move. Don't use
  mood words ("melancholy", "epic") or explain intentions; show what produces them.
- **Camera as a sentence:** motion type, plus amplitude and speed when they matter.
  - Types: push in / pull out, pan left / right, truck left / right, tilt up / down,
    pedestal up / down, arc shot, tracking shot, static shot, slight / strong shake, POV,
    zoom in / out.
  - For example: "The camera pushes in with small amplitude at slow speed toward her hands."
- **A cut should add information:** a new subject, place, viewpoint or time. If only the framing
  changes a little, use camera motion inside the shot instead.
- **Visible text** (signs, labels) in "double quotes", exactly as it reads.
- **No possessives on @names.** Write "the reflection of @anna", not "@anna's reflection": an @name
  becomes a long description (for a placeholder) or a `<Subject N>` tag, and neither takes "'s".
- **Dialogue in its original language**, word for word. The studio writes it into H3's dialogue
  syntax for you; never write `<d>`, `(S1)`, `[Shot 1]` or timestamps inside the text.
- **Style once, at the top** (`style:`), in live-action / film terms for photoreal work. Don't mix
  in illustrator or anime names unless the film is meant to look illustrated.
- **Direction once, at the top** (`direction:`): how the film is made, said after the style in every
  scene: animation timing ("animated on twos, held poses"), camera habits ("mostly locked-off
  framing"), lens or film-stock texture. Keep it to a sentence; a scene can set its own.
- **Sound:**
  - `ambience:` is what's heard in the world (rain, traffic, footsteps).
  - `music:` is the score only the audience hears: instruments, tempo, dynamics, not moods.
  - Leave `music:` out for none.

## What a script can't hold

The script covers story, timing and dialogue. Pasted with **Replace the project**, the script becomes
the film: references and voices it doesn't use are removed (the user can choose to keep them), and
the scenes' keyframes and per-scene LoRA strengths go with the old scenes. Kept: pictures of the
references it uses, LoRA lanes, the canvas size (unless `canvas:` sets one) and render settings.
So **declare every reference the film needs**, even one no shot mentions yet. If the film needs
keyframes or per-scene LoRA strengths, say so in your notes, e.g. "add a first-frame keyframe to
scene 3 for the exact framing".

## Checklist before you hand it over

- Every scene has a length between 2s and 15s, and the shots in it start before that length.
- The first shot of each scene is at `0:00`.
- Every `@name` used in a shot is declared in `## References`, with a description.
- Every speaker is in `## Cast` (or is a reference), in CAPITALS in dialogue lines.
- Speech fits its shot (about 2.5 words per second).
- No `@name's`: write "the hand of @anna", "the door of @carriage".
- Nothing in shot text that the studio writes itself: no `[Shot N]`, timestamps, `<d>`, `(S1)`.
