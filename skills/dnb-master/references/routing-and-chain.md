# Routing and Chain

## Contents

- Executive rationale
- Scope and assumptions
- PREMASTER architecture
- Baseline mastering chain
- Level-matched bypass checks
- Macrodynamics before compression
- Compression decision rules
- Stereo imaging and M/S
- Tonal moves for DnB vocals and drums
- Transient preservation
- Saturation guidance

## Executive Rationale

Professional DnB mastering is mostly about small intentional moves that keep the mix translating everywhere while preserving punch, transient integrity, center strength, musical contrast, and stable sub-bass. The biggest risks are flattening the snare, destabilizing the stereo image, burying the vocal midrange, and letting the low end drive the limiter into audible distortion.

Keep mastering separate from mixing. If the mix has structural problems, do not try to hide them with heavy master-bus processing.

## Scope and Assumptions

- Assume Ableton Live 12 terminology by default, while tolerating minor version naming differences.
- "Stock devices only" means native Ableton devices with no third-party plugins.
- Device availability can vary by Live edition, so feature-detect when automating and fall back gracefully when a device or option is unavailable.

## PREMASTER Architecture

Use a dedicated PREMASTER track whenever routing control exists:

1. Route all mix tracks to PREMASTER.
2. Route PREMASTER to Main.
3. Route reference track(s) directly to Main, not to PREMASTER.
4. Keep Main for metering and output safety, not tone-shaping.

Why this matters:
- reference A/B stays honest because the reference does not hit your mastering chain
- PREMASTER keeps the mastering chain isolated from the final output bus
- clipping risk in Live matters most at outputs and export, not inside the floating-point mix engine

## Baseline Mastering Chain

Default order on PREMASTER:

1. Utility
2. EQ Eight
3. Glue Compressor or Compressor
4. Saturator
5. Multiband Dynamics when needed
6. EQ Eight in M/S mode or Utility width adjustment when needed
7. Limiter

Use the chain with a "remove problems -> control dynamics -> add controlled color -> finalize loudness and true peak" mindset.

Hard rules:
- Limiter stays last.
- Do not add gain after Limiter.
- Bass Mono is the default low-end stability tool.
- Heavy gain reduction is a warning sign, not a success metric.
- Level-match bypass checks after major stages so louder is not mistaken for better.

## Level-Matched Bypass Checks

After each meaningful chain stage, compare processed and bypassed signal at matched apparent level:
- EQ Eight: confirm tone improved, not just got brighter or louder
- Compressor or Glue Compressor: confirm groove and transient impact still feel alive
- Saturator: confirm density increased without hardening hats, vocal sibilance, or snare crack
- Multiband Dynamics: confirm the target band improved without making the whole master processed
- Limiter: confirm the loudness gain is worth the loss, if any, in punch, vocal size, stereo image, and depth

If a move only sounds better because it is louder, back it off or remove it.

## Macrodynamics Before Compression

Do not use compression as the first answer to every level problem. For musical section balance, try clip gain, track gain, or automation-style moves first.

Use macrodynamic moves when:
- an intro or breakdown disappears after a louder section
- a drop needs more impact from contrast rather than more limiter drive
- a chorus, second drop, or final drop needs a small level relationship adjustment
- an EP or album needs track-to-track continuity

Guidelines:
- keep moves small and musical, often fractions of a dB to about 1 dB
- move level during natural transition points when possible
- avoid fighting intentional crescendos or energy builds
- for multitrack vocal issues, prefer the Vocal Revision Loop before master-bus compression

## Compression Decision Rules

Prefer single-band compression when you want glue without changing the internal mix balance:
- preserves groove better
- avoids crossover artifacts
- reduces the chance of broadband pumping from sub energy

Use Glue Compressor or Compressor when:
- the master only needs 1-3 dB of control
- you need light bus cohesion
- the snare and kick must stay lively
- macrodynamic gain moves are not enough or are not the right tool

Useful starting points:
- attack 10-50 ms to let peaks through
- release auto when unsure
- keep gain reduction around 1-2 dB, or 3 dB at the upper end for denser masters

Use Multiband Dynamics only when a specific band is the problem:
- sub bursts are overrunning the limiter
- upper mids or highs become brittle when loud
- one region is blocking translation

Multiband guideline:
- keep it corrective and minimal
- often 0.5-2 dB GR is enough on the offending band
- if the whole master starts sounding "processed", back off

## Stereo Imaging and M/S

Use M/S as a scalpel, not as default decoration.

Stock M/S tools:
- EQ Eight supports Stereo, L/R, and M/S modes
- Utility supports width control, mono checks, and Bass Mono

Core DnB image rules:
- keep sub, kick, snare center weight, and lead vocal center-stable
- keep low frequencies mono, typically 90-150 Hz, with 120 Hz as the neutral first setting
- add width from upper frequencies first, not from the whole spectrum
- keep limiter link high when preserving image stability matters
- never widen to compensate for dull tone or low loudness
- after any M/S move, check mono and confirm the vocal, snare, and bass rhythm still read

Safe widening move:
- EQ Eight in M/S mode
- small side high-shelf lift of about +0.5 to +1 dB in the 10-16 kHz region
- do not widen lows

## Tonal Moves for DnB Vocals and Drums

Mastering EQ should compensate for broad systematic issues, not rescue a broken mix.

The midrange is the translation anchor. In DnB, the vocal, snare body/crack, bass rhythm harmonics, and main synth identity all depend on it. Do not scoop or brighten so much that small speakers lose the song.

Useful vocal-oriented frequency map:
- below 100 Hz: rumble
- 200-500 Hz: muddiness
- 3-5 kHz: presence
- 10-15 kHz: air

Typical mastering-scale moves:
- subsonic cleanup: HPF around 20-30 Hz
- muddy mix: wide cut of about -0.5 to -1.5 dB in 200-500 Hz
- buried vocal: small mid boost in 3-5 kHz, often +0.5 to +1 dB
- lacking air: very gentle shelf in 10-15 kHz

Warnings:
- keep presence boosts tiny because that area also carries snare crack and hat bite
- avoid narrow surgical cuts unless the issue is clearly mix-wide
- if a broad EQ move larger than about 2 dB seems necessary, consider whether the mix needs revision
- do not EQ around a bad monitoring problem; use references, Spectrum, mono, and small-speaker checks before committing
- if adding top end makes the master exciting on one system but brittle elsewhere, undo it and solve the real balance issue

## Transient Preservation

DnB depends on transient integrity. Fast aggressive compression can remove life from the master.

Safe approach:
- use compressor attack times in the 10-50 ms range when possible
- let the front edge of the kick and snare survive
- keep limiter lookahead longer when low-end distortion appears

Drum Buss can shape transients, but on a full master it is risky:
- only use it if the user explicitly wants that color
- keep moves very small
- monitor for low-end exaggeration and over-thickened sustain

## Saturation Guidance

Subtle saturation can increase density and perceived loudness without as much limiting, but it should stay quiet and controlled.

Preferred stock approach:
- use Saturator at low drive, often +0.5 to +2 dB
- use color filtering to avoid over-saturating the sub
- let the final Limiter True Peak stage handle final containment

Other color options:
- Limiter Soft Clip can add punch near the ceiling, but it is not the default clean path
- Drum Buss distortion modes are usually too characterful for transparent mastering

Avoid:
- aggressive clipping as a substitute for judgment
- heavy distortion on the full master unless the user explicitly wants a creative effect
