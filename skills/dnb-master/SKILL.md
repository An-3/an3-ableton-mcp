---
name: dnb-master
description: Master drum and bass, liquid, neurofunk, and jump up tracks in Ableton Live with stock devices only by using PREMASTER routing, source-fitness gates, reference A/B comparison, vocal-aware preset selection, loudness and true-peak targets, translation checks, safe export defaults, and regenerate-vs-repair decisions for AI-generated stereo renders or stems.
---

# DnB Master

## Overview

Use this skill when the user wants to master drum and bass in Ableton Live with stock devices only, especially for liquid, neurofunk, jump up, vocal-led DnB, loudness targeting, true peak control, source-fitness review, reference A/B workflows, EP/album continuity, or cleanup of AI-generated stereo renders from tools such as Suno or Udio. The skill is hybrid: automate when the MCP surface supports mastering actions, otherwise switch to a guided/manual workflow and state exactly which capabilities are missing.

The core mastering philosophy is conservative and professional: make small intentional moves, treat mastering as separate from mixing, preserve punch and transients, protect sub stability, and optimize for translation across club systems, headphones, phones, and streaming.

Practical Katz-derived discipline applies throughout: no magic preset, no loudness race by default, no processing just because tools are available, and no pretending a damaged source can always be mastered into a clean record. If the source needs a mix revision, stem revision, alternate export, or regeneration, say that before building a chain.

For vocal-led multitrack mixes, the first vocal-forward move after an initial master pass is usually not more master-bus loudness. Prefer a track-level vocal revision loop first: reduce vocal ambience, add a small vocal gain step, re-meter, and only then escalate to master-bus `VOCAL_FORWARD` tonal work if the words still sink behind the drop.

For AI-generated stereo sources, the first job is not always mastering. Decide whether the file should be `regenerate-first` or `process-first`. If the user has the generation prompt, audit the prompt for contradictory style pulls, overstacked bright elements, or wording that is likely to create brittle top-end, resonance spikes, or unstable vocals before attempting repair.

When the set is Arrangement-based, preserve Arrangement continuity. Session clip launches are useful for auditioning and meter checks, but they create a dirty playback state that must be cleared before export.

## Core Constraints

- Do not use third-party plugins.
- Use only Ableton stock devices relevant to mastering: Utility, EQ Eight, Glue Compressor, Compressor, Saturator, Multiband Dynamics, Drum Buss, Spectrum, and Limiter.
- Prefer a PREMASTER routing architecture so the mastering chain does not process reference tracks.
- Keep Limiter last in the mastering chain.
- Do not place gain-adding devices after Limiter.
- Keep low frequencies mono. Default Bass Mono decision range is 90-150 Hz, with 120 Hz as the neutral starting point.
- Keep mastering-scale moves subtle. Warn if any compressor or limiter is asked to exceed about 6 dB of gain reduction unless the user explicitly wants aggressive loudness.
- Run a source-fitness gate before preset selection. If the source is clipped, normalized into full-scale peaks, lossy, over-limited, missing needed handles, or already damaged, choose `revision-needed`, `minimal-touch`, or `regenerate-first` before normal mastering.
- Prefer earliest-generation sources: WAV, AIFF, or BWF; 24-bit or 32-bit float where possible; no MP3 or other lossy file unless the task is explicitly salvage.
- For submitted stereo premasters, prefer peaks safely below full scale, with about `-3 dBFS` maximum peak as a useful default and no overs. Do not require this for already-finished references.
- Keep Normalize off on export.
- Apply dither only once, at the final integer bit-depth reduction stage. Do not dither 32-bit float test renders.
- Do not upsample as a magic improvement. Stay at project or native sample rate unless delivery requires conversion.
- Use level-matched monitoring and reference checks. Louder is not automatically better.
- On multitrack mixes with a clear lead vocal, prefer track-level vocal revision before master-bus vocal-forward EQ or louder limiting.
- Default vocal revision order for multitrack mixes:
  1. lower vocal insert reverb `Dry/Wet` by about `2-5` percentage points
  2. raise the vocal track by about `0.01-0.03` normalized
  3. re-meter the vocal track and the master before exporting
- Escalate to master-bus `VOCAL_FORWARD` processing only if the track-level revision loop is not enough.
- Treat AI-generated stereo renders and AI-derived stems as special-case sources, not normal multitrack mixes.
- If the source already sounds hard-limited, brittle, or pre-mastered, default to `minimal-touch` or `regenerate-first` instead of loudness chasing.
- For clear stable whistles or resonance spikes, allow narrow EQ Eight notches and gentle high-band control as corrective repair. This is an exception to the usual broad-EQ rule.
- If repair creates holes, exposes tearing, or reveals missing frequency content, stop and recommend regeneration instead of pushing processing further.
- Treat AI stems as unreliable reconstruction artifacts; do not assume they are clean, full-band, or suitable for normal stem-mastering logic.
- Do not present unverifiable claims about a generator's internals as facts. Stay operational: describe what is audible, what is measurable, and what action follows.
- Do not pretend unsupported automation exists. If routing, insertion, render, or loudness-analysis tools are unavailable, say so and continue in guided mode.
- Never export after any `fire_clip`-based meter or audition pass until Arrangement playback has been restored and verified. If verification is unavailable, require a manual Back to Arrangement step before export.

## Capability Check

Start every task by identifying whether the environment is `automation-ready` or `guided`.

Treat the following as currently supported in the Ableton MCP server used for this project:
- `get_session_info`
- `get_track_info`
- `get_master_meter`
- `get_transport_state`
- `list_playing_clips`
- `back_to_arrangement`
- `verify_arrangement_export_ready`
- `get_browser_tree`
- `get_browser_items_at_path`
- `load_instrument_or_effect`
- `get_device_parameters`
- `set_device_parameter`

Treat the following as optional future capabilities, not guaranteed today:
- audio-track creation
- PREMASTER/reference routing
- deterministic device insertion and ordering
- device option toggles such as EQ Eight oversampling
- render/export
- LUFS and true-peak analysis
- automated QC report generation

Mode rules:
- `automation-ready`: the MCP surface can inspect the session, build routing, insert or reorder devices, set parameters, render, and analyze loudness. Use the full workflow.
- `guided`: some or all mastering actions are missing. Provide exact Ableton steps, use MCP only for safe inspection or parameter edits, and call out the missing capabilities up front.

Before any export recommendation, also identify whether the session is `export-ready`:
- `export-ready`: `verify_arrangement_export_ready` reports safe Arrangement playback
- `export-blocked`: Session override is active or Arrangement state cannot be verified

## Workflow

1. Inspect the session and the user goal.
2. Identify the source type:
   - `multitrack mix`
   - `premaster stereo`
   - `AI-generated stereo render`
   - `AI-derived stems`
3. Identify the release context:
   - `single`
   - `EP/album`
   - `unknown`
4. Read [katz-principles.md](references/katz-principles.md), run the Source Fitness Gate, and decide whether the source is `fit-to-master`, `revision-needed`, `minimal-touch`, or `regenerate-first`.
5. If the source is AI-generated or AI-derived, read [ai-generated-sources.md](references/ai-generated-sources.md), decide `regenerate-first` vs `process-first`, and audit the text prompt if the user can provide it.
6. Decide whether vocals are a first-class concern in this master.
7. Choose a delivery profile:
   - `streaming-safe`
   - `louder-than-normalized`
   - `club-impact`
   - `minimal-touch`
8. If routing tools exist and the source is a real multitrack mix, build or verify the PREMASTER architecture:
   - all mix tracks feed PREMASTER
   - PREMASTER feeds Main
   - reference tracks bypass PREMASTER and feed Main directly
   For single stereo renders, PREMASTER is optional. Do not invent fake mix-layer separation.
9. Establish a monitoring/reference plan:
   - keep references outside the PREMASTER chain
   - level-match A/B before judging tone, punch, width, or loudness
   - use a repeatable monitor level when possible
10. If release context is `EP/album`, check track order, relative loudness, spacing, fades, tails, and continuity before final loudness decisions.
11. Choose one preset from the 9-preset matrix in [presets.md](references/presets.md), unless the source-fitness result already requires `revision-needed`, `minimal-touch`, or `regenerate-first`.
12. Apply only mastering-scale moves. Prefer broad EQ, low drive saturation, light compression, and macrodynamic clip/track-gain moves before heavier compression. For AI artifact repair, a narrow notch or light high-band containment is acceptable when the problem is stable and obvious.
13. If a vocal-led multitrack mix still feels buried after the initial master pass, run the Vocal Revision Loop before pushing the master harder.
14. Measure and iterate when analyzer tools exist:
   - streaming-safe default target: about `-14 LUFS-I` and `<= -1 dBTP`
   - louder-than-normalized default: preserve more headroom and prefer `<= -2 dBTP`
   For AI-generated sources that already sound mastered, prefer safety checks and restraint over chasing a louder target.
15. Prefer arrangement-safe metering. If the set is Arrangement-based and transport plus meter sampling are enough, do not launch Session clips.
16. If you do launch Session clips with `fire_clip`, mark the set as dirty until `back_to_arrangement` succeeds and `verify_arrangement_export_ready` passes.
17. If LUFS or true-peak analysis is unavailable, give the user the exact render and offline analysis loop from [metering-and-targets.md](references/metering-and-targets.md).
18. Finish with export defaults, a concise session log, and the QC checklist from [katz-principles.md](references/katz-principles.md), [export-and-troubleshooting.md](references/export-and-troubleshooting.md), [metering-and-targets.md](references/metering-and-targets.md), and [ai-generated-sources.md](references/ai-generated-sources.md) when relevant.

## Source Fitness Gate

Run this before selecting a normal preset.

Use `fit-to-master` when:
- the source is uncompressed or only intentionally mixed into the bus
- peaks are safely below full scale or at least not clipped
- the source is a lossless file or a live multitrack session
- the tonal, vocal, low-end, and transient problems are mastering-scale

Use `revision-needed` when:
- the source clips or has obvious overs that should be fixed in the mix
- the stereo premaster is normalized to full scale without headroom
- the vocal, kick, snare, or bass balance is structurally wrong in a real multitrack mix
- the file is lossy and the user can provide a lossless export
- fades, tails, or breaths are cut off and the user can provide handles

Use `minimal-touch` when:
- the mix is already mastered or hard-limited but still deliverable
- the user needs safety, level, format, or tiny tonal moves only
- more processing would reduce punch, depth, center strength, or codec safety

Use `regenerate-first` when:
- the source is AI-generated and artifacts are structural
- repair exposes holes, tearing, missing frequency content, or brittle top-end collapse
- the user can still alter the prompt or source generation

If the gate does not pass, clearly state what better source is needed and do not disguise source damage as a mastering decision.

## Single vs EP/Album Handling

For a `single`, focus on the chosen delivery profile, reference match, translation, and export safety.

For an `EP/album`, treat mastering as a continuity job:
- level-match tracks by musical impact, not peak level alone
- check drops, breakdowns, intros, and final drops across songs
- preserve intentional contrast instead of forcing every track to identical loudness
- consider spacing, fade shape, tails, and transition energy
- log per-track moves so revisions can be reconstructed

## Vocal Revision Loop

Use this loop only for multitrack mixes with a clear lead vocal track.

Track-first order:
1. Identify the lead vocal track.
2. Reduce vocal insert ambience first, usually by lowering insert reverb `Dry/Wet` about `2-5` percentage points.
3. If the vocal still feels behind the drop, raise the vocal track by one small step, about `0.01-0.03` normalized.
4. Re-meter the vocal track and the master.
5. If the vocal is still not reading clearly, escalate to `VOCAL_FORWARD` tonal help:
   - small mid presence lift around `2-5 kHz`, or
   - a competing-mid reduction elsewhere
6. Stop if the vocal track or master starts clipping, or if pushing the vocal makes the master lose punch or center stability.

Default reporting after a vocal revision loop:
- whether a vocal revision pass was used
- which track was touched
- what changed: `track gain`, `reverb wet`, and any optional presence EQ
- what meter or QC check cleared the change

## Preset Selection

Read [presets.md](references/presets.md) before selecting a chain. Use these defaults:

- `STREAM_SAFE_TRANSPARENT`: streaming-safe default for balanced masters with clean codec behavior.
- `STREAM_LOUD_CONTROLLED`: louder and denser, but still controlled.
- `CLUB_IMPACT`: punch-preserving club energy.
- `SUB_TIGHT`: choose when kick and sub trigger limiter overload or smear vocal clarity.
- `VOCAL_FORWARD`: choose when the vocal is buried in dense drops.
- `HARSH_SOFTENER`: choose when hats, upper mids, or sibilance get brittle.
- `WIDE_TOPS`: choose when the top end is narrow or dull but the low end is already solid.
- `MINIMAL_TOUCH`: choose when the mix already sounds finished and only needs safety moves.
- `AI_MINIMAL_REPAIR`: choose when the source is an AI-generated stereo render with resonance spikes, brittle highs, or already-baked loudness that should not be remastered aggressively.

Preset decision rules:
- Run the Source Fitness Gate before choosing any normal preset.
- If the source fails the gate, report `revision-needed`, `minimal-touch`, or `regenerate-first` instead of forcing a preset.
- Start with `STREAM_SAFE_TRANSPARENT` unless the user clearly wants louder, brighter, wider, more vocal-forward, or more low-end containment.
- Prefer `AI_MINIMAL_REPAIR` or `MINIMAL_TOUCH` over louder presets for AI-generated stereo material unless the source is unusually clean and under-processed.
- Prefer single-band compression over multiband unless a specific frequency region is causing translation failure.
- Use M/S only for precise image or vocal-center fixes, not as a default heavy-handed process.
- If the problem is a stable whistle or resonance spike, use the repair logic from [ai-generated-sources.md](references/ai-generated-sources.md) before assuming the track needs louder mastering.

## Measurement, QC, and Export

Use [metering-and-targets.md](references/metering-and-targets.md) for loudness targets, true-peak reasoning, reference matching, and deterministic QC. Use [export-and-troubleshooting.md](references/export-and-troubleshooting.md) for render settings, bit depth, dither, and problem fixing.

When measurement is available:
- iterate against LUFS-I, LRA, short-term loudness, and dBTP
- keep true peak within the chosen target
- stop pushing if loudness gains cost obvious punch, vocal size, or stereo stability
- for AI-generated stereo material, do not treat loudness headroom as permission to master again more aggressively if the render already sounds baked or lossy

When measurement is not available:
- say that Live stock metering is peak and RMS only, not LUFS-compliant
- instruct the user to render a test pass and run offline LUFS and true-peak analysis
- give a concrete next action instead of vague advice

Before export:
- call `verify_arrangement_export_ready`
- if it fails, restore Arrangement playback with `back_to_arrangement` and verify again
- if verification is still unavailable, stop and give exact manual instructions instead of claiming export is safe

## Response Format

Every mastering answer should include these sections in substance, even if the wording varies:

- `Source Type`: `multitrack mix`, `premaster stereo`, `AI-generated stereo render`, or `AI-derived stems`
- `Release Context`: `single`, `EP/album`, or `unknown`
- `Source Fitness`: `fit-to-master`, `revision-needed`, `minimal-touch`, or `regenerate-first`
- `Regenerate Decision`: `process-first` or `regenerate-first`, with a short reason
- `Mode`: `automation-ready` or `guided`
- `Export Readiness`: `export-ready` or `export-blocked`
- `Preset`: selected preset and why
- `Target`: delivery profile plus loudness and true-peak target
- `Monitoring/Reference Check`: how references were level-matched and what translation checks matter
- `Chain Moves`: the main device and parameter changes
- `Vocal Revision Pass`: whether it was used, which track changed, what changed, and what meter/QC check cleared it
- `Manual Steps`: unresolved steps if MCP cannot perform them
- `QC`: the checks required before calling the master done
- `Session Log`: concise source, target, moves, measurements, export, and revision notes
- `Export`: the recommended deliverable format and dither choice

If the session is not automation-ready, explicitly list the missing capabilities before giving the guided steps.
If export readiness is blocked, explicitly say why and do not present the export as complete.

## References To Read

- Read [routing-and-chain.md](references/routing-and-chain.md) for PREMASTER setup, chain order, EQ, compression, M/S, bass mono, transients, and saturation guidance.
- Read [katz-principles.md](references/katz-principles.md) for source-fitness gates, practical mastering discipline, monitoring habits, and session logging.
- Read [presets.md](references/presets.md) when selecting or tuning a preset.
- Read [metering-and-targets.md](references/metering-and-targets.md) for loudness targets, LUFS/true-peak workflow, A/B, and QC.
- Read [export-and-troubleshooting.md](references/export-and-troubleshooting.md) for render settings, dithering, and fix strategies.
- Read [ai-generated-sources.md](references/ai-generated-sources.md) when the source is a Suno/Udio-style stereo render, AI-derived stems, or the user reports resonance spikes, brittle highs, or pre-mastered sounding output.

## Example Prompts

- Use `$dnb-master` to master this liquid DnB vocal track for Spotify and keep it clean and punchy.
- Use `$dnb-master` to make this neurofunk master louder without killing the snare.
- Use `$dnb-master` to fix harsh hats and sibilance in my DnB master with stock Ableton devices only.
- Use `$dnb-master` to prepare a safe 24-bit distribution master and give me the QC checklist.
- Use `$dnb-master` to decide whether this Suno DnB render should be regenerated or repaired in Ableton.
- Use `$dnb-master` to audit this Suno prompt for wording that may cause resonance spikes before I render again.
