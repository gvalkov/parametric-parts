"""Parametric end cap for square tubing."""

from dataclasses import dataclass, field

from build123d import BuildPart, BuildSketch, Mode, Part, RectangleRounded, extrude, offset


@dataclass
class Params:
    """Dimensions of the end cap."""

    Length: float = 30.0
    Width: float = 30.0
    TubeWallThickness: float = 3.0
    InnerWallThickness: float = 0.6 * 4
    CapThickness: float = 2.0
    Clearance: float = 0.3
    InnerWallHeight: float = 6.0
    Radius: float = field(init=False)

    def __post_init__(self):
        # The cap uses the same radius as the tubing wall.
        self.Radius = self.TubeWallThickness


def make_end_cap(p: Params) -> Part:
    """Build an end cap that fits into square tubing."""
    with BuildPart() as part:
        with BuildSketch():
            RectangleRounded(p.Width, p.Length, p.Radius)
        extrude(amount=p.CapThickness)

        with BuildSketch():
            RectangleRounded(
                p.Width - p.TubeWallThickness - p.Clearance,
                p.Length - p.TubeWallThickness - p.Clearance,
                p.Radius,
            )
            offset(amount=-p.InnerWallThickness, mode=Mode.SUBTRACT)
        extrude(amount=p.InnerWallHeight)

    cap = part.part
    cap.label = f"W={p.Width} L={p.Length} H={max(p.CapThickness, p.InnerWallHeight)}"
    return cap
