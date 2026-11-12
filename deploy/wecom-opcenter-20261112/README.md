# 企微打卡同步 + 运营中心工时指标（2026-11-12）

## 变更

- 新增企业微信通讯录 / 打卡同步模块：`backend/app/modules/erp/wecom/`
- 新增迁移：`wecomsync01`（企微打卡表）、`wecomtoken01`（连接增加 token_url）
- 新增运营中心主表指标：
  - `TM-01` 正常工作时间（小时）
  - `TM-02` 加班时间（小时）
- 指标范围：企微部门 `14`（品类与流量部）及下级 `107/34/35`；在职人员，默认排除 `by` 备用账号
- 外部对接文档已更新到 v1.1：`docs/运营中心主表指标外部对接说明.md`

## 服务器 dev 更新

先进入项目 conda 环境，在项目根目录执行。默认只预演，不执行任何命令：

```bash
python deploy/wecom-opcenter-20261112/update.py
```

确认无误后执行：

```bash
python deploy/wecom-opcenter-20261112/update.py --apply --env dev --service fastapiadmin
```

脚本顺序：

1. `git fetch origin master` + `git merge --ff-only origin/master`
2. `python main.py upgrade --env=dev`（应用 `wecomsync01`、`wecomtoken01`）
3. 写入/更新企微连接（仅当提供 `WECOM_TOKEN_URL` 或 `--token-url`）
4. `python scripts/seed_opcenter_worktime_metrics.py`
5. `python scripts/recalc_metrics_batch.py --period 2026-09/10/11`
6. `systemctl restart fastapiadmin`（指定 `--service` 时）

## 企微连接

如果服务器数据库里已经有企微连接，可跳过第 3 步，直接沿用：

```bash
python deploy/wecom-opcenter-20261112/update.py --apply --env dev --skip-token --service fastapiadmin
```

如果是全新环境，先设置 Token 服务地址（含密钥，不要提交到 Git）：

```bash
export WECOM_TOKEN_URL='http://crm.yonggubox.com/qywechat/yg_technology_app/getAccessTokens/key/...'
python deploy/wecom-opcenter-20261112/update.py --apply --env dev --service fastapiadmin
```

## 校验

```bash
# 项目根目录；按指标编码查找并重算/打印结果
python deploy/wecom-opcenter-20261112/verify.py --period 2026-10
```

预期 2026-10：

- `TM-01 = 1225.5` 小时
- `TM-02 = 12.59` 小时

页面：指标中心 → 运营中心指标 → 运营中心主表指标，选 `2026-09` / `2026-10`。

## 回滚

代码回滚：

```bash
git log --oneline -5
git revert <本次上线提交>
```

数据库迁移默认不回滚（新增表/列对旧代码无影响）。确需回滚时：

```bash
# 在 backend 目录；会删除 token_url 列，再删除三张企微同步表
python main.py upgrade --env=dev   # 先确认当前 head
python -m alembic downgrade -1
python -m alembic downgrade -1
```

指标定义 `TM-01`/`TM-02` 如不再使用，可按需删除：

```sql
DELETE FROM metric_def WHERE code IN ('TM-01', 'TM-02');
```
