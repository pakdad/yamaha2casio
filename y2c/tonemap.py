"""Choose a Casio tone for each melodic part, from the voice the style declares.

Until this module existed the converter did not map tones at all.
`ac7.apply_rhythm` keeps the template's MIXR verbatim, which is the right
default for a format we only partly understand -- but it means every
converted rhythm plays its TEMPLATE's tones.  A style's bass part asking for
SawBass came out as the donor's fingered bass, and a chord part asking for
Kanoun came out as Theater Organ, which is exactly the complaint that the
converted rhythms do not sound like the originals even when every note is in
the right place.

Two tables make the mapping possible, both read from the makers' own
published documents:

    maps/yamaha-voices.json     tools/yamahavoices.py, from a PSR Data List
    maps/ctx-tones.json         tools/ctxtones.py, from Casio's appendix

The matching is deliberately conservative, in two layers.

Layer 1, within the GM family.  Both makers lay their variations over the
128 General MIDI programs, so a voice's program already names the instrument
family and can be trusted on its own.  Among the Casio tones that share that
program, the one whose NAME best matches the Yamaha voice name wins; with no
match the plain `GM ...` tone at bank 0 is used.  This cannot put a part in
the wrong family, because the family is fixed before any name is compared.

Layer 2, across families, by an explicit table.  The two makers disagree
about where some instruments live: Yamaha files Kanoun under GM 108 (Koto)
and Casio files KANUN under GM 16 (Dulcimer), so layer 1 would answer "Koto"
and be confidently wrong.  Cross-family moves are therefore not inferred at
all -- they are listed, one line each, and each one has been checked against
both published lists.  That is a short table because it only needs the
instruments whose GM slot the makers chose differently, and it is where most
of this project's value sits: the CT-X5000 has SANTUR, KANUN, OUD, NEY, SAZ,
ZURNA, KEMENCHE, RABAB and ARABIC STRINGS, and the converter was reaching
none of them.
"""
from __future__ import annotations

import json
import os
import re

# Instruments the two makers file under different GM programs, so a
# family-restricted search cannot find them.  Left side: a word in the Yamaha
# voice name.  Right side: the Casio tone name to use.
#
# Checked pair by pair against both lists.  Where Casio offers numbered
# variants the first is taken -- SANTUR 1 over SANTUR 2 -- because the
# variants differ in brightness and decay, which is a judgement to make by
# ear and not from a name.
CROSS_FAMILY = {
    "kanoun": "KANUN 1",
    "kanun": "KANUN 1",
    "qanun": "KANUN 1",
    "santur": "SANTUR 1",
    "santoor": "SANTUR 1",
    "oud": "OUD 1",
    "ud": "OUD 1",
    "saz": "SAZ",
    "baglama": "SAZ",
    "ney": "NEY 1",
    "nay": "NEY 1",
    "zurna": "ZURNA",
    "mizmar": "ZURNA",
    "kemenche": "KEMENCHE",
    "kamancheh": "KEMENCHE",
    "rabab": "RABAB",
    "rebab": "RABAB",
    "bouzouki": "BOUZOUKI",
    "sitar": "SITAR 1",
    "tanpura": "TANPURA 1",
    "sarangi": "SARANGI 1",
    "sarod": "SAROD 1",
    "bansuri": "BANSURI",
    "shanai": "SHANAI",
    "shehnai": "SHANAI",
    "harmonium": "HARMONIUM 1",
    "duduk": "NEY 1",          # Casio has no duduk; a ney is the near reed
    "tar": "SAZ",              # nor a Persian tar; the saz is the near lute
    "setar": "SAZ",
    "tombak": "TABLA",
    "dumbek": "TABLA",
}

# Words that say how a tone was treated rather than what it is.  A match
# that rests only on these is not a match: "SoftSquare" and "SOFT STRINGS"
# share nothing but "soft", which says nothing about the instrument.
#
# They are still COMPARED -- inside a fixed GM family they are the only thing
# that tells STAGE EP from PHASE EP, and that is a useful distinction.  What
# they may not do is carry a match across families on their own, so a shared
# modifier counts towards the score while a shared instrument word is what
# makes the match admissible at all.
#
# Words that name a General MIDI voice are deliberately NOT here: clean,
# distortion, overdrive, mute, nylon, steel, picked, fretless, acoustic,
# electric, slap and jazz all distinguish one GM program from another, so
# they carry real instrument meaning.
MODIFIER = {
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
    "bright", "soft", "warm", "dark", "mellow", "slow", "fast", "big",
    "small", "little", "hard", "thin", "fat", "wide", "deep", "light",
    "stereo", "mono", "ambient", "dsp", "velo", "velocity", "octave",
    "modulated", "chorus", "phase", "phaser", "wah", "amp", "amped",
    "detuned", "vintage", "modern", "new", "old", "dynamic", "versatile",
    "premium", "ex", "gm", "x", "va", "dx", "sa", "s", "pro", "studio",
    "stage", "live", "cool", "sweet", "real", "natural", "solo", "section",
    "ensemble", "attack", "hyper", "super", "mega", "ultra", "and",
    "trem", "sweep", "pulse",
}

# Short forms Yamaha writes inside run-together voice names.
SHORT = {
    "gt": "guitar", "gtr": "guitar", "ep": "piano", "bs": "bass",
    "str": "strings", "strs": "strings", "brs": "brass", "orch": "orchestra",
    "acc": "accordion", "vib": "vibraphone", "perc": "percussion",
    "seq": "sequence", "sax": "saxophone", "syn": "synth", "pno": "piano",
    "elec": "electric", "e": "electric", "ac": "acoustic",
}

# Yamaha's MegaVoice bank.  Its programs are its own, not General MIDI's.
MEGAVOICE_MSB = 8
# Banks that are not pitched voices laid over the GM programs: MegaVoice and
# S.Art+ have their own program layouts, OrganFlutes is a drawbar engine, and
# 126/127 are the SFX and drum banks.  They are left out when the table is
# searched for a GM program by name, so "AcousticBass" cannot be answered
# with "AcousticKit".
NON_GM_BANKS = {8, 10, 12, 126, 127}

# Yamaha runs its voice names together, so the word boundaries have to be
# recovered: lower-to-upper, an acronym followed by a word, and letter to
# digit -- without that last one "SolidGuitar2" yields the token "guitar2",
# which matches no Casio name at all.
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
                    r"|(?<=[a-zA-Z])(?=\d)")


def tokens(name: str) -> list:
    """Split a voice or tone name into comparable words.

    Yamaha runs its names together -- "DynamicNylonGt", "60sCleanGuitar" --
    and Casio spaces and abbreviates its own -- "GM NYLON STR.GUITAR".  Both
    have to come apart the same way for a comparison to mean anything.
    """
    s = _CAMEL.sub(" ", name)
    s = re.sub(r"[^A-Za-z0-9]+", " ", s).lower()
    out = []
    for w in s.split():
        w = re.sub(r"^(\d+)s$", r"\1", w)            # "60s" -> "60"
        out.append(SHORT.get(w, w))
    return out


def meaningful(toks) -> set:
    """The tokens that name an instrument, modifiers dropped."""
    return {t for t in toks if t not in MODIFIER and not t.isdigit()}


def name_score(yamaha: str, casio: str):
    """(agreement 0..1, do they share an instrument word?) for two names."""
    ta, tb = set(tokens(yamaha)), set(tokens(casio))
    if not ta or not tb:
        return 0.0, False
    inter = ta & tb
    if not inter:
        return 0.0, False
    return len(inter) / len(ta | tb), bool(meaningful(inter))


class ToneMap:
    """Resolve a style's (msb, lsb, program) to a Casio (program, bank)."""

    def __init__(self, voices: dict, tones: dict):
        self.voices = voices
        self.tones = tones
        self.by_program = {}
        self.by_name = {}
        for num, t in sorted(tones.items(), key=lambda kv: int(kv[0])):
            if t["bank"] == 120:                     # a drum kit, not a tone
                continue
            self.by_program.setdefault(t["program"], []).append(t)
            self.by_name.setdefault(t["name"].upper(), t)

    def voice_name(self, msb, lsb, program):
        """The Yamaha voice's name, or None when the table does not list it.

        Bank 0/0 is the plain GM bank, which the Data List does not enumerate
        because the voice is simply General MIDI's; and a style authored on
        one model can name an LSB variation a later model dropped.  Both end
        up here, and both are answered by the program alone, which is right:
        the program IS the instrument and only the variation is unknown.
        """
        v = self.voices.get(f"{msb}/{lsb}/{program}")
        if v:
            return v["name"]
        # Same program in any other bank of the same MSB: a sibling variation,
        # whose name is a far better clue than nothing.
        for key, v in self.voices.items():
            m, l, p = key.split("/")
            if int(p) == program and int(m) == msb:
                return v["name"]
        return None

    def gm_tone(self, program):
        """Casio's plain GM tone for a program -- the always-safe answer."""
        for t in self.by_program.get(program, []):
            if t["bank"] == 0:
                return t
        pool = self.by_program.get(program)
        return pool[0] if pool else None

    def gm_program_of(self, want):
        """The GM program of the regular Yamaha voice that `want` names.

        This is how a MegaVoice gets a family.  A MegaVoice's own program is
        its bank's, not General MIDI's -- MegaVoice 17 is an electric bass
        where GM 17 is a percussive organ -- so asking Casio for program 17
        put the corpus's most-used bass part, 91 of them, on GM ORGAN 2.

        Yamaha's own catalogue answers it: the regular banks lie over the GM
        programs, they name the same instruments in the same words, and the
        best-matching regular voice therefore carries the program the
        MegaVoice means.  NylonGuitar resolves through NylonGuitarSlide to
        24, ElectricBass through ElectricBass to 33, SolidGuitar2 through
        CleanSolidGuitar2 to 27.  A shared instrument word is required, so a
        shared "vintage" or "soft" cannot decide it.
        """
        best, best_s = None, 0.0
        for key, v in self.voices.items():
            msb, _, prog = (int(x) for x in key.split("/"))
            if msb in NON_GM_BANKS:
                continue
            sc, real = name_score(want, v["name"])
            if real and sc > best_s:
                best, best_s = prog, sc
        return best, best_s

    def choose(self, msb, lsb, program, role=None):
        """(program, bank, casio name, yamaha name, how) for one part."""
        want = self.voice_name(msb, lsb, program)
        # Layer 2 first: a named cross-family instrument beats the GM slot,
        # because the makers' slots for it disagree.
        if want:
            for word in meaningful(tokens(want)):
                target = CROSS_FAMILY.get(word)
                if target and target in self.by_name:
                    t = self.by_name[target]
                    return t["program"], t["bank"], t["name"], want, "named"
        # A MegaVoice's program is not a GM program -- MegaVoice 17 is an
        # electric bass where GM 17 is a percussive organ -- so the family
        # cannot be read off it and the name has to decide alone.  Sending
        # these through layer 1 put the corpus's most-used bass, 91 parts of
        # it, on GM ORGAN 2.
        how = "family"
        if msb == MEGAVOICE_MSB and want:
            found, _ = self.gm_program_of(want)
            if found is not None:
                program, how = found, "mega"
        # Layer 1: stay in the GM family and pick the closest name in it.
        best, best_s = None, 0.0
        if want:
            for t in self.by_program.get(program, []):
                sc, _ = name_score(want, t["name"])
                if sc > best_s:
                    best, best_s = t, sc
        if best is not None:
            return (best["program"], best["bank"], best["name"], want,
                    f"{how} {best_s:.2f}")
        t = self.gm_tone(program)
        if t is None:
            return None
        return t["program"], t["bank"], t["name"], want, how + " gm"


def load(root=None):
    """Read both published tables and return a ToneMap, or None if absent."""
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    vp = os.path.join(root, "maps", "yamaha-voices.json")
    tp = os.path.join(root, "maps", "ctx-tones.json")
    if not (os.path.exists(vp) and os.path.exists(tp)):
        return None
    with open(vp, encoding="utf-8") as f:
        voices = json.load(f)
    with open(tp, encoding="utf-8") as f:
        tones = json.load(f)
    return ToneMap(voices, tones)
