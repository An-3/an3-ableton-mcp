# Presets

## Contents

- How to use the presets
- STREAM_SAFE_TRANSPARENT
- STREAM_LOUD_CONTROLLED
- CLUB_IMPACT
- SUB_TIGHT
- VOCAL_FORWARD
- HARSH_SOFTENER
- WIDE_TOPS
- MINIMAL_TOUCH
- AI_MINIMAL_REPAIR

## How to Use the Presets

All presets assume they live on PREMASTER. These are starting points, not fixed formulas. Final settings must be judged by ear, by references, and by LUFS/true-peak measurement when available.

Run the source-fitness gate before preset selection:
- if the source is clipped, normalized into full-scale peaks, lossy with a better file available, or missing needed handles, choose `revision-needed` before a preset
- if the source is already loud or hard-limited but usable, choose `MINIMAL_TOUCH` or `AI_MINIMAL_REPAIR`
- if AI artifacts are structural, choose `regenerate-first`
- if the source is fit to master, choose one of the presets below

Common defaults across presets:
- Bass Mono usually starts at 120 Hz unless the preset says otherwise
- HPF cleanup usually lives around 20-30 Hz
- Limiter is last
- True Peak is on for streaming-safe work

## STREAM_SAFE_TRANSPARENT

Use when:
- the goal is clean streaming delivery
- the mix already feels balanced
- the user wants punch without obvious mastering color

Device order:
1. Utility
2. EQ Eight
3. Glue Compressor
4. Saturator
5. Limiter

Starting settings:
- Utility: Bass Mono on at 120 Hz, Width 100%, Gain 0 dB
- EQ Eight: HPF at 20-30 Hz, 12-24 dB/oct
- Glue Compressor: Ratio 2:1, Attack 10 ms, Release Auto, target 1-2 dB GR
- Saturator: Drive +0.5 to +1.5 dB, Soft Clip off or barely used
- Limiter: True Peak on, Lookahead 6 ms, Ceiling -1.0 dB, Auto Release on

Do not use when:
- the user clearly wants louder competitive loudness
- the sub is unstable enough to require dedicated multiband control
- the top end needs obvious stereo enhancement

## STREAM_LOUD_CONTROLLED

Use when:
- the mix is solid but needs more density
- the user wants it louder than neutral streaming-safe without obvious pumping

Device order:
1. Utility
2. EQ Eight
3. Compressor
4. Multiband Dynamics
5. Limiter

Starting settings:
- Compressor: Attack 10-30 ms, Release Auto, target 1-3 dB GR
- Multiband Dynamics: Low band mild downward compression, roughly 1.2:1 to 1.6:1 feel, plus gentle top containment if needed
- Limiter: True Peak on, Ceiling -1.0 dB, drive carefully to target

Do not use when:
- the mix already sounds squeezed
- the user mainly wants more punch rather than density
- one specific issue would be better served by a more focused preset

## CLUB_IMPACT

Use when:
- the priority is punch-preserving club energy
- the user wants impact without flattening drums

Device order:
1. Utility
2. EQ Eight
3. Glue Compressor
4. Saturator
5. Limiter

Starting settings:
- Glue Compressor: very light glue, around 0.5-1.5 dB GR
- Glue Soft Clip: off
- Saturator: Drive +1 to +3 dB with Soft Clip only as a light pre-limiter safety stage
- Limiter: Ceiling around -0.8 to -1.0 dB, True Peak optional depending on delivery

Do not use when:
- the delivery is strict streaming-safe and codec cleanliness is the top priority
- the mix is already bright or edgy enough that added saturation will harden it

## SUB_TIGHT

Use when:
- kick and sub intermittently overload the limiter
- low end smears the vocal or the drop loses definition

Device order:
1. Utility
2. EQ Eight
3. Multiband Dynamics
4. Saturator
5. Limiter

Starting settings:
- Utility: Bass Mono on somewhere between 90 and 150 Hz
- EQ Eight: HPF around 25 Hz, optional low shelf -0.5 to -1 dB at 80-120 Hz if bloated
- Multiband Dynamics: low band threshold set so only sub peaks reduce, target about 1-3 dB GR
- Saturator: very light drive if extra density is needed
- Limiter: True Peak on, Lookahead 6 ms

Do not use when:
- the low end is already stable and the real problem is harshness or stereo width
- the user wants the most minimal-touch chain possible

## VOCAL_FORWARD

Use when:
- the vocal loses intelligibility in the drop
- the center feels crowded and the words stop reading

Track-first rule:
- on multitrack mixes, start with track-level vocal gain and ambience reduction before touching the master bus
- reduce vocal insert reverb `Dry/Wet` by about `2-5` percentage points first
- then raise the vocal track by about `0.01-0.03` normalized if needed
- only use master-bus `VOCAL_FORWARD` EQ or compression after those moves are still insufficient

Device order:
1. Utility
2. EQ Eight in M/S mode
3. Glue Compressor
4. Limiter

Starting settings:
- track-level first pass: less vocal reverb, then a small vocal gain lift
- EQ Eight: mid bell +0.5 to +1.0 dB around 2-5 kHz
- EQ Eight optional: gentle side dip in low-mids if center vocal needs space
- Glue Compressor: around 1-2 dB GR
- Limiter: True Peak on, Ceiling -1 dB

Do not use when:
- the vocal is already forward and the problem is top-end harshness
- the center is fine but the low end is overrunning the master
- the track-level vocal revision loop has not been attempted yet on a multitrack mix

## HARSH_SOFTENER

Use when:
- hats, sibilance, or upper mids get brittle when loud
- bright material falls apart under limiting

Device order:
1. Utility
2. EQ Eight
3. Multiband Dynamics
4. Limiter

Starting settings:
- EQ Eight: wide cut of about -0.5 to -1.5 dB in the 3-6 kHz region
- Multiband Dynamics: mild high-band control
- Limiter: True Peak on, Release Auto or slower behavior

Do not use when:
- the master is already dark or dull
- the real issue is low-end overload rather than top-end bite

## WIDE_TOPS

Use when:
- the master feels narrow or dull
- the low end is already solid and centered

Device order:
1. Utility
2. EQ Eight in M/S mode
3. Saturator
4. Limiter

Starting settings:
- Utility: Bass Mono on
- EQ Eight M/S: side high-shelf +0.5 to +1 dB at 10-16 kHz
- Keep side lows cut or limited
- Saturator: apply only to the high-focused content if possible using color filtering
- Limiter: Link 100% for image stability

Do not use when:
- mono compatibility is already fragile
- the brightness problem is harshness, not lack of width

## MINIMAL_TOUCH

Use when:
- the mix is already excellent
- the user wants a safety-first master with the fewest possible moves
- the source is already loud or lightly mastered and should not be pushed

Device order:
1. Utility
2. EQ Eight
3. Limiter

Starting settings:
- EQ Eight: HPF around 20-25 Hz only
- Limiter: True Peak on, Ceiling -1 dB, less than 2 dB GR

Do not use when:
- the mix clearly needs tonal shaping, low-end control, or vocal help
- the user explicitly wants a louder or more colored result
- the source is damaged enough that `revision-needed` or `regenerate-first` is more honest

## AI_MINIMAL_REPAIR

Use when:
- the source is an AI-generated stereo render or AI-derived stem
- there are resonance spikes, brittle highs, or already-baked loudness
- the goal is salvage and containment, not a second obvious master

Device order:
1. Utility
2. EQ Eight
3. Multiband Dynamics
4. Limiter

Starting settings:
- Utility: Bass Mono on if the low end is unstable, usually starting around 120 Hz
- EQ Eight: broad cleanup first, with a narrow notch only for a stable obvious spike
- Multiband Dynamics: mild corrective high-band control, not aggressive tone reshaping
- Limiter: True Peak on when available, safety ceiling, minimal extra drive

Do not use when:
- the source is a healthy human-made premaster
- regeneration is clearly the better answer
- the user mainly wants a louder competitive master from a proper mix
