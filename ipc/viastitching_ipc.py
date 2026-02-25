#!/usr/bin/env python3
"""ViaStitching KiCad 9 IPC backend.

This module provides transactional zone via-array operations using
Board.begin_commit()/push_commit() so undo/redo is one coherent action.

State is stored in a board-embedded metadata text item, keeping ownership
and per-zone settings versioned with the PCB file.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import traceback
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from kipy import KiCad
from kipy.board_types import BoardText, Via, Zone
from kipy.geometry import Vector2

PLUGIN_NAME = "ViaStitching"
PLUGIN_ID = "nils-viastitching"
LOG_FILENAME = "viastitching_ipc.log"
METADATA_PREFIX = "VIASTITCHING_IPC_CONFIG:"
METADATA_VERSION = 1
LEGACY_PLUGIN_KEY = "ViaStitching"
LEGACY_GLOBAL_KEY = "__last_used__"

DEFAULT_ZONE_SETTINGS: Dict[str, Any] = {
    "ViaSize": 0.50,
    "ViaDrill": 0.30,
    "HSpacing": 1.00,
    "VSpacing": 1.00,
    "HOffset": 0.00,
    "VOffset": 0.00,
    "EdgeMargin": 0.00,
    "PadMargin": 0.00,
    "IncludeOtherLayers": True,
    "CenterSegments": True,
    "MaximizeVias": False,
}


class OperationCanceled(Exception):
    pass


def mm_to_nm(mm: float) -> int:
    return int(round(float(mm) * 1_000_000.0))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
    return default


def _item_id(item: Any) -> str:
    if item is None:
        return ""
    try:
        return str(getattr(item, "id", "") or "")
    except Exception:
        return ""


def _vector(x: int, y: int) -> Vector2:
    v = Vector2()
    v.x = int(x)
    v.y = int(y)
    return v


def _vector_xy(value: Any) -> Tuple[int, int]:
    if value is None:
        return (0, 0)
    return (_safe_int(getattr(value, "x", 0)), _safe_int(getattr(value, "y", 0)))


def _zone_polygons(zone: Zone) -> List[Any]:
    filled = getattr(zone, "filled_polygons", None)
    if filled is None:
        return []
    if isinstance(filled, dict):
        out: List[Any] = []
        for _, polys in filled.items():
            out.extend(list(polys or []))
        return out
    return list(filled)


def _polygon_points(poly: Any) -> List[Tuple[int, int]]:
    pts = []
    seq = getattr(poly, "points", None)
    if seq is None:
        return pts
    for p in seq:
        pts.append(_vector_xy(p))
    return pts


def _point_in_polygon(x: int, y: int, poly: Sequence[Tuple[int, int]]) -> bool:
    n = len(poly)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        intersects = (yi > y) != (yj > y)
        if intersects:
            denom = (yj - yi) if (yj - yi) else 1
            x_cross = (xj - xi) * (y - yi) / denom + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def _dist_point_to_segment(x: int, y: int, ax: int, ay: int, bx: int, by: int) -> float:
    vx = bx - ax
    vy = by - ay
    wx = x - ax
    wy = y - ay
    c1 = vx * wx + vy * wy
    if c1 <= 0:
        return math.hypot(x - ax, y - ay)
    c2 = vx * vx + vy * vy
    if c2 <= 0:
        return math.hypot(x - ax, y - ay)
    t = c1 / c2
    if t >= 1:
        return math.hypot(x - bx, y - by)
    px = ax + t * vx
    py = ay + t * vy
    return math.hypot(x - px, y - py)


def _poly_min_edge_distance(x: int, y: int, points: Sequence[Tuple[int, int]]) -> float:
    if len(points) < 2:
        return 1e30
    min_d = 1e30
    last = points[-1]
    for p in points:
        d = _dist_point_to_segment(x, y, last[0], last[1], p[0], p[1])
        if d < min_d:
            min_d = d
        last = p
    return min_d


def _point_inside_zone_with_margin(x: int, y: int, polygons: Sequence[Any], boundary_margin_nm: int) -> bool:
    for poly in polygons:
        outline = _polygon_points(getattr(poly, "outline", None))
        if not outline or not _point_in_polygon(x, y, outline):
            continue

        holes = getattr(poly, "holes", []) or []
        in_hole = False
        for hole in holes:
            hp = _polygon_points(hole)
            if hp and _point_in_polygon(x, y, hp):
                in_hole = True
                break
        if in_hole:
            continue

        if boundary_margin_nm <= 0:
            return True

        if _poly_min_edge_distance(x, y, outline) < boundary_margin_nm:
            continue

        too_close_hole = False
        for hole in holes:
            hp = _polygon_points(hole)
            if hp and _poly_min_edge_distance(x, y, hp) < boundary_margin_nm:
                too_close_hole = True
                break
        if too_close_hole:
            continue

        return True

    return False


def _board_text_items(board: Any) -> List[Any]:
    if hasattr(board, "get_text"):
        return list(board.get_text())
    if hasattr(board, "get_text_items"):
        return list(board.get_text_items())
    return []


def _metadata_json(metadata: Dict[str, Any]) -> str:
    return f"{METADATA_PREFIX}{json.dumps(metadata, sort_keys=True)}"


def _parse_metadata_text(value: str) -> Optional[Dict[str, Any]]:
    if not isinstance(value, str) or not value.startswith(METADATA_PREFIX):
        return None
    payload = value[len(METADATA_PREFIX) :].strip()
    if not payload:
        return None
    try:
        parsed = json.loads(payload)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    parsed.setdefault("version", METADATA_VERSION)
    parsed.setdefault("zones", {})
    if not isinstance(parsed.get("zones"), dict):
        parsed["zones"] = {}
    return parsed


def _find_metadata(board: Any) -> Tuple[Optional[Any], Dict[str, Any], str]:
    for text_item in _board_text_items(board):
        value = getattr(text_item, "value", None)
        parsed = _parse_metadata_text(value)
        if parsed is not None:
            return text_item, parsed, value
    empty = {"version": METADATA_VERSION, "zones": {}}
    return None, empty, _metadata_json(empty)


def _find_legacy_config_blob(board: Any) -> Dict[str, Any]:
    for text_item in _board_text_items(board):
        value = getattr(text_item, "value", None)
        if not isinstance(value, str):
            continue
        value = value.strip()
        if not value.startswith("{"):
            continue
        try:
            parsed = json.loads(value)
        except Exception:
            continue
        if isinstance(parsed, dict) and LEGACY_PLUGIN_KEY in parsed:
            return parsed
    return {}


def _normalize_settings(raw: Dict[str, Any]) -> Dict[str, Any]:
    settings = dict(DEFAULT_ZONE_SETTINGS)
    for key, default_value in DEFAULT_ZONE_SETTINGS.items():
        if key not in raw:
            continue
        if isinstance(default_value, bool):
            settings[key] = _to_bool(raw[key], default_value)
        else:
            settings[key] = _safe_float(raw[key], float(default_value))
    # Backward compatibility with legacy "Clearance" key.
    if "EdgeMargin" not in raw and "Clearance" in raw:
        settings["EdgeMargin"] = _safe_float(raw.get("Clearance"), settings["EdgeMargin"])
    return settings


def _zone_name(zone: Zone) -> str:
    name = getattr(zone, "name", "")
    return str(name) if name is not None else ""


def _load_settings_for_zone(zone: Zone, zone_entry: Dict[str, Any], legacy_blob: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(zone_entry.get("settings"), dict):
        return _normalize_settings(zone_entry["settings"])

    zname = _zone_name(zone)
    if zname and isinstance(legacy_blob.get(zname), dict):
        return _normalize_settings(legacy_blob[zname])

    if isinstance(legacy_blob.get(LEGACY_GLOBAL_KEY), dict):
        return _normalize_settings(legacy_blob[LEGACY_GLOBAL_KEY])

    return dict(DEFAULT_ZONE_SETTINGS)


def _layer_set_of(item: Any) -> set[int]:
    layers = set()
    if hasattr(item, "layers"):
        try:
            for l in list(item.layers):
                layers.add(_safe_int(l))
        except Exception:
            pass
    if not layers and hasattr(item, "layer"):
        layers.add(_safe_int(getattr(item, "layer")))
    return layers


def _is_zone(item: Any) -> bool:
    if item is None:
        return False
    if isinstance(item, Zone):
        return True
    return hasattr(item, "filled_polygons") and hasattr(item, "bounding_box")


def _select_single_zone(board: Any) -> Zone:
    if not hasattr(board, "get_selection"):
        raise RuntimeError("KiCad IPC board API is unavailable (missing get_selection).")
    selection = list(board.get_selection())
    zones = [item for item in selection if _is_zone(item)]
    if not zones:
        raise RuntimeError("Select one filled copper zone first.")
    if len(zones) > 1:
        raise RuntimeError("Select exactly one zone.")
    zone = zones[0]
    if zone.is_rule_area():
        raise RuntimeError("Selected item is a rule area, not a copper zone.")
    return zone


def _zone_net_name(zone: Zone) -> str:
    net = getattr(zone, "net", None)
    if net is None:
        return ""
    return str(getattr(net, "name", "") or "")


def _ensure_zone_filled(board: Any, zone: Zone, allow_refill_prompt: bool = True) -> List[Any]:
    polygons = _zone_polygons(zone)
    if polygons:
        return polygons
    if allow_refill_prompt:
        should_refill = _prompt_yes_no(
            "ViaStitching",
            "Selected zone has no filled copper.\n\nRebuild copper for this zone now?",
            default_no=False,
        )
        if not should_refill:
            raise OperationCanceled("Selected zone is not filled. Operation canceled by user.")
    if not hasattr(board, "refill_zones"):
        raise RuntimeError(
            "Selected zone is not filled, and this KiCad IPC board object cannot refill zones."
        )
    board.refill_zones()
    polygons = _zone_polygons(zone)
    if polygons:
        return polygons
    raise RuntimeError("No filled copper in selected zone after refill.")


def _zone_bbox(zone: Zone) -> Tuple[int, int, int, int]:
    bbox = zone.bounding_box()
    pos = getattr(bbox, "pos", None)
    size = getattr(bbox, "size", None)
    x0 = _safe_int(getattr(pos, "x", 0))
    y0 = _safe_int(getattr(pos, "y", 0))
    sx = _safe_int(getattr(size, "x", 0))
    sy = _safe_int(getattr(size, "y", 0))
    return (x0, y0, x0 + sx, y0 + sy)


def _index_by_id(items: Iterable[Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for item in items:
        item_id = _item_id(item)
        if item_id:
            out[item_id] = item
    return out


def _track_segment(track: Any) -> Optional[Tuple[int, int, int, int, int]]:
    start = getattr(track, "start", None)
    end = getattr(track, "end", None)
    if start is None or end is None:
        return None
    sx, sy = _vector_xy(start)
    ex, ey = _vector_xy(end)
    width = _safe_int(getattr(track, "width", 0))
    return (sx, sy, ex, ey, width)


def _gather_via_obstacles(board: Any, ignore_ids: set[str], target_layers: set[int], include_other_layers: bool) -> List[Tuple[int, int, int]]:
    out: List[Tuple[int, int, int]] = []
    for via in board.get_vias():
        via_id = _item_id(via)
        if via_id in ignore_ids:
            continue
        if not include_other_layers:
            via_layers = _layer_set_of(via)
            if via_layers and via_layers.isdisjoint(target_layers):
                continue
        pos = getattr(via, "position", None)
        if pos is None:
            continue
        x, y = _vector_xy(pos)
        radius = _safe_int(getattr(via, "diameter", 0)) // 2
        out.append((x, y, radius))
    return out


def _gather_pad_obstacles(board: Any, target_layers: set[int], include_other_layers: bool) -> List[Tuple[int, int, int]]:
    out: List[Tuple[int, int, int]] = []
    for pad in board.get_pads():
        if not include_other_layers:
            pad_layers = _layer_set_of(getattr(pad, "padstack", pad))
            if pad_layers and pad_layers.isdisjoint(target_layers):
                continue
        pos = getattr(pad, "position", None)
        if pos is None:
            continue
        x, y = _vector_xy(pos)

        bbox = board.get_item_bounding_box(pad)
        size = getattr(bbox, "size", None) if bbox is not None else None
        rad = max(_safe_int(getattr(size, "x", 0)), _safe_int(getattr(size, "y", 0))) // 2
        if rad <= 0:
            rad = 1
        out.append((x, y, rad))
    return out


def _gather_track_obstacles(board: Any, target_layers: set[int], include_other_layers: bool) -> List[Tuple[int, int, int, int, int]]:
    out: List[Tuple[int, int, int, int, int]] = []
    for track in board.get_tracks():
        if not include_other_layers:
            track_layers = _layer_set_of(track)
            if track_layers and track_layers.isdisjoint(target_layers):
                continue
        seg = _track_segment(track)
        if seg is not None:
            out.append(seg)
    return out


def _conflicts_with_obstacles(
    x: int,
    y: int,
    via_radius: int,
    pad_margin: int,
    via_obstacles: Sequence[Tuple[int, int, int]],
    pad_obstacles: Sequence[Tuple[int, int, int]],
    track_obstacles: Sequence[Tuple[int, int, int, int, int]],
) -> bool:
    own_limit = via_radius + pad_margin

    for ox, oy, orad in via_obstacles:
        min_dist = own_limit + orad
        if math.hypot(x - ox, y - oy) < min_dist:
            return True

    for ox, oy, orad in pad_obstacles:
        min_dist = own_limit + orad
        if math.hypot(x - ox, y - oy) < min_dist:
            return True

    for sx, sy, ex, ey, width in track_obstacles:
        min_dist = own_limit + (width // 2)
        if _dist_point_to_segment(x, y, sx, sy, ex, ey) < min_dist:
            return True

    return False


def _metadata_layer(board: Any) -> int:
    layer = getattr(board, "active_layer", None)
    if layer is not None:
        try:
            return int(layer)
        except Exception:
            pass
    return 0


def _metadata_position(zone: Optional[Zone]) -> Vector2:
    if zone is None:
        return _vector(0, 0)
    x0, y0, _, _ = _zone_bbox(zone)
    return _vector(x0, y0)


def _sync_metadata_item(
    board: Any,
    metadata_item: Optional[Any],
    metadata: Dict[str, Any],
    old_text: str,
    zone_for_new_item: Optional[Zone],
) -> Tuple[bool, Optional[Any]]:
    new_text = _metadata_json(metadata)
    if new_text == old_text and metadata_item is not None:
        return False, metadata_item

    if metadata_item is None:
        item = BoardText()
        item.value = new_text
        item.layer = _metadata_layer(board)
        item.position = _metadata_position(zone_for_new_item)
        item.locked = True
        created = board.create_items([item])
        return True, (created[0] if created else None)

    metadata_item.value = new_text
    board.update_items([metadata_item])
    return True, metadata_item


def _validate_settings(settings: Dict[str, Any]) -> Dict[str, int]:
    via_size = mm_to_nm(_safe_float(settings.get("ViaSize"), 0.0))
    via_drill = mm_to_nm(_safe_float(settings.get("ViaDrill"), 0.0))
    step_x = mm_to_nm(_safe_float(settings.get("HSpacing"), 0.0))
    step_y = mm_to_nm(_safe_float(settings.get("VSpacing"), 0.0))
    off_x = mm_to_nm(_safe_float(settings.get("HOffset"), 0.0))
    off_y = mm_to_nm(_safe_float(settings.get("VOffset"), 0.0))
    edge_margin = mm_to_nm(_safe_float(settings.get("EdgeMargin"), 0.0))
    pad_margin = mm_to_nm(_safe_float(settings.get("PadMargin"), 0.0))

    if via_size <= 0 or via_drill <= 0:
        raise RuntimeError("Via size and drill must be > 0.")
    if via_drill >= via_size:
        raise RuntimeError("Via drill must be smaller than via size.")
    if step_x <= 0 or step_y <= 0:
        raise RuntimeError("HSpacing and VSpacing must be > 0.")
    if edge_margin < 0 or pad_margin < 0:
        raise RuntimeError("Margins cannot be negative.")

    return {
        "via_size": via_size,
        "via_drill": via_drill,
        "step_x": step_x,
        "step_y": step_y,
        "off_x": off_x,
        "off_y": off_y,
        "edge_margin": edge_margin,
        "pad_margin": pad_margin,
    }


def _phase_offsets(step: int, base_offset: int, samples: int) -> List[int]:
    if step <= 0:
        return [0]
    out = {int(base_offset % step)}
    if samples > 1:
        for i in range(samples):
            out.add(int((i * step) // samples))
    return sorted(out)


def _edge_intersections_x(points: Sequence[Tuple[int, int]], y: int) -> List[float]:
    xs: List[float] = []
    n = len(points)
    if n < 3:
        return xs

    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        if y1 == y2:
            continue
        if (y1 <= y < y2) or (y2 <= y < y1):
            t = (y - y1) / float(y2 - y1)
            xs.append(x1 + t * (x2 - x1))
    xs.sort()
    return xs


def _intervals_from_ring(points: Sequence[Tuple[int, int]], y: int) -> List[Tuple[float, float]]:
    xs = _edge_intersections_x(points, y)
    intervals: List[Tuple[float, float]] = []
    for i in range(0, len(xs) - 1, 2):
        a = xs[i]
        b = xs[i + 1]
        if b > a:
            intervals.append((a, b))
    return intervals


def _merge_intervals(intervals: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    if not intervals:
        return []
    items = sorted(intervals, key=lambda t: (t[0], t[1]))
    merged: List[Tuple[float, float]] = [items[0]]
    for a, b in items[1:]:
        la, lb = merged[-1]
        if a <= lb:
            merged[-1] = (la, max(lb, b))
        else:
            merged.append((a, b))
    return merged


def _subtract_intervals(
    base: Sequence[Tuple[float, float]],
    cuts: Sequence[Tuple[float, float]],
) -> List[Tuple[float, float]]:
    if not base:
        return []
    if not cuts:
        return list(base)

    out: List[Tuple[float, float]] = []
    cuts_merged = _merge_intervals(cuts)
    for a, b in base:
        cur = a
        for ca, cb in cuts_merged:
            if cb <= cur:
                continue
            if ca >= b:
                break
            if ca > cur:
                out.append((cur, min(ca, b)))
            cur = max(cur, cb)
            if cur >= b:
                break
        if cur < b:
            out.append((cur, b))
    return out


def _row_intervals(polygons: Sequence[Any], y: int) -> List[Tuple[float, float]]:
    intervals: List[Tuple[float, float]] = []
    for poly in polygons:
        outline_pts = _polygon_points(getattr(poly, "outline", None))
        if len(outline_pts) < 3:
            continue

        filled = _intervals_from_ring(outline_pts, y)
        if not filled:
            continue

        hole_intervals: List[Tuple[float, float]] = []
        for hole in (getattr(poly, "holes", []) or []):
            hole_pts = _polygon_points(hole)
            if len(hole_pts) < 3:
                continue
            hole_intervals.extend(_intervals_from_ring(hole_pts, y))

        if hole_intervals:
            filled = _subtract_intervals(filled, hole_intervals)

        intervals.extend(filled)
    return _merge_intervals(intervals)


def _grid_points_in_interval(a: float, b: float, start_x: int, step_x: int) -> List[int]:
    left = int(math.ceil(a))
    right = int(math.floor(b))
    if right < left:
        return []

    k = int(math.ceil((left - start_x) / float(step_x)))
    x = start_x + k * step_x
    pts: List[int] = []
    while x <= right:
        pts.append(int(x))
        x += step_x
    return pts


def _centered_points_in_interval(a: float, b: float, step_x: int, n: int) -> List[int]:
    if n <= 0:
        return []
    span = b - a
    used = (n - 1) * step_x
    x0 = a + 0.5 * (span - used)
    return [int(round(x0 + i * step_x)) for i in range(n)]


def _row_segment_points(
    intervals: Sequence[Tuple[float, float]],
    step_x: int,
    start_x: int,
    center_segments: bool,
    maximize_vias: bool,
) -> List[int]:
    row_points: List[int] = []
    for a, b in intervals:
        if b < a:
            continue
        grid_pts = _grid_points_in_interval(a, b, start_x, step_x)
        if not center_segments:
            row_points.extend(grid_pts)
            continue

        if maximize_vias:
            n = int(math.floor((b - a) / float(step_x))) + 1
        else:
            n = len(grid_pts)

        if n <= 0:
            continue
        row_points.extend(_centered_points_in_interval(a, b, step_x, n))

    # De-duplicate and keep deterministic order.
    return sorted(set(row_points))


def _build_candidates_for_phase(
    zone: Zone,
    polygons: Sequence[Any],
    dims: Dict[str, int],
    via_obstacles_seed: Sequence[Tuple[int, int, int]],
    pad_obstacles: Sequence[Tuple[int, int, int]],
    track_obstacles: Sequence[Tuple[int, int, int, int, int]],
    phase_x: int,
    phase_y: int,
    center_segments: bool,
    maximize_vias: bool,
) -> Tuple[List[Via], Dict[str, int]]:
    via_radius = dims["via_size"] // 2
    via_obstacles = list(via_obstacles_seed)

    x0, y0, x1, y1 = _zone_bbox(zone)
    start_x = x0 + ((phase_x - x0) % dims["step_x"])
    start_y = y0 + ((phase_y - y0) % dims["step_y"])

    stats = {
        "candidates_tested": 0,
        "inside": 0,
        "rejected_overlap": 0,
        "rejected_edge": 0,
    }
    new_vias: List[Via] = []

    y = start_y
    while y <= y1:
        intervals = _row_intervals(polygons, y)
        row_points = _row_segment_points(
            intervals=intervals,
            step_x=dims["step_x"],
            start_x=start_x,
            center_segments=center_segments,
            maximize_vias=maximize_vias,
        )

        for x in row_points:
            stats["candidates_tested"] += 1
            boundary_margin = via_radius + dims["edge_margin"]
            if not _point_inside_zone_with_margin(x, y, polygons, boundary_margin):
                stats["rejected_edge"] += 1
                continue

            stats["inside"] += 1
            if _conflicts_with_obstacles(
                x=x,
                y=y,
                via_radius=via_radius,
                pad_margin=dims["pad_margin"],
                via_obstacles=via_obstacles,
                pad_obstacles=pad_obstacles,
                track_obstacles=track_obstacles,
            ):
                stats["rejected_overlap"] += 1
                continue

            via = Via()
            via.position = _vector(x, y)
            via.diameter = dims["via_size"]
            via.drill_diameter = dims["via_drill"]
            via.net = zone.net
            new_vias.append(via)
            via_obstacles.append((x, y, via_radius))

        y += dims["step_y"]

    return new_vias, stats


def _build_candidates(
    board: Any,
    zone: Zone,
    polygons: Sequence[Any],
    dims: Dict[str, int],
    ignore_owned_ids: set[str],
    include_other_layers: bool,
    center_segments: bool,
    maximize_vias: bool,
) -> Tuple[List[Via], Dict[str, int]]:
    zone_layers = _layer_set_of(zone)
    via_obstacles_seed = _gather_via_obstacles(board, ignore_owned_ids, zone_layers, include_other_layers)
    pad_obstacles = _gather_pad_obstacles(board, zone_layers, include_other_layers)
    track_obstacles = _gather_track_obstacles(board, zone_layers, include_other_layers)

    x_phase_samples = 1
    y_phase_samples = 1
    if maximize_vias:
        y_phase_samples = 8
        if not center_segments:
            x_phase_samples = 6

    x_offsets = _phase_offsets(dims["step_x"], dims["off_x"], x_phase_samples)
    y_offsets = _phase_offsets(dims["step_y"], dims["off_y"], y_phase_samples)

    best_vias: List[Via] = []
    best_stats: Dict[str, int] = {
        "candidates_tested": 0,
        "inside": 0,
        "rejected_overlap": 0,
        "rejected_edge": 0,
    }
    best_score: Optional[Tuple[int, int, int, int]] = None

    for phase_y in y_offsets:
        for phase_x in x_offsets:
            vias, stats = _build_candidates_for_phase(
                zone=zone,
                polygons=polygons,
                dims=dims,
                via_obstacles_seed=via_obstacles_seed,
                pad_obstacles=pad_obstacles,
                track_obstacles=track_obstacles,
                phase_x=phase_x,
                phase_y=phase_y,
                center_segments=center_segments,
                maximize_vias=maximize_vias,
            )

            # Prefer most vias; then fewer total rejections; then fewer edge rejects.
            score = (
                len(vias),
                -(stats["rejected_overlap"] + stats["rejected_edge"]),
                -stats["rejected_edge"],
                -phase_y,
            )
            if best_score is None or score > best_score:
                best_score = score
                best_vias = vias
                best_stats = stats

    return best_vias, best_stats


def _via_inside_zone(via: Any, zone_polygons: Sequence[Any]) -> bool:
    pos = getattr(via, "position", None)
    if pos is None:
        return False
    x, y = _vector_xy(pos)
    return _point_inside_zone_with_margin(x, y, zone_polygons, 0)


def _via_net_name(via: Any) -> str:
    net = getattr(via, "net", None)
    if net is None:
        return ""
    return str(getattr(net, "name", "") or "")


def _vias_on_zone_net_inside(
    board: Any,
    zone: Zone,
    polygons: Sequence[Any],
    exclude_ids: Optional[set[str]] = None,
) -> List[Any]:
    zone_net = _zone_net_name(zone)
    if not zone_net:
        return []
    exclude_ids = exclude_ids or set()
    vias: List[Any] = []
    for via in board.get_vias():
        via_id = _item_id(via)
        if via_id and via_id in exclude_ids:
            continue
        if _via_net_name(via) != zone_net:
            continue
        if _via_inside_zone(via, polygons):
            vias.append(via)
    return vias


class Runtime:
    def __init__(self, kicad: KiCad) -> None:
        self.kicad = kicad
        self.log_path = self._resolve_log_path()

    def _resolve_log_path(self) -> str:
        path = self.kicad.get_plugin_settings_path(PLUGIN_ID)
        path = str(path) if path is not None else ""
        if not path:
            path = os.path.join(os.path.expanduser("~"), ".config", "viastitching")
        os.makedirs(path, exist_ok=True)
        return os.path.join(path, LOG_FILENAME)

    def log(self, message: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {message}\n")


def _require_board_api(board: Any) -> None:
    required = [
        "begin_commit",
        "push_commit",
        "drop_commit",
        "get_selection",
        "get_zones",
        "get_vias",
        "get_tracks",
        "get_pads",
        "create_items",
        "remove_items",
        "update_items",
    ]
    missing = [name for name in required if not hasattr(board, name)]
    if missing:
        missing_str = ", ".join(missing)
        raise RuntimeError(
            "KiCad IPC board API is incomplete for ViaStitching. "
            f"Missing methods: {missing_str}. "
            "Enable KiCad API in Preferences -> Plugins and run ViaStitching via plugin.json actions."
        )


def _open_log_folder(path: str) -> bool:
    folder = os.path.dirname(path)
    if not folder:
        return False
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", folder])
            return True
        if os.name == "nt":
            os.startfile(folder)
            return True
        subprocess.Popen(["xdg-open", folder])
        return True
    except Exception:
        return False


def _show_error_with_log(title: str, message: str, log_path: str) -> None:
    prompt = f"{message}\n\nLog file:\n{log_path}\n\nOpen log folder?"
    try:
        import wx  # type: ignore

        dlg = wx.MessageDialog(None, prompt, title, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_ERROR)
        if hasattr(dlg, "SetYesNoLabels"):
            dlg.SetYesNoLabels("Open Log Folder", "Close")
        result = dlg.ShowModal()
        dlg.Destroy()
        if result == wx.ID_YES:
            _open_log_folder(log_path)
        return
    except Exception:
        pass
    print(f"{title}: {prompt}", file=sys.stderr)


def _prompt_yes_no(title: str, message: str, default_no: bool = True) -> bool:
    try:
        import wx  # type: ignore

        style = wx.YES_NO | wx.ICON_QUESTION
        if default_no:
            style |= wx.NO_DEFAULT
        return wx.MessageBox(message, title, style) == wx.YES
    except Exception:
        return not default_no


def _format_mm(value: Any, fallback: float) -> str:
    v = _safe_float(value, fallback)
    text = f"{v:.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _prompt_zone_settings(
    zone: Zone,
    settings: Dict[str, Any],
    force_maximize: Optional[bool],
    force_center_segments: Optional[bool],
) -> Dict[str, Any]:
    try:
        import wx  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"Unable to open settings dialog (wx unavailable): {exc}")

    dlg = wx.Dialog(None, title=f"{PLUGIN_NAME}: Zone Settings", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
    root = wx.BoxSizer(wx.VERTICAL)

    zone_name = _zone_name(zone) or "(unnamed zone)"
    zone_net = _zone_net_name(zone) or "(no net)"
    hdr = wx.StaticText(dlg, label=f"Zone: {zone_name}")
    net = wx.TextCtrl(dlg, value=zone_net, style=wx.TE_READONLY)
    hdr.SetToolTip("Currently selected zone name.")
    net.SetToolTip("Net is derived from selected zone and cannot be edited.")
    root.Add(hdr, 0, wx.ALL | wx.EXPAND, 8)
    root.Add(net, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

    grid = wx.FlexGridSizer(0, 2, 6, 8)
    grid.AddGrowableCol(1, 1)
    fields = [
        ("Via size (mm)", "ViaSize", "Via outer diameter."),
        ("Via drill (mm)", "ViaDrill", "Via drill diameter. Must be smaller than via size."),
        ("Horizontal spacing (mm)", "HSpacing", "Horizontal center-to-center spacing."),
        ("Vertical spacing (mm)", "VSpacing", "Vertical center-to-center spacing."),
        ("Horizontal offset (mm)", "HOffset", "Horizontal grid offset."),
        ("Vertical offset (mm)", "VOffset", "Vertical grid offset."),
        ("Edge margin (mm)", "EdgeMargin", "Extra distance from via edge to zone boundary."),
        ("Pad margin (mm)", "PadMargin", "Extra spacing used against pads/tracks/vias."),
    ]
    controls: Dict[str, Any] = {}
    for label, key, tip in fields:
        txt_label = wx.StaticText(dlg, label=label)
        txt_value = wx.TextCtrl(dlg, value=_format_mm(settings.get(key), DEFAULT_ZONE_SETTINGS[key]))
        txt_label.SetToolTip(tip)
        txt_value.SetToolTip(tip)
        grid.Add(txt_label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(txt_value, 1, wx.EXPAND)
        controls[key] = txt_value
    root.Add(grid, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

    chk_include_layers = wx.CheckBox(dlg, label="Check overlaps on all copper layers")
    chk_include_layers.SetValue(_to_bool(settings.get("IncludeOtherLayers"), True))
    chk_include_layers.SetToolTip("Disable to only check overlaps on the selected zone layer(s).")
    root.Add(chk_include_layers, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

    chk_center_segments = wx.CheckBox(dlg, label="Center local segments")
    chk_center_segments.SetValue(_to_bool(settings.get("CenterSegments"), True))
    chk_center_segments.SetToolTip("Center vias within each reachable row segment.")
    if force_center_segments is not None:
        chk_center_segments.SetValue(bool(force_center_segments))
        chk_center_segments.Enable(False)
    root.Add(chk_center_segments, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

    chk_maximize = wx.CheckBox(dlg, label="Try to maximize vias")
    chk_maximize.SetValue(_to_bool(settings.get("MaximizeVias"), False))
    chk_maximize.SetToolTip("Search multiple grid phases to maximize via count while respecting margins.")
    if force_maximize is not None:
        chk_maximize.SetValue(bool(force_maximize))
        chk_maximize.Enable(False)
    root.Add(chk_maximize, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

    buttons = wx.StdDialogButtonSizer()
    btn_cancel = wx.Button(dlg, wx.ID_CANCEL, "Cancel")
    btn_ok = wx.Button(dlg, wx.ID_OK, "OK")
    buttons.AddButton(btn_cancel)
    buttons.AddButton(btn_ok)
    buttons.Realize()
    root.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

    dlg.SetSizer(root)
    dlg.SetMinSize((560, 0))
    dlg.Fit()
    dlg.CentreOnScreen()

    while True:
        result = dlg.ShowModal()
        if result != wx.ID_OK:
            dlg.Destroy()
            raise OperationCanceled("Operation canceled by user.")

        parsed: Dict[str, Any] = dict(DEFAULT_ZONE_SETTINGS)
        bad_value = False
        for _, key, _ in fields:
            text = controls[key].GetValue()
            try:
                parsed[key] = float(text)
            except Exception:
                bad_value = True
                break
        if bad_value:
            wx.MessageBox("Enter valid numeric values for all dimensions.", PLUGIN_NAME, wx.OK | wx.ICON_ERROR)
            continue

        parsed["IncludeOtherLayers"] = bool(chk_include_layers.GetValue())
        parsed["CenterSegments"] = bool(chk_center_segments.GetValue())
        parsed["MaximizeVias"] = bool(chk_maximize.GetValue())

        try:
            _validate_settings(parsed)
        except Exception as exc:
            wx.MessageBox(str(exc), PLUGIN_NAME, wx.OK | wx.ICON_ERROR)
            continue

        dlg.Destroy()
        return parsed


def _update_zone_array(
    runtime: Runtime,
    board: Any,
    zone: Zone,
    force_maximize: Optional[bool] = None,
    force_center_segments: Optional[bool] = None,
) -> Dict[str, int]:
    polygons = _ensure_zone_filled(board, zone, allow_refill_prompt=True)
    metadata_item, metadata, old_meta_text = _find_metadata(board)
    legacy_blob = _find_legacy_config_blob(board)

    zone_id = _item_id(zone)
    if not zone_id:
        raise RuntimeError("Selected zone does not expose a stable ID.")

    zones = metadata.setdefault("zones", {})
    zone_entry = zones.get(zone_id)
    if not isinstance(zone_entry, dict):
        zone_entry = {}
        zones[zone_id] = zone_entry

    settings = _load_settings_for_zone(zone, zone_entry, legacy_blob)
    settings = _prompt_zone_settings(
        zone=zone,
        settings=settings,
        force_maximize=force_maximize,
        force_center_segments=force_center_segments,
    )
    dims = _validate_settings(settings)
    include_other_layers = _to_bool(settings.get("IncludeOtherLayers"), True)
    center_segments = _to_bool(settings.get("CenterSegments"), True)
    maximize_vias = _to_bool(settings.get("MaximizeVias"), False)
    if force_center_segments is not None:
        center_segments = bool(force_center_segments)
        settings["CenterSegments"] = center_segments
    if force_maximize is not None:
        maximize_vias = bool(force_maximize)
        settings["MaximizeVias"] = maximize_vias

    owned_ids = [str(v) for v in (zone_entry.get("owned_via_ids") or []) if str(v)]
    via_by_id = _index_by_id(board.get_vias())
    owned_vias = [via_by_id[vid] for vid in owned_ids if vid in via_by_id]
    owned_id_set = set(owned_ids)

    user_vias = _vias_on_zone_net_inside(board, zone, polygons, exclude_ids=owned_id_set)
    user_via_ids = {_item_id(via) for via in user_vias if _item_id(via)}
    replace_user_vias = False
    if user_vias:
        replace_user_vias = _prompt_yes_no(
            PLUGIN_NAME,
            "User-placed vias were detected on the selected zone net inside this zone.\n\n"
            "Replace those vias with plugin vias?",
            default_no=True,
        )

    ignore_ids = set(owned_id_set)
    if replace_user_vias:
        ignore_ids |= user_via_ids

    new_vias, stats = _build_candidates(
        board=board,
        zone=zone,
        polygons=polygons,
        dims=dims,
        ignore_owned_ids=ignore_ids,
        include_other_layers=include_other_layers,
        center_segments=center_segments,
        maximize_vias=maximize_vias,
    )

    if not new_vias:
        raise RuntimeError(
            "No vias placed.\n"
            f"Candidate points tested: {stats['candidates_tested']}\n"
            f"Points inside selected zone copper: {stats['inside']}\n"
            f"Rejected by overlap/pad-margin checks: {stats['rejected_overlap']}\n"
            f"Rejected by edge margin checks: {stats['rejected_edge']}"
        )

    commit = board.begin_commit()
    pushed = False
    try:
        vias_to_remove = list(owned_vias)
        if replace_user_vias and user_vias:
            vias_to_remove.extend(user_vias)
        if vias_to_remove:
            vias_to_remove = list(_index_by_id(vias_to_remove).values())
            board.remove_items(vias_to_remove)

        created_vias = list(board.create_items(new_vias))
        created_ids = [_item_id(via) for via in created_vias if _item_id(via)]

        zone_entry["zone_name"] = _zone_name(zone)
        zone_entry["settings"] = settings
        zone_entry["owned_via_ids"] = created_ids

        meta_changed, _ = _sync_metadata_item(
            board=board,
            metadata_item=metadata_item,
            metadata=metadata,
            old_text=old_meta_text,
            zone_for_new_item=zone,
        )

        if vias_to_remove or created_vias or meta_changed:
            board.push_commit(commit, "ViaStitching: Update Array")
            pushed = True
        else:
            board.drop_commit(commit)

        return {
            "removed_old": len(owned_vias),
            "removed_user": len(user_vias) if replace_user_vias else 0,
            "placed": len(created_vias),
            "candidates_tested": stats["candidates_tested"],
            "inside": stats["inside"],
            "rejected_overlap": stats["rejected_overlap"],
            "rejected_edge": stats["rejected_edge"],
        }
    except Exception:
        if not pushed:
            board.drop_commit(commit)
        raise


def _remove_zone_array(runtime: Runtime, board: Any, zone: Zone) -> Dict[str, int]:
    metadata_item, metadata, old_meta_text = _find_metadata(board)
    zone_id = _item_id(zone)
    zones = metadata.setdefault("zones", {})
    zone_entry = zones.get(zone_id) if isinstance(zones, dict) else None

    if not isinstance(zone_entry, dict):
        return {"removed": 0}

    owned_ids = [str(v) for v in (zone_entry.get("owned_via_ids") or []) if str(v)]
    via_by_id = _index_by_id(board.get_vias())
    owned_vias = [via_by_id[vid] for vid in owned_ids if vid in via_by_id]
    owned_id_set = set(owned_ids)

    if not owned_vias and not owned_ids:
        return {"removed": 0}

    polygons = _zone_polygons(zone)
    remove_user_vias = False
    user_vias: List[Any] = []
    if polygons:
        user_vias = _vias_on_zone_net_inside(board, zone, polygons, exclude_ids=owned_id_set)
        if user_vias:
            remove_user_vias = _prompt_yes_no(
                PLUGIN_NAME,
                "User-placed vias were detected on the selected zone net inside this zone.\n\n"
                "Remove those user vias too?",
                default_no=True,
            )

    commit = board.begin_commit()
    pushed = False
    try:
        vias_to_remove = list(owned_vias)
        if remove_user_vias and user_vias:
            vias_to_remove.extend(user_vias)
        vias_to_remove = list(_index_by_id(vias_to_remove).values())
        if vias_to_remove:
            board.remove_items(vias_to_remove)

        zone_entry["owned_via_ids"] = []
        zone_entry["zone_name"] = _zone_name(zone)

        meta_changed, _ = _sync_metadata_item(
            board=board,
            metadata_item=metadata_item,
            metadata=metadata,
            old_text=old_meta_text,
            zone_for_new_item=zone,
        )

        if vias_to_remove or meta_changed:
            board.push_commit(commit, "ViaStitching: Remove Array")
            pushed = True
        else:
            board.drop_commit(commit)

        return {
            "removed": len(owned_vias),
            "removed_user": len(user_vias) if remove_user_vias else 0,
        }
    except Exception:
        if not pushed:
            board.drop_commit(commit)
        raise


def _clean_orphans(runtime: Runtime, board: Any) -> Dict[str, int]:
    metadata_item, metadata, old_meta_text = _find_metadata(board)
    zones_meta = metadata.setdefault("zones", {})
    if not isinstance(zones_meta, dict) or not zones_meta:
        return {"removed": 0, "cleaned_ids": 0}

    zones_by_id = _index_by_id(board.get_zones())
    vias_by_id = _index_by_id(board.get_vias())

    orphan_vias: List[Any] = []
    cleaned_ids = 0

    for zid, entry in list(zones_meta.items()):
        if not isinstance(entry, dict):
            zones_meta.pop(zid, None)
            cleaned_ids += 1
            continue

        owned_ids = [str(v) for v in (entry.get("owned_via_ids") or []) if str(v)]
        zone = zones_by_id.get(str(zid))

        valid_ids: List[str] = []
        zone_polygons = _zone_polygons(zone) if zone is not None else []

        for vid in owned_ids:
            via = vias_by_id.get(vid)
            if via is None:
                cleaned_ids += 1
                continue
            if zone is None or not zone_polygons or not _via_inside_zone(via, zone_polygons):
                orphan_vias.append(via)
                cleaned_ids += 1
                continue
            valid_ids.append(vid)

        entry["owned_via_ids"] = valid_ids

    if not orphan_vias and cleaned_ids == 0:
        return {"removed": 0, "cleaned_ids": 0}

    # De-duplicate by ID in case a via appears in multiple stale ownership lists.
    unique_orphans = list(_index_by_id(orphan_vias).values())

    commit = board.begin_commit()
    pushed = False
    try:
        if unique_orphans:
            board.remove_items(unique_orphans)

        meta_changed, _ = _sync_metadata_item(
            board=board,
            metadata_item=metadata_item,
            metadata=metadata,
            old_text=old_meta_text,
            zone_for_new_item=(next(iter(zones_by_id.values())) if zones_by_id else None),
        )

        if unique_orphans or cleaned_ids or meta_changed:
            board.push_commit(commit, "ViaStitching: Clean Orphans")
            pushed = True
        else:
            board.drop_commit(commit)

        return {"removed": len(unique_orphans), "cleaned_ids": cleaned_ids}
    except Exception:
        if not pushed:
            board.drop_commit(commit)
        raise


def run_mode(mode: str) -> int:
    mode = (mode or "update").strip().lower()
    with KiCad() as kicad:
        runtime = Runtime(kicad)
        runtime.log(f"start mode={mode}")

        board = kicad.get_board()
        if board is None:
            _show_error_with_log(PLUGIN_NAME, "No active PCB board.", runtime.log_path)
            return 1

        try:
            _require_board_api(board)
            runtime.log(
                f"board api ok type={type(board).__name__} python={sys.version.split()[0]}"
            )
            if mode == "clean-orphans":
                result = _clean_orphans(runtime, board)
                runtime.log(f"clean-orphans done: {result}")
                return 0

            zone = _select_single_zone(board)
            zone_net = _zone_net_name(zone)
            if not zone_net:
                raise RuntimeError("Selected zone has no net.")

            if mode == "remove":
                result = _remove_zone_array(runtime, board, zone)
                runtime.log(f"remove done: {result}")
                return 0

            force_maximize = True if mode == "update-maximize" else None
            result = _update_zone_array(runtime, board, zone, force_maximize=force_maximize)
            runtime.log(f"update done: {result}")
            return 0

        except OperationCanceled as exc:
            runtime.log(f"CANCELED: {exc}")
            return 0
        except Exception as exc:
            runtime.log(f"ERROR: {exc}")
            runtime.log(traceback.format_exc())
            _show_error_with_log(PLUGIN_NAME, str(exc), runtime.log_path)
            return 1


def main() -> int:
    mode = "update"
    if len(sys.argv) > 1:
        mode = sys.argv[1]
    return run_mode(mode)


if __name__ == "__main__":
    raise SystemExit(main())
