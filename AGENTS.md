# Tamarind Bio agent skills

This repo packages Tamarind Bio's biology platform (structure prediction, protein and antibody design, docking, binding affinity, and more) as agent skills. Hundreds of open-source tools run on Tamarind's managed GPUs behind one job API; these skills let an agent drive that API directly. One API key, the whole toolbox, no local GPU.

## Start here

**`plugins/tamarind/skills/tamarind-api-setup`** first. It covers getting a `TAMARIND_API_KEY`, exporting it, a first-call self-check, and the two ways to call Tamarind (REST and the optional MCP server). Every other skill assumes setup is done and the key is in the environment.

Then **`plugins/tamarind/skills/tamarind-submit-and-poll`** is the base job lifecycle (validate, submit, poll to terminal, download) that every workflow builds on.

## Conventions

- The API key lives in the `TAMARIND_API_KEY` environment variable (sent as the `x-api-key` REST header). Never hardcode it.
- Tool names, schemas, and the catalog change frequently. Discover live (`GET /tools` or MCP `getAvailableTools` + `getJobSchema`) rather than trusting a hardcoded list. The canonical live sources are `app.tamarind.bio/llms.txt`, `app.tamarind.bio/openapi.yaml`, and `docs.tamarind.bio`.
- Each skill ships a thin REST client (`scripts/tamarind_client.py`, stdlib + `requests`) that bakes in the non-obvious API shapes. Probe the deps first, install from `scripts/requirements.txt` only if the import fails.
- Bio jobs run minutes to hours. Submit and poll non-blocking (Codex: foreground with `yield_time_ms`; Claude Code: `run_in_background`). Jobs are addressable by name, so you can re-attach later from any process.

## Layout

```
plugins/tamarind/
  .codex-plugin/plugin.json         Codex manifest (interface block)
  .claude-plugin/plugin.json        Claude manifest (flat displayName)
  skills/
    _shared/                        single source for the vendored client + helpers
    tamarind-api-setup/             setup + first-call self-check
    tamarind-tool-discovery/        find which tool fits a goal, live
    tamarind-submit-and-poll/       the base submit/poll/download lifecycle
    tamarind-results-analysis/      read back a finished job, metrics, scoring, chaining
    tamarind-structure-prediction/  fold or co-fold from sequence
    tamarind-antibody/              antibody / nanobody / VHH engineering
    tamarind-binder-design/         de novo protein, peptide, small-molecule binders
    tamarind-inverse-folding/       sequence design for a fixed backbone, PLMs
    tamarind-docking/               ligand docking, screening, affinity scoring
    tamarind-developability/        manufacturability and clinic-readiness filters
    tamarind-finetune/              fine-tune on your data then run inference
    tamarind-more-tools/            enzyme, ADMET, MD, nucleic acids, cryo-EM, search
    tamarind-batch/                 run ONE tool across MANY inputs
    tamarind-pipeline/              chain MULTIPLE tools into one workflow
```

The `skills/` tree is format-agnostic: both Codex and Claude Code read the same directory. The manifests point at the directory (`skills/`), so new skill subdirectories are auto-discovered with no per-skill manifest edits. Codex-only per-skill cards live at `skills/<skill>/agents/openai.yaml` (Claude ignores them).
