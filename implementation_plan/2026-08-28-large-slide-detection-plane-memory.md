# Large Slide Detection Plane Memory

Date: 2026-08-28

## Goal And Motivation

Allow large ND2 slides to complete crop detection when a single mask channel is
requested, without sanitizing the full channel stack first.

## Current Problem

Running `Slide_04_x4.nd2` with full-resolution crop detection and
`mask_channel=0` failed in `_detection_plane`. The code converted the full
4-channel image to float and ran `nan_to_num` before selecting channel 0,
creating a very large temporary allocation.

## Why This Is Needed Now

The requested Slide 4 run cannot proceed until crop detection avoids full-stack
sanitization. The previous large-slide memory-safe export work reduced
full-slide RGB allocation, but this separate mask-channel detection allocation
was still present.

## Affected Files

- `src/brain_section_pipeline/crop.py`
- `tests/test_merge_and_crop.py`
- `implementation_plan/README.md`
- `change_log/`

## Public Parameters Or API Changes

No public API changes.

## Expected Behavior

- If `mask_channel` is supplied, select that 2D channel first and sanitize only
  the selected plane.
- If `mask_channel` is not supplied, preserve the existing RGB/channel-stack
  max-projection behavior.
- Existing crop-detection behavior and output boxes should remain unchanged.

## Verification

- Add a focused test proving channel selection happens before sanitization for
  channel-first images.
- Run the focused crop test.
- Rerun the Slide 4 export.

## Non-Goals

- Do not rewrite ND2 reading to be lazy.
- Do not change crop sorting or merge behavior.
