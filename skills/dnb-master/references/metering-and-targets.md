# Metering and Targets

## Contents

- Gain staging
- Monitoring discipline
- Loudness targets
- Limiter strategy
- What Live can and cannot measure
- Reference A/B
- QC checklist

## Gain Staging

Ableton Live uses a floating-point mix engine, so internal tracks can exceed 0 dBFS without immediate internal clipping. That does not make reckless gain staging acceptable. Output and export are where clipping becomes a real delivery problem.

Working rules:
- keep device input and output levels sensible so dynamics tools behave predictably
- watch saturation stages closely
- treat more than about 6 dB of gain reduction as a warning that the master is being overworked
- for submitted stereo premasters, prefer no overs and useful headroom below full scale; about `-3 dBFS` maximum peak is a practical default when the user can re-export

## Monitoring Discipline

Full K-System calibration is not required for this skill, but use the practical habit behind it: monitor level should be repeatable enough that loudness decisions mean something.

Working rules:
- choose a comfortable fixed monitor level before judging loudness
- level-match reference A/B comparisons before judging tone, width, punch, or loudness
- do not keep turning the monitor down as limiting gets heavier; that hides fatigue
- judge by ear and meters together, not by LUFS alone
- if the user wants aggressive loudness, compare a cleaner version and a louder version at matched playback level
- use alternate playback checks as diagnostics, not as the main tonal target

## Loudness Targets

There is no single "professional LUFS" target. Pick a delivery profile and explain the tradeoff.

### Streaming-safe default

Use when the user wants clean platform delivery.

Targets:
- about -14 LUFS-I
- <= -1 dBTP

Reasoning:
- this aligns with common Spotify normalization guidance
- at louder-than--14 masters, prefer more headroom, not less
- Apple playback guidance supports leaving at least 1 dB of headroom

### Louder-than-normalized

Use when the user explicitly wants a more aggressive result.

Targets:
- louder than -14 LUFS-I only if requested
- prefer <= -2 dBTP when pushing louder than normalized

Warnings:
- louder is a creative choice with real costs
- watch for distortion, transient loss, and stereo collapse
- client-demanded extreme loudness can reach around -8 LUFS-I, but that is not a universal best practice
- stop pushing if added loudness costs snare impact, kick/sub clarity, vocal size, stereo stability, or codec/radio resilience
- if the loud version only wins when unmatched, report that clearly and recommend the cleaner version

### General professional context

Useful framing for the user:
- many popular-music masters sit roughly in the -14 to -16 LUFS range
- some do not exceed -12 LUFS
- the right answer depends on genre, delivery, and intent

## Limiter Strategy

Limiter is the final loudness gate and final safety stage.

Default clean setup:
- True Peak on
- Ceiling -1.0 dB
- Lookahead 6 ms
- Auto Release on
- Link high or 100% unless there is a specific reason not to

Important Limiter behaviors:
- 1.5 ms, 3 ms, and 6 ms are the meaningful lookahead choices
- shorter lookahead can increase distortion, especially on bass-heavy material
- True Peak mode is the safest choice for streaming-safe work
- high Link keeps stereo movement more stable

Two-stage limiting idea:
- shave tiny peaks with subtle saturation or soft clipping before the Limiter
- let the Limiter do less work

Warnings:
- Glue Soft Clip is not a transparent limiter
- do not add gain after the Limiter

## What Live Can and Cannot Measure

Live stock tools give you:
- peak and RMS metering
- Spectrum for frequency balance inspection
- Limiter gain reduction feedback

Live stock tools do not give you a fully compliant LUFS/LRA/true-peak meter.

If no analyzer exists in the MCP stack:
1. Apply the chain in Live.
2. Render a test master, usually 32-bit float with Normalize off.
3. Measure LUFS-I, short-term loudness, LRA, and dBTP offline.
4. Iterate Limiter drive, threshold, and upstream dynamics.

Never describe RMS as a substitute for LUFS. It is only a rough loudness clue.

## Reference A/B

Reference comparisons only work when the level is matched.

Practical workflow:
- keep the reference routed to Main, not PREMASTER
- use Utility on the reference track to gain match by ear and by peak/RMS clues
- compare meaningful DnB sections: intro, build, drop, breakdown, final drop
- use Spectrum to compare broad tonal tilt
- do mono and Bass Mono checks to confirm the drop keeps weight and the vocal still reads
- check whether the master still communicates through midrange-limited playback, not just full-range monitors
- for EPs and albums, compare track-to-track energy in sequence, not only each song against an external reference

## QC Checklist

### Signal integrity

- no clip indicators on Main during the loudest section
- Limiter is the last processing device on PREMASTER
- no gain-adding devices after Limiter
- True Peak is enabled for streaming-safe work

### Loudness and dynamics

- LUFS-I, short-term loudness, LRA, and dBTP are measured when possible
- streaming-safe work lands around -14 LUFS-I and <= -1 dBTP
- louder-than-normalized work preserves extra true-peak margin, preferably <= -2 dBTP
- if more loudness requires obvious loss of punch or vocal size, back off

### Translation

- mono compatibility holds
- Bass Mono audition keeps low-end weight intact
- small-speaker or phone-style check still gives you readable vocal, snare intent, bass rhythm, and main hook
- Spectrum does not show uncontrolled sub-20 Hz buildup
- Spectrum does not show sustained harsh spikes dominating the upper mids or top end
- the clean and loud variants were compared at matched playback level when aggressive loudness was requested
- for EPs or albums, track transitions, fades, and relative loudness feel intentional

### Vocal-forward QC

- after any vocal gain lift, sample the vocal track and the master, not just the master alone
- stop if any sampled channel reports clipping
- stop if the sampled master peak gets too close to full scale, about above `-0.5 dBFS`
- if the vocal gets louder but feels farther away, reduce wet effects before adding more level
