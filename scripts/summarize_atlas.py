"""Summarize registered slice intensities by atlas region."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brain_section_pipeline import AtlasSummaryConfig, summarize_registered_slices_by_region


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registration_manifest", type=Path, help="Path to the slice-registration manifest.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for atlas summary outputs.")
    parser.add_argument("--include-background", action="store_true", help="Include annotation region 0 in the summary.")
    parser.add_argument("--min-region-pixels", type=int, default=1, help="Minimum number of pixels required to keep a region row.")
    parser.add_argument(
        "--skip-structure-metadata",
        action="store_true",
        help="Do not attempt to attach BrainGlobe structure acronym/name metadata.",
    )
    args = parser.parse_args()

    config = AtlasSummaryConfig(
        include_background=args.include_background,
        min_region_pixels=args.min_region_pixels,
        include_structure_metadata=not args.skip_structure_metadata,
    )
    result = summarize_registered_slices_by_region(args.registration_manifest, args.output_dir, config=config)
    print(f"Atlas summary directory: {result.output_dir}")
    print(f"Per-section summary: {result.per_section_summary_path}")
    print(f"Aggregate summary: {result.aggregate_summary_path}")
    print(f"Metadata: {result.metadata_path}")


if __name__ == "__main__":
    main()
