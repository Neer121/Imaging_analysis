"""Suggest atlas slice indices and review overlays for isolated sections."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from brain_section_pipeline import AtlasIndexSuggestionConfig, SliceRegistrationConfig, suggest_atlas_indices


def _parse_float_list(value: str) -> tuple[float, ...]:
    values = [item.strip() for item in value.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("Provide at least one comma-separated float.")
    try:
        return tuple(float(item) for item in values)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid comma-separated float list: {value!r}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Path to section_manifest.csv.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for candidate outputs.")
    parser.add_argument("--atlas", default="whs_sd_rat_39um", help="BrainGlobe atlas name.")
    parser.add_argument("--anatomical-axis", choices=("ap", "si", "dv", "rl", "ml"), default="ap")
    parser.add_argument(
        "--ap-coordinate-system",
        choices=("atlas", "paxinos"),
        default="atlas",
        help=(
            "Coordinate convention for AP inputs/outputs. "
            "'atlas' preserves the existing WHS/native convention; 'paxinos' records values as a "
            "Paxinos/Gaidi-style Bregma AP coordinate while converting to the WHS atlas index."
        ),
    )
    parser.add_argument(
        "--ap-coordinate-offset-mm",
        type=float,
        default=0.0,
        help=(
            "Offset from user AP to WHS/native AP in mm. Used only with --ap-coordinate-system paxinos: "
            "native_ap = user_ap + offset."
        ),
    )
    parser.add_argument("--section-source", choices=("registration", "rgb", "channel"), default="registration")
    parser.add_argument("--channel", type=int, default=None, help="Channel index when --section-source channel is used.")
    parser.add_argument("--sample-id", default=None, help="Optional sample_id filter.")
    parser.add_argument("--ignore-include-flag", action="store_true", help="Include sections even when include_in_stack is false.")
    parser.add_argument("--start-ap-mm", type=float, default=None, help="Approximate AP coordinate for the first selected section.")
    parser.add_argument("--start-slice-index", type=int, default=None, help="Approximate atlas index for the first selected section.")
    parser.add_argument("--section-interval-um", type=float, default=None, help="Physical spacing between selected sections.")
    parser.add_argument("--slice-index-step", type=int, default=0, help="Atlas-index step when section interval is not provided.")
    parser.add_argument("--direction", choices=("posterior", "anterior"), default="posterior")
    parser.add_argument(
        "--selection-strategy",
        choices=("best_score", "spacing_locked"),
        default="best_score",
        help="Use best_score for independent per-section selection or spacing_locked to anchor later sections to the first selected index.",
    )
    parser.add_argument("--search-radius-slices", type=int, default=25)
    parser.add_argument(
        "--search-stride-slices",
        type=int,
        default=1,
        help="Coarse candidate stride for non-anchor searches. Values above 1 enable per-section coarse-to-fine search.",
    )
    parser.add_argument(
        "--search-refine-radius-slices",
        type=int,
        default=None,
        help="Fine search radius around each non-anchor section's best coarse candidate.",
    )
    parser.add_argument(
        "--anchor-search-radius-slices",
        type=int,
        default=None,
        help="Optional first-section search radius. Use this for broad anchor search while keeping later searches small.",
    )
    parser.add_argument(
        "--anchor-search-stride-slices",
        type=int,
        default=1,
        help="Stride for a coarse first-section anchor scan. Values above 1 enable coarse-to-fine anchor search.",
    )
    parser.add_argument(
        "--anchor-refine-radius-slices",
        type=int,
        default=None,
        help="Fine search radius around the best coarse first-section anchor. Defaults to max(search radius, anchor stride).",
    )
    parser.add_argument("--min-ap-mm", type=float, default=None, help="Minimum AP coordinate allowed for candidate atlas planes.")
    parser.add_argument("--max-ap-mm", type=float, default=None, help="Maximum AP coordinate allowed for candidate atlas planes.")
    parser.add_argument("--ap-prior-mm", type=float, default=None, help="Soft AP prior coordinate for candidate scoring.")
    parser.add_argument(
        "--ap-prior-weight",
        type=float,
        default=0.0,
        help="Score penalty per millimeter away from --ap-prior-mm. Defaults to 0.",
    )
    parser.add_argument(
        "--auto-ap-range",
        action="store_true",
        help="Estimate AP bounds from the first section's gross tissue silhouette when manual AP bounds are not provided.",
    )
    parser.add_argument("--auto-ap-range-stride-slices", type=int, default=10)
    parser.add_argument("--auto-ap-range-top-n", type=int, default=5)
    parser.add_argument("--auto-ap-range-padding-mm", type=float, default=0.75)
    parser.add_argument("--auto-ap-range-shape-size", type=int, default=96)
    parser.add_argument("--auto-ap-range-tissue-quantile", type=float, default=0.5)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--tissue-threshold-quantile", type=float, default=0.8)
    parser.add_argument("--max-rotation-degrees", type=float, default=1.0)
    parser.add_argument("--min-scale-factor", type=float, default=0.65)
    parser.add_argument("--max-scale-factor", type=float, default=1.05)
    parser.add_argument("--translation-search-fraction", type=float, default=0.30)
    parser.add_argument(
        "--initial-rotation-degrees",
        type=float,
        default=0.0,
        help="Initial rotation for candidate registration. Default keeps slide orientation neutral.",
    )
    parser.add_argument(
        "--use-mask-orientation-initialization",
        action="store_true",
        help="Initialize rotation from mask moments instead of --initial-rotation-degrees.",
    )
    parser.add_argument(
        "--scale-initialization",
        choices=("bbox_fit", "area"),
        default="bbox_fit",
        help="How to estimate the initial section-to-atlas scale.",
    )
    parser.add_argument(
        "--translation-initialization",
        choices=("crop_center", "tissue_centroid"),
        default="tissue_centroid",
        help="How to initialize translation. tissue_centroid maps section tissue centroid to atlas centroid.",
    )
    parser.add_argument("--area-loss-weight", type=float, default=0.2)
    parser.add_argument("--extent-loss-weight", type=float, default=0.5)
    parser.add_argument("--center-loss-weight", type=float, default=0.8)
    parser.add_argument(
        "--show-crop-background",
        action="store_true",
        help="Show the full warped rectangular crop in candidate overlay PNGs.",
    )
    parser.add_argument("--overlay-mask-threshold-quantile", type=float, default=0.35)
    parser.add_argument("--overlay-mask-dilation-px", type=int, default=10)
    parser.add_argument("--boundary-fit-threshold-quantile", type=float, default=0.35)
    parser.add_argument("--boundary-fit-dilation-px", type=int, default=0)
    parser.add_argument("--boundary-fit-weight", type=float, default=0.25)
    parser.add_argument("--boundary-containment-weight", type=float, default=0.9)
    parser.add_argument(
        "--boundary-distance-weight",
        type=float,
        default=0.35,
        help="Candidate score penalty weight for symmetric section/atlas boundary distance.",
    )
    parser.add_argument(
        "--dorsal-midline-weight",
        type=float,
        default=0.45,
        help="Candidate score penalty weight for dorsal midline notch/anchor mismatch.",
    )
    parser.add_argument(
        "--atlas-plane-angle-search",
        action="store_true",
        help="Search oblique atlas planes by combining each AP candidate with pitch/yaw angle candidates.",
    )
    parser.add_argument(
        "--atlas-plane-pitch-degrees",
        type=_parse_float_list,
        default=(0.0,),
        help="Comma-separated pitch angles in degrees. Pitch varies AP position along the atlas preview vertical axis.",
    )
    parser.add_argument(
        "--atlas-plane-yaw-degrees",
        type=_parse_float_list,
        default=(0.0,),
        help="Comma-separated yaw angles in degrees. Yaw varies AP position along the atlas preview horizontal axis.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    registration_config = SliceRegistrationConfig(
        tissue_threshold_quantile=args.tissue_threshold_quantile,
        max_rotation_degrees=args.max_rotation_degrees,
        min_scale_factor=args.min_scale_factor,
        max_scale_factor=args.max_scale_factor,
        translation_search_fraction=args.translation_search_fraction,
        initial_rotation_degrees=None if args.use_mask_orientation_initialization else args.initial_rotation_degrees,
        scale_initialization=args.scale_initialization,
        translation_initialization=args.translation_initialization,
        area_loss_weight=args.area_loss_weight,
        extent_loss_weight=args.extent_loss_weight,
        center_loss_weight=args.center_loss_weight,
        mask_overlay_to_tissue=not args.show_crop_background,
        overlay_mask_threshold_quantile=args.overlay_mask_threshold_quantile,
        overlay_mask_dilation_px=args.overlay_mask_dilation_px,
        boundary_fit_threshold_quantile=args.boundary_fit_threshold_quantile,
        boundary_fit_dilation_px=args.boundary_fit_dilation_px,
        boundary_fit_weight=args.boundary_fit_weight,
        boundary_containment_weight=args.boundary_containment_weight,
    )
    config = AtlasIndexSuggestionConfig(
        atlas_name=args.atlas,
        anatomical_axis=args.anatomical_axis,
        ap_coordinate_system=args.ap_coordinate_system,
        ap_coordinate_offset_mm=args.ap_coordinate_offset_mm,
        section_source=args.section_source,
        channel=args.channel,
        sample_id=args.sample_id,
        require_include_in_stack=not args.ignore_include_flag,
        start_ap_mm=args.start_ap_mm,
        start_slice_index=args.start_slice_index,
        section_interval_um=args.section_interval_um,
        slice_index_step=args.slice_index_step,
        direction=args.direction,
        selection_strategy=args.selection_strategy,
        search_radius_slices=args.search_radius_slices,
        search_stride_slices=args.search_stride_slices,
        search_refine_radius_slices=args.search_refine_radius_slices,
        anchor_search_radius_slices=args.anchor_search_radius_slices,
        anchor_search_stride_slices=args.anchor_search_stride_slices,
        anchor_refine_radius_slices=args.anchor_refine_radius_slices,
        min_ap_mm=args.min_ap_mm,
        max_ap_mm=args.max_ap_mm,
        ap_prior_mm=args.ap_prior_mm,
        ap_prior_weight=args.ap_prior_weight,
        auto_ap_range=args.auto_ap_range,
        auto_ap_range_stride_slices=args.auto_ap_range_stride_slices,
        auto_ap_range_top_n=args.auto_ap_range_top_n,
        auto_ap_range_padding_mm=args.auto_ap_range_padding_mm,
        auto_ap_range_shape_size=args.auto_ap_range_shape_size,
        auto_ap_range_tissue_quantile=args.auto_ap_range_tissue_quantile,
        top_n=args.top_n,
        boundary_distance_weight=args.boundary_distance_weight,
        dorsal_midline_weight=args.dorsal_midline_weight,
        atlas_plane_angle_search=args.atlas_plane_angle_search,
        atlas_plane_pitch_degrees=args.atlas_plane_pitch_degrees,
        atlas_plane_yaw_degrees=args.atlas_plane_yaw_degrees,
        registration_config=registration_config,
    )
    result = suggest_atlas_indices(args.manifest, args.output_dir, config=config)
    print(f"Atlas-index suggestion directory: {result.output_dir}")
    print(f"Candidate manifest: {result.candidate_manifest_path}")
    print(f"Selected manifest: {result.selected_manifest_path}")
    print(f"Selected choices: {result.selected_choices_path}")
    print(f"Metadata: {result.metadata_path}")
    print(f"Review grids: {len(result.review_grid_paths)}")


if __name__ == "__main__":
    main()
