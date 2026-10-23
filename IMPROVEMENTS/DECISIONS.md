# DECISIONS — facts settled during the remediation programme

Record each decision with the date, who settled it, the evidence examined (file names only — never commit the files), and the resulting rule. Items marked **OPEN** block the specification items listed in `IMPROVEMENTS/README.md` section 4.

| ID | Question | Status | Decision | Evidence | Date / owner |
|---|---|---|---|---|---|
| D1 | Field layout of a real BICC `MANIFEST-*.MF` data line (`filename;ucm_doc_id` or `filename;ucm_doc_id;md5`) | **OPEN** | it is `filename;ucm_doc_id;md5` (2nd part is a 32 character hexadecimal) | Example: `file_fscmtopmodelam_useram_userpvo-batch1736238000-20261005_132817.zip;a72f1edd20f156733e7ea3d50fec706f` | 23/10/2026 - Mani Sadegh |
| D2 | Do all parts of a BICC multi-file extract start with a header row? | **OPEN** | We need to assume that all csv files start with a header row | No proof, we do not have big chunked multi-part data extracts | 23/10/2026 - Mani Sadegh |
| D3 | Does the TPT Load operator accept string literals in the `VALUES` list of the `APPLY` INSERT? (Phase 1, F1.2 spike) | **OPEN** | Variant A / Variant B | paste the `tbuild` output summary | |
| D4 | Do all files of one BICC extract share one `-batch<id>-` token? | **OPEN** | Yes, all files of one BICC extract share the same `-batch<id>-` token | From received manifest files | 23/10/2026 - Mani Sadegh |
| D5 | Is a git history rewrite required for the identifier scrub? | **OPEN** | No, leave that for now | security contact's answer | 23/10/2026 - Mani Sadegh |
