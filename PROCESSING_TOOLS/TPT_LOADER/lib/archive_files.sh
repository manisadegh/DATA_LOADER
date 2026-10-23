#!/bin/bash
# ---------------------------------------------------------------------------
# Archive loaded files (optional)
# ---------------------------------------------------------------------------
if [ -n "${ARCHIVE_DIR}" ]; then
    mkdir -p "${ARCHIVE_DIR}" || die 1 "Cannot create archive dir ${ARCHIVE_DIR}"
    for f in "${FILES[@]}"; do
        mv "${f}" "${ARCHIVE_DIR}/" || die 1 "Cannot archive ${f}"
    done
    log INFO "Archived ${#FILES[@]} file(s) to ${ARCHIVE_DIR}"
fi
