import math
from math import cos, sin
from fractions import Fraction
from typing import Literal
from dataclasses import dataclass, field, replace

from build123d import Pos, Vector, Part, Plane, Line, Face, Axis
from build123d import RectangleRounded, SlotOverall, Circle, CounterSinkHole, TangentArc, Hole
from build123d import offset, extrude, mirror
from build123d import export_stl, Compound, Mesher
from build123d import *


@dataclass
class KeyholeParams:
    Length: float  # Overall length
    Width: float   # Overall width
    Height: float  # Overall height
    Radius: float  # Outer radius
    WallThickness: float  # Outer wall thickness
    TopThickness:  float
    HoleDiameter:  float
    SlotWidth: float
    SlotLength: float

    HoleRadius: float = field(init=False)
    HolePosition: Pos = field(init=False)
    SlotRadius: float = field(init=False)

    def __post_init__(self):
        # In case the top is a circle.
        if self.Length == self.Width and math.isclose(self.Length / 2.0, self.Radius):
            self.Radius = self.Radius - 0.001

        self.HoleRadius = self.HoleDiameter / 2.0
        self.SlotRadius = self.SlotWidth / 2.0
        self.HolePosition = Pos(0, (self.SlotLength / 2.0) - (self.HoleRadius), 0)


def make_keyhole(p: KeyholeParams) -> Part:
    rect = RectangleRounded(p.Width, p.Length, p.Radius)
    wall = rect - offset(rect, -p.WallThickness)

    top = rect - SlotOverall(p.SlotLength, p.SlotWidth, 90)
    top -= p.HolePosition * Circle(p.HoleRadius)

    part = extrude(top, p.TopThickness) + extrude(wall, p.Height)
    part.label = f"W={p.Width} L={p.Length} H={p.Height}"
    return part


def add_bottom(
    part: Part,
    p: KeyholeParams,
    *,
    BottomThickness: float = 0.0,
    HoleType: Literal["simple", "countersink"] = "countersink",
    HoleDiameter: float = 0.0,
    CounterSinkDiameter: float = 0.0,
    HoleLocation: Literal["center", "center-hole"] = "center-hole"
):
    plane = Plane(part.faces().sort_by().last)
    bot = plane * RectangleRounded(p.Width, p.Length, p.Radius)

    part += extrude(bot, BottomThickness)

    if HoleLocation == "center-hole":
        pos = -(plane * p.HolePosition)
    elif HoleLocation == "center":
        pos = -plane

    if HoleType == "simple":
        assert HoleDiameter <= p.HoleDiameter
        hole = Hole(radius=HoleDiameter/2.0, depth=BottomThickness)

    if HoleType == "countersink":
        if not CounterSinkDiameter:
            CounterSinkDiameter = min(p.HoleDiameter, HoleDiameter * 2.0)
        hole = CounterSinkHole(
            radius=HoleDiameter / 2.0,
            depth=BottomThickness,
            counter_sink_radius=CounterSinkDiameter / 2.0,
        )

    part -= pos * hole
    return part


def add_snaplock(
    part: Part,
    p: KeyholeParams,
    *,
    Radius: float = 1.0,
    Length: float = None,
):
    c = Circle(Radius)

    if Length and (Fraction(Radius / Length).limit_denominator() >= Fraction(1, 5)):
        raise AssertionError("TODO: ...")
    else:
        Length = Radius * 4.5

    # There must be an easier way to do this ...
    theta = math.radians(-45)
    a_sta = Vector(0, -Length/2.0)
    a_end = Vector(Radius * cos(theta), Radius * sin(theta))
    a_tan = Vector(-sin(theta), cos(theta)).normalized()

    theta = math.radians(45)
    b_sta = Vector(0, Length/2.0)
    b_end = Vector(Radius * cos(theta), Radius * sin(theta))
    b_tan = Vector(-sin(theta), cos(theta)).normalized()

    a = TangentArc([a_end, a_sta], tangent=-a_tan)
    b = TangentArc([b_end, b_sta], tangent=b_tan)

    f = Face(a + c.wire().trim(0.875, 1.0) + c.wire().trim(-1.0, 0.125) + b + Line([(0, -Length/2.0), (0, Length/2.0)]))

    f = Pos(-p.SlotRadius, -p.SlotLength/2.0 + p.SlotRadius + Length / 2.0) * f

    lock = extrude(f, -p.TopThickness)
    part = part + mirror(lock, Plane.YZ) + lock
    return part


def make_key(
    part: Part,
    p: KeyholeParams,
    Tolerance: float = 0.2,
    HoleDiameter: float = 1.0
):
    c1 = p.HolePosition * Circle(p.SlotRadius - Tolerance)
    key = extrude(c1, p.TopThickness + Tolerance)

    pl = Plane((key.faces() >> Axis.Z).last)
    c2 = pl * Circle(p.HoleRadius - Tolerance)
    key += extrude(c2, p.Height - p.TopThickness - Tolerance)

    if HoleDiameter:
        key -= p.HolePosition * Hole(HoleDiameter / 2.0, p.Height)

    return key

