# yamaha2casio (`y2c`)

Convert Yamaha style files (`.sty`, `.prs`, `.bcs`, `.pcs`) into Casio CT-X
rhythms.

Pure Python 3, standard library only — every part of it, the converter, the
window, the `.AC7` reader and the table scripts, runs on a stock Python with
nothing installed. Developed and tested on 3.13; nothing in it uses syntax
newer than 3.8.

Recording the instrument and transcribing rhythms from audio are a separate
job, and live in a companion repository:
[audio2style](https://github.com/pakdad/audio2style). It writes `.sty` files,
which this converts. The two share a file format and no code, so neither has
to be installed to use the other.

## What you have to supply

Three things are deliberately **not** in this repository, and the first two
are needed before it can write a rhythm at all.

| | why it is not here |
|---|---|
| **A rhythm exported from your own CT-X**, as `--template` | A converted rhythm is written *into* a real `.AC7` container. Factory rhythms are the instrument maker's content. Save any user rhythm to USB from your keyboard and point `--template` at it. |
| **Yamaha styles to convert** | Yours to find; the tool reads them, it does not ship them. |
| **The published tables**, in `maps/` | Generated from Casio's and Yamaha's own manuals by the scripts in `tools/`. They are the makers' content too, so they stay out of the history. `docs/README.md` has the one command each. |

Without the tables the converter still runs — it falls back to a hand-written
drum map such as `maps/persian.json` and leaves the template's tones alone —
but the sound-based drum mapping and the tone mapping, which are most of what
makes a conversion sound like the original, need them. Every command that
wants one says so and tells you how to build it.

`python3 y2c_gui.py --selftest` reports exactly which of them you have.

## Scope, and what this is not

The `.AC7` format is undocumented. Everything here about it was worked out by
reading files, measuring the instrument's output, and checking against
Casio's own published manuals — the method, and where each claim came from,
is the substance of this README. Much of it is confirmed against factory
rhythms; some of it is still inference, and the [Known
gaps](#known-gaps) section says which is which.

No Casio or Yamaha content is distributed here: no rhythms, no manuals, no
extracted tables, no samples. *Casio*, *CT-X*, *Yamaha* and *PSR* are their
owners' trademarks; this project is not affiliated with or endorsed by
either company.

The code is MIT licensed — see [LICENSE](LICENSE). That covers this code
only. What you convert with it, and the tables you generate from manuals you
own, are between you and whoever owns them.

## The three stages

1. **Read the Yamaha style** — exact. `.sty` is a Standard MIDI File plus
   `CASM`/`OTS` chunks; section markers (`Main A`, `Fill In AA`, …) split it
   into parts, and MIDI channels 9–16 are the eight style tracks.
2. **Translate** — drum-note mapping, source-chord fix, tempo/meter, and
   Yamaha track → Casio part assignment. This is where Persian rhythms need
   your attention.
3. **Write the `.AC7`** — rebuilds a real Casio rhythm file, using one
   exported from your own keyboard as the container.

## Quick start

These three need nothing but a style file, so they work on a fresh clone:

```sh
./y2c.py info   MyPersianStyle.sty                       # what's inside
./y2c.py report MyPersianStyle.sty --map maps/persian.json   # drum notes used
./y2c.py midi   MyPersianStyle.sty -o preview.mid --map maps/persian.json
```

`preview.mid` is the *converted* rhythm rendered back to MIDI, elements laid
end to end with markers. Audition it before touching the keyboard — if it
sounds right there, only the container is left to get right.

Writing a rhythm needs a container exported from your own keyboard, and the
good drum mapping needs the generated tables — see [What you have to
supply](#what-you-have-to-supply):

```sh
./y2c.py convert MyPersianStyle.sty -o PERSIAN.AC7 \
    --map by-sound:52/0 --name PERSIAN --template MY_RHYTHM.AC7
```

There is [a window](#a-window-if-you-would-rather-not-type) too, if you would
rather click: `python3 y2c_gui.py`.

`--map by-sound:PERC/DRUM` routes each drum note by the SOUND its declared
Yamaha kit gives it, into two named Casio kits — see
[Drum maps](#drum-maps--the-part-that-matters-for-persian-rhythms) — and loads
those two kits, which the older `--tone perc=52/120 --tone drum=0/120` had to
be remembered for. Melodic parts get their tones from the style as well; see
[Tones](#tones--the-other-half-of-the-mapping-problem).

A whole folder at once, with names a FAT volume and a 12-character display
field will both take:

```sh
python3 tools/convert_all.py STYLEDIR -o OUTDIR \
    --template MY_RHYTHM.AC7 --map by-sound:52/0
```

## A window, if you would rather not type

```sh
python3 y2c_gui.py
```

Pick a style file or a whole folder, press **Convert**, then **Copy to
keyboard**. Everything it does is `y2c.py convert`; it saves the typing and
it checks the copy, comparing each file on the stick against the one it
wrote and saying so byte for byte.

It calls the converter **in-process** rather than running `y2c.py` as a
subprocess. A frozen build has no `python3` to spawn and no script on disk to
point at, so a subprocess works from a checkout and fails as an .exe — the
kind of difference that only shows up after shipping. In-process also means
the log pane shows the converter's own output, with no second code path to
keep in step. That is why the commands live in `y2c/cli.py` with `y2c.py` as
a four-line wrapper: a top-level `y2c.py` beside a `y2c/` package cannot be
imported, because the package wins the name.

Only tkinter is used, which ships with Python. `python3 y2c_gui.py
--selftest` prints whether the published tables are where the program expects
them — worth running on a frozen build, where the code is fine and it is the
*data* that goes missing.

### Making it a program you can double-click

```sh
pip install pyinstaller
python3 tools/build_app.py          # -> dist/y2c, needs no Python to run
python3 tools/build_app.py --check  # just say what a build here would be
```

**PyInstaller cannot cross-compile.** It bundles the interpreter that runs
it, so the building machine fixes both the operating system and the
processor of the result, and there is no flag for either. A Windows `.exe`
must be built by a Windows Python; an x86-64 `.exe` by an x86-64 one.

On Linux, wine supplies the Windows Python:

```sh
tools/build_windows_exe.sh          # -> dist-windows/y2c.exe
```

On an x86-64 Linux machine that gives the ordinary `y2c.exe` that runs on any
Windows PC. **It will not do so on an ARM machine**, for two reasons found by
trying it on a Raspberry Pi 5 rather than by reasoning about it:

* Debian's arm64 wine packages carry only the ARM Windows libraries — their
  `x86_64-windows` directories are empty and there is no `wowbox64.dll` to
  bridge to box64 — so the best it could build is an ARM64 Windows binary,
  for Snapdragon and Surface laptops and not for a normal PC.
* On the `rpi-2712` kernel it cannot build even that: the Pi 5 uses 16 KiB
  memory pages and wine requires 4 KiB, so `wineserver` refuses to start at
  all. Booting `kernel=kernel8.img` would fix that, and would still leave the
  first problem. The script checks the page size first and says so, rather
  than failing confusingly half an hour into downloading Python.

So on a Pi, build the native `dist/y2c` and use that; produce the `.exe` on an
x86-64 machine with the same script, unchanged.

## Track and section mapping

Verified against the CT-X3000/CT-X5000 MIDI Implementation, §1.3.2: the CT-X
accomp parts 09–16 are Percussion, Drum, Bass, Chord 1–5 on MIDI channels
9–16 — the same channel layout Yamaha styles use, so this is a
channel-for-channel pass-through.

| Channel | Yamaha track | Casio part | AC7 part index |
|---|---|---|---|
| 9  | Rhythm Sub  | Percussion | 0 |
| 10 | Rhythm Main | Drum | 1 |
| 11 | Bass        | Bass |
| 12 | Chord 1     | Chord 1 |
| 13 | Chord 2     | Chord 2 |
| 14 | Pad         | Chord 3 |
| 15 | Phrase 1    | Chord 4 |
| 16 | Phrase 2    | Chord 5 |

The preview MIDI defaults to `--midi-layout gm` (both drum parts on channel 10)
so it auditions correctly in a normal player; `--midi-layout ctx` mirrors the
table above instead. Neither can drive the keyboard's accompaniment engine —
the MIDI Implementation lists no receive channel for the port A accomp parts.

The AC7 part index is the channel minus 9, so part 0 is Percussion and part 1
is Drum. Getting that pair the wrong way round is silent whenever both drum
parts share a kit and badly audible when they do not, so it is worth stating
twice.

`Main A–D` → `Variation 1–4`, `Fill In AA–DD` → `Fill 1–4`,
`Intro A–D` → `Intro 1–4`, `Ending A–D` → `Ending 1–2`.
The CT-X5000 panel only drives six of these; `--core-only` keeps just those.

## Casio's own documentation

`docs/` holds the manuals that ship with the keyboard. They are worth reading
before guessing anything:

| file | what it settles |
|---|---|
| `CTX5000_3000_EN.pdf` | user's guide, CT-X5000 **and** CT-X3000. The rhythm editor section (EN-77 to EN-83) is effectively a field list for the AC7 format: the eight parts, the six mixer columns, the element bar limits, the meter range. |
| `CTX-appendix-tone-rhythm-lists.pdf` | tone list, rhythm list and the **Drum Assignment List** — every note of every one of the 36 drum kits, by name, with each kit's program and bank. |
| `CT-X5000-midi-implementation.pdf` | MIDI implementation. |

Extract either as text with `pdftotext -layout` before grepping; the tables are
wide and lose their columns without it.

### The drum assignment list replaces guesswork

Most of this project's sound identification was done the hard way — record a
key sweep off the instrument, measure each hit's fundamental, decay and band
energies, and name it. That worked, but it mislabelled sounds and it could not
see a key no probe had struck. Casio publishes the list. `tools/drumlist.py`
parses it:

```sh
pdftotext -layout docs/CTX-appendix-tone-rhythm-lists.pdf /tmp/app.txt
python3 tools/drumlist.py /tmp/app.txt --kit 'ARABIC SET'
python3 tools/drumlist.py /tmp/app.txt --json maps/ctx-drum-assignments.json
```

`maps/ctx-drum-assignments.json` is the checked-in result: 36 kits, each with
its program, bank and note names. **Kit 52 is `ARABIC SET`** (tone 792). What
measurement had got wrong about it:

| key | measured as | actually |
|---|---|---|
| 69, 70, 71 | doum, bright slap, crisp tak | `Tablah 1/2/3` — right |
| 72, 73 | "open tone (208 Hz)", "open tone (288 Hz)" | **`Daf 1`, `Daf 2`** — the Persian frame drum, the most idiomatic sound in the kit for this music, and unused |
| 77, 78 | "mid tone, quiet", "metal, very bright" | `Davul 1/2`, a Turkish bass drum — "very bright metal" is not a bass drum, so one of those measurements was simply wrong |
| 79, 80 | "metal, very bright", "low-mid resonant" | `Zill 1/2`, finger cymbals |
| 88-91 | never probed | **`Riq Jingle`, `Riq Slap`, `Riq Tek 1`, `Riq Tek 2`** — the probe swept 59 and 69-80 and stopped |

Keys 81-87 carry no sound in this kit. The low range (35-68) is the kit's own
standard drums, so a rhythm can keep kick, snare, hats and the hand drums on
one kit instead of splitting across two.

`tools/kit_table.py` still answers a different and useful question — which
keys the factory rhythms actually *use*, which separates an idiomatic choice
from a merely legal one — but it is no longer the authority on what a key is.

## Drum maps — the part that matters most

Yamaha oriental styles use the Arabic/Turkish kits, whose doum, tak, riq and
sagat articulations sit **outside** the GM percussion range and do not line up
with the CT-X Middle-East kits. `maps/persian.json` passes GM notes 35–87
through unchanged and maps the oriental notes to their nearest GM equivalent so
the groove is at least recognisable. Then tune it by ear:

```sh
./y2c.py report MyStyle.sty --map maps/persian.json
```

prints every drum note the style uses, how often, and where it lands, broken
out per Casio part.

**A collapsing map needs collision merging.** A Yamaha kit has far more keys
than an oriental Casio kit has, so several source articulations end up on one
target key — and where two of them land on the same tick, one drum voice
cannot play both. It retriggers, which sounds like a buzz or a choke and not
like a rhythm. `convert` therefore merges same-key hits that coincide, keeping
the loudest, and reports how many it merged; `--merge-window TICKS` also
merges hits that are merely very close. On the Iranian styles the oriental map
produced 8.5% colliding notes on the percussion part against 1.0% for the
standard-kit map, which is what made it sound wrong. Edit the `notes` object (`"27": 36`) until it sounds right;
`null` drops a note.

The two drum parts can hold different kits, so a map can give one its own
table — which it has to, when that kit is not GM-mapped:

```json
{"notes": {"36": 36}, "parts": {"perc": {"kit": 52, "notes": {"36": 69}}}}
```

`maps/ctx-oriental.json` is that map for Persian material: the percussion part
goes to the oriental kit and the drum part keeps a standard one. Declaring
`kit` lets `report` name the targets correctly — without it the doum shows up
labelled "Cabasa", which is its GM name and not what it is.

```sh
./y2c.py convert STYLE -o OUT.AC7 --map maps/ctx-oriental.json \
    --template 'Baladi X3000.AC7' --clear-unused --tone drum=40/120
```

### A note number is only half of a drum sound

The drum event streams contain **no program change at all**. Which kit a part
plays comes from the `MIXR` table, which the converter inherits from the
template — so the same note data sounds completely different depending on
which rhythm was used as the container, and a map tuned against one template
is wrong against another.

`ac7info` prints the tones a rhythm assigns. `convert --tone ROLE=PROG[/BANK]`
overrides them, which is how a conversion stops depending on its template:

```sh
./y2c.py ac7info MY_RHYTHM.AC7                # what kits does it assign?
./y2c.py convert ... --tone drum=0/120 --tone perc=0/120
```

Program 0 in bank 120 behaves as a full GM-compatible standard kit on both
drum parts, and is the safest target for a **converted** rhythm, whose note
numbers come from the Yamaha style and are GM-flavoured. Kits like programs
33, 34 and 40 are specialised — a rhythm that assigns a *different* kit to
each of its two drum parts will play ordinary GM note numbers as the wrong
instruments.

The most reliable way to choose notes is to copy the ones a factory rhythm
already strikes in the kit you are targeting, since those are proven to exist
and to be audible. `tools/kit_table.py` reports exactly that, read off a tree
of factory rhythms, and the rhythm-authoring scripts in
[audio2style](https://github.com/pakdad/audio2style) record the strike count
behind every note they use.

### The oriental kit, and where the doum and tak are

For a rhythm written here from scratch, rather than converted, the Arabic &
Oriental factory rhythms are the better model. They put their hand drums on
the **percussion** part using **kit program 52** (bank 120), whose vocabulary
sits in notes 69–80, and pair it with a kick/hat kit on the drum part
(program 4 in Baladi, 2 in Khaliji).

Which key is which articulation was settled by position, in three rhythms
independently — each is a different pattern, so they are not one observation
repeated:

| Rhythm | Canonical pattern | What note 69 does | What 71 does |
|---|---|---|---|
| Malfouf | doum tak tak | beats 1 and 3, loudest in the element (v112) | the offbeat taks (v101) |
| Baladi | doum doum · tak · doum · tak | beat 1, and-of-1, beat 3 | the two taks |
| Khaliji | — | the kick (35) doubles this pattern exactly | the lighter layer is 73 |

So **69 is the doum, 71 the tak**, 73 a lighter tak layer and 70 the busy soft
riq. `Baladi X3000.AC7` also makes a good container: oriental kits, a fretless
bass, an oriental chord part (program 105 bank 11), and bass and chord tracks
present in *every* element including the intro and ending — which the stock
6/8 rhythm lacks.

CT-X3000 and CT-X5000 rhythms are interchangeable — a CT-X3000 factory rhythm
imported into a CT-X5000 is identical to that keyboard's own copy — so the
CT-X3000 factory set is usable on either, both as data and as templates.

### Which notes a kit actually has

Since the assignment list is unpublished, the only evidence that a kit has
anything on a given key is a factory rhythm striking it there.
`tools/kit_table.py` reads a tree of factory rhythms, pairs each drum track
with the kit its `MIXR` row assigns, and tabulates it:

```sh
python3 tools/kit_table.py '/path/to/CT-X3000 Rhythm Archive'
python3 tools/kit_table.py ARCHIVE --covers converted/oriental drum
```

Read the table as a lower bound: it says what is safe, not what is absent.
Over the 235-rhythm factory set it finds 27 kits, and the useful summary is:

| Kit | Keys struck | Character |
|---|---|---|
| 0 | 92, spanning 1–125 | the richest standard kit |
| 40 | 67, spanning 19–112 | standard, best upper-percussion coverage |
| 2 | 68, spanning 7–102 | standard |
| 52 | 13 — only 59 and 69–80 | **oriental hand drums**, nothing below 59 |
| 51 | 7 — only 69–75 | a second, smaller oriental kit |

`--covers` scores each kit against what a set of rhythms actually plays, which
is how to choose one rather than guess. Kit 40 on the drum part and kit 52 on
the percussion part cover **100%** of what the Iranian conversions play; the
standard-kit pairing left notes on keys that are never struck in those kits,
and those would simply be silent.

### Asking the keyboard instead of guessing

Reading the factory rhythms gives a key's rhythmic *role* — which beats it
lands on, how loud, how often — but never its sound. For that you have to ask
the instrument, which means playing a diagnostic rhythm and listening to it.
`make_probe.py` in [audio2style](https://github.com/pakdad/audio2style) writes
them, and this converts them:

```sh
python3 make_probe.py /tmp/p.sty notes       # one key per bar, 4 hits
./y2c.py convert /tmp/p.sty -o PROBE.AC7 --map maps/identity.json \
    --name PROBE --template MY_RHYTHM.AC7 --clear-unused
```

`notes` walks a kit one key per bar, grouped so each variation button plays a
short labelled run — enough to hear what each key actually is. `layers` plays
one groove with the percussion part alone, then the drum part alone, then
both, so a bad layer can be named in four button presses instead of guessed
at.

That is also where the recording and measuring side lives, for reading the
answers back. Two wrong guesses about a key's sound cost more than the five
minutes a probe takes.

### Deriving the map from the keyboard instead of guessing

The MIDI Implementation documents the accomp parts as transmit-only and says
Volume/Pan/Reverb/Chorus/Delay Send are sent "when MIDI setting of Accomp Out
is set to ON and automatic accompaniment is used". So the keyboard will tell
you what its own oriental kits use:

1. On the CT-X5000: MIDI setting → **Accomp Out = ON**.
2. Start one of its own Middle-East rhythms.
3. Record its MIDI output to a `.mid`.

```sh
./y2c.py kitdiff MyStyle.sty ctx_capture.mid -o maps/draft.json
```

This prints the style's drum notes beside the captured Casio notes, both ranked
by how often they are struck, and drafts a map: notes present in both kits map
to themselves, the rest are paired by rank. The pairing is a starting point to
audition, not an answer — but it beats guessing, because the right-hand column
is ground truth from your instrument.

## Tones — the other half of the mapping problem

The drum map decides what a *note* sounds like. Nothing decided what a *part*
sounded like, and that was the larger omission. `ac7.apply_rhythm` keeps MIXR
verbatim, so every converted rhythm played **the template's** tones: a style
asking for a santur came out as whatever the donor rhythm held on that part,
and the 46 Iranian styles declare 187 distinct voices that were all being
discarded. A conversion could have every note in the right place and still
not sound like the original.

`convert` now reads the voice each part declares and picks a CT-X tone for
it, writing program, bank, volume and pan into MIXR per element — per
element, because a style re-declares its voices at every section: Bandari 05
plays chord 1 as FatSawHook in variation 1, DanceChords in 2 and CryingLead
in 4.

Two published tables make it possible, neither of them committed:

```sh
pdftotext -layout docs/CTX-appendix-tone-rhythm-lists.pdf /tmp/app.txt
python3 tools/ctxtones.py /tmp/app.txt --json maps/ctx-tones.json
python3 tools/yamahavoices.py DataList.xlsx --json maps/yamaha-voices.json
```

The matching is in two layers, and the division matters:

* **Within the GM family.** Both makers lay their variations over the 128
  General MIDI programs, so a voice's program names its family and can be
  trusted alone. Among the Casio tones sharing that program, the closest name
  wins; with no name match the plain `GM ...` tone is used. This cannot put a
  part in the wrong family, because the family is fixed before any name is
  compared.
* **Across families, only by an explicit table.** The makers disagree about
  where some instruments live — Yamaha files Kanoun under GM 108 (Koto) and
  Casio files KANUN under GM 16 (Dulcimer) — so layer 1 would answer "Koto"
  and be confidently wrong. Cross-family moves are therefore never inferred.
  `tonemap.CROSS_FAMILY` lists them one line each, checked against both
  published lists. It is short, and it is where most of the value is: the
  CT-X5000 has SANTUR, KANUN, OUD, NEY, SAZ, ZURNA, KEMENCHE, RABAB and
  ARABIC STRINGS, and the converter was reaching none of them.

Reverb and chorus are **not** carried from the style — the two makers do not
scale their sends alike, so the number means a different amount of room.
They come instead from `convert.MIX_DEFAULTS`, measured across 37 working
CT-X rhythms which agree on them exactly. Volume and pan do come from the
style, because those are a balance between its own parts, with one exception
noted below.

### MegaVoice parts are not music until they are flattened

A Yamaha MegaVoice stacks a bank of articulations behind one program and
chooses between them by velocity and key zone. In a MegaVoice part the
velocity byte is not a dynamic and the high keys are not pitches. Yamaha's
tone generator knows this; nothing else does, so the layers arrive as music.
Measured over the 46 styles: 12,496 of their 65,872 melodic notes (19.0%) are
on MegaVoice parts, in 19 of the 46 styles, and by layer those break down as

| layer | notes | share |
|---|---|---|
| a plain dynamic, playable as written | 9,129 | 73.1% |
| the noise key zone | 2,109 | 16.9% |
| dead or muted strokes | 1,154 | 9.2% |
| harmonics and pitch gestures | 73 | 0.6% |
| slaps and pops | 31 | 0.2% |

The noise zone is the decisive one. Yamaha's own map heads those columns "C6
and higher" and "C8 and higher", in keyboard octaves where middle C is C3 —
and the styles confirm the reading rather than the other way round. Their
MegaVoice notes form two populations with a clean gap: 10,380 notes run from
key 24 to key 83 and stop, **seven** stray notes sit in 84–95, and then 2,109
notes cluster from **exactly 96** with a second rise at **exactly 120**. Both
thresholds land on the document's own boundaries. Played on a pitched tone
those are shrill high notes — the "whistle" on a chord part.

The velocity zones invert the dynamics, which is the subtler damage. A guitar
MegaVoice answers 61–75 with a dead note and 76–90 with a mute; a guitarist
plays those to get *out of the way*, and they arrive as the loudest notes in
the part. So `y2c/mega.py` drops the noise zone, drops the layers whose pitch
is not the written pitch (harmonics, glissandi, falls, scoops), and rebuilds
velocity so that the layer *order* becomes the dynamic. Hammer-ons and slides
are kept — they do sound at the written pitch — at the middle of the range
rather than the top.

A MegaVoice's program is also not a GM program: MegaVoice 17 is an electric
bass where GM 17 is a percussive organ, and asking Casio for program 17 put
the corpus's most-used bass on `GM ORGAN 2`. The family is recovered through
Yamaha's own catalogue instead — the best-matching *regular* voice carries
the program the MegaVoice means, so NylonGuitar resolves via NylonGuitarSlide
to 24 and ElectricBass via ElectricBass to 33.

A MegaVoice part's volume is not carried over either. Those samples are
recorded hot, so Yamaha compensates with a low part volume: Bandari 05 asks
for 35 out of 127 on a MegaVoice guitar carrying 140 notes, which on a CT-X
clean guitar is almost silence.

### Voices are declared per section, not in the setup block

`ir._mixer` read only the `SInt` block, and that was wrong for most styles.
SInt is an *initialise*: Bandari 05's sets all sixteen channels to bank 0/113
program 0, a grand piano, and the voices the style plays are sent again at
the **start of each section**. Reading SInt alone reported every melodic part
of every style as a grand piano — so the first working version of the tone
mapper faithfully gave all of them one, and the MegaVoice pass saw 13 of the
46 styles instead of 19. `ir.mixer_at` replays every change up to a section's
end instead, which is also what a sequencer does, so a section that does not
re-send a program keeps the one in force.

`--no-mega`, `--no-tones` and `--no-clamp` turn the three passes off.

## Chord parts

Yamaha records chord tracks against a source chord of CMaj7; Casio expects a
plain C major. `--chord-fix maj7-to-maj` (default) folds the major 7th up an
octave, `maj7-drop` removes it, `none` leaves it alone. Irrelevant for
drum-only rhythms.

### Chord 5, and choosing a donor

The editor lists five chord parts and MIXR carries eight rows per element, so
Chord 5 exists — but **no factory rhythm puts a stream on it**, and a rhythm
can only be built on a factory container, so there is no track to write it
into. Dropping it cost real music: 4,179 notes across the 46 styles. A part
with nowhere to go is now moved to the highest chord slot its element leaves
empty, carrying its own voice, which works precisely because the tone is set
per part from the style instead of inherited from the slot.

**Donors are not interchangeable**, for the same reason, and this is worth a
minute when you pick yours. A rhythm can only be written into the tracks its
container already has, so a donor missing a part in some element silently
drops that part's notes there. Of the three factory rhythms used while
working on this, one carried all seven parts in all ten used elements and
another was missing bass in three of them — and that one was quietly losing
bass notes from intros and endings until the two were compared.

`y2c.py ac7info YOUR.AC7` lists each element's tracks, so you can check a
candidate before adopting it. Prefer a dense, fully arranged rhythm. The
donor's own meter does not matter, because `convert` writes the meter.

## Meter

The time signature is stored in TLV id `0x01`, packed as

```
code = (numerator << 3) | log2(denominator)
```

so the numerator occupies the top five bits and the denominator's power of two
the low three. `convert` writes it, which means **the template does not have to
be in the style's meter** — a 4/4 factory rhythm can carry a 6/8 or 3/8 one.

The instrument's own rhythm editor settles what the field can hold: its
"Beat" setting offers **2/4 to 8/4 and 2/8 to 16/8** (user's guide, EN-77).
The codec round-trips every meter in that range, which is a much stronger
check than the three codes that could be read off factory rhythms, and it
bounds the domain — `4/16` and `2/2` have no representation the keyboard will
read, so `meter_code` now refuses them instead of writing a byte it cannot
interpret. Odd numerators are fine: 3/4, 5/4, 7/8 and 9/8 all encode.

Note that many "Iranian 6/8" Yamaha styles are authored in **4/4**, with the
6/8 feel carried inside the bar rather than in the time signature. `info`
reports what the file actually declares.

## The AC7 container

The Yamaha format is published; AC7 is not. It was reverse-engineered here from
rhythms exported from a CT-X5000, and the model is verified by parsing each one
and rebuilding it **byte for byte** — currently all 235 rhythms of the CT-X3000
factory set plus three exported from the keyboard, 238 files, zero differences:

```sh
./y2c.py ac7check YOURS.AC7      # parse + rebuild, must report identical
./y2c.py ac7info  YOURS.AC7      # elements, tracks, note counts, meter
./y2c.py ac7midi  YOURS.AC7 -o casio.mid    # hear what the decoder sees
./y2c.py ac7diff  A.AC7 B.AC7    # which field differs between two rhythms
```

`ac7diff` compares two rhythms field by field. It is how the remaining unknown
parameters get pinned down: export two factory rhythms that differ in exactly
one respect and the field that encodes it is the one that moves. It also makes
a useful check on a conversion — diffing a converted rhythm against its own
template should report only the name, the tempo and the bar counts.

The layout is documented at the top of [y2c/ac7.py](y2c/ac7.py). In short:
a 28-byte header with absolute section offsets, an element directory, one
`ELMT` chunk per element (TLV parameter streams), then `MIXR`, `DRUM` and
`OTHR`. `MIXR` is a table of one 6-byte record per element and part —
`program, bank, volume, pan, reverb, chorus` — where program/bank is a plain
GM program with a bank MSB; the drum and percussion parts carry bank 120.
Event streams are flat runs of 3-byte `(delta, code, value)` frames at 96
ticks per quarter note — code `0x01-0x7f` is a note whose value is velocity
(0 = note off), `0xfc` ends the stream.

Each element's TLV `0x20` holds two bytes per track giving that track's
**stream index**, the `DRUM` ones first and then the `OTHR` ones. It has to be
read rather than predicted: classifying by part index gets the split right for
135 of the 235 factory rhythms and wrong for the other 100, which keep a drum
part — or the second copy of one inside an intro — over in `OTHR`. The table
is keyed by track *position*, not by code, since intro and ending elements
list the same code twice. TLV `0x21` is a parallel table of slot indices,
`0x7fff` marking the duplicated copies.

`ac7info` reports the stored meter and, independently, the bar length measured
from the event streams — if those two ever disagree, the file is inconsistent
and the keyboard will not play it the way the notes were written. The two are
complementary: bar length alone cannot tell 3/4 from 6/8, since both are 288
ticks per bar, and only the stored field separates them.

### Why conversion needs a template

`convert` does not synthesise an AC7 from nothing. It parses a rhythm from your
keyboard, keeps every `ELMT` and `MIXR` byte — so the tones, mixer settings and
chord-conversion tables that already work stay intact — and replaces only the
note data, patching each element's bar count to match the style. Each track
keeps its own setup frames (tone selection, bend), moved to tick 0.

Elements the style has no data for keep the template's own pattern; pass
`--clear-unused` to empty them instead. The name, tempo and time signature are
taken from the style; `--keep-tempo` and `--keep-meter` keep the template's.

Diffing a converted rhythm against its template is a good sanity check — it
should report only the name, tempo, meter and bar counts:

```sh
./y2c.py ac7diff MY_RHYTHM.AC7 PERSIAN.AC7
```

### Known gaps

- **Time signature — decoded.** See [Meter](#meter). Verified against three
  factory rhythms (4/4 `0x22`, 6/8 `0x33`, 3/4 `0x1a`); in each the decoded
  meter agrees with the bar length measured independently from the streams.
  An earlier two-sample reading of this field was wrong: 4/4 and 6/8 both
  satisfy `numerator == 2 * log2(denominator)`, which made the numerator look
  like a half-width field and odd numerators look unrepresentable. The waltz
  settled it.

- **Two slots go unused — and the manual says why.** Elements 6 and 11 are
  empty in all 235 rhythms of the CT-X3000 factory set *and* their `MIXR` rows
  sit at the file's default tone and volume while every used slot carries real
  values. The user's guide explains it: the instrument drives **one** intro and
  **one** ending, but **four** variations and **four** fill-ins. That is ten
  patterns in twelve slots, and the two spare ones are the second block's
  intro and ending. `ac7.UNUSED_ELEMENTS` records them.

  The same section gives the per-element bar limits: intro and ending 1-16,
  variation 1-16, **fill-in 1-2**. A fill longer than two bars is not
  representable.

- **Element roles.** The whole factory set agrees on the shape: bar counts run
  in two blocks of six, and elements 3, 4, 9 and 10 are one bar in every
  rhythm, which pins them as the fill-ins. Corroborated in detail by two
  independent factory rhythms: in both,
  elements 0 and 5 carry 12 tracks with every instrument role doubled while all
  the others carry 8, and elements 3, 4, 9 and 10 are always exactly one bar.
  That pins the grouping — 0/5 are the intro and ending, the one-bar elements
  are the fill-ins — and the 6/8 rhythm backs it up with a 7-bar element 0 and a
  6-bar element 5, lengths that only make sense for an intro and an ending.
  What is still assumed is the ordering *within* each group (which intro slot is
  Intro 1 rather than Intro 2). Verify by ear.
- **Doubled intro/ending tracks.** Intro and ending elements store two copies of
  each instrument part, presumably variants the keyboard picks between. The
  converter writes the style's notes into both copies.
- **Chord 5 exists, but nothing uses it.** The instrument has eight
  accompaniment parts, not seven: the mixer selects Percussion, Drums, Bass and
  **Chord 1 to Chord 5** (user's guide, EN-83), which is why `MIXR` carries
  eight rows per element. Part 7 is Chord 5, and it had no name here until the
  manual supplied one.

  It is still not somewhere to put Yamaha's Phrase 2, though. Across all 235
  factory rhythms, **no track at all** is coded for part 7 — the stream part
  codes run 0-6 plus `0x0f` for control — so `MIXR` reserves a row the
  rhythms never fill. Writing a stream there is untested and would be an
  experiment, not a fix. The accomp-channel arithmetic (`part = channel - 9`)
  cannot reach it either, since MIDI stops at channel 15.

  What is done instead is to re-home the part — see
  [Chord 5, and choosing a donor](#chord-5-and-choosing-a-donor) — which keeps
  4,179 notes across the 46 Iranian styles that used to be dropped. `convert`
  still reports anything it cannot place.

- **Bank 126 kits, and kit numbering across models.** 10.6% of the corpus's
  drum notes declare a kit the merged Yamaha table does not list (bank 126,
  programs 38/67/76/77/79); the nearest kit in the same bank is used and the
  substitution is reported. Kit numbering also drifts between models: program
  37 is `Arabic Kit 2` on the S650 and `ArabicKit1` on the SX920, and these
  styles were authored on a third. The family is right; the exact kit is an
  inference.

- **Collapse is unavoidable, not a bug.** Yamaha's Arabic Kit 2 holds 72
  distinct sounds and Casio's ARABIC SET holds 16, so four tablah
  articulations genuinely become one or two. That is the instrument, and it is
  why the residual mismatch after sound-based mapping does not go to zero.

## Layout

```
y2c.py            the command you type; a wrapper around y2c/cli.py
y2c_gui.py        the window, and `--selftest` for a frozen build
y2c.spec          PyInstaller recipe

y2c/cli.py        the commands themselves, so both front ends share them
y2c/smf.py        Standard MIDI File reader/writer
y2c/yamaha.py     .sty parser (sections, channels, CASM chord tables)
y2c/ir.py         neutral rhythm representation + Yamaha→Casio mapping
y2c/drummap.py    drum-note translation, including by-sound mapping
y2c/tonemap.py    which CT-X tone a declared Yamaha voice becomes
y2c/mega.py       flattening MegaVoice articulation layers
y2c/naming.py     stable 8-character file and 12-character display names
y2c/convert.py    pipeline, chord fix, part folding, preview MIDI
y2c/capture.py    learn the Casio kit from a recording of its accomp output
y2c/ac7.py        AC7 reader, writer and inspector

maps/             drum maps, and the generated tables (not committed)
samples/          where to put your own donor rhythm (none committed)
tools/            extracting the published tables, batch conversion,
                  and building the program
```
