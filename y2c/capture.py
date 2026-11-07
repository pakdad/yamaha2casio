"""Learn the Casio drum kit from the keyboard's own MIDI output.

The CT-X3000/5000 MIDI Implementation documents the accomp parts as
transmit-only on channels 9-16 (section 1.3.2), and says Volume/Pan/Reverb/
Chorus/Delay Send are sent "when MIDI setting of Accomp Out is set to ON and
automatic accompaniment is used".  So:

    1. On the keyboard: MIDI setting -> Accomp Out = ON.
    2. Start one of the CT-X's own Middle-East rhythms.
    3. Record its MIDI output to a .mid file.

That capture shows exactly which notes the Casio oriental kits use -- the
ground truth this converter otherwise has to guess at.
"""
from __future__ import annotations

import json
from collections import Counter

from . import drummap, ir
from .smf import iter_chunks, read_track


def read_capture(path):
    """role -> Counter(note) from a recording of the CT-X accomp output."""
    with open(path, "rb") as f:
        data = f.read()
    by_ch = {}
    for tag, _, body in iter_chunks(data):
        if tag != "MTrk":
            continue
        for e in read_track(body):
            if e.kind == "note_on" and e.b > 0:
                by_ch.setdefault(e.ch, Counter())[e.a] += 1
    ch2role = {v: k for k, v in ir.CTX_ACCOMP_CHANNELS.items()}
    return {ch2role[ch]: c for ch, c in by_ch.items() if ch in ch2role}


def drum_notes(capture):
    """Merged drum+percussion histogram from a capture."""
    total = Counter()
    for role in ("drum", "perc"):
        total.update(capture.get(role, Counter()))
    return total


def compare(style_hist: Counter, casio_hist: Counter):
    """Side-by-side, both ranked by how often the note is struck."""
    a = style_hist.most_common()
    b = casio_hist.most_common()
    lines = [f"{'Yamaha style':>22}   |   {'Casio capture':<22}",
             f"{'note':>5} {'count':>6} {'name':<10}|{'note':>5} {'count':>6} {'name':<10}"]
    for i in range(max(len(a), len(b))):
        ln, rn = "", ""
        if i < len(a):
            k, c = a[i]
            ln = f"{k:>5} {c:>6} {drummap.GM_DRUM_NAMES.get(k, ''):<10}"
        if i < len(b):
            k, c = b[i]
            rn = f"{k:>5} {c:>6} {drummap.GM_DRUM_NAMES.get(k, ''):<10}"
        lines.append(f"{ln:<22}|{rn:<22}")
    return "\n".join(lines)


def propose(style_hist: Counter, casio_hist: Counter, name="drafted-from-capture"):
    """Draft a map by pairing both kits' notes in order of how busy they are.

    This is a starting point to audition, not an answer: the loudest Yamaha
    note is usually the loudest Casio note (the doum, then the tak, then the
    shaker), but the tail of the ranking is guesswork.  Notes already shared
    by both kits are mapped to themselves first, and only the leftovers are
    paired by rank.
    """
    shared = set(style_hist) & set(casio_hist)
    notes = {k: k for k in shared}
    left = [k for k, _ in style_hist.most_common() if k not in shared]
    right = [k for k, _ in casio_hist.most_common() if k not in shared]
    for i, k in enumerate(left):
        notes[k] = right[i] if i < len(right) else None
    return {
        "name": name,
        "_comment": [
            "DRAFT. Notes present in both kits map to themselves; the rest are",
            "paired by strike-count rank, which is a guess. Audition and edit.",
        ],
        "notes": {str(k): v for k, v in sorted(notes.items())},
    }


def write_proposal(doc, path):
    with open(path, "w") as f:
        json.dump(doc, f, indent=2)
