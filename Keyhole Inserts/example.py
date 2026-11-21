# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.4
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% tags=["readme-skip"]
# %load_ext autoreload
# %autoreload 2

# %%
from main import make_keyhole, make_key, add_bottom, add_snaplock, KeyholeParams
from common.utils import show_svg, show_image
from dataclasses import replace

# %% tags=["readme-skip"]
from jupyter_cadquery import show, open_viewer, set_defaults, show_object, reset_show, Camera
cv = open_viewer("Viewer", anchor="split-bottom", aspect_ratio=0)
set_defaults(edge_accuracy=0.0001, axes=True, reset_camera=Camera.KEEP)

# %% [markdown]
# # Base geometry

# %%
show_image("drawing.png")

# %%
params_slot = KeyholeParams(
    Length = 22.0,
    Width = 14.0,
    Height = 6.0,
    Radius = 6.0,
    WallThickness = 1.0,
    TopThickness = 2.0,
    HoleDiameter = 7.0,
    SlotWidth = 4.0,
    SlotLength = 12.0,
)

params_circle = replace(params_slot, Width=22, Radius=11)

part_slot = make_keyhole(params_slot)
part_circle = make_keyhole(params_circle)
show_svg(part_slot)
show_svg(part_circle)

# %% [markdown]
# ### Bottom wall
#
# To increase the glue area, you can add a bottom wall to the part. This wall can include an optional through-hole or countersunk hole, aligned with either the center of the part or the center of the top hole. Keep in mind that adding a bottom hole makes the part harder to 3D print.

# %%
with_bottom_a = add_bottom(
    part_slot, params_slot,
    BottomThickness=1.0,
    HoleType="simple",
    HoleDiameter=3.0
)

with_bottom_b = add_bottom(
    part_slot, params_slot,
    BottomThickness=1.0,
    HoleType="countersink",
    HoleLocation="center",
    HoleDiameter=3.0,
    CounterSinkDiameter=8.0,
)

show_svg(with_bottom_a, wireframe=True)
show_svg(with_bottom_b, wireframe=True)

# %% [markdown]
# ### Snap-lock and key

# %%
with_snaplock = add_snaplock(part_slot, params_slot, Radius=.4)
show_svg(with_snaplock)

key = make_key(part_slot, params_slot)
show_svg(with_snaplock + key, wireframe=True)
