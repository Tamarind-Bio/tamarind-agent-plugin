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

## What the protocol names — and what the catalog carried when this was written

The protocol's structure-design roster is RFdiffusion*, RFdiffusion3*,
FreeBindCraft*, BoltzGen*, PXDesign*, Proteina-Complexa*, Genie3* (starred, and
owing the floor), plus Mosaic, FoldCraft, BoltzDesign1, HalluDesign and Protein
Hunter. **All seven starred methods were present.** Two unstarred ones were not — re-check both against `getAvailableTools` before recording either as dropped:

- **FoldCraft** — the protocol names it specifically as the way to design binders
  "that include beta-sheets and mixed alpha-beta folds, not only all-alpha helical
  bundles, by supplying small beta-containing reference folds". Its absence bears
  directly on the 10% non-all-alpha objective, so record the drop with **that**
  consequence, not as a generic missing tool.
- **HalluDesign** — hallucinates through Protenix v2, Chai-1 or Boltz. `mosaic-hallucinate`
  occupies the same niche here (gradient-based, through Boltz-2/Protenix/AlphaFold/
  OpenDDE) but is a different tool; name it as a substitute rather than reporting
  HalluDesign as run.

The catalog also carries generators the protocol does not name — BindCraft itself,
BoltzProt-1, RSO, DISCO, EvoPro, AnewOmni, Promera. The protocol permits adding any
open-source tool with a usable license **once a production run has taken it end to
end on a real target**; an unrun tool is not roster material. Added arms do not owe
the 50-backbone floor, which belongs to the starred set.

## Defaults you must override, per method

**Every starred method needs settings set explicitly, and at least four of them produce something that is not a miniprotein binder campaign if you accept their defaults.** These are not tuning knobs — at defaults the method silently does the wrong job, and the canary in §2 still returns PASS because *something* ran. Resolve each against `getJobSchema` before submitting; this is a grounded snapshot, not the authority.

| method | setting | default | why you must set it |
|---|---|---|---|
| `rfdiffusion` | `task` | **`Motif Scaffolding`** | **Not binder design.** All of `targetChains`, `binderLength`, `binderHotspots` are scoped to `Binder Design` and are ignored otherwise. Set `task: "Binder Design"`. |
| | `binderLength` | required | A **string** range (`"60-80"`), not a number. |
| `rfdiffusion3` | `task` | `protein-binder-design` | **Correct by default here — but a different task vocabulary from `rfdiffusion`'s, and that is the trap.** Omitting it autofills the right task; *copying `rfdiffusion`'s* `task: "Binder Design"` is REFUSED. The options are `protein-binder-design`, `enzyme-design`, `na-binder-design`, `small-molecule-binder-design`, `json`. Keeping the two method tokens distinct is not enough; the TASK tokens are distinct too. |
| | `binderLength` | `"100,150"` | **COMMA-separated here, and the key name is the same as `rfdiffusion`'s, which is DASH-separated.** Declared `type: "range"`; the schema's own default and `exampleJob` are both `"100,150"`. Both `"60-80"` and `"60,80"` return `valid: true` and are stored VERBATIM, so validation cannot tell you which one the worker parses — see the note under the aiming table. The default also sits inside the mimic band. |
| | `numDesigns` | returns MORE than you ask | Measured: `numDesigns: 4` came back as **8** model rows. The mechanism is `diffusionBatchSize` (default **8**), whose own description says *"Extra designs may be generated if the leaf count does not divide evenly"* — so the request is rounded UP to a multiple of the batch. This is the one entry that overshoots rather than undershoots: count the rows in the result table, never assume the request. |
| | `diffusionBatchSize` | **8** | **Designs in one GPU pass SHARE the sampled binder length** (the schema says so). At the default, a 50-design round samples ~7 lengths, not 50 — a length-diversity collapse that no output column reports. Lower it when length diversity is part of the panel. |
| `boltzgen` | `binderType` | **`de-novo-nanobody`** | **The default designs a nanobody** — the modality §0 puts out of scope. Set `binderType: "protein"`. |
| | `budget` | **2** | Caps designs *returned* regardless of `numDesigns`. Left alone, a request for 50 backbones yields **2**, and the per-method floor silently goes undischarged. |
| | `lengthRange` | protein `"100,150"` | Exists **only** on the `protein`/`peptide` tasks — so length is unsettable until `binderType` is right. The default also sits inside the mimic band. |
| | `filterBindingSite` | **false** | Supplying `bindingSite` does **not** filter on it; the conditioning is soft and the schema says so. |
| `pxdesign` | `pxdesignMode` | **`generation`** | Raw backbones, **no ranked table and no output contract at all**. Only `extended` writes `summary.csv`. |
| | `binderLength` | **10** | Below this campaign's own 35-residue floor; every row would be refused by the gate. |
| `mosaic-hallucinate` | `binderLength` | **220** | Above the 160 ceiling. A plain NUMBER, like `pxdesign`'s — not a range. |
| | `numDesigns` | **1** | Same silent-single-run trap. |
| `freebindcraft` | **`hotspotResidues`** | **optional — auto-selects** | **The one that breaks the campaign silently.** Its description reads *"If left empty suitable hotspots will be selected automatically."* Omit it and the tool picks its **own** epitope: no error, a normal-looking run, and a method aimed somewhere else. One frozen epitope across every method is this campaign's central invariant, and this is the only roster entry that answers a missing epitope by choosing **another one**. Six more violate the invariant just as silently by dropping the constraint and designing unaimed — see the adherence section below — but their designs at least are not aimed somewhere you did not pick. Audit it afterwards on the `Target_Hotspot` output column, documented as *"empty if auto-selected"* — an empty value there means the epitope was not yours. |
| | `numDesigns` | **1** | It generates until this many designs *pass its filters*, and stops early on its runtime cap — so a run can end partial and silently short. |
| | `maxRunTime` | 16 h (free: 4 h) | The cap that makes a run end partial. |
| `genie3` | `foldNumModels` | 5 | Rows are per predicted **model**, and `rank` is the AF2 model rank, not a design ordinal — there is no design identifier at all. See [pool_schema.md](pool_schema.md). |
| | `minBinderLength` / `maxBinderLength` | 80 / 120 | **Two separate required numbers, not a range string** — the only roster entry that splits length across two keys. A `binderLength` borrowed from a neighbour lands in `unrecognized_settings` and fails the job. |
| `proteina-complexa` | `numDesigns` | **1** | "Number of independent Proteina-Complexa jobs to launch." Like FreeBindCraft's, a request for 50 backbones yields **one** run unless you set it, and the per-method floor silently goes undischarged. |
| | `binderLengthRange` | protein-binder `"70,150"` | The upper end is above this campaign's 120 band, and for a mid-size target it reaches into the mimic band. |
| `boltzdesign` | `numDesigns` | **1** | Same silent-single-run trap. |
| | `inputFormat` | required — no default | `"pdb"` is what makes `pdbFile`/`targetChains` the active inputs; `"sequence"` and `"small_molecule"` are the other enums. |
| | `binderLengthRange` | **`"100,150"`** | Comma range. Above this campaign's band at both ends. |
| `protein-hunter` | `numDesigns` | **1** | Same silent-single-run trap. |
| | `lengthRange` | **`"90,150"`** | Comma range, and a THIRD spelling of "binder length" (`binderLength` / `binderLengthRange` / `lengthRange` / `min`+`max` are all in use across this roster). |
| | `numCycles` | **7** | Per-design optimization depth — it multiplies GPU time per design, so it is the cost knob to check before scaling `numDesigns`. |

## Aiming at the frozen epitope — the key per method

Five spellings and four value grammars. Submission validates against that type's own schema and rejects the whole job on the first unrecognized key, so a spelling borrowed from a neighbour costs the entire round.

**Three keys move together and all three differ per method: the target file, the chain list, and the aiming field.** A campaign that gets the aiming field right and the file field wrong loses the round exactly as completely.

| method | target file | chain field | aiming field | required? | value shape | binder length |
|---|---|---|---|---|---|---|
| `rfdiffusion` | `pdbFile` | `targetChains` | `binderHotspots` | optional | `{"A": "20 21 23"}` — space | `binderLength` — STRING range `"60-80"` |
| `rfdiffusion3` | `pdbFile` | `targetChains` | `hotspots` | optional | `{"A": "185 213 216 217 247 248"}` — space | `binderLength` — COMMA range `"60,80"` (same key name as `rfdiffusion`, opposite separator) |
| `freebindcraft` | `pdbFile` | `chains` | `hotspotResidues` | **optional — AUTO-SELECTS** | `{"A": "1-10"}` — dash range; discrete residues go in as `"185-185,213-213,216-217"` | `binderLengthRange` — `"60,80"` |
| `boltzgen` | `targetFile` | `targetChains` | `bindingSite` / `notBindingSite` | optional | `{"A": "185,213,216,217,247,248"}` — comma | `lengthRange` — `"60,80"` |
| `pxdesign` | `targetFile` | `targetChains` | `hotspots` | optional | `{"A": "12-33"}` — dash range | `binderLength` — a NUMBER, not a range |
| `proteina-complexa` | `pdbFile` | `targetChains` | `hotspotResidues` | optional | `{"A": "37,39,49,98"}` — comma | `binderLengthRange` — `"60,80"` |
| `genie3` | `targetFile` | `targetChains` | `hotspots` | **REQUIRED** | `{"A": "261 263 264"}` — space | `minBinderLength` **and** `maxBinderLength` — two separate numbers |
| `boltzdesign` | `pdbFile` (needs `inputFormat: "pdb"`) | `targetChains` (+ `constraintChain` scopes the picker) | `constraintResidues` | optional — set both or neither | comma-separated, on the ONE `constraintChain` — **not** a `{chain: …}` map like every other entry | `binderLengthRange` — `"100,150"` |
| `mosaic-hallucinate` | **none** — `targetSequence` only | — | — | — | cannot be aimed | `binderLength` — a NUMBER (220), not a range |
| `protein-hunter` | **none** — `targetSequence`/`targetCCD` | — | — | — | cannot be aimed | `lengthRange` — `"90,150"` |

Every cell above was resolved on 2026-08-25 against the live catalog: the aiming keys by submitting to prod and reading back `valid: true` against a two-chain target with a six-residue epitope, and the length keys and their defaults from each tool's own schema.

**`valid: true` is evidence the key is ACCEPTED. It is not evidence the VALUE is well-formed, and it is not evidence the method aimed where you asked.** Three separate limits, and the middle one bit this page:

- A range value is stored **verbatim**. `rfdiffusion3` takes `binderLength: "60-80"` and `binderLength: "60,80"` with equal cheer and normalizes neither, so the separator is settled by the WORKER, not the validator. An earlier version of this table recorded the dash for `rfdiffusion3` on exactly that evidence and was wrong: the schema declares `type: "range"` with `"100,150"` as both its default and its `exampleJob`. **For any `type: "range"` field, take the separator from the schema's own default — never from a validation that passed.** `rfdiffusion` really is dash (`"20-30"` is its declared example); `rfdiffusion3`, `boltzgen`, `freebindcraft`, `proteina-complexa`, `boltzdesign` and `protein-hunter` are all comma.
- A key can be accepted and then ignored — see the adherence section below, which is a different question with a different answer per method.
- A missing key can be *filled in for you*: `freebindcraft` picks its own epitope, and `rfdiffusion3`'s task autofills correctly. Absence of an error says nothing about which of those two happened.

**Four of the seven starred methods take a key this table did not previously carry**, which is four failed submissions for a campaign that reads only the aiming column: `pxdesign` and `boltzgen` want `targetFile` where `rfdiffusion` wants `pdbFile`, `genie3` splits its length into two numbers, and `rfdiffusion3` needs a `task` the other diffusion entry spells differently (see the defaults table above).

Three carried **no example in the schema** — `rfdiffusion3`, `boltzgen`, and FreeBindCraft's discrete-residue form. The shapes in the table for those three are measured from accepted submissions, not read off the schema, so re-probe them rather than trusting this page if a round fails.

**Probe what is actually enforced with `validateJob`, which costs nothing — but read the `error`, not just `missing_fields`.** Calling it with empty settings names what the tool refuses to run without:

```
validateJob(jobName="probe", type="genie3", settings={})
  -> valid: false, missing_fields: [targetFile, targetChains, hotspots]

validateJob(jobName="probe", type="rfdiffusion", settings={})
  -> valid: false, missing_fields: []      <- EMPTY
     error: 'Missing required rfdiffusion field "pdbFile"'

validateJob(jobName="probe", type="boltzgen", settings={})
  -> valid: false, missing_fields: []      <- EMPTY
     error: 'Missing required boltzgen field "targetFile"'
```

**`missing_fields` is populated for some tools and empty for others, and it is empty on the two most complicated ones.** Measured on prod: genie3 and freebindcraft list their fields; rfdiffusion and boltzgen return `[]` and name only the FIRST missing field, in the `error` string. boltzgen has 25 task-gated required parameters and rfdiffusion's requirements shift across its 8 tasks, so an empty `missing_fields` means *this surface did not answer*, never *this tool needs one field*. The TYPED source for field names is the schema: `getJobSchema(<type>).parameters` carries a `required` flag on each one. It over-reports rather than under-reports — boltzgen marks 25 required, gated by task — so read it for the NAMES and let the probe tell you which of them your task actually enforces. Treat the probe as best-effort confirmation: fix the field the `error` names, call it again, and keep going until it validates. **The error string's wording is not a contract** — match the field name it quotes, never the sentence around it, and if the text stops naming a field, fall back to the schema and say the probe stopped answering rather than guessing a payload.

That is how the `targetFile`/`pdbFile` difference above was found — a plausible-looking `pdbFile` came back under `unrecognized_settings`, which fails the whole job. Validate one payload per method before committing a round to it, and treat a `mutatedFields` warning as a failure: it means the validator silently altered your input.

**Seven of the eight aimable methods accept no epitope without complaint.** Only `genie3` refuses — measured: omitting `hotspots` returns `valid: false` ("At least one residue is required"), while omitting `freebindcraft`'s `hotspotResidues` returns **`valid: true`** and runs. Forgetting the epitope is therefore a silent event on almost every method, and it fails in two different ways:

- **FreeBindCraft substitutes its own epitope** — it selects hotspots automatically and designs against a site you did not choose. Its designs then look like ordinary members of the pool aimed somewhere else.
- **The other six drop the constraint entirely** — the binder lands wherever the model prefers. Proteina-Complexa says so outright: "will design without specified hotspots."

Neither errors, and the difference matters: the first is a *wrong* epitope, the second is *no* epitope.

**Setting the key is not the same as hitting the site — measured.** Two methods given the *identical* frozen six-residue epitope on the same target, in the same campaign:

| method | what it was given | what it delivered |
|---|---|---|
| `genie3` | `hotspots` (required) | `target_hotspot_coverage` = **1.0** on both designs — all 6 residues engaged |
| `boltzgen` | `bindingSite` **plus `filterBindingSite: true`** | `bindsite_under_5rmsd` = **0.0** on 3 of 4 designs (0.167 on the fourth) |

Same epitope, same target, opposite outcomes — and boltzgen had its post-filter switched on, which is the stricter setting. So the aim is genuinely a bias on some methods and a constraint on others, and **which one you got is only visible in the output.** Do not report a method as aimed at the frozen site because you set its key. Report the adherence number, per method, and treat a method that cannot reach the site as a diversity arm with that fact disclosed — not as a failure, and not silently as an aimed arm.

**Audit adherence from the output, not from what you submitted.** Two methods hand you the check for free — `genie3` emits `target_hotspot_coverage` ("fraction of user-specified target hotspot residues the designed binder engages") and `boltzgen` emits `bindsite_under_*rmsd`. FreeBindCraft's `Target_Hotspot` is documented "empty if auto-selected", so a blank cell there means the epitope was not yours. For the rest, compute interface contacts against the frozen site yourself.

**Setting `bindingSite` on `boltzgen` is necessary but not sufficient.** Its own `filterBindingSite` description states that "the soft bindingSite conditioning alone does not guarantee adherence" — so set `filterBindingSite: true` (default `false`) or accept that the aim is a bias rather than a constraint, and say which.

"Every method got the same epitope" is a claim about what came back, not about what you sent.

**None of these defaults produce an error.** Measured: a `boltzgen` submission carrying only a target file and `targetChains` returns `valid: true`, and its normalized settings come back `binderType: "de-novo-nanobody"`, `numDesigns: 10`, `budget: 2`, `filterBindingSite: false`. A clean validation is not evidence that you submitted the campaign you meant to. **Read the `normalized` block that `validateJob` returns and check it against your frozen plan** — it is the only place the platform tells you what it actually decided to run.

**No method opens the campaign by default.** The protocol names them as peers and requires backbones from each, so a preferred first method is a finger on the scale of the very comparison the campaign exists to make. A method whose outputs will not parse is a gap to disclose and fix, never a reason to substitute a different method for it.

**Per-method floor: at least 50 backbones into the scored pool from every starred method not proved UNAVAILABLE.** NOT_PROBED still owes them — the way to discharge that is to run the canary, not to assume the method is dead. Beyond the floor, reallocate toward whichever methods perform best on this target and epitope, while staying under the selection caps.

## Sequence routing — which methods need a sequence-design pass

Getting this wrong costs designs in both directions.

- **Sequence-carrying** — `boltzgen`, `rfdiffusion`, `rfdiffusion3`, `genie3`, `mosaic-hallucinate`, `freebindcraft`. Their per-design table already contains the binder sequence, so they feed a scoring pool directly. **Do not route them through a sequence-design job.** The unnecessary hop mints a second, job-local id space over the same backbones, which is how a shipped design ends up carrying another backbone's sequence. Run a redesign only when you deliberately want the co-design comparison, and then record it as a new design row that keeps the original `root_backbone_id`.
- **Backbone-only** — `proteina-complexa`, `pxdesign`. Their per-design table drops every upstream sequence column, so there is nothing to score. Submit a sequence-design job on the generator's output structures, then build the pool from **that** job. `root_backbone_id` and `structure_method` still name the original generator; `seq_method` names the sequence designer. Skipping this is how a method contributes zero ranked backbones.
**`proteina-complexa` publishes per-design `ss_alpha`/`ss_beta` fractions** — the only roster entry that does. `ss_alpha < 0.70` settles non-all-alpha on its own; a helix-rich row still needs residue-level `ss_codes`, since an aggregate fraction cannot show the run of three consecutive strand residues the other half of the definition asks for.

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
