"""CRM 组织/人员同步解析规则测试（离线，不发请求）。

fixture 按 ``/hs/base/getDepartment`` 与 ``/hs/base/getPersonnel`` 的真实返回裁剪：
顶层节点是组织、下级是部门、部门 ``code`` 可能为 ``null``、一个人员可挂多个部门
（含审批分组）、``getPersonnel`` 里有 ``state`` 与工号重复的情况。
"""

from app.modules.crm.org_person import build_source_rows, node_code

DEPARTMENTS = [
    {
        "id": 13,
        "pid": 0,
        "name": "永锢",
        "code": None,
        "status": 1,
        "principal": 0,
        "memberCount": 0,
        "members": [],
        "children": [
            {
                "id": 14,
                "pid": 13,
                "name": "部门架构",
                "code": "BMJG",
                "status": 1,
                "members": [],
                "children": [
                    {
                        "id": 30,
                        "pid": 14,
                        "name": "财务部",
                        "code": None,
                        "status": 1,
                        "members": [
                            {
                                "id": 3,
                                "nickname": "谭玲玲",
                                "username": "tanlingling",
                                "number": "YG20002",
                                "mobile": "13822111222",
                                "state": 1,
                                "stateText": "在职",
                                "status": "normal",
                            }
                        ],
                        "children": [],
                    }
                ],
            }
        ],
    },
    {
        "id": 54,
        "pid": 0,
        "name": "审批分组",
        "code": "SPJG",
        "status": 1,
        "members": [],
        "children": [
            {
                "id": 57,
                "pid": 54,
                "name": "主管审批组",
                "code": "ZGSPZ",
                "status": 1,
                "members": [
                    {
                        "id": 3,
                        "nickname": "谭玲玲",
                        "username": "tanlingling",
                        "number": "YG20002",
                        "mobile": "",
                        "state": 1,
                        "stateText": "在职",
                        "status": "normal",
                    },
                    # 只在部门树出现、getPersonnel 未返回的成员
                    {
                        "id": 88,
                        "nickname": "仅部门可见",
                        "username": "deptonly",
                        "number": "YG20013",
                        "mobile": "",
                        "state": 1,
                        "stateText": "在职",
                        "status": "normal",
                    },
                ],
                "children": [],
            }
        ],
    },
]

PERSONNEL = [
    {
        "id": 3,
        "nickname": "谭玲玲",
        "username": "tanlingling",
        "number": "YG20002",
        "mobile": "13822111222",
        "email": "tanlingling@qq.com",
        "status": "normal",
        "state": "1",
        "hired_date": "2012-06-01",
        "dimission_date": None,
    },
    {
        "id": 1,
        "nickname": "超级管理员",
        "username": "admin",
        "number": "YG20036",
        "mobile": "",
        "email": "admin@admin.com",
        "status": "hidden",
        "state": "2",
        "hired_date": "2022-01-21",
        "dimission_date": "2025-09-11",
    },
    {
        "id": 999,
        "nickname": "无部门在职",
        "username": "nodept",
        "number": None,
        "mobile": "",
        "email": None,
        "status": "normal",
        "state": "1",
        "hired_date": None,
        "dimission_date": None,
    },
]


def _rows():
    return build_source_rows(DEPARTMENTS, PERSONNEL)


def test_node_code_falls_back_to_crm_id_when_code_empty():
    assert node_code({"id": 30, "code": None}) == "CRM30"
    assert node_code({"id": 14, "code": "BMJG"}) == "BMJG"


def test_top_nodes_become_source_orgs():
    orgs, _, _ = _rows()
    assert [(o.source_code, o.source_name, o.status) for o in orgs] == [
        ("CRM13", "永锢", 0),
        ("SPJG", "审批分组", 0),
    ]
    # raw_json 只留自身字段 + 人数，不带整棵树
    assert "children" not in orgs[0].raw_json and "members" not in orgs[0].raw_json
    assert orgs[0].raw_json["memberCount"] == 0


def test_children_become_source_depts_with_parent_codes():
    _, depts, _ = _rows()
    by_code = {d.source_code: d for d in depts}
    assert set(by_code) == {"BMJG", "CRM30", "ZGSPZ"}
    # 顶层节点的直接下级：属于该组织、没有上级部门
    assert (by_code["BMJG"].source_org_code, by_code["BMJG"].source_parent_code) == ("CRM13", None)
    # 部门 code 为空时用 CRM<ID> 兜底，上级部门编码用兜底值
    assert (by_code["CRM30"].source_name, by_code["CRM30"].source_parent_code) == ("财务部", "BMJG")
    # 审批分组树的下级部门归到来源组织 SPJG
    assert (by_code["ZGSPZ"].source_org_code, by_code["ZGSPZ"].source_parent_code) == ("SPJG", None)


def test_person_merges_detail_with_all_departments():
    _, _, persons = _rows()
    person = next(p for p in persons if p.source_code == "tanlingling")
    assert person.source_name == "谭玲玲"
    # 明细字段来自 getPersonnel
    assert person.mobile == "13822111222" and person.email == "tanlingling@qq.com"
    # 所属部门来自 getDepartment，可多个；source_org_code 取第一个
    assert person.source_org_code == "CRM13"
    assert [(d["org_code"], d["dept_code"]) for d in person.departments] == [
        ("CRM13", "CRM30"),
        ("SPJG", "ZGSPZ"),
    ]
    assert person.raw_json["employee_number"] == "YG20002"
    assert person.raw_json["departments"] == person.departments


def test_person_state_drives_source_status():
    _, _, persons = _rows()
    by_code = {p.source_code: p for p in persons}
    assert by_code["tanlingling"].status == 0  # state=1 在职 → 有效
    assert by_code["admin"].status == 1  # state=2 离职 → 停用
    assert by_code["admin"].raw_json["dimission_date"] == "2025-09-11"
    # 在职但未挂任何部门：不猜组织
    assert by_code["nodept"].status == 0 and by_code["nodept"].source_org_code is None
    assert by_code["nodept"].departments == []


def test_member_missing_from_personnel_is_still_synced():
    _, _, persons = _rows()
    fallback = next(p for p in persons if p.source_code == "deptonly")
    assert fallback.source_name == "仅部门可见"
    assert fallback.status == 0
    assert fallback.raw_json["employee_number"] == "YG20013"
    assert [d["dept_code"] for d in fallback.departments] == ["ZGSPZ"]


def test_source_codes_are_unique():
    orgs, depts, persons = _rows()
    assert len({o.source_code for o in orgs}) == len(orgs)
    assert len({(d.source_org_code, d.source_code) for d in depts}) == len(depts)
    assert len({p.source_code for p in persons}) == len(persons)
