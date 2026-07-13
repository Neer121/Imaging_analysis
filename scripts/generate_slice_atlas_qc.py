"""Generate coarse QC overlays for slice-wise atlas pairings."""

from __future__ import annotations

import argparse
from pathlib import Path

from brain_section_pipeline import SliceAtlasQcConfig, generate_slice_atlas_qc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pairing_manifest", type=Path, help="Path to the slice_atlas pairing manifest.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for QC overlay images.")
    parser.add_argument("--overlay-alpha", type=float, default=0.55, help="Blend weight for the transformed section image.")
    parser.add_argument(
        "--tissue-threshold-quantile",
        type=float,
        default=0.80,
        help="Quantile used to derive the section tissue mask.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = SliceAtlasQcConfig(
        overlay_alpha=args.overlay_alpha,
        tissue_threshold_quantile=args.tissue_threshold_quantile,
    )
    result = generate_slice_atlas_qc(args.pairing_manifest, args.output_dir, config=config)
    print(f"QC output directory: {result.output_dir}")
    print(f"QC metadata: {result.metadata_path}")
    print(f"Overlay count: {len(result.overlay_paths)}")


if __name__ == "__main__":
    main()
