"""Register paired histology sections to atlas planes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brain_section_pipeline import SliceRegistrationConfig, register_slices_to_atlas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pairing_manifest", type=Path, help="Path to the slice_atlas pairing manifest.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for warped sections and registration overlays.")
    parser.add_argument("--tissue-threshold-quantile", type=float, default=0.8, help="Quantile used to derive the section tissue mask.")
    parser.add_argument("--max-rotation-degrees", type=float, default=35.0, help="Allowed rotation search range around the initial estimate.")
    parser.add_argument("--min-scale-factor", type=float, default=0.6, help="Lower scale bound relative to the initial estimate.")
    parser.add_argument("--max-scale-factor", type=float, default=1.6, help="Upper scale bound relative to the initial estimate.")
    parser.add_argument("--translation-search-fraction", type=float, default=0.25, help="Allowed translation search range as a fraction of atlas height/width.")
    args = parser.parse_args()

    config = SliceRegistrationConfig(
        tissue_threshold_quantile=args.tissue_threshold_quantile,
        max_rotation_degrees=args.max_rotation_degrees,
        min_scale_factor=args.min_scale_factor,
        max_scale_factor=args.max_scale_factor,
        translation_search_fraction=args.translation_search_fraction,
    )
    result = register_slices_to_atlas(args.pairing_manifest, args.output_dir, config=config)
    print(f"Slice registration output directory: {result.output_dir}")
    print(f"Registration manifest: {result.manifest_path}")
    print(f"Registration metadata: {result.metadata_path}")


if __name__ == "__main__":
    main()
