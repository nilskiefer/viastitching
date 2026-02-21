#!/usr/bin/env python3
"""
KiCad 9 IPC action entrypoint for ViaStitching.

This is a transactional backend that uses Board.begin_commit()/push_commit()
for grouped undo/redo actions.
"""

from __future__ import annotations

import json
import math
import os
import sys
import traceback
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from kipy import KiCad
from kipy.board_types import Zone, Via
from kipy.utility import MessageBox, MessageBoxIcon

PLUGIN_ID = "org.nilskiefer.viastitching"
STATE_FILENAME = "ipc_state.json"
LOG_FILENAME = "viastitching_ipc.log"

DEFAULT_ZONE_SETTINGS: Dict[str, float] = {
    "ViaSize": 0.50,
    "ViaDrill": 0.30,
    "HSpacing": 1.00,
    "VSpacing": 1.00,
    "HOffset": 0.00,
    "VOffset": 0.00,
    "EdgeMargin": 0.00,
    "PadMargin": 0.00,
}


def mm_to_nm(mm: float) -> int:
    return int(round(float(mm) * 1_000_000.0))


def _kiid_to_str(item_id: Any) -> str:
    if item_id is None:
        return ""
    try:
        return str(item_id)
    except Exception:
        return ""


def _is_zone(item: Any) -> bool:
    if item is None:
        return False
    try:
        if isinstance(item, Zone):
            return True
    except Exception:
        pass
    return hasattr(item, "filled_polygons") and hasattr(item, "bounding_box")


def _item_id(item: Any) -> str:
    if item is None:
        return ""
    return _kiid_to_str(getattr(item, "id", None))


def _show(title: str, message: str, icon: Any = None) -> None:
    if icon is None:
        icon = MessageBoxIcon.ICON_INFO
    try:
        MessageBox(message, title, icon)
    except Exception:
        stream = sys.stderr if icon == MessageBoxIcon.ICON_ERROR else sys.stdout
        print(f"{title}: {message}", file=stream)


class Runtime:
    def __init__(self, kicad: KiCad) -> None:
        self.kicad = kicad
        self.settings_dir = self._resolve_settings_dir()
        self.state_path = os.path.join(self.settings_dir, STATE_FILENAME)
        self.log_path = os.path.join(self.settings_dir, LOG_FILENAME)
        self.state = self._load_state()

    def _resolve_settings_dir(self) -> str:
        path = self.kicad.get_plugin_settings_path(PLUGIN_ID)
        path = str(path) if path is not None else ""
        if not path:
            path = os.path.join(os.path.expanduser("~"), ".config", "viastitching")
        os.makedirs(path, exist_ok=True)
        return path

    def _load_state(self) -> Dict[str, Any]:
        if not os.path.exists(self.state_path):
            return {"zones": {}}
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                value = json.load(f)
            if isinstance(value, dict):
                value.setdefault("zones", {})
                return value
        except Exception:
            self.log("Failed to load state file; starting with empty state")
        return {"zones": {}}

    def save_state(self) -> None:
        tmp_path = self.state_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, sort_keys=True)
        os.replace(tmp_path, self.state_path)

    def zone_state(self, zone_id: str) -> Dict[str, Any]:
        zones = self.state.setdefault("zones", {})
        zone_entry = zones.get(zone_id)
        if not isinstance(zone_entry, dict):
            zone_entry = {}
            zones[zone_id] = zone_entry
        zone_entry.setdefault("owned_via_ids", [])
        zone_entry.setdefault("settings", dict(DEFAULT_ZONE_SETTINGS))
        return zone_entry

    def log(self, message: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {message}\n")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _vector_xy(value: Any) -> Tuple[int, int]:
    if value is None:
        return (0, 0)
    return (_safe_int(getattr(value, "x", 0)), _safe_int(getattr(value, "y", 0)))


def _polygon_points(poly: Any) -> List[Tuple[int, int]]:
    pts = []
    seq = getattr(poly, "points", None)
    if seq is None:
        return pts
    for p in seq:
        pts.append(_vector_xy(p))
    return pts


def _point_in_polygon(x: int, y: int, poly: Sequence[Tuple[int, int]]) -> bool:
    inside = False
    n = len(poly)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        intersects = ((yi > y) != (yj > y))
        if intersects:
            denom = (yj - yi) if (yj - yi) != 0 else 1
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


def _zone_polygons(zone: Zone) -> List[Any]:
    filled = getattr(zone, "filled_polygons", None)
    if filled is None:
        return []
    if isinstance(filled, dict):
        out = []
        for _, polys in filled.items():
            out.extend(list(polys))
        return out
    return list(filled)


def _point_inside_zone_with_margin(
    x: int,
    y: int,
    polygons: Sequence[Any],
    boundary_margin_nm: int,
) -> bool:
    for poly in polygons:
        outline = _polygon_points(getattr(poly, "outline", None))
        if not outline or not _point_in_polygon(x, y, outline):
            continue

        holes = getattr(poly, "holes", []) or []
        hole_hit = False
        for hole in holes:
            hole_points = _polygon_points(hole)
            if hole_points and _point_in_polygon(x, y, hole_points):
                hole_hit = True
                break
        if hole_hit:
            continue

        if boundary_margin_nm <= 0:
            return True

        d_outline = _poly_min_edge_distance(x, y, outline)
        if d_outline < boundary_margin_nm:
            continue

        too_close_hole = False
        for hole in holes:
            hole_points = _polygon_points(hole)
            if hole_points and _poly_min_edge_distance(x, y, hole_points) < boundary_margin_nm:
                too_close_hole = True
                break
        if too_close_hole:
            continue

        return True
    return False


def _track_width(track: Any) -> int:
    return _safe_int(getattr(track, "width", 0))


def _track_segment(track: Any) -> Optional[Tuple[int, int, int, int]]:
    start = getattr(track, "start", None)
    end = getattr(track, "end", None)
    if start is None or end is None:
        return None
    sx, sy = _vector_xy(start)
    ex, ey = _vector_xy(end)
    return (sx, sy, ex, ey)


def _gather_zone_owned_vias(board: Any, owned_ids: Iterable[str]) -> List[Any]:
    id_set = {s for s in owned_ids if s}
    if not id_set:
        return []
    out = []
    for via in board.get_vias():
        if _item_id(via) in id_set:
            out.append(via)
    return out


def _build_via_obstacles(board: Any, ignore_ids: Iterable[str]) -> List[Tuple[int, int, int]]:
    ignores = set(ignore_ids)
    out = []
    for via in board.get_vias():
        via_id = _item_id(via)
        if via_id in ignores:
            continue
        pos = getattr(via, "position", None)
        if pos is None:
            continue
        x, y = _vector_xy(pos)
        radius = _safe_int(getattr(via, "diameter", 0)) // 2
        out.append((x, y, radius))
    return out


def _build_track_obstacles(board: Any) -> List[Tuple[int, int, int, int, int]]:
    out = []
    for track in board.get_tracks():
        seg = _track_segment(track)
        if seg is None:
            continue
        width = _track_width(track)
        out.append((seg[0], seg[1], seg[2], seg[3], width))
    return out


def _conflicts_with_obstacles(
    x: int,
    y: int,
    via_radius: int,
    pad_margin: int,
    via_obstacles: Sequence[Tuple[int, int, int]],
    track_obstacles: Sequence[Tuple[int, int, int, int, int]],
) -> bool:
    limit_extra = via_radius + pad_margin

    for ox, oy, orad in via_obstacles:
        min_dist = limit_extra + orad
        if math.hypot(x - ox, y - oy) < min_dist:
            return True

    for sx, sy, ex, ey, width in track_obstacles:
        min_dist = limit_extra + (width // 2)
        if _dist_point_to_segment(x, y, sx, sy, ex, ey) < min_dist:
            return True

    return False


def _select_single_zone(board: Any) -> Zone:
    selection = list(board.get_selection())
    zones = [item for item in selection if _is_zone(item)]
    if not zones:
        raise RuntimeError("Select one filled copper zone first.")
    if len(zones) > 1:
        raise RuntimeError("Select exactly one zone.")
    return zones[0]


def _zone_net_name(zone: Zone) -> str:
    net = getattr(zone, "net", None)
    if net is None:
        return ""
    name = getattr(net, "name", "")
    return str(name) if name is not None else ""


def _ensure_zone_is_filled(board: Any, zone: Zone) -> List[Any]:
    polygons = _zone_polygons(zone)
    if polygons:
        return polygons
    if hasattr(board, "refill_zones"):
        try:
            board.refill_zones([zone])
        except TypeError:
            board.refill_zones()
    polygons = _zone_polygons(zone)
    if polygons:
        return polygons
    raise RuntimeError(
        "No filled copper found for selected zone. Refill the zone and retry."
    )


def _zone_bbox(zone: Zone) -> Tuple[int, int, int, int]:
    bbox = zone.bounding_box()
    x0 = _safe_int(getattr(getattr(bbox, "pos", None), "x", 0))
    y0 = _safe_int(getattr(getattr(bbox, "pos", None), "y", 0))
    sx = _safe_int(getattr(getattr(bbox, "size", None), "x", 0))
    sy = _safe_int(getattr(getattr(bbox, "size", None), "y", 0))
    return (x0, y0, x0 + sx, y0 + sy)


def _settings_from_zone_state(zone_entry: Dict[str, Any]) -> Dict[str, float]:
    out = dict(DEFAULT_ZONE_SETTINGS)
    saved = zone_entry.get("settings")
    if isinstance(saved, dict):
        for key in out.keys():
            if key in saved:
                try:
                    out[key] = float(saved[key])
                except Exception:
                    pass
    return out


def remove_zone_array(runtime: Runtime, board: Any, zone: Zone) -> Dict[str, int]:
    zone_id = _item_id(zone)
    zone_entry = runtime.zone_state(zone_id)
    owned_ids = zone_entry.get("owned_via_ids", [])
    owned_vias = _gather_zone_owned_vias(board, owned_ids)

    if not owned_vias:
        zone_entry["owned_via_ids"] = []
        runtime.save_state()
        return {"removed": 0}

    commit = board.begin_commit()
    try:
        board.remove_items(owned_vias)
        board.push_commit(commit, "ViaStitching: Remove Array")
    except Exception:
        board.drop_commit(commit)
        raise

    zone_entry["owned_via_ids"] = []
    runtime.save_state()
    return {"removed": len(owned_vias)}


def update_zone_array(runtime: Runtime, board: Any, zone: Zone) -> Dict[str, int]:
    polygons = _ensure_zone_is_filled(board, zone)
    zone_id = _item_id(zone)
    zone_entry = runtime.zone_state(zone_id)
    settings = _settings_from_zone_state(zone_entry)

    via_size = mm_to_nm(settings["ViaSize"])
    via_drill = mm_to_nm(settings["ViaDrill"])
    step_x = mm_to_nm(settings["HSpacing"])
    step_y = mm_to_nm(settings["VSpacing"])
    offset_x = mm_to_nm(settings["HOffset"])
    offset_y = mm_to_nm(settings["VOffset"])
    edge_margin = mm_to_nm(settings["EdgeMargin"])
    pad_margin = mm_to_nm(settings["PadMargin"])

    if via_size <= 0 or via_drill <= 0:
        raise RuntimeError("Via size and drill must be greater than 0.")
    if via_drill >= via_size:
        raise RuntimeError("Via drill must be smaller than via size.")
    if step_x <= 0 or step_y <= 0:
        raise RuntimeError("Spacing must be greater than 0.")
    if edge_margin < 0 or pad_margin < 0:
        raise RuntimeError("Margins must be non-negative.")

    via_radius = via_size // 2
    zone_net = getattr(zone, "net", None)
    if zone_net is None:
        raise RuntimeError("Selected zone has no net.")

    existing_owned_ids = zone_entry.get("owned_via_ids", [])
    owned_vias = _gather_zone_owned_vias(board, existing_owned_ids)
    ignore_ids = {_item_id(via) for via in owned_vias}

    via_obstacles = _build_via_obstacles(board, ignore_ids=ignore_ids)
    track_obstacles = _build_track_obstacles(board)

    x0, y0, x1, y1 = _zone_bbox(zone)
    start_x = x0 + ((offset_x - x0) % step_x)
    start_y = y0 + ((offset_y - y0) % step_y)

    candidates_tested = 0
    inside_count = 0
    rejected_obstacles = 0
    rejected_edges = 0
    created_items: List[Any] = []

    commit = board.begin_commit()
    try:
        if owned_vias:
            board.remove_items(owned_vias)

        new_vias: List[Via] = []
        y = start_y
        while y <= y1:
            x = start_x
            while x <= x1:
                candidates_tested += 1
                min_boundary = via_radius + edge_margin
                inside = _point_inside_zone_with_margin(x, y, polygons, min_boundary)
                if not inside:
                    rejected_edges += 1
                    x += step_x
                    continue
                inside_count += 1

                if _conflicts_with_obstacles(
                    x=x,
                    y=y,
                    via_radius=via_radius,
                    pad_margin=pad_margin,
                    via_obstacles=via_obstacles,
                    track_obstacles=track_obstacles,
                ):
                    rejected_obstacles += 1
                    x += step_x
                    continue

                via = Via(position=(x, y), net=zone_net)
                via.diameter = via_size
                via.drill_diameter = via_drill
                new_vias.append(via)

                # Reserve this candidate so the array keeps spacing to itself.
                via_obstacles.append((x, y, via_radius))
                x += step_x
            y += step_y

        if new_vias:
            created_items = list(board.create_items(new_vias))
        if owned_vias or created_items:
            board.push_commit(commit, "ViaStitching: Update Array")
        else:
            board.drop_commit(commit)
    except Exception:
        board.drop_commit(commit)
        raise

    zone_entry["settings"] = dict(settings)
    zone_entry["owned_via_ids"] = [_item_id(via) for via in created_items if _item_id(via)]
    runtime.save_state()

    return {
        "removed_old": len(owned_vias),
        "placed": len(created_items),
        "candidates_tested": candidates_tested,
        "inside": inside_count,
        "rejected_obstacles": rejected_obstacles,
        "rejected_edges": rejected_edges,
    }


def main() -> int:
    mode = "update"
    if len(sys.argv) > 1:
        mode = str(sys.argv[1]).strip().lower()

    with KiCad() as kicad:
        runtime = Runtime(kicad)
        runtime.log(f"Start mode={mode}")

        board = kicad.get_board()
        if board is None:
            _show("ViaStitching IPC", "No active PCB board.", MessageBoxIcon.ICON_ERROR)
            return 1

        try:
            zone = _select_single_zone(board)
            net_name = _zone_net_name(zone)
            if not net_name:
                raise RuntimeError("Selected zone has no net.")

            if mode == "remove":
                result = remove_zone_array(runtime, board, zone)
                _show("ViaStitching IPC", f"Removed {result['removed']} plugin vias.")
                runtime.log(f"Remove done: {result}")
            else:
                result = update_zone_array(runtime, board, zone)
                summary = (
                    f"Placed {result['placed']} vias.\n"
                    f"Removed old plugin vias: {result['removed_old']}\n\n"
                    f"Candidates tested: {result['candidates_tested']}\n"
                    f"Inside zone copper: {result['inside']}\n"
                    f"Rejected by overlap checks: {result['rejected_obstacles']}\n"
                    f"Rejected by edge margin checks: {result['rejected_edges']}"
                )
                _show("ViaStitching IPC", summary)
                runtime.log(f"Update done: {result}")
            return 0
        except Exception as exc:
            runtime.log(f"ERROR: {exc}")
            runtime.log(traceback.format_exc())
            _show(
                "ViaStitching IPC",
                f"{exc}\n\nDebug log:\n{runtime.log_path}",
                MessageBoxIcon.ICON_ERROR,
            )
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
