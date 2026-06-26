---
name: tamarind-docking
description: Use when docking a small molecule into a protein pocket (pose + score), screening a ligand library against one receptor, or predicting protein-ligand / protein-protein binding affinity or interface quality from a STRUCTURE you already have. Covers Autodock Vina and Smina (known-pocket box docking), DiffDock and SurfDock and Uni-Mol2 (blind, pocket-free), GNINA (CNN-rescored), pocket detection (fpocket, af2bind), protein-protein dockers (EquiDock, GeoDock), and the affinity/interface-scoring set (PRODIGY, binding-ddg, dockq, pdockq, ipsae, boltz-affinity-inference). Not for co-folding a complex from SEQUENCE (use tamarind-structure-prediction), not for designing a NEW ligand or binder (use tamarind-binder-design), not for first-time key setup (use tamarind-api-setup).
license: MIT
metadata:
  version: "1.0"
required_environment_variables:
  - TAMARIND_API_KEY
---

# Tamarind Bio: docking and binding affinity

Place a small molecule in a protein pocket (a pose) and score how well it fits, screen a ligand library against one receptor, or read a binding-affinity / interface-quality number off a complex you already have. The headline distinction is whether you KNOW the pocket: box-based physics dockers (Autodock Vina, Smina, GNINA) want a search box; ML dockers (DiffDock, SurfDock, Uni-Mol2) find the site themselves. Affinity tools (PRODIGY, the ddG family, boltz-affinity) take a structure and return a number, not a pose.

This skill is the docking layer on top of the base job lifecycle. The submit/poll/download mechanics live in `tamarind-submit-and-poll`; this skill picks the right docker or scorer, builds correct `settings`, and reads the poses/affinity back. If `TAMARIND_API_KEY` is unset or a call returns 401, run `tamarind-api-setup` first.

The canonical order is the same everywhere: **discover -> schema -> validate -> submit -> poll -> download -> rank poses.** Do not hardcode a tool or its settings; the catalog drifts and schemas evolve. Fetch the live schema (`getJobSchema` / `GET /tools`) and let `validateJob` confirm the shape before you spend.

## Pick the right tool

Match the user's INPUT (do you have a box? a complex? just sequence?) and OUTPUT (a pose? an affinity number? an interface score?), not a favorite name. Filter live with `getAvailableTools(function="protein-ligand-docking")` or `function="protein-protein-docking"`, read each `description`, then confirm fields with `getJobSchema`. Quick orientation:

- **Known pocket, want a pose + a physics score** -> `autodock-vina` (the classic, well-validated baseline; also the one to reach for when SCREENING many ligands against one receptor box, it accepts a SMILES CSV). `smina` is the customizable Vina fork. `gnina` adds a deep-learning CNN rescore on top of the same search for better pose ranking.
- **Unknown pocket, no box** -> `diffdock` (diffusion blind docking, the go-to when the site is unknown), `unimol2` (strong general ML docker). These find the site themselves.
- **Site defined by a known bound ligand (no box, but you have a reference pose)** -> `surfdock` (surface-informed diffusion). NOT blind: its schema REQUIRES a `referenceLigandFile` (an SDF of a ligand bound in the target pocket) to define the site, so reach for it only when you have that reference, not for a truly unknown pocket.
- **Want a pose AND an affinity in one ML shot** -> `flowdock` (returns both).
- **Score an EXISTING pose without re-docking** (e.g. rescore a DiffDock or cofold pose) -> `gnina` with `scoreOnly:true` (CNN affinity + pose score for the input conformation), or a structure-based affinity model (`aev-plig`, `gems`).
- **Absolute protein-PROTEIN affinity** (dG / Kd) from one complex structure -> `prodigy` (fast contact-based regression, no GPU). For antibody-antigen specifically, `dsmbind`.
- **EFFECT of a mutation on binding** (a delta, not an absolute) -> `binding-ddg` (wildtype vs mutant complex) or the interface affinity-maturation scanners `proteinmpnn-ddg-binder` / `stabddg`. Plain `proteinmpnn-ddg` scores fold STABILITY, not binding, so use the `-binder` sibling for interface ddG.
- **Interface QUALITY** of a predicted complex (not affinity) -> `dockq` (vs a native reference), `pdockq` / `ipsae` (no reference needed, straight from a fold job's confidence).
- **Find the pocket first** (you have a structure but no box) -> `fpocket` / `pykvfinder` (geometric cavity detection) or `af2bind` (learned binding-site prediction); feed the predicted site into a Vina box.
- **Dock two PROTEINS into a complex** -> `equidock` / `geodock` (fast rigid-body / geometric DL), `colabdock` (restraint-guided). To SCORE an existing PPI complex interface use `rosetta-ppi` (InterfaceAnalyzer, not a structure predictor). (`rosetta-dock` is a protein-LIGAND docker, not protein-protein.)

See [references/tools.md](references/tools.md) for per-tool schema, when-to-pick reasoning, and gotchas. Co-folding a complex from sequence (no input structure) belongs in `tamarind-structure-prediction`; designing a new ligand or binder belongs in `tamarind-binder-design`.

## The pocket box is the load-bearing input

Box-based dockers (`autodock-vina`, `smina`, `gnina`) need a focused search box around the pocket, supplied as a center (`boxX`/`boxY`/`boxZ`) plus dimensions (`width`/`height`/`depth`). Two things bite agents here:

- **The box defaults to the origin.** The schema defaults are `0,0,0` for the center (Vina) or `35,27,35` (gnina), which usually MISS the protein. The website renders a 3D box picker over the structure (`showDockingBox`), but over the API you must supply real coordinates: a known ligand's centroid, a pocket-residue centroid, or the output of a pocket-detection job (`fpocket` / `af2bind`). Surface this choice to the user before submitting, do not silently dock at the origin.
- **Size it to the pocket, not the protein** (~20-30 Angstroms per side). A box bigger than the protein makes the search explode and time out. For true whole-protein blind docking, use `gnina` with `wholeProtein:true` (box is ignored) or a pocket-free ML docker (`diffdock`).

If you have no pocket and no box, do not guess one: reach for `diffdock` / `unimol2` (truly blind, find the site themselves), or run a pocket-detection job first. (`surfdock` is NOT blind, it needs a `referenceLigandFile` defining the site.)

## Param names drift across the dockers (read the schema, do not copy fields)

Closely-related dockers use DIFFERENT field names and enum strings. Always `getJobSchema(<tool>)` for the exact tool; do not copy a payload across siblings:

- **Receptor field:** `autodock-vina` uses `receptorFile`; `diffdock` / `gnina` / `smina` use `proteinFile`.
- **Ligand format enum:** Vina's `ligandFormat` is **lowercase** (`"sdf"` / `"smiles"`); DiffDock's is `"sdf/mol2 file"` / `"SMILES"` (different strings, capital SMILES). Passing Vina's `"smiles"` to DiffDock fails.
- **SMILES support:** Vina and DiffDock expose a SMILES path (`ligandSmiles`); `gnina` and `smina` take an SDF only (no SMILES branch), so convert a SMILES to a 3D SDF first (the Conformer Generation tool, or obabel) before submitting.
- **Multi-fragment SMILES:** DiffDock rejects a `.` in the SMILES (disconnected fragments / salts). Strip counterions to a single connected ligand first.

## Build settings and validate

`getJobSchema(<tool>)` then `validateJob` before submitting. validateJob runs the real submit-validation with no spend and names the first bad field. Two notes that prevent false stalls:

- Act on `valid`, not the `source` label (built-in tools always report `source:"static-fallback"`, which is a schema-resolution note, not a "validator down" signal).
- Submit the clean settings you validated, not validateJob's `normalized` echo (it fills in defaults and platform-managed fields).

A file param given a real-but-unuploaded name returns `valid:false` ("File ... has not been uploaded"); that is the expected response until you upload the file, not a schema error. See `tamarind-submit-and-poll` for the validateJob authority rule and [references/examples.md](references/examples.md) for validateJob-confirmed payloads.

## Surface consequential choices before submitting

When the request fully specifies what to run, proceed. But a docking submit hides knobs that change runtime, cost, and results: the box center and size (the single most consequential choice, above), `exhaustiveness` (raise to 32 for a more reproducible result, at more compute), `cnnScoring` mode on gnina, `wholeProtein` vs a box, and ligand format. When the request is open-ended, present the meaningful options plus the default you would apply and let the user pick BEFORE you submit, rather than choosing silently and reporting it after the job is queued.

## File inputs (clean receptor PDB)

Docking file params (`receptorFile` / `proteinFile`, `ligandFile`) take a **bare filename** of an uploaded file (`receptor.pdb`, NOT an email-prefixed S3 key), a prior job's output by the `JobName/path/to/file.ext` form, or inline file content. A plain string in a file field is treated as INLINE content, not a path to an existing object. See `tamarind-submit-and-poll/references/api_reference.md`.

The receptor should be a CLEAN protein PDB. The docking wrappers run a receptor-prep pipeline (strip HETATM, `pdb2pqr`, convert to PDBQT), so bound waters, ions, and cofactors in the input can perturb the prep. Remove non-protein heteroatoms from the receptor before docking unless a cofactor is meant to stay.

Score-only affinity tools (`aev-plig`, `gems`, `gnina scoreOnly`) take the protein and ligand as SEPARATE files, not one combined complex. If you start from a bound complex, split it first: extract the HETATM ligand to an SDF and the protein to a PDB, then submit the two. `PRODIGY` is the exception (it takes a single complex file, but is protein-protein only). For pure affinity scoring, `getAvailableTools(function="binding-affinity")` is the cleaner discovery entry than the docking filter.

## Submit, poll, download

Drive the lifecycle through the bundled CLI wrapper so the sibling client import resolves from any cwd (probe `python3 -c "import requests"` first; install `scripts/requirements.txt` only if it fails):

```bash
python3 scripts/tamarind_job.py submit my-dock autodock-vina @settings.json
python3 scripts/tamarind_job.py wait     my-dock      # polls JobStatus to a terminal state
python3 scripts/tamarind_job.py download my-dock      # two-step presigned -> my-dock.zip
# or submit + wait + download in one call:
python3 scripts/tamarind_job.py run      my-dock autodock-vina @settings.json
```

`wait` polls on a 15-30s cadence and raises on `Stopped`/`Failed`; for a stopped job read the tail with MCP `getJobLogs(jobName)` (an oversized box that timed out is the classic docking failure, also bad input, OOM, budget). Jobs run minutes to hours, so launch the submit/poll with the runtime's non-blocking facility:

- **Codex (primary):** run the script as a FOREGROUND command with `yield_time_ms: 1000`; do NOT append `&` or `nohup`.
- **Claude Code:** run it via Bash with `run_in_background: true`.

For SCREENING many ligands against one receptor through a single docker, use `tamarind-batch` (one subjob per ligand, poll the parent `batchStatus`). To chain dock -> rescore -> filter, use `tamarind-pipeline`.

## Read the poses and scores back

What you read depends on the tool family, so reason about the metric SHAPE, not golden numbers:

- **Box / physics dockers** (Vina, smina): the results zip has the docked ligand pose(s) (`ligand_out.{sdf,pdb,pdbqt}`) and a `log.txt` with the binding-affinity table in kcal/mol per pose. **More negative is better.**
- **gnina:** docked poses (`out/result.sdf`), a combined receptor+ligand PDB, and `out/log.txt` with a CNN affinity + pose score. `scoreOnly` returns the score of the input pose as-is.
- **DiffDock:** confidence-ranked pose files (multiple ranks, `rank*.sdf`), no physics energy. Higher confidence is better; ordering IS the rank. For an affinity number, rescore a top pose with `gnina scoreOnly` or a structure-based affinity model.
- **PRODIGY:** an `output.csv` of binding affinity (dG) and dissociation constant (Kd) plus interfacial-contact counts, parsed from the PRODIGY log.
- **binding-ddg:** a single predicted ddG float on the row `Score` and in a one-row `results.csv` (negative = mutation stabilizes binding). It needs same-length wildtype and mutant complexes.

The bundled `scripts/extract_docking_poses.py` reads a downloaded docking results dir, auto-detects the metric (Vina/gnina/smina affinity kcal/mol vs DiffDock confidence), prints a ranked pose table, and copies the top-N pose files out for downstream use:

```bash
python3 scripts/extract_docking_poses.py my-dock/                 # ranked table + top 3
python3 scripts/extract_docking_poses.py my-dock/ --top 5 --json  # top 5, machine-readable
```

To enumerate a job's exact output filenames before downloading, use MCP `listJobFiles(jobName)` (returns `s3Path`, usable directly as the next job's file input). For deeper metric read-back and downstream chaining, see `tamarind-results-analysis`.

## Verify the pose, not just the score

A binding-affinity number can look fine while the pose sits outside the pocket or the ligand is mangled. Before trusting a result, open at least one actual output pose and sanity-check it: the ligand is intact (atom count, connectivity), it sits IN the intended pocket, and distinct ranks are not byte-identical. The score table can pass while the geometry is wrong, so spend the extra read.

## Wider catalog (one line each; confirm params live)

These cover special cases. Filter with `getAvailableTools(function="protein-ligand-docking" | "protein-protein-docking")` and `getJobSchema(<tool>)` before submitting; details in [references/tools.md](references/tools.md):

- **More ML dockers:** `surfdock` (surface-informed diffusion, needs a `referenceLigandFile`), `unimol2` (Uni-Mol Docking V2, strong general docker), `flowdock` (pose + affinity in one shot), `af2dock` (AF2-representation docking), `dfmdock` (diffusion variant).
- **Flexible-receptor physics docker:** `rosetta-dock` is a protein-LIGAND docker with full side-chain / backbone / ligand flexibility (Rosetta energy function, slower than Vina/GNINA; reach for it when receptor flexibility matters, not for protein-protein). Rosetta-license gated.
- **Local pose-ensemble refinement (NOT a docker, needs an existing pose):** `placer` samples atomistic protein-ligand conformational ensembles and scores active-site preorganization around an EXISTING pose (SOTA for local ensemble modeling; a Baker-lab enzyme-design filter). Pair it downstream of a docker (Vina/GNINA/Uni-Mol2); it does not do blind docking.
- **De novo ligand generation in a pocket** (designing, not docking; these are small-molecule generators, discover via `getAvailableTools(function="ligand-generation")`): `drugflow` (reference-ligand pocket), `diffsbdd` (pocket-only, fragment growing/linking), `flowr`, `pocketgen` (regenerate the pocket around a ligand).
- **Protein-protein docking:** `equidock` (equivariant rigid-body), `geodock` (geometric DL), `colabdock` (restraint-guided), `rosetta-ppi` (Rosetta InterfaceAnalyzer that SCORES an existing complex, not a structure predictor), `rosetta-relax-ligand` (refine a docked complex).
- **Pocket / site detection:** `fpocket`, `pykvfinder` (geometric cavity detection + volume), `af2bind` (learned binding-site prediction), `masif` / `atomsurf` (surface-fingerprint site prediction).
- **Library screening** (shape / pharmacophore, not per-ligand docking): `pharmit` (pharmacophore + shape against a library), `roshambo` (GPU 3D shape/color similarity), `virtudockdl` (end-to-end DL screen-then-dock pipeline).
- **Affinity & interface scoring** (a number off a structure, no pose):
  - protein-ligand: `aev-plig` / `gems` (structure-based, PDB + ligand SDF), `balm-inference` (sequence + SMILES, no structure), `boltz-affinity-inference` (Boltz-2 affinity head finetuned on your data; requires a prior `boltz-affinity-finetune` run, see `tamarind-finetune`).
  - protein-protein / antibody-antigen: `prodigy` (absolute dG/Kd), `dsmbind` (learned Ab-Ag), `spatial-ppi` (do two proteins interact, yes/no).
  - interface quality: `dockq` (vs a native reference), `pdockq` (no reference), `ipsae` (ipSAE/ipTM from a fold's PAE/pLDDT), `intercaat` (interface contact analysis), `contact-ms` (contact molecular surface area, the standard binder-design interface-burial filter).
  - mutation-effect ddG (binding): `binding-ddg` (wildtype vs mutant complex), `proteinmpnn-ddg-binder` (interface logit-difference scan), `stabddg` (SOTA SKEMPIv2 binding ddG). Plain `proteinmpnn-ddg` is fold STABILITY, not binding.

## Reference files

- [references/tools.md](references/tools.md): per-tool schema, when-to-pick, and gotchas for the four deep tools (Autodock Vina, DiffDock, GNINA, PRODIGY) plus the affinity/interface-scoring set and the wider catalog. Cites `getJobSchema` as the authority.
- [references/examples.md](references/examples.md): validateJob-confirmed `settings` payloads (Vina box dock + SMILES library screen, DiffDock blind, gnina CNN/scoreOnly, PRODIGY, binding-ddg, batch screen), the read-only self-check, what fails with the exact error, and output shapes.
- `scripts/extract_docking_poses.py`: rank docked poses by affinity/confidence, write the top-N.
