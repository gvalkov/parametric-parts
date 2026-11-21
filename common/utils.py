"""Helpers to show build123d parts in Jupyter."""

from io import BytesIO

from build123d import Compound, ExportSVG, LineType
from IPython.display import HTML, Image, display


def show_svg(part, viewport=(-50, -100, 150), wireframe=False):
    """Show an SVG projection of a part.

    The projection uses the given viewport. Hidden edges appear as dotted
    lines when wireframe is true.
    """
    visible, hidden = part.project_to_viewport(viewport)
    max_dimension = max(*Compound(children=visible + hidden).bounding_box().size)

    exporter = ExportSVG(scale=100 / max_dimension)
    exporter.add_layer("Visible", line_color=(0, 0, 0))
    exporter.add_layer("Hidden", line_color=(99, 99, 99), line_type=LineType.ISO_DOT)

    exporter.add_shape(visible, layer="Visible")
    if wireframe:
        exporter.add_shape(hidden, layer="Hidden")

    buffer = BytesIO()
    exporter.write(buffer)
    svg = buffer.getvalue().decode("utf8")
    html = HTML(
        '<div style="background-color: white; display: inline-block; '
        f'padding: 30px;">{svg}</div>'
    )
    display(html)


def show_image(*args, **kwargs):
    """Show an image in a notebook."""
    display(Image(*args, **kwargs))
