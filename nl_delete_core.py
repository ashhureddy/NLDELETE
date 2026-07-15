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


def parse_precheck_pre_state(precheck_text):
    """Returns {node_name: {"LTE": bool, "5G": bool}} from Pre-checks' Summary Status table."""
    pre_state = {}
    if not precheck_text:
        return pre_state
    for m in SUMMARY_STATUS_ROW_RE.finditer(precheck_text):
        node, tech, cell, admin = m.groups()
        node = node.strip()
        pre_state.setdefault(node, {"LTE": False, "5G": False})
        pre_state[node][tech] = True
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
    "id_value": <eNBId/gNBId or None>}."""
    results = []
    for node, techs in pre_state.items():
        post_node = post_state.get(node)
        for tech, had_it in techs.items():
            if not had_it:
                continue
            id_field = "eNBId" if tech == "LTE" else "gNBId"
            post_value = post_node.get(id_field) if post_node else None
            if is_populated(post_value):
                results.append({"node": node, "tech": tech, "status": "survives", "id_value": post_value})
            else:
                results.append({"node": node, "tech": tech, "status": "deletes", "id_value": None})
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

def build_scenarios(pre_state, post_state, move_rows):
    """Returns a list of scenario dicts, one per (node, tech) that has either an identity
    deletion or at least one moving/deleting cell:
      {"node", "tech", "status": "survives"|"deletes", "id_value": str_or_None,
       "cells": [{"cell_id","cell_name"}, ...]}
    A node/tech with status "deletes" always appears (even with zero cells in Sector
    Del_Movement — the node-level cleanup still applies); a node/tech with status "survives"
    only appears if it actually has moving/deleting cells."""
    identities = classify_identities(pre_state, post_state)
    grouped_cells = group_moves_by_node_and_tech(move_rows)

    scenarios = []
    seen_keys = set()
    for ident in identities:
        key = (ident["node"], ident["tech"])
        seen_keys.add(key)
        cells = grouped_cells.get(key, [])
        if ident["status"] == "deletes" or cells:
            scenarios.append({**ident, "cells": cells})

    # Any (node, tech) with moving cells but no matching Pre-checks identity entry (e.g. the
    # TARGET side of a move, or a node not seen in Pre-checks at all) is not a deletion scenario
    # on its own — nothing to add here; only SOURCE-side identities matter for NL delete.
    return scenarios
