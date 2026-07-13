# BrainGlobe Atlas Preparation

Date: 2026-07-08

Git state: uncommitted changes in the working tree. A commit hash could not be
queried in this shell session because `git` is not available on the command
path here.

Implementation plan: [2026-07-08 BrainGlobe Atlas Preparation](../implementation_plan/2026-07-08-brainglobe-atlas-preparation.md)

## What Changed

- Added `src/brain_section_pipeline/export.py` with:
  - `BrainGlobeExportConfig`;
  - `BrainGlobeExportResult`;
  - `export_sections_for_brainglobe(...)` for sample-level export of isolated
    sections, per-channel TIFFs, registration-channel TIFFs, QC overlays, and a
    sample manifest.
- Added `src/brain_section_pipeline/stack.py` with:
  - `StackBuildConfig`;
  - `StackBuildResult`;
  - `build_stack_from_manifest(...)` for manifest-driven TIFF stack
    construction from registration images or exported channel images.
- Added `src/brain_section_pipeline/brainreg_runner.py` with:
  - `BrainRegConfig`;
  - `BrainRegPreparationResult`;
  - `prepare_brainreg_run(...)` to expand stack volumes into `brainreg`
    slice directories and construct the `brainreg` command from recorded
    metadata;
  - `run_prepared_brainreg(...)` for optional command execution.
- Added `src/brain_section_pipeline/slice_atlas.py` with:
  - `SliceAtlasConfig`;
  - `SliceAtlasResult`;
  - `prepare_slice_atlas_inputs(...)` for per-section BrainGlobe atlas-plane
    export in sparse slice-wise mode.
- Added `src/brain_section_pipeline/qc.py` with:
  - `SliceAtlasQcConfig`;
  - `SliceAtlasQcResult`;
  - `generate_slice_atlas_qc(...)` for coarse slice-to-atlas overlay previews.
- Added `src/brain_section_pipeline/slice_registration.py` with:
  - `SliceRegistrationConfig`;
  - `SliceRegistrationResult`;
  - `register_slices_to_atlas(...)` for real per-section 2D
    slice-to-atlas registration using a similarity transform
    (scale/rotation/translation) against each paired atlas plane.
- Updated `src/brain_section_pipeline/crop.py` to merge nearby split component
  boxes after threshold-based detection so small detached slivers can be folded
  back into their parent section crop instead of being counted as extra slices.
- Refined `src/brain_section_pipeline/crop.py` again so post-detection box
  merging only applies to fragment-like size imbalances instead of to any close
  neighboring boxes. This prevents real multi-slice rows from collapsing into
  one merged section after crop margins expand their boxes.
- Retuned the fragment-merge threshold in `src/brain_section_pipeline/crop.py`
  so moderately smaller companion fragments on `Slide_01_x4.nd2` merge back
  into the intended 6-section layout while the equal-sized four-section slides
  remain separate.
- Added a reversible final crop-box padding option in
  `src/brain_section_pipeline/crop.py` and threaded it through
  `src/brain_section_pipeline/pipeline.py` plus `scripts/preview_nd2.py` so
  slightly tight crops can be loosened without changing section grouping.
- Added `src/brain_section_pipeline/workflow.py` with:
  - `SliceWorkflowResult`;
  - `run_slicewise_atlas_workflow(...)` to run sparse slice-wise export,
    atlas-plane preparation, optional QC overlays, registration, and optional
    atlas summaries in one call.
- Added `src/brain_section_pipeline/atlas_summary.py` with:
  - `AtlasSummaryConfig`;
  - `AtlasSummaryResult`;
  - `summarize_registered_slices_by_region(...)` for per-section and aggregate
    intensity summaries by atlas region from the slice-registration manifest.
- Stabilized `src/brain_section_pipeline/slice_registration.py` for the
  Windows `histology` environment by:
  - replacing the earlier native warp path with explicit NumPy coordinate
    mapping and local bilinear/nearest sampling;
  - replacing covariance/eigendecomposition-based mask orientation with a
    moment-based closed-form orientation estimate;
  - removing the registration path's dependence on `skimage` morphology and
    intensity-rescaling helpers in favor of local NumPy/SciPy equivalents;
  - reducing registration search density and atlas downsample size so the safer
    backend remains practical to run.
- Extended `src/brain_section_pipeline/io.py` to capture ND2 voxel-size
  metadata when the underlying reader provides it.
- Reworked `src/brain_section_pipeline/__init__.py` to use lazy exports rather
  than eagerly importing the full package graph during `import
  brain_section_pipeline`.
- Exported the new BrainGlobe-preparation API from
  `src/brain_section_pipeline/__init__.py`.
- Exported the new stack-building API from
  `src/brain_section_pipeline/__init__.py`.
- Added `scripts/build_stack.py` as a thin command-line wrapper around
  `build_stack_from_manifest(...)`.
- Added `scripts/run_brainreg.py` as a thin command-line wrapper around
  `prepare_brainreg_run(...)` and optional execution.
- Added `scripts/prepare_slice_atlas.py` and
  `scripts/generate_slice_atlas_qc.py` as thin entrypoints for sparse
  slice-wise atlas workflows.
- Added `scripts/register_slices_to_atlas.py` as a thin entrypoint for
  manifest-driven slice-wise 2D atlas registration.
- Added `scripts/summarize_atlas.py` as a thin entrypoint for slice-wise
  atlas-region summaries.
- Added focused tests for BrainGlobe export behavior, stack construction, and
  `brainreg` preparation behavior, plus graceful atlas-metadata fallback when
  BrainGlobe Atlas API is unavailable.
- Added focused tests for per-section atlas-plane export and coarse QC overlay
  generation.
- Added focused tests for slice-wise registration output writing, synthetic
  alignment behavior, and empty-mask handling.
- Added focused tests for atlas-region summary generation, aggregate behavior,
  and graceful fallback when structure lookup metadata is unavailable.
- Added focused tests for post-detection crop-box merging so nearby split
  fragments are merged while clearly separate sections remain separate.
- Added focused regression tests so similarly sized neighboring sections are not
  merged just because margin expansion makes their boxes nearly touch or
  overlap.
- Added a focused test that allows a moderately smaller companion fragment to
  merge into a neighboring parent section, matching the recovered `Slide_01`
  behavior more closely.
- Added a focused test for final crop-box padding expansion and boundary
  clamping.
- Added focused orchestration tests that verify the new slice-wise workflow
  helper calls stages in order and can skip QC plus atlas-summary stages.
- Updated `README.md` with the new preparation workflow, example code, and the
  recommended BrainGlobe handoff path for rat atlas registration.
- Added `scripts/run_slicewise_workflow.py` as a thin one-command entrypoint
  for the sparse slice-wise workflow.
- Added a `brainglobe` optional dependency group in `pyproject.toml` and added
  `brainglobe-atlasapi` plus `brainreg` to `environment.yml`.

## Why The Change Was Made

The repository already isolated sections from ND2 slide images but did not yet
provide the structured handoff needed for BrainGlobe-based atlas workflows.
This change adds that bridge so sample metadata, section numbering, channel
exports, and registration inputs are preserved consistently before either 3D
reconstruction or slice-wise atlas matching. After the user clarified that the
immediate goal is sparse slice-wise atlas superimposition, the implementation
also added a BrainGlobe Atlas API bridge and QC overlays that support
per-section atlas-plane workflows directly, without requiring a full 3D model
first. The latest extension adds the missing real 2D registration stage so the
repository no longer stops at coarse overlays for sparse mode. The follow-up
stability pass was needed because the first registration implementation
triggered repeated Windows `python.exe` application crashes during runtime
verification. With registration outputs now available, the next useful step
was to summarize those aligned slices by atlas region so the workflow produces
analysis-ready tables rather than only overlays and transform metrics.

## Verification Performed

- Manual code review against the existing ND2 crop pipeline and repository
  paperflow guidance.
- Attempted test command:

```powershell
python -m pytest tests/test_merge_and_crop.py
```

- Attempted test command after stack-module changes:

```powershell
python -m pytest tests/test_merge_and_crop.py
```

- Syntax verification command after adding slice-wise registration:

```powershell
C:\Users\neerc\miniconda3\envs\histology\python.exe -m py_compile src\brain_section_pipeline\slice_registration.py scripts\register_slices_to_atlas.py tests\test_merge_and_crop.py
```

- Syntax verification command after the Windows-stability pass:

```powershell
C:\Users\neerc\miniconda3\envs\histology\python.exe -m py_compile src\brain_section_pipeline\slice_registration.py src\brain_section_pipeline\__init__.py tests\test_merge_and_crop.py
```

- Syntax verification command after adding atlas summaries:

```powershell
C:\Users\neerc\miniconda3\envs\histology\python.exe -m py_compile src\brain_section_pipeline\atlas_summary.py src\brain_section_pipeline\__init__.py scripts\summarize_atlas.py tests\test_merge_and_crop.py
```

- Syntax verification command after the crop-fragment merge fix:
 
```powershell
C:\Users\neerc\miniconda3\envs\histology\python.exe -m py_compile src\brain_section_pipeline\crop.py tests\test_merge_and_crop.py scripts\preview_nd2.py
```

- Real-data count verification after tightening the crop-fragment merge rule:
 
```powershell
C:\Users\neerc\miniconda3\envs\histology\python.exe -c "import sys; sys.path.insert(0, 'src'); from brain_section_pipeline import read_nd2_image; from brain_section_pipeline.crop import detect_section_crops; files=[r'C:\Users\neerc\OneDrive\Documents\RM014_Nikon_260604\Slide_01_x4.nd2', r'C:\Users\neerc\OneDrive\Documents\RM014_Nikon_260604\Slide_02_x4.nd2', r'C:\Users\neerc\OneDrive\Documents\RM014_Nikon_260604\Slide_03_x4.nd2', r'C:\Users\neerc\OneDrive\Documents\RM014_Nikon_260604\Slide_04_x4.nd2', r'C:\Users\neerc\OneDrive\Documents\RM014_Nikon_260604\Slide_05_x4.nd2']; [print(path.split('\\\\')[-1], len(detect_section_crops(read_nd2_image(path, downsample=64).data, min_area=max(100, 1000000 // (64**2)), margin=max(5, 250 // 64), opening_radius=0, closing_iterations=max(1, 160 // 64), mask_channel=0, sort_mode='row_right_to_left').boxes)) for path in files]"
```

- Real-data count verification after retuning `Slide_01_x4.nd2` fragment
  merges:

```powershell
C:\Users\neerc\miniconda3\envs\histology\python.exe -c "import sys; sys.path.insert(0, 'src'); from brain_section_pipeline import read_nd2_image; from brain_section_pipeline.crop import detect_section_crops; files=[r'C:\Users\neerc\OneDrive\Documents\RM014_Nikon_260604\Slide_01_x4.nd2', r'C:\Users\neerc\OneDrive\Documents\RM014_Nikon_260604\Slide_02_x4.nd2', r'C:\Users\neerc\OneDrive\Documents\RM014_Nikon_260604\Slide_03_x4.nd2', r'C:\Users\neerc\OneDrive\Documents\RM014_Nikon_260604\Slide_04_x4.nd2', r'C:\Users\neerc\OneDrive\Documents\RM014_Nikon_260604\Slide_05_x4.nd2']; [print(path.split('\\\\')[-1], len(detect_section_crops(read_nd2_image(path, downsample=64).data, min_area=max(100, 1000000 // (64**2)), margin=max(5, 250 // 64), opening_radius=0, closing_iterations=max(1, 160 // 64), mask_channel=0, sort_mode='row_right_to_left').boxes)) for path in files]"
```

- Refreshed full-preview command after the `Slide_01` retune:
 
```powershell
C:\Users\neerc\miniconda3\envs\histology\python.exe -m py_compile src\brain_section_pipeline\crop.py src\brain_section_pipeline\pipeline.py scripts\preview_nd2.py tests\test_merge_and_crop.py
```

- Real-data count verification after adding final box padding:

```powershell
C:\Users\neerc\miniconda3\envs\histology\python.exe -c "import sys; sys.path.insert(0, 'src'); from brain_section_pipeline import read_nd2_image; from brain_section_pipeline.crop import detect_section_crops; files=[r'C:\Users\neerc\OneDrive\Documents\RM014_Nikon_260604\Slide_01_x4.nd2', r'C:\Users\neerc\OneDrive\Documents\RM014_Nikon_260604\Slide_02_x4.nd2', r'C:\Users\neerc\OneDrive\Documents\RM014_Nikon_260604\Slide_03_x4.nd2', r'C:\Users\neerc\OneDrive\Documents\RM014_Nikon_260604\Slide_04_x4.nd2', r'C:\Users\neerc\OneDrive\Documents\RM014_Nikon_260604\Slide_05_x4.nd2']; [print(path.split('\\\\')[-1], len(detect_section_crops(read_nd2_image(path, downsample=64).data, min_area=max(100, 1000000 // (64**2)), margin=max(5, 250 // 64), opening_radius=0, closing_iterations=max(1, 160 // 64), mask_channel=0, sort_mode='row_right_to_left', final_box_padding=1).boxes)) for path in files]"
```

- `Slide_01_x4.nd2` preview refresh command with final box padding:

```powershell
C:\Users\neerc\miniconda3\envs\histology\python.exe scripts\preview_nd2.py "C:\Users\neerc\OneDrive\Documents\RM014_Nikon_260604\Slide_01_x4.nd2" --output outputs\RM014_Slide01_preview_padded --downsample 64 --min-area 1000000 --margin 250 --closing-iterations 160 --mask-channel 0 --sort-mode row_right_to_left --final-box-padding 1
```

- Refreshed full-preview command after the `Slide_01` retune:

```powershell
C:\Users\neerc\miniconda3\envs\histology\python.exe scripts\preview_nd2.py "C:\Users\neerc\OneDrive\Documents\RM014_Nikon_260604" --output outputs\RM014_preview_all_rerun_v3 --downsample 64 --min-area 1000000 --margin 250 --closing-iterations 160 --mask-channel 0 --sort-mode row_right_to_left
```

- Real-data preview refresh command after the regression fix:

```powershell
C:\Users\neerc\miniconda3\envs\histology\python.exe scripts\preview_nd2.py "C:\Users\neerc\OneDrive\Documents\RM014_Nikon_260604\Slide_05_x4.nd2" --output outputs\RM014_preview_all_rerun_v2 --downsample 64 --min-area 1000000 --margin 250 --closing-iterations 160 --mask-channel 0 --sort-mode row_right_to_left
```

- Attempted focused crop-test command after the regression fix:

```powershell
C:\Users\neerc\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -k "detect_section_crops"
```

- Direct one-slice registration verification was also run in the active
  `histology` environment with a temporary synthetic-check script during this
  session.
- Syntax verification command after adding the slice-wise workflow wrapper:

```powershell
C:\Users\neerc\miniconda3\envs\histology\python.exe -m py_compile src\brain_section_pipeline\workflow.py scripts\run_slicewise_workflow.py src\brain_section_pipeline\__init__.py tests\test_merge_and_crop.py
```

- Import verification command for the new public workflow API:

```powershell
C:\Users\neerc\miniconda3\envs\histology\python.exe -c "import sys; sys.path.insert(0, 'src'); from brain_section_pipeline import run_slicewise_atlas_workflow, SliceWorkflowResult; print(callable(run_slicewise_atlas_workflow), SliceWorkflowResult.__name__)"
```

- Attempted focused workflow-test command:

```powershell
C:\Users\neerc\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -k run_slicewise_atlas_workflow
```
- Direct atlas-summary verification was run in the active `histology`
  environment on a synthetic two-section registration manifest, producing:
  - 4 per-section region rows;
  - an aggregate CSV with region 1 `intensity_sum=10.0`,
    `intensity_mean=2.5`;
  - an aggregate CSV with region 2 `intensity_sum=26.0`,
    `intensity_mean=6.5`.
- Real-data preview verification after the crop-fragment merge fix:

```powershell
C:\Users\neerc\miniconda3\envs\histology\python.exe scripts\preview_nd2.py "C:\Users\neerc\OneDrive\Documents\RM014_Nikon_260604\Slide_05_x4.nd2" --output outputs\RM014_Slide05_preview_merged --downsample 64 --min-area 1000000 --margin 250 --closing-iterations 160 --mask-channel 0 --sort-mode row_right_to_left
```

## Result Or Observed Behavior

- The code changes were applied successfully.
- Automated test execution could not be completed from this shell session
  reliably through this shell session backend even when using the
  `histology` environment's Python directly, so verification still relies more
  heavily on targeted runtime checks and preview outputs than on captured
  `pytest` output.
- The earlier Windows failure was narrowed to the first slice-registration
  implementation, especially the package import path, the native-backed affine
  warp/resampling path, and covariance/eigendecomposition-based orientation
  estimation.
- After the stability fixes, `import brain_section_pipeline` completed
  normally, a direct `_warp_image(...)` check returned successfully, and the
  one-slice registration verification completed successfully with:
  - `registration_status='ok'`;
  - `registration_dice=0.9820359281437125`;
  - `registration_iou=0.9647058823529412`;
  - `registration_rotation_degrees=-13.973831865020614`.
- The new atlas-summary function completed successfully in the `histology`
  environment and wrote the expected per-section and aggregate CSV outputs on
  synthetic registered slices.
- The real-data preview rerun on `Slide_05_x4.nd2` changed from the incorrect
  3 detected sections to the expected 2 detected sections after the crop-box
  merge fix.
- After tightening the merge rule, the real-data downsampled detection counts
  for the current preview settings became:
  - `Slide_01_x4.nd2`: 6 sections;
  - `Slide_02_x4.nd2`: 4 sections;
  - `Slide_03_x4.nd2`: 4 sections;
  - `Slide_04_x4.nd2`: 4 sections;
  - `Slide_05_x4.nd2`: 2 sections.
- After adding `final_box_padding=1` for preview verification, those counts
  stayed unchanged while `Slide_01_x4.nd2` sections 1 and 3 received slightly
  more crop margin in the refreshed preview.
- The repository now exposes a single sparse-workflow wrapper that should make
  the first faster-PC end-to-end run much easier: one command can now perform
  ND2 section export, atlas pairing, QC generation, registration, and optional
  atlas summaries.
- Focused `pytest` verification of the registration tests remained difficult to
  observe reliably through this shell backend, so the runtime-verification gap
  is smaller than before but not completely closed.

## Known Limitations And Next Steps

- `export_sections_for_brainglobe(...)` prepares BrainGlobe-ready inputs but
  does not yet perform image-registration-based section alignment or execute
  `brainreg`.
- Atlas metadata capture is optional and only runs when
  `brainglobe-atlasapi` is installed in the active environment.
- The new stack builder preserves order and spacing metadata but does not yet
  solve rigid or nonrigid section-to-section alignment.
- The new `brainreg` runner prepares valid inputs and commands, but it does not
  yet validate registration quality or automate orientation selection.
- The new slice-wise atlas QC overlays are coarse bounding-box fits meant for
  review, not final anatomical registrations.
- The new slice-wise registration stage currently assumes the atlas plane has
  already been chosen correctly; it does not yet search across candidate AP
  planes automatically.
- The registration stage currently writes warped sections, overlays, and
  transform metrics and now also writes atlas-region intensity summaries, but
  it does not yet detect objects/cells within regions.
- The registration backend is now intentionally conservative and stability
  first; if later work needs higher-precision transforms, that should be added
  only after verifying it does not reintroduce the Windows crash path.
- The crop detector now handles the observed split-fragment case better, but it
  still uses heuristic box merging and may need more tuning on other slide
  layouts, especially if additional real slides reveal fragment cases with less
  extreme size imbalance.
- The new final-box-padding step is intentionally small and reversible; if it
  proves too loose on other datasets, set `final_box_padding` back to `0`.
- The next implementation step should add either object/cell-level atlas
  summaries or manual/semi-automatic atlas-plane refinement for sparse mode.
