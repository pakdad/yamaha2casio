"""Drum-note translation between a Yamaha kit and a Casio CT-X kit.

Yamaha oriental styles use the Arabic/Turkish kits, whose doum/tak/riq/sagat
notes sit outside the GM percussion range and do NOT line up with the CT-X
Middle-East kits.  A map file is therefore a plain JSON dict:

    {"name": "...", "notes": {"36": 36, "62": 63, "27": null}}

  value = int   -> play this note on the Casio kit instead
  value = null  -> drop the note entirely
  key missing   -> handled by the --unmapped policy (keep / drop / report)

The two Casio drum parts can need different targets, because they can hold
different kits: the factory Arabic rhythms put a hand-drum kit (program 52)
on the percussion part and a kick/hat kit on the drum part, and kit 52 has
nothing at all below note 59.  An optional "parts" section overrides the
shared table for one part only:

    {"notes": {...}, "parts": {"perc": {"notes": {"36": 69}}}}

A part's own table wins; anything it does not mention falls back to the
shared "notes", then to the --unmapped policy.
"""
from __future__ import annotations

import collections
import json
import re
from collections import Counter
from dataclasses import dataclass, field

GM_DRUM_NAMES = {
    35: "Ac Bass Drum", 36: "Bass Drum 1", 37: "Side Stick", 38: "Ac Snare",
    39: "Hand Clap", 40: "El Snare", 41: "Low Floor Tom", 42: "Closed HH",
    43: "High Floor Tom", 44: "Pedal HH", 45: "Low Tom", 46: "Open HH",
    47: "Low-Mid Tom", 48: "Hi-Mid Tom", 49: "Crash 1", 50: "High Tom",
    51: "Ride 1", 52: "Chinese Cym", 53: "Ride Bell", 54: "Tambourine",
    55: "Splash", 56: "Cowbell", 57: "Crash 2", 58: "Vibraslap",
    59: "Ride 2", 60: "Hi Bongo", 61: "Low Bongo", 62: "Mute Hi Conga",
    63: "Open Hi Conga", 64: "Low Conga", 65: "High Timbale",
    66: "Low Timbale", 67: "High Agogo", 68: "Low Agogo", 69: "Cabasa",
    70: "Maracas", 71: "Short Whistle", 72: "Long Whistle", 73: "Short Guiro",
    74: "Long Guiro", 75: "Claves", 76: "Hi Wood Block", 77: "Low Wood Block",
    78: "Mute Cuica", 79: "Open Cuica", 80: "Mute Triangle",
    81: "Open Triangle", 82: "Shaker", 83: "Jingle Bell", 84: "Bell Tree",
    85: "Castanets", 86: "Mute Surdo", 87: "Open Surdo",
}


def _table(raw):
    """Parse a note table.  A target is a key, None to drop, or a move.

    A move is {"part": "<role>", "key": N} and sends the note to a different
    Casio part as well as a different key.  That matters because a note's
    part is otherwise decided by which Yamaha sub-track it came from -- an
    accident of how the style was authored -- and then whatever single kit
    sits on that part has to supply the sound whether it has it or not.  With
    two kits loaded, one per part, a note can go to whichever part holds the
    right sound.
    """
    out = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            out[int(k)] = (str(v["part"]), int(v["key"]))
        else:
            out[int(k)] = None if v is None else int(v)
    return out


# What a target note means in a kit that is not GM-mapped.  Only the
# articulations actually established from the factory rhythms are named; the
# rest of kit 52 is real but its role is not pinned down, so it is left blank
# rather than labelled with a GM name it does not have.
KIT_NOTE_NAMES = {
    # Kit 52 is ARABIC SET (appendix tone 792, program 52 / bank 120).  These
    # names are Casio's own, from the Drum Assignment List in the appendix
    # that ships with the keyboard; `tools/drumlist.py` parses it into
    # maps/ctx-drum-assignments.json, which is the authority.  This table is
    # the subset the Persian styles use, inlined so the converter can name a
    # key without loading the JSON.
    #
    # Everything here was previously identified by recording a key sweep and
    # measuring each hit.  That got the three darbuka strokes and the riq
    # right.  It also got two things wrong and missed a third:
    #   - 72/73 were read as generic "open tones"; they are Daf 1 and Daf 2,
    #     the Persian frame drum, the single most idiomatic sound in the kit
    #     for this music and the one we were not using.
    #   - 77/78 were read as "mid tone, quiet" and "metal, very bright";
    #     they are Davul 1 and Davul 2, a Turkish bass drum.  "Very bright
    #     metal" is not a bass drum, so one of those measurements was simply
    #     wrong.
    #   - 88-91 were never probed at all, because the probe swept 59 and
    #     69-80 and stopped.  They are the riq's articulations, and Riq Tek
    #     1/2 are precisely the crisp light strokes the groove needed for its
    #     in-between notes.
    # Keys 81-87 carry no sound in this kit; the list shows them empty.
    52: {
        35: "Standard3 Kick 2",
        36: "Standard3 Kick 1",
        38: "Standard3 Snare 1",
        40: "Standard3 Snare 2",
        42: "Room Closed Hi-Hat",
        44: "Room Pedal Hi-Hat",
        46: "Room Open Hi-Hat",
        59: "Standard3 Ride Cymbal 2",
        67: "High Agogo 3",
        68: "Low Agogo 3",
        69: "Tablah 1",        # darbuka: the doum, 136 Hz as measured
        70: "Tablah 2",        # the brighter slap, 78 ms
        71: "Tablah 3",        # the crisp tak, 60 ms
        72: "Daf 1",           # Persian frame drum, 208 Hz
        73: "Daf 2",           # Persian frame drum, 288 Hz
        74: "Riq 1",           # membrane at 398 Hz plus metal shimmer
        75: "Riq 2",
        76: "Riq 3",
        77: "Davul 1",
        78: "Davul 2",
        79: "Zill 1",          # finger cymbals
        80: "Zill 2",
        88: "Riq Jingle",
        89: "Riq Slap",
        90: "Riq Tek 1",
        91: "Riq Tek 2",
    },
    # Kit 54 is INDIAN SET (appendix tone 791).  Persian music is played on
    # the tombak and the daf, and the keyboard has neither by name -- but the
    # tabla is the closest thing in it to a tombak (a hand-tuned skin drum
    # articulated with the fingers, with a pitched bass stroke and crisp rim
    # strokes) and "Duff" is the same instrument as a daf.  ARABIC SET's
    # darbuka-led palette is Arabic, which is not the same music.
    #
    # Keys 74 and 76 are read straight off the appendix layout: they are two
    # of the rows tools/drumlist.py drops, so the generated JSON is missing
    # them and this table fills the gap.
    54: {
        71: "Tabla Ge",        # pitched bass stroke -- the tombak's "tom"
        72: "Tabla Ka",
        73: "Tabla Te",
        74: "Tabla Na",        # rim stroke -- the tombak's "bak"
        75: "Tabla Tun",
        76: "Dholak Ge",       # barrel-drum bass
        77: "Dholak Ke",
        80: "Dholak Na",
        81: "Dholak Ta 3",
        99: "Duff Close",      # the daf
        100: "Duff Open",
        101: "Duffli Close 1",
        104: "Duffli Open 1",
        106: "Duffli Jingle 1",
        107: "Duffli Jingle 2",
        108: "Dhol L",
        111: "Ghungroo 1",     # bells -- a light shimmer layer
        112: "Ghungroo 2",
        113: "Ghungroo 3",
        116: "Tabla Chi",      # the lightest finger stroke in the kit
    },
}


@dataclass
class DrumMap:
    name: str = "identity"
    notes: dict = field(default_factory=dict)      # int -> int | None
    parts: dict = field(default_factory=dict)      # role -> {int: int | None}
    part_kits: dict = field(default_factory=dict)  # role -> kit program
    unmapped: str = "keep"                         # keep | drop

    def target_name(self, role, key):
        """What the target note is called, in whichever kit the part holds."""
        kit = self.part_kits.get(role)
        if kit in KIT_NOTE_NAMES:
            return KIT_NOTE_NAMES[kit].get(key, "")
        return GM_DRUM_NAMES.get(key, "")

    def table_for(self, role):
        return self.parts.get(role)

    def apply(self, key, role=None):
        own = self.parts.get(role)
        if own is not None and key in own:
            return own[key]
        if key in self.notes:
            return self.notes[key]
        return key if self.unmapped == "keep" else None

    def covers(self, key, role=None):
        own = self.parts.get(role)
        return (own is not None and key in own) or key in self.notes

    @classmethod
    def load(cls, path, unmapped="keep"):
        if path in (None, "", "identity"):
            return cls(unmapped=unmapped)
        with open(path) as f:
            raw = json.load(f)
        parts = {role: _table(cfg.get("notes", {}))
                 for role, cfg in raw.get("parts", {}).items()}
        kits = {role: cfg["kit"] for role, cfg in raw.get("parts", {}).items()
                if "kit" in cfg}
        return cls(raw.get("name", path), _table(raw.get("notes", {})),
                   parts, kits, unmapped)


def histogram(rhythm, role=None):
    """Counter of drum notes used, across every element and drum part."""
    c = Counter()
    for el in rhythm.elements.values():
        for r, p in el.parts.items():
            if p.is_drum and (role is None or r == role):
                c.update(n.key for n in p.notes)
    return c


def drum_roles(rhythm):
    """The drum part roles the rhythm actually uses, in a stable order."""
    seen = {r for el in rhythm.elements.values()
            for r, p in el.parts.items() if p.is_drum}
    return [r for r in ("perc", "drum") if r in seen] + sorted(seen - {"perc", "drum"})


def report(rhythm, dmap: DrumMap):
    lines = []
    for role in drum_roles(rhythm):
        hist = histogram(rhythm, role)
        if not hist:
            continue
        kit = dmap.part_kits.get(role)
        own = f" -- own table, kit {kit}" if kit else (
            " -- own table" if dmap.table_for(role) else "")
        lines.append(f"-- {role}{own} --")
        lines.append(f"{'note':>5} {'count':>6}  {'->':>4}  name / status")
        for key, count in sorted(hist.items()):
            dst = dmap.apply(key, role)
            name = GM_DRUM_NAMES.get(key, "")
            if not dmap.covers(key, role):
                status = f"UNMAPPED ({dmap.unmapped})"
            elif dst is None:
                status = "dropped"
            else:
                status = dmap.target_name(role, dst)
            arrow = "--" if dst is None else str(dst)
            lines.append(f"{key:>5} {count:>6}  {arrow:>4}  {name:<16} {status}")
        lines.append("")
    return "\n".join(lines)


def dedupe(notes, window=0):
    """Collapse hits that share a key and land together, keeping the loudest.

    A map that sends several source articulations to one target key creates
    these, and one drum voice cannot play two hits at the same instant: it
    retriggers, which sounds like a buzz or a choke rather than a rhythm.  A
    Yamaha kit has far more keys than an oriental Casio kit has, so the
    collapse is unavoidable -- but the collisions it produces are not.

    `window` in ticks also merges hits that are merely very close; 0 merges
    only exact ties.  Returns (kept notes, number removed).
    """
    out, removed = [], 0
    last = {}                                   # key -> index in `out`
    for n in sorted(notes, key=lambda x: (x.tick, x.key, -x.vel)):
        prev = last.get(n.key)
        if prev is not None and n.tick - out[prev].tick <= window:
            removed += 1
            if n.vel > out[prev].vel:            # keep the loudest of the pair
                out[prev] = n
            continue
        last[n.key] = len(out)
        out.append(n)
    return out, removed


# How close two drum-sound names are to meaning the same thing.
#
# Token overlap alone is not enough for this music.  "Tablah Tak Finger 2"
# and "Tablah 2" share one word out of four, which scores the same as
# "Tablah 1" and leaves the four tablah articulations indistinguishable.  So
# the instrument is matched first and weighs most, the articulation next, and
# a mismatch of instrument is a veto rather than a low score -- a katem is
# never a Chinese drum however many words two names happen to share.
_INSTRUMENT = {
    "tablah": "tablah", "tabla": "tablah", "darbuka": "tablah",
    "doumbek": "tablah", "katem": "tablah",   # nearest family
    # Persian and South Asian hand drums.  The Yamaha Arabic kits carry real
    # tombak, zarb and neghareh samples -- tombak and zarb are the same
    # Persian goblet drum, the instrument this whole project is chasing --
    # and the CT-X has none of them in any of its 36 kits.  The tablah keys
    # are the nearest thing it has: a hand-tuned skin drum with a pitched
    # bass stroke and crisp rim strokes.  Mapping them there is a
    # substitution, and a far better one than leaving them wherever their
    # note number happened to land.
    "tombak": "tablah", "zarb": "tablah", "tonbak": "tablah",
    "neghareh": "davul", "naghareh": "davul", "daholla": "davul",
    "dohola": "davul", "dhol": "davul", "davul": "davul",
    "dholak": "tablah", "dholki": "tablah", "baya": "tablah",
    "tablabaya": "tablah", "mridangam": "tablah", "kanjira": "daf",
    "chimta": "zill", "chipri": "zill", "chutki": "clap", "daf": "daf", "duff": "daf",
    "duffli": "daf", "riq": "riq", "req": "riq", "zill": "zill",
    "sagat": "zill", "davul": "davul", "dohola": "dohola",
    "bendir": "bendir", "cabasa": "cabasa", "maracas": "maracas",
    "tambourine": "tambourine", "conga": "conga", "bongo": "bongo",
    "timbale": "timbale", "agogo": "agogo", "cowbell": "cowbell",
    "clave": "clave", "claves": "clave", "shaker": "shaker",
    "triangle": "triangle", "kick": "kick", "bd": "kick", "snare": "snare",
    "sd": "snare", "hihat": "hat", "hat": "hat", "tom": "tom",
    "crash": "crash", "ride": "ride", "clap": "clap", "stick": "stick",
    "sticks": "stick", "castanet": "castanet", "castanets": "castanet",
    "surdo": "surdo", "guiro": "guiro", "cuica": "cuica",
    "whistle": "whistle", "woodblock": "woodblock", "block": "woodblock",
    "bell": "bell", "cymbal": "cymbal",
}
_ARTICULATION = {
    "dom": "bass", "doum": "bass", "dum": "bass", "big": "bass",
    "low": "bass", "bass": "bass", "open": "open", "mute": "mute",
    "muted": "mute", "closed": "mute", "close": "mute", "tak": "rim",
    "tik": "rim", "tek": "rim", "ka": "rim", "rim": "rim", "small": "rim",
    "high": "rim", "finger": "finger", "slap": "slap", "tremolo": "roll",
    "roll": "roll", "trill": "roll", "jingle": "jingle",
    # Articulation names used by the Persian and Indian drums above.
    "sak": "rim", "snap": "rim", "back": "rim", "eshareh": "finger",
    "pelang": "rim", "whipping": "roll", "slide": "roll", "ring": "jingle",
    "ge": "bass", "ghe": "bass", "dha": "bass", "ke": "rim", "na": "rim",
    "tun": "open", "head": "open", "edge": "rim",
}
_KITWORD = re.compile(r"\b(standard\d*|room|rock|power|electronic|dance\d*|"
                      r"trance|hip-?hop|jazz|brush|orchestra|latin\d*|arabic|"
                      r"indian|indonesian|chinese|turkish|khaligi|pop|dm\d|"
                      r"ex|gm|set|kit\d*)\b")


def _sound_tokens(name):
    t = name.lower().replace("-", " ").replace("_", " ")
    t = _KITWORD.sub(" ", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    words = [w for w in t.split() if not (w.isdigit() and len(w) <= 2)]
    inst = {_INSTRUMENT[w] for w in words if w in _INSTRUMENT}
    art = {_ARTICULATION[w] for w in words if w in _ARTICULATION}
    rest = {w for w in words
            if w not in _INSTRUMENT and w not in _ARTICULATION}
    return inst, art, rest


def sound_score(a, b):
    """0 when the two names cannot be the same sound; higher is closer."""
    ia, aa, ra = _sound_tokens(a)
    ib, ab, rb = _sound_tokens(b)
    if ia and ib and not (ia & ib):
        return 0.0
    s = 0.0
    if ia & ib:
        s += 3.0
    if aa & ab:
        s += 2.0
    elif aa and ab:
        s -= 0.5
    if ra & rb:
        s += 0.5 * len(ra & rb)
    return max(0.0, s)


# ---------------------------------------------------------------------------
# Mapping by SOUND, using both makers' published kit tables.
#
# A style's drum note means nothing on its own: the meaning comes from the kit
# the style's part declares, and one style can declare a different kit in
# every element.  Mapping note-for-note assumed every part used GM's standard
# kit, so an Arabic percussion part's "Tablah Tak 1" on key 78 became GM's
# Mute Cuica, and "Tablah Tak Finger 2" on 71 became a whistle.
#
# Target keys are deliberately restricted to ranges verified on the
# instrument, not to everything the Casio table lists.  tools/drumlist.py
# mis-assigns columns on some rows -- it has STANDARD SET 1 holding Indian
# tabla below key 27, which no Casio standard kit does -- and an unrestricted
# search picks those phantom rows precisely because their names match an
# Arabic style's note so well.
TRUSTED = {
    # ARABIC SET: measured key by key off the instrument with
    # identify.py (audio2style repo), and every cycle checked.
    52: list(range(69, 81)) + [88, 89, 90, 91],
    # STANDARD SET 1: GM-standard through here, and swept on the instrument.
    0: list(range(35, 82)),
}


# Casio's names do not say which articulation a key is: ARABIC SET offers
# "Tablah 1", "Tablah 2", "Tablah 3" and nothing more, so matching by name
# cannot tell a bass stroke from a rim stroke and every tablah note in a
# style collapses onto one key.  These tags come from measuring the keys on
# the instrument with identify.py in the audio2style repo -- key 69 is the
# doum at 136 Hz with a quarter of its energy below 150 Hz, 70 is the brighter
# slap at 78 ms, 71 the crisp tak at 60 ms -- and they are appended to the
# target's name so the articulation in a Yamaha name has something to match.
ARTICULATION_TAG = {
    (52, 69): "dom bass", (52, 70): "slap", (52, 71): "tak rim",
    (52, 72): "daf open", (52, 73): "daf high rim",
    (52, 74): "roll jingle", (52, 75): "jingle", (52, 76): "jingle roll",
    (52, 77): "dom bass", (52, 78): "tak rim",
    (52, 79): "jingle", (52, 80): "jingle",
    (52, 88): "jingle", (52, 89): "slap",
    (52, 90): "tak rim finger", (52, 91): "tak rim finger",
}


def _sound_targets(perc_kit, drum_kit, casio):
    """[(role, key, name)] that may be mapped onto, restricted to TRUSTED."""
    out = []
    for role, prog in (("perc", perc_kit), ("drum", drum_kit)):
        tbl = {}
        for v in casio.values():
            if v.get("program") == prog:
                tbl = v["notes"]
                break
        for key in TRUSTED.get(prog, range(0, 128)):
            name = tbl.get(str(key))
            if name:
                tag = ARTICULATION_TAG.get((prog, key), "")
                label = name.split("  ")[0]
                out.append((role, key, (label + " " + tag).strip(), label))
    return out


def assign_sounds(wanted, targets, score):
    """Pair each wanted sound with a target, keeping distinct sounds distinct.

    Greedy best-first over every (sound, target) pair.  A plain "best match
    per sound" lookup sends every tablah stroke to the same key -- four
    different articulations arriving as one sound, which is its own kind of
    wrong -- so a target is used once before any is used twice.
    """
    pairs = sorted(((score(w, t[2]), i, j)
                    for i, w in enumerate(wanted)
                    for j, t in enumerate(targets) if score(w, t[2]) > 0),
                   key=lambda z: (-z[0], z[1], z[2]))
    out, used = {}, set()
    for sc, i, j in pairs:
        if wanted[i] in out or j in used:
            continue
        out[wanted[i]] = targets[j]
        used.add(j)
    for sc, i, j in pairs:               # second pass: reuse is allowed now
        if wanted[i] not in out:
            out[wanted[i]] = targets[j]
    # Third pass, by articulation alone.  The instrument veto is right almost
    # always and leaves a residue it is wrong about: "Katem Tak 2" scored zero
    # against every target because no Casio key is named katem, so it had no
    # target at all and would have been dropped.  Dropping a sound the style
    # plays is worse than placing it on a related drum, so anything still
    # unassigned is matched ignoring the instrument.
    missing = [w for w in wanted if w not in out]
    if missing:
        loose = sorted(((_articulation_only(w, t[2]), i, j)
                        for i, w in enumerate(missing)
                        for j, t in enumerate(targets)),
                       key=lambda z: (-z[0], z[1], z[2]))
        for sc, i, j in loose:
            if missing[i] not in out and sc > 0:
                out[missing[i]] = targets[j]
    return out


def _articulation_only(a, b):
    """Score two names on articulation and shared words, ignoring instrument."""
    _, aa, ra = _sound_tokens(a)
    _, ab, rb = _sound_tokens(b)
    s = 2.0 if (aa & ab) else 0.0
    s += 0.5 * len(ra & rb)
    return s


def remap_by_sound(rhythm, perc_kit, drum_kit, ykits, casio, score,
                   window=0, report=None):
    """Map every drum note through its declared kit's sound name.

    Returns (dropped, merged, moved, unresolved kits).
    """
    targets = _sound_targets(perc_kit, drum_kit, casio)
    if not targets:
        raise ValueError("no trusted target sounds for those kits")
    cache, unknown = {}, collections.Counter()

    def table_for(p):
        key = f"{p.msb}/{p.lsb}/{p.tone + 1}"
        kit = ykits.get(key)
        if kit is None:                  # unlisted kit: try the same family
            fam = [k for k in ykits
                   if k.startswith(f"{p.msb}/{p.lsb}/")]
            near = min(fam, key=lambda k: abs(int(k.split("/")[2])
                                              - (p.tone + 1)), default=None)
            unknown[key] += 1
            kit = ykits.get(near) if near else None
        return (kit or {}).get("notes", {}), key

    dropped = merged = moved = 0
    for el in rhythm.elements.values():
        incoming = {}
        for role, p in list(el.parts.items()):
            if not p.is_drum:
                continue
            notes, kitkey = table_for(p)
            if kitkey not in cache:
                wanted = sorted({s for s in notes.values()})
                cache[kitkey] = assign_sounds(wanted, targets, score)
            plan = cache[kitkey]
            kept = []
            for n in p.notes:
                sound = notes.get(str(n.key))
                tgt = plan.get(sound) if sound else None
                if tgt is None:
                    # No target at all: a sound whose name shares neither
                    # instrument nor articulation with anything trusted, or a
                    # note the declared kit does not define.  Keep it where it
                    # is -- that is exactly what happened before any of this
                    # existed, so it cannot be a regression, whereas dropping
                    # silences something the style plays.
                    if report is not None:
                        report.append((kitkey, n.key, sound, n.key, "kept"))
                    kept.append(n)
                    continue
                to_role, to_key, _, to_name = tgt
                if report is not None:
                    report.append((kitkey, n.key, sound, to_key, to_name))
                n.key = to_key
                if to_role == role:
                    kept.append(n)
                elif to_role in el.parts and el.parts[to_role].is_drum:
                    incoming.setdefault(to_role, []).append(n)
                    moved += 1
                else:
                    kept.append(n)
            p.notes = kept
        for role, arr in incoming.items():
            el.parts[role].notes.extend(arr)
        for role, p in el.parts.items():
            if not p.is_drum:
                continue
            p.notes.sort(key=lambda n: (n.tick, n.key))
            p.notes, m = dedupe(p.notes, window)
            merged += m
    return dropped, merged, moved, unknown


def remap(rhythm, dmap: DrumMap, window=0):
    """Apply the map in place.

    Returns (notes dropped, collisions removed, notes moved between parts).
    A target of the form (role, key) moves the note to another drum part, so
    moves are collected first and applied once every part has been read --
    appending to a part while iterating it would re-map the arrivals.
    """
    dropped = merged = moved = 0
    for el in rhythm.elements.values():
        incoming = {}
        for role, p in el.parts.items():
            if not p.is_drum:
                continue
            kept = []
            for n in p.notes:
                dst = dmap.apply(n.key, role)
                if dst is None:
                    dropped += 1
                elif isinstance(dst, tuple):
                    to_role, to_key = dst
                    if to_role == role:
                        n.key = to_key
                        kept.append(n)
                    elif to_role in el.parts and el.parts[to_role].is_drum:
                        n.key = to_key
                        incoming.setdefault(to_role, []).append(n)
                        moved += 1
                    else:
                        # The element has no such part -- sparse intros and
                        # endings often carry only one drum track.  Keep the
                        # note where it is at the mapped key rather than
                        # dropping it: the sound may be absent from this
                        # part's kit, but that is exactly what happened
                        # before any of this routing existed, so it is no
                        # worse.  Dropping cost 64 notes in a single style.
                        n.key = to_key
                        kept.append(n)
                else:
                    n.key = dst
                    kept.append(n)
            p.notes = kept
        for role, arrivals in incoming.items():
            el.parts[role].notes.extend(arrivals)
        for role, p in el.parts.items():
            if not p.is_drum:
                continue
            p.notes.sort(key=lambda n: (n.tick, n.key))
            p.notes, n_merged = dedupe(p.notes, window)
            merged += n_merged
    return dropped, merged, moved
