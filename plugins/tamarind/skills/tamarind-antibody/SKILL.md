---
name: tamarind-antibody
description: "Use for antibody and nanobody / VHH engineering on Tamarind Bio: de novo CDR design against an epitope (RFantibody), CDR sequence redesign on a complex (IgDesign, AbMPNN), antibody/nanobody/TCR structure prediction (ImmuneBuilder), plus numbering (ANARCI, IgBLAST), humanization (Humatch, BioPhi), and paratope/repertoire search. Not for general non-antibody binder design (use tamarind-binder-design), not for generic protein or complex structure prediction (use tamarind-structure-prediction), not for antibody developability scoring like TAP / TNP (use tamarind-developability). Pairs with tamarind-submit-and-poll for the run loop and tamarind-batch for screening many designs."
license: MIT
metadata:
  version: "1.0"
required_environment_variables:
  - TAMARIND_API_KEY
---

# Tamarind Bio: antibody and nanobody engineering

Design, redesign, and model antibodies and nanobodies (VHH) on Tamarind's managed GPUs: generate brand-new CDR loops against an epitope, resequence CDRs on an existing complex, predict an Fv / VHH / TCR structure, number and humanize a candidate, and search repertoires. This skill is the antibody-specific layer; it builds on the base run loop in `tamarind-submit-and-poll` (validate, submit, poll, download) and uses `tamarind-batch` to screen many designs.

If `TAMARIND_API_KEY` is unset or a call returns 401, run `tamarind-api-setup` first. Always `getJobSchema` / `validateJob` a tool before submitting; the catalog and schemas drift, so the live schema is the authority, not this page.

## Don't keyword-match a pure-antibody tool over the established generalist

This is the most common antibody mis-pick. When the user names an antibody but the task is generic, an AlphaFold3-class cofolder or a general designer is usually the better, more validated choice than a niche antibody-only tool that merely has "antibody" in its description:

- **Antibody-antigen complex structure** (you have both sequences and want the bound pose + interface metrics): reach for a cofolder, `boltz` / `chai` / `protenix` (`tamarind-structure-prediction`). `protenix` specifically touts antibody-antigen interface gains. Use the antibody-only structure predictors below (`immunebuilder` / `abodybuilder`) when you want a fast variable-domain model **without** the antigen.
- **A general protein binder** against a target that happens to be on an antibody scaffold: `rfdiffusion` / `boltzgen` / `bindcraft` (`tamarind-binder-design`) often fit better than forcing an antibody-design tool. `boltzgen` and `promera` natively span nanobodies/antibodies AND general binders in one model.
- **Inverse folding on an antibody backbone** with no CDR-specific intent: plain `proteinmpnn` (with `modelType: "abmpnn"`) or `tamarind-inverse-folding` may be all you need; the dedicated `abmpnn` tool is for when you want antibody-aware CDR detection built in.

Rule: match the user's INTENT (input you have, output you need), not the word "antibody". Filter live by `function` + `modality=antibody`, read each candidate's `description`, and let `validateJob` confirm it accepts your input before committing. Reach into THIS skill when the work is genuinely antibody-specific: CDR-aware design, paratope/epitope targeting, numbering, or VHH/humanization machinery.

## Canonical tools (deep)

Four tools cover the bulk of antibody work. Confirm required fields with `getJobSchema(<tool>)` before submitting; the payloads here are schema-derived starting points.

### rfantibody - de novo CDR design against an epitope

Generate brand-new antibody or nanobody binders from scratch against a target antigen: you give the antigen structure plus the epitope hotspots, and it designs novel CDR-loop backbones and sequences docked onto that epitope (an RFdiffusion -> ProteinMPNN -> RoseTTAFold2 pipeline). The antibody-native analog of RFdiffusion binder design.

Pick it for **de novo CDR generation against a specific epitope on a known antigen structure**. If you only want to redesign CDR sequence on a FIXED backbone (not generate new loops), use `igdesign` / `abmpnn` / `antifold` / `antidif` instead; for a general non-antibody binder use `tamarind-binder-design`.

Key settings (live `getJobSchema`): `task` (`antibody`|`nanobody`, required), `framework` (named scFv/nanobody frameworks `hu-4D5-8_Fv` / `h-NbBCII10`, or `custom` to upload your own via `antibodyFile` + chain IDs), `targetFile` (required `.pdb` antigen, **bare filename**), `antigenChains` (required list; multiple chains merge into one continuous target), `hotspots` (per-chain residue map like `{"A": "305, 456"}`, schema-optional with `default: ""` but effectively required: without hotspots the design is not steered to your epitope, so always set them; pass ORIGINAL chain+resnum, the wrapper remaps), `regions` (which CDRs to design, default all 6 / 3 HCDRs for nanobody), per-region length knobs (`hcdr1Length`..., accept a fixed length, a range, or `auto`), and `numDesigns`. `abmpnnWeights: true` uses AbMPNN weights in the sequence stage.

```json
{"jobName": "rfab-nanobody-demo", "type": "rfantibody",
 "settings": {"task": "nanobody", "framework": "h-NbBCII10",
   "targetFile": "antigen.pdb", "antigenChains": ["A"],
   "hotspots": {"A": "305, 456"}, "regions": ["hcdr1", "hcdr2", "hcdr3"],
   "numDesigns": 100, "temperature": 0.1}}
```

(Upload `antigen.pdb` first, then pass the bare filename. ACE/NME capping groups are auto-stripped. An unmatched hotspot residue is rejected with a clear error.)

### igdesign - wet-lab-validated CDR redesign on a complex

Given an antibody/nanobody-antigen **complex** structure, design new CDR sequences (especially HCDR3) more likely to bind, with the antigen explicitly in context. Its designs were experimentally validated to bind in vitro; it is the strongest "redesign CDRs on an existing complex" choice when you can condition on the target.

Pick it over `abmpnn` when you have a complex and want antigen-conditioned design with a published wet-lab pedigree. If you have only the antibody (no antigen), use `abmpnn` / `antifold` / `antidif`. To GENERATE new loops de novo, use `rfantibody`.

Key settings: `task` (required), `pdbFile` (required `.pdb`, ideally the complex), `heavyChain` / `lightChain` (light only for `task=antibody`) / `antigenChain` (note: a SINGLE `antigenChain`, unlike rfantibody's list), `regions` (default all CDRs; `["hcdr3"]` is the headline use case), `condition_on_antigen` (default true) / `condition_on_light_chain` (default false), `numBatches` (each batch = 1000 designs; start at 1). The input PDB should be IMGT-numbered if you hand-pick CDR residues (`selectCDRIndices`).

```json
{"jobName": "igdesign-hcdr3-demo", "type": "igdesign",
 "settings": {"task": "antibody", "pdbFile": "complex.pdb",
   "heavyChain": "B", "lightChain": "L", "antigenChain": "A",
   "regions": ["hcdr3"], "condition_on_antigen": true,
   "condition_on_light_chain": false, "numBatches": 1}}
```

### abmpnn - antibody-tuned inverse folding

Redesign the sequence of an antibody/nanobody from its backbone using ProteinMPNN weights fine-tuned on antibody structures (CDR positions get antibody-specific priors). The fastest antibody-aware inverse folder, and the antibody analog of plain `proteinmpnn`. Use it to diversify CDRs or recover a sequence for a designed backbone.

Pick it for fast antibody-aware sequence design from a backbone. For antigen-conditioned, wet-lab-validated CDR design on a complex use `igdesign`; for a diffusion-based antibody inverse folder use `antidif`, the AntiFold model `antifold`, or the AbLang+MPNN ensemble `ablang-mpnn`.

API-driver note (from `getJobSchema`): `designedChains` is `exclude: ["api"]` and `verifySequences` is `exclude: ["api", "pipelines", "batch"]` - do NOT pass either over the API/MCP; they are silently dropped. The API shape is `pdbFile` + `designedResidues` (per-chain, space-separated resnums) with `detectCDRs: false`, OR `detectCDRs: true` + `regions` (subset of the 14 framework/CDR labels). Cysteine is omitted by default (`omitAAs: "C"`); override if you want disulfides.

```json
{"jobName": "abmpnn-cdrh-demo", "type": "abmpnn",
 "settings": {"pdbFile": "antibody.pdb", "detectCDRs": false,
   "designedResidues": {"B": "26 27 28 29 30 31 32 52 53 54 55 56 95 96 97 98 99 100 101 102"},
   "numSequences": 8, "temperature": 0.2, "omitAAs": "C"}}
```

### immunebuilder - fast Fv / VHH / TCR structure prediction

Predict the 3D structure of an antibody (Fv), nanobody (VHH), or TCR directly from sequence in seconds, no MSA. The lightweight default when you just need a good-enough variable-domain model before docking, design, or developability scoring.

Pick it for the fastest sequence-to-structure of a variable region. For a refined antibody-only model use `abodybuilder` (ABodyBuilder3) or `flashabb` (structure + developability + embeddings in one pass); for a nanobody with HCDR3 / disulfide priors use `nbforge`; for a conformational ensemble use `abb4` or `its-flexible`. When you need the **antigen complex** (not the antibody alone) or high-accuracy cofolding, use `boltz` / `chai` / `protenix` (`tamarind-structure-prediction`).

Sequence-only (no file), so it validates fast and runs via `submitJob` with inline text: `modelType` (`Antibody`|`Nanobody`|`TCR`), `sequence1` (heavy / alpha), `sequence2` (light / beta - required for Antibody and TCR, omit for Nanobody).

```json
{"jobName": "immunebuilder-ab-demo", "type": "immunebuilder",
 "settings": {"modelType": "Antibody",
   "sequence1": "EVQLVESGGGVVQPGGSLRLSCAASGFTFNSYGMHWVRQAPGKGLEWVAFIRYDGGNKYYADSVKGRFTISRDNSKNTLYLQMKSLRAEDTAVYYCANLKDSRYSGSYYDYWGQGTLVTVS",
   "sequence2": "VIWMTQSPSSLSASVGDRVTITCQASQDIRFYLNWYQQKPGKAPKLLISDASNMETGVPSRFSGSGSGTDFTFTISSLQPEDIATYYCQQYDNLPFTFGPGTKVDFK"}}
```

For a nanobody: `{"modelType": "Nanobody", "sequence1": "<VHH sequence>"}` (drop `sequence2`).

## More antibody tools (catalog - filter live, read the description, then `getJobSchema`)

These are one-line pointers; reach for one when its niche fits. They drift, so confirm the name and params live (`getAvailableTools(modality="antibody", function=...)` then `getJobSchema`). Full map in `references/tools.md`.

- **De novo / generative design:** `germinal` (SOTA epitope-targeted de novo nanobody/scFv design from a target structure: ColabDesign hallucination -> AbMPNN CDR redesign -> cofold filter), `iggm` (joint CDR-sequence + antibody-antigen complex co-design against a target antigen; epitope-specific when you pass epitope residues), `mber` (VHH binder design, lighter than rfantibody), `evonb` (mutate/optimize nanobody sequences with a VHH language model, supports finetuning), `nos-inference` (property-guided discrete-diffusion antibody generation: finetune on paired heavy/light sequences with numeric property labels, then infill masked positions toward that property), `adapt` (structure-based TCR / TCR-mimic antibody design against a peptide-MHC target), `mage` (de novo antibody generation from antigen SEQUENCE when you have no structure), `antibody-diffusion-properties` (property-aware CDR design), `abgpt` (unconditional generative antibody-sequence LM, no antigen conditioning), `lichen` (light-chain sequences conditioned on a heavy chain).
- **Inverse folding (existing backbone):** `antifold` (AntiFold model), `antidif` (diffusion-based antibody inverse folding), `ablang-mpnn` (AbLang + ProteinMPNN ensemble). Antigen-conditioned redesign is `igdesign` above; fast antibody-aware is `abmpnn` above.
- **Structure / conformation:** `abodybuilder` (ABodyBuilder3, refined antibody-only), `flashabb` (FlashABB - fast structure + developability + embeddings in one pass), `nbforge` (nanobody structure with HCDR3 blueprint + disulfide priors), `abb4` (conformational ensemble), `its-flexible` (CDR3 loop flexibility), `tcrmodel2` (TCR-peptide-MHC COMPLEX modeling where AF-Multimer fails on docking orientation / CDR3; immunebuilder models the TCR Fv alone, this does the pMHC complex).
- **Affinity / sequence optimization + naturalness scoring:** `ablang` (AbLang2, SOTA antibody-specific LM: score how natural a VH/VL is, suggest non-germline CDR/framework mutations, restore masked residues, emit antibody embeddings, filter designs for naturalness; likelihood is not affinity, rank binding with the developability ddG tools), `antibody-evolution` / `antiberty` / `cosine` (affinity-maturation mutation recommendations), `balm-paired` (score point mutations with the paired heavy+light LM).
- **Humanization:** `humatch` (Humatch - humanization evaluation + mutation recommendation), `biophi` (BioPhi - OASis/Sapiens humanness scoring + humanization). Both live under `function=humanization`.
- **Numbering / annotation / search:** `anarci` (ANARCI - the canonical CDR/framework numbering utility), `igblast` (IgBLAST - germline assignment, searches public DBs from nucleotide or AA), `antibody-annotation` (annotate CDRs/regions), `oas` (OAS Search - find similar natural-repertoire sequences), `plabdab` (search antibodies from patents + literature), `space2` (cluster by structural similarity for epitope binning).
- **Paratope / interface / affinity:** `paragraph` / `parasurf` (predict paratope residues), `p2pxml` (antibody-antigen IC50), `dsmbind` (antibody-antigen affinity), `deeprank-ab` (rank antibody-antigen models by predicted DockQ).

### Cross-references to other skills (don't reach for the wrong skill)

- **Developability** (does this antibody survive manufacturing and the clinic): `tap` (TAP2, Therapeutic Antibody Profiler - paired antibodies), `tnp` (TNP, Therapeutic Nanobody Profiler - the VHH analog), plus thermostability (`tempro`), polyreactivity (`nanobody-polyreactivity`, `polyxpert`), viscosity, aggregation, and immunogenicity (`deepimmuno`, `tlimmuno`) all live in **`tamarind-developability`**. Run those as FILTERS on a hit list after design. The TAP-vs-TNP split is paired-antibody vs single-domain VHH.
- **Antibody-antigen complex structure + interface metrics:** the cofolders `boltz` / `chai` / `protenix` in **`tamarind-structure-prediction`**.
- **General (non-antibody) binders:** `rfdiffusion` / `boltzgen` / `bindcraft` in **`tamarind-binder-design`**.
- **Generic inverse folding / protein language models:** `proteinmpnn` and the PLM family in **`tamarind-inverse-folding`**.

## Running a job (build on the base loop)

The lifecycle is the same `validate -> submit -> poll -> download` as `tamarind-submit-and-poll`; only the `settings` are antibody-specific. Sequence-only tools (`immunebuilder`) submit with inline text; structure tools (`rfantibody`, `igdesign`, `abmpnn`) need a file param.

**File params take a BARE filename** (`"targetFile": "antigen.pdb"`, NOT email-prefixed, NOT an `s3://` URL), a prior-job output path (`JobName/path/to/file.pdb`), or inline PDB text. A plain string in a file field is treated as inline content, so an email-prefixed key 400s as not-uploaded. Upload first:

```bash
# probe deps, install only if missing
python3 -c "import requests" 2>/dev/null || python3 -m pip install -r scripts/requirements.txt || python3 -m pip install --user --break-system-packages -r scripts/requirements.txt

python3 scripts/tamarind_job.py upload antigen.pdb            # prints the bare filename to reference
python3 scripts/tamarind_job.py run rfab-demo rfantibody @settings.json   # submit + poll + download
```

(Run the submit+poll non-blocking: Codex foreground with `yield_time_ms: 1000`; Claude Code `run_in_background: true`. Jobs are addressable by name from a fresh session.) Use the MCP `validateJob` first when present - it is the authority and catches the first bad field with no spend. Act on `valid`, not the `source` label (built-in tools always report `static-fallback`, a schema-resolution note, not a "validator down" signal). Inline-content file params make `validateJob` upload synchronously and can be slow; reference an uploaded file by name to keep it fast (or pass inline PDB text for a quick no-upload dry-run).

**Surface consequential choices before submitting.** De novo design knobs multiply cost and runtime: `numDesigns` / `numBatches` (igdesign produces 1000 designs per batch), `regions` (all 6 CDRs vs HCDR3-only), `task` antibody-vs-nanobody, and the framework. When the request is open-ended, present the meaningful options plus your default and let the user pick before you submit, especially in a batch where one shared choice multiplies across every job.

## Ranking and reading back designs

A design job emits many candidates; rank them by interface confidence, don't eyeball the zip. The bundled `scripts/summarize_binder_metrics.py` reads a downloaded design results dir and prints designs ranked by the interface metric (ipSAE / ipTM / pDockQ / pLDDT) plus the max + 10th-best + fraction-above-cutoff summary:

```bash
python3 scripts/summarize_binder_metrics.py <downloaded-run-dir>
python3 scripts/summarize_binder_metrics.py <run-dir> --metric plddt --cutoff 80 --json
```

For RFantibody, also reason about epitope distance when `calculateEpitopeDistance` is on (min distance from designed CDR loops to the hotspots) - a design that scores well but sits off the epitope is not what you asked for. To fold designed sequences back for verification, chain into a cofolder (see `tamarind-structure-prediction` and the chaining recipe in `tamarind-submit-and-poll`).

## Reference files

- [references/tools.md](references/tools.md): the full antibody tool map (de novo / inverse-folding / structure / affinity / humanization / numbering / paratope), the when-to-pick reasoning, and the deep-tool gotchas (hotspot remapping, IMGT numbering, the `exclude:["api"]` fields).
- [references/examples.md](references/examples.md): validated/schema-derived `settings` payloads for the four canonical tools, a worked de-novo-then-rank recipe, and output-shape notes.
