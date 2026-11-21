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
from build123d import export_stl

from main import Params, make_end_cap
from common.utils import show_svg

# %% tags=["readme-skip"]
from jupyter_cadquery import show, open_viewer, set_defaults, show_object, reset_show, Camera
cv = open_viewer("Viewer", anchor="split-bottom", aspect_ratio=0)
set_defaults(edge_accuracy=0.0001, axes=True, reset_camera=Camera.KEEP)

# %%
params = Params()
part = make_end_cap(params)

show_svg(part, wireframe=True)
show(part)
