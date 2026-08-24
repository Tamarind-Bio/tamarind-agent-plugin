# Molecular dynamics + free energy

> Operational examples in this reference use the Tamarind CLI. Query the live catalog and schema before relying on this grounded snapshot.

Simulate how a biomolecule moves (MD) and compute how tightly a ligand binds (free energy). Spans classical all-atom MD, membrane MD, enhanced sampling, generative MD surrogates, and the alchemical / endpoint free-energy methods (RBFE, MM/GBSA, MM/PBSA) used to rank ligand affinities.

Discover live, then read the schema:

```bash
tamarind --json tools --function molecular-dynamics
tamarind --json tools --function binding-affinity
tamarind --json schema openmm
```

Pick by outcome:
- A solvated protein or protein-ligand trajectory + analysis plots: `gromacs` (Amber99 family, full plot set, parallel replicas) or `openmm` (ff19SB/ff14SB, explicit ligand charge, 2D-RMSD). Engine/force-field preference.
- Membrane protein in a lipid bilayer: `membrane-gromacs` (CHARMM36, CG-to-atomistic embed).
- A binding free energy (not a trajectory): `openfe` / `rbfe` (alchemical RBFE, rigorous) or `gbsa` / `g-mmpbsa` (endpoint, cheaper, approximate).
- Quick structure cleanup: `openmm-relax`. Enhanced sampling: `openmm-temperature-replica` (REMD), `openmm-metadynamics` (CV-biased), or `af2rave` (reduced-MSA AF2 + AI-augmented MD for Boltzmann-ranked metastable states). A fast ensemble surrogate WITHOUT real MD: `bioemu` / `mdgen`.

File params (`pdbFile`, `proteinFile`, `ligandFile`, `proteinPDB`, `ligandsSDF`) take a bare filename uploaded first. `tamarind --json validate` checks file existence, so an unuploaded filename can return `valid:false` while the rest of the settings resolved correctly.

## Anchor tools

### gromacs (GROMACS): classical MD
- `systemType` (`protein` / `protein-ligand`). For `protein`: `uploadType` (`upload` -> `pdbFile`, or `fetch` -> `pdbID`, no upload). For `protein-ligand`: `proteinFile` (.pdb) + `ligandFile` (.sdf) (note the protein param name differs between modes). `forceField` (`amber99sb` / `-ildn` / `amber14sb`); box/water/salt/temp knobs; `simulationTime` (ns); `numReplicas` (1-5).
- Outputs: trajectory + final-frame PDB + analysis plots (RMSD, RMSF, Rg, per-phase energies). The `fetch` path needs no uploaded file.
- Only `protein` and `protein-ligand` system types exist; no protein-DNA/RNA system type.

### openmm (OpenMM MD): classical MD on GPU
- `systemType` (`protein` / `protein-ligand`); `pdbFile` (.pdb, **all non-protein atoms are stripped** from this PDB, so pass a ligand separately as `ligandFile` SDF in protein-ligand mode); `ligandCharge` (required, the ligand's total formal charge, -3..3) in protein-ligand mode; `equilibrationTime` / `productionTime` (ns).
- **GOTCHA (submit-blocker): several numeric-looking params are STRING-typed in the schema**: `minimizationSteps` (`"10000"`), `timestep` (`"2"`/`"4"`), `temperature` (`"298"`), `pressure` (`"1"`), `equilTrajFreq`, `prodTrajFreq`. Pass them as quoted strings, NOT bare numbers, or the submit is rejected. `tamarind --json validate openmm --input FILE --name JOB_NAME` catches this.
- Runtime / cost scales roughly with atom count times total ns; large systems or long `productionTime` are the cost drivers. Surface those before submitting.

### openfe (OpenFE) and rbfe (Relative Binding Free Energy)
Relative binding free energies across a ligand series against one protein (lead-optimization affinity ranking).
- `openfe`: `simulationType` (`rbfe` or `complexMD`); `proteinPDB`; for rbfe: `ligandsSDF` (a single multi-ligand SDF, `no_split_sdf`: do NOT pre-split it), `networkType`, `atomMapper` (`lomap`/`kartograf`), `max3d`, `chargeMethod` (`am1bcc`/`nagl`), `protocolRepeats` (2-5, min 2 for error bars); `equilLength` / `prodLength` (ps).
- `rbfe`: the same surface with `simulationType` hidden and locked to `rbfe` (omits the complexMD-only `ligandFile` / `nvtLength`). Same runner as `openfe` rbfe mode.
- **GOTCHA: RBFE needs CONGENERIC ligands**: a common scaffold so atoms can be mapped between pairs, and the perturbation network must form ONE connected graph across all ligands. For structurally diverse molecules, use endpoint methods (`gbsa` / `g-mmpbsa`) or docking scores instead.
- Long-running and checkpointed; runtime scales with network edges times `protocolRepeats` times `(equilLength + prodLength)`.

### gbsa (MM/GB(PB)SA): endpoint affinity
- A fast, approximate binding-free-energy estimate for a protein-ligand or protein-protein complex (`em`-only or short-`md` modes). Reach for it when a full alchemical RBFE network is too expensive. Tool ID is `gbsa`, not `mmgbsa`.

## Catalog (one-liners)

- `membrane-gromacs`: all-atom MD of a membrane protein embedded in a lipid bilayer (CHARMM36, CG-to-atomistic pipeline, lipid presets). For proteins in a membrane, not plain water.
- `openmm-relax`: fast single-structure relaxation / minimization to remove clashes; not a full equilibration + production run.
- `openmm-temperature-replica`: temperature replica-exchange MD for enhanced sampling across a temperature ladder; for escaping a single basin.
- `openmm-metadynamics`: well-tempered metadynamics to map free-energy landscapes along chosen collective variables.
- `bioemu` (BioEmu): generative model approximating a protein's equilibrium conformational distribution without running MD; a fast ensemble, not a time-ordered trajectory.
- `mdgen` (MDGen): generative MD trajectories for peptides without a full MD engine.
- `af2rave` (AF2Rave): Boltzmann-ranked alternative conformations from reduced-MSA AlphaFold2 PLUS AI-augmented MD (it RUNS MD, ~4h default, not a no-MD surrogate); learns SPIB collective variables, good for kinase DFG-in/out and other metastable-state sampling.
- `g-mmpbsa` (g_mmpbsa): binding free energy (dGbind) from an EXISTING GROMACS trajectory via MM-PBSA decomposition (vs `gbsa`, which runs its own short simulation).
- `tmd` (TMD): a differentiable-MD engine for RBFE with GPU HREX sampling; a newer/alternative RBFE path to OpenFE.
- `orb-models3` (Orb Models 3): ML interatomic-potential protein-ligand interaction-energy score; a fast learned estimate, not physics-based MD.
- `dynamicsplm-finetune` / `dynamicsplm-inference` (DynamicsPLM): a dynamics-aware protein language model you finetune then run inference with (a PLM finetune pair tagged molecular-dynamics, not a simulation). See `tamarind-finetune`.

For execution mechanics, see `tamarind-submit-and-poll`.
