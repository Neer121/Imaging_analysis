"""Create downsampled ND2 crop-detection previews."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from brain_section_pipeline import detect_section_crops, find_nd2_files, merge_channels, read_nd2_image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="ND2 file or folder containing ND2 files.")
    parser.add_argument("--output", type=Path, default=Path("demo_previews"))
    parser.add_argument("--downsample", type=int, default=16)
    parser.add_argument("--min-area", type=int, default=1_000_000)
    parser.add_argument("--margin", type=int, default=250)
    parser.add_argument("--closing-iterations", type=int, default=160)
    parser.add_argument("--mask-channel", type=int, default=0)
    parser.add_argument("--final-box-padding", type=int, default=1)
    parser.add_argument(
        "--sort-mode",
        choices=("row", "row_left_to_right", "row_right_to_left", "diagonal", "area"),
        default="row_right_to_left",
    )
    args = parser.parse_args()

    paths = [args.input] if args.input.is_file() else find_nd2_files(args.input)
    args.output.mkdir(parents=True, exist_ok=True)

    for path in paths:
        nd2_image = read_nd2_image(path, downsample=args.downsample)
        rgb = merge_channels(
            nd2_image.data,
            channel_colors=((3 / 255, 81 / 255, 1), (91 / 255, 1, 0), (1, 160 / 255, 0)),
            percentiles=(0.5, 99.8),
        )
        detection = detect_section_crops(
            nd2_image.data if args.mask_channel is not None else rgb,
            mask_channel=args.mask_channel,
            min_area=max(100, args.min_area // (args.downsample**2)),
            margin=max(5, args.margin // args.downsample),
            opening_radius=0,
            closing_iterations=max(1, args.closing_iterations // args.downsample),
            sort_mode=args.sort_mode,
            final_box_padding=args.final_box_padding,
        )

        overlay = Image.fromarray(rgb, mode="RGB")
        draw = ImageDraw.Draw(overlay)
        for index, box in enumerate(detection.boxes, start=1):
            draw.rectangle((box.x0, box.y0, box.x1, box.y1), outline=(255, 64, 64), width=2)
            draw.text((box.x0 + 4, box.y0 + 4), str(index), fill=(255, 255, 0))

        output_path = args.output / f"{path.stem}_preview_ds{args.downsample}.png"
        overlay.save(output_path)
        print(f"{path.name}: {len(detection.boxes)} sections -> {output_path}")


if __name__ == "__main__":
    main()
