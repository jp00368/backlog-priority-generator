import streamlit as st
import pandas as pd

import config
import jira_client
import sample_data
from components.draggable_table import draggable_table

st.set_page_config(page_title="Backlog Priority Generator", layout="wide")
st.title("Backlog Priority Generator")

# --- Session state init ---
if "issues_df"       not in st.session_state: st.session_state["issues_df"]       = None
if "is_sample_data"  not in st.session_state: st.session_state["is_sample_data"]  = False
if "descriptions"    not in st.session_state: st.session_state["descriptions"]    = {}
if "editor_version"  not in st.session_state: st.session_state["editor_version"]  = 0
if "_pending_desc"   not in st.session_state: st.session_state["_pending_desc"]   = None
if "history"         not in st.session_state: st.session_state["history"]         = []  # undo stack (up to 5)
if "redo_stack"      not in st.session_state: st.session_state["redo_stack"]      = []  # redo stack (up to 5)

HISTORY_LIMIT = 5
BACKLOG_STATUSES = {"Backlog", "On Hold", "New", "Open", "Hold"}
HIDDEN_LABELS: set = set()  # add label strings here to suppress them from the Labels column

def _padded_ranks(n: int) -> list:
    """Return 3-digit zero-padded rank strings: ['001','002',...] sized to n."""
    return [str(i).zfill(3) for i in range(1, n + 1)]

def _push_history(df: pd.DataFrame):
    """Save current state before a change. Clears redo stack."""
    st.session_state["history"].append(df.copy())
    if len(st.session_state["history"]) > HISTORY_LIMIT:
        st.session_state["history"].pop(0)
    st.session_state["redo_stack"].clear()

def _push_redo(df: pd.DataFrame):
    """Save current state to redo stack (called by undo)."""
    st.session_state["redo_stack"].append(df.copy())
    if len(st.session_state["redo_stack"]) > HISTORY_LIMIT:
        st.session_state["redo_stack"].pop(0)


# --- Description modal ---
@st.dialog("Issue Description", width="large")
def show_description_dialog(issue_key: str, description: str):
    st.markdown(f"**{issue_key}**")
    st.divider()
    if description and description.strip():
        st.write(description)
    else:
        st.info("No description available for this issue.")


# --- Sidebar (keyed so fragment can read values via session_state) ---
cfg = config.get_config()
jira_disabled = True

with st.sidebar:
    st.header("Jira Configuration")
    st.caption("🔒 Jira integration — connect to your own instance.")

    st.text_input("Jira URL",        value=cfg["jira_url"],        key="cfg_jira_url",        placeholder="https://your-org.atlassian.net", disabled=jira_disabled)
    st.text_input("API Token (PAT)", value=cfg["jira_api_token"],  key="cfg_api_token",        type="password",                              disabled=jira_disabled)
    st.text_input("Project Key",     value=cfg["jira_project_key"],key="cfg_project_key",      placeholder="e.g. AIPRODUCT",                 disabled=jira_disabled)
    st.text_input("Tracking Field ID",    value=cfg["tracking_field_id"],    key="cfg_field_id",        placeholder="e.g. customfield_11400", disabled=jira_disabled)
    st.text_input("External ID Field ID", value=cfg["external_id_field_id"], key="cfg_ext_id_field_id", placeholder="e.g. customfield_10000", disabled=jira_disabled)

    st.divider()
    st.subheader("Field ID Lookup")
    st.caption("Find the customfield_XXXXX ID for your Tracking ID field.")

    if st.button("List Custom Fields", disabled=jira_disabled):
        jira_url  = st.session_state["cfg_jira_url"]
        api_token = st.session_state["cfg_api_token"]
        if not all([jira_url, api_token]):
            st.error("Enter Jira URL and API token first.")
        else:
            with st.spinner("Fetching fields..."):
                try:
                    fields_df = jira_client.list_custom_fields(jira_url, api_token)
                    st.dataframe(fields_df, use_container_width=True, hide_index=True)
                except RuntimeError as e:
                    st.error(str(e))


# --- Sample data loader ---
if st.session_state["is_sample_data"]:
    st.info(
        "📋 **Sample dataset loaded** — 20 demo issues from a fictional insurance AI product backlog. "
        "Drag rows to reprioritize. Connect your Jira in the sidebar to work with real issues.",
        icon=None,
    )
    if st.button("Clear sample data", type="secondary"):
        st.session_state["issues_df"]      = None
        st.session_state["is_sample_data"] = False
        st.session_state["descriptions"]   = {}
        st.session_state["history"]        = []
        st.session_state["redo_stack"]     = []
        st.rerun()
else:
    if st.button("Load sample data", type="secondary"):
        df = sample_data.get_sample_dataframe()
        st.session_state["descriptions"]   = dict(zip(df["Issue Key"], df["Description"]))
        st.session_state["issues_df"]      = df
        st.session_state["is_sample_data"] = True
        st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
        st.session_state["history"]        = []
        st.session_state["redo_stack"]     = []
        st.rerun()

st.divider()

# --- JQL + Fetch ---
st.subheader("Import Issues from Jira")

default_jql = ""
jql_query = st.text_input(
    "JQL Query or Filter ID",
    value=default_jql,
    key="jql_query",
    help="Enter a JQL query or a numeric saved filter ID (e.g. 12345).",
    disabled=jira_disabled,
)

fetch_btn = st.button("Fetch Issues from Jira", type="primary", disabled=jira_disabled)

if fetch_btn:
    jira_url     = st.session_state["cfg_jira_url"]
    api_token    = st.session_state["cfg_api_token"]
    field_id     = st.session_state["cfg_field_id"]
    ext_field_id = st.session_state["cfg_ext_id_field_id"]

    if not all([jira_url, api_token, field_id, jql_query]):
        st.error("Fill in Jira URL, API Token, Tracking Field ID, and JQL query.")
    else:
        resolved_jql = (
            f"filter={jql_query.strip()}"
            if jql_query.strip().isdigit()
            else jql_query.strip()
        )
        with st.spinner("Fetching issues..."):
            try:
                df = jira_client.fetch_issues_by_jql(
                    jira_url, api_token, resolved_jql, field_id, ext_field_id
                )
                st.session_state["descriptions"] = dict(
                    zip(df["Issue Key"], df["Description"])
                )
                df["_tid_sort"] = pd.to_numeric(df["Tracking ID"], errors="coerce")
                df = df.sort_values("_tid_sort", na_position="last").reset_index(drop=True)
                df.drop(columns=["_tid_sort"], inplace=True)
                df["Rank"] = _padded_ranks(len(df))
                df["UpdateJira"] = df["Tracking ID"].notna() & (df["Tracking ID"].astype(str).str.strip() != "")
                df["Issue URL"] = jira_url.rstrip("/") + "/browse/" + df["Issue Key"]
                st.session_state["issues_df"] = df
                st.session_state["editor_version"] += 1
                st.success(f"Fetched {len(df)} issues.")
            except RuntimeError as e:
                st.error(str(e))


# --- Add single issue ---
if st.session_state["issues_df"] is not None:
    with st.expander("Add an issue by ID", disabled=jira_disabled):
        add_col1, add_col2 = st.columns([3, 1])
        with add_col1:
            add_key = st.text_input(
                "Issue Key", placeholder="e.g. AIPRODUCT-123",
                label_visibility="collapsed", disabled=jira_disabled,
            )
        with add_col2:
            add_btn = st.button("Add Issue", use_container_width=True, disabled=jira_disabled)

        if add_btn:
            jira_url     = st.session_state["cfg_jira_url"]
            api_token    = st.session_state["cfg_api_token"]
            field_id     = st.session_state["cfg_field_id"]
            ext_field_id = st.session_state["cfg_ext_id_field_id"]

            if not add_key.strip():
                st.error("Enter an issue key.")
            else:
                key = add_key.strip().upper()
                existing_keys = st.session_state["issues_df"]["Issue Key"].tolist()
                if key in existing_keys:
                    st.warning(f"{key} is already in the list.")
                else:
                    with st.spinner(f"Fetching {key}..."):
                        try:
                            row = jira_client.fetch_single_issue(
                                jira_url, api_token, key, field_id, ext_field_id
                            )
                            st.session_state["descriptions"][key] = row.get("Description", "")
                            row["Issue URL"] = jira_url.rstrip("/") + "/browse/" + row["Issue Key"]
                            new_row = pd.DataFrame([row])
                            new_n = len(st.session_state["issues_df"]) + 1
                            new_row["Rank"] = str(new_n).zfill(3)
                            tracking_val = row.get("Tracking ID", "")
                            new_row["UpdateJira"] = bool(tracking_val and str(tracking_val).strip())
                            st.session_state["issues_df"] = pd.concat(
                                [st.session_state["issues_df"], new_row],
                                ignore_index=True,
                            )
                            st.session_state["editor_version"] += 1
                            st.success(f"Added {key} at rank {new_row['Rank'].iloc[0]}.")
                            st.rerun()
                        except RuntimeError as e:
                            st.error(str(e))


# --- Main table (fragment = reruns stay local, no scroll-to-top) ---
@st.fragment
def render_table():
    if st.session_state["issues_df"] is None:
        return

    df = st.session_state["issues_df"]

    st.divider()
    col1, col2 = st.columns([6, 1])
    with col1:
        st.subheader("Priority Order")
    with col2:
        st.metric("Total", len(df))

    show_inprogress = st.toggle("Show In Progress items", value=False, key="show_inprogress")

    ctrl_col, undo_col, redo_col, font_col = st.columns([5, 1, 1, 2])
    with ctrl_col:
        st.caption("Drag rows to reorder. Click 📄 to preview an issue's description.")
    with undo_col:
        can_undo = len(st.session_state["history"]) > 0
        if st.button("↩ Undo", disabled=not can_undo, use_container_width=True,
                     help=f"{len(st.session_state['history'])} action(s) to undo"):
            _push_redo(st.session_state["issues_df"])
            st.session_state["issues_df"] = st.session_state["history"].pop()
            st.session_state["editor_version"] += 1
            st.rerun(scope="fragment")
    with redo_col:
        can_redo = len(st.session_state["redo_stack"]) > 0
        if st.button("↪ Redo", disabled=not can_redo, use_container_width=True,
                     help=f"{len(st.session_state['redo_stack'])} action(s) to redo"):
            _push_history(st.session_state["issues_df"])
            st.session_state["redo_stack"][-1]  # peek to verify non-empty
            st.session_state["issues_df"] = st.session_state["redo_stack"].pop()
            st.session_state["editor_version"] += 1
            st.rerun(scope="fragment")
    with font_col:
        font_size = st.slider(
            "Table Font Size", min_value=10, max_value=18, value=13, step=1,
            help="Adjust the font size of the table"
        )

    # Show pending description dialog (set by previous fragment rerun)
    if st.session_state["_pending_desc"]:
        key  = st.session_state["_pending_desc"]
        st.session_state["_pending_desc"] = None
        desc = st.session_state["descriptions"].get(key, "")
        show_description_dialog(key, desc)

    display_data = [
        {
            "Issue URL":   row.get("Issue URL", ""),
            "Issue Key":   row.get("Issue Key", ""),
            "Summary":     row.get("Summary", ""),
            "Issue Type":  row.get("Issue Type", ""),
            "Status":      row.get("Status", ""),
            "Labels":      ", ".join(l for l in (row.get("Labels", "") or "").split(", ") if l and l.strip().lower() not in HIDDEN_LABELS),
            "LoE":         str(row.get("External ID", "") or ""),
            "Tracking ID": str(row.get("Tracking ID", "") or ""),
            "Rank":        str(row.get("Rank", "")),
            "selected":    bool(row.get("UpdateJira", True)),
            "hidden":      row.get("Status", "") not in BACKLOG_STATUSES and not show_inprogress,
        }
        for _, row in df.iterrows()
    ]

    result = draggable_table(
        data=display_data,
        font_size=font_size,
        key=f"drag_table_{st.session_state['editor_version']}",
    )

    if result is not None:
        event_type = result.get("type")

        if event_type == "reorder":
            new_order = result.get("order", [])
            if new_order and new_order != list(range(len(df))):
                _push_history(df)
                reordered = df.iloc[new_order].reset_index(drop=True)
                reordered["Rank"] = _padded_ranks(len(reordered))
                st.session_state["issues_df"] = reordered
                st.session_state["editor_version"] += 1
                st.rerun(scope="fragment")

        elif event_type == "show_desc":
            st.session_state["_pending_desc"] = result.get("key", "")
            st.session_state["editor_version"] += 1
            st.rerun(scope="fragment")

        elif event_type == "toggle_update":
            idx = result.get("idx")
            checked = result.get("checked", True)
            if idx is not None and 0 <= idx < len(df):
                st.session_state["issues_df"].at[idx, "UpdateJira"] = checked
                st.session_state["editor_version"] += 1
                st.rerun(scope="fragment")

    st.divider()

    jira_url     = st.session_state.get("cfg_jira_url", "")
    api_token    = st.session_state.get("cfg_api_token", "")
    field_id     = st.session_state.get("cfg_field_id", "")
    ext_field_id = st.session_state.get("cfg_ext_id_field_id", "")

    if st.button("Update Issues in Jira", type="primary", disabled=jira_disabled):
        if not all([jira_url, api_token, field_id]):
            st.error("Fill in Jira URL, API Token, and Tracking Field ID in the sidebar.")
        else:
            current_df = st.session_state["issues_df"]
            update_df = current_df[current_df["UpdateJira"] == True]
            if update_df.empty:
                st.warning("No issues are checked for update. Check the Update column to select issues.")
            else:
                with st.spinner(f"Updating {len(update_df)} of {len(current_df)} issues in Jira..."):
                    results = jira_client.update_tracking_ids(
                        jira_url, api_token, update_df, field_id
                    )
                successes = [r for r in results if r["status"] == "ok"]
                errors    = [r for r in results if r["status"] == "error"]
                if errors:
                    st.warning(f"Updated {len(successes)} issues. {len(errors)} failed:")
                    for e in errors:
                        st.error(f"**{e['key']}**: {e['detail']}")
                if successes:
                    raw_jql = st.session_state.get("jql_query", "")
                    resolved_jql = (
                        f"filter={raw_jql.strip()}"
                        if raw_jql.strip().isdigit()
                        else raw_jql.strip()
                    )
                    with st.spinner("Refetching updated issues..."):
                        try:
                            df = jira_client.fetch_issues_by_jql(
                                jira_url, api_token, resolved_jql, field_id, ext_field_id
                            )
                            st.session_state["descriptions"] = dict(
                                zip(df["Issue Key"], df["Description"])
                            )
                            df["_tid_sort"] = pd.to_numeric(df["Tracking ID"], errors="coerce")
                            df = df.sort_values("_tid_sort", na_position="last").reset_index(drop=True)
                            df.drop(columns=["_tid_sort"], inplace=True)
                            df["Rank"] = _padded_ranks(len(df))
                            df["UpdateJira"] = df["Tracking ID"].notna() & (df["Tracking ID"].astype(str).str.strip() != "")
                            df["Issue URL"] = jira_url.rstrip("/") + "/browse/" + df["Issue Key"]
                            st.session_state["issues_df"] = df
                            st.session_state["editor_version"] += 1
                            st.success(f"Done. Updated {len(successes)} issues and refreshed the list.")
                        except RuntimeError as e:
                            st.success(f"Successfully updated {len(successes)} issues.")
                            st.warning(f"Refetch failed: {e}")
                    st.rerun(scope="fragment")


render_table()

if st.session_state["issues_df"] is None:
    st.info(
        "Configure your Jira credentials in the sidebar and click "
        "**Fetch Issues from Jira** to get started."
    )
