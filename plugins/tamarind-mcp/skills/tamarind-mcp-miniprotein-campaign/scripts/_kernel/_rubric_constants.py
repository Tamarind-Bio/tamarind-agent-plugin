"""Constants the kernel needs from the campaign's QA rubrics.

Copied verbatim rather than importing a 3,900-line prompt module. Values are
frozen protocol thresholds, not tuning knobs -- change them here only when the
source changes them, and re-vendor rather than editing by hand.
"""

ESMC_LL_TOOL = "esmc-6b:scan"
MONOMER_CHECK_NOT_RUN_CODE = "MONOMER_FOLDABILITY_NOT_RUN"
MONOMER_GATE_STAGE_TOKEN = "s1b_monomer"
MONOMER_PLDDT_FLOOR_THRESHOLD = 0.70
MONOMER_PLDDT_SEED_AGGREGATION = "max"
MONOMER_ROW_MEASUREMENT_TERM = "monomer_plddt"
