"""Helpers to show build123d parts in Jupyter."""

import re
from io import BytesIO

from build123d import Compound, ExportSVG, LineType
from IPython.display import SVG, Image, display

VIEWBOX_RE = re.compile(r'viewBox="([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)"')


def add_white_background(svg):
    """Add a white background so the drawing is visible in dark themes."""
    match = VIEWBOX_RE.search(svg)
    if match is None:
        return svg

    x, y, width, height = match.groups()
    rect = f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="white"/>'
    return re.sub(r"(<svg\b[^>]*>)", lambda m: m.group(1) + rect, svg, count=1)


def show_svg(part, viewport=(-50, -100, 150), wireframe=False):
    """Show an SVG projection of a part.

    The projection uses the given viewport. Hidden edges appear as dotted
    lines when wireframe is true.
    """
    visible, hidden = part.project_to_viewport(viewport)
    max_dimension = max(*Compound(children=visible + hidden).bounding_box().size)

    exporter = ExportSVG(scale=100 / max_dimension)
    exporter.add_layer("Visible", line_color="#000000")
    exporter.add_layer("Hidden", line_color="#636363", line_type=LineType.ISO_DOT)

    exporter.add_shape(visible, layer="Visible")
    if wireframe:
        exporter.add_shape(hidden, layer="Hidden")

    buffer = BytesIO()
    exporter.write(buffer)
    svg = buffer.getvalue().decode("utf8")
    display(SVG(add_white_background(svg)))


def show_image(*args, **kwargs):
    """Show an image in a notebook."""
    display(Image(*args, **kwargs))
