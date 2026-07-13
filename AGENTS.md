# Tamarind Bio agent plugin

This repository packages Tamarind Bio workflows as Codex and Claude Code skills. Keep the plugin a thin orchestration layer over the independently released `tamarind` CLI.

## Architecture rules

- Do not vendor or recreate HTTP, authentication, retry, polling, file-transfer, or API-shape logic in the plugin.
- Invoke the `tamarind` executable as a subprocess. Do not import private modules from the `tamarind-cli` Python package.
- Keep CLI output parsing narrow and version-aware. The supported range is `tamarind-cli>=0.2,<0.3`.
- Put global options before subcommands: `tamarind --json jobs`, not `tamarind jobs --json`.
- Treat JSON stdout and structured JSON stderr as the CLI protocol; branch on typed exit codes, not message substrings.
- Inspect `JobStatus` or `batchStatus`; process exit 0 alone does not prove a job succeeded.
- Use `submit` followed by bounded `wait --timeout`; do not teach unbounded `submit --wait` or `results --wait` flows.
- Never retry an ambiguous submission. Query its durable job name first.
- Confirm material scope and weighted-hour spend before `submit` or `batch` unless the user already authorized that exact run.
- Download with `tamarind --json results ... --download ...`; normal CLI 0.2 output suppresses presigned URLs. Never use `--show-url` in agent logs.
- Keep local scripts only for deterministic scientific preprocessing or post-processing of downloaded artifacts.

## Skill design

- Frontmatter contains only `name` and `description`.
- Put trigger and exclusion rules in `description`; keep the body procedural and concise.
- Discover tools and schemas live with `tamarind --json tools` and `tamarind --json schema`.
- Validate every payload with `tamarind --json validate` before any submission.
- Use the domain skill for scientific choices and `tamarind-submit-and-poll` for the lifecycle contract.
- Keep mutable catalogs and detailed examples in `references/`; do not hardcode them as authoritative.
- `agents/openai.yaml` strings are quoted, short descriptions are 25-64 characters, and default prompts explicitly name `$skill-name`.

## Layout

```text
plugins/tamarind/
  .codex-plugin/plugin.json
  .claude-plugin/plugin.json
  skills/
    tamarind-api-setup/
    tamarind-tool-discovery/
    tamarind-submit-and-poll/
    tamarind-results-analysis/
    tamarind-structure-prediction/
    tamarind-antibody/
    tamarind-binder-design/
    tamarind-inverse-folding/
    tamarind-docking/
    tamarind-developability/
    tamarind-finetune/
    tamarind-more-tools/
    tamarind-batch/
    tamarind-pipeline/
```

## Verification

Before handing off changes:

1. Run repository tests.
2. Validate `plugins/tamarind` with the plugin validator.
3. Validate every skill with `quick_validate.py`.
4. Compile and test each retained Python helper.
5. Run CLI help-contract tests.
6. If credentials are already available, run only the authenticated no-spend smoke path: auth status, tool search, schema, and validate. Never submit a compute job as a smoke test.
