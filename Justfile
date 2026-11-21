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

# Generate a README.md for each part from its example notebook.
# The notebooks use the jupyter-cadquery viewer, so `nbconvert --execute`
# fails without a live Jupyter server. Run and save the notebooks in
# JupyterLab first, then generate the READMEs from their saved outputs.
readmes:
    set -eu; \
    for nb in */example.ipynb; do \
        dir=$(dirname "$nb"); \
        title=$(basename "$dir"); \
        rm -rf "$dir/README_files" "$dir/.assets"; \
        uv run jupyter nbconvert --to markdown "$nb" \
            --output-dir "$dir" \
            --output README.md \
            --NbConvertApp.output_files_dir=.assets \
            --TagRemovePreprocessor.enabled=True \
            --TagRemovePreprocessor.remove_cell_tags=readme-skip; \
        printf '# %s\n\n' "$title" | cat - "$dir/README.md" > "$dir/README.md.tmp"; \
        mv "$dir/README.md.tmp" "$dir/README.md"; \
    done

# Start JupyterLab at the repository root.
lab:
    uv run jupyter lab
