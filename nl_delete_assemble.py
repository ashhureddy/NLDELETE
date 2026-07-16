"""NL Delete tool — top-level assembly. Ties detected scenarios + engineer-provided site
lists/IDs together into the two final output files: SET/Delete commands and GET commands."""
from nl_delete_commands import build_lte_scenario, build_5g_scenario


def assemble_outputs(scenarios, user_inputs):
    """scenarios: from nl_delete_core.build_scenarios().
    user_inputs: {(node, tech): {"id_value": str (manual entry if deleting), "site_list_1": str,
                                  "site_list_2": str_or_None, "delete_node_site_id": str_or_None,
                                  "gnodeb_name": str (5G only)}}
    Returns (set_delete_text, get_commands_text).

    ComConnectivityInformation / NetworkElement,CmFunction checks are physical-node-level, not
    per-technology — when a physical site has BOTH LTE and 5G deleting together, only the
    primary technology (determined per-site via primary_tech, not hardcoded to either) generates
    that final existence check; the other side skips it. A single-technology deletion (no
    sibling) still gets its own check regardless, since there's no primary to cover it."""
    set_blocks, get_blocks = [], []

    for s in scenarios:
        key = (s["node"], s["tech"])
        ui = user_inputs.get(key, {})
        is_deletion = s["status"] == "deletes"
        site_list_1 = ui.get("site_list_1", "<SiteList1>")
        site_list_2 = ui.get("site_list_2", "<SiteList2>") if is_deletion else None
        id_value = ui.get("id_value") or s["id_value"] or "<ID>"
        delete_node_site_id = ui.get("delete_node_site_id", s["identity_name"]) if is_deletion else None
        # Suppress the node-existence check unless this scenario IS the primary technology
        # for its physical site (or is the only deleting technology there at all).
        other_tech = "5G" if s["tech"] == "LTE" else "LTE"
        sibling_deleting = any(o["node"] == s["node"] and o["tech"] == other_tech and o["status"] == "deletes" for o in scenarios)
        include_node_existence_check = (not sibling_deleting) or (s["tech"] == s.get("primary_tech"))

        if s["tech"] == "LTE":
            blocks = build_lte_scenario(
                enbid=id_value, site_list_1=site_list_1, cells=s["cells"], is_deletion=is_deletion,
                site_list_2=site_list_2, delete_node_site_id=delete_node_site_id,
                include_node_existence_check=include_node_existence_check,
            )
        else:
            gnodeb_name = ui.get("gnodeb_name", s["identity_name"])
            blocks = build_5g_scenario(
                gnbid=id_value, gnodeb_name=gnodeb_name, site_list_1=site_list_1, cells=s["cells"],
                is_deletion=is_deletion, site_list_2=site_list_2, delete_node_site_id=delete_node_site_id,
                include_node_existence_check=include_node_existence_check,
            )

        set_parts = [blocks["set_delete"]]
        if blocks["node_step3"]:
            set_parts.append(blocks["node_step3"])
        set_blocks.append("\n".join(set_parts))

        get_blocks.append(blocks["postchecks_get"])

    set_delete_text = "\n\n\n".join(set_blocks)
    get_commands_text = "\n\n\n".join(get_blocks)
    return set_delete_text, get_commands_text
