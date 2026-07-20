# Large Slide Memory-Safe Export

Date: 2026-07-17

## Goal And Motivation

Allow the sparse slice-wise workflow to process larger ND2 slides such as
`RM014_SampleData/Slide_03_x4.nd2` without allocating a full-resolution
three-channel float RGB canvas.

## Current Problem

Slide 3 failed during section export with:

```text
numpy._core._exceptions._ArrayMemoryError: Unable to allocate 10.0 GiB for an array with shape (21450, 41800, 3) and data type float32
```

The current pipeline calls `merge_channels` for the full slide before crop
detection. That is useful for small previews, but unnecessary for crop
extraction when `crop_output_mode="rgb_direct"` because each RGB crop can be
assembled directly from raw channel slices.

## Why This Is Needed Now

The user asked to run the full process on Slide 3. The crop/export step cannot
complete until the pipeline avoids the full-slide RGB allocation.

## Affected Files

- `src/brain_section_pipeline/pipeline.py`
- `tests/test_merge_and_crop.py`
- `change_log/`

## Public Parameters Or API Changes

Add `preview_max_dim` to `PipelineConfig`.

- When set, full-slide merged preview and crop overlay images are generated at
  a downsampled display size.
- Crop extraction remains full resolution.
- Default behavior remains full-resolution previews unless the caller sets the
  value.

## Expected Behavior

- Large slides can be cropped with `crop_output_mode="rgb_direct"` without
  creating a full-slide RGB crop source.
- Crop overlay coordinates are scaled correctly when using a downsampled
  preview.
- Existing small-slide behavior remains compatible.

## Verification

- Add focused tests for downsampled preview overlay sizing and direct RGB crop
  generation.
- Run focused crop/export tests.
- Rerun Slide 3 export with `preview_max_dim`.

## Non-Goals

- Do not rewrite the ND2 reader for lazy/dask access.
- Do not change atlas registration behavior.
