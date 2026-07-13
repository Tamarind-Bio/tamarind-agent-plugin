# Enzyme: design, kinetics, function

> Operational examples in this reference use the Tamarind CLI. Query the live catalog and schema before relying on this grounded snapshot.

Enzyme work splits two ways: (1) **design** a new enzyme that keeps a known active-site / catalytic motif, and (2) **predict** an enzyme's function or kinetics for an existing or candidate sequence. Discover live, then read the schema:

```bash
tamarind --json tools --function enzyme-design
tamarind --json tools --modality enzyme
tamarind --json schema enzygen2
```

Mental model for picking:
- Known scaffold + catalytic residues, want full-length variants that keep the active site: `enzygen2` (the default enzyme-design tool).
- Theozyme (catalytic residues + ligand), want a complete de novo enzyme: `riffdiff` (RiffDiff-ProtFlow scaffolds the motif into a backbone and refines it end-to-end). For atom-level active-site scaffolding from atomic motifs: `rfdiffusion2`.
- A bound ligand (or DNA/RNA) but NO theozyme or template, want sequence + structure co-designed around it: `disco` (SOTA ligand-conditioned co-design).
- Generate enzyme sequences from an EC number (plus a required seed FASTA), no structure: `zymctrl`.
- Enzyme + substrate SMILES, want a kinetic number: `catpred` (kcat / Km / Ki) or `dlkcat` (kcat only, lighter).
- Sequence or structure, want to know WHAT it does (GO terms, EC class): `deepfri`.
- Labeled fitness data, want ML-guided variants: `proteus`. Evolutionary mutation-effect / covariation: `evcouplings`. Place metal ions: `allmetal3d`.

## Anchor tools

### enzygen2 (EnzyGen2): motif-conditioned enzyme co-design
Given a reference enzyme structure and the residue positions of its active site, generate new variants that keep those catalytic positions fixed while redesigning the rest, producing sequence + structure together. Taxonomy-aware (you give the target organism's NCBI ID).
- Required: `pdbFile` (bare filename `.pdb`/`.cif`), `chain` (e.g. `A`), `motif` (comma-separated PDB residue numbers, integers only, no chain prefix), `ncbiId` (e.g. `562` for E. coli), `numDesigns`. Optional: `decodingStrategy` (`greedy`/`top-k`/`top-p`), `toppProbability` (only when `decodingStrategy=top-p`).
- Gotcha: there is a per-chain residue ceiling (trained mostly on 200-600 residue proteins; very large chains fail fast at input parse). A bad chain ID or a non-integer `motif` token also fails at input.
- Finetune pair: `enzygen2-finetune` (train on your enzyme family) -> `enzygen2-inference` (`model` = the finetune job name). See `tamarind-finetune`.

### catpred (CatPred): kinetic-parameter prediction (kcat / Km / Ki)
Enzyme sequence + substrate SMILES -> predicted steady-state kinetics. Use it to rank variants by activity or screen substrates against one enzyme.
- Required: `sequence` (inline text), `smiles` (inline text). No optional knobs.
- Both inputs are inline strings, so no file upload is needed. Put one pair in a YAML/JSON settings file, validate it, then run `tamarind --json submit catpred --input FILE --name JOB_NAME`; use `tamarind-batch` to score many pairs.
- `dlkcat` is the lighter kcat-only predecessor (kcat, no Km/Ki).

### deepfri (DeepFRI): function prediction (GO + EC)
Sequence or structure -> Gene Ontology terms and Enzyme Commission number, optionally with residue saliency maps. Use it to annotate an uncharacterized enzyme or confirm a designed protein kept its intended function.
- `task` selector: `sequence` (then `sequence`, supports batching) or `PDB` (then `pdbFile`, bare filename). `ontology` is a LIST even for one value (e.g. `["mf","ec"]`; include `ec` for enzymes). Optional `saliency` emits class-activation maps.
- A bare string `ontology` can mis-parse; always a list.

## Catalog (one-liners)

- `enzygen2-inference`: design enzymes with a USER-finetuned EnzyGen2 checkpoint (paired with `enzygen2-finetune`); same shape as `enzygen2` plus a `model` reference.
- `riffdiff` (RiffDiff-ProtFlow): a COMPLETE de novo enzyme-design pipeline from a theozyme (catalytic residues + ligand). It inverts catalytic-residue rotamers into a motif-fragment library, connects fragments with RFdiffusion, then refines designs via LigandMPNN / Rosetta Relax / ESMFold cycles, so it produces finished backbones, not just a fragment library. Inputs: `pdbFile`, `resnums` (chain-prefixed, e.g. `A121 A153`), `ligands`.
- `rfdiffusion2`: SOTA atom-level enzyme active-site scaffolding, scaffolds unindexed atomic motifs directly (no inverse-rotamer or sequence-index pre-assignment), with an ORI token to control active-site placement (a design tool tagged `enzyme-design` + `motif-scaffolding`).
- `disco` (DISCO): SOTA multimodal diffusion that co-designs protein sequence + 3D structure conditioned on a bound small molecule, reactive intermediate, DNA, or RNA, with NO template scaffold or pre-specified catalytic residues. The pick for de novo enzyme / ligand-binding design when you have a target ligand but no theozyme. Also designs DNA/RNA-binding proteins (cross-ref [references/nucleic_acid.md](nucleic_acid.md)).
- `zymctrl` (ZymCTRL): conditionally generate artificial enzyme sequences from an EC number plus a seed FASTA. Inputs: `ecNumber` (e.g. `1.1.1.1`), `numSequences`, and `fastaFile` (`tamarind --json schema zymctrl` currently marks it required, despite the platform example showing EC-number-only). Confirm with `tamarind --json validate zymctrl --input FILE --name JOB_NAME`.
- `dlkcat` (DLKcat): deep-learning kcat-ONLY prediction from `sequence` + `smiles`; the lighter, kcat-only predecessor to `catpred`.
- `proteus` (ProteusAI): ML-assisted directed evolution: train on experimental fitness data (CSV with a sequence column + a fitness-score column) to propose improved variants. Inputs: `csvFile`, `sequenceColumn`, `fitnessScoreColumn`.
- `evcouplings` (EVcouplings): function and mutation effects from evolutionary covariation (DCA over an MSA built from the input). Input: `sequence`. Builds its own alignment.
- `allmetal3d` (AllMetal3D): predict and ADD metal-ion binding sites (and waters) to a structure, for metal-dependent catalysis. Inputs: `pdbFile`, `models`, `mode` (`fast`/`all`/`site`), optional `centralResidue` / `radius` / `threshold` for site mode.

For execution mechanics (validate, submit, poll, download, batch), see `tamarind-submit-and-poll` and `tamarind-batch`.
