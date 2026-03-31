import os
from typing import List, Tuple, Optional

import streamlit as st


st.set_page_config(page_title="LEDES Matter / Invoice Updater", layout="centered")


COMMON_MATTER_FIELDS = [
    "LAW_FIRM_MATTER_ID",
    "CLIENT_MATTER_ID",
    "MATTER_ID",
    "MATTER_NUMBER",
]

COMMON_INVOICE_FIELDS = [
    "INVOICE_NUMBER",
]


# -----------------------------
# Helpers
# -----------------------------
def parse_ledes_text(text: str) -> Tuple[List[str], List[List[str]], str, Optional[str], Optional[str]]:
    """
    Parses a pipe-delimited LEDES-style text file.

    Returns:
        preamble_lines: lines before the header row
        data_rows: parsed rows including header row at index 0
        line_ending: detected line ending
        trailing_token: trailing token such as [] if present on data/header lines
        delimiter: detected delimiter, usually |
    """
    if "\r\n" in text:
        line_ending = "\r\n"
    else:
        line_ending = "\n"

    raw_lines = text.splitlines()
    non_empty_lines = [ln for ln in raw_lines if ln.strip()]

    if not non_empty_lines:
        raise ValueError("The uploaded file appears to be empty.")

    delimiter = "|"
    header_idx = None
    trailing_token = None

    for idx, line in enumerate(raw_lines):
        stripped = line.strip()
        if not stripped:
            continue

        candidate = stripped
        candidate_trailing = None

        if candidate.endswith("[]"):
            candidate = candidate[:-2]
            candidate_trailing = "[]"

        if "INVOICE_NUMBER" in candidate and "|" in candidate:
            header_idx = idx
            trailing_token = candidate_trailing
            break

    if header_idx is None:
        raise ValueError(
            "Could not find a valid LEDES header row containing INVOICE_NUMBER."
        )

    preamble_lines = raw_lines[:header_idx]
    body_lines = [ln for ln in raw_lines[header_idx:] if ln.strip()]

    parsed_rows = []
    for line in body_lines:
        working = line.rstrip()
        if trailing_token and working.endswith(trailing_token):
            working = working[: -len(trailing_token)]
        parsed_rows.append(working.split(delimiter))

    if len(parsed_rows) < 2:
        raise ValueError("The file does not contain any invoice line-item rows.")

    return preamble_lines, parsed_rows, line_ending, trailing_token, delimiter


def find_first_matching_field(header: List[str], candidates: List[str]) -> Optional[str]:
    for field in candidates:
        if field in header:
            return field
    return None


def find_all_matching_fields(header: List[str], candidates: List[str]) -> List[str]:
    return [field for field in candidates if field in header]


def safe_get_first_value(rows: List[List[str]], column_index: int) -> str:
    for row in rows[1:]:
        if column_index < len(row):
            return row[column_index]
    return ""


def update_column_value(rows: List[List[str]], column_index: int, new_value: str) -> List[List[str]]:
    updated = [rows[0][:]]
    for row in rows[1:]:
        new_row = row[:]
        if column_index < len(new_row):
            new_row[column_index] = new_value
        updated.append(new_row)
    return updated


def rebuild_ledes_text(
    preamble_lines: List[str],
    rows: List[List[str]],
    line_ending: str,
    trailing_token: Optional[str],
    delimiter: str,
) -> str:
    output_lines = []
    output_lines.extend(preamble_lines)

    for row in rows:
        line = delimiter.join(row)
        if trailing_token:
            line += trailing_token
        output_lines.append(line)

    return line_ending.join(output_lines) + line_ending


def derive_output_filename(original_name: str) -> str:
    base = os.path.splitext(original_name)[0]
    return f"{base}_updated.txt"


# -----------------------------
# UI
# -----------------------------
st.title("LEDES Matter / Invoice Updater")
st.write(
    "Upload a LEDES text file, review the current matter and invoice numbers, "
    "optionally replace either value, and download the updated file as a .txt file."
)

uploaded_file = st.file_uploader(
    "Upload LEDES file",
    type=["txt", "ledes"],
    help="Upload a pipe-delimited LEDES text file.",
)

if uploaded_file is not None:
    try:
        raw_bytes = uploaded_file.read()

        try:
            file_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            file_text = raw_bytes.decode("latin-1")

        preamble_lines, parsed_rows, line_ending, trailing_token, delimiter = parse_ledes_text(file_text)
        header = parsed_rows[0]

        matter_fields = find_all_matching_fields(header, COMMON_MATTER_FIELDS)
        matter_field = matter_fields[0] if matter_fields else None
        invoice_field = find_first_matching_field(header, COMMON_INVOICE_FIELDS)

        if not invoice_field:
            st.error("INVOICE_NUMBER was not found in the header row.")
            st.stop()

        matter_indices = [header.index(field) for field in matter_fields]
        matter_index = matter_indices[0] if matter_indices else None
        invoice_index = header.index(invoice_field)

        original_matter_value = (
            safe_get_first_value(parsed_rows, matter_index) if matter_index is not None else ""
        )
        original_invoice_value = safe_get_first_value(parsed_rows, invoice_index)

        st.subheader("Detected values")
        col1, col2 = st.columns(2)

        with col1:
            st.text_input(
                "Original Matter Number",
                value=original_matter_value if matter_fields else "Not found",
                disabled=True,
            )
            st.caption(
                f"Mapped field(s): {', '.join(matter_fields)}"
                if matter_fields
                else "No common matter field was found."
            )

        with col2:
            st.text_input(
                "Original Invoice Number",
                value=original_invoice_value,
                disabled=True,
            )
            st.caption(f"Mapped field: {invoice_field}")

        st.subheader("Update options")

        update_matter = st.checkbox(
            "Update Matter Number",
            value=True if matter_fields else False,
            disabled=(not matter_fields),
        )

        new_matter_value = st.text_input(
            "New Matter Number",
            value=original_matter_value,
            disabled=(not update_matter or not matter_fields),
        )

        update_invoice = st.checkbox("Update Invoice Number", value=True)
        new_invoice_value = st.text_input(
            "New Invoice Number",
            value=original_invoice_value,
            disabled=not update_invoice,
        )

        default_output_name = derive_output_filename(uploaded_file.name)
        output_filename = st.text_input(
            "Output File Name",
            value=default_output_name,
            help="This will be the downloaded .txt filename.",
        )

        if not output_filename.lower().endswith(".txt"):
            output_filename += ".txt"

        if st.button("Generate Updated File", type="primary"):
            updated_rows = [row[:] for row in parsed_rows]

            if update_matter and matter_indices:
                for idx in matter_indices:
                    updated_rows = update_column_value(updated_rows, idx, new_matter_value)

            if update_invoice:
                updated_rows = update_column_value(updated_rows, invoice_index, new_invoice_value)

            updated_text = rebuild_ledes_text(
                preamble_lines=preamble_lines,
                rows=updated_rows,
                line_ending=line_ending,
                trailing_token=trailing_token,
                delimiter=delimiter,
            )

            st.success("Updated file is ready.")
            st.download_button(
                label="Download Updated .txt File",
                data=updated_text.encode("utf-8"),
                file_name=output_filename,
                mime="text/plain",
            )

            with st.expander("Preview updated header and first line item"):
                preview_lines = updated_text.splitlines()
                for line in preview_lines[: min(4, len(preview_lines))]:
                    st.code(line, language="text")

    except Exception as exc:
        st.error(f"Unable to process file: {exc}")
else:
    st.info("Upload a LEDES file to begin.")


st.markdown("---")
st.caption(
    "Notes: The app detects the invoice field from INVOICE_NUMBER and matter-related fields from common LEDES names "
    "such as LAW_FIRM_MATTER_ID and CLIENT_MATTER_ID. When Matter Number updating is enabled, all detected matter-related fields are updated together. Disabled update checkboxes leave the original values unchanged."
)
