"""NL Delete tool — top-level assembly. Ties detected scenarios + engineer-provided site
lists/IDs together into the two final output files: SET/Delete commands and GET commands."""
from nl_delete_commands import build_lte_scenario, build_5g_scenario


def assemble_outputs(scenarios, user_inputs):
    """scenarios: from nl_delete_core.build_scenarios().
    user_inputs: {(node, tech): {"id_value": str (manual entry if deleting), "site_list_1": str,
                                  "site_list_2": str_or_None, "delete_node_site_id": str_or_None,
                                  "gnodeb_name": str (5G only)}}
    Returns (set_delete_text, get_commands_text)."""
    set_blocks, get_blocks = [], []

    for s in scenarios:
        key = (s["node"], s["tech"])
        ui = user_inputs.get(key, {})
        is_deletion = s["status"] == "deletes"
        site_list_1 = ui.get("site_list_1", "<SiteList1>")
        site_list_2 = ui.get("site_list_2", "<SiteList2>") if is_deletion else None
        id_value = ui.get("id_value") or s["id_value"] or "<ID>"
        delete_node_site_id = ui.get("delete_node_site_id", s["node"]) if is_deletion else None

        if s["tech"] == "LTE":
            blocks = build_lte_scenario(
                enbid=id_value, site_list_1=site_list_1, cells=s["cells"], is_deletion=is_deletion,
                site_list_2=site_list_2, delete_node_site_id=delete_node_site_id,
            )
        else:
            gnodeb_name = ui.get("gnodeb_name", s["node"])
            blocks = build_5g_scenario(
                gnbid=id_value, gnodeb_name=gnodeb_name, site_list_1=site_list_1, cells=s["cells"],
                is_deletion=is_deletion, site_list_2=site_list_2, delete_node_site_id=delete_node_site_id,
            )

        set_parts = [blocks["set_delete"]]
        if blocks["node_step3"]:
            set_parts.append(blocks["node_step3"])
        set_blocks.append("\n".join(set_parts))

        get_blocks.append(blocks["postchecks_get"])

    set_delete_text = "\n\n\n".join(set_blocks)
    get_commands_text = "\n\n\n".join(get_blocks)
    return set_delete_text, get_commands_text
