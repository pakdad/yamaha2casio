"""Read the CT-X Tone List out of Casio's appendix into name -> (program, bank).

    pdftotext -layout docs/CTX-appendix-tone-rhythm-lists.pdf /tmp/app.txt
    python3 tools/ctxtones.py /tmp/app.txt --json maps/ctx-tones.json
    python3 tools/ctxtones.py /tmp/app.txt --grep santur

This is the melodic half of the mapping problem, and until now the converter
had no answer to it at all.  `ac7.apply_rhythm` keeps the template's MIXR
verbatim -- which is right for a format we only partly understand, but it
means every converted rhythm plays the TEMPLATE's tones.  The Yamaha style
declares a voice per part, 187 distinct ones across the 46 Iranian styles,
and all 187 were being thrown away.  That is why a converted style can have
every note in the right place and still not sound like the original: the
santur line was coming out as whatever the donor rhythm happened to hold.

The appendix prints the list in seven-column page spreads, so the rows are
read with a regex rather than by position:

    493 SANTUR 1               15     1            4
    NNN name                   PC    MSB   [DSP]  octave shift

The "Program Change" column is the raw MIDI program, 0-based: GM NYLON
STR.GUITAR is 24 where General MIDI calls it 25, and GM TIMPANI is 47 for
GM's 48.  Yamaha's Data List prints PC 1-based instead, so a Yamaha voice at
PC 16 and a Casio tone at program 15 are the same program number.

Two spaces at least must separate the name from the numbers, because tone
names end in serial numbers: with a single-space rule "SANTUR 1" parses as
name SANTUR, program 1, bank 15.  A few long names do sit one space from
their column, so those are picked up in a second, looser pass over whatever
the first pass missed.

About 11 of the 800 rows are lost because pdftotext cuts the page spread and
leaves the name with no numbers beside it ("339 DIRTY PLUCK").  None of them
is a drum kit and none is reachable another way from this text, so they are
simply absent from the table; --json reports the count.
"""
import argparse
import collections
import json
import re

NAME = r"[A-Z0-9][A-Z0-9 .,&'’\-+/\[\]()]*?"
STRICT = re.compile(rf"(?<![\d.])(\d{{3}})\s+({NAME})\s{{2,}}"
                    r"(\d{1,3})\s+(\d{1,3})\s+(DSP\s+)?(\d)(?!\d)")
LOOSE = re.compile(rf"(?<![\d.])(\d{{3}})\s+({NAME})\s+"
                   r"(\d{1,3})\s+(\d{1,3})\s+(DSP\s+)?(\d)(?!\d)")

# Casio's drum kits live in bank 120, the same bank the MIXR rows of the two
# percussion parts carry.  Keeping them out of the melodic table stops a
# chord part being handed a kit because its name matched.
DRUM_BANK = 120


def parse(text):
    """{tone number: {"name", "program", "bank", "dsp"}}."""
    out = {}
    for rx in (STRICT, LOOSE):
        for m in rx.finditer(text):
            n = int(m.group(1))
            if n in out:
                continue
            pc, msb = int(m.group(3)), int(m.group(4))
            if pc > 127 or msb > 127:
                continue
            out[n] = {"name": " ".join(m.group(2).split()),
                      "program": pc, "bank": msb, "dsp": bool(m.group(5))}
    return dict(sorted(out.items()))


def melodic(tones):
    """[(name, program, bank)] -- the pitched tones, kits left out."""
    return [(t["name"], t["program"], t["bank"])
            for t in tones.values() if t["bank"] != DRUM_BANK]


def main():
    p = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("text", help="appendix text from `pdftotext -layout`")
    p.add_argument("--json")
    p.add_argument("--grep", help="print tones whose name matches")
    a = p.parse_args()
    tones = parse(open(a.text, encoding="utf-8").read())
    if a.grep:
        rx = re.compile(a.grep, re.I)
        for n, t in tones.items():
            if rx.search(t["name"]):
                print(f"  {n:3d} {t['name']:<28} program {t['program']:3d} "
                      f"bank {t['bank']:3d}{'  DSP' if t['dsp'] else ''}")
        return
    kits = sum(1 for t in tones.values() if t["bank"] == DRUM_BANK)
    missing = [i for i in range(1, max(tones) + 1) if i not in tones]
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(tones, f, indent=1, ensure_ascii=False)
        print(f"wrote {a.json}: {len(tones)} tones "
              f"({len(tones) - kits} melodic, {kits} drum kits), "
              f"{len(missing)} rows lost to the page split")
    else:
        cat = collections.Counter(t["bank"] for t in tones.values())
        print(f"{len(tones)} tones, {kits} of them drum kits; "
              f"missing: {missing}")
        print("banks:", ", ".join(f"{b}x{n}" for b, n in cat.most_common(12)))


if __name__ == "__main__":
    main()
