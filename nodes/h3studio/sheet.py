"""A render as a contact sheet: frames evenly spaced through the clip in a grid, each marked with its
time (and its shot, when the shots are given), so a whole scene fits in one picture — to look over,
drag into a chat, or hand to an agent. Saved beside the renders under output/h3studio/sheets, one
per clip and layout, and made again only when the clip is newer. Files in, a file out, on the CPU.
"""

from __future__ import annotations

import os
import zlib

from ._media import path_of

#: Frames across, and the most a sheet takes.
COLUMNS = 4
MOST = 48
TILE = 400
GAP = 6
HEAD = 30
INK = (235, 235, 235)
SOFT = (150, 150, 150)
PAPER = (18, 18, 20)


def _font(size: int):
    from PIL import ImageFont

    for name in ("DejaVuSans.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def picks(total: int, count: int) -> list[int]:
    """`count` frame indexes evenly through `total` frames, each in the middle of its stretch."""
    count = max(1, min(count, total))
    return sorted({min(total - 1, int((i + 0.5) * total / count)) for i in range(count)})


def shot_of(frame: int, starts: list[int]) -> int:
    """The 1-based shot a frame falls in, given each shot's first frame (ascending)."""
    return sum(1 for s in starts if s <= frame) or 1


def _frames(path: str, want: list[int]) -> tuple[list, float, int]:
    """The wanted frames that are there, as (index, PIL image), the clip's frame rate and its
    frame count."""
    import av

    got, wanted = {}, set(want)
    with av.open(path) as c:
        stream = c.streams.video[0]
        fps = float(stream.average_rate or 24)
        n = 0
        for n, frame in enumerate(c.decode(video=0), start=1):
            if n - 1 in wanted:
                got[n - 1] = frame.to_image()
    return [(i, got[i]) for i in want if i in got], fps, n


def _count(path: str) -> int:
    import av

    with av.open(path) as c:
        return int(c.streams.video[0].frames) or sum(1 for _ in c.decode(video=0))


def make(
    ref: str,
    count: int = 12,
    columns: int = COLUMNS,
    shots: list[int] | None = None,
    title: str = "",
) -> dict:
    """The contact sheet of clip `ref`: `count` frames in rows of `columns`. `shots` are each shot's
    first frame, to mark which shot every frame is from. Returns {ref, path, frames, seconds}."""
    import folder_paths
    from PIL import Image, ImageDraw

    src = path_of(ref)
    count = max(1, min(int(count), MOST))
    columns = max(1, min(int(columns), count))
    starts = sorted({int(s) for s in shots or [] if int(s) >= 0})
    stem = os.path.splitext(os.path.basename(src))[0]
    # One file per clip and layout: the title and the shots are part of what's drawn.
    marks = zlib.crc32(f"{title}|{starts}".encode())
    tag = f"{count}x{columns}_{marks:08x}"
    folder = os.path.join(folder_paths.get_output_directory(), "h3studio", "sheets")
    out = os.path.join(folder, f"{stem}_sheet_{tag}.png")
    out_ref = f"output/h3studio/sheets/{os.path.basename(out)}"

    total = _count(src)
    want = picks(total, count)
    if os.path.isfile(out) and os.path.getmtime(out) >= os.path.getmtime(src):
        import av

        with av.open(src) as c:
            fps = float(c.streams.video[0].average_rate or 24)
        return _made(out_ref, out, want, fps, total)

    images, fps, total = _frames(src, want)
    if not images:
        raise ValueError(f"H3 Studio: {os.path.basename(src)} has no frames to show.")
    w, h = images[0][1].size
    tw, th = TILE, max(1, round(TILE * h / w))
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new(
        "RGB", (columns * tw + (columns + 1) * GAP, HEAD + rows * th + (rows + 1) * GAP), PAPER
    )
    draw = ImageDraw.Draw(sheet)
    big, small = _font(16), _font(14)
    head = title or os.path.basename(src)
    draw.text((GAP + 2, 7), head, fill=INK, font=big)
    facts = f"{total / fps:.2f} s · {total} frames · {fps:g} fps · {w}x{h}"
    draw.text(
        (sheet.width - GAP - 2 - draw.textlength(facts, font=small), 9),
        facts,
        fill=SOFT,
        font=small,
    )
    for k, (frame, img) in enumerate(images):
        x = GAP + (k % columns) * (tw + GAP)
        y = HEAD + GAP + (k // columns) * (th + GAP)
        sheet.paste(img.convert("RGB").resize((tw, th), Image.LANCZOS), (x, y))
        label = f"{frame / fps:.2f}s"
        if starts:
            label = f"shot {shot_of(frame, starts)} · {label}"
        lw = draw.textlength(label, font=small)
        draw.rectangle((x, y + th - 22, x + lw + 12, y + th), fill=(0, 0, 0))
        draw.text((x + 6, y + th - 20), label, fill=INK, font=small)
    os.makedirs(folder, exist_ok=True)
    sheet.save(out)
    return _made(out_ref, out, [f for f, _ in images], fps, total)


def _made(ref: str, path: str, want: list[int], fps: float, total: int) -> dict:
    """What a sheet reports: its media ref, its file (for agents reading from disk), each frame's
    time and the clip's length."""
    return {
        "ref": ref,
        "path": path,
        "frames": [round(i / fps, 3) for i in want],
        "seconds": round(total / fps, 3),
    }
