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
    parser.add_argument("--max-rotation-degrees", type=float, default=0.0, help="Allowed rotation search range around the initial estimate.")
    parser.add_argument("--min-scale-factor", type=float, default=0.8, help="Lower scale bound relative to the initial estimate.")
    parser.add_argument("--max-scale-factor", type=float, default=1.0, help="Upper scale bound relative to the initial estimate.")
    parser.add_argument("--translation-search-fraction", type=float, default=0.25, help="Allowed translation search range as a fraction of atlas height/width.")
    parser.add_argument(
        "--transform-model",
        choices=("similarity", "affine"),
        default="similarity",
        help="Final transform model. affine adds constrained anisotropic scale and shear refinement after similarity fitting.",
    )
    parser.add_argument(
        "--initial-rotation-degrees",
        type=float,
        default=0.0,
        help="Initial rotation for similarity search. Default keeps slide orientation neutral.",
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
    parser.add_argument(
        "--max-affine-anisotropy",
        type=float,
        default=0.10,
        help="Maximum fractional y/x scale imbalance for --transform-model affine.",
    )
    parser.add_argument(
        "--max-affine-shear",
        type=float,
        default=0.04,
        help="Maximum shear coefficient for --transform-model affine.",
    )
    parser.add_argument(
        "--affine-regularization-weight",
        type=float,
        default=0.08,
        help="Penalty weight for affine anisotropy and shear.",
    )
    parser.add_argument("--area-loss-weight", type=float, default=0.2, help="Penalty weight for warped-mask area mismatch.")
    parser.add_argument("--extent-loss-weight", type=float, default=0.8, help="Penalty weight for warped-mask bounding-box mismatch.")
    parser.add_argument("--center-loss-weight", type=float, default=0.4, help="Penalty weight for warped-mask center offset.")
    parser.add_argument(
        "--show-crop-background",
        action="store_true",
        help="Show the full warped rectangular crop in overlay PNGs instead of masking the section display to tissue.",
    )
    parser.add_argument(
        "--overlay-mask-threshold-quantile",
        type=float,
        default=0.45,
        help="Permissive threshold quantile used only to hide crop background in overlay PNGs.",
    )
    parser.add_argument(
        "--overlay-mask-dilation-px",
        type=int,
        default=6,
        help="Pixels of dilation applied to the overlay display mask after thresholding.",
    )
    parser.add_argument(
        "--boundary-fit-threshold-quantile",
        type=float,
        default=0.35,
        help="Lower-threshold quantile used for outer-boundary scale containment during registration.",
    )
    parser.add_argument(
        "--boundary-fit-dilation-px",
        type=int,
        default=0,
        help="Pixels of dilation applied to the outer-boundary fit mask.",
    )
    parser.add_argument(
        "--boundary-fit-weight",
        type=float,
        default=0.35,
        help="Weight for matching the outer slice boundary to the atlas mask.",
    )
    parser.add_argument(
        "--boundary-containment-weight",
        type=float,
        default=1.2,
        help="Weight for penalizing outer slice boundary outside the atlas mask.",
    )
    parser.add_argument(
        "--nonlinear-refinement-model",
        choices=("none", "boundary_spline"),
        default="none",
        help="Optional local boundary refinement after the global similarity/affine fit.",
    )
    parser.add_argument(
        "--nonlinear-max-displacement-px",
        type=float,
        default=8.0,
        help="Maximum cumulative local displacement in atlas pixels for boundary_spline refinement.",
    )
    parser.add_argument(
        "--nonlinear-control-point-spacing-px",
        type=float,
        default=48.0,
        help="Smoothing scale for the boundary_spline displacement field.",
    )
    parser.add_argument(
        "--nonlinear-iterations",
        type=int,
        default=2,
        help="Number of conservative boundary_spline refinement iterations.",
    )
    parser.add_argument(
        "--nonlinear-boundary-sample-step",
        type=int,
        default=3,
        help="Sample every N boundary pixels when estimating the local displacement field.",
    )
    args = parser.parse_args()

    config = SliceRegistrationConfig(
        tissue_threshold_quantile=args.tissue_threshold_quantile,
        max_rotation_degrees=args.max_rotation_degrees,
        min_scale_factor=args.min_scale_factor,
        max_scale_factor=args.max_scale_factor,
        translation_search_fraction=args.translation_search_fraction,
        transform_model=args.transform_model,
        initial_rotation_degrees=None if args.use_mask_orientation_initialization else args.initial_rotation_degrees,
        scale_initialization=args.scale_initialization,
        translation_initialization=args.translation_initialization,
        max_affine_anisotropy=args.max_affine_anisotropy,
        max_affine_shear=args.max_affine_shear,
        affine_regularization_weight=args.affine_regularization_weight,
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
        nonlinear_refinement_model=args.nonlinear_refinement_model,
        nonlinear_max_displacement_px=args.nonlinear_max_displacement_px,
        nonlinear_control_point_spacing_px=args.nonlinear_control_point_spacing_px,
        nonlinear_iterations=args.nonlinear_iterations,
        nonlinear_boundary_sample_step=args.nonlinear_boundary_sample_step,
    )
    result = register_slices_to_atlas(args.pairing_manifest, args.output_dir, config=config)
    print(f"Slice registration output directory: {result.output_dir}")
    print(f"Registration manifest: {result.manifest_path}")
    print(f"Registration metadata: {result.metadata_path}")


if __name__ == "__main__":
    main()
