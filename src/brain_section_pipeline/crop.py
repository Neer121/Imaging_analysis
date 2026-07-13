"""Section detection and crop extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from scipy import ndimage
from skimage import filters, measure, morphology
from tifffile import imwrite

from .merge import sanitize_array


SortMode = Literal["row", "row_left_to_right", "row_right_to_left", "diagonal", "area"]


@dataclass(frozen=True)
class CropBox:
    """Pixel bounds for one crop in y/x coordinates."""

    y0: int
    y1: int
    x0: int
    x1: int
    label: int
    area: int
    centroid_y: float
    centroid_x: float

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    def as_slices(self) -> tuple[slice, slice]:
        return slice(self.y0, self.y1), slice(self.x0, self.x1)

    def to_dict(self, index: int | None = None) -> dict[str, int | float]:
        data: dict[str, int | float] = {
            "label": self.label,
            "y0": self.y0,
            "y1": self.y1,
            "x0": self.x0,
            "x1": self.x1,
            "height": self.height,
            "width": self.width,
            "area": self.area,
            "centroid_y": self.centroid_y,
            "centroid_x": self.centroid_x,
        }
        if index is not None:
            data = {"section_index": index, **data}
        return data


@dataclass(frozen=True)
class CropDetectionResult:
    """Detected crop boxes plus intermediate mask products."""

    boxes: list[CropBox]
    mask: np.ndarray
    labels: np.ndarray
    threshold: float


def detect_section_crops(
    image: np.ndarray,
    *,
    mask_channel: int | None = None,
    min_area: int = 100_000,
    margin: int = 100,
    opening_radius: int = 2,
    closing_iterations: int = 20,
    threshold_method: Literal["otsu", "quantile"] = "otsu",
    threshold_quantile: float = 0.90,
    sort_mode: SortMode = "row",
    row_tolerance: float | None = None,
    merge_box_fragments: bool = True,
    merge_box_gap: int | None = None,
    merge_overlap_fraction: float = 0.5,
    merge_max_area_ratio: float = 0.5,
    final_box_padding: int = 0,
) -> CropDetectionResult:
    """Detect separated tissue sections and return ordered crop boxes."""

    detection_image = _detection_plane(image, mask_channel=mask_channel)
    threshold = _threshold(detection_image, threshold_method, threshold_quantile)
    mask = detection_image > threshold

    if opening_radius > 0:
        mask = morphology.binary_opening(mask, morphology.disk(opening_radius))
    if closing_iterations > 0:
        mask = ndimage.binary_closing(mask, iterations=closing_iterations)
    mask = _remove_small_components(mask.astype(bool), min_area=min_area)
    mask = ndimage.binary_fill_holes(mask)

    labels = measure.label(mask)
    boxes = _boxes_from_labels(labels, min_area=min_area, margin=margin)
    boxes = _drop_nested_boxes(boxes)
    if merge_box_fragments:
        boxes = _merge_close_boxes(
            boxes,
            gap=max(5, margin // 2) if merge_box_gap is None else merge_box_gap,
            min_overlap_fraction=merge_overlap_fraction,
            max_area_ratio=merge_max_area_ratio,
        )
    if final_box_padding > 0:
        boxes = _expand_boxes(boxes, padding=final_box_padding, image_shape=mask.shape)
    boxes = sort_crop_boxes(boxes, image_shape=mask.shape, mode=sort_mode, row_tolerance=row_tolerance)
    return CropDetectionResult(boxes=boxes, mask=mask.astype(bool), labels=labels, threshold=float(threshold))


def crop_sections(image: np.ndarray, boxes: list[CropBox]) -> list[np.ndarray]:
    """Crop an image array with detected boxes."""

    array = np.asarray(image)
    return [_crop_array(array, box) for box in boxes]


def save_crops(
    image: np.ndarray,
    boxes: list[CropBox],
    output_dir: str | Path,
    *,
    stem: str = "section",
    extension: str = "tif",
    start_index: int = 1,
    filename_template: str = "{stem}_section{index:03d}.{extension}",
) -> list[Path]:
    """Save crops and return their paths."""

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, crop in enumerate(crop_sections(image, boxes), start=start_index):
        filename = filename_template.format(stem=stem, index=index, extension=extension)
        path = out_dir / filename
        _write_crop(path, crop)
        paths.append(path)
    return paths


def sort_crop_boxes(
    boxes: list[CropBox],
    *,
    image_shape: tuple[int, int],
    mode: SortMode = "row",
    row_tolerance: float | None = None,
) -> list[CropBox]:
    """Sort crop boxes into stable section order."""

    if mode == "area":
        return sorted(boxes, key=lambda box: (-box.area, box.centroid_y, box.centroid_x))
    if mode == "diagonal":
        height, width = image_shape
        return sorted(boxes, key=lambda box: box.centroid_y * 0.5 + (width - box.centroid_x) * 1.2)
    if mode not in {"row", "row_left_to_right", "row_right_to_left"}:
        raise ValueError("sort_mode must be one of: 'row', 'row_left_to_right', 'row_right_to_left', 'diagonal', 'area'.")

    if not boxes:
        return []
    tolerance = row_tolerance
    if tolerance is None:
        median_height = float(np.median([box.height for box in boxes]))
        tolerance = max(25.0, median_height * 0.5)

    ordered = sorted(boxes, key=lambda box: (box.centroid_y, box.centroid_x))
    rows: list[list[CropBox]] = []
    row_centers: list[float] = []
    for box in ordered:
        for row_index, center in enumerate(row_centers):
            if abs(box.centroid_y - center) <= tolerance:
                rows[row_index].append(box)
                row_centers[row_index] = float(np.mean([item.centroid_y for item in rows[row_index]]))
                break
        else:
            rows.append([box])
            row_centers.append(box.centroid_y)

    reverse_x = mode == "row_right_to_left"
    sorted_rows = [sorted(row, key=lambda box: box.centroid_x, reverse=reverse_x) for row in rows]
    return [box for row in sorted_rows for box in row]


def _detection_plane(image: np.ndarray, *, mask_channel: int | None) -> np.ndarray:
    array = sanitize_array(image)
    if array.ndim == 2:
        return array
    if array.ndim != 3:
        raise ValueError("Detection image must be 2D, RGB, or channel-first.")
    if array.shape[-1] in (3, 4):
        if mask_channel is None:
            return array[..., :3].max(axis=-1)
        return array[..., mask_channel]
    if array.shape[0] <= 8:
        if mask_channel is None:
            return array.max(axis=0)
        return array[mask_channel]
    raise ValueError("Could not infer detection image layout.")


def _crop_array(array: np.ndarray, box: CropBox) -> np.ndarray:
    y_slice, x_slice = box.as_slices()
    if array.ndim == 2:
        return array[y_slice, x_slice]
    if array.ndim == 3 and array.shape[-1] in (3, 4):
        return array[y_slice, x_slice, :]
    if array.ndim >= 3:
        return array[..., y_slice, x_slice]
    raise ValueError("Crop image must be at least 2D.")


def _write_crop(path: Path, crop: np.ndarray) -> None:
    if crop.ndim == 3 and crop.shape[0] <= 8 and crop.shape[-1] not in (3, 4):
        imwrite(
            path,
            crop,
            imagej=True,
            photometric="minisblack",
            metadata={"axes": "CYX", "mode": "composite"},
        )
        return
    imwrite(path, crop)


def _threshold(
    image: np.ndarray,
    method: Literal["otsu", "quantile"],
    quantile: float,
) -> float:
    finite = image[np.isfinite(image)]
    if finite.size == 0:
        return 0.0
    if method == "quantile":
        return float(np.quantile(finite, quantile))
    if method != "otsu":
        raise ValueError("threshold_method must be 'otsu' or 'quantile'.")
    try:
        return float(filters.threshold_otsu(finite))
    except ValueError:
        return float(np.quantile(finite, quantile))


def _boxes_from_labels(labels: np.ndarray, *, min_area: int, margin: int) -> list[CropBox]:
    height, width = labels.shape
    boxes: list[CropBox] = []
    for region in measure.regionprops(labels):
        if region.area < min_area:
            continue
        y0, x0, y1, x1 = region.bbox
        y0 = max(0, y0 - margin)
        x0 = max(0, x0 - margin)
        y1 = min(height, y1 + margin)
        x1 = min(width, x1 + margin)
        boxes.append(
            CropBox(
                y0=int(y0),
                y1=int(y1),
                x0=int(x0),
                x1=int(x1),
                label=int(region.label),
                area=int(region.area),
                centroid_y=float(region.centroid[0]),
                centroid_x=float(region.centroid[1]),
            )
        )
    return boxes


def _remove_small_components(mask: np.ndarray, *, min_area: int) -> np.ndarray:
    labels = measure.label(mask)
    if labels.max() == 0:
        return mask.astype(bool)
    areas = np.bincount(labels.ravel())
    keep = areas >= min_area
    keep[0] = False
    return keep[labels]


def _drop_nested_boxes(boxes: list[CropBox], *, containment_threshold: float = 0.75) -> list[CropBox]:
    keep: list[CropBox] = []
    for index, box in enumerate(boxes):
        box_area = max(1, box.height * box.width)
        nested = False
        for other_index, other in enumerate(boxes):
            if index == other_index:
                continue
            other_area = max(1, other.height * other.width)
            if other_area <= box_area:
                continue
            intersection = _intersection_area(box, other)
            if intersection / box_area >= containment_threshold:
                nested = True
                break
        if not nested:
            keep.append(box)
    return keep


def _merge_close_boxes(
    boxes: list[CropBox],
    *,
    gap: int,
    min_overlap_fraction: float,
    max_area_ratio: float,
) -> list[CropBox]:
    if len(boxes) < 2:
        return list(boxes)

    merged = list(boxes)
    changed = True
    while changed:
        changed = False
        next_boxes: list[CropBox] = []
        consumed = [False] * len(merged)
        for index, box in enumerate(merged):
            if consumed[index]:
                continue
            current = box
            for other_index in range(index + 1, len(merged)):
                if consumed[other_index]:
                    continue
                other = merged[other_index]
                if _should_merge_boxes(
                    current,
                    other,
                    gap=gap,
                    min_overlap_fraction=min_overlap_fraction,
                    max_area_ratio=max_area_ratio,
                ):
                    current = _combine_boxes(current, other)
                    consumed[other_index] = True
                    changed = True
            consumed[index] = True
            next_boxes.append(current)
        merged = next_boxes
    return merged


def _expand_boxes(
    boxes: list[CropBox],
    *,
    padding: int,
    image_shape: tuple[int, int],
) -> list[CropBox]:
    if padding <= 0:
        return list(boxes)
    height, width = image_shape
    expanded: list[CropBox] = []
    for box in boxes:
        expanded.append(
            CropBox(
                y0=max(0, box.y0 - padding),
                y1=min(height, box.y1 + padding),
                x0=max(0, box.x0 - padding),
                x1=min(width, box.x1 + padding),
                label=box.label,
                area=box.area,
                centroid_y=box.centroid_y,
                centroid_x=box.centroid_x,
            )
        )
    return expanded


def _should_merge_boxes(
    first: CropBox,
    second: CropBox,
    *,
    gap: int,
    min_overlap_fraction: float,
    max_area_ratio: float,
) -> bool:
    horizontal_gap = _axis_gap(first.x0, first.x1, second.x0, second.x1)
    vertical_gap = _axis_gap(first.y0, first.y1, second.y0, second.y1)
    horizontal_overlap = _axis_overlap(first.x0, first.x1, second.x0, second.x1)
    vertical_overlap = _axis_overlap(first.y0, first.y1, second.y0, second.y1)

    min_height = max(1, min(first.height, second.height))
    min_width = max(1, min(first.width, second.width))
    vertical_overlap_fraction = vertical_overlap / min_height
    horizontal_overlap_fraction = horizontal_overlap / min_width
    smaller_area = min(first.area, second.area)
    larger_area = max(first.area, second.area, 1)
    smaller_box_area = min(first.height * first.width, second.height * second.width)
    larger_box_area = max(first.height * first.width, second.height * second.width, 1)
    fragment_like = (
        (smaller_area / larger_area) <= max_area_ratio
        or (smaller_box_area / larger_box_area) <= max_area_ratio
    )

    if not fragment_like:
        return False

    if horizontal_gap <= gap and vertical_overlap_fraction >= min_overlap_fraction:
        return True
    if vertical_gap <= gap and horizontal_overlap_fraction >= min_overlap_fraction:
        return True
    return False


def _combine_boxes(first: CropBox, second: CropBox) -> CropBox:
    combined_area = first.area + second.area
    centroid_y = ((first.centroid_y * first.area) + (second.centroid_y * second.area)) / max(1, combined_area)
    centroid_x = ((first.centroid_x * first.area) + (second.centroid_x * second.area)) / max(1, combined_area)
    return CropBox(
        y0=min(first.y0, second.y0),
        y1=max(first.y1, second.y1),
        x0=min(first.x0, second.x0),
        x1=max(first.x1, second.x1),
        label=min(first.label, second.label),
        area=combined_area,
        centroid_y=float(centroid_y),
        centroid_x=float(centroid_x),
    )


def _intersection_area(a: CropBox, b: CropBox) -> int:
    x0 = max(a.x0, b.x0)
    y0 = max(a.y0, b.y0)
    x1 = min(a.x1, b.x1)
    y1 = min(a.y1, b.y1)
    if x1 <= x0 or y1 <= y0:
        return 0
    return (x1 - x0) * (y1 - y0)


def _axis_overlap(a0: int, a1: int, b0: int, b1: int) -> int:
    return max(0, min(a1, b1) - max(a0, b0))


def _axis_gap(a0: int, a1: int, b0: int, b1: int) -> int:
    if _axis_overlap(a0, a1, b0, b1) > 0:
        return 0
    if a1 < b0:
        return b0 - a1
    return a0 - b1
