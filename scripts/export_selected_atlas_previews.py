"""Export atlas-only PNG previews from a selected slice-atlas manifest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brain_section_pipeline import export_selected_atlas_previews


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selected_manifest", type=Path, help="Path to selected_slice_atlas_manifest.csv.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for atlas-only preview PNGs.")
    parser.add_argument(
        "--contact-sheet-name",
        default="selected_atlas_contact_sheet.png",
        help="Filename for the generated atlas-preview contact sheet.",
    )
    args = parser.parse_args()

    result = export_selected_atlas_previews(
        args.selected_manifest,
        args.output_dir,
        contact_sheet_name=args.contact_sheet_name,
    )
    print(f"Atlas preview directory: {result.output_dir}")
    print(f"Preview PNGs: {len(result.preview_paths)}")
    if result.contact_sheet_path is not None:
        print(f"Contact sheet: {result.contact_sheet_path}")


if __name__ == "__main__":
    main()
