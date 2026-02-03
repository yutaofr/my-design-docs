# Kafka Streams EOS v2 Inconsistency Bug - Observed Behavior

## Summary

A Kafka Streams application configured with `exactly_once_v2` processing guarantee produces inconsistent output values for the same key when observed by a downstream consumer using `read_committed` isolation level.

---

## Environment

| Component | Version / Configuration |
|-----------|------------------------|
| Kafka Brokers | Confluent Platform 7.5.3 (Kafka 3.5.1) |
| Kafka Streams Client | 3.5.1 |
| Processing Guarantee | `exactly_once_v2` |
| Broker Count | 3 |
| Stream App Instances | 3 |
| Topic Partitions | 64 |
| Replication Factor | 3 |
| `min.insync.replicas` | 2 |
| `transaction.state.log.replication.factor` | 3 |
| `transaction.state.log.min.isr` | 2 |
| `num.standby.replicas` | 1 |

### Streams Application Configuration

```properties
processing.guarantee = exactly_once_v2
commit.interval.ms = 100
num.stream.threads = 2
num.standby.replicas = 2
session.timeout.ms = 10000
heartbeat.interval.ms = 3000
max.poll.interval.ms = 30000
max.poll.records = 100
transaction.timeout.ms = 5000
delivery.timeout.ms = 30000
request.timeout.ms = 15000
replication.factor = 3
acks = all
```

---

## Application Logic

The stream application maintains a watermark (maximum timestamp seen) **per partition** in a local state store (`KeyValueStore<Integer, Long>`) with changelog enabled.

**Processing logic:**
```java
// Logic: newWatermark = max(stored_watermark, current_record_timestamp)
long currentWatermark = (storedWatermark == null) ? 0L : storedWatermark;
long newWatermark = Math.max(currentWatermark, recordTimestamp);
store.put(recordPartition, newWatermark); // Key is partition ID (Integer)
```

The application emits a record `(key, value)` where `value` contains the `newWatermark`. The input keys are unique per message (e.g., `key-0-1`, `key-0-2`).

Under EOS semantics, a specific input source record should result in exactly one unique committed output record.

---

## Downstream Validation

A validator consumer reads from the sink topic with `isolation.level=read_committed` and tracks the watermark seen for each unique key. Since input keys are unique, each key should appear exactly once in the committed output.

The validator flags an error if it observes the same key more than once with a different watermark, indicating inconsistent processing or duplicate delivery of what should be a unique EOS result.

```java
if (lastWatermark != null && newWatermark != lastWatermark) {
    log.error("BUG REPRODUCED: INCONSISTENT WATERMARK REGRESSION");
}
```

---

## Reproduction Steps

1. Start 3-broker Kafka cluster with Zookeeper and 3 Cassandra nodes.
2. Create topics with 64 partitions, replication factor 3.
3. Inject 640,000 messages (64 partitions x 10,000 messages).
4. Start validator consumer with `read_committed`.
5. **Run Structured Progressive Startup Cycles:**
    - **Cycle Start:** Stop all stream app instances.
    - **Start Stream-App-1**: Wait 30s.
    - **Start Stream-App-2**: Inject network chaos (150ms delay, 10% loss) -> Start -> Wait 30s -> Remove chaos.
    - **Start Stream-App-3**: Inject network chaos (150ms delay, 10% loss) -> Start -> Wait 30s -> Remove chaos.
    - **Steady State**: Wait 60s.
    - **Stop All**: Stop all instances to reset for the next cycle.
6. The bug typically reproduces during the progressive startup phase when rebalancing occurs under network stress.

---

## Observed Behavior

### Bug Reproduced At

**Timestamp:** 2026-02-03 15:55:26 UTC

### Validator Log Output

```
2026-02-03 15:55:26.322 [ERROR] [main] !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
2026-02-03 15:55:26.322 [ERROR] [main] BUG REPRODUCED: INCONSISTENT WATERMARK REGRESSION (Read Committed)
2026-02-03 15:55:26.322 [ERROR] [main] Key: key-13-5576, Last: 1770133226383, New: 1770133226403, Offset: 2842, Partition: 42
2026-02-03 15:55:26.322 [ERROR] [main] !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
2026-02-03 15:55:26.322 [ERROR] [main] !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
2026-02-03 15:55:26.322 [ERROR] [main] BUG REPRODUCED: INCONSISTENT WATERMARK REGRESSION (Read Committed)
2026-02-03 15:55:26.322 [ERROR] [main] Key: key-13-5695, Last: 1770133226383, New: 1770133226403, Offset: 2843, Partition: 42
```

### Observations

1. **Affected Key:** `key-13-5576` (and others in rapid succession)
2. **Failure Pattern:** The validator received a second committed record for the same unique key.
3. **Values:**
    - First committed value: `1770133226383`
    - Second committed value: `1770133226403`
4. **Offsets:** `2842` (for the duplicate?) - Note: The log snippet shows offsets close together for different keys, indicating a batch of duplicate processing.
5. **Context:** The error occurred during a rebalance/chaos injection phase, causing the stream thread to likely retry processing and commit a duplicate result that should have been fenced or deduplicated by EOS limits.

---

## Files Attached

| File | Description |
|------|-------------|
| `validator.log` | Validator consumer output showing bug detection |
| `stream-app-{1,2,3}.log` | Stream application instance logs |
| `kafka-{1,2,3}.log` | Broker logs |

---

## Related

- JIRA: KAFKA-17507
