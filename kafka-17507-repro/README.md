# Kafka-17507 复现环境 (Reproduction Stack)

本项目旨在复现 Kafka Streams 在 Exactly-Once (EOS v2) 语义下，由于**Offset 批次重复处置 (Re-processing)** 与 **State Store 状态不一致** 共同作用导致的严重 Bug (Kafka-17507)。

## 1. 核心问题与目的 (Problem & Purpose)

### Bug 定义
在生产环境中，当 Kafka Streams 任务遭遇崩溃或网络分区导致 Rebalance 时，未提交成功的 Offset 批次会被新的流线程接管并重新处理（Re-process）。
**正常预期**：State Store 应该准确恢复到该批次处理前的状态（Snapshot），确保重新处理的结果与初次处理完全一致（确定性）。
**实际 Bug**：在特定故障场景下，State Store 从 Changelog 恢复的状态与当前 Offset 不匹配（通常是回退到了更旧的版本，或者保留了部分未提交的脏数据）。导致重新处理逻辑基于错误的 State 计算，产生了与之前不同的输出（例如 Watermark 回退），破坏了 EOS 语义。

### 关键触发条件
1.  **重复处置 (Re-processing)**: 必须发生事务提交超时或失败，导致同一批 Offset 被再次消费。
2.  **状态不一致 (State Inconsistency)**: 本地 RocksDB/Checkpoint 与 Kafka Changelog Topic 之间的同步机制在异常关闭时出现由于 Flush 顺序或日志截断逻辑导致的偏差。

---

## 2. 根本原因分析 (Root Cause Analysis)

### 故障链推演
1.  **Phase 1: 正常处理**
    *   Stream App 消费 Offset `N` 到 `N+5`。
    *   更新本地 State Store (RocksDB)。
    *   准备提交事务 (Commit Transaction)。

2.  **Phase 2: 故障发生**
    *   **触发点**: Broker 网络分区或 Fencing Zombie 导致 Commit 请求超时/失败。
    *   **结果**: Kafka 事务协调器 Abort 事务。该批次 Offset `N` 未被标记为 Committed。

3.  **Phase 3: 恢复与重复处置 (The Bug)**
    *   Stream App 重启或 Rebalance，重新从 Offset `N` 开始消费。
    *   **预期**: State Store 应回滚/恢复到 Offset `N` 之前的状态。
    *   **实际**: 由于 Bug (如本地 Checkpoint 文件损坏或 Changelog 截断逻辑缺陷)，State Store 恢复到了 Offset `N-k` (更早的状态)。
    *   **计算错误**: 代码逻辑 `NewVal = Max(StoreVal, RecordVal)`。由于 `StoreVal` 变小了，计算出的 `NewVal` 可能比 Phase 1 中计算出的值小。
    *   **下游影响**: 下游消费者（Validator）先收到了 Phase 1 的结果（虽然事务 Abort 了，但在 `read_uncommitted` 或特定可见性下可能已泄露，或者 Validator 验证的是最终一致性），随后收到了 Phase 2 较小的结果，判定为 **Watermark 回退**。

---

## 3. 验证方案 (Verification Plan)

本环境包含针对性的测试用例，覆盖正常与异常边界。

| 测试用例 ID | 场景描述 | 故障注入手段 | 预期结果 | 验证逻辑 |
| :--- | :--- | :--- | :--- | :--- |
| **TC-01** | **正常流处理** | 无 | Watermark 单调递增 | Validator 无报错 |
| **TC-02** | **进程硬崩溃 (Crash Loop)** | `kill -9` Stream App | 状态自动恢复，无数据丢失 | Validator 检测到重复但一致的数据 |
| **TC-03** | **网络分区导致超时** | `tc` 注入 5% 丢包 + 100ms 延迟 | 触发事务超时与 Retry | **复现目标**: Validator 发现 Key 的 Watermark 值变小 (Regression) |
| **TC-04** | **脑裂模拟 (Zombie Fencing)** | 隔离 Zookeeper/Broker 通信 | 触发 Fencing | 新旧实例切换期间数据一致 |

---

## 4. 复现步骤 (Reproduction Steps)

### 环境准备
*   Docker Desktop (建议 4 CPUs, 8GB RAM)
*   本地磁盘空间 > 10GB (用于容纳 Kafka Logs 和 Core Dumps)

### 启动流程
运行自动化编排脚本：

```bash
./scripts/reproduce.sh
```

### 脚本执行逻辑
1.  **基础设施启动**: 启动 3 Broker Kafka 集群 (携带 `NET_ADMIN` 权限) + Cassandra。
2.  **网络环境初始化**: 自动安装 `iproute-tc` 并清理残留规则。
3.  **基准数据注入**: `Injector` 产生 6400 条确定性数据。
4.  **混沌循环 (Chaos Loop)**:
    *   **Step 1**: 随机 SIGKILL 一个 Stream App 实例。
    *   **Step 2**: 在 Rebalance 窗口期，向随机 Broker 注入网络故障（模拟 commit 请求无法 ack）。
    *   **Step 3**: 重启 Stream App，强制触发 State Restore 流程。
    *   **Step 4**: `Validator` 实时监控 Sink Topic。

### 结果判定
*   **成功复现**: 脚本输出红色 `BUG REPRODUCED` 信息，并自动 Dump 现场日志。
*   **未复现**: 脚本运行 50 次迭代后正常退出。

---

## 5. 代码结构与核心模块

*   **`src/main/java/com/repro/StreamApp.java`**:
    *   实现核心业务逻辑。
    *   **关键点**: 使用 `processing.guarantee="exactly_once_v2"`。
    *   **State Logic**: 包含易受状态回退影响的聚合逻辑 (`Math.max`).
*   **`src/main/java/com/repro/Validator.java`**:
    *   使用 `read_committed` 隔离级别消费。
    *   维护内存 Map 记录每个 Key 见过的最大 Watermark。一旦发现新值 < 旧值，立即报警。
*   **`docker-compose.yml`**:
    *   定义 `NET_ADMIN` 权限，允许容器内执行 `tc` 命令。
    *   配置 `x-logging` 防止日志爆盘。

---

## 6. 贡献指南

*   **Reporting**: 如果发现新的复现变种，请提交 Issue 并附带 `kafka-*.log`。
*   **Improvements**: 欢迎提交 PR 优化 `reproduce.sh` 的故障注入策略（例如更精细的 Packet Corruption）。