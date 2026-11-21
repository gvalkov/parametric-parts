# Install the environment and the `common` package.
sync:
    uv sync

# Convert each notebook to a percent-format Python script.
docs:
    #!/usr/bin/env bash
    set -euo pipefail
    shopt -s nullglob
    for nb in */example.ipynb; do
        uv run jupytext --to py:percent "$nb" -o "${nb%.ipynb}.py"
    done

# Start JupyterLab at the repository root.
lab:
    uv run jupyter lab
