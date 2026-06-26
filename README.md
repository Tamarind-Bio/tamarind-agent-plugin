# Tamarind Bio agent skills

Run [Tamarind Bio](https://www.tamarind.bio)'s biology platform from your AI agent. Predict structures, fold complexes, dock ligands, design and screen binders and antibodies, and fine-tune models, all through one job API. One API key, the whole toolbox, no local GPU.

Tamarind bundles hundreds of open-source computational-biology tools (AlphaFold, Boltz, Chai, ESMFold, RFdiffusion, ProteinMPNN, BoltzGen, DiffDock, AutoDock Vina, and many more) behind one uniform submit/poll/download surface on managed GPUs. These skills package that surface so an agent can drive it directly.

The plugin exposes **both** of Tamarind's surfaces: a bundled REST client (the universal execution floor for submit/poll/download) plus the Tamarind MCP connector (`mcp.tamarind.bio`), auto-wired with your `TAMARIND_API_KEY` on both Claude Code and Codex. The MCP is preferred for discovery and validation (`getAvailableTools`, `getJobSchema`, the free `validateJob` dry-run); REST is the floor and everything works over REST alone if a host lacks MCP support.

## Install

The fastest path works the moment the repo is public, with no submission or approval, via [vercel-labs/skills](https://github.com/vercel-labs/skills):

```bash
npx skills add Tamarind-Bio/tamarind-agent-plugin -a codex -a claude-code
```

Use `-a codex` or `-a claude-code` to target one agent, or pass both. Add `--skill <name>` to install a specific skill.

### Three install channels

1. **`npx skills add` (vercel-labs/skills)**: the zero-gate channel above; installs the shared skill tree into whichever agent's config you target.
2. **Codex marketplace**: add this repo as a Codex marketplace (it ships `.agents/plugins/marketplace.json`) and install the `tamarind` plugin. You'll be prompted for your API key at install. See [the Codex local-install steps](#codex) below.
3. **Claude Code marketplace**: add this repo (it ships `.claude-plugin/marketplace.json`) and install the `tamarind` plugin. See [the Claude Code local-install steps](#claude-code) below.

All three read the same `plugins/tamarind/skills/` tree.

### Codex

Add this repo as a Codex marketplace, then install the `tamarind` plugin. Once the repo is public, pass `Tamarind-Bio/tamarind-agent-plugin` (or the Git URL); from a local clone, pass the path to your checkout:

```bash
codex plugin marketplace add Tamarind-Bio/tamarind-agent-plugin
# or from a local clone: codex plugin marketplace add /path/to/tamarind-agent-plugin
codex plugin add tamarind --marketplace tamarind-agent-plugin
# equivalently: codex plugin add tamarind@tamarind-agent-plugin
```

Verify it registered:

```bash
codex plugin marketplace list
codex plugin list
```

You'll be prompted for your API key at install (the marketplace manifest at `.agents/plugins/marketplace.json` declares the `tamarind` plugin with `ON_INSTALL` authentication for `TAMARIND_API_KEY`). Verified against `codex-cli 0.142.2`.

### Claude Code

Add this repo as a Claude Code marketplace, then install the `tamarind` plugin. Once the repo is public, pass `Tamarind-Bio/tamarind-agent-plugin` (or the Git URL); from a local clone, pass the path to your checkout:

```bash
claude plugin marketplace add Tamarind-Bio/tamarind-agent-plugin
# or from a local clone: claude plugin marketplace add /path/to/tamarind-agent-plugin
claude plugin install tamarind@tamarind-agent-plugin
```

Inside the Claude Code TUI the equivalent is `/plugin marketplace add Tamarind-Bio/tamarind-agent-plugin`, then `/plugin` to install `tamarind`. Verify with `claude plugin list`.

The bundled MCP connector (`mcp.tamarind.bio`) auto-wires from your `TAMARIND_API_KEY` (sent as the `x-api-key` header); restart Claude Code after install so it loads.

## API key

Every skill reads your key from the `TAMARIND_API_KEY` environment variable (sent as the `x-api-key` REST header). Get a key from the account / API settings at [app.tamarind.bio](https://app.tamarind.bio), then:

```bash
export TAMARIND_API_KEY="your_api_key"
```

New accounts get a free allotment of weighted-hours to try tools without a credit card. The `tamarind-api-setup` skill walks through the key + a first-call self-check.

## Skills

Setup and core:

- **`tamarind-api-setup`**: one-time setup: get a key, export `TAMARIND_API_KEY`, verify it, learn the REST vs MCP surfaces and the canonical live sources.
- **`tamarind-tool-discovery`**: find WHICH tool fits a goal: discover live (getAvailableTools / listModalities / listTags), match intent over keyword, name a primary plus alternatives.
- **`tamarind-submit-and-poll`**: run one tool end to end: validate, submit, poll to terminal, download. The base lifecycle every workflow builds on.
- **`tamarind-results-analysis`**: read back a finished job: interpret confidence metrics, list and download outputs, score against a reference, chain outputs by s3Path.

Domain tools:

- **`tamarind-structure-prediction`**: fold or co-fold from sequence (AlphaFold, Boltz-2, Chai-1, ESMFold2, Protenix, and the wider folding catalog).
- **`tamarind-antibody`**: antibody / nanobody / VHH engineering: CDR design, ImmuneBuilder structure, numbering, humanization, repertoire search.
- **`tamarind-binder-design`**: de novo protein, peptide, or small-molecule binder design (BindCraft, RFdiffusion, BoltzGen, the peptide family).
- **`tamarind-inverse-folding`**: design sequences for a fixed backbone and run protein language models (ProteinMPNN, LigandMPNN, ESM-IF1, ESM-C, embeddings).
- **`tamarind-docking`**: dock a ligand into a pocket, screen a library, or score binding affinity / interface quality from a structure (Vina, DiffDock, GNINA, PRODIGY).
- **`tamarind-developability`**: score manufacturability and clinic-readiness as filters: thermostability, aggregation, solubility, viscosity, immunogenicity.
- **`tamarind-finetune`**: fine-tune a model on your labeled data then run inference with it (plm/esmc, boltz-affinity, progen2, reinvent).
- **`tamarind-more-tools`**: domains without a dedicated skill: enzyme design, ADMET / quantum chem, MD / free energy, nucleic acids, cryo-EM, search and format utilities.

Scale and orchestration:

- **`tamarind-batch`**: run ONE tool across MANY inputs: submit a batch, poll the parent batchStatus, await aggregation, download and rank.
- **`tamarind-pipeline`**: chain MULTIPLE tools where each output feeds the next, either a declarative server-side pipeline or an imperative campaign loop you drive.

## Responsible use

These skills submit prediction, design, and characterization jobs to Tamarind's API for legitimate research. Use them accordingly, and follow Tamarind's terms and your agent platform's usage policies.

## License

MIT. See [LICENSE](LICENSE).
