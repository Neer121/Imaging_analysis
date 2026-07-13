"""Prepare and optionally run brainreg from stack metadata."""

from __future__ import annotations

import argparse
from pathlib import Path

from brain_section_pipeline import BrainRegConfig, prepare_brainreg_run, run_prepared_brainreg


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stack_metadata", type=Path, help="Path to the stack JSON sidecar created by build_stack_from_manifest.")
    parser.add_argument("--manifest", type=Path, default=None, help="Optional explicit section_manifest.csv path.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for prepared brainreg inputs and outputs.")
    parser.add_argument("--atlas", default=None, help="Atlas name override, e.g. whs_sd_rat_39um.")
    parser.add_argument("--orientation", default=None, help="Orientation override, e.g. asl or psl.")
    parser.add_argument(
        "--additional-channel",
        dest="additional_channels",
        action="append",
        type=int,
        default=None,
        help="Channel index to export as an additional brainreg input. Repeat for multiple channels.",
    )
    parser.add_argument("--sort-input-file", action="store_true", help="Pass --sort-input-file true to brainreg.")
    parser.add_argument("--n-free-cpus", type=int, default=None, help="Number of CPU cores to leave unused.")
    parser.add_argument("--backend", default=None, help="Registration backend override.")
    parser.add_argument("--debug", action="store_true", help="Pass --debug to brainreg.")
    parser.add_argument(
        "--save-original-orientation",
        action="store_true",
        help="Pass --save-original-orientation to brainreg.",
    )
    parser.add_argument(
        "--brain-geometry",
        choices=("full", "hemisphere_l", "hemisphere_r"),
        default="full",
        help="brainreg brain geometry mode.",
    )
    parser.add_argument(
        "--pre-processing",
        choices=("default", "skip"),
        default="default",
        help="brainreg preprocessing mode.",
    )
    parser.add_argument("--execute", action="store_true", help="Execute the prepared brainreg command after preparation.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = BrainRegConfig(
        atlas_name=args.atlas,
        orientation=args.orientation,
        additional_channels=tuple(args.additional_channels or ()),
        sort_input_file=args.sort_input_file,
        n_free_cpus=args.n_free_cpus,
        backend=args.backend,
        debug=args.debug,
        save_original_orientation=args.save_original_orientation,
        brain_geometry=args.brain_geometry,
        pre_processing=args.pre_processing,
    )
    result = prepare_brainreg_run(
        args.stack_metadata,
        args.output_dir,
        manifest_path=args.manifest,
        config=config,
    )
    print(f"Prepared brainreg directory: {result.prepared_dir}")
    print(f"Registration input: {result.registration_input_dir}")
    print(f"brainreg output directory: {result.brainreg_output_dir}")
    print(f"Command script: {result.command_script_path}")
    print("Command:")
    print(" ".join(result.command))

    if args.execute:
        completed = run_prepared_brainreg(result)
        if completed.stdout:
            print(completed.stdout)
        if completed.stderr:
            print(completed.stderr)


if __name__ == "__main__":
    main()
