"""Flatten Yamaha MegaVoice parts into something a normal tone can play.

A MegaVoice stacks a bank of articulations behind one program and selects
between them by velocity and key zone, so in a MegaVoice part the velocity
byte is not a dynamic and the high keys are not pitches.  Yamaha's own tone
generator knows this.  Nothing else does, so the layers arrive as music:

  - Every key from C6 up (MIDI 96, Yamaha counts octaves from C3) is strum
    noise, fret noise or a sound effect.  Played on a pitched tone those come
    out as shrill high notes.  The 46 Iranian styles put 2,109 notes up
    there, 16.9% of all their MegaVoice notes.

  - Velocity above the open zone selects a dead note, a mute, a hammer-on, a
    slide or a pick harmonic.  Another 10% of their MegaVoice notes are in
    one of those bands, and they arrive as ordinary notes struck hard -- so
    the damped strokes, which a guitarist plays to get OUT of the way, come
    out as the loudest thing in the part.  The dynamics are inverted.

So this pass does three things, all of them from the published MegaVoice Map
(tools/megavoice.py) rather than from guesswork: it drops the noise key zone,
drops the layers whose pitch is not the written pitch, and rewrites velocity
so the layer ORDER becomes the dynamic -- which is what the layer order meant
in the first place.

What is dropped is only what cannot be played: a harmonic sounds an octave or
more above the written note, and a fall, scoop, doit, shake or glissando is a
pitch gesture rather than a pitch.  Hammer-ons and slides are kept, because
they do sound at the written pitch; they just arrive without the slur.
"""
from __future__ import annotations

import json
import re
import os

# Layers whose pitch is not the note that is written, so they can only be
# wrong on an instrument that plays the note.
DROP = ("harmonic", "glissando", "fall", "doit", "scoop", "shake",
        "key off", "growl")
# Deliberately damped strokes: real music, but quiet by intent.
DAMPED = ("dead", "mute")
# Strokes that are loud by nature.
LOUD = ("slap", "pop", "thumb")
# Words that make a layer a step on a dynamic ladder rather than a separate
# gesture.  Only these layers are spread across the output range: a hammer-on
# or a slide is not a louder note, and ranking it by its velocity band put it
# at the top of the part, which is the same inversion this pass exists to
# undo.  The corpus shows why it matters -- every guitar MegaVoice in it lays
# out open soft / open med / open hard / dead / mute / hammer / slide /
# harmonics, so four of the eight layers are not dynamics at all.
GRADED = {"soft", "med", "medium", "hard", "p", "mp", "mf", "f", "ff",
          "open", "pp"}

# The dynamic range the layers are spread over.  The top stops short of 127
# so an accent written into the style still has somewhere to go, and the
# bottom stays above the level where the CT-X's own tones thin out.
TONE_LO, TONE_HI = 62, 112
DAMPED_LO, DAMPED_HI = 44, 58
LOUD_VEL = 116
# Pitched gestures that are not graded: played at the middle of the range.
PLAIN_VEL = (TONE_LO + TONE_HI) // 2


def _class(label):
    if any(w in label for w in DROP):
        return "drop"
    if any(w in label for w in LOUD):
        return "loud"
    if any(w in label for w in DAMPED):
        return "damped"
    return "tone"


def _graded(label):
    return bool(GRADED & set(re.split(r"[^a-z0-9]+", label)))


def plan(entry):
    """[(lo, hi, kind, out_lo, out_hi)] for one MegaVoice's velocity layers.

    The graded layers are spread over the musical range in the order the
    table lists them, because that order IS the dynamic the voice was built
    around.  Everything else pitched sits in the middle of that range.
    """
    layers = [(lo, hi, _class(label), _graded(label))
              for lo, hi, label in entry["vel"]]
    ladder = [i for i, l in enumerate(layers) if l[2] == "tone" and l[3]]
    out = []
    for i, (lo, hi, kind, graded) in enumerate(layers):
        if kind == "drop":
            out.append((lo, hi, kind, 0, 0))
        elif kind == "loud":
            out.append((lo, hi, kind, LOUD_VEL, LOUD_VEL))
        elif kind == "damped":
            out.append((lo, hi, kind, DAMPED_LO, DAMPED_HI))
        elif not graded or not ladder:
            out.append((lo, hi, kind, PLAIN_VEL - 6, PLAIN_VEL + 6))
        else:
            n = len(ladder)
            j = ladder.index(i)
            span = (TONE_HI - TONE_LO) / n
            out.append((lo, hi, kind,
                        int(TONE_LO + span * j),
                        int(TONE_LO + span * (j + 1)) - 1))
    return out


class MegaTable:
    def __init__(self, raw: dict):
        self.raw = raw
        self._plans = {}
        self.by_program = {}
        for key, entry in raw.items():
            msb, lsb, prog = (int(x) for x in key.split("/"))
            self.by_program.setdefault((msb, int(prog)), key)

    def lookup(self, msb, lsb, program):
        """The MegaVoice entry for a part, or None.

        A style authored on another model can name an LSB this table does not
        carry, so a voice with the same MSB and program is accepted as a
        stand-in: the articulation LAYOUT is shared across a program's
        variations even where the samples differ, and the layout is all this
        pass uses.
        """
        key = f"{msb}/{lsb}/{program}"
        if key in self.raw:
            return self.raw[key]
        alt = self.by_program.get((msb, program))
        return self.raw[alt] if alt else None

    def plan_for(self, msb, lsb, program):
        entry = self.lookup(msb, lsb, program)
        if entry is None:
            return None, None
        key = id(entry)
        if key not in self._plans:
            self._plans[key] = plan(entry)
        return entry, self._plans[key]


def load(root=None):
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "maps", "yamaha-megavoice.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return MegaTable(json.load(f))


def flatten(rhythm, table: MegaTable, report=None):
    """Rewrite every MegaVoice part in place.  Returns a counts dict."""
    n = {"parts": 0, "noise": 0, "articulation": 0, "revelocity": 0,
         "unknown": 0}
    for el in rhythm.elements.values():
        for role, part in el.parts.items():
            if part.is_drum or part.msb != 8:
                continue
            entry, layers = table.plan_for(part.msb, part.lsb, part.tone)
            if entry is None:
                n["unknown"] += 1
                continue
            n["parts"] += 1
            noise_from = entry.get("noise_from", 96)
            kept = []
            for note in part.notes:
                if note.key >= noise_from:
                    n["noise"] += 1
                    continue
                band = next((b for b in layers
                             if b[0] <= note.vel <= b[1]), None)
                if band is None:
                    kept.append(note)
                    continue
                lo, hi, kind, olo, ohi = band
                if kind == "drop":
                    n["articulation"] += 1
                    continue
                # Keep the note's position inside its own layer, so a style
                # that writes two velocities in one band still has two.
                frac = (note.vel - lo) / max(1, hi - lo)
                note.vel = max(1, min(127, int(olo + frac * (ohi - olo))))
                n["revelocity"] += 1
                kept.append(note)
            part.notes = kept
            if report is not None:
                report.append((el_name(rhythm, el), role, entry["name"],
                               len(part.notes)))
    return n


def el_name(rhythm, el):
    for name, e in rhythm.elements.items():
        if e is el:
            return name
    return "?"
