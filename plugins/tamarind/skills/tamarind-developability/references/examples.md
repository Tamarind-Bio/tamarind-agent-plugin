# Tamarind Bio: developability example payloads

The freshest example for any tool is the `exampleJob` that MCP `getJobSchema(<tool>)`
returns: a `{jobName, type, settings}` assembled from each param's example/default (file
params get placeholder names). It is the best starting point, but **run `validateJob` on it
before submitting** - it is built from per-param examples, not a guaranteed-valid payload.
The payloads below are a worked, `validateJob`-confirmed fallback for REST callers. Schemas
evolve; if one stops validating, re-fetch with `getJobSchema(<tool>)`. Sequences here are
illustrative; swap your own candidate.

**File params (`pdbFile`) need a real file value:** the **bare filename** of an uploaded file
(`my_protein.pdb`, NOT email-prefixed), a prior-job output path (`JobName/out/x.pdb`), or
inline PDB text (multi-line `ATOM`/`HETATM` records). A `<...>` placeholder is NOT valid as
written; replace it. Don't put an amino-acid sequence in a file param - a structure goes in
`pdbFile`, a sequence goes in `sequence` (or `heavySequence`/`lightSequence`).

`BASE = "https://app.tamarind.bio/api"`, `HEADERS = {"x-api-key": <key>}`.

## Self-check (run this first, read-only, no cost)

Confirms the discover -> validate loop end to end with no submission:

```python
import os, requests
BASE, HEADERS = "https://app.tamarind.bio/api", {"x-api-key": os.environ["TAMARIND_API_KEY"]}
tools = requests.get(f"{BASE}/tools", headers=HEADERS).json()
assert any(t["name"] == "tap" for t in tools), "developability tools reachable"
```

With the MCP, `validateJob(jobName="selfcheck", type="netsolp", settings={"sequence":"MKTVRQERLKSIVRILERSKEPVSGAQLAEELSVSRQVIVQDIAYLRSLGYNIVATPRGYVLAGG"})` returns `valid: true`.

## Canonical tools

### tap - paired-antibody developability scorecard (sequence-only, validates fast)
```json
{ "heavySequence": "QVQLQQSGAELARPGASVKMSCKASGYTFTRYTMHWVKQRPGQGLEWIGYINPSRGYTNYNQKFKDKATLTTDKSSSTAYMQLSSLTSEDSAVYYCARYYDDHYCLDYWGQGTTLTVSS",
  "lightSequence": "QIVLTQSPAIMSASPGEKVTMTCSASSSVSYMNWYQQKSGTSPKRWIYDTSKLASGVPAHFRGSGSGTSYSLTISGMEAEDAATYYCQQWSSNPFTFGSGTKLEIN" }
```
Both chains **required** (TAP is paired-only; an empty chain fails). For a single-domain
nanobody use `tnp` instead (below).

### tnp - nanobody / VHH developability (single `sequence`)
```json
{ "sequence": "QVKLQESGAELARPGASVKLSCKASGYTFTNYWMQWVKQRPGQGLDWIGAIYPGDGNTRYTHKFKGKATLTADKSSSTAYMQLSSLASEDSGVYYCARGEGNYAWFAYWGQGTTVTVSS" }
```
ONE `sequence` (the VHH). Never run `tap` on a nanobody (no light chain) or `tnp` on a paired
antibody (it ignores the light chain).

### thermompnn - propose stabilizing single mutations (structure input)
```json
{ "pdbFile": "<uploaded-bare-filename-or-inline-PDB-text>",
  "chains": ["A"], "topK": "10" }
```
`pdbFile` is a file param (upload first, reference the bare filename). `chains` is a **LIST**,
required unless `allChains: true`. `topK` is the max sequences out (a string dropdown). Do NOT
pass `verify` over the API (`exclude:["api","pipelines","batch"]`, silently dropped).

### thermompnn-d - propose stabilizing double mutations
```json
{ "pdbFile": "<uploaded-bare-filename-or-inline-PDB-text>",
  "chains": ["A"], "model": "epistatic" }
```
`model` is one of `epistatic` / `additive` / `single`. Default `threshold` (-0.5 kcal/mol) only
saves mutations below it; set it high (e.g. 100) to save all. `distance` filters double mutants
by pairwise Ca distance (default 5 A).

### netsolp - sequence-only solubility / usability
```json
{ "sequence": "MKTVRQERLKSIVRILERSKEPVSGAQLAEELSVSRQVIVQDIAYLRSLGYNIVATPRGYVLAGG" }
```
Only `sequence`. For many sequences, prefer a `tamarind-batch` (one subjob per sequence).

### protein-sol - sequence-only solubility (compositional)
```json
{ "sequence": "MALKSLVLLSLLVLVLLLVRVQPSLGKETAAAKFERQHMDSSTSAASSSNYCNQMMKSRNLTKDRCKPVNTFVHESLADVQAVCSQKNVACKNGQTNCYQSYSTMSITDCRETGSSKYPNCAYKTTQANKHIIVACEGNPYVPVHFDASV" }
```
Requires sequences of at least 21 residues (a shorter one is rejected).

### aggrescan3d - structure-aware aggregation map
```json
{ "pdbFile": "<uploaded-bare-filename-or-inline-PDB-text>" }
```
Only `pdbFile` (bare filename). Accepts a multi-chain complex, scoring aggregation in the
assembled context.

### temstapro / deepstabp - thermostability / Tm from sequence
```json
{ "sequence": "AKLAGQKVRIGGWVKTGRQQGKGTFAFLEVNDGSCPANLQVMVDSSLYDLSRLVATGTCVTVDGVLKIPPEGKGLKQSIELSVETVIAVGTVDP" }
```
`temstapro` (thermostability call) and `deepstabp` (numeric Tm) both take just `sequence`;
`deepstabp` also accepts optional `growthTemp` and `measurementCondition` (`cell`/`lysate`).

### stabddg - protein-protein BINDING ddG of interface mutations (home: tamarind-docking)
```json
{ "pdbFile": "<uploaded-bare-filename-or-inline-PDB-text>",
  "binder1Chains": ["A", "B", "C"], "binder2Chains": ["D", "E"],
  "mutations": ["EA63Q,QD30V,KA66A"] }
```
StaB-ddG scores protein-protein **binding** ddG for **interface** mutations on a complex (SKEMPIv2
SOTA), NOT fold/monomer thermostability; its home skill is `tamarind-docking`, shown here only
because affinity maturation is developability-adjacent. Mutations are `wildtype+chain+position+mutant`
(e.g. `EA63Q` = E->Q at position 63 of chain A), one per line; commas join a multi-point mutant on
one entry. `binder1Chains` / `binder2Chains` define the two interface partners. Uses your PDB's
numbering (it renumbers each chain to start at 1 internally and reports the renumbered string).

### proteinmpnn-ddg - fold-stability ddG saturation scan (structure input)
```json
{ "pdbFile": "<uploaded-bare-filename-or-inline-PDB-text>",
  "chains": "H", "topK": "10" }
```
Unsupervised **fold-stability** ddG over every position on a monomer/multimer structure (stability,
NOT binding). `pdbFile` is a file param (upload first, reference the bare filename); `chains` selects
the chain(s) to scan; `topK` caps the output. For interface binding-ddG use `stabddg` (in
`tamarind-docking`) instead.

### rosetta-ddg-prediction - physics-based ddG-of-folding (monomer)
```json
{ "pdbFile": "<uploaded-bare-filename-or-inline-PDB-text>",
  "saturationMutagenesis": false, "mutations": ["A.V.1.K"] }
```
Rosetta ddG-of-folding on a **monomer**. Named-mutation mode (`saturationMutagenesis: false`) needs
`mutations` (`chain.wt.pos.mut`, e.g. `A.V.1.K`, newline-separated, commas for a multi-point entry);
saturation mode (`saturationMutagenesis: true`) needs `positions` + `residueTypes` instead. `protocol`
is `cartddg2020` (default) / `cartddg` / `flexddg`.

### saprot - intrinsic stability + solubility (sequence or structure)
```json
{ "inputType": "sequence", "properties": ["solubility", "stability"],
  "sequence": "MKTVRQERLKSIVRILERSKEPVSGAQLAEELSVSRQVIVQDIAYLRSLGYNIVATPRGYVLAGG" }
```
Structure-aware PLM scoring **intrinsic stability** + binary **solubility**. `inputType` is
`sequence` (give `sequence`) or `structure` (give `pdbFile`); `properties` selects `solubility` /
`stability`. The sequence path needs no structure.

### deepsp / deep-viscosity - antibody aggregation / viscosity (paired)
```json
{ "heavySequence": "QVQLQQSGAELARPGASVKMSCKASGYTFTRYTMHWVKQRPGQGLEWIGYINPSRGYTNYNQKFKDKATLTTDKSSSTAYMQLSSLTSEDSAVYYCARYYDDHYCLDYWGQGTTLTVSS",
  "lightSequence": "QIVLTQSPAIMSASPGEKVTMTCSASSSVSYMNWYQQKSGTSPKRWIYDTSKLASGVPAHFRGSGSGTSYSLTISGMEAEDAATYYCQQWSSNPFTFGSGTKLEIN" }
```
Both take the paired `heavySequence` + `lightSequence`. `deepsp` returns viscosity + SCM + SAP;
`deep-viscosity` returns viscosity.

### polyxpert - antibody polyreactivity (note the param names)
```json
{ "heavyChain": "QVQLQESGGGVVQPGRSLRLSCAASGFTFSSYGMHWVRQAPGKGLEWVAVIWYDGSNKYYADSVKGRFTISRDNSRNTLYLQMNSLRGEDTAVYYCAKRGTGSSFYYFDYWGQGTLVTVSS",
  "lightChain": "EIVLTQSPSALSASVGDRVTITCRASQNIANYLNWYQQKPGKPPKLLIYVASNLPSGVPSRFSGSGSGTDFTLTISGLQPDDFATYYCQQSYTTPRTFGQGTKVDIK" }
```
`polyxpert` uses `heavyChain` / `lightChain` (the Fv sequences), NOT
`heavySequence`/`lightSequence`. Copying the TAP/DeepSP param names here fails.

### n-linked-glycosylation - N-glyco sequon sites
```json
{ "sequence": "MALKSLVLLSLLVLVLLLVRVQPSLGKETAAAKFERQHMDSSTSAASSSNYCNQMMKSRNLTKDRCKPVNTFVHESLADVQAVCSQKNVACKNGQTNCYQSYSTMSITDCRETGSSKYPNCAYKTTQANKHIIVACEGNPYVPVHFDASV" }
```

### deepimmuno - T-cell immunogenicity (Class I / CD8)
```json
{ "sequence": "HPPLMNVER", "hlas": ["HLA-A*0201"] }
```
`sequence` required (the top result from every 9-mer is returned). `hlas` is optional (all
class-I alleles by default, `HLA-A*`-style); narrow to the relevant HLA panel for a targeted read.

### tlimmuno - MHC class II / CD4 immunogenicity (TLimmuno2)
```json
{ "sequence": "GLLFRRLTSREVLLL", "hlas": ["DRB1_0803"] }
```
`sequence` required (sliding-window peptides are scanned; default `peptideLength` 15, max
immunogenicity reported). `hlas` are HLA class-II alleles in the `DRB1_*` / `DQ` / `DP` format,
NOT the class-I `HLA-A*` format that `deepimmuno` uses; the default is the full HLA-II panel.

### peptiverse - therapeutic-peptide developability (sequence or SMILES)
```json
{ "inputType": "wt", "sequence": "GIVEQCCTSICSLYQLENYCN" }
```
`inputType` is `wt` (give an amino-acid `sequence`) or `smiles` (give a `smilesInput` string for a
cyclic / non-canonical peptide). Pass an optional `targetSequence` to also get a peptide-protein
binding-affinity class (High / Moderate / Low). For a standard protein, use the protein scorers
above, not PeptiVerse.

## Worked recipe: filter a hit list of designs in one batch

After a design or fold stage, score the whole shortlist through one developability tool in a
single `tamarind-batch` call, then keep the candidates that pass. This folds the filter over N
inputs (poll the batch PARENT's `batchStatus`, not subjob `JobStatus` - see `tamarind-batch`):

```bash
# Score MANY antibody candidates with TAP in one batch: use the inline submit_batch()
# client function (see tamarind-batch). The tamarind_job.py CLI has no batch subcommand;
# `submit` posts a SINGLE job, so it cannot drive a batch.
#   from tamarind_client import submit_batch
#   submit_batch("dev-batch", "tap", jobNames, settingsList)   # then poll the parent's batchStatus
# Single candidate, one-at-a-time:
python3 scripts/tamarind_job.py run cand-a-tap tap '{"heavySequence":"...","lightSequence":"..."}'
```

For a structure-based filter (e.g. `aggrescan3d` / `thermompnn` across a set of folded
candidates), upload each structure first, then reference the bare filename in each subjob's
settings. The general pattern is the same: one developability tool over many inputs is a batch.

## What fails (and why), confirmed live

- **`tap` with only one chain** - rejected: TAP is paired-only, it needs both `heavySequence`
  and `lightSequence`. For a single-domain nanobody use `tnp` (one `sequence`).
- **`polyxpert` with `heavySequence`/`lightSequence`** - wrong param names; it expects
  `heavyChain` / `lightChain`.
- **A sequence in `pdbFile`** (thermompnn/aggrescan3d/stabddg) - rejected with a file-type
  error. A structure goes in the file param; a sequence goes in `sequence`.
- **An email-prefixed file key** (`{email}/my.pdb`) in a file param - treated as inline content
  and 400s as not-uploaded. Use the BARE filename.
- **`thermompnn` `chains` as a bare string** instead of a list, or passing `verify` over the
  API (silently dropped, `exclude:["api"]`).
- **`protein-sol` with a sequence under 21 residues** - rejected (minimum length).
- **Building a submit from `validateJob`'s `normalized` echo** - submit the clean settings you
  validated, not the normalized blob (it carries filled-in defaults).

## Output shapes (describe, don't expect exact values)

Read the metric KEYS, don't hardcode golden numbers; outputs depend on the candidate and on
the folded structure (for sequence tools that fold first, like TAP):

- **tap / tnp** - the TAP/TNP metric row (PSH/PPC/PNC/CDR length/SFvCSP) with a green/amber/red
  flag each, plus a per-residue liability table (deamidation, isomerization, oxidation,
  glycosylation, unpaired cysteine, glycation). Triage on the amber/red flags + liability count.
- **thermompnn / thermompnn-d / proteinmpnn-ddg / rosetta-ddg-prediction** - a CSV of point
  mutations with a predicted **fold-stability** ddG. Read the column header for the sign convention
  before ranking (more-stabilizing direction differs by tool). (`stabddg` instead returns a
  protein-protein **binding** ddG; it lives in `tamarind-docking`.)
- **netsolp / protein-sol / saprot / temstapro / deepstabp** - a per-sequence score (solubility +
  usability 0-1, an intrinsic-stability + solubility readout for saprot, or a predicted Tm).
  Threshold to keep/drop a candidate.
- **deepsp / deep-viscosity / polyxpert / deepimmuno / tlimmuno / n-linked-glycosylation /
  peptiverse** - per-antibody, per-peptide, or per-sequence risk readouts (viscosity/SAP/SCM,
  polyreactivity class, immunogenic Class-I 9-mers or Class-II windows, glyco sequons, peptide
  developability/permeability/half-life).
- **aggrescan3d** - per-residue A3D scores (CSV) plus an annotated structure with the propensity
  mapped on; look at the high-propensity surface patches, not just a single aggregate.

Job-row `Score` (JSON string on completed jobs) is tool-family dependent; `WeightedHours` is
the billing unit. To learn a tool's exact output filenames, run one small job and
`listJobFiles(jobName)` (MCP) before downloading - filenames vary by tool and version.
