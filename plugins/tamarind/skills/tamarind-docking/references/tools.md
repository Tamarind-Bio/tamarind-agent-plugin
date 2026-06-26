# Tamarind docking and affinity tools

Per-tool detail for the dockers and scorers this skill covers. `getJobSchema(<tool>)` is the authority for required fields, options, bounds, and defaults; this file captures when-to-pick and the gotchas the schema does not spell out. Schemas evolve, so re-fetch if a payload stops validating. Filter the live catalog with `getAvailableTools(function="protein-ligand-docking")` or `function="protein-protein-docking"`.

A note that applies to every file-typed param below (`receptorFile`, `proteinFile`, `ligandFile`, `wildtypeFile`, `mutantFile`): reference an uploaded file by its **bare filename** (e.g. `receptor.pdb`), never an email-prefixed S3 key. Upload first, then pass the returned bare name. A raw string in a file param is treated as inline file CONTENT, not a reference. See `tamarind-submit-and-poll/references/api_reference.md`.

The receptor in a docking job should be a CLEAN protein PDB. The wrappers run a receptor-prep pipeline (strip HETATM, `pdb2pqr`, convert to PDBQT), so bound waters, ions, and cofactors in the input can perturb the prep. Strip non-protein heteroatoms before docking unless a cofactor is meant to stay.

---

## autodock-vina (Autodock Vina)

Find where a drug-like molecule docks in a KNOWN protein pocket and estimate its binding affinity, so you can rank candidate ligands or confirm a hypothesized binding mode. Classical physics-based docking: it samples ligand poses inside a user-defined search box and scores them with the AutoDock Vina empirical scoring function.

Pick autodock-vina when:
- You KNOW the pocket and can give box coordinates, and you want a fast, interpretable, well-validated baseline. Especially when SCREENING many ligands against ONE receptor box (it accepts a SMILES, or a `.smi`/`.csv` of many SMILES against the same box).
- For CNN-rescored pose ranking on the same search, use `gnina`. For Vina-family docking with custom scoring/minimization, use `smina`.
- For an UNKNOWN pocket with no box, use a blind ML docker (`diffdock`, `unimol2`) that finds the site itself. (`surfdock` is NOT blind; it needs a `referenceLigandFile` defining the site.)
- Do not use Vina for protein-protein docking (`equidock` / `geodock`) or for co-folding a complex from sequence (`boltz` / `chai` / `protenix`).

Schema highlights (from `getJobSchema`):
- `receptorFile` (required, `.pdb`): the protein. Bare filename. (Note: `receptorFile` here, NOT `proteinFile` like the others.)
- `ligandFormat` (dropdown, default `sdf`): `sdf` or `smiles`. **Lowercase** here (DiffDock uses different strings).
- `ligandFile` (required when `ligandFormat=="sdf"`, `.sdf`): the ligand structure. Bare filename.
- `ligandSmiles` (required when `ligandFormat=="smiles"`, type `smiles`): a SMILES string, or upload a `.smi`/`.csv` with one SMILES per row to screen many ligands against the same receptor box.
- Bounding box (all required, number): `boxX`/`boxY`/`boxZ` (center, default 0), `width`/`height`/`depth` (dimensions, default 10).
- `exhaustiveness` (number, default 8): search effort; raise to 32 for a more reproducible result.

Gotchas:
- SMILES are converted to a SINGLE 3D conformer with OpenBabel before docking, so Vina samples rotatable bonds but NOT ring conformations. For multi-stereocenter, strained-ring, or macrocyclic ligands, pre-generate conformers (the Conformer Generation tool) and submit as SDF.
- The box must be a FOCUSED pocket box (~20-30 Angstroms per side), not the whole protein. A box exceeding the protein bounding box makes the search explode and time out. For whole-protein blind docking use `gnina wholeProtein` or `diffdock`.
- The schema box center defaults to `0,0,0`, which usually misses the protein. Supply real coordinates (a known ligand centroid, a pocket-residue centroid, or a pocket-detection job's output).

Output: a docked ligand pose in `ligand_out.{pdbqt,sdf,pdb}` plus a `log.txt` with the Vina binding-affinity table (kcal/mol per pose; more negative is better). Delivered as a result zip via `getResult`.

---

## diffdock (DiffDock)

Predict how a ligand binds a protein WITHOUT knowing the pocket, so you can find the binding site and a plausible pose from structure + ligand alone. Diffusion-model docking: it generates poses by denoising over translation/rotation/torsion, no search box required.

Pick diffdock when:
- You do NOT have box coordinates and want blind, site-agnostic pose prediction fast. The go-to when the pocket is unknown.
- When you DO know the pocket and want an interpretable physics score with a defined box (and many-ligand screens), use `autodock-vina` / `smina`. For a search-based dock plus a CNN affinity, use `gnina`.
- For state-of-the-art ML docking when DiffDock poses look off, try `unimol2` (strong general docker), or `surfdock` (surface-informed) if you have a reference-bound ligand for the site (it requires `referenceLigandFile`).
- To co-fold the whole complex from SEQUENCE (no input receptor structure), use `boltz` / `chai` / `protenix` (in `tamarind-structure-prediction`).

Schema highlights (from `getJobSchema`):
- `proteinFile` (required, `.pdb`): the receptor. Bare filename. (Named `proteinFile`, NOT `receptorFile`.)
- `ligandFormat` (required, dropdown, default `sdf/mol2 file`): `sdf/mol2 file` or `SMILES`. These option STRINGS differ from Vina's lowercase `sdf`/`smiles`; use the exact strings (capital `SMILES`).
- `ligandFile` (required when `ligandFormat=="sdf/mol2 file"`, `.sdf` or `.mol2`): the ligand. Bare filename; the wrapper routes by extension.
- `ligandSmiles` (required when `ligandFormat=="SMILES"`, type `smiles`): one connected ligand SMILES.
- No box params (blind docking; that is the point).

Gotchas:
- DiffDock REJECTS a multi-fragment ligand SMILES: a `.` in `ligandSmiles` (disconnected fragments / salts) errors. Strip counterions to a single connected ligand first.
- DiffDock predicts the POSE; it does not return a physics binding energy. For an affinity number, rescore a top pose with `gnina scoreOnly`, or use a structure-based affinity model (`aev-plig`, `gems`) or a cofolding affinity head (`boltz`).

Output: ranked docked ligand poses (multiple ranks) with DiffDock confidence scores in the filenames (higher confidence is better; ordering IS the rank). Delivered as a result zip.

---

## gnina (GNINA)

Dock a ligand into a protein and rank poses with a deep-learning (CNN) scorer layered on AutoDock-Vina-style search, giving better pose discrimination than the raw Vina score. Also supports whole-protein blind docking and pure scoring of a supplied pose.

Pick gnina when:
- You want docking PLUS a learned CNN affinity/pose score (its headline advantage over Vina/smina), or blind whole-protein docking while still wanting a search-based, box-capable method.
- Use `gnina scoreOnly` to score an EXISTING ligand pose (e.g. rescore a DiffDock or cofold pose) without re-docking.
- For the lightest, most interpretable classical baseline, or for large SMILES/CSV screens, use `autodock-vina`. For smina's custom scoring-function tuning, use `smina`.

Schema highlights (from `getJobSchema`):
- `proteinFile` (required, `.pdb`): the protein. Bare filename.
- `ligandFile` (required, `.sdf`): the ligand. Bare filename. **No SMILES option** in the gnina schema; supply an SDF (convert a SMILES to a 3D SDF first via Conformer Generation / obabel). (The schema's `descr` mislabels the ligand field "for your receptor"; it is the ligand.)
- Bounding box (all required, number): `boxX`/`boxY`/`boxZ` (center; defaults 35/27/35), `width`/`height`/`depth` (defaults 20).
- `cnnScoring` (dropdown, default `rescore`): `none` / `rescore` / `refinement` / `metrorefine`. More CNN scoring = slower, better pose ranking.
- `wholeProtein` (boolean, default false): search the whole receptor; when true the box coordinates and size are IGNORED. Use this for blind docking instead of guessing a box.
- `exhaustiveness` (number, default 8): search effort; raise to 32 for consistency.
- `scoreOnly` (boolean, default false): score the supplied ligand pose as-is (returns CNN affinity + pose score for the input conformation) without docking.

Gotchas:
- `wholeProtein:true` maps to an autobox over the receptor and ignores the box fields, so do not also rely on the box center when whole-protein is on.
- gnina expects an SDF ligand specifically; there is no SMILES branch. Convert SMILES to a 3D SDF first.

Output: docked poses in `out/result.sdf`, a combined receptor+ligand PDB, and `out/log.txt` with CNN affinity + pose scores. `scoreOnly` returns the score of the input pose with the ligand copied through. Delivered as a result zip.

---

## prodigy (PRODIGY)

Predict the ABSOLUTE binding affinity (binding free energy dG and dissociation constant Kd) of a protein-PROTEIN complex from a single 3D structure, using PRODIGY's contact-based regression on interfacial residue contacts. The fast, classic answer to "how tight is this PPI?" given a complex you already have.

Pick prodigy when:
- You want ABSOLUTE protein-protein affinity (dG / Kd) of ONE complex structure, with a quick, interpretable, contact-based number, no GPU and no training data.
- For the CHANGE in affinity from a mutation (a delta), use `binding-ddg` (wildtype vs mutant) or the interface scanners `proteinmpnn-ddg-binder` / `stabddg`. (Plain `proteinmpnn-ddg` scores fold STABILITY, not binding; use the `-binder` sibling for interface ddG.)
- For antibody-antigen complexes and a learned model rather than a contact heuristic, use `dsmbind`.
- To score docking/interface QUALITY rather than affinity, use `dockq`, `pdockq`, `ipsae`, or `spatial-ppi`.

Schema highlights (from `getJobSchema`):
- `proteinFile` (required, `.pdb`): the protein COMPLEX structure to predict dG for (both partners in one PDB). Bare filename.

Gotchas:
- PRODIGY is for PROTEIN-PROTEIN complexes; it is not a protein-ligand tool (no small-molecule affinity). For protein-ligand affinity use `aev-plig` / `gems` / `boltz-affinity-inference`.
- The structure must already CONTAIN the bound complex; PRODIGY scores the interface in the given pose, it does not dock. Chain a fold/dock job upstream if you only have separate partners.
- A bare-filename payload validates as `valid:false` ("File ... has not been uploaded") until you upload the PDB; that is expected (schema-correct, file-gated), not a settings error.

Output: an `output.csv` of PRODIGY properties (predicted binding affinity dG, predicted dissociation constant Kd, interfacial-contact counts by polarity) plus the raw log. Delivered as a result zip.

---

## Affinity and interface-scoring set (a number off a structure, no pose)

These take a STRUCTURE you already have and return a binding/interface number, not a docked pose. When you only have sequence, chain a fold tool (`boltz` / `alphafold` / `chai`) upstream first. `getJobSchema(<tool>)` for exact fields.

Protein-ligand affinity:
- `aev-plig` (AEV-PLIG): protein-ligand affinity from a 3D complex (atomic-environment-vector graph model). Takes `pdbFile` (protein) + `sdfFile` (bound ligand). Fast structure-based number, no finetuning. Reach for it on a docked pose.
- `gems` (GEMS): GNN protein-ligand affinity with language-model embeddings; same inputs as aev-plig (`pdbFile` + `sdfFile`). Try both on a docked pose and compare.
- `balm-inference` (Inference BALM): protein-ligand affinity from SEQUENCE + SMILES (no 3D structure), via a protein-language-model. Takes a `csvFile` with a protein-sequence column + a drug-SMILES column. The pick for high-throughput sequence-only screening when you have no structures.
- `boltz-affinity-inference` (Boltz-2 Affinity Inference): predict small-molecule binding affinity with a Boltz-2 affinity head FINETUNED on your own measured data. It is the inference half of a finetune+inference pair: requires a prior `boltz-affinity-finetune` run, and a `model` set to that finetune job's name. See `tamarind-finetune`. For an out-of-the-box number without finetuning, prefer `aev-plig` / `gems` / `balm-inference`.

Protein-protein / antibody-antigen affinity:
- `prodigy`: see the canonical entry above (absolute PPI dG/Kd from one complex).
- `dsmbind` (DSMBind): learned antibody-antigen (or single-chain-binder) binding-affinity prediction. Takes a `task` (antibody vs nanobody), a binder PDB + chain(s), and a target PDB + chain. The learned alternative to PRODIGY's contact heuristic for Ab-Ag.

Interface quality (not affinity):
- `dockq` (DockQ): compare a MODEL complex against a NATIVE (ground-truth) complex and report the standard DockQ quality score. Takes `modelFile` + `nativeFile` (both PDB). The benchmark tool when you DO have a reference structure.
- `pdockq` (PDockQ): predict the DockQ score of a single predicted complex from one `pdbFile`, no native reference needed. A quick interface-confidence estimate on an AlphaFold / Boltz complex.
- `ipsae` (IPSAE): interface scoring (ipSAE / ipTM-style) for AlphaFold or Boltz complexes from the model's PAE/pLDDT metrics. An `inputType` toggle picks the AF2 vs Boltz input shape. Re-score interfaces straight from a fold job's confidence outputs.
- `contact-ms` (Contact Molecular Surface): distance-weighted contact molecular surface area at a protein-protein interface from a complex PDB (target-side + binder-side CMS, fraction of target surface contacted). The standard interface-burial filter in de novo binder-design pipelines (Cao et al. Nature 2022); a geometric scorer (needs an existing complex), sibling to intercaat/dockq/pdockq.

Mutation-effect ddG:
- `binding-ddg` (Binding ddG): how a set of point mutations changes the binding affinity of a protein-protein (or antibody-antigen) complex, by comparing a wildtype complex vs a mutant complex (a delta). Takes `wildtypeFile` + `mutantFile` (both `.pdb`, SAME LENGTH). Output: a single predicted ddG float (negative = mutation stabilizes binding). Small molecules / heteroatoms are stripped from both inputs before prediction.
- `proteinmpnn-ddg` (ProteinMPNN-ddG): a fast structure-conditioned ddG PROXY ranking single-mutation candidates by a ProteinMPNN logit-difference score (a ranking score, not a calibrated kcal/mol energy). Takes `pdbFile` + `chains` (+ optional `topK`). For mutation effects on BINDING specifically, the sibling `proteinmpnn-ddg-binder` takes binder + receptor chains.

---

## Wider catalog (one line each; confirm params live)

`getAvailableTools(function="protein-ligand-docking" | "protein-protein-docking")` to enumerate, `getJobSchema(<tool>)` for params.

More small-molecule dockers:
- `smina` (Smina): customizable AutoDock-Vina fork; Vina-style box docking with extra scoring/minimization control. `proteinFile` + `ligandFile` (SDF) + box; the public schema is box + SDF only (no SMILES branch).
- `surfdock` (SurfDock): surface-informed diffusion docking. NOT blind: its schema REQUIRES `referenceLigandFile` (an SDF of a ligand bound in the pocket) to define the site, plus `proteinFile` + `ligandFormat` + `ligandFile`/`ligandSmiles` (optional `numSamples` ~40, `numRescored` ~10). Pick it when you have a reference-bound ligand defining the site and want a surface-aware ML alternative to DiffDock, NOT for a truly unknown pocket.
- `unimol2` (Uni-Mol Docking V2): state-of-the-art ML protein-ligand docking; reach for it when DiffDock poses look wrong and you want a strong pocket-aware deep-learning docker.
- `flowdock` (FlowDock): flow-matching docking that returns BOTH a pose and an affinity estimate in one shot.
- `af2dock` (AF2-based docking), `dfmdock` (DFMDock): AF2-representation and diffusion-variant ML docking alternatives.

Local pose-ensemble refinement (NOT a docker; needs an existing pose):
- `placer` (PLACER): local protein-ligand conformational ENSEMBLE sampling plus active-site preorganization scoring around an EXISTING pose (SOTA for local ensemble modeling, PNAS 2025; used as the design filter in Baker-lab enzyme-design pipelines). It is not a blind docker, it needs an initial pose, so pair it DOWNSTREAM of a docker (Vina / GNINA / Uni-Mol2 / FlowDock) or a cofold. Good for modeling joint ligand + side-chain conformational heterogeneity and active-site preorganization of designed enzymes.

De novo ligand / pocket generation (designing, not docking; these are small-molecule generators, discover via `getAvailableTools(function="ligand-generation")`):
- `drugflow` (DrugFlow): SOTA structure-based pocket-conditioned de novo small-molecule generation built around a REFERENCE LIGAND that defines the site (ICLR 2025); emits an SDF library for downstream docking/scoring.
- `diffsbdd` (DiffSBDD): SE(3)-equivariant pocket-conditioned generator that is pocket-only (no reference ligand needed) and supports inpainting (fragment growing/linking, scaffold hopping, substructure fixing) via an atom mask.
- `flowr` (FlowR): flow-matching pocket-conditioned small-molecule generator (confirm params live).
- `pocketgen` (PocketGen): (re)generate a protein binding POCKET around a given small molecule.

Protein-protein docking:
- `equidock` (EquiDock): equivariant rigid-body PPI complex prediction without an exhaustive search.
- `geodock` (GeoDock): geometric deep-learning protein-protein docking.
- `colabdock` (ColabDock): integrative PPI docking that can use experimental distance/contact restraints.
- `rosetta-ppi` (Rosetta PPI): Rosetta InterfaceAnalyzer that SCORES an existing protein-protein complex interface (dG_separated binding energy, buried interface SASA, shape complementarity, unsatisfied H-bonds). It does NOT predict the complex structure, so dock or fold the complex upstream first (EquiDock / Boltz-2).
- `rosetta-relax-ligand` (Rosetta Relax with ligand): energy-minimize / relax a protein-ligand complex (refine a docked pose, not generate one).
- `intercaat` (Intercaat): interatomic contact analysis to characterize an existing interface.

Flexible-receptor physics docker (protein-LIGAND, not protein-protein):
- `rosetta-dock` (Rosetta Dock): Rosetta-based protein-LIGAND docking with full-atom side-chain, backbone, and ligand flexibility during refinement; emits docked complex PDB + ligand SDF with an energy breakdown. Slower than Vina/GNINA, so reach for it when receptor conformational adjustment matters; Rosetta-license gated. Do NOT use it for protein-protein docking (use EquiDock / GeoDock / Boltz-2) or for blind site-finding (localize a pocket with AF2BIND / fpocket first).

Pocket / binding-site detection (run before a box docker to find the pocket):
- `fpocket` (fpocket): geometric cavity/pocket detection; enumerate candidate pockets quickly.
- `pykvfinder` (PyKVFinder): grid-and-voxel cavity detection with volume/area characterization (druggability sizing).
- `af2bind` (AF2BIND): predict ligand BINDING SITES on a protein from sequence/structure; feed the predicted site into a Vina box.
- `masif` (MaSIF), `atomsurf` (AtomSurf): molecular-surface-fingerprint learning for interaction-site / binding prediction.

Library screening (shape / pharmacophore, not per-ligand docking):
- `pharmit` (Pharmit): pharmacophore + shape virtual screening against an uploaded SDF or a hosted public DB.
- `roshambo` (Roshambo): GPU 3D shape/color similarity screening of a query molecule against a dataset.
- `virtudockdl` (VirtuDockDL): end-to-end DL virtual-screening pipeline (GNN ligand prioritization, OpenMM refinement, AutoDock Vina docking) in one shot.
