# Large Slide Detection Plane Memory

Date: 2026-08-28

Git state: uncommitted changes in the working tree.

Implementation plan:
[2026-08-28 Large Slide Detection Plane Memory](../implementation_plan/2026-08-28-large-slide-detection-plane-memory.md)

## What Changed

- Updated `src/brain_section_pipeline/crop.py` so `_detection_plane` selects
  the requested 2D mask channel before sanitizing the image data.
- Added a regression test confirming channel-first detection sanitizes only the
  selected channel plane.

## Why

The Slide 4 export failed because full-resolution crop detection sanitized the
entire 4-channel ND2 array before extracting `mask_channel=0`, causing a large
temporary allocation and memory failure.

## Verification

```powershell
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m py_compile src\brain_section_pipeline\crop.py
C:\Users\Cornell\miniconda3\envs\histology\python.exe -m pytest tests\test_merge_and_crop.py -k "detection_plane_sanitizes_selected_channel_only or preview_source or rgb_direct"
git diff --check
```

Results:

- Focused crop/memory tests: 4 passed.
- `git diff --check` passed with only LF-to-CRLF warnings.

## Result

After this fix, `Slide_04_x4.nd2` crop/export completed and detected 4
sections.

## Known Limitations And Next Steps

- This does not make ND2 reading itself lazy; it avoids the unnecessary
  full-stack temporary allocation during mask-channel detection.
