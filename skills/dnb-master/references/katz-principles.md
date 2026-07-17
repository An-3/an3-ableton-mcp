# Katz Principles for Practical DnB Mastering

## Contents

- Practical philosophy
- Source fitness
- Monitoring discipline
- Macrodynamics and continuity
- Session log

## Practical Philosophy

Use this reference as practical mastering discipline, not as a historical CD-mastering manual.

Core rules:
- there is no magic preset or universal setting
- mastering is a final objective check, not a substitute for mixing
- do no harm; stop when processing reduces punch, depth, vocal size, center weight, or musical contrast
- use references and repeatable monitoring, not loudness alone
- make small changes, then level-match the result against the bypassed source
- if the source should be remixed, re-exported, or regenerated, say so before building a chain

## Source Fitness

Prefer the earliest clean source available:
- WAV, AIFF, or BWF
- 24-bit or 32-bit float when possible
- project/native sample rate
- no MP3, AAC, or other lossy file unless the task is salvage
- no normalization as a preparation step
- no master-bus limiter unless it is an intentional part of the mix sound

For submitted stereo premasters:
- useful default maximum peak is around `-3 dBFS`
- lower peaks are fine in 24-bit or 32-bit float
- no overs or clipped samples
- leave heads, tails, breaths, and reverb decays intact when fades may need mastering judgment

Choose `revision-needed` when:
- clipping, overs, or full-scale normalization can be fixed by re-export
- the source is lossy and a lossless file is available
- the mix has structural balance problems that mastering cannot solve cleanly
- fades, tails, or transitions are cut off and handles are available

Choose `minimal-touch` when:
- the source is already loud, limited, or mastered
- only tiny safety, tone, or format work is appropriate
- further processing would make the record smaller, flatter, or harsher

Choose `regenerate-first` when:
- AI artifacts, missing spectral content, or vocal tearing are built into the source
- repair lowers the artifact but damages the music
- the prompt or source generation can still be changed

## Monitoring Discipline

Use a repeatable listening level whenever possible. The skill does not require full K-System calibration, but it should borrow the habit: if the monitor level keeps changing, loudness judgment becomes unreliable.

Working rules:
- level-match A/B comparisons before judging tone, width, punch, or loudness
- do not turn the monitor down to make over-limiting feel comfortable
- use references as orientation, not as a demand to copy exact loudness
- judge midrange translation carefully; vocal, snare, and bass rhythm must still read on small speakers
- use alternate checks as diagnostics, not as the main tonal authority
- if a decision only works on one problem playback system, do not make it the master unless the user asked for a dedicated version

## Macrodynamics and Continuity

Before using compression to solve every level problem, check whether the song needs musical level shaping.

Use clip gain, track gain, or automation-style moves when:
- an intro is too low compared with the drop
- a breakdown loses intention after the previous loud section
- a drop needs impact from contrast rather than more limiting
- an EP or album needs relative level continuity

For EPs and albums:
- preserve intentional contrast between tracks
- compare track-to-track loudness by musical effect, not peak value alone
- check spacing and fade shape in context
- make tails feel natural unless the user wants abrupt edits
- log per-track changes for revisions

## Session Log

Every serious mastering pass should leave enough information to reconstruct the decision.

Log:
- source type, file format, sample rate, bit depth, and release context
- source-fitness result and any requested replacement source
- delivery profile and loudness/true-peak target
- selected preset or reason no preset was used
- main device moves and level-matched bypass observations
- monitoring/reference notes
- LUFS-I, short-term loudness, LRA, dBTP, and peak results when available
- export format, bit depth, sample rate, normalize state, and dither choice
- revision notes, including what changed and why
