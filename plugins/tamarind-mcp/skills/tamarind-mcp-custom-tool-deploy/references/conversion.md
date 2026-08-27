# Converting a repository into a custom tool

The three required files are an *adapter*. You are not rewriting the repository - you are wrapping
its existing entry point so the orchestrator can call it. Change repository code only when the
runtime contract forces it.

## Triage by repository shape

| Shape | Signal | Approach |
|---|---|---|
| Python script or package | `predict.py`, `main.py`, `argparse`, `click` | `run.sh` maps env vars onto the existing flags |
| Already has a Dockerfile | `Dockerfile` at root | Keep the base and install layers; replace `ENTRYPOINT`/`CMD` with `CMD ["bash", "run.sh"]` |
| Conda environment | `environment.yml` | Use a micromamba or conda base image; activate the env inside `run.sh`, not only in a build layer |
| Notebook only | `.ipynb` and no script | Ask the user for the intended entry point, or extract the inference path into a script and say that you did |
| Compiled or non-Python | `Makefile`, `CMakeLists.txt`, Go, Rust | Build in the image; `run.sh` invokes the produced binary |
| Model weights fetched at runtime | `hf_hub_download`, `torch.hub.load`, `wget` in the runtime path | Move the fetch into the `Dockerfile`; runtime has no network |

## Identify the one job

A repository usually offers training, evaluation, and inference. **Ask the user which one is the
product** - inference is the common answer, not the automatic one, and deploying the workflow they
did not ask for wastes the whole exercise. Whichever they pick is one entry point, one output
shape, one job per submission. If two entry points are genuinely different products, that is two
tools with two names - not one tool with a mode switch, unless the repository already presents it
as one.

## Infer inputs from the entry point, not the README

Read the actual argument parser. Each argument becomes one `inputs[]` entry:

| Argument shape | `inputs[]` type |
|---|---|
| A path to a structure | `pdb` |
| A path to a ligand | `sdf` |
| Any other path | `file` with an `extension` list |
| A protein or nucleic sequence | `sequence` |
| A molecule string | `smiles` |
| A free string | `text` |
| An int or float, especially with a range | `number` with `lowerBound` / `upperBound` |
| A store-true flag | `boolean` |
| A `choices=[...]` argument | `dropdown` with `options` |

Carry the parser's default into `default`, and its required-ness into `required`. Drop arguments
that only make sense to a developer - output directories, `--verbose`, `--device`, seeds you intend
to fix. Anything you drop must be hard-coded in `run.sh` so the behavior is still explicit.

Name each input exactly as you will read it in `run.sh`. Mismatched names are the single most
common cause of a tool that builds and then fails on its first job.

## Write the adapter

`run.sh` is the whole adapter. Keep it short and fail loudly:

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

Notes that matter:

- `set -euo pipefail` turns a silent partial failure into a failed job.
- Quote every expansion; sequences and paths contain characters that break unquoted words.
- Use `${VAR:-default}` only for inputs you declared with a `default`.
- A `store_true` flag takes no value, so it cannot be mapped like the others: passing
  `--use-feature "$USE_FEATURE"` either makes argparse reject the argument or enables the option
  even when the user said false. Append the flag only when the value is true:
  `[ "$USE_FEATURE" = "true" ] && set -- "$@" --use-feature`, or build the argument list
  conditionally before the call.
- File inputs are read-only. If the code writes beside its input, copy it into `/app` first:
  `cp "$TARGET_STRUCTURE" /app/target.pdb`.
- If the entry point insists on writing to a fixed directory, let it, then move the results:
  `mv /app/results/* /app/out/`.

## Bake everything at build time

The build has network; the runtime does not. Everything the tool needs must be in the image.

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Weights are baked here, not fetched at runtime.
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('org/model', local_dir='/app/weights')"
COPY . .
RUN chmod +x run.sh
CMD ["bash", "run.sh"]
```

Then point the code at the baked path - usually an `envVars` entry such as
`{"MODEL_DIR": "/app/weights"}` - rather than leaving a download call in the runtime path.

Pin what you can. An unpinned rebuild months later can silently upgrade a transitive dependency and
break a tool that has not changed.

## Choose resources honestly

- `gpuType: "None"` unless the code actually requires CUDA. A GPU request makes jobs slower to
  schedule and more expensive.
- If it does need CUDA, the base image must carry a matching runtime. A `python:3.12-slim` base with
  `gpuType: "A100"` fails at the first CUDA call, not at build.
- `memory` and `cpu` should reflect a measured run when you have one. Start modest; a job that dies
  on memory is easier to diagnose than an over-provisioned tool nobody notices.
- Set `estTime` from a real run once you have one.

## Worked example

Repository:

```text
esm-embed/
├── requirements.txt
└── embed.py        # argparse: --fasta (path, required), --layer (int, default 33)
```

Files you add:

```bash
# run.sh
#!/bin/bash
set -euo pipefail
mkdir -p /app/out
python /app/embed.py --fasta "$FASTA_FILE" --layer "${LAYER:-33}" --out /app/out/embeddings.csv
```

```json
{
  "displayName": "ESM embeddings",
  "description": "Per-residue ESM embeddings for a FASTA file",
  "gpuType": "T4",
  "memory": "16Gi",
  "cpu": 2,
  "inputs": [
    { "name": "FASTA_FILE", "type": "file", "extension": ["fasta", "fa"], "displayName": "FASTA", "required": true },
    { "name": "LAYER", "type": "number", "displayName": "Layer", "default": 33, "lowerBound": 1, "upperBound": 33 }
  ],
  "producedOutputs": [{ "type": "csv", "name": "embeddings" }],
  "taskType": "score"
}
```

The `Dockerfile` installs `requirements.txt`, downloads the ESM checkpoint into the image, copies
the repository, and ends with `CMD ["bash", "run.sh"]`.

## Before you build

- [ ] `Dockerfile`, `run.sh`, and `config.json` are at the archive root
- [ ] every `inputs[].name` is read in `run.sh`, and every variable `run.sh` reads is declared
- [ ] no network call remains on the runtime path
- [ ] every durable result lands under `/app/out/`
- [ ] no secret files, no `.git/`, no cached weights in the folder being uploaded
- [ ] `config.json` validates against the published schema
