"""Intermediate rhythm representation, shared by both sides of the converter."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import yamaha
from .smf import Ev

# Casio rhythm parts, in the order the CT-X mixer shows them.
CASIO_PARTS = ["drum", "perc", "bass", "chord1", "chord2",
               "chord3", "chord4", "chord5"]

# CT-X accomp part -> MIDI channel (0-based).  Verified against the
# CT-X3000/5000 MIDI Implementation, section 1.3.2, part table: parts 09-16
# are Accomp Percussion, Drum, Bass, Chord1..Chord5 on channels 9-16.
# This is the same channel layout Yamaha styles use, so the mapping below is
# a straight channel-for-channel pass-through.
CTX_ACCOMP_CHANNELS = {
    "perc": 8, "drum": 9, "bass": 10, "chord1": 11,
    "chord2": 12, "chord3": 13, "chord4": 14, "chord5": 15,
}

# Layout for the preview MIDI.  "gm" puts both drum parts on channel 10 so a
# normal MIDI player auditions them as drums; "ctx" mirrors the keyboard.
# Note the CT-X accomp parts are transmit-only -- the MIDI Implementation
# lists no receive channel for port A -- so neither layout can drive the
# accompaniment engine from outside.
MIDI_LAYOUTS = {
    "gm": {"drum": 9, "perc": 9, "bass": 0, "chord1": 1, "chord2": 2,
           "chord3": 3, "chord4": 4, "chord5": 5},
    "ctx": CTX_ACCOMP_CHANNELS,
}

# Yamaha style part -> Casio part
PART_MAP = {
    "rhythm_main": "drum",
    "rhythm_sub":  "perc",
    "bass":        "bass",
    "chord1":      "chord1",
    "chord2":      "chord2",
    "pad":         "chord3",
    "phrase1":     "chord4",
    "phrase2":     "chord5",
}

# Yamaha section marker -> Casio rhythm element
ELEMENT_MAP = {
    "Intro A": "Intro1", "Intro B": "Intro2",
    "Intro C": "Intro3", "Intro D": "Intro4",
    "Main A": "Variation1", "Main B": "Variation2",
    "Main C": "Variation3", "Main D": "Variation4",
    "Fill In AA": "Fill1", "Fill In BB": "Fill2",
    "Fill In CC": "Fill3", "Fill In DD": "Fill4",
    "Fill In BA": "Fill1", "Fill In AB": "Fill2",
    "Ending A": "Ending1", "Ending B": "Ending2",
    "Ending C": "Ending3", "Ending D": "Ending4",
}

ELEMENT_ORDER = ["Variation1", "Variation2", "Variation3", "Variation4",
                 "Fill1", "Fill2", "Fill3", "Fill4",
                 "Intro1", "Intro2", "Intro3", "Intro4",
                 "Ending1", "Ending2", "Ending3", "Ending4"]

# CT-X5000 front panel drives 6 elements; the rest are reachable only from
# a rhythm that stores them, so keep this list for the --minimal preset.
CTX_CORE_ELEMENTS = ["Variation1", "Variation2", "Fill1", "Fill2",
                     "Intro1", "Ending1"]


@dataclass
class Note:
    tick: int
    dur: int
    key: int
    vel: int


@dataclass
class Part:
    role: str
    tone: int = 0            # GM program (0-based); drums use kit number
    casio_tone: tuple = None  # (program, bank) once tonemap has chosen one
    casio_name: str = ""      # what Casio calls that tone, for reporting
    msb: int = 0
    lsb: int = 0
    volume: int = 100
    pan: int = 64
    reverb: int = 40
    chorus: int = 0
    notes: list = field(default_factory=list)

    @property
    def is_drum(self):
        return self.role in ("drum", "perc")


@dataclass
class Element:
    name: str
    bars: int
    parts: dict = field(default_factory=dict)   # role -> Part

    @property
    def length_ticks_key(self):
        return self.bars


@dataclass
class Rhythm:
    name: str = "RHYTHM"
    tempo_bpm: float = 120.0
    numerator: int = 4
    denominator: int = 4
    ppqn: int = 96
    elements: dict = field(default_factory=dict)   # name -> Element

    @property
    def ticks_per_bar(self):
        return int(self.ppqn * 4 * self.numerator / self.denominator)


def _pair_notes(events):
    """Turn note_on/note_off pairs into (channel -> [Note])."""
    out, open_notes = {}, {}
    for e in events:
        if e.kind == "note_on":
            open_notes.setdefault((e.ch, e.a), []).append((e.tick, e.b))
        elif e.kind == "note_off":
            stack = open_notes.get((e.ch, e.a))
            if not stack:
                continue
            start, vel = stack.pop(0)
            out.setdefault(e.ch, []).append(
                Note(start, max(1, e.tick - start), e.a, vel))
    # notes never released: give them a short default length
    for (ch, key), stack in open_notes.items():
        for start, vel in stack:
            out.setdefault(ch, []).append(Note(start, 24, key, vel))
    for ch in out:
        out[ch].sort(key=lambda n: (n.tick, n.key))
    return out


_CC_FIELD = {0: "msb", 32: "lsb", 7: "volume", 10: "pan",
             91: "reverb", 93: "chorus"}


def _mixer(setup_evs):
    """channel -> dict of tone/volume/pan/reverb/chorus from a run of events."""
    m = {}
    for e in setup_evs:
        d = m.setdefault(e.ch, {})
        if e.kind == "pc":
            d["tone"] = e.a
        elif e.kind == "cc" and e.a in _CC_FIELD:
            d[_CC_FIELD[e.a]] = e.b
    return m


def mixer_at(style: yamaha.Style, before):
    """Each channel's voice and mix as of a tick, by replaying every change.

    Reading only the SInt block, as this did, is wrong for most styles.  SInt
    is an initialise: Bandari 05's sets all sixteen channels to bank 0/113
    program 0, a grand piano, and the voices the style actually plays are
    sent again at the START OF EACH SECTION -- bass program 33, chord1 51,
    chord3 50, chord5 3 for its Main B, and a different set for Main D.
    Taking SInt alone therefore reported every melodic part in every style as
    a grand piano, and the tone mapping faithfully gave them all one.

    Replaying in order is also what a sequencer does, so a section that does
    not re-send a program keeps the one in force, which is what the style
    means by leaving it out.
    """
    return _mixer([e for e in style.events
                   if e.kind in ("pc", "cc") and e.tick < before])


def from_style(style: yamaha.Style, ppqn=96, elements=None) -> Rhythm:
    """Convert a parsed Yamaha style into the neutral Rhythm IR."""
    import os

    r = Rhythm(name=os.path.splitext(os.path.basename(style.path))[0][:12].upper(),
               tempo_bpm=style.tempo_bpm,
               numerator=style.numerator,
               denominator=style.denominator,
               ppqn=ppqn)

    scale = ppqn / style.division
    notes_by_ch = _pair_notes(style.events)
    tpb = style.ticks_per_bar

    for sec in yamaha.musical_sections(style):
        elem_name = ELEMENT_MAP.get(sec.name)
        if elem_name is None or (elements and elem_name not in elements):
            continue
        bars = max(1, round((sec.end - sec.start) / tpb))
        mix = mixer_at(style, sec.end)
        el = Element(elem_name, bars)
        limit = sec.start + bars * tpb
        for ch, role in yamaha.YAMAHA_CHANNELS.items():
            src = [n for n in notes_by_ch.get(ch, []) if sec.start <= n.tick < limit]
            if not src:
                continue
            p = Part(PART_MAP[role])
            cfg = mix.get(ch, {})
            for k in ("tone", "msb", "lsb", "volume", "pan", "reverb", "chorus"):
                if k in cfg:
                    setattr(p, k, cfg[k])
            for n in src:
                t = round((n.tick - sec.start) * scale)
                d = max(1, round(min(n.dur, limit - n.tick) * scale))
                p.notes.append(Note(t, d, n.key, n.vel))
            el.parts[p.role] = p
        if el.parts:
            r.elements[elem_name] = el
    return r


def to_midi_events(r: Rhythm, element: str, layout="gm"):
    """Render one element back to MIDI events, for auditioning a conversion."""
    el = r.elements[element]
    chan = MIDI_LAYOUTS[layout]
    evs = [Ev(0, "meta", meta=0x51,
              data=int(60_000_000 / r.tempo_bpm).to_bytes(3, "big"))]
    for role, p in el.parts.items():
        ch = chan[role]
        if not p.is_drum:
            evs.append(Ev(0, "pc", ch, p.tone))
        evs.append(Ev(0, "cc", ch, 7, p.volume))
        evs.append(Ev(0, "cc", ch, 10, p.pan))
        for n in p.notes:
            evs.append(Ev(n.tick, "note_on", ch, n.key, n.vel))
            evs.append(Ev(n.tick + n.dur, "note_off", ch, n.key, 0))
    return evs
