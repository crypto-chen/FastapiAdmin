"""CRM 组织架构与人员接口解析。

数据源为 CRM 开放接口（``GET``、无需鉴权，统一返回
``{"code": 1, "msg": "", "time": ..., "data": ...}``）：

- ``/hs/base/getDepartment``：组织/部门树，节点字段
  ``id / pid / name / code / status / principal / principalName / memberCount /
  members / children``，``members`` 是节点下的人员精简信息
  （``id / nickname / username / number / mobile / ident / state / stateText / status``）。
- ``/hs/base/getPersonnel``：人员明细，字段
  ``id / nickname / username / number / mobile / email / status / state /
  hired_date / dimission_date``（``state=1`` 在职、``state=2`` 离职）。

这里只做**纯解析**（不碰数据库、不发请求），把两个接口拍平成来源表要用的三类行，
便于单测；落库逻辑在 ``scripts/sync_crm_personnel.py``。

编码约定：

- 顶层节点（``pid = 0``）视为**来源组织**（实测 4 棵树的根：永锢 / 审批分组 / 其它分组 / 消息抄送），
  其所有下级节点写入**来源部门**，``source_parent_code`` 指向上级部门编码。
- 部门编码可能为空（如「财务部」「人资部」），用 ``CRM<节点ID>`` 兜底保证唯一。
- 人员来源编码取 ``username``（CRM 工号有重复：``YG20013`` 同时对应两人），
  工号与所属部门保留在 ``raw_json`` 里。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.crm.client import CrmClient

DEPARTMENT_PATH = "/hs/base/getDepartment"
PERSONNEL_PATH = "/hs/base/getPersonnel"
CRM_SOURCE_TYPE = "crm"

# CRM 人员状态：state=1 在职、state=2 离职
STATE_ACTIVE = "1"


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _as_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


@dataclass(slots=True)
class CrmOrgRow:
    """来源组织行（顶层节点）。"""

    source_code: str
    source_name: str
    status: int
    raw_json: dict[str, Any]
    crm_id: int | None = None


@dataclass(slots=True)
class CrmDeptRow:
    """来源部门行。"""

    source_org_code: str
    source_code: str
    source_name: str
    source_parent_code: str | None
    status: int
    raw_json: dict[str, Any]
    crm_id: int | None = None


@dataclass(slots=True)
class CrmPersonRow:
    """来源人员行。"""

    source_code: str
    source_name: str
    source_org_code: str | None
    mobile: str | None
    email: str | None
    status: int
    raw_json: dict[str, Any]
    crm_id: int | None = None
    departments: list[dict[str, Any]] = field(default_factory=list)


def node_code(node: dict[str, Any]) -> str:
    """部门/组织编码；CRM 里可能为 ``null``，用 ``CRM<id>`` 兜底。"""
    code = _text(node.get("code"))
    if code:
        return code
    node_id = node.get("id")
    return f"CRM{node_id}" if node_id is not None else "CRM_UNKNOWN"


def _node_meta(node: dict[str, Any]) -> dict[str, Any]:
    """节点原始信息（去掉 children/members，只留自身字段与人数）。"""
    meta = {key: value for key, value in node.items() if key not in ("children", "members")}
    meta["memberCount"] = len(_as_list(node.get("members")))
    return meta


def _node_status(node: dict[str, Any]) -> int:
    """节点状态：CRM status=1 表示正常，映射为来源表 status=0（有效）。"""
    return 0 if _text(node.get("status")) == "1" else 1


async def fetch_departments(client: CrmClient) -> list[dict[str, Any]]:
    """拉取组织/部门树（``data`` 为顶层节点数组）。"""
    payload = await client.call(DEPARTMENT_PATH)
    return _as_list(payload.get("data"))


async def fetch_personnel(client: CrmClient) -> list[dict[str, Any]]:
    """拉取人员明细列表。"""
    payload = await client.call(PERSONNEL_PATH)
    return _as_list(payload.get("data"))


def build_source_rows(
    departments: list[dict[str, Any]],
    personnel: list[dict[str, Any]],
) -> tuple[list[CrmOrgRow], list[CrmDeptRow], list[CrmPersonRow]]:
    """把组织树 + 人员明细拍平成来源组织 / 来源部门 / 来源人员三类行。

    人员以 ``id`` 为键合并：``getPersonnel`` 提供明细字段，
    ``getDepartment`` 提供所属组织/部门（一个人可能挂在多个部门）。
    """

    orgs: list[CrmOrgRow] = []
    depts: list[CrmDeptRow] = []
    # 人员ID -> {"member": 节点里的成员精简信息, "departments": [组织/部门...]}
    member_index: dict[int, dict[str, Any]] = {}

    def collect_member(member: dict[str, Any], org_code: str, dept_code: str, dept_name: str) -> None:
        member_id = member.get("id")
        if member_id is None:
            return
        bucket = member_index.setdefault(int(member_id), {"member": member, "departments": []})
        bucket["member"] = member
        bucket["departments"].append({"org_code": org_code, "dept_code": dept_code, "dept_name": dept_name})

    def walk(node: dict[str, Any], org_code: str, parent_code: str | None) -> None:
        dept_code = node_code(node)
        dept_name = _text(node.get("name"))
        depts.append(
            CrmDeptRow(
                source_org_code=org_code,
                source_code=dept_code,
                source_name=dept_name,
                source_parent_code=parent_code,
                status=_node_status(node),
                raw_json=_node_meta(node),
                crm_id=node.get("id"),
            )
        )
        for member in _as_list(node.get("members")):
            collect_member(member, org_code, dept_code, dept_name)
        for child in _as_list(node.get("children")):
            walk(child, org_code, dept_code)

    for root in departments:
        org_code = node_code(root)
        orgs.append(
            CrmOrgRow(
                source_code=org_code,
                source_name=_text(root.get("name")),
                status=_node_status(root),
                raw_json=_node_meta(root),
                crm_id=root.get("id"),
            )
        )
        # 顶层节点的下级才是部门（顶层自身是组织，不作为部门）
        for child in _as_list(root.get("children")):
            walk(child, org_code, None)

    persons: list[CrmPersonRow] = []
    seen: set[str] = set()
    for item in personnel:
        person_id = item.get("id")
        username = _text(item.get("username"))
        source_code = username or (f"CRM{person_id}" if person_id is not None else "")
        if not source_code or source_code in seen:
            continue
        seen.add(source_code)
        info = member_index.get(int(person_id)) if person_id is not None else None
        departments = list(info["departments"]) if info else []
        persons.append(
            CrmPersonRow(
                source_code=source_code,
                source_name=_text(item.get("nickname")) or source_code,
                source_org_code=departments[0]["org_code"] if departments else None,
                mobile=_text(item.get("mobile")) or None,
                email=_text(item.get("email")) or None,
                status=0 if _text(item.get("state")) == STATE_ACTIVE else 1,
                raw_json={
                    **item,
                    "employee_number": _text(item.get("number")) or None,
                    "departments": departments,
                },
                crm_id=person_id,
                departments=departments,
            )
        )

    # 兜底：部门成员里出现、但 getPersonnel 未返回的人员
    for person_id, info in member_index.items():
        member = info["member"]
        username = _text(member.get("username"))
        source_code = username or _text(member.get("number")) or f"CRM{person_id}"
        if source_code in seen:
            continue
        seen.add(source_code)
        departments = list(info["departments"])
        persons.append(
            CrmPersonRow(
                source_code=source_code,
                source_name=_text(member.get("nickname")) or source_code,
                source_org_code=departments[0]["org_code"] if departments else None,
                mobile=_text(member.get("mobile")) or None,
                email=None,
                status=0 if _text(member.get("state")) == STATE_ACTIVE else 1,
                raw_json={
                    **member,
                    "employee_number": _text(member.get("number")) or None,
                    "departments": departments,
                },
                crm_id=person_id,
                departments=departments,
            )
        )

    return orgs, depts, persons
