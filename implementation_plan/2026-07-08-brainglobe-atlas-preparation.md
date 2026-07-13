# BrainGlobe Atlas Preparation

Date: 2026-07-08

## Goal And Motivation

Add a reproducible preparation stage between ND2 slide-section isolation and
BrainGlobe atlas usage. For the current sparse-dataset goal, that stage should
support slice-wise 2D section-to-atlas workflows first, while keeping the
existing 3D-oriented preparation pieces available for later use.

## Current Problem

The repository already isolates multiple brain sections from ND2 slide images
and can now export per-section images, build a stack, and prepare a `brainreg`
run. That is useful infrastructure, but it is not the right primary workflow
for the clarified short-term goal.

The current goal is not full 3D reconstruction. It is to superimpose each
isolated histology section onto a rat atlas plane. For that sparse slice-wise
mode, the repository still lacks:

- a manifest-driven way to assign or compute atlas planes per section;
- a BrainGlobe Atlas API bridge that exports 2D atlas reference and annotation
  slices for each section;
- a coarse section-to-atlas overlay workflow for visual QC;
- per-section overlay outputs that let the user inspect whether the selected
  atlas plane and coarse alignment are plausible before investing in tighter
  registration.
- a reusable registration stage that estimates and records an actual 2D
  transform for each section rather than only a bounding-box preview.

The repository now contains an initial `slice_registration.py` module, but the
first runtime attempts on Windows triggered `python.exe` application crashes
(`0xc06d007f`) while exercising the image-warp path used by the new
registration stage. That means the immediate problem is no longer only missing
functionality; it is also a stability issue in the current implementation.

After the registration crash was mitigated, the next concrete gap is that the
slice-wise workflow still stops at aligned images plus overlap metrics. The
registered slices are not yet summarized by atlas region, so the pipeline does
not produce the anatomy-indexed tables that users actually need for downstream
analysis.

Real-data previewing on `RM014_Nikon_260604\Slide_05_x4.nd2` also exposed a
section-isolation error in the upstream crop detector: the left histology slice
was split into a main component plus a small detached sliver, and the preview
stage counted that sliver as a third section. The detector needs a
post-component merge rule so obviously associated nearby fragments are grouped
into a single section crop.

After that merge step was added, the user reported a regression on
`Slide_02_x4.nd2`, `Slide_03_x4.nd2`, and `Slide_04_x4.nd2`: previews that
should contain 4 sections were collapsed into a single merged section. The
current merge heuristic is therefore too broad for slides where multiple true
sections sit in the same row with large crop margins.

After tightening that rule, the user confirmed the real target counts for
slides 2 to 5 but reported that `Slide_01_x4.nd2` should still read as
6 sections rather than the current 8. The saved preview in
`outputs/RM014_preview_all_rerun/Slide_01_x4_preview_ds64.png` is the desired
behavior. The remaining problem is that two fragmented top-row sections on
slide 1 are still split into extra crops, while the broader multi-slice
regression on slides 2 to 4 must stay fixed.

The existing paperflow work in
`paperflow/2d-rat-slice-3d-reconstruction/answer.md` and
`paperflow/2d-rat-slice-3d-reconstruction/reviews/brainj-vs-brainglobe-workflows.md`
explicitly recommends sparse 2D atlas mode first for the current demo-style
dataset.

## Why This Is Needed Now

The user clarified that slice-wise atlas superimposition is the immediate goal.
That makes per-section atlas-plane preparation and per-section QC overlays more
important than additional 3D reconstruction work right now.

After the initial sparse-mode helpers were added, the remaining blocker is that
the workflow still stops at coarse preview overlays. The user has now asked for
real 2D slice-to-atlas registration per section, so the next step is to turn
those pairings into actual reusable transforms and warped section images.

After the first implementation pass, the user reported repeated Windows crash
dialogs during verification. That makes crash diagnosis and backend
stabilization the top priority before treating the registration stage as a
usable part of the BrainGlobe workflow.

With the registration path now stabilized enough to run synthetic checks, the
next most useful step is to convert those registered slices into region-level
atlas summaries.

At the same time, the user pointed out a concrete false split in the real-data
preview stage. Fixing that upstream section-isolation behavior is now an
immediate usability requirement because every later BrainGlobe step depends on
correct section counts.

Now that the first merge fix has introduced a regression on other real slides,
the immediate priority is to tighten that merge behavior so it only joins
probable fragments rather than neighboring full sections.

With that regression controlled, the next immediate priority is to recover the
desired 6-section behavior on `Slide_01_x4.nd2` by allowing moderate
fragment-size merges for obviously related pieces without reopening the
slides-2-to-4 over-merge bug.

With the 6-section count now restored, the remaining issue on
`Slide_01_x4.nd2` is slight crop tightness for sections 1 and 3 in the preview.
This is no longer a component-grouping problem; it is a box-padding problem.
The safest fix is to add a small, explicit final crop-box padding stage that
can be enabled conservatively and reverted by configuration if it expands boxes
too far on other slides.

The next user-facing gap is workflow ergonomics. The repository now has the
main slice-wise stages implemented, but testing them on a faster PC would still
require manually running export, atlas-plane preparation, QC generation,
registration, and optional atlas-summary commands in the right order.

## Git Or Worktree State

The workspace contains a `.git` directory, but `git` is not currently
available on the command path in this shell session, so branch/commit details
cannot be queried from the terminal tooling used here.

## Affected Modules And Files

- `src/brain_section_pipeline/slice_atlas.py`: slice-wise BrainGlobe atlas
  preparation helpers.
- `src/brain_section_pipeline/crop.py`: section detection, fragment merging,
  and crop-box construction.
- `src/brain_section_pipeline/slice_registration.py`: per-section 2D
  registration helpers, transform export, and crash-prone warp backend.
- `src/brain_section_pipeline/qc.py`: per-section atlas overlay QC helpers.
- `src/brain_section_pipeline/atlas_summary.py`: region-level slice summary
  helpers built on registered sparse-mode outputs.
- `src/brain_section_pipeline/workflow.py`: orchestration helper for the full
  slice-wise atlas workflow.
- `src/brain_section_pipeline/__init__.py`: public exports.
- `tests/test_merge_and_crop.py`: focused slice-wise atlas and QC tests.
- `README.md`: workflow documentation for sparse slice-wise atlas mode.
- `implementation_plan/README.md`: plan index.
- `change_log/`: post-implementation record.

Existing modules such as `export.py`, `stack.py`, and `brainreg_runner.py`
remain relevant, but they are no longer the only primary path described in the
README for the current use case.

## Public Parameters Or API Changes

Keep the existing preparation, stack, and `brainreg` APIs.

Extend the crop-detection API conservatively if needed to support post-detection
merge tuning without breaking current callers.

Add a public slice-wise atlas API:

- `SliceAtlasConfig`: atlas, plane axis, AP/atlas-index mapping, section image
  source, and output settings.
- `SliceAtlasResult`: paths for exported atlas planes, updated manifest, and
  generated metadata.
- `prepare_slice_atlas_inputs(...)`: read `section_manifest.csv`, assign an
  atlas plane to each selected section, export BrainGlobe atlas reference and
  annotation planes, and write per-section pairing metadata.

Add a public slice-wise QC API:

- `SliceAtlasQcConfig`: coarse alignment and overlay styling settings.
- `SliceAtlasQcResult`: paths for overlay previews and contact-sheet style QC
  outputs.
- `generate_slice_atlas_qc(...)`: create coarse section-to-atlas overlays using
  atlas boundaries and simple bounding-box alignment for fast review.

Add a public slice-wise registration API:

- `SliceRegistrationConfig`: parameters for mask extraction, optimization
  bounds, transform model, and output writing.
- `SliceRegistrationResult`: manifest and per-section output paths for warped
  sections, overlays, and transform metadata.
- `register_slices_to_atlas(...)`: estimate a real 2D transform for each
  section against its paired atlas plane, export warped images, and record the
  transform plus fit metrics.

Keep the public registration API shape stable if possible, but allow internal
algorithm changes that remove unstable native warp calls on Windows.

Add a public atlas-summary API:

- `AtlasSummaryConfig`: output paths, region-filtering rules, and structure
  lookup behavior.
- `AtlasSummaryResult`: per-section and aggregate summary table paths plus
  metadata.
- `summarize_registered_slices_by_region(...)`: read the registration manifest,
  summarize warped section intensities by atlas region, and optionally enrich
  rows with BrainGlobe structure metadata.

Add a public slice-wise workflow API:

- `SliceWorkflowResult`: stage-by-stage output paths and result objects for one
  sparse-mode run.
- `run_slicewise_atlas_workflow(...)`: run section export, atlas-plane
  preparation, optional coarse QC, slice registration, and optional atlas
  summaries in sequence from one ND2 file or folder input.

## Algorithm And Data Details

1. Reuse the existing export step so each isolated section already has:
   - `crop_path_registration`;
   - `crop_path_rgb`;
   - per-channel paths;
   - per-section QC/include flags.
2. Use BrainGlobe Atlas API when available to load the selected rat atlas
   reference and annotation volumes.
3. Determine the atlas slicing axis from the atlas orientation and the selected
   anatomical axis. For coronal-style sparse workflows, the default should
   target the atlas anterior-posterior axis.
4. Assign one atlas plane to each section using either:
   - explicit `atlas_slice_index` values already present in the manifest; or
   - a sequential rule defined by a start index and step size in the config.
5. Export for each selected section:
   - a 2D atlas reference plane;
   - a 2D atlas annotation plane;
   - a lightweight per-section metadata row linking section image and atlas
     plane.
6. Generate a coarse visual overlay by:
   - masking section tissue and atlas tissue extents;
   - scaling the section mask to match the atlas tissue bounding box;
   - centering or fitting the section on the atlas plane;
   - drawing atlas boundaries on top of the transformed section image;
   - saving the overlay as a QC preview, not as a final anatomical transform.
7. Write a slice-wise pairing manifest and a JSON sidecar so later manual or
   semi-automatic 2D registration can build on the same section-to-atlas
   assignments.
8. Add a real registration stage that:
   - reuses the section-to-atlas pairings from the slice-atlas manifest;
   - estimates a similarity-style 2D transform per section using tissue-mask
     overlap against the atlas plane;
   - initializes from the existing bounding-box fit;
   - refines scale, rotation, and translation numerically;
   - warps each section image into atlas coordinates;
   - records transform parameters, matrices, and overlap metrics for later
     review or downstream quantification.
9. Diagnose the Windows crash path by isolating which image warp or
   resampling backend triggers the `python.exe` application error.
10. Replace or simplify that warp backend if needed so registration uses a
    conservative, testable 2D transform path that does not depend on the
    crashing native code path.
11. Add atlas-summary generation that:
    - reads each warped section and its atlas annotation plane from the
      registration manifest;
    - computes per-region pixel count, integrated intensity, mean intensity,
      max intensity, and section-level participation;
    - aggregates those values across sections for sample-level region tables;
    - optionally attaches structure acronym/name information when BrainGlobe
      atlas metadata is available.
12. Add a crop-box merge step that:
    - considers nearby component boxes after thresholding and cleanup;
    - merges narrow split fragments into their parent section when horizontal or
      vertical gaps are small and row overlap is high;
    - reduces false extra-slice counts in real slide previews without broadly
      merging distinct sections.
13. Refine that crop-box merge step so it additionally checks fragment-like
    geometry before merging:
    - require a strong size imbalance or near-containment pattern between the
      two candidate boxes;
    - avoid merging similarly sized neighboring sections that only became close
      because crop margins expanded their boxes;
    - preserve the `Slide_05_x4.nd2` fragment fix while restoring 4-section
      detection on `Slide_02_x4.nd2`, `Slide_03_x4.nd2`, and
      `Slide_04_x4.nd2`.
14. Retune the fragment-size threshold so moderate fragment splits on
    `Slide_01_x4.nd2` can still merge back into the intended 6-section layout:
    - compare the current 8-box detection against the previously accepted
      preview image;
    - allow merges for smaller companion boxes that are meaningfully smaller
      than their neighbor, even if they are not tiny slivers;
    - keep the no-merge behavior for similarly sized neighboring sections on
      slides 2 to 4.
15. Add a final crop-box padding option after section grouping:
    - expand each accepted box by a small configurable number of pixels;
    - clamp the expansion to image bounds;
    - use a conservative default in the preview and pipeline paths so
      `Slide_01_x4.nd2` sections 1 and 3 are not visibly clipped;
    - keep the change easy to disable by setting the padding back to zero.
16. Add a thin orchestration layer for sparse slice-wise testing:
    - accept one ND2 path or a folder of ND2 files;
    - run export, atlas pairing, QC, registration, and optional summary stages
      in the correct order;
    - return a structured result object with the key manifests and output
      directories from every stage;
    - provide one script entry point so a full test can use a single command.

## Expected Behavior

After running the slice-wise atlas preparation function on a sample manifest,
the user should receive one atlas reference plane and one atlas annotation plane
per selected histology section, with explicit atlas-plane metadata recorded.

After running the slice-wise QC function, the user should receive overlay
previews that let them judge whether each section is plausibly paired to the
selected atlas plane and whether the coarse fit is close enough to continue
with more careful registration.

After running the slice-wise registration function, the user should receive one
warped section image and one registration overlay per selected section, plus a
manifest and JSON metadata describing the estimated 2D transform and fit
quality for each section.

After the stabilization pass, the registration stage should run in the Windows
`histology` environment without triggering the `python.exe` application error
dialog that was observed during earlier verification.

After running the atlas-summary function, the user should receive:

- a per-section per-region summary table;
- an aggregate per-region summary table across all registered slices;
- optional structure acronym/name fields when atlas lookup metadata is
  available.

After rerunning the real preview on `Slide_05_x4.nd2`, the detector should
report 2 sections instead of the previous incorrect 3 by merging the detached
sliver into the left slice crop.

After rerunning the real previews on the `RM014_Nikon_260604` folder, the
detector should also preserve separate section counts on neighboring slides:

- `Slide_01_x4.nd2`: 6 sections;
- `Slide_02_x4.nd2`: 4 sections;
- `Slide_03_x4.nd2`: 4 sections;
- `Slide_04_x4.nd2`: 4 sections;
- `Slide_05_x4.nd2`: 2 sections.

After the orchestration helper is added, one command should be able to produce:

- a sample export folder with `section_manifest.csv`;
- a `slice_atlas` folder with atlas planes and pairing manifest;
- optional QC overlays;
- a `slice_registration` folder with warped sections and registration manifest;
- optional atlas-summary CSV outputs.

## Verification

- Run existing crop/export tests conceptually to confirm section-isolation
  behavior still passes.
- Add tests that verify:
  - atlas-plane assignment from sequential config;
  - graceful fallback when BrainGlobe Atlas API is unavailable;
  - export of per-section atlas reference and annotation images;
  - coarse overlay generation with expected output dimensions and metadata.
- Add tests that verify:
  - per-section registration writes warped outputs and transform metadata;
  - synthetic rotated/scaled sections can be aligned back to a known atlas mask
    with strong overlap;
  - registration gracefully handles empty masks without crashing.
- Add or adjust verification so the registration path can be exercised in the
  Windows conda environment without triggering the prior application crash.
- Add tests that verify:
  - per-region summary rows are produced from a registration manifest;
  - aggregate rows combine multiple sections correctly;
  - structure metadata enrichment degrades gracefully when BrainGlobe atlas
    lookup is unavailable.
- Add tests that verify:
  - nearby split component boxes are merged into one section;
  - clearly separated sections are not merged accidentally.
- Add tests that verify:
  - similarly sized neighboring sections are not merged just because expanded
    crop margins make their boxes nearly touch;
  - the real-data-inspired regression pattern is blocked by the refined merge
    criterion.
- Add tests that verify:
  - moderately smaller fragment companions can still merge back into a parent
    section when their geometry matches the `Slide_01_x4.nd2` pattern;
  - equal-size neighboring sections remain separate after that threshold
    retuning.
- Add tests that verify:
  - final crop-box padding expands coordinates symmetrically and respects image
    bounds;
  - section counts are unchanged by the padding-only adjustment.
- Add tests that verify:
  - the new orchestration helper calls each slice-wise stage in the expected
    order;
  - optional QC and atlas-summary stages can be skipped without breaking the
    core export -> atlas -> registration path.
- Review README instructions against the implemented sparse slice-wise workflow.

## Non-Goals

- Do not implement full 3D reconstruction as the primary workflow in this
  change.
- Do not claim that the coarse overlay is a final anatomical registration.
- Do not require `brainreg` execution during tests or in environments where it
  is not installed.
- Do not implement a full nonlinear 2D registration engine in this change.
- Do not attempt full AP plane-search across the whole atlas volume in this
  change; keep atlas-plane selection as a separate upstream step.
- Do not broaden scope into unrelated BrainGlobe features until the crash in
  the current slice-wise registration path is understood and mitigated.
- Do not implement object-level cell detection in this change; summarize image
  intensity by atlas region only.
- Do not replace the whole thresholding/detection approach in this change; fix
  the observed false split with a targeted merge step.
- Do not tune around this regression by disabling crop margins globally; keep
  the existing crop expansion behavior and fix the merge criterion itself.
- Do not create a second independent registration pipeline for the orchestration
  command; it should stay a thin wrapper around the existing reusable stage
  functions.
