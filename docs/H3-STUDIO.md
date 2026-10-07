# H3 Studio

Plan a MiniMax H3 film on a timeline and render it a scene at a time.

## The idea in one paragraph

A **film** is a row of **scenes**. A scene is one H3 generation (H3 is trained on about 5–15 s).
Inside a scene, **shots** are the beats of the prompt — H3 writes them as `[Shot 2] At 00:03.500,`
— so cutting a shot on the timeline *is* editing the prompt. **References** (pictures, videos,
audio) tell H3 who and what appears; **keyframes** pin exact frames (the first frame, the last
frame, or a moment in between). A scene can **continue** from the one before it, carrying its last
frames and sound across the cut.

## The node and its wiring

    H3 Studio Setup ──setup──▶ H3 Studio ──render──▶ H3 Studio Outputs ──▶ your sampler / decode
    clip, vae, audio_vae,       the editor             positive, latent, prompt,
    previous scene, scene       (pop-out panel)        trim_frames, frames, size

The studio renders the scene under the playhead (or the `scene` given to Setup). Everything else —
model, sampler, decode, save — is ordinary ComfyUI.

## The editor

| Area | What it is for | How to use it |
|---|---|---|
| Monitor | See the film before rendering it: an animatic at the playhead | Play (Space) or scrub; right-click for options |
| Inspector | Edit what is selected | Click anything on the timeline; with nothing selected it follows the shot under the playhead |
| Timeline | The whole film on one clock | Drag scene ends to change length, shot edges to retime, keyframes to move; double-click a shot to split; right-click for everything else |
| References tab | Every reference, grouped *look*, *meaning*, video, audio, in the order H3 numbers them | Drop or add media; drag a card to reorder, or across the picture groups to switch look/meaning; click to edit |
| Canvas size | The size every scene renders at | Toolbar button: pick an aspect and orientation, then *Native* (H3's own size: 768 short edge, ≤ 1344×768 area) or a megapixel size, or type width × height; always snapped to 32 px |

### References

| Kind | Limit per scene | H3 tag | Notes |
|---|---|---|---|
| Picture | 9 | `<Picture n>` | *Look + meaning* (H3 sees the pixels) or *meaning only* (text encoder only) |
| Video | 3 | `<Video n>` | 2–15 s; plays at 24 fps; can bring its own soundtrack |
| Audio | 3 | `<Audio n>` | A voice, music or sound to follow; soundtracks of videos are numbered first |

Mention a reference in a shot as `@name`; the studio turns it into the right tag.

### Keyframes

| Keyframe | Effect | H3 task |
|---|---|---|
| First frame only | The scene starts exactly on this picture | i2va |
| Last frame only | The scene ends exactly on this picture | l2va |
| First and last | The scene travels from one to the other | fl2va |
| In between | A guide frame at that moment (latent only) | — |

With references in the scene, keyframes still guide the frames but the prompt cannot mention them.

### Continuation

*Cut* starts the scene fresh. *Continue* anchors the previous scene's last 5 / 22 / 39 frames (and
its sound) at frame 0; `trim_frames` says how many to cut from the head after decoding so scenes
join cleanly. Wire the previous scene's decoded frames and audio into H3 Studio Setup.

### Rendering the whole film in a loop

Core's loop nodes render every scene in one run. The clip is what goes round the loop, never the
latent (Start Loop can only take an initial value from outside the loop):

    Start Loop (simple, num_iterations = number of scenes)
      iteration_index ─────────▶ H3 Studio Setup.scene        (counts from 0)
      current_iteration_value ─▶ H3 Studio Setup.previous     (empty on the first pass → a fresh start)
    H3 Studio ▶ Outputs ▶ your sampler ▶ decode video + audio
      ▶ H3 Studio Clip (render, images, audio)                (cuts the carried-over head)
          ├─▶ End Loop.next_iteration_value                   (the next scene continues from it)
          └─▶ End Loop.output_value, accumulate on
    End Loop ▶ Concatenate Video ▶ Save Video

The number of passes needn't be typed in. **H3 Studio Scenes** sits outside the loop and *names*
the studio rather than being wired to it (a wire from the studio would close a cycle round the loop):

    H3 Studio Scenes (pick the studio on the node)
      scene ─▶ Start Loop (List).list                         (one pass per scene, 0, 1, 2, …)
      count ─▶ Start Loop (simple).num_iterations             (or this, in simple mode)

Pick the studio from the node's dropdown — hovering an entry outlines that studio on the canvas, and
the crosshair button pans to it. With only one studio in the workflow it's picked for you. The node
shows the studio's scene count and keeps it in step (that's what tells ComfyUI the loop changed); at
run time the count comes from the studio's project in the same prompt.

**Rendering only some scenes in a loop.** Render ▸ a scene (or several) runs the loop once with the
others held back: a scene that has a clip plays its latest one, and a scene that has never been
rendered plays as black for its length, so the film keeps its timing. A scene that isn't picked
still renders when a picked scene continues from it (Continuation other than *cut*) and it has no
clip to continue from.

A per-scene Save Video or preview on End Loop's terminations runs on every pass, so feed it from
**H3 Studio Clip's `video`** (a skipped scene plays its clip there), not from the decoded frames. Fed
from the decoder it would need a skipped scene's sampler, and a partial render stops with an error
saying so.

### Seeds, reuse and rendering part of the film

Every scene has its own seed (Outputs' `seed` and `noise`): the one shown in its settings, which a
re-roll replaces; a scene that never had one uses a fixed hash of its id, so it renders the same
every time. A continuation also starts from the very noise the previous scene drew for the frames
it regenerates.

H3 Studio Clip records each scene's **latest clip** with a fingerprint of everything that shaped it
(the compiled scene, its media files, the clip it continued from, and the model and sampler chain).
On a later run a scene whose fingerprint still matches plays its saved clip and its sampler never
runs. The editor shows each scene's state on the Scenes track — ✓ up to date, ⟳ out of date (it,
or the scene it continues from, changed since its last render), or not rendered — and the toolbar's
**Render** button (with a count of what's out of date) and a scene's right-click menu render just
part of the film:

- *This scene*, *From here to the end*, *What's out of date*, or *Every scene*.
- In a scene loop it's one run: the scenes you didn't pick play their latest clip without sampling.
- Without a loop (Setup's `scene` unwired, so the studio renders its active scene) it's one run per
  scene, in order. A scene that continues from the previous one picks up that scene's latest clip
  (frames, sound and its sampled latent), so you can re-render scene 4 alone to see how it reads.

A scene that continues from one you haven't re-rendered continues from that scene's older clip:
handy for previews, and the out-of-date mark says when the final film needs a full pass.

## Status

- [x] Project model, prompt compiler (t2va / i2va / l2va / fl2va / ref2va), live prompt preview
- [x] Setup → Studio → Outputs nodes; continuation (guide) with trim
- [x] Editor: monitor animatic, transport, multi-track timeline, inspector, right-click menus
- [x] Video and audio references (loading, encoding, tags, slots)
- [x] Keyframes: first/last slots per scene, clear explanation
- [x] `@` autocomplete with previews; mentions highlighted, unknown ones flagged
- [x] References panel: look/meaning groups, drag to reorder, per-scene use
- [x] Canvas size: aspect + orientation, megapixels, exact W×H, snapped to 32 px
- [x] Pick references and keyframes from ComfyUI's input/output/temp folders (ZenKit `ZenMediaPicker`: folders, kind filters, previews, upload, ordered multi-select)
- [x] Hover a `@mention` to preview what it refers to
- [ ] Flag references whose file has gone missing
- [ ] In-editor help and first-run guidance
- [x] Long-form rendering in one run with core's loop nodes (Setup `previous` + `scene`, H3 Studio Clip)
- [ ] Monitor plays real renders
- [ ] Rewrite: draft, diff, rewrite a selection with presets
