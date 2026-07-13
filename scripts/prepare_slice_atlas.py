"""Prepare per-section BrainGlobe atlas planes for sparse slice workflows."""

from __future__ import annotations

import argparse
from pathlib import Path

from brain_section_pipeline import SliceAtlasConfig, prepare_slice_atlas_inputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Path to section_manifest.csv")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for exported atlas planes and pairing metadata.")
    parser.add_argument("--atlas", default="whs_sd_rat_39um", help="BrainGlobe atlas name.")
    parser.add_argument(
        "--anatomical-axis",
        choices=("ap", "si", "dv", "rl", "ml"),
        default="ap",
        help="Anatomical axis to slice along in the atlas.",
    )
    parser.add_argument("--section-source", choices=("registration", "rgb", "channel"), default="registration")
    parser.add_argument("--channel", type=int, default=None, help="Channel index when --section-source channel is used.")
    parser.add_argument("--start-slice-index", type=int, default=0, help="Atlas slice index assigned to the first selected section.")
    parser.add_argument("--slice-index-step", type=int, default=1, help="Step between sequential atlas slice assignments.")
    parser.add_argument("--sample-id", default=None, help="Optional sample_id filter.")
    parser.add_argument("--qc-status", dest="qc_statuses", action="append", default=None, help="Allowed QC status. Repeat to allow multiple.")
    parser.add_argument("--ignore-include-flag", action="store_true", help="Include sections even when include_in_stack is false.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = SliceAtlasConfig(
        atlas_name=args.atlas,
        anatomical_axis=args.anatomical_axis,
        section_source=args.section_source,
        channel=args.channel,
        start_slice_index=args.start_slice_index,
        slice_index_step=args.slice_index_step,
        sample_id=args.sample_id,
        allowed_qc_statuses=tuple(args.qc_statuses) if args.qc_statuses is not None else None,
        require_include_in_stack=not args.ignore_include_flag,
    )
    result = prepare_slice_atlas_inputs(args.manifest, args.output_dir, config=config)
    print(f"Slice-atlas output directory: {result.output_dir}")
    print(f"Pairing manifest: {result.manifest_path}")
    print(f"Metadata: {result.metadata_path}")
    print(f"Prepared sections: {len(result.section_indices)}")


if __name__ == "__main__":
    main()
