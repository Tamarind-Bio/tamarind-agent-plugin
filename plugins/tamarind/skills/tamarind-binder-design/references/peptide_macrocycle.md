# Peptide and macrocycle binders

> Operational examples in this reference use the Tamarind CLI. Query the live catalog and schema before relying on this grounded snapshot.

The peptide/macrocycle family on Tamarind covers linear peptide binders, head-to-tail cyclized macrocycles, and the sequence/structure tooling around them. Source of truth is `tamarind --json schema TOOL`; payloads below are grounded snapshots, so re-query if one stops validating. File parameters take the **bare filename** returned by `tamarind --json files upload PATH`, not an email-prefixed key.

## Pick by what you have and the shape you want

- Target protein + you want a CYCLIZED (macrocyclic) binder -> **`rfpeptides`** (designs backbone AND sequence from scratch).
- A cyclic backbone already in hand, you only need sequences for it -> **`cyclicmpnn`** (inverse folding on a fixed cyclic backbone).
- A LINEAR peptide binder from just the target's SEQUENCE (no structure) -> **`pepmlm`**.
- A de novo cyclic peptide, a binder against a target protein or a free scaffold -> **`afcycdesign`**.
- Mimic a KNOWN binder's interface rather than design fresh -> **`pepmimic`**.
- Predict the structure of a cyclic-peptide sequence you already have -> a cyclic structure predictor (lives in `tamarind-structure-prediction`), not a design tool.

---

## rfpeptides (RFpeptides): macrocyclic binder against a target

RFdiffusion run with a cyclic-offset/closure protocol to generate macrocyclic backbones, then ProteinMPNN sequence design and AlphaFold-style refold validation (optional Rosetta scoring with a license). Cyclic backbones tend to be more protease-resistant and conformationally constrained than linear peptides.

- `pdbFile` (required, `.pdb`): target structure.
- `binderLength` (required, default `"12-18"`): single length (`"14"`) or a range sampled uniformly (`"12-18"`).
- `targetChains` (list, e.g. `["A"]`).
- `binderHotspots` (per-chain residue map, **space-separated** author residue numbers, e.g. `{"A": "48 50 51 52 62 65"}`): target residues to focus the interface on. The wrapper also tolerates comma-separated, but prefer the space-separated schema form.
- `numDesigns` (default 1, large ceiling, batched internally at 64/batch): total macrocycles to generate. For a large sweep, prefer the built-in batching over many separate jobs.
- `temperature` (default 50): the **RFdiffusion denoising-step count** (T), displayed as "Diffusion Steps"; 50 matches the RFpeptides paper. NOT a sampling temperature despite the field name.
- `rosetta` (default false): license-gated interface scoring; contact Tamarind to enable.

Output: per-design macrocyclic backbone + designed-sequence PDBs, plus refold/designability metrics (AlphaFold refold i_pae per design; with `rosetta: true`, interface ddg and i_pae from Rosetta).

Validated payload:
```json
{"pdbFile": "target.pdb", "targetChains": ["A"], "binderLength": "12-18",
 "binderHotspots": {"A": "48 50 51 52 62 65"}, "numDesigns": 8, "temperature": 50}
```

---

## afcycdesign (AfCycDesign): de novo cyclic peptides (binder or free scaffold)

Hallucinates head-to-tail cyclic-peptide backbones by inverting AlphaFold with a cyclic-offset positional encoding, redesigning a starting structure into a cyclized peptide. Designs cyclic-peptide binders against a target protein as well as target-free novel cyclic scaffolds; confirm the exposed fields with `tamarind --json schema af-cyc-design`.

- `pdbFile` (required, `.pdb`): starting structure to cyclize/redesign.
- `chain` (required, single chain ID, e.g. `"A"`): the chain to design.
- `numDesigns` (default 1): number of cyclic peptides to generate.

The schema is intentionally lean (just `pdbFile` + `chain` + `numDesigns`); do not invent temperature/seed knobs that are not exposed. Scale with `numDesigns`.

Output: per-design cyclic-peptide PDB structures with AlphaFold confidence (pLDDT-style) metrics.

Validated payload:
```json
{"pdbFile": "start.pdb", "chain": "A", "numDesigns": 4}
```

---

## pepmlm (PepMLM): linear peptide binder from a sequence

An ESM-2-based masked protein language model that generates linear peptide sequences predicted to bind a supplied target. The fastest, lowest-input path: you only need the target SEQUENCE, no structure, no MSA.

- `targetSequence` (required): the target protein sequence to design against.
- `peptideLength` (required, default 15): length of each designed peptide.
- `numDesigns` (required, **dropdown** with discrete values `[1,2,4,8,16,32]`, default 8): passing an arbitrary integer (e.g. 10) is invalid; pick one of the options.

Output: a set of `numDesigns` linear peptide sequences (each `peptideLength` long) with the model's per-sequence score/perplexity.

Validated payload (all-sequence input, directly runnable):
```json
{"targetSequence": "MQRGKVKWFNNEKGYGFIEVEGGSDVFVHFTAIQGEGFKTLEEGQEVSFEIVQGNRGPQAANVVKE",
 "peptideLength": 15, "numDesigns": 8}
```

Note: pure sequence-in, sequence-out, no structure prediction or docking. A high-scoring peptide still needs downstream validation: cofold the target plus the designed peptide with a structure-prediction tool, or screen developability. Output is LINEAR; for cyclic/macrocyclic binders use `rfpeptides`.

---

## pepmimic (PepMimic): mimic a known binder's interface

Designs peptide binders by reproducing a KNOWN binder's interface, via latent-diffusion generation. Reach for it when you have one or more reference protein-binder complexes and want new peptides that recreate that interface.

- `refComplexesZip` (required, bare filename of an uploaded zip): the zip must contain the reference PDBs AND an `index.txt`. `index.txt` is tab-separated: `<pdb-noext>` then target chains then binder chains (comma-separated) then an annotation. Every PDB referenced in `index.txt` must be present in the zip.
- `lengthLowerBound` / `lengthUpperBound`: peptide length, must be <= 25 (the model's training ceiling).
- `numSamplesPerComplex`: how many peptides to sample per reference complex.

Generation-only on the platform (no FoldX/Rosetta scoring step bundled). Score the output downstream.

---

## cyclicmpnn (CyclicMPNN): sequences for a given cyclic backbone

Inverse folding for cyclic peptides: designs stable sequences for a GIVEN cyclic backbone (a ProteinMPNN-family model with a cyclic offset). Reach for it after `rfpeptides` / `afcycdesign` gives you a macrocyclic backbone and you want diverse sequences that fold to it.

- `pdbFile` (required): the cyclic backbone.
- `designedChains`, `designedResidues` (per-chain residue subset to design): per-residue scope uses sequential numbering from each chain's min author number with gaps included.
- `numSequences` (default 2).
- `temperature` (0.1-0.3 suggested): sampling temperature for sequence diversity.

This is a sequence-design step, not a backbone generator. (It also appears under inverse folding; `tamarind-inverse-folding` is the general home for sequence design on fixed backbones.)

---

## The peptide design-then-validate loop

A typical macrocyclic-binder campaign chains generation -> validation:

1. **Generate** with `rfpeptides` (target + hotspots) or `afcycdesign` (free scaffold). Poll to Complete.
2. **Diversify sequences** for a chosen backbone with `cyclicmpnn` if you want more than the designed sequence per backbone.
3. **Validate** the structure of a designed cyclic sequence with a cyclic-peptide structure predictor (in `tamarind-structure-prediction`), and screen developability (peptide property tools live under the developability/utility skills).

Chain by reference when the downstream schema accepts it: pass a prior job's output in the `JobName/path/to/file.ext` form into the next tool's file parameter. If the exact output path is uncertain, download the completed upstream result with `tamarind --json results JOB_NAME --download DIRECTORY`, inspect the extracted bundle, and use the documented relative path. See `tamarind-submit-and-poll` and the binder `examples.md` for the mechanics.
