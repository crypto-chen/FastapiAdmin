# 同步任务 / 指标批次每日三次排期

## 变更

- 同步任务：保留各任务原有凌晨时点，追加 `12:20`、`18:20`。
- 指标批次：`02:30`、`12:20`、`18:20`。
- 日间指标轮次：先等待同步完成，再重建订单全链路 / 客户分析，最后计算指标。
- 月结：只在凌晨轮次执行，中午/晚上不重复结转。

## 服务器执行

在 `backend/` 目录、已激活的 conda 环境内执行。

先预演：

```bash
python scripts/apply_three_times_schedule.py
```

确认后写入数据库：

```bash
python scripts/apply_three_times_schedule.py --apply
```

如果后端以 Windows 服务运行，可同时重启：

```bash
python scripts/apply_three_times_schedule.py --apply --restart-service fastapiadmin
```

Linux systemd 同样使用 `--restart-service`，脚本会自动调用 `systemctl restart`。

## 校验

```bash
python scripts/apply_three_times_schedule.py --apply
```

正常输出应包含：

```text
指标批次时间: 02:30, 12:20, 18:20
数据库校验通过：所有启用且已配置 Cron 的同步任务均为每日三次
```

## 回滚

执行 `--apply` 前先备份 `meta_sync_job` 表。需要回滚时：

1. `git revert <本次提交 SHA>` 恢复旧版代码。
2. 用备份恢复 `meta_sync_job.cron_expr`（旧版代码只支持单条 Cron）。
3. 重启后端，确认旧排期重新注册。
