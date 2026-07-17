# Export and Troubleshooting

## Contents

- Render defaults
- Deliverable formats
- Dither rules
- File prep and delivery checks
- Jitter clarification
- Troubleshooting

## Render Defaults

Core render rules:
- Normalize off
- use the project sample rate unless there is a delivery reason to change it
- remember that downsampling is not neutral, even when Ableton uses a high-quality resampler
- do not upsample as a magic improvement; it does not recreate information or guarantee better sound

If exporting below the project sample rate:
- do final sample-rate conversion only when delivery requires it
- do not change sample rate casually during iterative mastering unless the delivery requires it
- render test passes at the project/native sample rate when possible, then convert final deliverables as the last format step

PCM deliverables can be WAV, AIFF, or FLAC, but WAV is the default safest expectation unless the user requests otherwise.

## Deliverable Formats

### Working master and iteration renders

Use for test passes and analyzer loops:
- WAV
- 32-bit float
- project sample rate
- Normalize off
- no dither

### Distribution master

Use for general release delivery:
- WAV
- 24-bit
- project or native sample rate
- Normalize off
- dither only if actually reducing from a higher bit depth

### 16-bit deliverable

Use only when specifically needed:
- WAV
- 16-bit
- appropriate dither
- dither applied once

## Dither Rules

Use dither only at the final integer bit-depth reduction stage. Do not dither 32-bit float test renders.

Safe defaults:
- Triangular is the safest all-purpose option when more processing may still happen
- Rectangular has less noise but more quantization error
- POW-r modes are for final output only, not for files that will still be processed

Non-negotiable rules:
- apply dither once, at the final bit-depth reduction stage
- avoid repeated 16-bit dithering
- do not dither if exporting 32-bit float for analysis, archive, or continued processing
- if both sample-rate conversion and bit-depth reduction are required, do sample-rate conversion before final dither

## File Prep and Delivery Checks

For sources:
- prefer earliest-generation WAV, AIFF, or BWF
- prefer 24-bit or 32-bit float
- avoid MP3, AAC, or other lossy files unless the job is salvage
- ask for a lossless re-export when available
- keep source files, references, and deliverables clearly separated

For project and file organization:
- use meaningful filenames and version labels
- include mix notes or requested references when available
- for EPs or albums, keep track order, titles, and intended transitions explicit
- preserve handles, breaths, reverb tails, and unfaded endings when mastering may need to shape fades
- label exports as working render, distribution master, 16-bit deliverable, instrumental, clean, or revision as appropriate

## Jitter Clarification

Do not blame offline Ableton renders, EQ, compression, or file export tone on jitter. Offline rendering and most digital processors operate on data, not a playback clock.

Operational rule:
- jitter is mainly a conversion or monitoring-chain concern
- if a rendered file sounds wrong, investigate source quality, clipping, sample-rate conversion, dither, limiter settings, codec conversion, or monitoring translation first
- do not recommend jitter-reduction hardware as a fix for an offline master file

## Troubleshooting

### Limiter sounds crunchy only in drops

Likely causes:
- sub peaks are overrunning the limiter
- lookahead is too short
- overall limiter drive is too aggressive

Fixes:
- move Lookahead to 6 ms
- reduce pre-limiter drive
- tighten the low end with Bass Mono
- use low-band Multiband Dynamics lightly to contain sub peaks

### Vocal gets smaller when pushing for loudness

Likely causes:
- too much broadband compression
- limiter gain reduction is flattening the center
- upper-band control is clamping consonants

Fixes:
- reduce limiter and compressor workload
- switch to M/S-aware vocal help
- add a small mid presence lift around 3-5 kHz
- ease off multiband or high-band compression

### Vocal feels farther back after mastering

Likely causes:
- the master is denser, but the vocal ambience is still too wet
- the vocal level did not come up with the new density
- the fix was attempted on the master bus before the vocal track itself

Fixes:
- reduce vocal insert reverb `Dry/Wet` first
- then add a small vocal gain lift
- meter-check the vocal track and the master before export
- only then escalate to master-bus `VOCAL_FORWARD` EQ if the words still do not read

### Stereo image wobbles or collapses

Likely causes:
- limiter stereo behavior is too independent
- M/S processing is too aggressive
- widening is touching the low end

Fixes:
- keep Limiter Link high, near 100%
- reduce aggressive M/S limiting or widening
- keep lows centered and mono

### Master clips after upload or encoding

Likely causes:
- not enough true-peak margin
- sample peaks looked safe, but inter-sample peaks were not

Fixes:
- target <= -1 dBTP for streaming-safe work
- prefer <= -2 dBTP when pushing louder than normalized
- keep Limiter in True Peak mode
- leave at least about 1 dB of playback headroom

### Reference A/B feels misleading

Likely causes:
- level mismatch
- the reference is accidentally routed through the mastering chain

Fixes:
- bypass PREMASTER for the reference
- gain match the reference with Utility before judging tone and punch

### Source is clipped, normalized, or lossy

Likely causes:
- the premaster was normalized before mastering
- a limiter or clipper was printed onto the source
- the only available file is MP3, AAC, or a platform download

Fixes:
- request a lossless WAV, AIFF, or BWF export when possible
- request no normalize and no safety limiter unless it is intentional
- prefer a new export with peaks safely below full scale, about `-3 dBFS` as a practical default
- if no better source exists, use `minimal-touch` and report it as salvage

### User asks to fix an offline render with jitter tools

Likely causes:
- confusion between playback conversion jitter and rendered audio data
- a real issue exists elsewhere in the export or mastering chain

Fixes:
- explain that jitter tools will not repair an offline rendered file
- check clipping, limiter gain reduction, sample-rate conversion, dither, and codec conversion
- compare the rendered file against the Live playback at matched level

### Export structure does not match the Arrangement

Likely causes:
- Session clips were launched for metering or auditioning
- the set was exported before Back to Arrangement was restored
- the render followed Session override instead of the Arrangement timeline

Fixes:
- restore Arrangement playback before export
- confirm Arrangement clips are no longer gray
- if the MCP surface supports it, run the export-readiness verification step before rendering
- if verification is unavailable, do the Back to Arrangement step manually and only then export
