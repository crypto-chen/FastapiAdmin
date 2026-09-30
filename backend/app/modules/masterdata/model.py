from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import ModelMixin, UserMixin


class MasterOrgModel(ModelMixin, UserMixin):
    """内部标准组织树。"""

    __tablename__: str = "master_org"
    __table_args__: dict[str, str] = {"comment": "内部标准组织表"}
    __data_scope_exempt__: bool = True

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True, comment="组织编码")
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True, comment="组织名称")
    parent_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("master_org.id", ondelete="SET NULL", onupdate="CASCADE"),
        default=None,
        nullable=True,
        index=True,
        comment="上级组织ID",
    )
    order: Mapped[int] = mapped_column(Integer, default=999, nullable=False, index=True, comment="显示排序")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:启用 1:停用)")
    description: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="备注")

    parent: Mapped["MasterOrgModel | None"] = relationship(
        back_populates="children",
        remote_side="MasterOrgModel.id",
        foreign_keys=[parent_id],
        uselist=False,
    )
    children: Mapped[list["MasterOrgModel"]] = relationship(back_populates="parent", foreign_keys=[parent_id])


class MasterPersonModel(ModelMixin, UserMixin):
    """内部标准人员。"""

    __tablename__: str = "master_person"
    __table_args__: dict[str, str] = {"comment": "内部标准人员表"}
    __data_scope_exempt__: bool = True

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True, comment="人员编码")
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True, comment="人员姓名")
    org_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("master_org.id", ondelete="SET NULL", onupdate="CASCADE"),
        default=None,
        nullable=True,
        index=True,
        comment="所属组织ID",
    )
    mobile: Mapped[str | None] = mapped_column(String(32), default=None, nullable=True, index=True, comment="手机号")
    email: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, index=True, comment="邮箱")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:启用 1:停用)")
    description: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="备注")

    org: Mapped["MasterOrgModel | None"] = relationship(foreign_keys=[org_id])


class SourceOrgModel(ModelMixin, UserMixin):
    """外部来源组织。"""

    __tablename__: str = "source_org"
    __table_args__: tuple = (
        UniqueConstraint("source_type", "source_code", name="uq_source_org_type_code"),
        {"comment": "外部来源组织表"},
    )
    __data_scope_exempt__: bool = True

    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="来源类型(kingdee/crm/excel/other)")
    source_code: Mapped[str] = mapped_column(String(128), nullable=False, index=True, comment="来源组织编码")
    source_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="来源组织名称")
    source_parent_code: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, comment="来源上级编码")
    raw_json: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="原始数据")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:有效 1:停用)")


class SourcePersonModel(ModelMixin, UserMixin):
    """外部来源人员。"""

    __tablename__: str = "source_person"
    __table_args__: tuple = (
        UniqueConstraint("source_type", "source_code", name="uq_source_person_type_code"),
        {"comment": "外部来源人员表"},
    )
    __data_scope_exempt__: bool = True

    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="来源类型")
    source_code: Mapped[str] = mapped_column(String(128), nullable=False, index=True, comment="来源人员编码")
    source_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="来源人员姓名")
    source_org_code: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, comment="来源组织编码")
    mobile: Mapped[str | None] = mapped_column(String(32), default=None, nullable=True, index=True, comment="手机号")
    email: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, index=True, comment="邮箱")
    raw_json: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="原始数据")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:有效 1:停用)")


class OrgMappingModel(ModelMixin, UserMixin):
    """来源组织 → 内部标准组织映射。"""

    __tablename__: str = "master_org_mapping"
    __table_args__: dict[str, str] = {"comment": "来源组织映射表"}
    __data_scope_exempt__: bool = True

    source_org_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("source_org.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="来源组织ID",
    )
    master_org_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("master_org.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="内部标准组织ID",
    )
    match_mode: Mapped[str] = mapped_column(String(16), default="manual", nullable=False, comment="匹配方式(exact/fuzzy/manual)")
    confidence: Mapped[int] = mapped_column(Integer, default=100, nullable=False, comment="匹配置信度(0-100)")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:有效 1:失效)")


class PersonMappingModel(ModelMixin, UserMixin):
    """来源人员 → 内部标准人员映射。"""

    __tablename__: str = "master_person_mapping"
    __table_args__: dict[str, str] = {"comment": "来源人员映射表"}
    __data_scope_exempt__: bool = True

    source_person_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("source_person.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="来源人员ID",
    )
    master_person_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("master_person.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="内部标准人员ID",
    )
    match_mode: Mapped[str] = mapped_column(String(16), default="manual", nullable=False, comment="匹配方式(exact/fuzzy/manual)")
    confidence: Mapped[int] = mapped_column(Integer, default=100, nullable=False, comment="匹配置信度(0-100)")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:有效 1:失效)")


class MasterDeptModel(ModelMixin, UserMixin):
    """内部标准部门（组织内独立，编码按组织唯一）。"""

    __tablename__: str = "master_dept"
    __table_args__: tuple = (
        UniqueConstraint("org_id", "code", name="uq_master_dept_org_code"),
        {"comment": "内部标准部门表"},
    )
    __data_scope_exempt__: bool = True

    org_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("master_org.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="所属法人/公司ID",
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="组织内部门编码")
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True, comment="部门名称")
    parent_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("master_dept.id", ondelete="SET NULL", onupdate="CASCADE"),
        default=None,
        nullable=True,
        index=True,
        comment="上级部门ID",
    )
    order: Mapped[int] = mapped_column(Integer, default=999, nullable=False, index=True, comment="显示排序")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:启用 1:停用)")
    description: Mapped[str | None] = mapped_column(Text, default=None, nullable=True, comment="备注")

    org: Mapped["MasterOrgModel | None"] = relationship(foreign_keys=[org_id])
    parent: Mapped["MasterDeptModel | None"] = relationship(
        back_populates="children",
        remote_side="MasterDeptModel.id",
        foreign_keys=[parent_id],
        uselist=False,
    )
    children: Mapped[list["MasterDeptModel"]] = relationship(back_populates="parent", foreign_keys=[parent_id])


class MasterPersonOrgModel(ModelMixin, UserMixin):
    """共享人员与组织/部门的关系表。"""

    __tablename__: str = "master_person_org"
    __table_args__: tuple = (
        UniqueConstraint("person_id", "org_id", "dept_id", name="uq_master_person_org"),
        {"comment": "人员组织部门关系表"},
    )
    __data_scope_exempt__: bool = True

    person_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("master_person.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="共享人员ID",
    )
    org_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("master_org.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="法人/公司ID",
    )
    dept_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("master_dept.id", ondelete="CASCADE", onupdate="CASCADE"),
        default=None,
        nullable=True,
        index=True,
        comment="部门ID",
    )
    is_primary: Mapped[bool] = mapped_column(default=False, nullable=False, comment="是否主任岗")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:有效 1:失效)")


class SourceDeptModel(ModelMixin, UserMixin):
    """来源部门（组织内独立）。"""

    __tablename__: str = "source_dept"
    __table_args__: tuple = (
        UniqueConstraint("source_type", "source_org_code", "source_code", name="uq_source_dept"),
        {"comment": "来源部门表"},
    )
    __data_scope_exempt__: bool = True

    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="来源类型")
    source_org_code: Mapped[str] = mapped_column(String(128), nullable=False, index=True, comment="来源组织编码")
    source_code: Mapped[str] = mapped_column(String(128), nullable=False, index=True, comment="来源部门编码")
    source_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="来源部门名称")
    source_parent_code: Mapped[str | None] = mapped_column(String(128), default=None, nullable=True, comment="来源上级编码")
    raw_json: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True, comment="原始数据")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:有效 1:停用)")


class MasterDeptMappingModel(ModelMixin, UserMixin):
    """来源部门 → 内部标准部门映射。"""

    __tablename__: str = "master_dept_mapping"
    __table_args__: dict[str, str] = {"comment": "来源部门映射表"}
    __data_scope_exempt__: bool = True

    source_dept_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("source_dept.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="来源部门ID",
    )
    master_dept_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("master_dept.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="内部标准部门ID",
    )
    match_mode: Mapped[str] = mapped_column(String(16), default="manual", nullable=False, comment="匹配方式(exact/fuzzy/manual)")
    confidence: Mapped[int] = mapped_column(Integer, default=100, nullable=False, comment="匹配置信度(0-100)")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:有效 1:失效)")


class SysDeptBusinessMappingModel(ModelMixin, UserMixin):
    """系统权限部门(sys_dept) ↔ 业务标准部门(master_dept)绑定。"""

    __tablename__: str = "sys_dept_business_mapping"
    __table_args__: tuple = (
        UniqueConstraint("sys_dept_id", "master_dept_id", name="uq_sys_dept_business_mapping"),
        {"comment": "权限部门与业务标准部门绑定表"},
    )
    __data_scope_exempt__: bool = True

    sys_dept_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sys_dept.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="系统权限部门ID",
    )
    master_dept_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("master_dept.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
        index=True,
        comment="业务标准部门ID",
    )
    match_mode: Mapped[str] = mapped_column(String(16), default="manual", nullable=False, comment="绑定方式")
    confidence: Mapped[int] = mapped_column(Integer, default=100, nullable=False, comment="置信度")
    status: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="状态(0:有效 1:失效)")
