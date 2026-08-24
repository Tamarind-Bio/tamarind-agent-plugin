# Reading the live CLI catalog

## Filter axes

List current modality and function values:

```bash
tamarind --json modalities
tamarind --json functions
```

- Modality describes the molecule/input family, such as protein, antibody, peptide, small molecule, nucleic acid, enzyme, or cryo-EM.
- Function describes the operation, such as structure prediction, binder design, inverse folding, docking, developability, molecular dynamics, or embeddings.

Filter server-side:

```bash
tamarind --json tools --function structure-prediction
tamarind --json tools --modality antibody --function developability
tamarind --json tools --search mpnn
```

Each tool entry includes a lowercase `name` used by CLI commands, a display name, descriptions when the query is narrow, categories/modalities, and tags/functions.

## Read a schema

```bash
tamarind --json schema TOOL
```

Inspect:

- `required`, `type`, `default`, and `options`;
- `conditionals` and task/mode-specific fields;
- file extensions and list/object subfields;
- bounds, version gates, feature flags, and surface exclusions;
- `exampleJob` as a starting shape, not guaranteed-valid input.

Adapt the example to real user inputs and validate it:

```bash
tamarind --json validate TOOL --input settings.yaml --name discovery-probe
```

Submit the original settings, never the validator's normalized echo.

## Availability

The catalog is account-scoped. Recommend only tools returned for the active authenticated profile. A pre-release-looking variant can still be gated despite appearing to a privileged account; prefer a stable public equivalent when access is uncertain.

## Routing map

- Structure prediction: `tamarind-structure-prediction`
- Antibody/nanobody/TCR: `tamarind-antibody`
- De novo binders: `tamarind-binder-design`
- Fixed-backbone design/PLMs: `tamarind-inverse-folding`
- Docking and affinity: `tamarind-docking`
- Developability: `tamarind-developability`
- Fine-tuning: `tamarind-finetune`
- Other scientific domains: `tamarind-more-tools`

Use `tamarind-submit-and-poll` after selection, `tamarind-batch` for many independent inputs, and `tamarind-pipeline` for dependent stages.
