# Parametric Parts

Parametric 3D-printable parts modelled with build123d.

## Layout

- `common/utils.py` — preview helpers that all parts use
- `Keyhole Inserts/` — keyhole insert with snap lock and key
- `Square Tubing End Cap/` — end cap for square tubing
- `pyproject.toml` — one environment for all parts
- `Justfile` — tasks for the environment and the examples

Each part folder contains `main.py` with the geometry and `example.py` with a
demo notebook.

## Install

Install the environment and the `common` package:

    uv sync

## Run

Start JupyterLab at the repository root:

    just lab

Open the notebook in a part folder. The notebooks import `common`, so start
JupyterLab from the root. If Jupyter shows a trust warning, trust the notebook.

## Update an example script

The notebook is the source. The script is generated from the notebook. After
you change a notebook, regenerate its script:

    just docs
