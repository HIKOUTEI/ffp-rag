# 02 · 运行图快照归档

Status: done

Blocked by: 01

## 任务

每次同步 GTFS 时，把原始 `output_gtfs.zip` 连同 release tag 一起归档。

**动机**：GTFS 只有当前运行图。用户今天记录的行程，半年后车次可能改点或停运，
届时无法还原"他坐的那趟车当时是什么时刻"。从现在起归档，**未来**的记录可精确还原。
（已经过去的历史救不回来——这正是 spec 里"历史手填、不编造时刻"的原因。）

## 实现

- 归档到 `config.DATA_DIR/rail_snapshots/<release_tag>.zip`，约 1.6MB/份。
- 每条乘车记录存 `gtfs_version` 字段（见 issue 06），指向录入时所用的快照。
- 保留策略：全量保留。83MB/年，先不做清理。

## ⚠️ 未决：磁盘余量

部署机是 1.9G 内存那台（已在用 swap），**剩余磁盘空间未知**。
实现前先确认；若不足，改为归档到自建 GitHub fork 的 Release，`DATA_DIR` 只留最近 4 份。

同时按 ADR-0008 的兜底要求，**fork `wensimehrp/chinese-railway-gtfs` 建镜像**——
上游无 LICENSE 且作者刻意不公开数据获取方式，随时可能消失。

## 验收

- 同步后 `rail_snapshots/` 下出现以 release tag 命名的 zip，内容与上游一致。
- 同一 tag 重复同步不重复归档。
- 归档失败不影响同步主流程（同步本身要能完成）。

## Comments

### 2026-09-17 实现完成

归档逻辑在 `scripts/sync_gtfs.py:archive()`，随同步一起跑。
实测产出 `rail_snapshots/gtfs-20260913-040340.zip`；同 tag 重复同步直接返回不重复拷贝；
`archive()` 整体裹在 `try/except` 里，失败只打印警告——**归档不能拖垮同步本身**。

两项未决事项仍未办，不阻塞本 issue 但上线前要清：

1. **服务器磁盘余量**未确认（83MB/年）。
2. **上游 fork 未建**。脚本已把仓库做成环境变量 `GTFS_REPO`，
   届时改环境变量即可，代码不动。
