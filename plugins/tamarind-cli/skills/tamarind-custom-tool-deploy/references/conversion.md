# Converting a repository

The three root files are an adapter around the repository's existing entry point. Avoid rewriting application code unless the runtime contract requires it.

## Triage

| Repository shape | Approach |
|---|---|
| Python CLI (`argparse`, Click, Typer) | Map environment variables to its existing flags in `run.sh` |
| Existing Dockerfile | Preserve useful build layers; make `run.sh` the runtime command |
| Conda environment | Build from a compatible conda/micromamba image and activate it in `run.sh` |
| Notebook only | Ask which workflow is the product, then extract that path into a script |
| Compiled project | Build the binary in the image and invoke it from `run.sh` |
| Runtime weight download | Move the download into the Dockerfile and point code at the baked path |

When a repository exposes distinct training, evaluation, and inference workflows, ask which one should become the tool. One tool should have one entry point and output shape.

## Infer inputs from code

Read the real argument parser rather than trusting documentation.

| Argument | Custom Tool input |
|---|---|
| Structure path | `pdb` |
| Ligand path | `sdf` |
| Other file path | `file` with allowed extensions |
| Protein or nucleic-acid sequence | `sequence` |
| Molecule string | `smiles` |
| Free string | `text` |
| Integer or float | `number` with real bounds |
| Store-true flag | `boolean` |
| Fixed choices | `dropdown` |

Carry real defaults and requiredness into `config.json`. Drop developer-only controls such as output directories, verbosity, and device selection, then set them explicitly in the adapter.

## Write `run.sh`

```bash
#!/bin/bash
set -euo pipefail
mkdir -p /app/out

python /app/predict.py \
  --target "$TARGET_STRUCTURE" \
  --sequence "$SEQUENCE" \
  --num-samples "${NUM_SAMPLES:-8}" \
  --output-dir /app/out
```

Quote every expansion. Use `${VAR:-default}` only when the input declares that default. For store-true flags, append the flag only when the boolean is true; do not pass the string `false` after a flag that takes no value.

If the code expects its input at a fixed path, put it there - `/app` and `/app/inputs/` are both writable. If an application insists on another output directory, move the finished artifacts into `/app/out/` before exiting.

## Bake dependencies and weights

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('org/model', local_dir='/app/weights')"
COPY . .
RUN chmod +x run.sh
CMD ["bash", "run.sh"]
```

Pin dependencies where practical. A CUDA tool needs a CUDA-compatible base image; setting `gpuType` alone does not add drivers or libraries.

Start with resources justified by a representative run. CPU-only tools should use `gpuType: "None"`; unnecessary GPUs increase scheduling latency and cost.

## Pre-build check

- `Dockerfile`, `run.sh`, and `config.json` are at the source root.
- Every environment variable read by `run.sh` is declared as an input or fixed `envVars` value.
- No runtime path makes a network request.
- Every durable result lands below `/app/out/`.
- No credential, repository metadata, virtual environment, or cache will be uploaded.
- Local `custom-tools validate` reports no errors or blocking warnings.
