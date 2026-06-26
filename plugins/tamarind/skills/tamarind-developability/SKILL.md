---
name: tamarind-developability
description: "Use to score whether a protein or antibody will survive manufacturing and the clinic on Tamarind Bio: thermostability and melting temperature (ThermoMPNN, TemStaPro, deepSTABp), aggregation (Aggrescan3D, DeepSP), solubility (NetSolP, Protein-Sol), viscosity, polyreactivity, glycosylation, and T-cell immunogenicity. Run these as FILTERS on a hit list after design or structure prediction. Not for designing or generating the molecule (use tamarind-binder-design / tamarind-antibody), not for folding or co-folding a structure (use tamarind-structure-prediction), not for binding affinity or docking (use tamarind-docking). Pairs with tamarind-submit-and-poll for the run loop and tamarind-batch to screen a whole hit list."
license: MIT
metadata:
  version: "1.0"
required_environment_variables:
  - TAMARIND_API_KEY
---

# Tamarind Bio: developability, stability, and immunogenicity

Score whether a candidate protein or antibody will actually survive manufacturing, formulation, and a patient. This is the "is it developable?" stage: thermal stability, aggregation, solubility, viscosity, polyreactivity, glycosylation, and immunogenicity. You run these tools as **filters on a hit list** after the design or structure-prediction stage, before committing a candidate to wet-lab.

These are scoring tools, not generators. They take a sequence or a structure you already have and return red-flag metrics. To make the molecule, use `tamarind-binder-design` / `tamarind-antibody`; to fold it, use `tamarind-structure-prediction`. This skill builds on the base run loop in `tamarind-submit-and-poll` (validate, submit, poll, download) and uses `tamarind-batch` to push a whole hit list through one tool in one call.

If `TAMARIND_API_KEY` is unset or a call returns 401, run `tamarind-api-setup` first. Always `getJobSchema` / `validateJob` a tool before submitting; the catalog and schemas drift, so the live schema is the authority, not this page.

## Where this fits: a filter stage, not a goal

A typical campaign is design -> structure -> **developability filter** -> shortlist. So most of the time you arrive here with a list of candidates and a structure or sequence for each, and you want to drop the ones that will aggregate, express poorly, or trigger an immune response. Two consequences:

- **Pick the tool by the input you already have.** Sequence-only (no structure)? Use the PLM-based scorers (`netsolp`, `protein-sol`, `saprot`, `temstapro`, `deepstabp`, `tap`/`tnp`, `deepsp`). Have a folded structure? Use the structure-aware ones (`aggrescan3d`, `thermompnn`, `proteinmpnn-ddg`). Don't fold a structure just to score solubility if a sequence model answers it.
- **Run the filter across the whole list at once.** One developability tool over many candidates is a `tamarind-batch` job (poll the parent's `batchStatus`). Reach for the batch skill rather than looping single submits.

## The antibody disambiguation: TAP vs TNP (the most common mis-pick)

The single biggest mistake in this bucket is running the wrong antibody profiler for the format you have. The platform has two, and they are not interchangeable:

- **`tap` (TAP2, Therapeutic Antibody Profiler)** is for a **paired antibody** (a heavy chain AND a light chain, VH+VL). It requires BOTH `heavySequence` and `lightSequence`; submitting only one fails. This is the canonical one-shot developability scorecard for a conventional mAb / Fv.
- **`tnp` (TNP, Therapeutic Nanobody Profiler)** is for a **single-domain nanobody / VHH** (heavy chain only). It takes ONE `sequence`. Never run TAP on a nanobody (you have no light chain to give it), and never run TNP on a paired antibody (it ignores the light chain entirely).

Rule of thumb: paired (VH+VL) -> `tap`; single-domain VHH -> `tnp`. If the user hands you one chain and calls it an "antibody", confirm the format before picking, because the wrong profiler gives a meaningless score, not an error.

The antibody-specific aggregation/viscosity tools (`deepsp`, `deep-viscosity`) and polyreactivity (`polyxpert`) are also paired-antibody (heavy+light) tools; the nanobody analogs live under `function=developability` filtered by `modality=antibody` (search for the VHH-specific variant). General-protein scorers (`aggrescan3d`, `netsolp`, `temstapro`, ...) don't care about format.

## Canonical tools (deep)

Four tools cover the bulk of developability work, one per major axis. Confirm required fields with `getJobSchema(<tool>)` before submitting; the payloads here are schema-derived starting points (all validated `valid:true`).

### tap - paired-antibody developability scorecard (TAP2)

Flags developability red-flags in a paired antibody Fv before you spend on it: surface hydrophobicity, charge patches, and CDR length that correlate with poor manufacturability, plus a sequence-liability scan (deamidation, isomerization, oxidation, glycosylation, unpaired cysteine, glycation). It folds the Fv from the heavy+light sequence, then computes the five Raybould-style TAP metrics on the predicted structure with green/amber/red "traffic light" flags.

Pick it for a **paired antibody (VH+VL)** when you want the one-shot developability scorecard. For a nanobody/VHH use `tnp`; for just aggregation use `aggrescan3d` (any structure) or `deepsp` (antibody-specific); for humanness/immunogenicity see the catalog below. Sequence-only, no file, validates fast.

```json
{"jobName": "tap-mab-demo", "type": "tap",
 "settings": {
   "heavySequence": "QVQLQQSGAELARPGASVKMSCKASGYTFTRYTMHWVKQRPGQGLEWIGYINPSRGYTNYNQKFKDKATLTTDKSSSTAYMQLSSLTSEDSAVYYCARYYDDHYCLDYWGQGTTLTVSS",
   "lightSequence": "QIVLTQSPAIMSASPGEKVTMTCSASSSVSYMNWYQQKSGTSPKRWIYDTSKLASGVPAHFRGSGSGTSYSLTISGMEAEDAATYYCQQWSSNPFTFGSGTKLEIN"}}
```

Both sequences are **required**: an empty `heavySequence` or `lightSequence` is rejected (TAP is paired-only). Output is a set of CSVs: the TAP metrics (PSH, PPC, PNC, CDR length, SFvCSP) with a traffic-light column each, a per-residue liability table, residue/pair contribution decompositions, and the predicted Fv structure.

### thermompnn - propose stabilizing point mutations (from a structure)

Recommends single-point substitutions that raise a protein's thermostability (predicted ddG), so you can stabilize an enzyme, scaffold, or antibody without losing fold. A ProteinMPNN-based model scores every single substitution from the input structure and ranks the most stabilizing.

Pick it when you have a **structure** and want a ranked list of **stabilizing single mutations**. For **double** mutations use `thermompnn-d`; for an unsupervised **fold-stability saturation scan** over every position use `proteinmpnn-ddg` (or the physics-based `rosetta-ddg-prediction`); for just a **melting temperature from sequence** (no mutation list, no structure) use `deepstabp` or `temstapro`. (To score the **binding**-ddG effect of **interface** mutations on a complex, that's `stabddg`, a protein-protein binding tool in `tamarind-docking`, not a fold-stability tool.)

```json
{"jobName": "thermompnn-demo", "type": "thermompnn",
 "settings": {"pdbFile": "my_protein.pdb", "chains": ["A"], "topK": "10"}}
```

- `pdbFile` is a **file param**: upload first, then reference the **bare filename** (`my_protein.pdb`, NOT email-prefixed). See "File inputs" below.
- `chains` is a **LIST** (`["A"]`), required unless `allChains: true`. Indexing `[0]` silently designs the wrong scope on a multi-chain input.
- `verify` (auto-fold the designs with AlphaFold) is `exclude:["api","pipelines","batch"]` - it is UI-only premium and silently dropped over the API; leave it out.
- Output is a CSV of ranked mutations (wildtype residue, position, mutant, predicted ddG) plus the top-K sequences. Reconstruct a mutated sequence from the CSV columns, not by re-parsing the PDB.

### netsolp - sequence-only solubility / usability pre-screen

Predicts whether a protein will be soluble and expressible straight from its amino-acid sequence: a fast pre-screen before committing to expression. A protein-language-model classifier outputting a solubility and a usability score (0-1).

Pick it for **sequence-only solubility** when you have no structure. For **structure-aware** aggregation-driven solubility use `aggrescan3d`; for a compositional sequence method (with a 21-residue minimum) use `protein-sol`. NetSolP gives a single solubility readout, not a per-residue aggregation map.

```json
{"jobName": "netsolp-demo", "type": "netsolp",
 "settings": {"sequence": "MKTVRQERLKSIVRILERSKEPVSGAQLAEELSVSRQVIVQDIAYLRSLGYNIVATPRGYVLAGG"}}
```

Only `sequence` is required. For many sequences, the cleaner path is a `tamarind-batch` (one subjob per sequence) rather than building a multi-sequence payload by hand.

### aggrescan3d - structure-aware aggregation map

Predicts aggregation-prone regions on a folded protein surface (the A3D score mapped onto the 3D structure, accounting for surface exposure rather than raw sequence hydrophobicity), and supports rational solubility redesign. The structure-aware aggregation screen for a candidate or complex.

Pick it when you have a **structure** and want **per-residue, surface-aware** aggregation. For **sequence-only** aggregation/amyloid use a sequence model (`canya` for amyloid nucleation); for **antibody-specific** aggregation/viscosity use `deepsp` / `deep-viscosity`; for sequence-only solubility use `netsolp` / `protein-sol`.

```json
{"jobName": "aggrescan3d-demo", "type": "aggrescan3d",
 "settings": {"pdbFile": "my_structure.pdb"}}
```

`pdbFile` is the only param (the **bare filename** of an uploaded structure). It accepts a multi-chain **complex**, not just a monomer, so it scores aggregation in the assembled context. Output is per-residue A3D scores (CSV), an annotated structure with the propensity mapped on, and surface-map visualization assets.

## More developability tools (catalog: filter live, read the description, then getJobSchema)

One-line pointers; reach for one when its niche fits. They drift, so confirm the name and params live (`getAvailableTools(function="developability")`, then `getJobSchema`). Pass the lowercase tool `name`, not the displayName. Full map in `references/tools.md`.

**Thermostability / stability (ddG, Tm)**
- **thermompnn-d** - double point-mutation recommender for thermostability (structure input). Reach for it when single mutations (`thermompnn`) aren't enough and you want stabilizing pairs; `model` is `epistatic`/`additive`/`single`.
- **proteinmpnn-ddg** - unsupervised **fold-stability ddG saturation scan** (every position) on a monomer or multimer structure, built on ProteinMPNN. Reach for it to rank stabilizing single mutations across the whole structure with no labeled data. Stability only, NOT binding (for interface binding-ddG use `stabddg` in `tamarind-docking`).
- **rosetta-ddg-prediction** - **physics-based** (Rosetta) ddG-of-folding on a **monomer**; the Rosetta-grounded alternative to the ML `thermompnn` / `proteinmpnn-ddg` family. `saturationMutagenesis` toggles a full position scan (`positions` + `residueTypes`) vs a named `mutations` list (`chain.wt.pos.mut`, e.g. `A.V.1.K`); `protocol` is `cartddg2020`/`cartddg`/`flexddg`.
- **saprot** - structure-aware PLM that scores **intrinsic stability** (fold-robustness proxy) and binary **solubility** from a `sequence` OR a structure (`#1` on ProteinGym DMS); a quick developability triage. `properties` selects `solubility`/`stability`; `inputType` is `sequence`/`structure`.
- **temstapro** - sequence-based thermostability prediction (PLM); a quick thermostability call from sequence, no structure.
- **deepstabp** - predicts protein **melting temperature (Tm)** from sequence; reach for it when you want a numeric Tm rather than a mutation list (optional `growthTemp` and cell-vs-lysate `measurementCondition`).

**Aggregation / viscosity**
- **deepsp** - antibody **viscosity, spatial charge map (SCM), and spatial aggregation propensity (SAP)** from the **paired** heavy+light sequence; the antibody-specific aggregation/viscosity screen.
- **deep-viscosity** - antibody viscosity prediction from the **paired** heavy+light sequence; flags high-concentration formulation viscosity risk for an mAb.
- **apm** - note: the platform `apm` (All-Atom Protein Generative Model) is a **design** tool (it generates binder backbones from a complex PDB), not an aggregation scorer. For structure-aware aggregation use `aggrescan3d` above. Don't reach for `apm` to "map aggregation".

**Solubility**
- **protein-sol** - sequence-based solubility via compositional features; an alternative to `netsolp`. Requires sequences of at least 21 residues.

**Polyreactivity / non-specific binding**
- **polyxpert** - antibody (paired) polyreactivity classifier. Note the param names are `heavyChain` / `lightChain` (the Fv sequences), NOT `heavySequence`/`lightSequence`.

**Glycosylation**
- **n-linked-glycosylation** - predicts N-linked glycosylation **sequon sites** from a `sequence`; spot N-glyco motifs that affect manufacturability / heterogeneity.

**Immunogenicity**
- **deepimmuno** - predicts immunogenic epitopes for T-cell immunity (**Class I / CD8**): give a `sequence` (the top result from every 9-mer is returned) and optional `hlas` (class-I HLA alleles, `HLA-A*0201`-style; all by default). Use to flag immunogenic hotspots in a candidate.
- **tlimmuno** - **Class II / CD4** immunogenicity (TLimmuno2): scans sliding-window peptides (default `peptideLength` 15) of a `sequence` against HLA-II alleles (`hlas`, `DRB1_*`/`DQ`/`DP`-style, NOT the class-I `HLA-A*` format) for a CD4+ response. The Class-II counterpart to `deepimmuno`; reach for it for CD4 / MHC-II liabilities or neoepitope ranking.

**Therapeutic peptides**
- **peptiverse** - unified therapeutic-peptide developability: hemolysis, solubility, non-fouling, cell penetrance, toxicity, plus serum half-life (hours) and PAMPA / Caco-2 permeability, and optional peptide-protein binding affinity (`targetSequence`). `inputType` is `wt` (amino-acid `sequence`) or `smiles` (a `smilesInput` string, which handles cyclic / non-canonical peptides that sequence-only models can't). Reach for it to triage a peptide hit list, not a full protein.

**Antibody / nanobody profilers (TAP family)**
- **tnp** - nanobody/VHH developability profiler (TNP); the single-domain counterpart to `tap`. Takes one `sequence`. Use for a VHH, never `tap`.

## Running a job (build on the base loop)

The lifecycle is the same `validate -> submit -> poll -> download` as `tamarind-submit-and-poll`; only the `settings` are developability-specific. Sequence-only tools (`tap`, `tnp`, `netsolp`, `saprot`, `temstapro`, `deepstabp`, `deepsp`, `deep-viscosity`, `polyxpert`, `n-linked-glycosylation`, `deepimmuno`, `tlimmuno`, `peptiverse`, `protein-sol`) submit with inline text and validate fast; structure tools (`thermompnn`, `thermompnn-d`, `aggrescan3d`, `proteinmpnn-ddg`, `rosetta-ddg-prediction`) need a file param.

```bash
# probe deps, install only if missing
python3 -c "import requests" 2>/dev/null || python3 -m pip install -r scripts/requirements.txt || python3 -m pip install --user --break-system-packages -r scripts/requirements.txt

# sequence-only: submit + poll + download in one call
python3 scripts/tamarind_job.py run tap-run tap '{"heavySequence":"QVQL...","lightSequence":"QIVL..."}'

# structure-based: upload first, then reference the bare filename
python3 scripts/tamarind_job.py upload my_protein.pdb            # prints the bare filename
python3 scripts/tamarind_job.py run thermompnn-run thermompnn '{"pdbFile":"my_protein.pdb","chains":["A"],"topK":"10"}'
```

Run the submit+poll non-blocking: **Codex** as a foreground command with `yield_time_ms: 1000` (no `&`/`nohup`); **Claude Code** via Bash with `run_in_background: true`. Jobs are addressable by name from a fresh session, so you can submit a filter, persist the name, and collect later (see `tamarind-submit-and-poll`).

Use the MCP `validateJob` first when present: it is the authority and catches the first bad field with no spend. (The response may carry a `source` field like `"static-fallback"` - that labels how the **schema** was resolved, not whether the validator was reachable; act on `valid`, not `source`. Built-in tools always report `static-fallback`.) Inline file content makes `validateJob` upload synchronously and can be slow; reference an uploaded file by name to keep it fast, or skip the dry-run and let `submit-job` validate.

### File inputs (the structure tools)

A file param (`pdbFile`) takes a **bare filename** (`"pdbFile": "my_protein.pdb"`, NOT email-prefixed, NOT an `s3://` URL), a prior-job output path (`JobName/path/to/file.pdb`), or inline PDB text (multi-line `ATOM`/`HETATM` records). A plain string in a file field is treated as **inline content**, so an email-prefixed key 400s as not-uploaded. Upload with `tamarind_job.py upload <path>` (it returns the bare name) and confirm the registered name with `getFiles` / `GET /files`. **Don't put a sequence in a file param** - a structure goes in `pdbFile`, a sequence goes in `sequence`.

### Surface consequential choices before submitting

When the request fully specifies what to score, proceed. But when it's open-ended, or a setting materially changes the result, runtime, or cost (which axis to filter on, `topK` for ThermoMPNN, the `model` mode for ThermoMPNN-D, the HLA panel for DeepImmuno, the mutation set for StaB-ddG), present the meaningful options plus the default you'd otherwise apply and let the user pick **before** you submit. This matters most when filtering a **batch**: one shared-settings choice multiplies across every candidate.

## Reading back the scores

Developability tools return per-axis CSVs and metrics, not structures-to-rank, so reason about the **shape** of the output, not golden numbers:

- **`tap`** - the TAP metric row (PSH/PPC/PNC/CDR length/SFvCSP) with a green/amber/red flag each, plus the per-residue liability table. Triage on the amber/red flags and the liability count.
- **`thermompnn` / `thermompnn-d` / `proteinmpnn-ddg` / `rosetta-ddg-prediction`** - a CSV of point mutations with a predicted **fold-stability** ddG; read the column header for the sign convention (more-stabilizing direction differs by tool), then rank. (`stabddg` instead returns a **binding** ddG for interface mutations, not fold stability; see `tamarind-docking`.)
- **`netsolp` / `protein-sol` / `saprot` / `temstapro` / `deepstabp`** - a per-sequence score (solubility/usability, an intrinsic-stability + solubility readout for `saprot`, or a predicted Tm). Threshold to keep/drop.
- **`deepsp` / `deep-viscosity` / `polyxpert` / `deepimmuno` / `tlimmuno` / `n-linked-glycosylation` / `peptiverse`** - per-antibody, per-peptide, or per-sequence risk readouts (viscosity/SAP/SCM, polyreactivity class, immunogenic Class-I 9-mers or Class-II windows, glyco sequons, peptide developability). Read the keys, don't assume.
- **`aggrescan3d`** - per-residue A3D scores plus an annotated structure; look at the high-propensity surface patches, not just a single aggregate number.

The job row's `Score` (JSON string on completed jobs) is tool-family dependent, and `WeightedHours` is the billing unit. To learn a tool's exact output filenames, run one small job and `listJobFiles(jobName)` (MCP) before downloading; filenames vary by tool and version.

## Reference files

- [references/tools.md](references/tools.md): the full developability tool map by axis (thermostability / aggregation / solubility / viscosity / polyreactivity / glycosylation / immunogenicity / antibody profilers), the input-type-drives-the-pick reasoning, the TAP-vs-TNP split, and the deep-tool gotchas.
- [references/examples.md](references/examples.md): validated `settings` payloads for the canonical and catalog tools, a read-only self-check, a worked "filter a hit list in a batch" recipe, what-fails errors, and output-shape notes.
