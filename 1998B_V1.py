import csv
import io
import os
from collections import OrderedDict
from typing import List, Tuple, Optional, Dict, Any

import pandas as pd
import streamlit as st


st.set_page_config(page_title="LEDES Matter / Invoice / Timekeeper Updater", layout="wide")


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

COMMON_TIMEKEEPER_NAME_FIELDS = [
    "TIMEKEEPER_NAME",
    "TK_NAME",
    "NAME",
]

COMMON_TIMEKEEPER_ID_FIELDS = [
    "TIMEKEEPER_ID",
    "TK_ID",
    "EMPLOYEE_ID",
    "ID",
]

COMMON_TIMEKEEPER_CLASS_FIELDS = [
    "TIMEKEEPER_CLASSIFICATION",
    "TIMEKEEPER_CLASS",
    "TK_CLASSIFICATION",
    "TK_CLASS",
    "CLASSIFICATION",
    "CLASS",
]


# -----------------------------
# Helpers
# -----------------------------
def decode_text_file(raw_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Unable to decode the uploaded file.")


def normalize_header_name(value: str) -> str:
    return "".join(ch for ch in str(value).strip().upper() if ch.isalnum())


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


def parse_delimited_table(text: str) -> Tuple[List[str], List[Dict[str, str]], str]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = reader.fieldnames or []
    if not headers:
        raise ValueError("The timekeeper CSV does not contain a header row.")

    rows: List[Dict[str, str]] = []
    for raw_row in reader:
        cleaned_row = {str(k).strip(): (str(v).strip() if v is not None else "") for k, v in raw_row.items() if k is not None}
        if any(value for value in cleaned_row.values()):
            rows.append(cleaned_row)

    if not rows:
        raise ValueError("The timekeeper CSV does not contain any data rows.")

    return headers, rows, delimiter


def find_first_matching_field(header: List[str], candidates: List[str]) -> Optional[str]:
    for field in candidates:
        if field in header:
            return field
    return None


def find_all_matching_fields(header: List[str], candidates: List[str]) -> List[str]:
    return [field for field in candidates if field in header]


def find_first_matching_header_by_alias(headers: List[str], aliases: List[str]) -> Optional[str]:
    normalized_to_header = {normalize_header_name(header): header for header in headers}
    for alias in aliases:
        match = normalized_to_header.get(normalize_header_name(alias))
        if match:
            return match
    return None


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


def collect_unique_timekeepers(
    rows: List[List[str]],
    invoice_index: int,
    timekeeper_name_index: int,
    timekeeper_id_index: int,
    timekeeper_class_index: int,
) -> "OrderedDict[Tuple[str, str, str], Dict[str, Any]]":
    groups: "OrderedDict[Tuple[str, str, str], Dict[str, Any]]" = OrderedDict()

    for row_idx, row in enumerate(rows[1:], start=1):
        key = (
            safe_get_row_value(row, timekeeper_name_index),
            safe_get_row_value(row, timekeeper_id_index),
            safe_get_row_value(row, timekeeper_class_index),
        )
        invoice_number = safe_get_row_value(row, invoice_index)

        if key not in groups:
            groups[key] = {
                "row_indices": [],
                "invoice_numbers": set(),
            }

        groups[key]["row_indices"].append(row_idx)
        groups[key]["invoice_numbers"].add(invoice_number)

    return groups


def format_timekeeper_label(name: str, timekeeper_id: str, classification: str) -> str:
    return f"{name or '[blank name]'} | {timekeeper_id or '[blank id]'} | {classification or '[blank classification]'}"


def build_approved_timekeeper_records(
    rows: List[Dict[str, str]],
    name_col: str,
    id_col: str,
    class_col: str,
) -> List[Dict[str, str]]:
    deduped: "OrderedDict[Tuple[str, str, str], Dict[str, str]]" = OrderedDict()

    for row in rows:
        name = row.get(name_col, "").strip()
        timekeeper_id = row.get(id_col, "").strip()
        classification = row.get(class_col, "").strip()

        if not any([name, timekeeper_id, classification]):
            continue

        key = (name, timekeeper_id, classification)
        if key not in deduped:
            deduped[key] = {
                "name": name,
                "id": timekeeper_id,
                "classification": classification,
                "label": format_timekeeper_label(name, timekeeper_id, classification),
            }

    return list(deduped.values())


# -----------------------------
# UI
# -----------------------------
st.title("LEDES Matter / Invoice / Timekeeper Updater")
st.write(
    "Upload a LEDES text file, review each invoice in the file, optionally replace matter, invoice, client, "
    "law firm, and timekeeper values, and download the updated file as a .txt file. "
    "Timekeeper remapping updates Name, ID, and Classification together, but it does not recalculate rates or totals."
)

uploaded_file = st.file_uploader(
    "Upload LEDES file",
    type=["txt", "ledes"],
    help="Upload a pipe-delimited LEDES text file.",
)

if uploaded_file is not None:
    try:
        raw_bytes = uploaded_file.read()
        file_text = decode_text_file(raw_bytes)

        preamble_lines, parsed_rows, line_ending, trailing_token, delimiter = parse_ledes_text(file_text)
        header = parsed_rows[0]

        matter_fields = find_all_matching_fields(header, COMMON_MATTER_FIELDS)
        invoice_field = find_first_matching_field(header, COMMON_INVOICE_FIELDS)
        client_field = find_first_matching_field(header, COMMON_CLIENT_FIELDS)
        law_firm_field = find_first_matching_field(header, COMMON_LAW_FIRM_FIELDS)

        timekeeper_name_field = find_first_matching_field(header, COMMON_TIMEKEEPER_NAME_FIELDS)
        timekeeper_id_field = find_first_matching_field(header, COMMON_TIMEKEEPER_ID_FIELDS)
        timekeeper_class_field = find_first_matching_field(header, COMMON_TIMEKEEPER_CLASS_FIELDS)

        if not invoice_field:
            st.error("INVOICE_NUMBER was not found in the header row.")
            st.stop()

        matter_indices = [header.index(field) for field in matter_fields]
        invoice_index = header.index(invoice_field)
        client_index = header.index(client_field) if client_field else None
        law_firm_index = header.index(law_firm_field) if law_firm_field else None

        timekeeper_name_index = header.index(timekeeper_name_field) if timekeeper_name_field else None
        timekeeper_id_index = header.index(timekeeper_id_field) if timekeeper_id_field else None
        timekeeper_class_index = header.index(timekeeper_class_field) if timekeeper_class_field else None

        invoice_groups = collect_invoice_groups(parsed_rows, invoice_index)
        invoice_count = len(invoice_groups)

        st.subheader("File summary")
        scol1, scol2, scol3, scol4 = st.columns(4)
        with scol1:
            st.metric("Invoices detected", invoice_count)
        with scol2:
            st.metric("Matter fields detected", len(matter_fields))
        with scol3:
            st.metric("Line items detected", len(parsed_rows) - 1)
        with scol4:
            detected_timekeeper_fields = sum(
                1
                for field in [timekeeper_name_field, timekeeper_id_field, timekeeper_class_field]
                if field is not None
            )
            st.metric("Timekeeper fields detected", detected_timekeeper_fields)

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

        st.subheader("Timekeeper mapping")
        timekeeper_mapping_configs: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        has_required_timekeeper_fields = all(
            field is not None
            for field in [timekeeper_name_field, timekeeper_id_field, timekeeper_class_field]
        )

        if not has_required_timekeeper_fields:
            missing_timekeeper_fields = []
            if timekeeper_name_field is None:
                missing_timekeeper_fields.append("TIMEKEEPER_NAME")
            if timekeeper_id_field is None:
                missing_timekeeper_fields.append("TIMEKEEPER_ID")
            if timekeeper_class_field is None:
                missing_timekeeper_fields.append("TIMEKEEPER_CLASSIFICATION")

            st.warning(
                "Timekeeper mapping is unavailable because the uploaded LEDES file is missing required field(s): "
                + ", ".join(missing_timekeeper_fields)
            )
        else:
            unique_timekeepers = collect_unique_timekeepers(
                parsed_rows,
                invoice_index=invoice_index,
                timekeeper_name_index=timekeeper_name_index,
                timekeeper_id_index=timekeeper_id_index,
                timekeeper_class_index=timekeeper_class_index,
            )

            tcol1, tcol2 = st.columns(2)
            with tcol1:
                st.metric("Original timekeepers detected", len(unique_timekeepers))
            with tcol2:
                st.metric("Line items with timekeepers", sum(len(v["row_indices"]) for v in unique_timekeepers.values()))

            original_timekeeper_preview = []
            for (orig_name, orig_id, orig_class), tk_info in unique_timekeepers.items():
                original_timekeeper_preview.append(
                    {
                        "Original Name": orig_name,
                        "Original ID": orig_id,
                        "Original Classification": orig_class,
                        "Line Items": len(tk_info["row_indices"]),
                        "Invoices": ", ".join(sorted(tk_info["invoice_numbers"])),
                    }
                )

            with st.expander("Preview original timekeepers", expanded=False):
                st.dataframe(pd.DataFrame(original_timekeeper_preview), use_container_width=True, hide_index=True)

            st.caption(
                "Upload a CSV containing the law firm's approved timekeepers. The app will let you map each original "
                "invoice timekeeper to one approved timekeeper, updating Name, ID, and Classification together. "
                "Rates and totals are not recalculated."
            )

            approved_timekeeper_file = st.file_uploader(
                "Upload approved timekeeper CSV",
                type=["csv", "txt"],
                key="approved_timekeeper_csv",
                help="Upload a CSV or delimited text file containing approved timekeepers for the law firm.",
            )

            if approved_timekeeper_file is not None:
                approved_tk_text = decode_text_file(approved_timekeeper_file.read())
                csv_headers, csv_rows, detected_csv_delimiter = parse_delimited_table(approved_tk_text)

                st.caption(f"Detected CSV delimiter: {repr(detected_csv_delimiter)}")

                detected_name_col = find_first_matching_header_by_alias(csv_headers, COMMON_TIMEKEEPER_NAME_FIELDS)
                detected_id_col = find_first_matching_header_by_alias(csv_headers, COMMON_TIMEKEEPER_ID_FIELDS)
                detected_class_col = find_first_matching_header_by_alias(csv_headers, COMMON_TIMEKEEPER_CLASS_FIELDS)

                st.markdown("**Approved timekeeper CSV column mapping**")
                cmap1, cmap2, cmap3 = st.columns(3)
                with cmap1:
                    approved_name_col = st.selectbox(
                        "Approved Timekeeper Name column",
                        options=csv_headers,
                        index=csv_headers.index(detected_name_col) if detected_name_col in csv_headers else 0,
                        key="approved_name_col",
                    )
                with cmap2:
                    approved_id_col = st.selectbox(
                        "Approved Timekeeper ID column",
                        options=csv_headers,
                        index=csv_headers.index(detected_id_col) if detected_id_col in csv_headers else 0,
                        key="approved_id_col",
                    )
                with cmap3:
                    approved_class_col = st.selectbox(
                        "Approved Timekeeper Classification column",
                        options=csv_headers,
                        index=csv_headers.index(detected_class_col) if detected_class_col in csv_headers else 0,
                        key="approved_class_col",
                    )

                if len({approved_name_col, approved_id_col, approved_class_col}) < 3:
                    st.error("Please map three distinct columns for approved Timekeeper Name, ID, and Classification.")
                else:
                    approved_timekeepers = build_approved_timekeeper_records(
                        rows=csv_rows,
                        name_col=approved_name_col,
                        id_col=approved_id_col,
                        class_col=approved_class_col,
                    )

                    if not approved_timekeepers:
                        st.error("No approved timekeeper records could be built from the selected CSV columns.")
                    else:
                        st.metric("Approved timekeepers loaded", len(approved_timekeepers))

                        approved_option_values = [""] + [record["label"] for record in approved_timekeepers]
                        approved_lookup = {record["label"]: record for record in approved_timekeepers}

                        st.markdown("**Timekeeper remapping selections**")
                        for tk_position, ((orig_name, orig_id, orig_class), tk_info) in enumerate(unique_timekeepers.items(), start=1):
                            original_label = format_timekeeper_label(orig_name, orig_id, orig_class)
                            expander_label = (
                                f"Timekeeper {tk_position} of {len(unique_timekeepers)}: {original_label} "
                                f"({len(tk_info['row_indices'])} line items)"
                            )

                            with st.expander(expander_label, expanded=(tk_position <= 3)):
                                st.text_input(
                                    "Original Timekeeper",
                                    value=original_label,
                                    disabled=True,
                                    key=f"orig_tk_label_{tk_position}",
                                )
                                st.caption(
                                    "Invoices impacted: " + ", ".join(sorted(tk_info["invoice_numbers"]))
                                )

                                remap_timekeeper = st.checkbox(
                                    "Remap this timekeeper",
                                    value=False,
                                    key=f"remap_tk_{tk_position}",
                                )

                                selected_approved_label = st.selectbox(
                                    "Approved timekeeper",
                                    options=approved_option_values,
                                    index=0,
                                    disabled=not remap_timekeeper,
                                    key=f"approved_tk_select_{tk_position}",
                                    help="Select the approved timekeeper that should replace this original timekeeper.",
                                )

                                selected_approved_record = approved_lookup.get(selected_approved_label)
                                if remap_timekeeper and selected_approved_record:
                                    st.markdown(
                                        f"**Updated values**  \\n"
                                        f"Name: {selected_approved_record['name']}  \\n"
                                        f"ID: {selected_approved_record['id']}  \\n"
                                        f"Classification: {selected_approved_record['classification']}"
                                    )

                                timekeeper_mapping_configs[(orig_name, orig_id, orig_class)] = {
                                    "update_timekeeper": bool(remap_timekeeper and selected_approved_record),
                                    "approved_timekeeper": selected_approved_record,
                                }

                        mapping_preview_rows = []
                        for (orig_name, orig_id, orig_class), config in timekeeper_mapping_configs.items():
                            approved_record = config.get("approved_timekeeper")
                            if config.get("update_timekeeper") and approved_record:
                                mapping_preview_rows.append(
                                    {
                                        "Original Name": orig_name,
                                        "Original ID": orig_id,
                                        "Original Classification": orig_class,
                                        "Updated Name": approved_record["name"],
                                        "Updated ID": approved_record["id"],
                                        "Updated Classification": approved_record["classification"],
                                    }
                                )

                        if mapping_preview_rows:
                            with st.expander("Preview active timekeeper mappings", expanded=False):
                                st.dataframe(pd.DataFrame(mapping_preview_rows), use_container_width=True, hide_index=True)
                        else:
                            st.info("No active timekeeper mappings selected yet.")
            else:
                st.info("Upload an approved timekeeper CSV to enable timekeeper remapping.")

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
                invoice_config = invoice_configs.get(original_invoice_number, {})

                if invoice_config.get("update_matter") and matter_indices:
                    for idx in matter_indices:
                        if idx < len(updated_row):
                            updated_row[idx] = invoice_config.get("new_matter", updated_row[idx])

                if invoice_config.get("update_client") and client_index is not None and client_index < len(updated_row):
                    updated_row[client_index] = invoice_config.get("new_client", updated_row[client_index])

                if invoice_config.get("update_law_firm") and law_firm_index is not None and law_firm_index < len(updated_row):
                    updated_row[law_firm_index] = invoice_config.get("new_law_firm", updated_row[law_firm_index])

                if invoice_config.get("update_invoice") and invoice_index < len(updated_row):
                    updated_row[invoice_index] = invoice_config.get("new_invoice", updated_row[invoice_index])

                if has_required_timekeeper_fields:
                    original_timekeeper_key = (
                        safe_get_row_value(original_row, timekeeper_name_index),
                        safe_get_row_value(original_row, timekeeper_id_index),
                        safe_get_row_value(original_row, timekeeper_class_index),
                    )
                    timekeeper_config = timekeeper_mapping_configs.get(original_timekeeper_key, {})
                    approved_record = timekeeper_config.get("approved_timekeeper")

                    if timekeeper_config.get("update_timekeeper") and approved_record:
                        updated_row[timekeeper_name_index] = approved_record["name"]
                        updated_row[timekeeper_id_index] = approved_record["id"]
                        updated_row[timekeeper_class_index] = approved_record["classification"]

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
    "Notes: The app detects INVOICE_NUMBER, CLIENT_ID, LAW_FIRM_ID, and common matter-related fields such as "
    "LAW_FIRM_MATTER_ID and CLIENT_MATTER_ID. When present, it also detects TIMEKEEPER_NAME, TIMEKEEPER_ID, and "
    "TIMEKEEPER_CLASSIFICATION for approved timekeeper remapping. Each distinct invoice number in the file gets its "
    "own editable update section. Disabled update checkboxes leave the original values unchanged. Timekeeper remapping "
    "does not recalculate rates, units, totals, or any other invoice math."
)
