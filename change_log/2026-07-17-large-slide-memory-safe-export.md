# Large Slide Memory-Safe Export

Date: 2026-07-17

Git state: uncommitted changes in the working tree.

Implementation plan:
[2026-07-17 Large Slide Memory-Safe Export](../implementation_plan/2026-07-17-large-slide-memory-safe-export.md)

## What Changed

- Added `preview_max_dim` to `PipelineConfig`.
- Changed full-slide merged previews to optionally use a downsampled display
  image while keeping crop extraction at full resolution.
- Added direct RGB crop writing from raw channel slices for
  `crop_output_mode="rgb_direct"`, avoiding allocation of a full-slide
  three-channel float canvas.
- Updated crop-overlay drawing so detection boxes are scaled correctly when the
  preview image is downsampled.
- Added focused tests for downsampled previews and direct RGB crop writing.

## Why

`RM014_SampleData/Slide_03_x4.nd2` failed during export because the pipeline
tried to allocate a full-resolution merged RGB array:

```text
numpy._core._exceptions._ArrayMemoryError: Unable to allocate 10.0 GiB for an array with shape (21450, 41800, 3) and data type float32
```

The full-slide RGB image is useful for QC previews, but it is not necessary for
full-resolution section crop extraction.

## Verification

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -k "preview_source or rgb_direct or export_sections_for_brainglobe or raw_channels_to_rgb or save_crops" -q
```

Result: `6 passed, 41 deselected`.

Slide 3 export was rerun with `preview_max_dim=4096`.

Result: completed successfully and detected 4 sections in right-to-left row
order.

## Output Artifacts

- Slide 3 exported sections:
  `outputs/rm014_slide03_full_apminus0p7_to_minus0p9_spacing600um/rm014_slide03`
- Crop QC overlay:
  `outputs/rm014_slide03_full_apminus0p7_to_minus0p9_spacing600um/rm014_slide03/qc/slide_crop_overlays/Slide_03_x4_crops_overlay.png`

## Known Limitations

- This does not make ND2 reading itself lazy; it avoids the unnecessary
  full-slide RGB merge after the ND2 has been loaded.
- Full-resolution previews are still possible if `preview_max_dim` is left
  unset.
