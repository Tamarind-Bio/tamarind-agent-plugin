# Generation roster, sequence routing, and length policy

> Tool names, settings keys and defaults change. This is a grounded snapshot, not an authority. Resolve every entry with `getAvailableTools` and `getJobSchema` before you submit, and drop what the live catalog does not carry rather than substituting a neighbour.

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

## Defaults you must override, per method

**Every starred method needs settings set explicitly, and at least four of them produce something that is not a miniprotein binder campaign if you accept their defaults.** These are not tuning knobs — at defaults the method silently does the wrong job, and the canary in §2 still returns PASS because *something* ran. Resolve each against `getJobSchema` before submitting; this is a grounded snapshot, not the authority.

| method | setting | default | why you must set it |
|---|---|---|---|
| `rfdiffusion` | `task` | **`Motif Scaffolding`** | **Not binder design.** All of `targetChains`, `binderLength`, `binderHotspots` are scoped to `Binder Design` and are ignored otherwise. Set `task: "Binder Design"`. |
| | `binderLength` | required | A **string** range (`"60-80"`), not a number. |
| `boltzgen` | `binderType` | **`de-novo-nanobody`** | **The default designs a nanobody** — the modality §0 puts out of scope. Set `binderType: "protein"`. |
| | `budget` | **2** | Caps designs *returned* regardless of `numDesigns`. Left alone, a request for 50 backbones yields **2**, and the per-method floor silently goes undischarged. |
| | `lengthRange` | protein `"100,150"` | Exists **only** on the `protein`/`peptide` tasks — so length is unsettable until `binderType` is right. The default also sits inside the mimic band. |
| | `filterBindingSite` | **false** | Supplying `bindingSite` does **not** filter on it; the conditioning is soft and the schema says so. |
| `pxdesign` | `pxdesignMode` | **`generation`** | Raw backbones, **no ranked table and no output contract at all**. Only `extended` writes `summary.csv`. |
| | `binderLength` | **10** | Below this campaign's own 35-residue floor; every row would be refused by the gate. |
| `mosaic-hallucinate` | `binderLength` | **220** | Above the 160 ceiling. |
| `freebindcraft` | **`hotspotResidues`** | **optional — auto-selects** | **The one that breaks the campaign silently.** Its description reads *"If left empty suitable hotspots will be selected automatically."* Omit it and the tool picks its **own** epitope: no error, a normal-looking run, and a method aimed somewhere else. One frozen epitope across every method is this campaign's central invariant, and this is the only roster entry that can violate it without failing. Audit it afterwards on the `Target_Hotspot` output column, documented as *"empty if auto-selected"* — an empty value there means the epitope was not yours. |
| | `numDesigns` | **1** | It generates until this many designs *pass its filters*, and stops early on its runtime cap — so a run can end partial and silently short. |
| | `maxRunTime` | 16 h (free: 4 h) | The cap that makes a run end partial. |
| `genie3` | `foldNumModels` | 5 | Rows are per predicted **model**, and `rank` is the AF2 model rank, not a design ordinal — there is no design identifier at all. See [pool_schema.md](pool_schema.md). |

## Aiming at the frozen epitope — the key per method

Five spellings and four value grammars. Submission validates against that type's own schema and rejects the whole job on the first unrecognized key, so a spelling borrowed from a neighbour costs the entire round.

| method | aiming field(s) | value shape |
|---|---|---|
| `rfdiffusion` | `targetChains` + `binderHotspots` | `{"A": "20 21 23"}` — space |
| `rfdiffusion3` | `targetChains` + `hotspots` | no example in schema |
| `freebindcraft` | `chains` + `hotspotResidues` — **OPTIONAL, auto-selects** | `{"A": "1-10"}` — dash range |
| `boltzgen` | `targetChains` + `bindingSite` / `notBindingSite` | no example in schema |
| `pxdesign` | `targetChains` + `hotspots` | `{"A": "12-33"}` — dash range |
| `proteina-complexa` | `targetChains` + `hotspotResidues` | `{"A": "37,39,49,98"}` — comma |
| `genie3` | `targetChains` + `hotspots` (**required**) | `{"A": "261 263 264"}` — space |
| `boltzdesign` | `constraintChain` + `constraintResidues` | comma-separated |
| `mosaic-hallucinate` | **none** — sequence-conditioned | diversity arm |
| `protein-hunter` | **none** — sequence-conditioned | diversity arm |

Three of these carry **no example** in the schema, so the value shape cannot be read off it. Validate a single job before committing a round to that method.

**Check whether the aiming field is REQUIRED, and treat an optional one as the hazard it is.** A required field fails loudly when you forget it. An optional one does not — the job runs, and the method aims wherever it likes. `freebindcraft` is confirmed to work this way. Before you submit a method's first production round, confirm from its schema that the aiming field is required, or that you have supplied it; then confirm from the run's own output that the site it used is the site you froze. "Every method got the same epitope" is a claim about what came back, not about what you sent.

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

Every method that can be aimed is aimed at the one frozen site. The setting key and value shape differ per method and are **not** interchangeable: submission validates the settings object against that type's own schema and rejects the whole job on the first unrecognized key, so a spelling borrowed from a neighbouring method costs the entire design round. Read each method's schema with `getJobSchema` and take the key and value shape from there — do not carry one over from another tool, and do not guess a plural.

Sequence-conditioned methods take the target's amino-acid sequence with no structure file and no epitope field under any spelling. They are **diversity arms**, which is a real role: keep them, name them as unaimed in the report so a reader does not read their misses as poor performance, and compute their designs' interface contacts against the frozen site downstream instead of assuming engagement.

## Fold diversity

At least **10% non-all-alpha** designs on the shipped sheet, where a design is not-all-alpha if it has at least one beta strand of three or more consecutive strand residues, or its helical fraction is below 70%. This is a **reported target, not a ranking gate**: if the ranked pool cannot supply it without displacing materially better designs, ship fewer and state the count and the reason. Buy it at generation time where the generator supports it, not by filtering at the end.
