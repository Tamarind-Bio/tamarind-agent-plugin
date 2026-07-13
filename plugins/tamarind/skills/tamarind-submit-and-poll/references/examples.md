# Settings examples

These are starting shapes, not schema authority. Run `tamarind --json schema TOOL` and `tamarind --json validate TOOL --input FILE --name NAME` before use.

## Boltz sequence fold

```yaml
inputFormat: sequence
sequence: GYAGYAGYAGYAGYAGYAGYAGYA
numSamples: 1
numRecycles: 3
useMSA: false
```

## ProteinMPNN fixed-backbone design

```yaml
pdbFile: target.pdb
designedChains: [B]
numSequences: 8
temperature: 0.1
omitAAs: C
```

The exact designed-chain/residue fields vary by tool version. Use the live schema.

## Known-pocket docking

```yaml
receptorFile: receptor.pdb
ligand: "CC(=O)Oc1ccccc1C(=O)O"
centerX: 10.0
centerY: 12.0
centerZ: 8.0
sizeX: 20.0
sizeY: 20.0
sizeZ: 20.0
```

Field names above are illustrative; different docking tools use different box and ligand fields.

## Input-file rules

Upload first:

```bash
tamarind --json files upload /absolute/path/target.pdb
```

Use the returned bare filename. A failed validation that says a named file has not been uploaded is a file-availability failure, not proof that the rest of the payload is malformed.
