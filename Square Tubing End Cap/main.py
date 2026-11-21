"""Parametric end cap for square tubing."""

from dataclasses import dataclass, field

from build123d import BuildPart, BuildSketch, Mode, Part, RectangleRounded, extrude, offset

# If the opening in the plug is smaller than this (mm), the plug is solid.
MIN_PLUG_OPENING = 2.0


@dataclass
class Params:
    """Dimensions of the end cap.

    Length and Width are the outer dimensions of the tube. Clearance is the
    gap between the plug and the inner tube wall on each side.
    """

    Length: float = 30.0
    Width: float = 30.0
    TubeWallThickness: float = 3.0
    # 4 extrusion lines of 110% of a 0.6 mm nozzle.
    InnerWallThickness: float = 4 * 1.1 * 0.6
    CapThickness: float = 2.0
    Clearance: float = 0.3
    InnerWallHeight: float = 6.0
    # The corner radius of the cap. If None, it is the tube wall thickness.
    OuterRadius: float | None = None
    # The corner radius of the plug. If None, it is the same as OuterRadius.
    # Make it at least the inner corner radius of the tube, or the plug
    # hits the corners of the tube.
    PlugRadius: float | None = None
    Radius: float = field(init=False)
    PlugLength: float = field(init=False)
    PlugWidth: float = field(init=False)

    def __post_init__(self):
        if self.OuterRadius is None:
            self.OuterRadius = self.TubeWallThickness
        if self.PlugRadius is None:
            self.PlugRadius = self.OuterRadius
        self.Radius = self.OuterRadius

        # The plug fits inside the tube: subtract the wall and the clearance
        # on both sides.
        gap = 2 * (self.TubeWallThickness + self.Clearance)
        self.PlugLength = self.Length - gap
        self.PlugWidth = self.Width - gap
        if min(self.PlugLength, self.PlugWidth) <= 0:
            raise ValueError("The tube wall is too thick for the tube size.")

        # RectangleRounded needs a radius less than half of the shortest side.
        limit = min(self.PlugLength, self.PlugWidth) / 2.0 - 0.001
        self.PlugRadius = min(self.PlugRadius, limit)
        self.Radius = min(self.Radius, min(self.Length, self.Width) / 2.0 - 0.001)

    @property
    def SolidPlug(self) -> bool:
        """Return True if the plug is too small for an opening."""
        opening = min(self.PlugLength, self.PlugWidth) - 2 * self.InnerWallThickness
        return opening < MIN_PLUG_OPENING


def make_end_cap(p: Params) -> Part:
    """Build an end cap that fits into square tubing."""
    with BuildPart() as part:
        with BuildSketch():
            RectangleRounded(p.Width, p.Length, p.Radius)
        extrude(amount=p.CapThickness)

        with BuildSketch():
            RectangleRounded(p.PlugWidth, p.PlugLength, p.PlugRadius)
            if not p.SolidPlug:
                offset(amount=-p.InnerWallThickness, mode=Mode.SUBTRACT)
        extrude(amount=p.InnerWallHeight)

    cap = part.part
    cap.label = f"W={p.Width} L={p.Length} H={max(p.CapThickness, p.InnerWallHeight)}"
    return cap
