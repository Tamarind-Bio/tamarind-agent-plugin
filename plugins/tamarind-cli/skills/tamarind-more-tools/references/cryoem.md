# Cryo-EM model building

> Operational examples in this reference use the Tamarind CLI. Query the live catalog and schema before relying on this grounded snapshot.

Build, predict, and improve atomic models from cryo-EM density maps. Discover live, then read the schema:

```bash
tamarind --json tools --modality cryoem
tamarind --json schema modelangelo
```

Pick by goal:
- Build coordinates directly into a map (map-to-model): `modelangelo` (sequence OPTIONAL, handles protein + nucleic acid) or `cryfold` (newer transformer builder, sequence REQUIRED, often faster, protein-focused).
- Predict a structure from sequence STEERED to fit a map (you have a sequence + an aligned starting model): `cryoboltz`.
- Sharpen / denoise a map before building: `locscale`. Reconstruct a continuous distribution of maps from raw particles (heterogeneity): `cryodrgn`.

Every file param (`map`, `densityMapFile`, `alignedModelFile`, `mask`) takes a BARE filename of a file uploaded first; never an email-prefixed S3 path.

## Anchor tools

### modelangelo (Model Angelo): map-to-model building
Automatically build a complete atomic model (protein + nucleic-acid chains) into a density map: a near-finished coordinate file instead of hand-tracing.
- Required: `map` (.mrc, bare filename). Optional: `sequence` (protein, `:` between chains). If you give a sequence it informs chain assignment; if you omit it, the builder still traces and identifies the chain.
- The only builder here categorized for nucleic acid. Best at roughly 3.5 Angstrom or better. Output: a CIF (with a PDB conversion) plus build logs.

### cryfold (CryFold): map-to-model building (sequence required)
Same outcome as `modelangelo` via a newer transformer builder, often faster for the common protein case.
- Required: `map` (.mrc, bare filename) and `sequence` (required here, unlike `modelangelo`). Pick `modelangelo` when you have NO sequence or want the nucleic-acid-proven builder.

### cryoboltz (CryoBoltz): map-guided structure prediction
Predict a structure from sequence while STEERING the prediction to fit a map: a model both physically plausible and density-consistent, useful when the map alone is too low-resolution to trace.
- Required: `sequence`, `densityMapFile` (.mrc/.map), `alignedModelFile` (.cif, a starting structure ALREADY aligned to the density, e.g. an unguided prediction docked in ChimeraX), `resolution` (Angstroms), `threshold` (map iso-threshold). Optional: `numSamples`, `useMSA` (default true; runs an MSA stage first).
- Setup pitfall: the `alignedModelFile` must already be fit to the map. Passing an unaligned prediction defeats the density guidance. If you have no aligned starting model, use `modelangelo` / `cryfold` instead.

## Catalog (one-liners)

- `cryodrgn` (CryoDRGN): reconstructs a CONTINUOUS distribution of 3D maps from a raw particle dataset (from CryoSPARC/RELION) to capture conformational heterogeneity; for per-particle variability when one consensus map is not enough. (Org-restricted for some tenants.)
- `locscale` (LocScale): physics-informed LOCAL sharpening and density modification to improve map interpretability, with a model-free mode and a feature-enhanced mode; run it BEFORE model building. Input is the `map` plus an optional `mask`. (`deepemhancer` is the deep-learning alternative for the same map-postprocessing goal.)

For execution mechanics (upload the map, validate, submit, poll, download), see `tamarind-submit-and-poll`.
