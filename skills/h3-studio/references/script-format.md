# H3 Studio script format

Plain text, read line by line. Blank lines and lines starting with `//` are ignored. Sections are
marked by headings; the order of `## References`, `## Cast` and the scenes is free (references and
cast may come after the scenes that use them).

## Film settings (before any section)

```
# Title                         a label for you; not stored
style: Live-action, cinematic, 35mm, soft tungsten light
direction: animated on twos, with held poses and smear frames on fast moves    said after the style in every scene (optional)
canvas: 1344x768                width x height in pixels, rounded to multiples of 32 (optional)
ambience: rain on glass, distant traffic          heard under every scene unless a scene sets its own
music: sparse piano at a slow tempo               the score for every scene unless a scene sets its own
```

## References

```
## References
- @anna: a woman in her thirties with long dark hair and a blue cardigan
- @platform: a rainy night platform under orange sodium lights (picture)
- @theme: a slow solo cello melody (audio)
```

- `@name` uses letters, numbers, `_` and `-`.
- After the colon is what it looks or sounds like. A reference with no media yet (a *placeholder*)
  is written into the prompt as this description wherever it's mentioned.
- The kind in brackets is optional: `(picture)` (the default), `(video)` or `(audio)`. Add
  `every scene` to show it in every scene whether used or not: `(audio, every scene)`.
- `(video, blocking)` makes a video **blocking**: H3 follows where everyone stands and moves, the
  timing and the camera, and takes nothing else from it (no look, no sound). It's for grey-box
  renders (Grey Box Studio → Render) and rough animatics. It is named `<Video N>`, not a subject,
  and the prompt tells H3 its shapes are stand-ins. A video reference without `blocking` is the
  opposite: H3 copies its people, place and look.
- A scene shows H3 only the references it **uses**: the ones its shots `@mention`, and the ones
  whose voices speak in it. Anything else is left out of that scene's prompt.
- Names the project already has keep their media; a description given here replaces their note.
- Any `@name` used in a shot but declared nowhere becomes a placeholder with no description, which
  is weak. Declare everything.
- In shots, the first mention of a placeholder in a scene is written as its whole description, and
  later mentions as its first clause ("a woman in her thirties, a red coat" becomes "the woman in
  her thirties"). Don't put `'s` after an @name ("the coat of @anna", not "@anna's coat").

## Cast

```
## Cast
- Anna (@anna): a quiet, breathy young female voice
- The conductor: a gruff older man [English]
```

- A voice's name, optionally the reference it belongs to (then H3 attributes the speech to that
  subject), what the voice sounds like, and `[Language]` if not English.
- Voices are matched to the project's by name.

## Scenes

```
## Scene 1: Departure (6s, cut)
ambience: footsteps echoing under a canopy
music: a single held synth note
```

- The heading gives an optional title, then `(length, how)`. `how` says what carries over from the
  previous scene:
  - `cut` (the default): nothing; starts fresh. For a new place or time.
  - `continues`: its last frames lead in, so the motion and the camera carry straight on. For one
    continuous action split across scenes.
  - `from last frame`: opens exactly on its last picture, then moves on its own. For picking up
    where it ended without inheriting its camera move.
  - `sound carries`: a new shot, but the sound (music, ambience) runs on from the previous scene
    across the cut.
  - `same place`: its last picture becomes a reference, `@setting`, so the place and light carry
    over while the shot is new (another angle, a later moment). Mention `@setting` in a shot to
    anchor it.
- Lengths snap up to H3's frame grid (6s becomes 6.58s) and are kept between 1s and 30s; write 2–15.
- `direction:` / `ambience:` / `music:` lines right after the heading override the film's for this
  scene.
- `with: @theme, @rain` right after the heading shows those references in this scene without a
  shot mentioning them (a soundtrack, a style picture).

## Shots

```
### 0:00
### 0:03 (dissolve)
### 0:05.5 (no cut)
```

- `### m:ss` (or `### 3.5s`) starts a shot that many seconds into its scene. The first shot is
  always at 0:00. Every shot must start before the scene's length.
- The text lines under it, up to the next heading, are the shot: what is seen and heard, present
  tense, in order.
- How the shot begins (optional, in brackets):

  | Word | Meaning |
  |---|---|
  | `cut` (default) | a new shot: H3 cuts here |
  | `dissolve`, `fade`, `wipe` | a new shot with that transition |
  | `no cut` | continues the previous shot (joined with "Then,"), with no cut |
  | `no cut, timed` | continues the previous shot at this time ("At 00:05.500, …"), with no cut |

## Dialogue

Inside a shot, a line of the form `NAME (how): words` is dialogue, not description.

```
ANNA: I get off at the next station.
ANNA (softly): I get off at the next station.
CONDUCTOR (V.O.): All aboard!
ANNA & BEN: Wait for us!
ANNA (sings): La la la.
ANNA: I still remember that road >> and the house at the end of it.
ANNA: I just wanted to --
```

- NAME is in CAPITALS, or is a cast name, or an `@reference`. `&` makes several speak together.
- `(how)`:
  - `(V.O.)` / `(O.S.)`: heard off-screen, lips closed.
  - `(sings)`: sung.
  - Anything else: how it's said ("softly", "with a laugh").
- `>>`: what comes after is heard over the next cut (it belongs to this shot but carries into the
  next).
- A line ending in `--` is cut off by the end of the scene. Only use it in a scene's last shot.
- Words are kept exactly, in their own language.
- About 2.5 words take a second; keep each shot's dialogue within its length.
