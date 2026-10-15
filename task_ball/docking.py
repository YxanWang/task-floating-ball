"""Screen-edge docking geometry, independent of Qt and persisted settings."""

from dataclasses import dataclass


Point = tuple[int, int]
Bounds = tuple[int, int, int, int]
SIDES = ("left", "right", "top", "bottom")
HANDLE_THICKNESS = 12
HANDLE_LENGTH = 32


@dataclass(frozen=True)
class DockPlacement:
    side: str
    bounds: Bounds
    anchor: Point
    handle_rect: Bounds


def _validate_size(size: int, padding: int) -> None:
    if type(size) is not int or size < HANDLE_LENGTH:
        raise ValueError("size must be an integer of at least 32 pixels")
    if type(padding) is not int or padding < 0:
        raise ValueError("padding must be a nonnegative integer")


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def _anchor_range(origin: int, extent: int, size: int, padding: int) -> Point:
    # Very small work areas may not fit the requested visual-effect padding.
    inset = min(padding, (extent - size) // 2)
    return origin + inset, origin + extent - size - inset


def placement_for(side: str, bounds: Bounds, position: Point, size: int,
                  *, padding: int) -> DockPlacement:
    """Keep the selected edge while recalculating the ball and handle geometry."""
    _validate_size(size, padding)
    if side not in SIDES:
        raise ValueError("unknown docking side")
    x, y, width, height = bounds
    if width < size or height < size:
        raise ValueError("the work area must contain the full ball")
    bounds = (x, y, width, height)
    min_x, max_x = _anchor_range(x, width, size, padding)
    min_y, max_y = _anchor_range(y, height, size, padding)
    anchor_x = _clamp(position[0], min_x, max_x)
    anchor_y = _clamp(position[1], min_y, max_y)
    if side == "left":
        anchor_x = min_x
    elif side == "right":
        anchor_x = max_x
    elif side == "top":
        anchor_y = min_y
    else:
        anchor_y = max_y

    center_x, center_y = anchor_x + size // 2, anchor_y + size // 2
    if side in ("left", "right"):
        handle_x = x if side == "left" else x + width - HANDLE_THICKNESS
        handle = (handle_x, center_y - HANDLE_LENGTH // 2,
                  HANDLE_THICKNESS, HANDLE_LENGTH)
    else:
        handle_y = y if side == "top" else y + height - HANDLE_THICKNESS
        handle = (center_x - HANDLE_LENGTH // 2, handle_y,
                  HANDLE_LENGTH, HANDLE_THICKNESS)
    return DockPlacement(side, bounds, (anchor_x, anchor_y), handle)


def _distance_to_screen(center: Point, bounds: Bounds) -> float:
    x, y, width, height = bounds
    dx = max(x - center[0], center[0] - (x + width), 0)
    dy = max(y - center[1], center[1] - (y + height), 0)
    return dx * dx + dy * dy


def _contains(bounds: Bounds, center: Point) -> bool:
    x, y, width, height = bounds
    return x <= center[0] < x + width and y <= center[1] < y + height


def _nearest_work_area(position: Point, size: int, screens: list[Bounds]) -> Bounds | None:
    center = (position[0] + size / 2, position[1] + size / 2)
    containing = next((area for area in screens if _contains(area, center)), None)
    if containing is not None:
        return containing
    return min(screens, key=lambda area: _distance_to_screen(center, area)) if screens else None


def released_position(position: Point, size: int, screens: list[Bounds],
                      *, padding: int) -> Point:
    """Keep a released ball inside a real work area, including display gaps.

    Selection uses the same center/nearest-screen rule as docking. An empty or
    unusably small screen inventory leaves the position unchanged.
    """
    _validate_size(size, padding)
    work_areas = [tuple(bounds) for bounds in screens
                  if bounds[2] >= size and bounds[3] >= size]
    bounds = _nearest_work_area(position, size, work_areas)
    if bounds is None:
        return position
    x, y, width, height = bounds
    min_x, max_x = _anchor_range(x, width, size, padding)
    min_y, max_y = _anchor_range(y, height, size, padding)
    return (_clamp(position[0], min_x, max_x),
            _clamp(position[1], min_y, max_y))


def _overlap(start: int, length: int, other_start: int, other_length: int) -> bool:
    return max(start, other_start) < min(start + length, other_start + other_length)


def _is_exposed(placement: DockPlacement, screens: list[Bounds]) -> bool:
    x, y, width, height = placement.bounds
    hx, hy, hw, hh = placement.handle_rect
    for other in screens:
        if other == placement.bounds:
            continue
        ox, oy, ow, oh = other
        if placement.side in ("left", "right"):
            outside_x = x - 1 if placement.side == "left" else x + width
            if ox <= outside_x < ox + ow and _overlap(hy, hh, oy, oh):
                return False
        else:
            outside_y = y - 1 if placement.side == "top" else y + height
            if oy <= outside_y < oy + oh and _overlap(hx, hw, ox, ow):
                return False
    return True


def exposed_placement(placement: DockPlacement, screens: list[Bounds]) -> bool:
    """Whether a stored placement still belongs to an exposed screen-edge segment."""
    work_areas = [tuple(bounds) for bounds in screens if bounds[2] > 0 and bounds[3] > 0]
    return (placement.side in SIDES and placement.bounds in work_areas
            and _is_exposed(placement, work_areas))


def find_dock(position: Point, size: int, screens: list[Bounds], *, padding: int,
              threshold: int = 24) -> DockPlacement | None:
    """Choose a nearby exposed edge of the work area containing the ball center.

    A ball in a gap uses the nearest real work area. Adjacent monitors block only
    the portion of an edge beside the handle, allowing exposed offset segments.
    """
    _validate_size(size, padding)
    if type(threshold) is not int or threshold < 0:
        raise ValueError("threshold must be a nonnegative integer")
    work_areas = [tuple(bounds) for bounds in screens
                  if bounds[2] >= size and bounds[3] >= size]
    bounds = _nearest_work_area(position, size, work_areas)
    if bounds is None:
        return None
    candidates = []
    for side in SIDES:
        placement = placement_for(side, bounds, position, size, padding=padding)
        dx, dy = placement.anchor[0] - position[0], placement.anchor[1] - position[1]
        distance = dx * dx + dy * dy
        if distance <= threshold * threshold and _is_exposed(placement, work_areas):
            candidates.append((distance, placement))
    return min(candidates, key=lambda candidate: candidate[0])[1] if candidates else None
