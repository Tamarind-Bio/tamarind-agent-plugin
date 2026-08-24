# Generation roster, sequence routing, and length policy

> Tool names, settings keys and defaults change. This is a grounded snapshot, not an authority. Resolve every entry with `tamarind --json tools` and `tamarind --json schema TOOL` before you submit, and drop what the live catalog does not carry rather than substituting a neighbour.

## The roster

The lowercase token is the job `type`; the name in parentheses is the only spelling you use with the user.

| Token | Name | Role |
|---|---|---|
| `rfdiffusion` | RFdiffusion | starred — owes the per-method floor |
| `rfdiffusion3` | RFdiffusion3 | starred |
| `freebindcraft` | FreeBindCraft | starred |
| `boltzgen` | BoltzGen (binder type "protein") | starred |
| `pxdesign` | PXDesign | starred |
| `proteina-complexa` | Proteina-Complexa | starred |
| `genie3` | Genie 3 | starred |
| `mosaic-hallucinate` | Mosaic Hallucination | optional |
| `boltzdesign` | BoltzDesign1 | optional |
| `protein-hunter` | Protein Hunter | optional |

**No method opens the campaign by default.** The protocol names them as peers and requires backbones from each, so a preferred first method is a finger on the scale of the very comparison the campaign exists to make. A method whose outputs will not parse is a gap to disclose and fix, never a reason to substitute a different method for it.

**Per-method floor: at least 50 backbones into the scored pool from every starred method not proved UNAVAILABLE.** NOT_PROBED still owes them — the way to discharge that is to run the canary, not to assume the method is dead. Beyond the floor, reallocate toward whichever methods perform best on this target and epitope, while staying under the selection caps.

## Sequence routing — which methods need a sequence-design pass

Getting this wrong costs designs in both directions.

- **Sequence-carrying** — `boltzgen`, `rfdiffusion`, `rfdiffusion3`, `genie3`, `mosaic-hallucinate`, `freebindcraft`. Their per-design table already contains the binder sequence, so they feed a scoring pool directly. **Do not route them through a sequence-design job.** The unnecessary hop mints a second, job-local id space over the same backbones, which is how a shipped design ends up carrying another backbone's sequence. Run a redesign only when you deliberately want the co-design comparison, and then record it as a new design row that keeps the original `root_backbone_id`.
- **Backbone-only** — `proteina-complexa`, `pxdesign`. Their per-design table drops every upstream sequence column, so there is nothing to score. Submit a sequence-design job on the generator's output structures, then build the pool from **that** job. `root_backbone_id` and `structure_method` still name the original generator; `seq_method` names the sequence designer. Skipping this is how a method contributes zero ranked backbones.
- **Undetermined** — `boltzdesign`, `protein-hunter`. Read the method's own per-design table on its canary and check for a sequence column. Treat it as backbone-only only when the table genuinely has none, and record which way you resolved it.

The same two-step route applies to any method you deliberately run **without** its in-job sequence step.

Use the base sequence-design model for backbone search; use the **soluble variant** when generating or selecting the designs that will be ordered. On this platform the soluble variant is a model option on the sequence-design tool's existing type, not a type of its own — read the schema's model enum rather than looking for a separate tool. For co-design models, score both the native sequence and a redesign.

## Length policy

- **50–120 residues**, 35–160 permitted where epitope geometry motivates it, with the rationale recorded in the sheet's target metadata. Nothing else computes a length range for you.
- **Stay more than 25% away from every target chain's length.** For a 115-residue target chain that means avoiding 87–143 aa and designing at or below 86 aa. Read the chain length off the frozen construct; do not guess it from the structure title.
- Shorter is the free direction. Go longer than the target only when the target is small enough that nothing fits underneath the band, and record that choice with its reason.
- **Set the length setting explicitly on every submit.** Several tool defaults sit inside the mimic band for a mid-size target, so inheriting a default is how a mimic arrives without anyone choosing one.

## Aiming at the frozen epitope

Every method that can be aimed is aimed at the one frozen site. The setting key and value shape differ per method and are **not** interchangeable: submission validates the settings object against that type's own schema and rejects the whole job on the first unrecognized key, so a spelling borrowed from a neighbouring method costs the entire design round. Read each method's schema with `tamarind --json schema TOOL` and take the key and value shape from there — do not carry one over from another tool, and do not guess a plural.

Sequence-conditioned methods take the target's amino-acid sequence with no structure file and no epitope field under any spelling. They are **diversity arms**, which is a real role: keep them, name them as unaimed in the report so a reader does not read their misses as poor performance, and compute their designs' interface contacts against the frozen site downstream instead of assuming engagement.

## Fold diversity

At least **10% non-all-alpha** designs on the shipped sheet, where a design is not-all-alpha if it has at least one beta strand of three or more consecutive strand residues, or its helical fraction is below 70%. This is a **reported target, not a ranking gate**: if the ranked pool cannot supply it without displacing materially better designs, ship fewer and state the count and the reason. Buy it at generation time where the generator supports it, not by filtering at the end.
