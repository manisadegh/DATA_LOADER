#!/bin/bash
# ---------------------------------------------------------------------------
# Generate TPT Job Script with explicit payload schema and APPLY statement
# ---------------------------------------------------------------------------
TEMPLATE="${LIB_DIR}/load_csv_generic.tpt.template"
JOB_TPT="${RUN_DIR}/job.tpt"
[ -f "${TEMPLATE}" ] || die 1 "TPT template not found: ${TEMPLATE}"
[ -s "${RUN_DIR}/columns.txt" ] || die 1 "No column metadata found in ${RUN_DIR}/columns.txt"

SCHEMA_LINES=""
INSERT_COLS=""
INSERT_VALS=""
while IFS='|' read -r c_name c_type c_len c_chartype c_digits c_frac; do
    [ -z "${c_name}" ] && continue
    case "${c_type}" in
        CV|CF) chars=$(( c_chartype == 2 ? c_len / 2 : c_len )); width=$(( chars * 3 )) ;;
        DA)    width=10 ;;
        TS)    width=32 ;;
        SZ)    width=40 ;;
        AT|TZ) width=20 ;;
        I|I1|I2|I8) width=21 ;;
        D|N)   width=$(( c_digits + 3 )) ;;
        F)     width=40 ;;
        *)     die 1 "Unsupported column type '${c_type}' on column '${c_name}' in ${FQ_TABLE}; add a rule to generate_tpt_job.sh" ;;
    esac
    SCHEMA_LINES+="        \"${c_name}\" VARCHAR(${width}),"$'\n'
    INSERT_COLS+="\"${c_name}\", "
    INSERT_VALS+=":\"${c_name}\", "
done < "${RUN_DIR}/columns.txt"

SCHEMA_LINES="${SCHEMA_LINES%,$'\n'}"
INSERT_COLS="${INSERT_COLS%, }"
INSERT_VALS="${INSERT_VALS%, }"
PAYLOAD_COL_COUNT=$(wc -l < "${RUN_DIR}/columns.txt" | tr -d ' ')

# Validate the literals before they are placed inside the TPT script (F1.2 Variant A)
if [ "${HAS_META}" -eq 2 ]; then
    [[ "${BATCH_ID}" =~ ^[A-Za-z0-9_-]{1,100}$ ]] || die 1 "BATCH_ID '${BATCH_ID}' contains characters not allowed in INFA_BATCH_ID"
    [[ "${META_TS}"  =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}\ [0-9]{2}:[0-9]{2}:[0-9]{2}$ ]] || die 1 "META_TS '${META_TS}' is not YYYY-MM-DD HH:MM:SS"
    INSERT_COLS+=", INFA_BATCH_ID, INFA_LAST_REPLICATED"
    INSERT_VALS+=", ''${BATCH_ID}'', ''${META_TS}''"
elif [ "${HAS_META}" -eq 1 ]; then
    die 1 "${FQ_TABLE} has exactly one of INFA_BATCH_ID / INFA_LAST_REPLICATED; it must have both or neither"
fi

INSERT_STATEMENT="APPLY ('INSERT INTO ${FQ_TABLE} (${INSERT_COLS}) VALUES (${INSERT_VALS});')
        TO OPERATOR (@ConsumerOperator [@LoadInstances])
        SELECT * FROM OPERATOR (FILE_READER [@ReaderInstances]);"

# Substitute placeholders into template using python
python3 -c "
import sys
template_path = sys.argv[1]
output_path = sys.argv[2]
schema_lines = sys.argv[3]
insert_stmt = sys.argv[4]

with open(template_path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('__PAYLOAD_SCHEMA__', schema_lines)
content = content.replace('__INSERT_STATEMENT__', insert_stmt)

with open(output_path, 'w', encoding='utf-8', newline='\n') as f:
    f.write(content)
" "${TEMPLATE}" "${JOB_TPT}" "${SCHEMA_LINES}" "${INSERT_STATEMENT}" || die 1 "Cannot write ${JOB_TPT}"

log INFO "Generated TPT job script at ${JOB_TPT} (${PAYLOAD_COL_COUNT} payload columns, HAS_META=${HAS_META})"
