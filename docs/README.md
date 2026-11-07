# Casio's own documentation

The manuals that ship with the CT-X5000 answer most questions about this
format far better than guessing does, and several of this project's decisions
came straight out of them. They are **not committed** — they are the
instrument maker's content, which is the same policy `samples/README.md`
applies to factory rhythms, and they are 15 MB of binary besides. Put your own
copies here:

| file | where it comes from | what it settles |
|---|---|---|
| `CTX5000_3000_EN.pdf` | user's guide, CT-X5000 and CT-X3000 | The rhythm editor section (EN-77 to EN-83) is effectively a field list for AC7: the eight accompaniment parts, the six mixer columns, the per-element bar limits, the meter range. |
| `CTX-appendix-tone-rhythm-lists.pdf` | tone/rhythm list appendix (14M3APPEND) | The **Drum Assignment List** — every note of all 36 drum kits, by name, with each kit's program and bank. |
| `CT-X5000-midi-implementation.pdf` | MIDI implementation chart | |

Casio publishes these on its support site; the appendix also ships with the
instrument.

## Extracting them

The tables are wide and lose their columns without `-layout`:

```sh
pdftotext -layout docs/CTX-appendix-tone-rhythm-lists.pdf /tmp/app.txt
python3 tools/drumlist.py /tmp/app.txt --json maps/ctx-drum-assignments.json
python3 tools/drumlist.py /tmp/app.txt --kit 'ARABIC SET'
```

The same text holds the **Tone List**, which is what tells the converter
which CT-X tone to give a part:

```sh
python3 tools/ctxtones.py /tmp/app.txt --json maps/ctx-tones.json
python3 tools/ctxtones.py /tmp/app.txt --grep 'santur|oud|kanun|ney'
```

789 of the 800 rows parse; the other 11 lose their numbers to the page split
and none of them is a drum kit. The parse is confirmed against the three
factory rhythms in `samples/`: decoding their MIXR through this table names a
musically sensible tone for every part of all three — fingered bass, synth
bass and strings on the bass part, and BRUSH SET on the waltz's drums.

## Yamaha's documentation

A PSR Data List `.xlsx` supplies the other three tables. Any recent model
will do; the Iranian styles were authored for an S-series and the banks are
shared.

```sh
python3 tools/yamahakits.py   DataList.xlsx --json maps/yamaha-drum-kits.json
python3 tools/yamahavoices.py DataList.xlsx --json maps/yamaha-voices.json
python3 tools/megavoice.py    DataList.xlsx --json maps/yamaha-megavoice.json
```

All of `maps/*-tones.json`, `maps/yamaha-*.json` and
`maps/ctx-drum-assignments.json` are generated, so none is committed.
Regenerate them before converting, and before using `tools/make_drummap.py`.

## Measurements of the instrument

Nothing in this folder is committed except this file. The manuals are Casio's,
so they are fetched rather than redistributed.

Measurements taken off the instrument rather than read out of a manual — which
keys a kit really has, and what each one sounds like — live in the companion
repository, [audio2style](https://github.com/pakdad/audio2style), along with
the recording and analysis scripts that produce them. The converter does not
need them: the tables it reads come from the manuals above.
