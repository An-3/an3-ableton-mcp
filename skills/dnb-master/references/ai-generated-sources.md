# AI-Generated Sources

## Contents

- When to use this reference
- Source classification
- Source-quality rule
- Regenerate-first gate
- Prompt audit
- Repair workflow
- AI_MINIMAL_REPAIR
- AI stems warning
- QC for AI sources

## When to Use This Reference

Read this file when the source is:
- a Suno, Udio, or similar AI-generated stereo render
- an AI-derived stem export
- a track with stationary whistle tones, resonance spikes, brittle highs, vocal tearing, or already-baked loudness

This is not a theory file about generator internals. Stay operational:
- describe what is audible
- describe what is measurable
- decide whether to regenerate or process

## Source Classification

Classify the source before choosing a mastering path:

- `AI-generated stereo render`: one baked stereo file, often already compressed and limited
- `AI-derived stems`: separated files from an already-generated render, often degraded and incomplete
- `Premaster stereo`: a human-produced mixdown that still behaves like a normal master candidate

Default assumptions for AI-generated material:
- it may already be pseudo-mastered
- it may contain artifacts that mastering cannot truly fix
- it may not tolerate a second loudness push well

## Source-Quality Rule

Lossy, artifacted, or AI-baked material cannot be truly restored by mastering. Processing can only contain or disguise damage.

Use this rule before preset selection:
- if the full stereo render is cleaner than AI-derived stems, prefer the stereo render
- if a lossless render is available, request it before processing a compressed download
- if artifacts are structural, choose `regenerate-first`
- if artifacts are mild and the user needs a practical salvage pass, choose `process-first` with `AI_MINIMAL_REPAIR`
- if the file is already loud and stable, choose `minimal-touch` rather than trying to master it again

## Regenerate-First Gate

Choose `regenerate-first` when any of these are true:
- stable whistle tones or resonance spikes dominate a section
- the vocal has tearing, watery artifacts, or severe consonant breakup
- the top end is brittle enough that fixing it would darken the whole song
- removing the artifact reveals holes or obviously missing spectral content
- the track already sounds over-limited and small
- the user can still change the text prompt and rerender

Choose `process-first` only when:
- the artifact is mild
- the musical balance is otherwise usable
- the source survives small corrective moves
- the user needs a practical salvage pass now

## Prompt Audit

If the user has the generation prompt, audit it before audio repair.

Look for:
- contradictory adjectives such as `intimate and huge`, `slow and frantic`, `clean and distorted`
- too many genre anchors pulling in different directions
- overstacked top-end language such as `bright`, `sparkling`, `shimmering`, `airy`, `crispy`, `wide` all at once
- too many production instructions in one sentence
- dense requests for multiple lead elements occupying the same range

Rewrite strategy:
- reduce the number of simultaneous aesthetic demands
- separate core genre, vocal tone, and arrangement intent
- keep the frequency picture simpler
- prefer one clear vocal description over several competing ones

Useful output format:
- `What may cause artifacts`
- `Why it is risky`
- `Safer rewrite`

## Repair Workflow

When the file is worth salvaging:

1. Start with `MINIMAL_TOUCH` or `AI_MINIMAL_REPAIR`.
2. Do not chase loudness first.
3. Confirm whether the source is lossless or only a lossy/platform file. If a better export is available, request it first.
4. Use Spectrum to confirm whether the problem is broad harshness or a stable narrow spike.
5. For broad harshness:
   - use a small wide cut around the offending region
   - add mild high-band control with Multiband Dynamics if needed
6. For a stable resonance spike:
   - use a narrow EQ Eight notch on the audible spike
   - keep the cut as small as possible
   - stop if the vocal or cymbals collapse
7. Use Limiter as a safety stage, not as a loudness target by default.
8. If the source already sounds mastered, avoid extra saturation unless the user explicitly wants color and accepts more damage.

Repair stop conditions:
- the artifact goes down but the track becomes hollow
- the vocal gets papery or smaller
- the drop loses weight
- mono compatibility gets worse

If any stop condition appears, recommend regeneration.

## AI_MINIMAL_REPAIR

Use when:
- the source is an AI-generated stereo render
- resonance spikes or brittle highs are present
- the file already sounds loud enough and should not be pushed harder

Device order:
1. Utility
2. EQ Eight
3. Multiband Dynamics
4. Limiter

Starting approach:
- Utility: Bass Mono on around 120 Hz if the low end is unstable
- EQ Eight: start with broad cleanup; allow a narrow notch only for a stable obvious spike
- Multiband Dynamics: gentle high-band containment, corrective not dramatic
- Limiter: safety ceiling, minimal added drive

Do not use when:
- the source is a normal healthy premaster
- the user mainly wants more punch or density from a real mix
- regeneration is clearly the better answer

## AI Stems Warning

Treat AI-derived stems as convenience files, not trustworthy mix assets.

Working rules:
- do not assume full-band fidelity
- do not assume the removed part truly exists elsewhere
- expect missing high-frequency detail, spectral holes, and smeared transients
- if the user asks for stem-based mastering, warn that the source quality may be worse than the full stereo render

Prefer:
- fixing the original stereo render when it is usable
- regenerating from a better prompt when the artifacts are structural

## QC for AI Sources

In addition to the normal mastering QC:

- check for stationary whistles in intros, sustains, and fades
- check whether hats turn into fizz when louder
- check whether the vocal tears or lisps after processing
- check whether notch cuts leave obvious holes
- check whether the file already sounds over-limited before adding loudness
- check whether a lossless source or cleaner regeneration is available
- check whether the repaired version is actually better than a simpler rerender would be
