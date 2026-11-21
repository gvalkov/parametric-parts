#!/usr/bin/env python3
"""Generate slot and circular matrices of keyhole inserts as 3MF files.

The matrix has two dimensions:
- The Forstner bit diameter sets the outline. It is the width of the slot
  shape and the diameter of the circular shape. The slot shape has round ends,
  so it fits in a pocket that you make with the same bit.
- The keyhole diameter is the hole for the screw head.

Within these limits, the other dimensions keep the proportions of the base
part from the example notebook (bit 14 mm, hole 7 mm):
- These dimensions scale with the bit: the wall thickness, and the extra
  length of the slot shape. The wall is rounded to a whole number of
  extrusion lines (LINE_FACTOR * NOZZLE, 0.66 mm by default).
- These dimensions scale with the hole: the slot, the top and total height,
  the snap-lock, the bottom, and the screw hole in the bottom.

A pair is skipped if the screw head cannot move along the full slot inside the
walls, or if the hole is very small compared with the bit (see --min-ratio).

For each pair and shape, the script generates normal and 1.5x wall versions of:
- the plain keyhole,
- the keyhole with a snap-lock,
- the keyhole with a snap-lock and bottom thickness,
- the keyhole with a snap-lock, bottom thickness, and countersunk hole,
  aligned with the top hole,
- the keyhole with a snap-lock, bottom thickness, and countersunk hole,
  centered on the part.

There are two sets of sizes:
- metric: bits and hole diameters in mm.
- imperial: bits and hole diameters in fractional inches. The script
  converts them to mm. All other dimensions stay in mm.

Each set, shape, and bottom option goes into a separate 3MF file:
  keyhole_matrix_<shape>[_imperial][_bottom].3mf
For example, keyhole_matrix_slot.3mf has the metric slot parts without a
bottom, and keyhole_matrix_slot_imperial_bottom.3mf has the imperial slot
parts with a bottom. In each file, each bit has a group of rows, one row for
each hole diameter.
"""

from __future__ import annotations

import argparse
import os
import zipfile
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from fractions import Fraction
from math import floor, isclose, radians, tan
from pathlib import Path
from typing import Literal, get_args

import build123d.mesher as b3d_mesher
from build123d import Mesher, Part, Pos

from main import KeyholeParams, add_bottom, add_snaplock, make_keyhole

Shape = Literal["slot", "circular"]
SHAPES: tuple[Shape, ...] = get_args(Shape)
Units = Literal["metric", "imperial"]
UNITS: tuple[Units, ...] = get_args(Units)
INCH = 25.4

# The base part. Width is the bit and HoleDiameter is the keyhole.
BASE = KeyholeParams(
    Length=22.0,
    Width=14.0,
    Height=6.0,
    Radius=6.0,
    WallThickness=1.0,
    TopThickness=2.0,
    HoleDiameter=7.0,
    SlotWidth=4.0,
    SlotLength=12.0,
)
# Common metric Forstner bit diameters (mm), from 12 mm to 30 mm.
FORSTNER_BITS = (12, 14, 15, 16, 18, 20, 22, 24, 25, 26, 28, 30)
# Common imperial Forstner bit diameters (inches), from 1/2" to 1-1/8"
# (28.6 mm). The next size, 1-1/4" (31.75 mm), is more than 30 mm.
IMPERIAL_BITS = tuple(Fraction(n, 8) for n in range(4, 10))
# Imperial hole diameters (inches), from 1/8" to 13/32" (3.2 to 10.3 mm) in
# 1/32" steps. This is about the same range as the metric holes.
IMPERIAL_HOLES = tuple(Fraction(n, 32) for n in range(4, 14))
WALL_FACTORS = (1.0, 1.5)
BASE_SNAP_RADIUS = 0.4
BASE_BOTTOM_THICKNESS = 1.0
BASE_BOTTOM_HOLE_DIAMETER = 3.0
BASE_COUNTERSINK_DIAMETER = 8.0
# The countersink is clamped to the top hole so that the screw head fits
# through it. CS_HEAD_CLEARANCE is the radial gap between them.
CS_HEAD_CLEARANCE = 0.1
# The material below the countersink cone, as a fraction of the bottom
# thickness. If it is 0, the cone goes through the full bottom.
CS_LAND_FRACTION = 0.5
CS_ANGLE = 82.0  # Default angle of build123d's CounterSinkHole.

# The walls are a whole number of extrusion lines, so the slicer fills them
# without gaps. The line width is LINE_FACTOR * NOZZLE.
NOZZLE = 0.6
LINE_FACTOR = 1.1
MIN_WALL_LINES = 2  # Applied before the wall factor.
# The minimum bottom thickness (mm). A value of 0 disables the minimum.
MIN_BOTTOM = 0.8

# Total difference between the bit and the outline of the insert (mm).
FIT_CLEARANCE = 0.2
# The minimum radial gap between the screw head and the walls (mm).
HEAD_CLEARANCE = 0.5
# Skip pairs where hole / bit is less than this.
MIN_RATIO = 0.25

GAP = 2.0
GROUP_GAP = 8.0  # Extra space between the groups of different bits.
# The mesh detail:
# - MESH_TOLERANCE is the largest distance (mm) between a facet and the true
#   surface. Large curves get more facets and small curves get fewer.
# - MESH_ANGLE is the largest angle (rad) between facets. It keeps at least
#   2 * pi / MESH_ANGLE facets on very small curves, such as the snap-lock.
MESH_TOLERANCE = 0.1
MESH_ANGLE = 0.8
# The number of decimals for the coordinates in the 3MF file (3 = 1 um).
MESH_DECIMALS = 3
OUTPUT_DIR = Path(__file__).parent


@dataclass(frozen=True)
class Feature:
    """Optional features to add to a keyhole."""

    snap: bool = False
    bottom: bool = False
    hole_location: Literal["center", "center-hole"] | None = None

    def __post_init__(self) -> None:
        if self.hole_location and not self.bottom:
            raise ValueError("A bottom hole needs bottom=True.")


FEATURES = (
    Feature(),
    Feature(snap=True),
    Feature(snap=True, bottom=True),
    Feature(snap=True, bottom=True, hole_location="center-hole"),
    Feature(snap=True, bottom=True, hole_location="center"),
)


@dataclass(frozen=True)
class Settings:
    bits: tuple[float, ...] = FORSTNER_BITS
    start: float = 3.0
    stop: float = 10.0
    step: float = 0.5
    imperial_bits: tuple[Fraction, ...] = IMPERIAL_BITS
    imperial_holes: tuple[Fraction, ...] = IMPERIAL_HOLES
    min_ratio: float = MIN_RATIO
    fit_clearance: float = FIT_CLEARANCE
    nozzle: float = NOZZLE
    line_factor: float = LINE_FACTOR
    min_wall_lines: int = MIN_WALL_LINES
    min_bottom: float = MIN_BOTTOM
    gap: float = GAP
    group_gap: float = GROUP_GAP
    mesh_tolerance: float = MESH_TOLERANCE
    mesh_angle: float = MESH_ANGLE
    output_dir: Path = OUTPUT_DIR


@dataclass(frozen=True)
class Size:
    """A nominal size. The value is in mm, and the name uses the nominal units."""

    mm: float
    name: str


def inch_name(value: Fraction) -> str:
    """Return a fractional inch size, for example 1-1/8"."""
    whole, rest = divmod(value, 1)
    if not rest:
        return f'{whole}"'
    return f'{whole}-{rest}"' if whole else f'{rest}"'


def parse_inches(text: str) -> Fraction:
    """Parse an inch size, for example 7/8, 1-1/8, or 1.125."""
    text = text.strip().rstrip('"')
    try:
        if "-" in text:
            whole, rest = text.split("-", 1)
            value = Fraction(whole) + Fraction(rest)
        else:
            value = Fraction(text)
    except (ValueError, ZeroDivisionError):
        raise argparse.ArgumentTypeError(f"Not an inch size: {text!r}") from None
    if value <= 0:
        raise argparse.ArgumentTypeError(f"Not an inch size: {text!r}")
    return value


def catalog(units: Units, s: Settings) -> tuple[list[Size], list[Size]]:
    """Return the bits and the hole diameters of a set of sizes."""
    if units == "metric":
        bits = [Size(float(b), f"{b:g}") for b in s.bits]
        holes = [Size(d, f"{d:.1f}") for d in hole_diameters(s)]
    else:
        def size(v: Fraction) -> Size:
            return Size(float(v) * INCH, f"{inch_name(v)}({float(v) * INCH:.2f})")

        bits = [size(b) for b in s.imperial_bits]
        holes = [size(d) for d in s.imperial_holes]
    return bits, holes


@dataclass(frozen=True)
class Variant:
    """All dimensions of one part. Calculated before any geometry is built."""

    shape: Shape
    bit: float
    bit_name: str
    hole_name: str
    wall_factor: float
    wall_lines: int
    feature: Feature
    params: KeyholeParams
    snap_radius: float
    bottom_thickness: float
    bottom_hole_diameter: float
    countersink_diameter: float

    def label(self) -> str:
        p = self.params
        parts = [
            f"shape={self.shape}",
            f"bit={self.bit_name}",
            f"D={self.hole_name}",
            f"L={p.Length:.2f}",
            f"W={p.Width:.2f}",
            f"H={p.Height:.2f}",
            f"wall={p.WallThickness:.2f}",
            f"lines={self.wall_lines}",
            f"wallx{self.wall_factor:g}",
        ]
        if self.feature.snap:
            parts.append(f"snap={self.snap_radius:.2f}")
        if self.feature.bottom:
            parts.append(f"bottom={self.bottom_thickness:.2f}")
        if self.feature.hole_location:
            parts.append(f"cs={self.feature.hole_location}")
            parts.append(f"bh={self.bottom_hole_diameter:.2f}")
            parts.append(f"csd={self.countersink_diameter:.2f}")
        return " ".join(parts)


def hole_diameters(s: Settings) -> list[float]:
    """Return the hole diameters from the start value to the stop value."""
    if s.step <= 0 or s.stop < s.start:
        raise ValueError("Use step > 0 and stop >= start.")
    span = (s.stop - s.start) / s.step
    if not isclose(span, round(span), abs_tol=1e-9):
        raise ValueError(f"The step {s.step} does not divide {s.start}..{s.stop}.")
    return [round(s.start + i * s.step, 6) for i in range(round(span) + 1)]


def countersink_depth(hole_d: float, cs_d: float) -> float:
    """Return the depth of the cone of a countersunk hole."""
    return (cs_d - hole_d) / 2.0 / tan(radians(CS_ANGLE / 2.0))


def make_params(
    bit: float, hole_diameter: float, wall_factor: float, shape: Shape, s: Settings
) -> KeyholeParams:
    """Calculate the keyhole dimensions for one bit and hole diameter."""
    width = bit - s.fit_clearance
    outline = width / BASE.Width  # Scale of the dimensions set by the bit.
    hole = hole_diameter / BASE.HoleDiameter  # Scale of the keyhole features.

    if shape == "circular":
        length = width
    else:
        # The extra length of the base part holds the travel of the slot.
        length = width + (BASE.Length - BASE.Width) * hole
    return replace(
        BASE,
        Length=length,
        Width=width,
        Height=BASE.Height * hole,
        # Round ends, so that the part fits a pocket made with the bit.
        # KeyholeParams makes the radius a bit smaller for a circle.
        Radius=width / 2.0 - (0.001 if shape == "slot" else 0.0),
        WallThickness=wall_lines(BASE.WallThickness * outline, wall_factor, s)
        * line_width(s),
        TopThickness=BASE.TopThickness * hole,
        HoleDiameter=hole_diameter,
        SlotWidth=BASE.SlotWidth * hole,
        SlotLength=BASE.SlotLength * hole,
    )


def line_width(s: Settings) -> float:
    return s.line_factor * s.nozzle


def wall_lines(wall: float, wall_factor: float, s: Settings) -> int:
    """Return the number of extrusion lines for a wall.

    The proportional wall is rounded to whole lines. The wall factor is then
    applied to the rounded count, so a thicker wall factor always adds at
    least one line.
    """
    lines = max(s.min_wall_lines, floor(wall / line_width(s) + 0.5), 1)
    if wall_factor > 1.0:
        lines = max(floor(lines * wall_factor + 0.5), lines + 1)
    return lines


def fits(p: KeyholeParams, bit: float, s: Settings) -> bool:
    """Return True if the screw head can move along the full slot."""
    if p.HoleDiameter < s.min_ratio * bit:
        return False
    # The head center moves from the hole center to the far end of the slot.
    travel = max(p.SlotLength / 2.0 - p.SlotRadius, p.SlotLength / 2.0 - p.HoleRadius)
    head = p.HoleRadius + HEAD_CLEARANCE
    inner_w = p.Width / 2.0 - p.WallThickness
    inner_l = p.Length / 2.0 - p.WallThickness
    return head <= inner_w and travel + head <= inner_l


def make_variant(
    bit: float | Size,
    hole_diameter: float | Size,
    wall_factor: float,
    feature: Feature,
    shape: Shape,
    s: Settings,
) -> Variant:
    """Calculate all the dimensions of one part. Plain numbers are in mm."""
    if not isinstance(bit, Size):
        bit = Size(float(bit), f"{bit:g}")
    if not isinstance(hole_diameter, Size):
        hole_diameter = Size(float(hole_diameter), f"{hole_diameter:.1f}")
    bit_size, hole_size = bit, hole_diameter
    bit, hole_diameter = bit.mm, hole_diameter.mm
    params = make_params(bit, hole_diameter, wall_factor, shape, s)
    hole = hole_diameter / BASE.HoleDiameter

    bottom = max(BASE_BOTTOM_THICKNESS * hole, s.min_bottom)
    bh = BASE_BOTTOM_HOLE_DIAMETER * hole
    # Make sure that the screw head fits through the top hole.
    csd = min(BASE_COUNTERSINK_DIAMETER * hole, hole_diameter - 2 * CS_HEAD_CLEARANCE)
    if feature.hole_location:
        # Make the bottom thick enough for the full cone and a land below it.
        # Otherwise, the cone cuts through the bottom and the hole on the
        # outer face is much larger than the screw.
        bottom = max(bottom, countersink_depth(bh, csd) + CS_LAND_FRACTION * bottom)

    return Variant(
        shape=shape,
        bit=bit,
        bit_name=bit_size.name,
        hole_name=hole_size.name,
        wall_factor=wall_factor,
        wall_lines=round(params.WallThickness / line_width(s)),
        feature=feature,
        params=params,
        snap_radius=BASE_SNAP_RADIUS * hole,
        bottom_thickness=bottom,
        bottom_hole_diameter=bh,
        countersink_diameter=csd,
    )


def build(v: Variant) -> Part:
    """Build the geometry of one variant."""
    part = make_keyhole(v.params)
    if v.feature.bottom:
        if v.feature.hole_location:
            hole_kwargs = dict(
                HoleType="countersink",
                HoleLocation=v.feature.hole_location,
                HoleDiameter=v.bottom_hole_diameter,
                CounterSinkDiameter=v.countersink_diameter,
            )
        else:
            hole_kwargs = dict(HoleType=None)
        part = add_bottom(
            part, v.params, BottomThickness=v.bottom_thickness, **hole_kwargs
        )
    if v.feature.snap:
        part = add_snaplock(part, v.params, Radius=v.snap_radius)
    if not part.is_valid:
        raise RuntimeError(f"Invalid geometry: {v.label()}")
    part.label = v.label()
    return part


BOTTOMS = {"without": False, "with": True}


def output_path(shape: Shape, bottom: bool, units: Units, s: Settings) -> Path:
    suffix = ("_imperial" if units == "imperial" else "") + ("_bottom" if bottom else "")
    return s.output_dir / f"keyhole_matrix_{shape}{suffix}.3mf"


def matrix_groups(
    shape: Shape, bottom: bool, units: Units, s: Settings
) -> list[list[list[Variant]]]:
    """Return the variants: one group for each bit, one row for each hole."""
    per_pair = [(w, f) for w in WALL_FACTORS for f in FEATURES if f.bottom == bottom]
    bits, holes = catalog(units, s)
    groups = []
    for bit in bits:
        rows = []
        for d in holes:
            # The thickest wall is the hardest case, so check it for all.
            params = make_params(bit.mm, d.mm, max(WALL_FACTORS), shape, s)
            if not fits(params, bit.mm, s):
                continue
            rows.append([make_variant(bit, d, w, f, shape, s) for w, f in per_pair])
        if rows:
            groups.append(rows)
    return groups


@contextmanager
def absolute_tolerance() -> Iterator[None]:
    """Make build123d's Mesher use the linear deflection as a distance in mm.

    Mesher always calls BRepMesh_IncrementalMesh with isRelative=True. Then
    the linear deflection is a fraction of the size of each edge, and you
    cannot set the mesh tolerance in mm.
    """
    original = b3d_mesher.BRepMesh_IncrementalMesh

    def mesh(*args, **kwargs):
        kwargs["isRelative"] = False
        return original(*args, **kwargs)

    b3d_mesher.BRepMesh_IncrementalMesh = mesh
    try:
        yield
    finally:
        b3d_mesher.BRepMesh_IncrementalMesh = original


def write_3mf(mesher: Mesher, out: Path) -> None:
    """Write a 3MF file with fewer decimals and the maximum ZIP compression."""
    tmp = out.with_name(out.name + ".tmp")
    writer = mesher.model.QueryWriter("3mf")
    writer.SetDecimalPrecision(MESH_DECIMALS)
    writer.WriteToFile(str(tmp))
    # lib3mf does not let you set the compression level, so compress again.
    try:
        with zipfile.ZipFile(tmp) as src, zipfile.ZipFile(
            out, "w", zipfile.ZIP_DEFLATED, compresslevel=9
        ) as dst:
            for info in src.infolist():
                dst.writestr(info, src.read(info), zipfile.ZIP_DEFLATED, 9)
    finally:
        os.remove(tmp)


def write_matrix(shape: Shape, bottom: bool, units: Units, s: Settings) -> str:
    """Build and write the matrix for one set of sizes, shape, and bottom option."""
    groups = [
        [[build(v) for v in row] for row in rows]
        for rows in matrix_groups(shape, bottom, units, s)
    ]
    rows = [row for group in groups for row in group]
    # The space above each row: a larger gap at the start of each group.
    gaps = [s.gap + (s.group_gap if i and j == 0 else 0.0)
            for i, group in enumerate(groups) for j in range(len(group))]
    gaps[0] = 0.0

    # Shelf layout: each row is as tall as its tallest part, and each part
    # takes only its own width. The matrix is centered on the origin.
    row_boxes = [[p.bounding_box() for p in row] for row in rows]
    row_widths = [sum(b.size.X for b in boxes) + s.gap * (len(boxes) - 1)
                  for boxes in row_boxes]
    row_heights = [max(b.size.Y for b in boxes) for boxes in row_boxes]
    width = max(row_widths)
    height = sum(row_heights) + sum(gaps)

    mesher = Mesher()
    y = height / 2.0
    count = 0
    for row, boxes, row_h, gap in zip(rows, row_boxes, row_heights, gaps):
        y -= gap
        x = -width / 2.0
        cy = y - row_h / 2.0
        for part, box in zip(row, boxes):
            c = box.center()
            placed = Pos(x + box.size.X / 2.0 - c.X, cy - c.Y, -box.min.Z) * part
            placed.label = part.label
            with absolute_tolerance():
                mesher.add_shape(
                    placed,
                    linear_deflection=s.mesh_tolerance,
                    angular_deflection=s.mesh_angle,
                )
            x += box.size.X + s.gap
            count += 1
        y -= row_h

    out = output_path(shape, bottom, units, s)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_3mf(mesher, out)
    kind = "with" if bottom else "without"
    return (f"Wrote {count} {units} {shape} keyholes {kind} a bottom"
            f" ({len(groups)} bits, {len(rows)} pairs,"
            f" {width:.0f} x {height:.0f} mm) to {out}")


Job = tuple[Shape, bool, Units]


def parse_args() -> tuple[list[Job], Settings, int]:
    d = Settings()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--shapes", nargs="+", choices=SHAPES, default=list(SHAPES))
    ap.add_argument("--bottom", nargs="+", choices=list(BOTTOMS),
                    default=list(BOTTOMS), help="files to make (default: both)")
    ap.add_argument("--units", nargs="+", choices=UNITS, default=list(UNITS),
                    help="sets of sizes to make (default: both)")
    ap.add_argument("--bits", nargs="+", type=float, default=list(d.bits),
                    metavar="MM", help="metric Forstner bit diameters (mm)")
    ap.add_argument("--start", type=float, default=d.start,
                    help="first metric hole diameter (mm)")
    ap.add_argument("--stop", type=float, default=d.stop,
                    help="last metric hole diameter (mm)")
    ap.add_argument("--step", type=float, default=d.step,
                    help="metric hole diameter step (mm)")
    ap.add_argument("--imperial-bits", nargs="+", type=parse_inches,
                    default=list(d.imperial_bits), metavar="IN",
                    help='imperial Forstner bit diameters (inches), e.g. 7/8 1-1/8')
    ap.add_argument("--imperial-holes", nargs="+", type=parse_inches,
                    default=list(d.imperial_holes), metavar="IN",
                    help="imperial hole diameters (inches), e.g. 1/4 5/16")
    ap.add_argument("--min-ratio", type=float, default=d.min_ratio,
                    help="skip pairs where hole / bit is less than this (0 = off)")
    ap.add_argument("--fit-clearance", type=float, default=d.fit_clearance,
                    help="bit diameter minus insert width (mm)")
    ap.add_argument("--nozzle", type=float, default=d.nozzle,
                    help="nozzle diameter (mm)")
    ap.add_argument("--line-factor", type=float, default=d.line_factor,
                    help="extrusion line width as a factor of the nozzle")
    ap.add_argument("--min-wall-lines", type=int, default=d.min_wall_lines,
                    help="minimum wall lines before the wall factor")
    ap.add_argument("--min-bottom", type=float, default=d.min_bottom,
                    help="minimum bottom thickness (mm, 0 = off)")
    ap.add_argument("--gap", type=float, default=d.gap, help="gap between parts (mm)")
    ap.add_argument("--group-gap", type=float, default=d.group_gap,
                    help="extra gap between bit groups (mm)")
    ap.add_argument("--mesh-tolerance", type=float, default=d.mesh_tolerance,
                    help="largest distance between the mesh and the part (mm)")
    ap.add_argument("--mesh-angle", type=float, default=d.mesh_angle,
                    help="largest angle between mesh facets (rad)")
    ap.add_argument("-o", "--output-dir", type=Path, default=d.output_dir)
    ap.add_argument("-j", "--jobs", type=int, default=0,
                    help="parallel processes (default: one for each file, up to the CPU count)")
    a = ap.parse_args()
    s = Settings(
        bits=tuple(sorted(set(a.bits))),
        start=a.start, stop=a.stop, step=a.step,
        imperial_bits=tuple(sorted(set(a.imperial_bits))),
        imperial_holes=tuple(sorted(set(a.imperial_holes))),
        min_ratio=a.min_ratio, fit_clearance=a.fit_clearance,
        nozzle=a.nozzle, line_factor=a.line_factor,
        min_wall_lines=a.min_wall_lines, min_bottom=a.min_bottom,
        gap=a.gap, group_gap=a.group_gap,
        mesh_tolerance=a.mesh_tolerance, mesh_angle=a.mesh_angle,
        output_dir=a.output_dir,
    )
    try:
        hole_diameters(s)  # Check the range before work starts.
    except ValueError as e:
        ap.error(str(e))
    shapes = list(dict.fromkeys(a.shapes))
    units = list(dict.fromkeys(a.units))
    for u in units:
        for shape in shapes:
            if not matrix_groups(shape, False, u, s):
                ap.error(f"No {u} bit and hole pair fits the {shape} shape.")
    jobs = [
        (shape, BOTTOMS[b], u)
        for u in units
        for shape in shapes
        for b in dict.fromkeys(a.bottom)
    ]
    return jobs, s, a.jobs or min(len(jobs), os.cpu_count() or 1)


def main() -> None:
    jobs, s, workers = parse_args()
    if workers <= 1 or len(jobs) == 1:
        for job in jobs:
            print(write_matrix(*job, s))
        return
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(write_matrix, *job, s) for job in jobs]
        for future in futures:
            print(future.result())


if __name__ == "__main__":
    main()
