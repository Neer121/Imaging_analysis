"""Build a manifest-driven TIFF stack for BrainGlobe registration."""

from __future__ import annotations

import argparse
from pathlib import Path

from brain_section_pipeline import StackBuildConfig, build_stack_from_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Path to section_manifest.csv")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for the stack TIFF and metadata JSON.")
    parser.add_argument(
        "--source-kind",
        choices=("registration", "rgb", "channel"),
        default="registration",
        help="Which manifest image source to stack.",
    )
    parser.add_argument("--channel", type=int, default=None, help="Channel index when --source-kind channel is used.")
    parser.add_argument(
        "--placement-mode",
        choices=("center", "original_coords"),
        default="center",
        help="How to place each section on the shared canvas.",
    )
    parser.add_argument(
        "--qc-status",
        dest="qc_statuses",
        action="append",
        default=None,
        help="Allowed QC status. Repeat to allow multiple statuses.",
    )
    parser.add_argument(
        "--ignore-include-flag",
        action="store_true",
        help="Include sections even when include_in_stack is false in the manifest.",
    )
    parser.add_argument("--output-name", default=None, help="Optional explicit stack TIFF filename.")
    parser.add_argument("--output-dtype", default=None, help="Optional numpy dtype name for the output stack.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = StackBuildConfig(
        source_kind=args.source_kind,
        channel=args.channel,
        placement_mode=args.placement_mode,
        allowed_qc_statuses=tuple(args.qc_statuses) if args.qc_statuses is not None else None,
        require_include_in_stack=not args.ignore_include_flag,
        output_dtype=args.output_dtype,
        output_name=args.output_name,
    )
    result = build_stack_from_manifest(args.manifest, args.output_dir, config=config)
    print(f"Stack written to: {result.stack_path}")
    print(f"Metadata written to: {result.metadata_path}")
    print(f"Stack shape (Z, Y, X): {result.stack_shape}")
    print(f"Voxel size (um): {result.voxel_size_um}")


if __name__ == "__main__":
    main()
