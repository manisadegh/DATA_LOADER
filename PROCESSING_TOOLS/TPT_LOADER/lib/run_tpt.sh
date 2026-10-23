#!/bin/bash
# ---------------------------------------------------------------------------
# Run TPT
#   replace : all steps (Truncate_Target -> Cleanup_Previous_Run -> Load_Data)
#   append  : start at Cleanup_Previous_Run (tbuild -s) so the target is kept
# ---------------------------------------------------------------------------
TBUILD_OPTS=( -f "${TPT_SCRIPT}" -v "${JOBVARS}" -j "${JOB_NAME}" )
[ "${LOAD_MODE}" = "append" ] && TBUILD_OPTS+=( -s Cleanup_Previous_Run )

log INFO "Job name    : ${JOB_NAME}"
log INFO "Job vars    : ${JOBVARS}"
log INFO "Running     : ${TBUILD_CMD} ${TBUILD_OPTS[*]}"

${TBUILD_CMD} "${TBUILD_OPTS[@]}" 2>&1 | tee "${RUN_DIR}/tbuild.out"
TPT_RC=${PIPESTATUS[0]}

case "${TPT_RC}" in
    0) log INFO "TPT job completed successfully (rc=0)" ;;
    4) log WARN "TPT job completed with warnings (rc=4) - check: tlogview -j ${JOB_NAME}" ;;
    *) die 3 "TPT job failed (rc=${TPT_RC}) - check: tlogview -j ${JOB_NAME} ; output in ${RUN_DIR}/tbuild.out" ;;
esac
