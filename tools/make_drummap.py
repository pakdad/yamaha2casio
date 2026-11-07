"""Build a drum map that pairs two Casio kits and routes notes by SOUND.

    python3 tools/make_drummap.py --perc 0 --drum 26 -o maps/twokit.json
    python3 tools/make_drummap.py --perc 0 --drum 26 --report

Why this exists.  The converter decides a note's Casio part from which Yamaha
sub-track it came from -- RhythmMain becomes the drum part, RhythmSub the
percussion part -- and then whatever single kit sits on that part has to
supply the sound whether it has it or not.  Nothing checks.  Two measurements
off the 46 Iranian styles say why that goes wrong:

  - Over their 76,608 drum events, the best single kit covers 94.4% of the
    keys used.  The best PAIR of kits, with notes free to go to whichever
    part holds them, covers 99.3%.  So two kits is worth about 5 points.

  - More important: 29% of those events are on keys OUTSIDE the GM
    percussion range of 35-81.  Inside that range Yamaha and Casio agree,
    because GM fixes it, and mapping a note to itself is right.  Outside it
    there is no shared convention at all, so note-for-note mapping is a
    guess -- and the guesses are bad.  Key 30 is the third busiest key in the
    whole corpus with 2,785 events; mapped to itself it lands on a record
    scratch.  Keys 17-23 carry 3,459 events between them and land on nothing.

So the fix is two parts, not one: pair two kits so the sounds exist, and
choose the target key by what the sound IS rather than by its number.  This
matches Yamaha's name for each note against Casio's name for each key -- the
published Drum Assignment List, via maps/ctx-drum-assignments.json -- and
emits a map with per-part tables, including moves between parts.

A note keeps its own key and part when that is as good a match as any, so
the GM-aligned middle of the range is left alone and the map only disturbs
what it improves.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# What Yamaha means by each drum note.  35-81 is General MIDI, which both
# makers follow.  13-34 and 82-87 are Yamaha's own extension (the XG layout),
# which Casio does not share -- that mismatch is what this map is for.
YAMAHA = {
    13: "Surdo Mute", 14: "Surdo Open", 15: "Hi Q", 16: "Whip Slap",
    17: "Scratch High", 18: "Scratch Low", 19: "Finger Snap",
    20: "Click Noise", 21: "Metronome Click", 22: "Metronome Bell",
    23: "Seq Click Low", 24: "Seq Click High", 25: "Brush Tap",
    26: "Brush Swirl", 27: "Brush Slap", 28: "Brush Tap Swirl",
    29: "Snare Roll", 30: "Castanet", 31: "Snare Soft", 32: "Sticks",
    33: "Kick Soft", 34: "Open Rim Shot",
    35: "Kick 2", 36: "Kick 1", 37: "Side Stick", 38: "Snare 1",
    39: "Hand Clap", 40: "Snare 2", 41: "Low Floor Tom",
    42: "Closed Hi-Hat", 43: "High Floor Tom", 44: "Pedal Hi-Hat",
    45: "Low Tom", 46: "Open Hi-Hat", 47: "Low Mid Tom", 48: "High Mid Tom",
    49: "Crash Cymbal 1", 50: "High Tom", 51: "Ride Cymbal 1",
    52: "Chinese Cymbal", 53: "Ride Bell", 54: "Tambourine",
    55: "Splash Cymbal", 56: "Cowbell", 57: "Crash Cymbal 2",
    58: "Vibraslap", 59: "Ride Cymbal 2", 60: "High Bongo", 61: "Low Bongo",
    62: "Mute High Conga", 63: "Open High Conga", 64: "Low Conga",
    65: "High Timbale", 66: "Low Timbale", 67: "High Agogo",
    68: "Low Agogo", 69: "Cabasa", 70: "Maracas", 71: "Short Whistle",
    72: "Long Whistle", 73: "Short Guiro", 74: "Long Guiro", 75: "Claves",
    76: "High Wood Block", 77: "Low Wood Block", 78: "Mute Cuica",
    79: "Open Cuica", 80: "Mute Triangle", 81: "Open Triangle",
    82: "Shaker", 83: "Jingle Bell", 84: "Bell Tree", 85: "Castanets",
    86: "Mute Surdo", 87: "Open Surdo",
}

# Kit-name prefixes and serial numbers carry no sound information: Casio
# writes "Standard1 Closed Hi-Hat" and "Room Closed Hi-Hat" for the same
# articulation in different kits, and "Cabasa 1" for GM's "Cabasa".
NOISE = re.compile(r"\b(standard\d*|room|rock|power|electronic|dance\d*|"
                   r"trance|hip-?hop|jazz|brush|orchestra|latin\d*|arabic|"
                   r"indian|indonesian|chinese|dm\d|ex|gm|set|kit)\b")
SYNONYM = {
    "bd": "kick", "bassdrum": "kick", "sd": "snare", "hh": "hihat",
    "hihat": "hat", "hi": "high", "lo": "low", "cym": "cymbal",
    "rimshot": "rim", "handclap": "clap", "claps": "clap",
    "castanets": "castanet", "sticks": "stick", "claves": "clave",
}


# Sounds Casio has no equivalent for at all, and the nearest thing that it
# does have.  Brushed snare articulations are the real gap: no kit names a
# brush anything, and between them Brush Tap and Brush Swirl carry 1,168 of
# the corpus's events (1.52%), which is too many to silence.  A brushed snare
# is a soft snare, so that is where they go.
EQUIVALENT = {
    "Brush Tap": "Snare 1",
    "Brush Swirl": "Snare 1",
    "Brush Tap Swirl": "Snare 1",
    "Brush Slap": "Snare 2",
    "Finger Snap": "Hand Clap",
    "Click Noise": "Sticks",
    "Seq Click Low": "Sticks",
    "Seq Click High": "Sticks",
}


def tokens(name):
    t = name.lower().replace("-", " ").replace("_", " ")
    t = NOISE.sub(" ", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    out = []
    for w in t.split():
        if w.isdigit() and len(w) <= 2:
            continue                      # a serial number, not a sound
        out.append(SYNONYM.get(w, w))
    return set(out)


def score(a, b):
    """How well two drum-sound names agree, 0..1."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    if not inter:
        return 0.0
    return inter / len(ta | tb)


def kit_notes(kits, program):
    for v in kits.values():
        if v.get("program") == program:
            return {int(n): s for n, s in v["notes"].items()}, v["name"]
    raise SystemExit(f"no kit with program {program}")


def build(perc_prog, drum_prog, path="maps/ctx-drum-assignments.json"):
    kits = json.load(open(path))
    pnotes, pname = kit_notes(kits, perc_prog)
    dnotes, dname = kit_notes(kits, drum_prog)
    avail = {"perc": pnotes, "drum": dnotes}
    out, report = {"perc": {}, "drum": {}}, []
    for note, want in sorted(YAMAHA.items()):
        best = []
        # Try the sound's own name first; if nothing in either kit matches it,
        # try the nearest equivalent before giving up on it.
        for candidate in (want, EQUIVALENT.get(want)):
            if candidate is None or best:
                continue
            for role, table in avail.items():
                for key, got in table.items():
                    s = score(candidate, got)
                    if s <= 0:
                        continue
                    # Prefer staying put: same key scores a nudge, and so
                    # does staying on the part the note already belongs to.
                    best.append((s + (0.05 if key == note else 0.0),
                                 s, role, key, got))
        for src in ("perc", "drum"):
            if not best:
                # No kit names this sound.  Fall back to what the converter
                # did before -- the note's own key -- so the map is never
                # worse than no map at all.  Dropping instead looked tidy and
                # was not: key 30 is the third busiest key in the corpus with
                # 2,785 events, and no kit calls anything a castanet, so a
                # drop-on-no-match map silenced it outright.
                if note in avail[src]:
                    report.append((note, want, src, src, avail[src][note], 0.0))
                else:
                    other = "drum" if src == "perc" else "perc"
                    if note in avail[other]:
                        out[src][str(note)] = {"part": other, "key": note}
                        report.append((note, want, src, other,
                                       avail[other][note], 0.0))
                    else:
                        out[src][str(note)] = None
                        report.append((note, want, src, None, None, 0.0))
                continue
            tie = max(b[0] for b in best)
            cands = [b for b in best if b[0] >= tie - 1e-9]
            cands.sort(key=lambda b: (b[2] != src, abs(b[3] - note)))
            _, s, role, key, got = cands[0]
            if role == src and key == note:
                pass                      # identity: leave it out of the map
            elif role == src:
                out[src][str(note)] = key
            else:
                out[src][str(note)] = {"part": role, "key": key}
            report.append((note, want, src, role, got, s))
    return out, report, (pname, pnotes), (dname, dnotes)


def main():
    p = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--perc", type=int, default=0, help="kit program for perc")
    p.add_argument("--drum", type=int, default=26, help="kit program for drum")
    p.add_argument("-o", "--out")
    p.add_argument("--report", action="store_true")
    a = p.parse_args()

    out, report, (pname, _), (dname, _) = build(a.perc, a.drum)
    if a.report:
        print(f"perc part: {pname} (program {a.perc})")
        print(f"drum part: {dname} (program {a.drum})\n")
        print("note  Yamaha sound        src   -> part   Casio sound            fit")
        for note, want, src, role, got, s in report:
            if src != "drum":
                continue
            tgt = f"{role}" if role else "DROP"
            print(f" {note:3d}  {want:<19} {src:<5} -> {tgt:<6} "
                  f"{(got or ''):<22} {s:.2f}")
    if a.out:
        doc = {
            "name": f"twokit-{a.perc}-{a.drum}",
            "_comment": [
                f"Generated by tools/make_drummap.py from the published Drum",
                f"Assignment List.  perc part = {pname} (program {a.perc}),",
                f"drum part = {dname} (program {a.drum}).",
                "",
                "Each Yamaha note is sent to whichever of the two kits names",
                "the closest sound, moving it between parts when that is",
                "where the sound lives.  Notes whose own key is already the",
                "best match are absent from the table and pass through.",
                "",
                "Convert with BOTH kits set, or the map points at sounds that",
                "are not loaded:",
                f"  --tone perc={a.perc}/120 --tone drum={a.drum}/120",
            ],
            "notes": {},
            "parts": {
                "perc": {"kit": a.perc, "notes": out["perc"]},
                "drum": {"kit": a.drum, "notes": out["drum"]},
            },
        }
        with open(a.out, "w") as f:
            json.dump(doc, f, indent=1, sort_keys=False)
        moved = sum(1 for t in out["perc"].values() if isinstance(t, dict)) \
            + sum(1 for t in out["drum"].values() if isinstance(t, dict))
        print(f"wrote {a.out}: {len(out['perc'])} perc entries, "
              f"{len(out['drum'])} drum entries, {moved} cross-part moves")


if __name__ == "__main__":
    main()
