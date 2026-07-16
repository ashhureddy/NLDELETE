"""
NL Delete tool — core logic.

Confirmed spec (from extensive discussion):
- Inputs: CIQ (.xlsx) + Pre-checks (.pdf text). No EDP.
- Pre state: Pre-checks' Summary Status table only (Node + Technology columns) — no Hardware Status.
- Post state: CIQ's Mixed Mode Info (eNBId / gNBId presence per node).
- Every identity (eNBId, gNBId) is evaluated INDEPENDENTLY, not per physical node:
    - Existed in Pre-checks, missing from CIQ -> that identity is being deleted (full superset
      treatment: Site List 1 sector-level cleanup + Site List 2 node-level cleanup). The engineer
      must manually supply the eNBId/gNBId for anything in this state, since the CIQ (a pure
      post-state file) has nothing to read for a deleted identity.
    - Present in both -> not a deletion; any of its cells listed in Sector Del_Movement get
      sector-level-ONLY treatment (Site List 1 only), using the eNBId/gNBId already known from
      the CIQ.
- Sector Del_Movement is the authoritative source of which specific cell IDs need relation
  cleanup, for BOTH the sector-only case and as the per-cell list within a full identity deletion.
  Rows are grouped by (Source Node name, technology) — technology inferred per-row from the cell
  name pattern (LTE vs 5G/NRCellDU), since a single node's rows could in principle be mixed.
- auto310_410_3_<ID> and auto1 are fully deterministic from the CIQ's own ID — never manual.
- xxDelete_Node_Site_IDxx / xx5G_Delete_Node_Site_IDxx = the deleted node's own name, straight
  from Pre-checks' Summary Status Node column.
- Output: two separate files — SET/Delete commands, and GET (verification) commands — covering
  every detected scenario for the whole site, not split per node.
"""
import re


# ============================================================
# Shared low-level helpers (same conventions as QUICKIX)
# ============================================================

def is_populated(v):
    if v is None:
        return False
    s = str(v).strip()
    return s != "" and s.upper() not in ("NA", "N/A", "NONE")


def sheet_objs(ws):
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    objs = []
    for r in rows[1:]:
        if not any(str(c).strip() for c in r if c is not None):
            continue
        objs.append({headers[i]: (r[i].strip() if isinstance(r[i], str) else r[i]) if i < len(r) else "" for i in range(len(headers))})
    return objs


# ============================================================
# Pre state (Pre-checks Summary Status) and Post state (CIQ)
# ============================================================

SUMMARY_STATUS_ROW_RE = re.compile(r'(\S+)\s+(LTE|5G)\s+(\S+)\s+(UNLOCKED|LOCKED)')
LTE_CELL_PREFIX_RE = re.compile(r'^(.+?)_\d[A-F]_\d+(_[EF])?$')
FIVEG_CELL_PREFIX_RE = re.compile(r'^(.+?)_N\d{3}[A-F]_\d+$')


def _identity_name_from_cell(cell_name, tech):
    """The Pre-checks 'Node' column is just the physical-site grouping — the actual
    eNodeB/gNodeB Name for each technology has to be derived from its own cells' naming,
    since it can genuinely differ from the Node column (confirmed with real data: Node
    'FCL08071R' but its 5G cells are prefixed 'FCON098071_...', not 'FCL08071R_...')."""
    pattern = LTE_CELL_PREFIX_RE if tech == "LTE" else FIVEG_CELL_PREFIX_RE
    m = pattern.match(str(cell_name))
    return m.group(1) if m else None


def parse_precheck_pre_state(precheck_text):
    """Returns {physical_site: {"LTE": identity_name_or_None, "5G": identity_name_or_None}}
    from Pre-checks' Summary Status table. physical_site (the Node column) is only a grouping
    key; the per-technology values are each technology's REAL derived identity name."""
    pre_state = {}
    if not precheck_text:
        return pre_state
    for m in SUMMARY_STATUS_ROW_RE.finditer(precheck_text):
        node, tech, cell, admin = m.groups()
        node = node.strip()
        pre_state.setdefault(node, {"LTE": None, "5G": None})
        if pre_state[node][tech] is None:
            identity_name = _identity_name_from_cell(cell, tech)
            if identity_name:
                pre_state[node][tech] = identity_name
    return pre_state


def parse_ciq_post_state(ciq_wb):
    """Returns {node_name: {"eNBId": value_or_None, "gNBId": value_or_None}} from Mixed Mode Info."""
    post_state = {}
    if "Mixed Mode Info" not in ciq_wb.sheetnames:
        return post_state
    for row in sheet_objs(ciq_wb["Mixed Mode Info"]):
        node = row.get("Node to be built as")
        if not is_populated(node):
            continue
        post_state[str(node).strip()] = {
            "eNBId": row.get("eNBId") if is_populated(row.get("eNBId")) else None,
            "gNBId": row.get("gNBId") if is_populated(row.get("gNBId")) else None,
        }
    return post_state


def classify_identities(pre_state, post_state):
    """For every node seen in Pre-checks, classify each technology it had as either surviving
    (with its CIQ-derived ID) or deleting (flagged, no ID available — needs manual entry).
    Returns a list of dicts: {"node": str, "tech": "LTE"|"5G", "status": "survives"|"deletes",
    "id_value": <eNBId/gNBId or None>, "identity_name": <the real derived eNodeB/gNodeB Name>}.
    'node' stays as the physical-site grouping key (for UI grouping only); 'identity_name' is
    the correct value to use for anything naming-specific (gNodeB_Name, delete-node site ID)."""
    results = []
    for node, techs in pre_state.items():
        post_node = post_state.get(node)
        for tech, identity_name in techs.items():
            if not identity_name:
                continue
            id_field = "eNBId" if tech == "LTE" else "gNBId"
            post_value = post_node.get(id_field) if post_node else None
            if is_populated(post_value):
                results.append({"node": node, "tech": tech, "status": "survives", "id_value": post_value, "identity_name": identity_name})
            else:
                results.append({"node": node, "tech": tech, "status": "deletes", "id_value": None, "identity_name": identity_name})
    return results


# ============================================================
# Sector Del_Movement — the authoritative per-cell list
# ============================================================

def _cell_technology(cell_name):
    """LTE cells: NODE_<digit><A-F>_<n>[_E/F]. 5G/NRCellDU cells: NODE_N<3digits><A-F>_<n>."""
    if not cell_name:
        return None
    if re.search(r'_N\d{3}[A-F]_\d+$', str(cell_name)):
        return "5G"
    if re.search(r'_\d[A-F]_\d+(_[EF])?$', str(cell_name)):
        return "LTE"
    return None


def parse_sector_del_movement(ciq_wb):
    """Returns a list of {"source_node", "source_cell_id", "source_cell_name", "tech"} —
    one entry per Sector Del_Movement row, technology inferred from the cell name pattern."""
    out = []
    if "Sector Del_Movement" not in ciq_wb.sheetnames:
        return out
    for row in sheet_objs(ciq_wb["Sector Del_Movement"]):
        src_node = row.get("Source Node name")
        src_cell_name = row.get("Source Sector")
        src_cell_id = row.get("Source Cell Id")
        if not is_populated(src_node) or not is_populated(src_cell_name):
            continue
        tech = _cell_technology(src_cell_name)
        if tech is None:
            continue
        out.append({
            "source_node": str(src_node).strip(),
            "source_cell_id": src_cell_id,
            "source_cell_name": str(src_cell_name).strip(),
            "tech": tech,
        })
    return out


def group_moves_by_node_and_tech(move_rows):
    """{(node, tech): [{"cell_id":..., "cell_name":...}, ...]}"""
    grouped = {}
    for r in move_rows:
        key = (r["source_node"], r["tech"])
        grouped.setdefault(key, []).append({"cell_id": r["source_cell_id"], "cell_name": r["source_cell_name"]})
    return grouped


# ============================================================
# Scenario assembly — ties identity classification + cell groups together
# ============================================================

def determine_primary_tech(pre_state):
    """For each physical site, the Node column value (constant across all its rows,
    regardless of technology) matches one of the two derived identity names as a prefix —
    that's the primary technology. Confirmed with real data: Node 'FCL06371R' starts with
    the LTE identity 'FCL06371' but not the 5G identity 'FCON096371' -> LTE is primary."""
    primary = {}
    for node, techs in pre_state.items():
        lte_name, fiveg_name = techs.get("LTE"), techs.get("5G")
        if lte_name and node.startswith(lte_name):
            primary[node] = "LTE"
        elif fiveg_name and node.startswith(fiveg_name):
            primary[node] = "5G"
        else:
            primary[node] = "LTE" if lte_name else ("5G" if fiveg_name else None)
    return primary


def build_scenarios(pre_state, post_state, move_rows):
    """Returns a list of scenario dicts, one per (node, tech) that has either an identity
    deletion or at least one moving/deleting cell:
      {"node", "tech", "status": "survives"|"deletes", "id_value": str_or_None,
       "identity_name", "primary_tech": "LTE"|"5G"|None, "cells": [{"cell_id","cell_name"}, ...]}
    A node/tech with status "deletes" always appears (even with zero cells in Sector
    Del_Movement — the node-level cleanup still applies); a node/tech with status "survives"
    only appears if it actually has moving/deleting cells."""
    identities = classify_identities(pre_state, post_state)
    grouped_cells = group_moves_by_node_and_tech(move_rows)
    primary_tech_by_site = determine_primary_tech(pre_state)

    scenarios = []
    seen_keys = set()
    for ident in identities:
        key = (ident["node"], ident["tech"])
        seen_keys.add(key)
        cells = grouped_cells.get(key, [])
        if ident["status"] == "deletes" or cells:
            scenarios.append({**ident, "cells": cells, "primary_tech": primary_tech_by_site.get(ident["node"])})

    # Any (node, tech) with moving cells but no matching Pre-checks identity entry (e.g. the
    # TARGET side of a move, or a node not seen in Pre-checks at all) is not a deletion scenario
    # on its own — nothing to add here; only SOURCE-side identities matter for NL delete.
    return scenarios


def format_site_label(site, site_techs, primary_tech):
    """site: the raw Pre-checks Node column value (matches CIQ's 'Node to be built as').
    site_techs: {"LTE": name_or_None, "5G": name_or_None} — cell-derived identity names.
    The PRIMARY technology displays as the raw site value (confirmed: 'FCL06371R(P)', not the
    cell-derived 'FCL06371(P)'); the secondary technology displays as its own derived name,
    since it never appears in the Node column at all."""
    lte_name, fiveg_name = site_techs.get("LTE"), site_techs.get("5G")
    if lte_name and fiveg_name:
        secondary_name = fiveg_name if primary_tech == "LTE" else lte_name
        return f"{site}(P)/{secondary_name}(S)"
    if lte_name or fiveg_name:
        return site
    return ""


def build_pre_post_config_lines(pre_state, post_state):
    """Returns (pre_line, post_line) — e.g. 'FCL06371R(P)/FCON096371(S) + ALL04584' style
    summary strings, one entry per physical site, for display at the top of results."""
    primary_tech_by_site = determine_primary_tech(pre_state)
    pre_labels, post_labels = [], []
    for site, techs in pre_state.items():
        primary_tech = primary_tech_by_site.get(site)
        pre_label = format_site_label(site, techs, primary_tech)
        if pre_label:
            pre_labels.append(pre_label)

        post_node = post_state.get(site, {})
        post_techs = {
            "LTE": techs.get("LTE") if is_populated(post_node.get("eNBId")) else None,
            "5G": techs.get("5G") if is_populated(post_node.get("gNBId")) else None,
        }
        post_label = format_site_label(site, post_techs, primary_tech)
        if post_label:
            post_labels.append(post_label)

    return " + ".join(pre_labels), " + ".join(post_labels)


def extract_own_id_from_kgetall(kgetall_text, node, mo_class, attr_name):
    """Parses a 'kget all' dump (a sequence of MO blocks, each starting with an 'MO  <path>'
    header line followed by that block's attribute lines) and returns the value of attr_name
    within the specific MO block matching MeContext=<node>,ManagedElement=<node>,<mo_class>.
    mo_class: 'ENodeBFunction=1' or 'GNBCUCPFunction=1'. Returns None if not found (e.g. a
    5G-only node has no ENodeBFunction=1 block at all)."""
    if not kgetall_text:
        return None
    lines = kgetall_text.splitlines()
    target_suffix = f"MeContext={node},ManagedElement={node},{mo_class}"
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("MO ") and target_suffix in line:
            start_idx = i
            break
    if start_idx is None:
        return None
    for j in range(start_idx + 1, len(lines)):
        if lines[j].strip().startswith("MO ") and "MeContext=" in lines[j]:
            break
        m = re.match(rf'^{attr_name}\s+(\S+)', lines[j].strip())
        if m:
            return m.group(1)
    return None


def extract_own_enbid(kgetall_text, node):
    return extract_own_id_from_kgetall(kgetall_text, node, "ENodeBFunction=1", "eNBId")


def extract_own_gnbid(kgetall_text, node):
    return extract_own_id_from_kgetall(kgetall_text, node, "GNBCUCPFunction=1", "gNBId")


def find_own_id_in_any_kgetall(kgetall_texts, node, tech):
    """Tries extraction against every uploaded kget-all log (a node's data could be in any of
    them, regardless of filename) and returns the first match found."""
    for text in kgetall_texts or []:
        id_val = extract_own_enbid(text, node) if tech == "LTE" else extract_own_gnbid(text, node)
        if id_val:
            return id_val
    return None
