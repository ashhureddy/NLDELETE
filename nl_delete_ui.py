import streamlit as st
import openpyxl
import io

import nl_delete_core as core
from nl_delete_commands import lte_sector_discovery_command, lte_node_discovery_command, gnb_sector_discovery_command, gnb_node_discovery_command
from nl_delete_assemble import assemble_outputs

st.set_page_config(page_title="NL Delete", layout="wide")

st.markdown(
    """
    <style>
    .qkx-scenario-card { border: 1px solid #d8dee8; border-radius: 8px; padding: 14px 18px; margin-bottom: 14px; background: #fbfcfe; }
    .qkx-scenario-title { font-weight: 700; font-size: 1.05rem; }
    .qkx-badge-delete { background:#fdeaea; color:#b3261e; padding:2px 10px; border-radius:12px; font-size:0.78rem; font-weight:600; }
    .qkx-badge-survive { background:#e8f1fd; color:#1a56b0; padding:2px 10px; border-radius:12px; font-size:0.78rem; font-weight:600; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("NL Delete Tool")
st.caption("Neighbor Relation deletion — sector moves/deletes and full identity deletions, LTE + 5G")

if "nl_scenarios" not in st.session_state:
    st.session_state.nl_scenarios = None
if "nl_user_inputs" not in st.session_state:
    st.session_state.nl_user_inputs = {}

with st.container(border=True):
    st.subheader("1. Inputs")
    c1, c2, c3 = st.columns(3)
    with c1:
        ciq_file = st.file_uploader("CIQ (.xlsx)", type=["xlsx"])
    with c2:
        precheck_file = st.file_uploader("Pre-checks (.pdf)", type=["pdf"])
    with c3:
        kgetall_files = st.file_uploader(
            "Pre 'kget all' logs (one per node, any that apply)",
            type=["log", "txt"], accept_multiple_files=True,
        )
    analyze = st.button("Analyze \u2192", type="primary", disabled=not (ciq_file and precheck_file))

if analyze:
    st.session_state.nl_kgetall_texts = [
        f.read().decode("utf-8", errors="replace") for f in (kgetall_files or [])
    ]
    import pdfplumber
    ciq_wb = openpyxl.load_workbook(io.BytesIO(ciq_file.read()), data_only=True)
    with pdfplumber.open(io.BytesIO(precheck_file.read())) as pdf:
        precheck_text = "\n".join(p.extract_text() or "" for p in pdf.pages)

    pre_state = core.parse_precheck_pre_state(precheck_text)
    post_state = core.parse_ciq_post_state(ciq_wb)
    move_rows = core.parse_sector_del_movement(ciq_wb)
    scenarios = core.build_scenarios(pre_state, post_state, move_rows)
    pre_line, post_line = core.build_pre_post_config_lines(pre_state, post_state)

    st.session_state.nl_scenarios = scenarios
    st.session_state.nl_pre_line = pre_line
    st.session_state.nl_post_line = post_line
    st.session_state.nl_user_inputs = {}
    if not scenarios:
        st.warning("No sector moves/deletes or identity deletions detected between Pre-checks and the CIQ.")

scenarios = st.session_state.nl_scenarios


def render_scenario_inputs(s):
    """Renders the input widgets for one (node, tech) scenario and returns nothing —
    writes into st.session_state.nl_user_inputs as a side effect, same as before."""
    key = (s["node"], s["tech"])
    is_deletion = s["status"] == "deletes"
    badge = '<span class="qkx-badge-delete">FULL IDENTITY DELETION</span>' if is_deletion else '<span class="qkx-badge-survive">SECTOR MOVE/DELETE</span>'
    st.markdown(f'<div class="qkx-scenario-title">[{s["tech"]}] &nbsp;{s["identity_name"]}&nbsp; {badge}</div>', unsafe_allow_html=True)
    st.caption(f'{len(s["cells"])} cell(s): ' + ", ".join(str(c.get("cell_id")) for c in s["cells"]))

    ui = st.session_state.nl_user_inputs.setdefault(key, {})

    if is_deletion:
        id_label = "eNBId" if s["tech"] == "LTE" else "gNBId"
        kgetall_texts = st.session_state.get("nl_kgetall_texts", [])
        id_val = core.find_own_id_in_any_kgetall(kgetall_texts, s["node"], s["tech"])
        if id_val:
            st.success(f"{id_label} for {s['node']}: **{id_val}**")
        else:
            st.warning(f"No uploaded kget all log contains the {id_label} for {s['node']}.")
        ui["id_value"] = id_val
        ui["gnodeb_name"] = s["identity_name"]
        ui["delete_node_site_id"] = s["identity_name"]
        if s["tech"] == "5G":
            st.caption(f"gNodeB Name: **{s['identity_name']}**")
        st.caption(f"Delete Node Site ID: **{s['identity_name']}**")

        if id_val:
            st.markdown("**Run for Site List 1 (sector-level):**")
            if s["tech"] == "LTE":
                st.code(lte_sector_discovery_command(id_val), language=None)
            else:
                st.code(gnb_sector_discovery_command(id_val), language=None)
            ui["site_list_1"] = st.text_area("Site List 1 result (sector-level)", key=f"sl1_{key}", height=80)

            st.markdown("**Run for Site List 2 (node-level):**")
            if s["tech"] == "LTE":
                st.code(lte_node_discovery_command(id_val), language=None)
            else:
                st.code(gnb_node_discovery_command(ui.get("gnodeb_name", s["identity_name"]), id_val), language=None)
            sl2_raw = st.text_area("Site List 2 result (node-level)", key=f"sl2_{key}", height=80)
            ui["site_list_2"] = core.dedupe_site_list_entries(sl2_raw)
            dupes = core.find_duplicate_site_list_entries(sl2_raw)
            if dupes:
                st.info(f"Removed duplicate Site IDs: {', '.join(dupes)}")
        else:
            st.info("Enter the ID above to reveal the Site List discovery commands.")

    else:
        id_val = s["id_value"]
        ui["id_value"] = id_val
        if s["tech"] == "5G":
            ui["gnodeb_name"] = s["identity_name"]
            st.caption(f"gNodeB Name: **{s['identity_name']}**")
            st.code(gnb_sector_discovery_command(id_val), language=None)
        else:
            st.code(lte_sector_discovery_command(id_val), language=None)
        ui["site_list_1"] = st.text_area("Site List 1 (result)", key=f"sl1_{key}", height=80)


if scenarios:
    with st.container(border=True):
        st.markdown(f"**Pre Configuration:** {st.session_state.get('nl_pre_line', '')}")
        st.markdown(f"**Post Configuration:** {st.session_state.get('nl_post_line', '')}")

    st.subheader("2. Detected scenarios")

    # Group by physical site (Pre-checks' Node column) so LTE + 5G for the same site
    # (e.g. FCL08071R primary / FCON098071 secondary) render together in one card.
    by_site = {}
    for s in scenarios:
        by_site.setdefault(s["node"], []).append(s)

    for site, site_scenarios in by_site.items():
        with st.container(border=True):
            st.markdown(f'<div class="qkx-scenario-title">{site}</div>', unsafe_allow_html=True)
            if len(site_scenarios) > 1:
                cols = st.columns(len(site_scenarios))
                for col, s in zip(cols, site_scenarios):
                    with col:
                        render_scenario_inputs(s)
            else:
                render_scenario_inputs(site_scenarios[0])

    st.subheader("3. Generate")
    if st.button("Generate NL Delete output files \u2192", type="primary"):
        set_text, get_text = assemble_outputs(scenarios, st.session_state.nl_user_inputs)
        st.success("Generated.")

        site_tag = "_".join(sorted({s["node"] for s in scenarios}))
        set_filename = f"NL_Delete_SET_{site_tag}.txt"
        get_filename = f"NL_Delete_GET_{site_tag}.txt"

        c1, c2 = st.columns(2)
        with c1:
            st.download_button("Download SET/Delete commands", set_text, file_name=set_filename)
        with c2:
            st.download_button("Download GET (verification) commands", get_text, file_name=get_filename)

        import zipfile
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(set_filename, set_text)
            zf.writestr(get_filename, get_text)
        st.download_button(
            "Download both (SET + GET) as .zip",
            zip_buf.getvalue(),
            file_name=f"NL_Delete_{site_tag}.zip",
            mime="application/zip",
        )

        with st.expander("Preview SET/Delete commands"):
            st.code(set_text, language=None)
        with st.expander("Preview GET commands"):
            st.code(get_text, language=None)
