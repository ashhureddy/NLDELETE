"""
NL Delete tool — command generation.

Builds the exact command text from the 4 confirmed templates:
  - LTE sector move/delete (Site List 1 only)
  - LTE full identity deletion (Site List 1 + Site List 2, superset of the above)
  - 5G sector move/delete (Site List 1 only)
  - 5G full identity deletion (Site List 1 + Site List 2, superset of the above)

Each returns three blocks of text: prechecks_get, set_delete, get_verify_and_postchecks —
matching the templates' Step 1 (Prechecks) / Step 2 (Execution, incl. its own embedded GET
verification) / Step 3+ (Postchecks, plus node-deletion's extra auto-cleanup sub-step).

The final assembly splits these into the two confirmed output files: SET/Delete commands
(everything except pure "get" blocks) and GET commands (every verification query, at all
three stages) — built by the caller from these pieces.
"""

SITE_A_TO_Z = "A*;B*;C*;D*;E*;F*;G*;H*;I*;J*;K*;L*;M*;N*;O*;P*;Q*;R*;S*;T*;U*;V*;W*;X*;Y*;Z*"


def lte_sector_discovery_command(enbid):
    return f"cmedit get {SITE_A_TO_Z} ExternalEnodeBFunction.(enBID=={enbid}) -t"


def lte_node_discovery_command(enbid):
    return f"cmedit get {SITE_A_TO_Z} ExternalenodeBFunction.(eNodeBId=={enbid}) -t"


def gnb_sector_discovery_command(gnbid):
    return f"cmedit get {SITE_A_TO_Z} ExternalGnodeBFunction.(gNodeBId=={gnbid}) -t"


def gnb_node_discovery_command(gnodeb_name, gnbid):
    return (
        f"cmedit get {SITE_A_TO_Z} ExternalGNBCUCPFunction.(ExternalGNBCUCPFunctionId=={gnodeb_name}) -t\n"
        f"cmedit get {SITE_A_TO_Z} ExternalGNBCUCPFunction.gnbid=={gnbid} -t"
    )


def build_lte_scenario(enbid, site_list_1, cells, is_deletion, site_list_2=None, delete_node_site_id=None):
    """cells: [{"cell_id":...}]. Returns {"prechecks_get","set_delete","get_verify","postchecks_get"}."""
    cell_ids = [c["cell_id"] for c in cells]

    prechecks = []
    for cid in cell_ids:
        prechecks.append(f"cmedit get {site_list_1}  ExternalEUtranCellFDD.(ExternalEUtranCellFDDid==310410-{enbid}-{cid}) \u2013t")
    for cid in cell_ids:
        prechecks.append(f"cmedit get {site_list_1} EUtranCellRelation.(eUtranCellRelationId==310410-{enbid}-{cid}) -t")
    if is_deletion:
        prechecks.append(f"cmedit get {site_list_1} ExternalEnodeBFunction.(ExternalENodeBFunctionId==310410-{enbid}) -t")
    prechecks.append(f"cmedit get {site_list_1} TermPointToENB.(administrativeState,usedipAddress,operationalState,availabilityStatus,termpointtoenbId==310410-{enbid}) -t")

    set_delete = []
    set_delete.append(f"cmedit get {site_list_1} TermPointToENB.(administrativeState,usedipAddress,operationalState,availabilityStatus,termpointtoenbId==310410-{enbid}) -t")
    set_delete.append(f"cmedit set {site_list_1} Termpointtoenb.(termpointtoenbId==310410-{enbid}) administrativestate=LOCKED")
    for cid in cell_ids:
        set_delete.append(f"cmedit delete {site_list_1} EUtranCellRelation.(eUtranCellRelationId==310410-{enbid}-{cid}) --force -ALL")
    for cid in cell_ids:
        set_delete.append(f"cmedit delete {site_list_1}  ExternalEUtranCellFDD.(ExternalEUtranCellFDDid==310410-{enbid}-{cid}) --force -ALL")
    if is_deletion:
        set_delete.append(f"cmedit delete {site_list_1} Termpointtoenb.(termpointtoenbId==310410-{enbid}) --force -ALL")
        set_delete.append(f"cmedit delete {site_list_1} ExternalEnodeBFunction.(ExternalENodeBFunctionId==310410-{enbid}) --force -ALL")

    get_verify = []
    for cid in cell_ids:
        get_verify.append(f"cmedit get {site_list_1}  ExternalEUtranCellFDD.(ExternalEUtranCellFDDid==310410-{enbid}-{cid}) \u2013t")
    for cid in cell_ids:
        get_verify.append(f"cmedit get {site_list_1} EUtranCellRelation.(eUtranCellRelationId==310410-{enbid}-{cid}) -t")
    if is_deletion:
        get_verify.append(f"cmedit get {site_list_1} TermPointToENB.(administrativeState,usedipAddress,operationalState,availabilityStatus,termpointtoenbId==310410-{enbid}) -t")
        get_verify.append(f"cmedit get {site_list_1} ExternalEnodeBFunction.(ExternalENodeBFunctionId==310410-{enbid}) -t")
    else:
        set_delete.append(f"cmedit set {site_list_1} Termpointtoenb.(termpointtoenbId==310410-{enbid}) administrativestate=UNLOCKED")
        get_verify.append(f"cmedit get {site_list_1} TermPointToENB.(administrativeState,usedipAddress,operationalState,availabilityStatus,termpointtoenbId==310410-{enbid}) -t")

    node_step3 = []
    if is_deletion:
        node_step3.append(f"# --- Step 3: auto-created ExternalENodeBFunction cleanup (Site List 2) ---")
        node_step3.append(lte_node_discovery_command(enbid))
        node_step3.append(f"cmedit set {site_list_2}  ExternalENodeBFunction.(ExternalENodeBFunctionId==auto310_410_3_{enbid}),TermPointToENodeB.(TermPointToENodeBId==auto1) administrativestate:LOCKED")
        node_step3.append(f"cmedit delete {site_list_2}  ExternalENodeBFunction.(ExternalENodeBFunctionID==auto310_410_3_{enbid}) -ALL")
        node_step3.append(lte_node_discovery_command(enbid))

    postchecks = []
    for cid in cell_ids:
        postchecks.append(f"cmedit get {site_list_1}  ExternalEUtranCellFDD.(ExternalEUtranCellFDDid==310410-{enbid}-{cid}) \u2013t")
    for cid in cell_ids:
        postchecks.append(f"cmedit get {site_list_1} EUtranCellRelation.(eUtranCellRelationId==310410-{enbid}-{cid}) -t")
    postchecks.append(f"cmedit get {site_list_1} TermPointToENB.(administrativeState,usedipAddress,operationalState,availabilityStatus,termpointtoenbId==310410-{enbid}) -t")
    if is_deletion:
        postchecks.append(f"cmedit get {site_list_1} ExternalEnodeBFunction.(ExternalENodeBFunctionId==310410-{enbid}) -t")
        postchecks.append(lte_node_discovery_command(enbid))
        postchecks.append(lte_sector_discovery_command(enbid))
        postchecks.append(f"\ncmedit get {delete_node_site_id} ComConnectivityInformation.*")
        postchecks.append(f"cmedit get NetworkElement={delete_node_site_id},CmFunction=1")

    return {
        "prechecks_get": "\n".join(prechecks),
        "set_delete": "\n".join(set_delete),
        "get_verify": "\n".join(get_verify),
        "node_step3": "\n".join(node_step3),
        "postchecks_get": "\n".join(postchecks),
    }


def build_5g_scenario(gnbid, gnodeb_name, site_list_1, cells, is_deletion, site_list_2=None, delete_node_site_id=None):
    """cells: [{"cell_id":..., "cell_name":...}]."""
    cell_ids = [c["cell_id"] for c in cells]
    cell_names = [c["cell_name"] for c in cells]
    tpgnb_num = f"TermPointToGNB.(administrativeState,usedipAddress,operationalState,availabilityStatus,termpointtognbId==310410-000000{gnbid})"
    tpgnb_name = f"TermPointToGNB.(administrativeState,usedipAddress,operationalState,availabilityStatus,termpointtognbId=={gnodeb_name})"

    prechecks = []
    for cid in cell_ids:
        prechecks.append(f"cmedit get {site_list_1}  ExternalGUtranCell.(externalGUtranCellId==310410-000000{gnbid}-{cid}) -t")
    for cid in cell_ids:
        prechecks.append(f"cmedit get {site_list_1}  GUtranCellRelation.(gUtranCellRelationId==310410-000000{gnbid}-{cid}) -t")
    for cn in cell_names:
        prechecks.append(f"cmedit get {site_list_1}  NRCellRelation.(NRCellRelationId=={cn}) -t")
    for cn in cell_names:
        prechecks.append(f"cmedit get {site_list_1} externalnrcellcu.(externalnrcellcuid=={cn}) -t")
    prechecks.append(f"cmedit get {site_list_1} {tpgnb_num} -t")
    prechecks.append(f"cmedit get {site_list_1} {tpgnb_name} -t")
    if is_deletion:
        prechecks.append(f"cmedit get {site_list_1} {gnb_sector_discovery_command(gnbid).split('cmedit get ')[-1]}")

    set_delete = []
    set_delete.append(f"cmedit get {site_list_1} {tpgnb_num} -t")
    set_delete.append(f"cmedit get {site_list_1} {tpgnb_name} -t")
    set_delete.append(f"cmedit set {site_list_1} TermPointToGNB.(termpointtognbId==310410-000000{gnbid}) administrativestate=LOCKED")
    set_delete.append(f"cmedit set {site_list_1} TermPointToGNB.(termpointtognbId=={gnodeb_name}) administrativestate=LOCKED")
    for cid in cell_ids:
        set_delete.append(f"cmedit delete {site_list_1}  GUtranCellRelation.(gUtranCellRelationId==310410-000000{gnbid}-{cid}) --force -ALL")
    for cid in cell_ids:
        set_delete.append(f"cmedit delete {site_list_1}  ExternalGUtranCell.(externalGUtranCellId==310410-000000{gnbid}-{cid}) --force -ALL")
    for cn in cell_names:
        set_delete.append(f"cmedit delete {site_list_1}  NRCellRelation.(NRCellRelationId=={cn}) --force -ALL")
    for cn in cell_names:
        set_delete.append(f"cmedit delete {site_list_1} externalnrcellcu.(externalnrcellcuid=={cn}) --force -ALL")
    if is_deletion:
        set_delete.append(f"cmedit delete {site_list_1} TermPointToGNB.(termpointtognbId==310410-000000{gnbid}) --force -ALL")
        set_delete.append(f"cmedit delete {site_list_1} TermPointToGNB.(termpointtognbId=={gnodeb_name}) --force -ALL")
        set_delete.append(f"cmedit delete {site_list_1} ExternalGnodeBFunction.(gNodeBId=={gnbid}) --force -ALL")
    else:
        set_delete.append(f"cmedit set {site_list_1} TermPointToGNB.(termpointtognbId==310410-000000{gnbid}) administrativestate=UNLOCKED")
        set_delete.append(f"cmedit set {site_list_1} TermPointToGNB.(termpointtognbId=={gnodeb_name}) administrativestate=UNLOCKED")

    get_verify = []
    for cid in cell_ids:
        get_verify.append(f"cmedit get {site_list_1}  ExternalGUtranCell.(externalGUtranCellId==310410-000000{gnbid}-{cid}) -t")
    for cid in cell_ids:
        get_verify.append(f"cmedit get {site_list_1}  GUtranCellRelation.(gUtranCellRelationId==310410-000000{gnbid}-{cid}) -t")
    for cn in cell_names:
        get_verify.append(f"cmedit get {site_list_1}  NRCellRelation.(NRCellRelationId=={cn}) -t")
    for cn in cell_names:
        get_verify.append(f"cmedit get {site_list_1} externalnrcellcu.(externalnrcellcuid=={cn}) -t")
    get_verify.append(f"cmedit get {site_list_1} {tpgnb_num} -t")
    get_verify.append(f"cmedit get {site_list_1} {tpgnb_name} -t")
    if is_deletion:
        get_verify.append(f"cmedit get {site_list_1} ExternalGnodeBFunction.(gNodeBId=={gnbid}) -t")

    node_step3 = []
    if is_deletion:
        node_step3.append("# --- Step 3: ExternalGNBCUCPFunction cleanup (Site List 2) ---")
        node_step3.append(gnb_node_discovery_command(gnodeb_name, gnbid))
        node_step3.append(f"cmedit set {site_list_2} ExternalGNBCUCPFunction.(ExternalGNBCUCPFunctionid==auto310_410_3_{gnbid}),TermPointToGNodeB.(TermPointToGNodeBid==auto1) administrativestate:LOCKED --force")
        node_step3.append(f"cmedit set {site_list_2} ExternalGNBCUCPFunction.(ExternalGNBCUCPFunctionid=={delete_node_site_id}),TermPointToGNodeB.(TermPointToGNodeBid==auto1) administrativestate:LOCKED --force")
        node_step3.append(f"cmedit delete {site_list_2} ExternalGNBCUCPFunction.gnbid=={gnbid} --force -ALL")
        node_step3.append(gnb_node_discovery_command(gnodeb_name, gnbid))

    postchecks = []
    for cid in cell_ids:
        postchecks.append(f"cmedit get {site_list_1}  ExternalGUtranCell.(externalGUtranCellId==310410-000000{gnbid}-{cid}) -t")
    for cid in cell_ids:
        postchecks.append(f"cmedit get {site_list_1}  GUtranCellRelation.(gUtranCellRelationId==310410-000000{gnbid}-{cid}) -t")
    for cn in cell_names:
        postchecks.append(f"cmedit get {site_list_1}  NRCellRelation.(NRCellRelationId=={cn}) -t")
    for cn in cell_names:
        postchecks.append(f"cmedit get {site_list_1} externalnrcellcu.(externalnrcellcuid=={cn}) -t")
    postchecks.append(f"cmedit get {site_list_1} {tpgnb_num} -t")
    postchecks.append(f"cmedit get {site_list_1} {tpgnb_name} -t")
    if is_deletion:
        postchecks.append(gnb_node_discovery_command(gnodeb_name, gnbid))
        postchecks.append(gnb_sector_discovery_command(gnbid))
        postchecks.append(f"\ncmedit get {delete_node_site_id} ComConnectivityInformation.*")
        postchecks.append(f"cmedit get NetworkElement={delete_node_site_id},CmFunction=1")

    return {
        "prechecks_get": "\n".join(prechecks),
        "set_delete": "\n".join(set_delete),
        "get_verify": "\n".join(get_verify),
        "node_step3": "\n".join(node_step3),
        "postchecks_get": "\n".join(postchecks),
    }
