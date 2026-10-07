"""H3 Studio's dialogue: a cast of voices, and the lines they speak in each shot, written into the
prompt the way MiniMax's H3 prompt-writing guide lays it out.

    cast   [{id, name, ref, timbre, voice, language}] — `ref` links a voice to a reference (it is
           then that `<Subject N>`), `timbre` to an audio reference its voice follows
    lines  per shot [{speakers, mode, delivery, words, next, cutoff, language}]

A line becomes `<who> (S1) says softly: <d>[English] exact words</d>`:

- speaker IDs `(S1)`, `(S2)` … count up in the order voices are first heard in the scene, and a
  group speaking together is `(S1,S2)`;
- the words go in verbatim with their language tag; everything else (who, how) stays outside `<d>`;
- the voice is described the first time a speaker is heard;
- a voice-over says `says in an off-screen voiceover` and states that the lips stay closed;
- a line placed after a real silence (dragged along the timeline) opens with "After a pause,";
- a line that crosses into the next shot is split there with `<scenetrans>` on both sides, and a
  line cut short by the end of the clip ends in `<cutoff>`.
"""

from __future__ import annotations

import re
from typing import Any

MODES = ("say", "voiceover", "sing")
_VERBS = {"say": "says", "voiceover": "says in an off-screen voiceover", "sing": "sings"}
_GROUP_VERBS = {"say": "say", "voiceover": "say in an off-screen voiceover", "sing": "sing"}
#: A longer silence than this before a line is written into the prompt as a pause.
PAUSE = 0.8
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def speech_seconds(text: str, mode: str = "say") -> float:
    """Roughly how long a line takes to say (the editor's `speechSeconds`): ~2.6 words a second,
    ~4.5 characters a second in Chinese, Japanese or Korean, slower when sung."""
    if not text.strip():
        return 0.0
    cjk = len(_CJK.findall(text))
    words = len(_CJK.sub(" ", text).split())
    seconds = words / 2.6 + cjk / 4.5
    return max(0.6, seconds * (1.6 if mode == "sing" else 1))


def _str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def normalize_cast(raw: Any) -> list[dict[str, Any]]:
    cast = []
    for i, v in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(v, dict):
            continue
        cast.append(
            {
                "id": _str(v.get("id")) or f"v{i + 1}",
                "name": _str(v.get("name")) or f"Speaker {i + 1}",
                "ref": _str(v.get("ref")),
                "timbre": _str(v.get("timbre")),
                "voice": _str(v.get("voice")),
                "language": _str(v.get("language")) or "English",
            }
        )
    return cast


def normalize_lines(raw: Any) -> list[dict[str, Any]]:
    lines = []
    for i, line in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(line, dict):
            continue
        speakers = [s for s in line.get("speakers") or [] if isinstance(s, str) and s]
        lines.append(
            {
                "id": _str(line.get("id")) or f"d{i + 1}",
                "speakers": list(dict.fromkeys(speakers)),
                "mode": line.get("mode") if line.get("mode") in MODES else "say",
                "delivery": _str(line.get("delivery")),
                # The words are the user's, verbatim: only the ends are trimmed.
                "words": line.get("words").strip() if isinstance(line.get("words"), str) else "",
                "next": line.get("next").strip() if isinstance(line.get("next"), str) else "",
                "cutoff": line.get("cutoff") is True,
                "language": _str(line.get("language")),
                "at": float(line["at"])
                if isinstance(line.get("at"), (int, float)) and line["at"] >= 0
                else None,
            }
        )
    return lines


class Dialogue:
    """Writes one scene's lines, numbering speakers as they are first heard."""

    def __init__(
        self,
        cast: list[dict[str, Any]],
        refs: list[dict[str, Any]],
        warnings: list[str],
        *,
        subjects: bool,
    ):
        self.voices = {v["id"]: v for v in cast}
        self.refs = {r["id"]: r for r in refs}
        self.subjects = subjects
        self.warnings = warnings
        self.ids: dict[str, int] = {}
        self.timbres: list[str] = []

    def _name(self, voice: dict[str, Any]) -> str:
        ref = self.refs.get(voice["ref"]) if self.subjects else None
        return f"<Subject {ref['subject']}>" if ref and ref["subject"] else voice["name"]

    def _timbre(self, voice: dict[str, Any]) -> str | None:
        ref = self.refs.get(voice["timbre"]) if self.subjects else None
        return ref["tag"] if ref and ref["kind"] == "audio" else None

    def _who(self, line: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
        """The speakers' names, their `(S…)` id, and which of them are heard for the first time."""
        voices = [self.voices[v] for v in line["speakers"] if v in self.voices]
        first = [v for v in voices if v["id"] not in self.ids]
        for v in first:
            self.ids[v["id"]] = len(self.ids) + 1
            tag = self._timbre(v)
            if tag:
                self.timbres.append(
                    f"{tag} is the voice-timbre reference for {self._name(v)} (S{self.ids[v['id']]})."
                )
        names = " and ".join(self._name(v) for v in voices)
        label = "(" + ",".join(f"S{self.ids[v['id']]}" for v in voices) + ")"
        return names, label, first

    def _words(self, line: dict[str, Any], words: str, *, before: str = "", after: str = "") -> str:
        voices = [self.voices[v] for v in line["speakers"] if v in self.voices]
        language = line["language"] or (voices[0]["language"] if voices else "English")
        return f"<d>[{language}] {before}{words}{after}</d>"

    def line(self, line: dict[str, Any], *, cut_after: bool, final: bool, lead: str = "") -> str:
        """One line. `cut_after`: a cut follows its shot (a line can only cross a cut);
        `final`: its shot ends the clip (only there can speech be cut off)."""
        if not line["words"]:
            return ""
        names, label, first = self._who(line)
        if not names:
            self.warnings.append("A line of dialogue has no speaker — it was left out.")
            return ""
        group = len(line["speakers"]) > 1
        verb = (_GROUP_VERBS if group else _VERBS)[line["mode"]] + (" together" if group else "")
        how = [line["delivery"]] if line["delivery"] else []
        if len(first) == 1 and not group:
            voice = first[0]
            if voice["voice"]:
                described = voice["voice"]
                if described.split(" ", 1)[0].lower() in ("in", "with", "using"):
                    how.append(described)
                elif "voice" in described.lower():
                    how.append(f"in {described}")
                else:  # a person ("a gruff older man") rather than a sound
                    how.append(f"with the voice of {described}")
            tag = self._timbre(voice)
            if tag:
                how.append(f", using the voice timbre referenced from {tag}")
        crosses = bool(line["next"])
        if crosses and final:
            self.warnings.append(
                "A line continues across the cut, but it is in the scene's last shot — it is kept whole."
            )
        split = crosses and cut_after
        cutoff = line["cutoff"] and not split
        if line["cutoff"] and not final:
            self.warnings.append(
                "<cutoff> is for speech cut short by the end of the clip; it is used in a shot that is not the last."
            )
        words = line["words"]
        if crosses and not split:
            words = f"{words} {line['next']}"
        manner = " ".join([verb, *how]).replace(" ,", ",")
        who = names if lead else f"{names[:1].upper()}{names[1:]}"
        text = f"{lead}{who} {label} {manner}: " + self._words(
            line,
            words,
            after=(" <scenetrans>" if split else "") + (" <cutoff>" if cutoff else ""),
        )
        if line["mode"] == "voiceover":
            text += " while their lips remain completely closed."
        if split:
            text += " The line continues seamlessly across the cut."
        return text

    def carried(self, line: dict[str, Any]) -> str:
        """The part of a line that carries on into the next shot."""
        names, label, _ = self._who(line)
        text = f"The voice of {names} {label} carries over from the previous shot: " + self._words(
            line, line["next"], before="<scenetrans> "
        )
        if line["mode"] == "voiceover":
            text += " while their lips remain completely closed."
        return text

    def shot(
        self,
        lines: list[dict[str, Any]],
        carried: list[dict[str, Any]],
        *,
        cut_after: bool,
        final: bool,
        start: float = 0.0,
    ) -> str:
        """Everything spoken in one shot: what carries over into it, then its own lines, each said
        when it was placed (`at`, seconds into the scene) or straight after the one before."""
        parts = [self.carried(line) for line in carried]
        cursor = start
        for line in lines:
            if not line["words"]:
                continue
            begin = max(cursor, line["at"] if line["at"] is not None else cursor)
            lead = "After a pause, " if begin - cursor > PAUSE else ""
            parts.append(self.line(line, cut_after=cut_after, final=final, lead=lead))
            cursor = begin + speech_seconds(line["words"], line["mode"])
        return " ".join(p for p in parts if p)

    def speaking_refs(self, lines: list[dict[str, Any]]) -> set[str]:
        """Reference ids of the voices that speak in these lines."""
        out = set()
        for line in lines:
            if not line["words"]:
                continue
            for vid in line["speakers"]:
                voice = self.voices.get(vid)
                if voice and voice["ref"]:
                    out.add(voice["ref"])
        return out
