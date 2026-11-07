"""Pipeline glue: Yamaha style -> IR -> (drum map, chord fix) -> outputs."""
from __future__ import annotations

import json
import os

from . import ac7, drummap, ir, mega, tonemap, yamaha
from .smf import write_smf

# Time signatures a CT-X rhythm slot is happy with.
CTX_METERS = {(2, 4), (3, 4), (4, 4), (6, 8), (2, 2), (3, 8), (5, 4),
              (6, 4), (9, 8), (12, 8)}

# Yamaha records chord parts against a source chord (usually CMaj7).  Casio
# rhythms expect a plain C major source, so the 7th has to go somewhere.
CHORD_FIX = {
    "none": {},
    "maj7-to-maj": {11: 12},     # B (maj7) -> C an octave up
    "maj7-drop": {11: None},     # B (maj7) -> removed
}


def apply_chord_fix(rhythm: ir.Rhythm, mode="maj7-to-maj"):
    table = CHORD_FIX.get(mode, {})
    if not table:
        return 0
    changed = 0
    for el in rhythm.elements.values():
        for role, p in el.parts.items():
            if p.is_drum or role == "bass":
                continue
            kept = []
            for n in p.notes:
                dst = table.get(n.key % 12, "keep")
                if dst == "keep":
                    kept.append(n)
                elif dst is None:
                    changed += 1
                else:
                    n.key = min(127, n.key - (n.key % 12) + dst)
                    kept.append(n)
                    changed += 1
            p.notes = kept
    return changed


# What the CT-X5000's own rhythm editor will accept per element, from the
# user's guide (EN-77): an intro or ending of 1 to 16 bars, a variation of 1
# to 16, and a fill-in of 1 or 2.  A Yamaha style can hold sections longer
# than that, and one in this corpus appears to -- Bandari 07's Fill In AA
# measures 162 bars, almost certainly because the marker that should end it
# is missing and the section ran on to the end of the file.
ELEMENT_BARS = {"Fill": (1, 2), "Intro": (1, 16), "Ending": (1, 16),
                "Variation": (1, 16)}


def clamp_elements(rhythm: ir.Rhythm):
    """Cut any element back to the length its slot allows.

    Returns [(element, was, now)].  Notes past the new end go, because an
    element that claims more bars than the instrument will hold is not
    something the keyboard can be relied on to interpret.
    """
    out = []
    tpb = ac7.ticks_per_bar(rhythm.numerator, rhythm.denominator)
    for name, el in rhythm.elements.items():
        kind = next((k for k in ELEMENT_BARS if name.startswith(k)), None)
        if kind is None:
            continue
        lo, hi = ELEMENT_BARS[kind]
        want = max(lo, min(hi, el.bars))
        if want == el.bars:
            continue
        out.append((name, el.bars, want))
        el.bars = want
        for part in el.parts.values():
            part.notes = [n for n in part.notes if n.tick < want * tpb]
    return out


# Reverb and chorus per part, measured across 37 working CT-X rhythms, which
# agree on them exactly -- every one of the 37 carries these same numbers, so
# they are a convention rather than an average.
#
# They are applied instead of the template's own, because a template passes
# on a balance mixed for ITS arrangement.  The most complete donor found
# while working on this -- the only factory rhythm to hand with all seven
# parts in all ten used elements, so that nothing has to be dropped for want
# of a track -- is a waltz, and it carries reverb 127 on its percussion and
# 90 on two chord parts.  That suits a waltz with strings and drowns a
# hand-drum groove.
#
# The style's own reverb is deliberately NOT used: the two makers do not
# scale their sends alike, so the number means a different amount of room.
# Volume and pan DO come from the style, because those are a balance between
# its own parts and that balance carries over.
MIX_DEFAULTS = {
    "perc":   {"volume": 112, "pan": 64, "reverb": 24, "chorus": 0},
    "drum":   {"volume": 112, "pan": 64, "reverb": 24, "chorus": 0},
    "bass":   {"volume": 112, "pan": 64, "reverb": 10, "chorus": 0},
    "chord1": {"volume": 106, "pan": 64, "reverb": 30, "chorus": 0},
    "chord2": {"volume": 100, "pan": 64, "reverb": 40, "chorus": 0},
    "chord3": {"volume": 100, "pan": 64, "reverb": 40, "chorus": 0},
    "chord4": {"volume": 100, "pan": 64, "reverb": 40, "chorus": 0},
    "chord5": {"volume": 100, "pan": 64, "reverb": 40, "chorus": 0},
}

# The chord parts, nearest-first from the top, for re-homing a part the
# template has no track for.
CHORD_SLOTS = ("chord4", "chord3", "chord2", "chord1")


def fold_to_free_parts(rhythm: ir.Rhythm, available):
    """Re-home parts the template has no track for.  Returns [(el, from, to)].

    The CT-X5000's editor lists five chord parts and MIXR carries eight rows
    per element, so Chord 5 exists -- but no factory rhythm puts a stream on
    it, and a rhythm can only be built on a factory container, so there is no
    track to write Chord 5 into.  Dropping it cost real music: Bandari 05
    alone writes 464 notes there.

    A part with nowhere to go is therefore moved to the highest chord slot
    the element leaves empty, carrying its own voice with it -- which works
    because the tone is now set per part from the style instead of inherited
    from the template, so the slot's name no longer decides its sound.
    """
    moves = []
    for name, el in rhythm.elements.items():
        for role in [r for r in el.parts if r not in available]:
            part = el.parts[role]
            if not part.notes:
                del el.parts[role]
                continue
            free = next((c for c in CHORD_SLOTS
                         if c in available and c not in el.parts), None)
            if free is None:
                continue
            part.role = free
            el.parts[free] = part
            del el.parts[role]
            moves.append((name, role, free, len(part.notes)))
    return moves


def map_tones(rhythm: ir.Rhythm, tones: tonemap.ToneMap):
    """Decide a Casio tone for every melodic part.  Returns [(role, ...)]."""
    out, seen = [], {}
    for el in rhythm.elements.values():
        for role, part in el.parts.items():
            if part.is_drum:
                continue
            key = (role, part.msb, part.lsb, part.tone)
            if key not in seen:
                seen[key] = tones.choose(part.msb, part.lsb, part.tone, role)
            got = seen[key]
            if got is None:
                continue
            part.casio_tone = (got[0], got[1])
            part.casio_name = got[2]
            out.append((role, got))
    return out


def transpose(rhythm: ir.Rhythm, semitones):
    if not semitones:
        return
    for el in rhythm.elements.values():
        for p in el.parts.values():
            if p.is_drum:
                continue
            for n in p.notes:
                n.key = max(0, min(127, n.key + semitones))


def load(path, ppqn=96, elements=None):
    style = yamaha.parse(path)
    return style, ir.from_style(style, ppqn=ppqn, elements=elements)


def describe(style: yamaha.Style, rhythm: ir.Rhythm):
    L = [f"file      : {style.path}",
         f"format    : {style.sff_version or 'SFF?'}  division={style.division} ppqn",
         f"tempo     : {style.tempo_bpm} bpm",
         f"meter     : {style.numerator}/{style.denominator}"
         + ("" if (style.numerator, style.denominator) in CTX_METERS
            else "   <-- WARNING: CT-X may not accept this meter"),
         f"ctabs     : {len(style.ctabs)} chord tables in CASM",
         "",
         f"{'Yamaha section':<16} {'Casio element':<12} {'bars':>4}  parts"]
    for sec in yamaha.musical_sections(style):
        el_name = ir.ELEMENT_MAP.get(sec.name)
        if el_name is None:
            L.append(f"{sec.name:<16} {'(skipped)':<12}")
            continue
        el = rhythm.elements.get(el_name)
        if el is None:
            L.append(f"{sec.name:<16} {el_name:<12} {'-':>4}  (empty)")
            continue
        parts = ", ".join(f"{r}:{len(p.notes)}" for r, p in el.parts.items())
        L.append(f"{sec.name:<16} {el_name:<12} {el.bars:>4}  {parts}")
    return "\n".join(L)


def to_json(rhythm: ir.Rhythm):
    return json.dumps({
        "name": rhythm.name, "tempo": rhythm.tempo_bpm, "ppqn": rhythm.ppqn,
        "meter": [rhythm.numerator, rhythm.denominator],
        "elements": {
            name: {"bars": el.bars, "parts": {
                role: {"tone": p.tone, "msb": p.msb, "lsb": p.lsb,
                       "volume": p.volume, "pan": p.pan,
                       "notes": [[n.tick, n.dur, n.key, n.vel] for n in p.notes]}
                for role, p in el.parts.items()}}
            for name, el in rhythm.elements.items()},
    }, indent=1)


def write_preview_midi(rhythm: ir.Rhythm, path, layout="gm"):
    """One MIDI file, elements laid out back to back, for auditioning."""
    from .smf import Ev
    evs, offset = [], 0
    for name in ir.ELEMENT_ORDER:
        el = rhythm.elements.get(name)
        if el is None:
            continue
        evs.append(Ev(offset, "meta", meta=0x06, data=name.encode()))
        for e in ir.to_midi_events(rhythm, name, layout):
            if e.tick == 0 and e.kind == "meta" and offset:
                continue
            e.tick += offset
            evs.append(e)
        offset += el.bars * rhythm.ticks_per_bar
    write_smf(path, rhythm.ppqn, [evs])
    return offset
