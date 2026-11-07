"""y2c -- Yamaha style  ->  Casio CT-X5000 rhythm converter.

  y2c.py info     style.sty                    what's inside a Yamaha style
  y2c.py report   style.sty --map maps/persian.json    drum notes used
  y2c.py midi     style.sty -o preview.mid     audition the conversion
  y2c.py convert  style.sty -o OUT.AC7 --template REAL.AC7
  y2c.py kitdiff  style.sty capture.mid -o maps/draft.json
  y2c.py ac7info  REAL.AC7                     decode a Casio rhythm
  y2c.py ac7midi  REAL.AC7 -o out.mid          export a Casio rhythm to MIDI
  y2c.py ac7check REAL.AC7                     verify the format model
  y2c.py ac7diff  A.AC7 B.AC7                  find the field that differs
"""
from __future__ import annotations

import argparse
import os
import sys

from y2c import ac7, capture, convert, drummap, ir, mega, tonemap
from y2c.smf import write_smf


def root():
    """The project directory -- one above this package, maps/ and samples/.

    This module used to be y2c.py at the top level, where the project root
    was simply its own directory.  It is a package module now, so the root is
    a level up; getting that wrong points the drum maps at y2c/maps and the
    by-sound mapping silently loses its tables.
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(a):
    elements = set(ir.CTX_CORE_ELEMENTS) if getattr(a, "core_only", False) else None
    style, rhythm = convert.load(a.style, ppqn=a.ppqn, elements=elements)
    return style, rhythm


def _sound_kits(spec):
    """"by-sound[:PERC/DRUM]" -> (perc kit, drum kit)."""
    body = spec.split(":", 1)[1] if ":" in spec else "52/0"
    perc, _, drum = body.partition("/")
    return int(perc), int(drum or 0)


def _passes(a, rhythm):
    """The style-side fixes that do not depend on which drum map is used."""
    if not getattr(a, "no_mega", False):
        table = mega.load()
        if table is not None:
            n = mega.flatten(rhythm, table)
            if n["parts"]:
                print(f"megavoice     : {n['parts']} parts flattened; "
                      f"{n['noise']} noise-zone notes and "
                      f"{n['articulation']} unplayable articulations dropped, "
                      f"{n['revelocity']} velocities rescaled")
            if n["unknown"]:
                print(f"megavoice     : {n['unknown']} parts declare a "
                      f"MegaVoice the table does not list; left alone")
    if not getattr(a, "no_clamp", False):
        cut = convert.clamp_elements(rhythm)
        for name, was, now in cut:
            print(f"element length: {name} {was} bars -> {now}, the longest "
                  f"a {name.rstrip('12345')} slot accepts")


def _kit_name(program):
    """What Casio calls the drum kit at this program, for the log."""
    tm = tonemap.load()
    if tm is None:
        return f"kit {program}"
    for t in tm.tones.values():
        if t["bank"] == ac7.DRUM_BANK and t["program"] == program:
            return t["name"]
    return f"kit {program}"


def _loudest_parts(rhythm):
    """One representative part per role, the one with the most notes.

    A role's volume and pan are a single MIXR column per element, while the
    style may declare them separately in every section.  Taking the busiest
    part's settings picks the section that does the most playing, rather than
    whichever happened to be read last.
    """
    best = {}
    for el in rhythm.elements.values():
        for role, part in el.parts.items():
            if part.is_drum:
                continue
            cur = best.get(role)
            if cur is None or len(part.notes) > len(cur.notes):
                best[role] = part
    return best


def _tones(a, rhythm):
    """Pick a CT-X tone per melodic part.  Returns the chosen rows."""
    if getattr(a, "no_tones", False):
        return []
    tm = tonemap.load()
    if tm is None:
        print("tones         : maps/ctx-tones.json or maps/yamaha-voices.json "
              "missing, so the template's tones are kept")
        return []
    return convert.map_tones(rhythm, tm)


class Missing(SystemExit):
    """A table or file the user has to supply is not there.

    Raised instead of letting an open() fail, because the fix is never
    obvious from a traceback: these tables are generated from Casio's and
    Yamaha's own manuals and are deliberately not in the repository, so a
    fresh clone genuinely does not have them and the message has to say so
    and give the command.
    """


def _table(name, what):
    """Load a generated table, or explain how to generate it."""
    import json as _json
    path = os.path.join(root(), "maps", name)
    if not os.path.exists(path):
        raise Missing(
            f"maps/{name} is not there.\n"
            f"It is generated from {what}, which is the instrument maker's\n"
            f"content and so is not distributed with this tool. "
            f"docs/README.md has\nthe one command that builds it.\n\n"
            f"Without it, use a hand-written drum map instead, for example\n"
            f"  --map maps/persian.json")
    with open(path, encoding="utf-8") as f:
        return _json.load(f)


def _prepare(a, rhythm):
    _passes(a, rhythm)
    if a.map and a.map.startswith("by-sound"):
        perc_kit, drum_kit = _sound_kits(a.map)
        ykits = _table("yamaha-drum-kits.json", "a Yamaha PSR Data List")
        casio = _table("ctx-drum-assignments.json",
                       "Casio's tone/rhythm list appendix")
        dropped, merged, moved, unknown = drummap.remap_by_sound(
            rhythm, perc_kit, drum_kit, ykits, casio, drummap.sound_score,
            a.merge_window)
        fixed = convert.apply_chord_fix(rhythm, a.chord_fix)
        convert.transpose(rhythm, a.transpose)
        if a.name:
            rhythm.name = a.name[:12].upper()
        class _M:
            name = f"by-sound perc={perc_kit} drum={drum_kit}"
        if unknown:
            top = ", ".join(f"{k} x{v}" for k, v in unknown.most_common(3))
            print(f"kits          : {len(unknown)} declared kits not in the "
                  f"Yamaha table, nearest in the same bank used ({top})")
        return _M(), dropped, fixed, merged, moved
    dmap = drummap.DrumMap.load(a.map, unmapped=a.unmapped)
    dropped, merged, moved = drummap.remap(rhythm, dmap, a.merge_window)
    fixed = convert.apply_chord_fix(rhythm, a.chord_fix)
    convert.transpose(rhythm, a.transpose)
    if a.name:
        rhythm.name = a.name[:12].upper()
    return dmap, dropped, fixed, merged, moved


def cmd_info(a):
    style, rhythm = _load(a)
    print(convert.describe(style, rhythm))


def cmd_report(a):
    style, rhythm = _load(a)
    dmap = drummap.DrumMap.load(a.map, unmapped=a.unmapped)
    print(convert.describe(style, rhythm))
    print("\n-- drum notes used --")
    print(drummap.report(rhythm, dmap))


def cmd_midi(a):
    style, rhythm = _load(a)
    _prepare(a, rhythm)
    ticks = convert.write_preview_midi(rhythm, a.out, a.midi_layout)
    print(f"wrote {a.out}  ({ticks} ticks, {len(rhythm.elements)} elements)")


def cmd_convert(a):
    style, rhythm = _load(a)
    dmap, dropped, fixed, merged, moved = _prepare(a, rhythm)
    print(convert.describe(style, rhythm))
    print(f"\ndrum map  : {dmap.name} ({dropped} notes dropped, "
          f"{merged} same-key collisions merged"
          + (f", {moved} moved between drum parts)" if moved else ")"))
    print(f"chord fix : {a.chord_fix} ({fixed} notes touched)")

    base = os.path.splitext(a.out)[0]
    convert.write_preview_midi(rhythm, base + ".mid", a.midi_layout)
    print(f"preview   : {base}.mid")

    if not a.template:
        print("\nNo --template given, so no .AC7 was written. Pass a rhythm "
              "exported from your CT-X5000 to use as the container.")
        return 2

    if not os.path.exists(a.template):
        print(f"\nNo such template: {a.template}\n"
              "The container has to be a rhythm exported from a CT-X -- "
              "factory\nrhythms are the instrument maker's content, so none "
              "ship with this\ntool. Save a user rhythm to USB from your own "
              "keyboard and point\n--template at it. See samples/README.md.")
        return 2
    with open(a.template, "rb") as f:
        tpl = ac7.parse(f.read())
    # Measure before converting: apply_rhythm rewrites the streams at the
    # style's bar length, which would make the check below always agree.
    tpl_tpb = tpl.measured_ticks_per_bar()
    have = {t.role for el in tpl.elements for t in el.tracks} - {"control"}
    folded = convert.fold_to_free_parts(rhythm, have)
    if folded:
        total = sum(n for _, _, _, n in folded)
        where = sorted({f"{src}->{dst}" for _, src, dst, _ in folded})
        print(f"part folding  : {', '.join(where)} in {len(folded)} elements, "
              f"{total} notes kept that had no track in the template")
    rep = ac7.apply_rhythm(tpl, rhythm, clear_unused=a.clear_unused)
    ac7.set_name(tpl, rhythm.name)

    # Point every melodic part at the tone the STYLE asks for.  Without this
    # the part plays whatever the template holds, because apply_rhythm keeps
    # MIXR verbatim -- so a style's santur line came out as the donor
    # rhythm's organ, and that is most of why a conversion with every note in
    # the right place still did not sound like the original.
    # MIXR holds a row per element AND part, and a style re-declares its
    # voices at every section -- Bandari 05's chord1 is FatSawHook in
    # Variation 1, DanceChords in 2 and CryingLead in 4 -- so the tone is
    # written per element rather than once per part.  The style's own volume
    # and pan go in the same pass: the template's were balanced for the
    # template's arrangement, so a converted rhythm would otherwise inherit,
    # say, a chord part at volume 70 panned to 85 -- faint and off to one side.
    # Reverb and chorus are left alone, because the two makers do not scale
    # their sends alike and a number copied across reads as a different
    # amount of room.
    # A sound-based drum map sends notes to keys in two NAMED kits, so those
    # kits have to be the ones loaded.  Leaving the template's kit in MIXR
    # made the map point at sounds that were not there: the perc part stayed
    # on STANDARD SET 1 while the map was addressing the ARABIC SET's tablah
    # and riq keys, so the mapping worked on paper and not in the instrument.
    if a.map and a.map.startswith("by-sound") and not a.tone:
        perc_kit, drum_kit = _sound_kits(a.map)
        for role, kit in (("perc", perc_kit), ("drum", drum_kit)):
            ac7.set_tone(tpl, role, kit, ac7.DRUM_BANK)
            ac7.set_mix(tpl, role, **convert.MIX_DEFAULTS[role])
        print(f"kits      : perc -> {_kit_name(perc_kit)}, "
              f"drum -> {_kit_name(drum_kit)}")

    chosen = _tones(a, rhythm) if not getattr(a, "no_tones", False) else None
    if chosen is not None:
        # Start every part from the measured convention, so no part is left
        # carrying a value the donor rhythm chose for its own arrangement --
        # the most complete donor is a waltz, and it sends its percussion to
        # reverb 127.  The style's own numbers are written over the top.
        for role, fields in convert.MIX_DEFAULTS.items():
            ac7.set_mix(tpl, role, **fields)
        done = {}
        for el in tpl.elements:
            src = rhythm.elements.get(el.role)
            if src is None:
                continue
            for role, part in src.parts.items():
                if part.is_drum or part.casio_tone is None:
                    continue
                prog, bank = part.casio_tone
                ac7.set_tone(tpl, role, prog, bank, elements={el.index})
                fields = dict(convert.MIX_DEFAULTS.get(role, {}))
                # A MegaVoice part's volume is not a balance, it is
                # compensation: those samples are recorded hot, so Yamaha
                # turns the part down to suit them.  Bandari 05 asks for 35
                # out of 127 on a MegaVoice guitar carrying 140 notes, and
                # carried onto a CT-X clean guitar that is almost silence.
                if part.volume and part.msb != tonemap.MEGAVOICE_MSB:
                    fields["volume"] = max(40, min(127, part.volume))
                if part.pan:
                    fields["pan"] = max(0, min(127, part.pan))
                ac7.set_mix(tpl, role, elements={el.index}, **fields)
                done.setdefault((role, part.casio_name), set()).add(el.role)
        for (role, cname), els in sorted(done.items()):
            print(f"tone      : {role:<7} {cname:<28} in {len(els)} elements")
    if a.keep_tempo:
        print(f"tempo     : kept from template ({tpl.tempo} bpm)")
    else:
        ac7.set_tempo(tpl, rhythm.tempo_bpm)
    tones = []
    for spec in a.tone:
        role, _, val = spec.partition("=")
        prog, _, bank = val.partition("/")
        try:
            prog = int(prog)
            bank = int(bank) if bank else None
        except ValueError:
            print(f"bad --tone {spec!r}: expected ROLE=PROGRAM[/BANK]")
            return 2
        n = ac7.set_tone(tpl, role.strip(), prog, bank)
        if not n:
            print(f"bad --tone {spec!r}: no part called {role.strip()!r}")
            return 2
        tones.append((role.strip(), prog, bank, n))

    for spec in a.mix:
        role, _, val = spec.partition("=")
        fields = {}
        try:
            for item in val.split(","):
                k, _, v = item.partition(":")
                fields[k.strip()] = int(v)
        except ValueError:
            print(f"bad --mix {spec!r}: expected ROLE=FIELD:VALUE[,FIELD:VALUE]")
            return 2
        try:
            n = ac7.set_mix(tpl, role.strip(), **fields)
        except ValueError as exc:
            print(f"bad --mix {spec!r}: {exc}")
            return 2
        if not n:
            print(f"bad --mix {spec!r}: no part called {role.strip()!r}")
            return 2
        print("mix       : " + role.strip() + " " +
              " ".join(f"{k}={v}" for k, v in fields.items()) +
              f" in {n} elements")

    meter_set = None
    if not a.keep_meter:
        code, verified, n = ac7.set_meter(tpl, rhythm.numerator, rhythm.denominator)
        if code is not None:
            meter_set = (code, verified, n)
    out = ac7.build(tpl)
    with open(a.out, "wb") as f:
        f.write(out)

    n = sum(c for _, _, c in rep["written"])
    print(f"\nwrote {a.out} ({len(out)} bytes) from template {a.template}")
    print(f"  elements written : {sorted({e for e, _, _ in rep['written']})}")
    if rep["skipped"]:
        print(f"  left as template : {rep['skipped']}")
    if rep["cleared"]:
        print(f"  emptied          : {rep['cleared']}")
    if rep["rebarred"]:
        print("  bar count fixed  : " + ", ".join(
            f"{e} {was}->{now}" for e, was, now in rep["rebarred"]))
    if rep["dropped"]:
        print("  no slot in AC7   : " + ", ".join(
            f"{e}/{r} ({c} notes)" for e, r, c in rep["dropped"]))
    if tones:
        print("  tones set        : " + ", ".join(
            f"{r} -> prog {p}" + (f" bank {b}" if b is not None else "")
            + f" ({n} elements)" for r, p, b, n in tones))
    print(f"  notes written    : {n}")
    want = ac7.ticks_per_bar(rhythm.numerator, rhythm.denominator)
    sig = f"{rhythm.numerator}/{rhythm.denominator}"
    if meter_set:
        code, verified, n = meter_set
        how = "verified against a factory rhythm" if verified else \
              "INFERRED from the two-sample encoding rule -- check it on the keyboard"
        print(f"  meter            : {sig} written as 0x{code:02x} "
              f"into {n} fields ({how})")
    elif a.keep_meter:
        print(f"  meter            : kept from template "
              f"({ac7.describe_meter(tpl_tpb)})")
    else:
        print(f"\n  METER NOT WRITTEN: {sig} is outside what the instrument "
              "accepts (its rhythm\n  editor offers 2/4 to 8/4 and 2/8 to "
              "16/8), so the keyboard "
              f"will read the template's meter of "
              f"{ac7.describe_meter(tpl_tpb)}.\n  Use a template rhythm "
              f"already in {sig}, or re-bar the style.")
        return 0
    if tpl_tpb is not None and tpl_tpb != want and not a.keep_meter:
        print(f"                     (template was {ac7.describe_meter(tpl_tpb)}, "
              f"now {want} ticks/bar to match the style)")
    return 0


def cmd_kitdiff(a):
    style, rhythm = _load(a)
    cap = capture.read_capture(a.capture)
    casio = capture.drum_notes(cap)
    if not casio:
        print("no notes on the CT-X accomp drum channels (9/10) -- was "
              "Accomp Out ON when you recorded?")
        return 2
    print("parts seen in capture: "
          + ", ".join(f"{r}:{sum(c.values())}" for r, c in sorted(cap.items())))
    print()
    print(capture.compare(drummap.histogram(rhythm), casio))
    if a.out:
        capture.write_proposal(
            capture.propose(drummap.histogram(rhythm), casio), a.out)
        print(f"\nwrote draft map to {a.out} -- audition it, then edit by ear")


def _read_ac7(path):
    with open(path, "rb") as f:
        return f.read()


def cmd_ac7info(a):
    d = _read_ac7(a.file)
    print(ac7.describe(ac7.parse(d)))
    if a.hex:
        print("\n-- header --")
        print(ac7.hexdump(d, 0, 128))


def cmd_ac7midi(a):
    obj = ac7.parse(_read_ac7(a.file))
    evs = ac7.to_midi_events(obj)
    write_smf(a.out, ac7.PPQN, [evs])
    print(f"wrote {a.out} ({len(evs)} events, {len(obj.elements)} elements)")


def cmd_ac7check(a):
    d = _read_ac7(a.file)
    obj = ac7.parse(d)
    rebuilt = ac7.build(obj)
    same = rebuilt == d
    print(f"parsed {a.file}: {len(obj.elements)} elements, "
          f"{sum(len(e.tracks) for e in obj.elements)} tracks")
    print(f"rebuild byte-identical: {same}")
    if not same:
        for i, (x, y) in enumerate(zip(rebuilt, d)):
            if x != y:
                print(f"  first difference at 0x{i:04x}: {x:02x} != {y:02x}")
                break
        print(f"  lengths {len(rebuilt)} vs {len(d)}")
        return 1
    return 0


def cmd_ac7diff(a):
    x, y = ac7.parse(_read_ac7(a.file_a)), ac7.parse(_read_ac7(a.file_b))
    import os
    print(ac7.diff(x, y, os.path.basename(a.file_a), os.path.basename(a.file_b)))


def main(argv=None):
    p = argparse.ArgumentParser(prog="y2c", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def style_args(sp, need_out=False):
        sp.add_argument("style")
        sp.add_argument("--map", default=None, help="drum map JSON")
        sp.add_argument("--unmapped", choices=["keep", "drop"], default="keep")
        sp.add_argument("--ppqn", type=int, default=ac7.PPQN,
                        help="target resolution (Casio uses 96)")
        sp.add_argument("--transpose", type=int, default=0)
        sp.add_argument("--merge-window", type=int, default=0, metavar="TICKS",
                        help="also merge same-key hits this close together "
                             "(0 = only exact ties); a map that collapses "
                             "many notes onto few keys needs this")
        sp.add_argument("--chord-fix", default="maj7-to-maj",
                        choices=list(convert.CHORD_FIX))
        sp.add_argument("--name", default=None, help="rhythm name (8 chars)")
        sp.add_argument("--no-mega", action="store_true",
                        help="leave MegaVoice parts as the style wrote them, "
                             "articulation layers and noise keys included")
        sp.add_argument("--no-tones", action="store_true",
                        help="keep the template's tones instead of mapping "
                             "the style's declared voices onto CT-X tones")
        sp.add_argument("--no-clamp", action="store_true",
                        help="keep element lengths the style asks for, even "
                             "past what a rhythm slot accepts")
        sp.add_argument("--core-only", action="store_true",
                        help="keep only the 6 elements the CT-X panel drives")
        sp.add_argument("--midi-layout", choices=["gm", "ctx"], default="gm",
                        help="preview MIDI channels: gm auditions correctly, "
                             "ctx mirrors the CT-X accomp part map")
        if need_out:
            sp.add_argument("-o", "--out", required=True)

    style_args(sub.add_parser("info"))
    style_args(sub.add_parser("report"))
    style_args(sub.add_parser("midi"), need_out=True)

    c = sub.add_parser("convert")
    style_args(c, need_out=True)
    c.add_argument("--template", help="a rhythm exported from your CT-X5000")
    c.add_argument("--clear-unused", action="store_true",
                   help="empty template elements the style has no data for "
                        "(default keeps the template's own pattern there)")
    c.add_argument("--keep-tempo", action="store_true",
                   help="keep the template's tempo instead of the style's")
    c.add_argument("--tone", action="append", default=[],
                   metavar="ROLE=PROG[/BANK]",
                   help="point a part at a tone, e.g. drum=33/120 -- the "
                        "drum streams carry no program change, so without "
                        "this a conversion plays the template's kit")
    c.add_argument("--mix", action="append", default=[],
                   metavar="ROLE=FIELD:VALUE[,...]",
                   help="set MIXR columns on a part, e.g. "
                        "perc=volume:110,reverb:30 -- fields are program, "
                        "bank, volume, pan, reverb, chorus; a part otherwise "
                        "inherits the template's balance, which was mixed "
                        "for the template's arrangement and not for ours")
    c.add_argument("--keep-meter", action="store_true",
                   help="keep the template's time signature instead of "
                        "writing the style's")

    k = sub.add_parser("kitdiff")
    style_args(k)
    k.add_argument("capture", help="MIDI recording of the CT-X accomp output")
    k.add_argument("-o", "--out", help="write a draft drum map here")

    i = sub.add_parser("ac7info"); i.add_argument("file")
    i.add_argument("--hex", action="store_true", help="also dump the header")
    m = sub.add_parser("ac7midi"); m.add_argument("file")
    m.add_argument("-o", "--out", required=True)
    v = sub.add_parser("ac7check"); v.add_argument("file")
    df = sub.add_parser("ac7diff")
    df.add_argument("file_a"); df.add_argument("file_b")

    a = p.parse_args(argv)
    fn = {"info": cmd_info, "report": cmd_report, "midi": cmd_midi,
          "convert": cmd_convert, "kitdiff": cmd_kitdiff,
          "ac7info": cmd_ac7info, "ac7midi": cmd_ac7midi,
          "ac7check": cmd_ac7check, "ac7diff": cmd_ac7diff}[a.cmd]
    return fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
