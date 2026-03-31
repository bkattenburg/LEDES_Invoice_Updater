import os
from collections import OrderedDict
from typing import List, Tuple, Optional, Dict, Any

import streamlit as st


st.set_page_config(page_title="LEDES Matter / Invoice Updater", layout="wide")


COMMON_MATTER_FIELDS = [
    "LAW_FIRM_MATTER_ID",
    "CLIENT_MATTER_ID",
    "MATTER_ID",
    "MATTER_NUMBER",
]

COMMON_INVOICE_FIELDS = [
    "INVOICE_NUMBER",
]

COMMON_CLIENT_FIELDS = [
    "CLIENT_ID",
]

COMMON_LAW_FIRM_FIELDS = [
    "LAW_FIRM_ID",
]


# -----------------------------
# Helpers
# -----------------------------
def parse_ledes_text(text: str) -> Tuple[List[str], List[List[str]], str, Optional[str], str]:
    """
    Parses a pipe-delimited LEDES-style text file.

    Returns:
        preamble_lines: lines before the header row
        data_rows: parsed rows including header row at index 0
        line_ending: detected line ending
        trailing_token: trailing token such as [] if present on data/header lines
        delimiter: detected delimiter, usually |
    """
    line_ending = "\r\n" if "\r\n" in text else "\n"

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

        if "INVOICE_NUMBER" in candidate and delimiter in candidate:
            header_idx = idx
            trailing_token = candidate_trailing
            break

    if header_idx is None:
        raise ValueError("Could not find a valid LEDES header row containing INVOICE_NUMBER.")

    preamble_lines = raw_lines[:header_idx]
    body_lines = [ln for ln in raw_lines[header_idx:] if ln.strip()]

    parsed_rows: List[List[str]] = []
    for line in body_lines:
        working = line.rstrip()
        if trailing_token and working.endswith(trailing_token):
            working = working[:-len(trailing_token)]
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


def safe_get_first_value(rows: List[List[str]], column_index: Optional[int]) -> str:
    if column_index is None:
        return ""
    for row in rows[1:]:
        if column_index < len(row):
            return row[column_index]
    return ""


def safe_get_row_value(row: List[str], column_index: Optional[int]) -> str:
    if column_index is None:
        return ""
    return row[column_index] if column_index < len(row) else ""


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


def collect_invoice_groups(rows: List[List[str]], invoice_index: int) -> "OrderedDict[str, Dict[str, Any]]":
    groups: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

    for row_idx, row in enumerate(rows[1:], start=1):
        invoice_number = safe_get_row_value(row, invoice_index)
        if invoice_number not in groups:
            groups[invoice_number] = {
                "row_indices": [],
                "sample_row": row,
            }
        groups[invoice_number]["row_indices"].append(row_idx)

    return groups


# -----------------------------
# UI
# -----------------------------
st.title("LEDES Matter / Invoice Updater")
st.write(
    "Upload a LEDES text file, review each invoice in the file, optionally replace matter, invoice, client, "
    "and law firm values, and download the updated file as a .txt file."
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
        invoice_field = find_first_matching_field(header, COMMON_INVOICE_FIELDS)
        client_field = find_first_matching_field(header, COMMON_CLIENT_FIELDS)
        law_firm_field = find_first_matching_field(header, COMMON_LAW_FIRM_FIELDS)

        if not invoice_field:
            st.error("INVOICE_NUMBER was not found in the header row.")
            st.stop()

        matter_indices = [header.index(field) for field in matter_fields]
        invoice_index = header.index(invoice_field)
        client_index = header.index(client_field) if client_field else None
        law_firm_index = header.index(law_firm_field) if law_firm_field else None

        invoice_groups = collect_invoice_groups(parsed_rows, invoice_index)
        invoice_count = len(invoice_groups)

        st.subheader("File summary")
        scol1, scol2, scol3 = st.columns(3)
        with scol1:
            st.metric("Invoices detected", invoice_count)
        with scol2:
            st.metric("Matter fields detected", len(matter_fields))
        with scol3:
            st.metric("Line items detected", len(parsed_rows) - 1)

        st.caption(
            "When Matter Number updating is enabled for an invoice, all detected matter-related fields for that invoice "
            f"are updated together: {', '.join(matter_fields) if matter_fields else 'none detected'}."
        )

        st.subheader("Invoice-specific update options")

        invoice_configs: Dict[str, Dict[str, Any]] = {}

        for invoice_position, (original_invoice_number, group_info) in enumerate(invoice_groups.items(), start=1):
            sample_row = group_info["sample_row"]
            original_matter_value = (
                safe_get_row_value(sample_row, matter_indices[0]) if matter_indices else ""
            )
            original_client_value = safe_get_row_value(sample_row, client_index)
            original_law_firm_value = safe_get_row_value(sample_row, law_firm_index)

            expander_label = (
                f"Invoice {invoice_position} of {invoice_count}: {original_invoice_number} "
                f"({len(group_info['row_indices'])} line items)"
            )

            with st.expander(expander_label, expanded=(invoice_count == 1 or invoice_position == 1)):
                st.markdown("**Original values**")
                dcol1, dcol2, dcol3, dcol4 = st.columns(4)

                with dcol1:
                    st.text_input(
                        "Original Matter Number",
                        value=original_matter_value if matter_fields else "Not found",
                        disabled=True,
                        key=f"orig_matter_{invoice_position}",
                    )
                    st.caption(
                        f"Mapped field(s): {', '.join(matter_fields)}"
                        if matter_fields
                        else "No common matter field was found."
                    )

                with dcol2:
                    st.text_input(
                        "Original Invoice Number",
                        value=original_invoice_number,
                        disabled=True,
                        key=f"orig_invoice_{invoice_position}",
                    )
                    st.caption(f"Mapped field: {invoice_field}")

                with dcol3:
                    st.text_input(
                        "Original Client ID",
                        value=original_client_value if client_field else "Not found",
                        disabled=True,
                        key=f"orig_client_{invoice_position}",
                    )
                    st.caption(
                        f"Mapped field: {client_field}" if client_field else "CLIENT_ID not found."
                    )

                with dcol4:
                    st.text_input(
                        "Original Law Firm ID",
                        value=original_law_firm_value if law_firm_field else "Not found",
                        disabled=True,
                        key=f"orig_lawfirm_{invoice_position}",
                    )
                    st.caption(
                        f"Mapped field: {law_firm_field}" if law_firm_field else "LAW_FIRM_ID not found."
                    )

                st.markdown("**Updated values**")
                ucol1, ucol2, ucol3, ucol4 = st.columns(4)

                with ucol1:
                    update_matter = st.checkbox(
                        "Update Matter Number",
                        value=True if matter_fields else False,
                        disabled=(not matter_fields),
                        key=f"update_matter_{invoice_position}",
                    )
                    new_matter_value = st.text_input(
                        "New Matter Number",
                        value=original_matter_value,
                        disabled=(not update_matter or not matter_fields),
                        key=f"new_matter_{invoice_position}",
                    )

                with ucol2:
                    update_invoice = st.checkbox(
                        "Update Invoice Number",
                        value=True,
                        key=f"update_invoice_{invoice_position}",
                    )
                    new_invoice_value = st.text_input(
                        "New Invoice Number",
                        value=original_invoice_number,
                        disabled=not update_invoice,
                        key=f"new_invoice_{invoice_position}",
                    )

                with ucol3:
                    update_client = st.checkbox(
                        "Update Client ID",
                        value=True if client_field else False,
                        disabled=(client_field is None),
                        key=f"update_client_{invoice_position}",
                    )
                    new_client_value = st.text_input(
                        "New Client ID",
                        value=original_client_value,
                        disabled=(not update_client or client_field is None),
                        key=f"new_client_{invoice_position}",
                    )

                with ucol4:
                    update_law_firm = st.checkbox(
                        "Update Law Firm ID",
                        value=True if law_firm_field else False,
                        disabled=(law_firm_field is None),
                        key=f"update_lawfirm_{invoice_position}",
                    )
                    new_law_firm_value = st.text_input(
                        "New Law Firm ID",
                        value=original_law_firm_value,
                        disabled=(not update_law_firm or law_firm_field is None),
                        key=f"new_lawfirm_{invoice_position}",
                    )

                invoice_configs[original_invoice_number] = {
                    "update_matter": update_matter,
                    "new_matter": new_matter_value,
                    "update_invoice": update_invoice,
                    "new_invoice": new_invoice_value,
                    "update_client": update_client,
                    "new_client": new_client_value,
                    "update_law_firm": update_law_firm,
                    "new_law_firm": new_law_firm_value,
                }

        st.subheader("Output")
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

            for row_idx in range(1, len(parsed_rows)):
                original_row = parsed_rows[row_idx]
                updated_row = updated_rows[row_idx]
                original_invoice_number = safe_get_row_value(original_row, invoice_index)
                config = invoice_configs.get(original_invoice_number, {})

                if config.get("update_matter") and matter_indices:
                    for idx in matter_indices:
                        if idx < len(updated_row):
                            updated_row[idx] = config.get("new_matter", updated_row[idx])

                if config.get("update_client") and client_index is not None and client_index < len(updated_row):
                    updated_row[client_index] = config.get("new_client", updated_row[client_index])

                if config.get("update_law_firm") and law_firm_index is not None and law_firm_index < len(updated_row):
                    updated_row[law_firm_index] = config.get("new_law_firm", updated_row[law_firm_index])

                if config.get("update_invoice") and invoice_index < len(updated_row):
                    updated_row[invoice_index] = config.get("new_invoice", updated_row[invoice_index])

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

            with st.expander("Preview updated header and first few lines"):
                preview_lines = updated_text.splitlines()
                for line in preview_lines[: min(8, len(preview_lines))]:
                    st.code(line, language="text")

    except Exception as exc:
        st.error(f"Unable to process file: {exc}")
else:
    st.info("Upload a LEDES file to begin.")


st.markdown("---")
st.caption(
    "Notes: The app detects INVOICE_NUMBER, CLIENT_ID, and LAW_FIRM_ID, and it detects matter-related fields from common LEDES names such as "
    "LAW_FIRM_MATTER_ID and CLIENT_MATTER_ID. Each distinct invoice number in the file gets its own editable update section. "
    "Disabled update checkboxes leave the original values unchanged."
)
