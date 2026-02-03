# Kafka-17507 Reproduction Suite

This project provides a deterministic reproduction environment for **KAFKA-17507**, a critical defect in Kafka Streams EOS v2 where **standby task state inconsistency** leads to duplicate, divergent records being committed downstream, violating Exactly-Once Semantics.

## 1. Problem Overview

### The Bug
In Kafka Streams (v3.5.1), when a **Standby Task** is promoted to **Active** during a rebalance (often triggered by network instability or timeouts), it may initialize its state store from a **local, non-transactional checkpoint file** that is stale compared to the transaction history.

This causes the task to "split brain":
1.  It resumes processing from a stale state.
2.  It generates new records based on this stale state.
3.  It successfully commits these records under a new Producer Epoch.
4.  **Result:** The sink topic contains divergent timelines (e.g., a counter regressing value), violating EOS.

### Trigger Conditions
1.  **Rebalancing**: Sequential startup or random failure of stream app instances.
2.  **Network Chaos**: Latency/Packet loss during the rebalance window to force unclean shutdowns or timeouts.
3.  **Standby Replicas**: `num.standby.replicas > 0` (The bug is specifically rooted in Standby Task promotion).

---

## 2. Documentation

*   [**BUG_DESCRIPTION.md**](./BUG_DESCRIPTION.md):  
    Detailed logs and evidence of the reproduction, including specific timestamps and duplicate records observed.
*   [**DIAGNOSIS.md**](./DIAGNOSIS.md):  
    Deep-dive technical root cause analysis (RCA), explaining the "Dirty Promotion" mechanism and the gap in EOS protection.

---

## 3. Reproduction Enviroment

*   **Kafka Cluster**: 3 Brokers (Confluent Platform 7.5.3 / Kafka 3.5.1).
*   **Stream App**: 3 Instances, configured with `processing.guarantee=exactly_once_v2` and `num.standby.replicas=2`.
*   **Chaos Engine**: Docker container capable of executing `tc` (Traffic Control) commands for network simulation.
*   **Validator**: Standalone consumer reading with `isolation.level=read_committed` to detect EOS violations.

---

## 4. How to Run

### Prerequisites
*   Docker Desktop (Recommended: 4+ CPUs, 8GB+ RAM).
*   ~10GB free disk space.

### 1. Execute Reproduction Script
The provided script orchestrates the entire lifecycle: building, starting infrastructure, injecting data, and running the reproduction cycles.

```bash
./scripts/reproduce.sh
```

### 2. What Happens (Structured Cycle)
The script runs a **Structured Progressive Startup Cycle** designed to reliably trigger the race condition:

1.  **Setup**: Starts Zookeeper, Brokers, Cassandra.
2.  **Inject Data**: Pre-loads 640,000 deterministic records.
3.  **Cycle Loop (Repeat 20 times)**:
    *   **Phase 1**: Start `stream-app-1` (Active on all partitions). Wait.
    *   **Phase 2**: Start `stream-app-2` while injecting **150ms delay + 10% packet loss** to a random broker. (Triggers unstable rebalance).
    *   **Phase 3**: Start `stream-app-3` with similar chaos.
    *   **Phase 4**: Wait for steady state.
    *   **Phase 5**: **Stop All Apps** (Simulate cluster restart/reset).
4.  **Validation**: A background `validator` service continuously checks for data regression. If found, the script exits with `BUG REPRODUCED`.

### 3. Check Results
If the bug is reproduced, logs will be dumped to a timestamped directory in `logs/`.

*   **Success**: You see `BUG REPRODUCED` in red text.
*   **Logs**: Check `validator.log` for details like:
    ```
    BUG REPRODUCED: INCONSISTENT WATERMARK REGRESSION (Read Committed)
    Key: key-XYZ, Last: 100, New: 95
    ```

---

## 5. Project Structure

*   `src/main/java/com/repro/StreamApp.java`: The victim application. Logic includes `Math.max()` state aggregation which makes regressions easy to spot.
*   `src/main/java/com/repro/Validator.java`: The detector. Enforces strict monotonicity on the output stream.
*   `scripts/reproduce.sh`: The orchestrator. Manages Docker Compose and executes chaos commands (`tc`).
*   `docker-compose.yml`: Defines the isolation environment.

---

## 6. Diagnosis & Fix
See [DIAGNOSIS.md](./DIAGNOSIS.md) for a full breakdown of the failure chain and suggested mitigations.