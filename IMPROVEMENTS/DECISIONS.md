# DECISIONS — facts settled during the remediation programme

Record each decision with the date, who settled it, the evidence examined (file names only — never commit the files), and the resulting rule. Items marked **OPEN** block the specification items listed in `IMPROVEMENTS/README.md` section 4.

| ID | Question | Status | Decision | Evidence | Date / owner |
|---|---|---|---|---|---|
| D1 | Field layout of a real BICC `MANIFEST-*.MF` data line (`filename;ucm_doc_id` or `filename;ucm_doc_id;md5`) | **OPEN** | | | |
| D2 | Do all parts of a BICC multi-file extract start with a header row? | **OPEN** | | | |
| D3 | Does the TPT Load operator accept string literals in the `VALUES` list of the `APPLY` INSERT? (Phase 1, F1.2 spike) | **OPEN** | Variant A / Variant B | paste the `tbuild` output summary | |
| D4 | Do all files of one BICC extract share one `-batch<id>-` token? | **OPEN** | | | |
| D5 | Is a git history rewrite required for the identifier scrub? | **OPEN** | | security contact's answer | |
