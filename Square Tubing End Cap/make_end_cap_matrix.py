#!/usr/bin/env python3
"""Generate matrices of end caps for common square tubing sizes as 3MF files.

The catalog has metric sizes (EN 10219 steel and common aluminum profiles)
and imperial sizes (ASTM A500 steel and common aluminum profiles). Each
standard goes into a separate 3MF file. Each tube size has a row, and each
wall thickness of that size has a column.

Tube corners are not sharp. For EN 10219, the outer corner radius is
1.6t..2.4t and the inner corner radius is 0.6t..1.4t, where t is the wall
thickness. The cap uses an outer radius of OUTER_RADIUS_FACTOR * t. The plug
uses a radius of PLUG_RADIUS_FACTOR * t, so it does not hit the inner corners.

You can also make caps for other tubes, including rectangular tubes, with
--tube WxLxT (mm). These caps go into a separate "custom" file.
"""

from __future__ import annotations

import argparse
import re
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from build123d import Mesher, Part, Pos

from main import Params, make_end_cap

INCH = 25.4

# Outer size -> wall thicknesses, in mm.
METRIC: dict[float, tuple[float, ...]] = {
    10: (1.0, 1.5),
    12: (1.0, 1.5),
    15: (1.5, 2.0),
    16: (1.5, 2.0),
    20: (1.5, 2.0),
    25: (1.5, 2.0, 3.0),
    30: (2.0, 3.0),
    35: (2.0, 3.0),
    40: (2.0, 3.0, 4.0),
    50: (2.0, 3.0, 4.0, 5.0),
    60: (3.0, 4.0, 5.0),
    70: (3.0, 4.0, 5.0),
    80: (3.0, 4.0, 5.0, 6.0),
    100: (4.0, 5.0, 6.0, 8.0),
}

# Outer size -> wall thicknesses, in inches.
IMPERIAL: dict[float, tuple[float, ...]] = {
    0.5: (0.049, 0.065),
    0.75: (0.065, 0.083),
    1.0: (0.065, 0.083, 0.120),
    1.25: (0.083, 0.120),
    1.5: (0.083, 0.120, 0.188),
    2.0: (0.083, 0.120, 0.188, 0.250),
    2.5: (0.120, 0.188, 0.250),
    3.0: (0.120, 0.188, 0.250),
    4.0: (0.188, 0.250),
}

STANDARDS = ("metric", "imperial")

OUTER_RADIUS_FACTOR = 2.0
PLUG_RADIUS_FACTOR = 1.5
CLEARANCE = 0.3  # Gap on each side between the plug and the tube (mm).
# The plug wall is a whole number of extrusion lines, so the slicer fills it
# without gaps. The line width is LINE_FACTOR * NOZZLE.
NOZZLE = 0.6
LINE_FACTOR = 1.1
WALL_LINES = 4  # 4 x 0.66 = 2.64 mm
# The cap and the plug get larger with the tube, within these limits (mm).
CAP_THICKNESS = (0.06, 2.0, 4.0)  # (factor of the tube size, min, max)
PLUG_HEIGHT = (0.25, 6.0, 20.0)
GAP = 3.0
# The mesh detail. This is the largest angle (rad) between the facets of a
# curved surface. The largest facet error is r * (1 - cos(angle / 2)).
ANGULAR_DEFLECTION = 0.1
# build123d's Mesher also needs a linear deflection. It is relative to the size
# of each edge, not in mm. This value is loose, so the angle sets the detail.
_LINEAR_DEFLECTION = 0.1
OUTPUT_DIR = Path(__file__).parent


@dataclass(frozen=True)
class Tube:
    """One tube. Dimensions are in mm. The name uses the nominal units."""

    width: float
    length: float
    wall: float
    name: str


@dataclass(frozen=True)
class Settings:
    clearance: float = CLEARANCE
    nozzle: float = NOZZLE
    line_factor: float = LINE_FACTOR
    wall_lines: int = WALL_LINES

    @property
    def inner_wall(self) -> float:
        """Return the wall thickness of the plug (mm)."""
        return self.wall_lines * self.line_factor * self.nozzle
    gap: float = GAP
    angular_deflection: float = ANGULAR_DEFLECTION
    output_dir: Path = OUTPUT_DIR


def fmt(value: float) -> str:
    return f"{value:g}"


def catalog(standard: str) -> list[list[Tube]]:
    """Return the tubes of a standard, one list for each size."""
    if standard == "metric":
        return [
            [Tube(size, size, t, f"{fmt(size)}x{fmt(size)}x{fmt(t)}mm") for t in walls]
            for size, walls in METRIC.items()
        ]
    if standard == "imperial":
        return [
            [
                Tube(
                    size * INCH,
                    size * INCH,
                    t * INCH,
                    f'{fmt(size)}"x{fmt(size)}"x{t:.3f}"',
                )
                for t in walls
            ]
            for size, walls in IMPERIAL.items()
        ]
    raise ValueError(f"Unknown standard: {standard}")


TUBE_RE = re.compile(r"^\s*([\d.]+)\s*x\s*([\d.]+)\s*x\s*([\d.]+)\s*$", re.I)


def parse_tube(text: str) -> Tube:
    """Parse a tube in the form WxLxT, in mm."""
    match = TUBE_RE.match(text)
    if not match:
        raise argparse.ArgumentTypeError(f"Use WxLxT in mm, not {text!r}.")
    w, l, t = map(float, match.groups())
    return Tube(w, l, t, f"{fmt(w)}x{fmt(l)}x{fmt(t)}mm")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def make_params(tube: Tube, s: Settings) -> Params:
    """Calculate the cap dimensions for one tube."""
    size = min(tube.width, tube.length)
    factor, low, high = CAP_THICKNESS
    cap_thickness = clamp(factor * size, low, high)
    factor, low, high = PLUG_HEIGHT
    plug_height = clamp(factor * size, low, high)
    return Params(
        Length=tube.length,
        Width=tube.width,
        TubeWallThickness=tube.wall,
        InnerWallThickness=s.inner_wall,
        CapThickness=cap_thickness,
        Clearance=s.clearance,
        InnerWallHeight=cap_thickness + plug_height,
        OuterRadius=OUTER_RADIUS_FACTOR * tube.wall,
        PlugRadius=PLUG_RADIUS_FACTOR * tube.wall,
    )


def build(tube: Tube, s: Settings) -> Part:
    """Build the end cap for one tube."""
    p = make_params(tube, s)
    part = make_end_cap(p)
    if not part.is_valid:
        raise RuntimeError(f"Invalid geometry: {tube.name}")
    part.label = (
        f"{tube.name} plug={p.PlugWidth:.2f}x{p.PlugLength:.2f}"
        f" clr={p.Clearance:g} h={p.InnerWallHeight:.1f}"
        + (" solid" if p.SolidPlug else
           f" wall={p.InnerWallThickness:.2f} lines={s.wall_lines}")
    )
    return part


def write_matrix(name: str, tubes: list[list[Tube]], s: Settings) -> str:
    """Build the caps and write them as one 3MF file, one row for each size."""
    rows = [[build(t, s) for t in row] for row in tubes if row]

    # Shelf layout: each row is as tall as its tallest part, and each part
    # takes only its own width. The matrix is centered on the origin.
    row_boxes = [[p.bounding_box() for p in row] for row in rows]
    row_widths = [
        sum(b.size.X for b in boxes) + s.gap * (len(boxes) - 1) for boxes in row_boxes
    ]
    row_heights = [max(b.size.Y for b in boxes) for boxes in row_boxes]
    width = max(row_widths)
    height = sum(row_heights) + s.gap * (len(rows) - 1)

    mesher = Mesher()
    y = height / 2.0
    count = 0
    for row, boxes, row_h in zip(rows, row_boxes, row_heights):
        x = -width / 2.0
        cy = y - row_h / 2.0
        for part, box in zip(row, boxes):
            c = box.center()
            placed = Pos(x + box.size.X / 2.0 - c.X, cy - c.Y, -box.min.Z) * part
            placed.label = part.label
            mesher.add_shape(
                placed,
                linear_deflection=_LINEAR_DEFLECTION,
                angular_deflection=s.angular_deflection,
            )
            x += box.size.X + s.gap
            count += 1
        y -= row_h + s.gap

    out = s.output_dir / f"end_caps_{name}.3mf"
    out.parent.mkdir(parents=True, exist_ok=True)
    mesher.write(out)
    return f"Wrote {count} {name} end caps ({width:.0f} x {height:.0f} mm) to {out}"


def size_filter(tubes: list[list[Tube]], sizes: list[str] | None) -> list[list[Tube]]:
    """Keep only the tubes whose name starts with one of the given sizes."""
    if not sizes:
        return tubes
    def norm(text: str) -> str:
        return text.lower().removesuffix("mm").replace(" ", "")

    queries = [norm(q) for q in sizes]
    keep = lambda t: any(
        norm(t.name) == q or norm(t.name).startswith(f"{q}x") for q in queries
    )
    return [[t for t in row if keep(t)] for row in tubes]


def parse_args() -> tuple[list[tuple[str, list[list[Tube]]]], Settings, int]:
    d = Settings()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--standards", nargs="*", choices=STANDARDS, default=None,
                    help="catalogs to build (default: all, or none if --tube is used)")
    ap.add_argument("--sizes", nargs="+", metavar="SIZE",
                    help='keep only these sizes, e.g. 40 40x40x3mm 1"')
    ap.add_argument("--tube", type=parse_tube, action="append", default=[],
                    metavar="WxLxT", help="add a custom tube in mm (repeatable)")
    ap.add_argument("--clearance", type=float, default=d.clearance,
                    help="gap on each side between the plug and the tube (mm)")
    ap.add_argument("--nozzle", type=float, default=d.nozzle,
                    help="nozzle diameter (mm)")
    ap.add_argument("--line-factor", type=float, default=d.line_factor,
                    help="extrusion line width as a factor of the nozzle")
    ap.add_argument("--wall-lines", type=int, default=d.wall_lines,
                    help="wall thickness of the plug, in extrusion lines")
    ap.add_argument("--gap", type=float, default=d.gap, help="gap between parts (mm)")
    ap.add_argument("--angular-deflection", type=float, default=d.angular_deflection,
                    help="mesh detail: largest angle between facets (rad)")
    ap.add_argument("-o", "--output-dir", type=Path, default=d.output_dir)
    ap.add_argument("-j", "--jobs", type=int, default=0,
                    help="parallel processes (default: one for each file)")
    a = ap.parse_args()

    s = Settings(
        clearance=a.clearance, nozzle=a.nozzle, line_factor=a.line_factor,
        wall_lines=max(1, a.wall_lines), gap=a.gap,
        angular_deflection=a.angular_deflection,
        output_dir=a.output_dir,
    )
    standards = a.standards
    if standards is None:
        standards = [] if a.tube else list(STANDARDS)

    jobs = []
    for std in dict.fromkeys(standards):
        tubes = size_filter(catalog(std), a.sizes)
        if any(tubes):
            jobs.append((std, tubes))
    if a.tube:
        jobs.append(("custom", [[t] for t in a.tube]))
    if not jobs:
        ap.error("No tubes match the given options.")

    for _, tubes in jobs:  # Check the dimensions before work starts.
        for tube in (t for row in tubes for t in row):
            try:
                make_params(tube, s)
            except ValueError as e:
                ap.error(f"{tube.name}: {e}")
    return jobs, s, a.jobs or len(jobs)


def main() -> None:
    jobs, s, workers = parse_args()
    if workers <= 1 or len(jobs) == 1:
        for name, tubes in jobs:
            print(write_matrix(name, tubes, s))
        return
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(write_matrix, n, t, s) for n, t in jobs]
        for future in futures:
            print(future.result())


if __name__ == "__main__":
    main()
