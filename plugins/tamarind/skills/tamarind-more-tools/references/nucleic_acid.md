# Nucleic-acid: design, language models, codon optimization

> Operational examples in this reference use the Tamarind CLI. Query the live catalog and schema before relying on this grounded snapshot.

RNA/DNA sequence design, mRNA codon optimization, nucleic-acid language models (embeddings + scoring), and structure-conditioned generation. This domain does NOT cover cofolding a complex that happens to contain RNA/DNA (that is structure prediction: `boltz`, `chai`, `protenix`, `esmfold2`, which carry the `nucleic-acid` modality but predict a 3D complex rather than design or score a sequence).

Discover live, then read the schema:

```bash
tamarind --json tools --modality nucleic-acid
tamarind --json tools --function rna-design
tamarind --json tools --function rna-language-models
tamarind --json tools --function codon-optimization
tamarind --json schema evo2
```

Alphabet matters: DNA tools use `ACGT`, RNA tools use `ACGU`. A lowercase or wrong-alphabet input is usually the wrong tool.

## Anchor tools

### evo2 (Evo 2): genome-scale DNA language model
Generate or embed nucleotide sequences across domains of life.
- `task` selector: `generate` (then `seed` DNA prompt + `length` / `numSequences` / `temperature` / `topK` / `topP`) or `embeddings` (then `sequence` + `embeddingLayer`). `model` (`7b` default; `20b` needs an H100 and routes to a larger GPU tier; `40b` coming soon).
- DNA alphabet `ACGT` only. The sequence field accepts a pasted FASTA or an uploaded CSV; each sequence becomes its own subjob (a fan-out).
- For RNA, use `rna-fm`; for mRNA-specific work, `mrnabert` / `orthrus`.

### rna-fm (RNA-FM): RNA embeddings + secondary structure
- `task` selector: `extract_embedding` (then `backbone` `rna-fm`/`mrna-fm`, `saveEmbeddingsFormat` `raw`/`mean`/`bos`) or `ss_prediction` (then `visualize` boolean). `sequence` is RNA (`ACGU`).
- The `mrna-fm` backbone requires the input length divisible by 3 (it tokenizes codons). The only secondary-structure predictor here; 3D RNA folds are a structure-prediction job.

### ribodiffusion (RiboDiffusion): RNA inverse folding
Given a target RNA 3D backbone, design sequences predicted to fold into that shape.
- Required: `pdbFile` (bare filename, the RNA structure to condition on), `numDesigns`. Optional: `modelVariant`, `condScale` (0-1; w=1 emphasizes sequence recovery, lower increases diversity), `dynamicThreshold`.
- `numDesigns > 1` fans out to one subjob per design, so poll the batch parent's `batchStatus`. `rhodesign` is the sibling RNA inverse-folding model.

### Codon optimization set
Turn a protein into an optimized mRNA coding sequence. Pick by objective:
- `derna` (DERNA): Pareto-optimal mRNA design jointly optimizing folding stability (MFE) and codon adaptation (CAI).
- `vaxpress` (VaxPress): genetic-algorithm codon optimizer for mRNA vaccine design (ViennaRNA folding + codon-usage objectives).
- `mrnabert` (mRNABERT): SOTA mRNA language model. Synonymous codon optimization that maximizes model likelihood while preserving the encoded protein, over the FULL mRNA (UTR + CDS); also scores candidates by pseudo-log-likelihood and runs per-position mutation scans. The learned-model pick when UTRs matter, not just the CDS.
- `syn-codon-lm` (SynCodonLM): a learned codon language model for codon optimization and codon embeddings; synonymous-masked, CDS-only, an alternative to the rule/MFE-based optimizers.

## Catalog (one-liners)

- `mrnabert`: pretrained mRNA language model for sequence scoring, point-mutation effects, codon optimization, and embeddings; for an mRNA CDS you want to score or optimize with a learned model.
- `orthrus`: mRNA embeddings from a cDNA sequence (`ACGT`), with optional CDS-position and 5' splice-site annotations; learned mRNA features for downstream stability/expression models.
- `rhodesign` (RhoDesign): deep generative RNA sequence design from a 3D structure (the sibling to `ribodiffusion`); for a second inverse-folding model or a different objective.
- `rfdpoly` (RFDpoly): diffusion-based de novo design of RNA / DNA / nucleoprotein-complex STRUCTURES (RFdiffusion for polymers): `na-binder-against-target` (design a DNA/RNA binder against a fixed protein target) or `unconditional` (contig grammar). Generates new backbones, the opposite of `ribodiffusion`.
- `disco` (DISCO): SOTA co-design of a PROTEIN sequence + structure conditioned on a bound DNA or RNA, i.e. de novo DNA/RNA-binding protein design with no template (lives in [references/enzyme.md](enzyme.md)). Complement of `rfdpoly`, which designs the nucleic-acid side rather than the protein.
- `dnaworks` (DNAWorks): oligonucleotide design for PCR-based gene synthesis (break a gene into synthesis-ready oligos); a utility, not an ML model.
- `emboss` (Emboss Backtranseq): deterministic protein-to-DNA back-translation; for optimized codons use `derna` / `vaxpress` / `syn-codon-lm`.
- `nampnn` / `ligandmpnn`: for mixed-polymer or protein+RNA/DNA inverse folding over a multi-polymer structure (vs `ribodiffusion`, which is RNA-only). These live in the inverse-folding skill.
- `waypoint` (Waypoint): embeds microbiome abundance SAMPLES (not a sequence-design or single-sequence tool, despite the modality).

For execution mechanics and the batch-parent polling that fan-out designs need, see `tamarind-submit-and-poll` and `tamarind-batch`.
