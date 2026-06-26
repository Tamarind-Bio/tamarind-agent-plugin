# Search + format utilities

Homology / structure search, structural alignment, and format / misc utilities. Discover live, then read the schema:

```
getAvailableTools(function="structure-search")    # foldseek, foldmason, us-align
getAvailableTools(function="utilities")            # the broad utility set
getJobSchema(jobType="foldseek")                   # exact params before you submit
```

Pick by what you have and what you want:
- A STRUCTURE, find similar folds in a big DB: `foldseek search`. Cluster a pile of structures by fold: `foldseek cluster`.
- A SEQUENCE, find homologs: `blast` (general public DBs), `psiblast` (distant/remote homologs). For antibodies: `igblast` (V(D)J annotation), `oas` (Observed Antibody Space).
- Align MANY structures at scale: `foldmason`. A careful pairwise structural superposition + TM-score: `us-align`.
- Convert a file format: `file-converter`. Rebuild side chains on a coarse (CA-only) model: `pulchra`. Trim disordered regions: `alphacutter`. A quick pI / charge estimate: `ipc`.

File params take a BARE filename uploaded first; `validateJob` checks file existence (an unuploaded filename returns `valid:false` while the rest resolved). You can also chain by passing an `s3Path` from `listJobFiles` of a prior job.

## Anchor tools

### foldseek (Foldseek): ultra-fast structure search
Given a protein structure, find structurally similar structures across large databases (homology / function transfer by structure, not sequence), or cluster structures by fold.
- `task` selector: `search` or `cluster`. For `search`: `database` (`pdb`, several `alphafold-*` sets, `esmatlas30`, `custom` upload, `custom-fasta` build-a-DB-from-sequences), and `pdbFile` (the query) unless `database=custom-fasta` (then `fastaFile`). For `cluster`: `proteinFiles` (PDBs or a zip). Tunables: `sensitivityToSpeed`, `maxSeqs`, `evalue`, `alignmentType`, `coverage`; `customOutputColumns` + `outputColumns` to pick BLAST-tab columns.
- For a `custom-fasta` (sequence-built) DB the wrapper drops structural columns (no real coordinates), so do not expect TM-scores / LDDT back from it.

### blast (BLAST) and psiblast: sequence search
- `blast`: `sequence` (protein or DNA, set `dnaSequence:true` for DNA); `database` (`nr`, `swissprot`, `pdbaa`, etc.); `evalue`, `maxTargetSeqs` (capped at 100), `wordSize`, `gapCosts`, `organism` (taxonomy filter). Runs against NCBI's REMOTE service, so runtime varies with NCBI load.
- `psiblast`: position-specific iterated BLAST for distant homologs plain BLAST misses.

### foldmason (FoldMason): multiple structure alignment
Align MANY protein structures at scale via a 3Di guide tree, vs `foldseek` which searches a DB.

## Catalog (one-liners)

**MSA / alignment / co-evolution**
- `msa`: build a multiple sequence alignment (ColabFold MMseqs2) for a sequence; the raw a3m artifact to feed a precomputed-MSA tool or to inspect. (Most structure predictors run their own MSA internally; standalone `msa` is for reuse / caching / analysis. See `tamarind-structure-prediction` for the MSA primer.)
- `msa-analysis`: align a user-supplied set of related protein sequences (FASTA in -> MSA out) via Clustal Omega / MUSCLE / MAFFT (algorithm auto-selected), returning the alignment plus quality/stats. The standalone aligner for a KNOWN sequence set (downstream phylogenetics, conserved-motif spotting), vs `msa` which builds a deep ColabFold MMseqs2 alignment from a single query.
- `msa-cluster`: cluster sequences within an MSA into sub-families.
- `hmmalign`: align a list of sequences to a profile / HMM.
- `evcouplings`: residue contacts, function, and mutation effects from evolutionary covariation (DCA).
- `pysca`: statistical coupling analysis of an MSA (co-evolving sectors / allostery).
- `afcluster`: predict alternate conformations by clustering an MSA and folding each cluster (subsampled AF2).

**Structure alignment / clustering / RMSD**
- `us-align`: universal structural alignment + TM-score for proteins and nucleic acids (a careful pairwise superposition).
- `align-pdbs`: superpose a list of PDB files onto a common frame.
- `rmsd-calculator`: RMSD between two structures (a single pairwise deviation number).
- `cluster-pdbs`: cluster a list of PDBs or MD-trajectory frames (geometry / RMSD-based).

**Structure quality / property analysis** (these score / characterize a structure; metric read-back lives in `tamarind-results-analysis`)
- `molprobity`: structure quality check (clashes, rotamers, Ramachandran).
- `pulchra`: all-atom reconstruction / refinement of reduced (CA-only) models.
- `legolas`: predict NMR chemical shifts from a PDB.
- `protein-metrics` (COMPSS): score sequences using protein-language-model metrics.
- `protein-properties`: quick biophysical property panel on a sequence / structure.
- `rog`: radius of gyration (compactness).
- `surfmap`: 2D projection of protein surface features (electrostatics, hydrophobicity).
- `pdbsum`: overview + schematic diagrams of chains, DNA, ligands, metals.
- `min-distance-selected-residues`: minimum distance between two sets of selected residues.
- `superwater`: add explicit waters to a structure (SOTA score-based water placement, surface + binding sites).
- `allmetal3d`: predict and place metal ions (identity + coordination geometry, no metal preselected) plus structural waters on a protein; pairs with `superwater` for explicit hydration. (Also surfaced in the enzyme reference for metalloenzyme prep.)
- `propka`: empirical pKa of ionizable protein residues (Asp/Glu/His/Lys/Arg/Cys/Tyr, and ligand groups in a complex) from a 3D structure; assign protonation states at a target pH before MD / docking / QM, or flag buried / catalytic residues with shifted pKa.
- `alphacutter`: remove non-globular (disordered / linker) regions from a predicted structure (trim AF2/ESMFold predictions to ordered domains).

**Sequence / antibody database search and conversion**
- `psiblast` / `igblast` / `oas`: distant-homolog / antibody-germline / Observed-Antibody-Space search (see anchors above; antibody numbering also lives in `tamarind-antibody`).
- `file-converter`: convert between molecular file formats (e.g. PDB/CIF/SDF).
- `ipc` (IPC 2.0): predict isoelectric point and pKa (a quick pI / charge estimate).

Note: `tmd` is tagged here by name overlap but is a free-energy MD engine, not a "TM-align"-style structural aligner; see [references/md.md](md.md).

For execution mechanics, see `tamarind-submit-and-poll`.
