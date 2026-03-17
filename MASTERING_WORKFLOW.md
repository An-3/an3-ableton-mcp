# Mastering Workflow

This workflow captures the current Ableton MCP mastering/export path for vocal-led multitrack mixes in Ableton Live.

## Initial Master Pass

Start with a conservative transparent chain on the master bus:

- `Utility -> EQ Eight -> Glue Compressor -> Saturator -> Limiter`
- keep lows mono, usually with Bass Mono around `120 Hz`
- use only gentle sub cleanup, usually around `20-30 Hz`
- keep limiter last with a streaming-safe ceiling around `-1.0 dB`
- do not chase loudness until the balance already feels right

For vocal-led material, the default first pass should stay clean and restrained. Do not push the whole master harder just because the vocal feels a little smaller after the first pass.

## Vocal Feedback Loop

If the user says the vocal fell into the background after mastering, use this order:

1. Identify the lead vocal track.
2. Reduce vocal ambience first, usually by lowering vocal insert reverb `Dry/Wet` by about `2-5` percentage points.
3. If the vocal still sits back, raise the vocal track by about `0.01-0.03` normalized.
4. Re-check the vocal track and the master with meter sampling.
5. Only if the vocal still does not read clearly, escalate to tonal help such as a small `2-5 kHz` presence lift or a competing-mid reduction.

This is intentionally track-first. Do not default to master-bus `VOCAL_FORWARD` EQ or extra limiting before trying the vocal track itself.

## Overload Check

After any vocal-forward revision:

- sample the vocal track and the master
- sample the main competing channels in the section being judged, typically `Drums`, `Bass`, `Synth`, and `Percussion`
- stop and back off if any sampled channel reports clipping
- stop and back off if the sampled master peak gets too close to full scale, about above `-0.5 dBFS`

If the vocal gets louder but farther away, reduce wet effects before adding more vocal level.

## Export Validation

Before export:

- confirm Arrangement playback is clean and `arrangement_export_ready` is true
- export a WAV with `Normalize Off`
- validate the written file on disk, not just the Live meter

Minimum validation checks:

- duration is plausible for the rendered arrangement
- the file is not silent
- first audible audio appears where expected
- master peak remains below full scale

Current macOS save-panel quirk:

- the save dialog may write the file as `.wav.wav`
- normalize the final filename after render if needed, then validate the normalized path that will be handed to the user
