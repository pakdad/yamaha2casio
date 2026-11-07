#!/bin/bash
# Record the keyboard: MIDI and line-in audio over one aligned window.
#
#     tools/capture.sh SECONDS LABEL [CARD]
#
# Writes LABEL/audio.wav and LABEL/midi.txt under $Y2C_CAPTURE_DIR (default
# ./captures).  Both streams start together: an earlier version treated
# `timeout`'s exit code 124 as a failure and retried, which recorded the two
# streams over two different windows and made them incomparable.
#
# The MIDI side is near useless on a CT-X5000 -- the instrument transmits what
# the keys play but not its own auto-accompaniment, so a running rhythm shows
# up as Active Sensing and nothing else.  It is still captured, because it
# costs nothing and proves the link is alive while a take is being recorded.
#
# Set the input level before trusting a take: the card's line capture gain
# wants to leave 6-12 dB of headroom.  Clipping flattens the transients that
# onset detection and spectral classification both depend on.
set -u
SECS=${1:-45}
LABEL=${2:-take}
CARD=${3:-2}
OUT="${Y2C_CAPTURE_DIR:-captures}/$LABEL"
mkdir -p "$OUT"

# aseqdump prints events in order but with NO timestamps, which is useless
# for anything rhythmic -- a hand-played take came back as 133 notes with no
# way to know where any of them fell.  arecordmidi writes a real SMF with
# timing and velocity, so it is the one that matters; aseqdump is kept only
# because its output proves the link was alive.  SIGINT, not SIGTERM: that is
# what arecordmidi installs a handler for, and it finalises the file on it.
timeout -s INT "$SECS" arecordmidi -p "CASIO USB-MIDI" -b 480 \
    "$OUT/midi.mid" 2> "$OUT/arecordmidi.log" &
RPID=$!
timeout "$SECS" aseqdump -p "CASIO USB-MIDI" > "$OUT/midi.txt" 2>&1 &
MPID=$!
timeout "$SECS" arecord -D "hw:$CARD,0" -f S16_LE -r 48000 -c 2 -t wav \
    "$OUT/audio.wav" 2> "$OUT/arecord.log"
rc=$?
if [ $rc -ne 0 ] && [ $rc -ne 124 ]; then
    echo "arecord failed (exit $rc):" >&2
    tail -3 "$OUT/arecord.log" >&2
fi
wait $MPID 2>/dev/null
wait $RPID 2>/dev/null

echo "== $LABEL =="
notes=$(grep -c 'Note on' "$OUT/midi.txt" 2>/dev/null) || notes=0
sens=$(grep -c 'Active Sensing' "$OUT/midi.txt" 2>/dev/null) || sens=0
echo "midi : $notes note-ons, $sens active-sensing"
if [ -s "$OUT/midi.mid" ]; then
    echo "smf  : $OUT/midi.mid ($(stat -c%s "$OUT/midi.mid") bytes, timestamped)"
else
    echo "smf  : NOT WRITTEN -- see $OUT/arecordmidi.log" >&2
fi
if [ "$notes" -gt 0 ]; then
    grep -E 'Note (on|off)' "$OUT/midi.txt" \
      | sed -E 's/.*Note (on|off) +([0-9]+),.*/       ch \2/' | sort | uniq -c
fi
echo "audio: $OUT/audio.wav"
