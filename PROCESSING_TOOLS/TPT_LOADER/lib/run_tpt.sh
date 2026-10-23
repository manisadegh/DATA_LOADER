#!/bin/bash
# ---------------------------------------------------------------------------
# Run TPT
#   replace : all steps (Truncate_Target -> Cleanup_Previous_Run -> Load_Data)
#   append  : start at Cleanup_Previous_Run (tbuild -s) so the target is kept
# ---------------------------------------------------------------------------
TBUILD_OPTS=( -f "${JOB_TPT}" -v "${JOBVARS}" -j "${JOB_NAME}" )
[ "${LOAD_MODE}" = "append" ] && TBUILD_OPTS+=( -s Cleanup_Previous_Run )

log INFO "Job name    : ${JOB_NAME}"
log INFO "Job vars    : ${JOBVARS}"
log INFO "Job script  : ${JOB_TPT}"
log INFO "Running     : ${TBUILD_CMD} ${TBUILD_OPTS[*]}"

${TBUILD_CMD} "${TBUILD_OPTS[@]}" 2>&1 | tee "${RUN_DIR}/tbuild.out"
TPT_RC=${PIPESTATUS[0]}

REJECT_COUNT=0
if [ -f "${RECORD_ERR_FILE}" ]; then
    REJECT_COUNT=$(wc -l < "${RECORD_ERR_FILE}" | tr -d ' ')
fi
log INFO "Rejected rows count : ${REJECT_COUNT} (${RECORD_ERR_FILE})"

case "${TPT_RC}" in
    0) 
        if [ "${REJECT_COUNT}" -gt 0 ]; then
            log WARN "TPT job succeeded (rc=0) but ${REJECT_COUNT} row(s) were rejected into ${RECORD_ERR_FILE}"
        else
            log INFO "TPT job completed successfully (rc=0)"
        fi
        ;;
    4) 
        if [ "${REJECT_COUNT}" -gt 0 ]; then
            log WARN "TPT job completed with warnings (rc=4) and ${REJECT_COUNT} row(s) were rejected into ${RECORD_ERR_FILE} - check: tlogview -j ${JOB_NAME}"
        else
            log WARN "TPT job completed with warnings (rc=4) - check: tlogview -j ${JOB_NAME}"
        fi
        ;;
    *) 
        die 3 "TPT job failed (rc=${TPT_RC}) - check: tlogview -j ${JOB_NAME} ; output in ${RUN_DIR}/tbuild.out"
        ;;
esac
