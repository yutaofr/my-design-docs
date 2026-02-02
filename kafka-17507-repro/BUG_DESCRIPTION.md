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
num.standby.replicas = 1
session.timeout.ms = 6000
heartbeat.interval.ms = 2000
max.poll.interval.ms = 30000
max.poll.records = 1
transaction.timeout.ms = 5000
delivery.timeout.ms = 10000
request.timeout.ms = 5000
```

---

## Application Logic

The stream application maintains a watermark (maximum timestamp seen) per key in a RocksDB-backed state store with changelog enabled.

**Processing logic:**
```java
long currentWatermark = (storedWatermark == null) ? 0L : storedWatermark;
long newWatermark = Math.max(currentWatermark, recordTimestamp);
store.put(key, newWatermark);
// Output: "key" -> "newWatermark,status"
```

Under EOS semantics, for any given key, the watermark value in committed output should be monotonically non-decreasing.

---

## Downstream Validation

A validator consumer reads from the sink topic with `isolation.level=read_committed` and tracks the last seen watermark for each key. It flags an inconsistency if a newly consumed committed message contains a different watermark value than previously observed for the same key.

```java
props.put(ConsumerConfig.ISOLATION_LEVEL_CONFIG, "read_committed");
// ...
if (lastWatermark != null && newWatermark != lastWatermark) {
    log.error("BUG REPRODUCED: INCONSISTENT WATERMARK REGRESSION");
}
```

---

## Reproduction Steps

1. Start 3-broker Kafka cluster with Zookeeper
2. Create topics with 64 partitions, replication factor 3
3. Inject 640,000 messages (10,000 per partition) with monotonically increasing timestamps
4. Start validator consumer with `read_committed`
5. Start stream-app-1 (receives all 64 partitions)
6. Inject network chaos (150ms delay, 10% packet loss) to a random broker
7. Start stream-app-2 (triggers rebalance: 64 → 32+32)
8. Wait 20 seconds, clear network chaos
9. Repeat network chaos injection
10. Start stream-app-3 (triggers rebalance: 32+32 → ~21+21+22)
11. Perform kill/restart cycles on random stream-app instances with intermittent network chaos

**Network chaos injection:**
```bash
docker compose exec -u root $kafka_target tc qdisc add dev eth0 root netem delay 150ms 50ms loss 10%
```

---

## Observed Behavior

### Bug Reproduced At

**Timestamp:** 2026-02-02 19:41:34 UTC

### Validator Log Output

```
2026-02-02 19:41:34.511 [ERROR] [main] !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
2026-02-02 19:41:34.511 [ERROR] [main] BUG REPRODUCED: INCONSISTENT WATERMARK REGRESSION (Read Committed)
2026-02-02 19:41:34.511 [ERROR] [main] Key: key-15, Last: 1770060668748, New: 1770060668764, Offset: 1295, Partition: 19
2026-02-02 19:41:34.512 [ERROR] [main] !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
2026-02-02 19:41:34.512 [ERROR] [main] [StreamApp Signal] State store regression detected for key: key-15
2026-02-02 19:41:34.512 [ERROR] [main] !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
2026-02-02 19:41:34.512 [ERROR] [main] BUG REPRODUCED: INCONSISTENT WATERMARK REGRESSION (Read Committed)
2026-02-02 19:41:34.512 [ERROR] [main] Key: key-15, Last: 1770060668748, New: 1770060668764, Offset: 1296, Partition: 19
2026-02-02 19:41:34.512 [ERROR] [main] !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
```

### Observations

1. **Affected Key:** `key-15`
2. **Affected Partition:** 19
3. **Previous Committed Value:** `1770060668748`
4. **New Committed Value:** `1770060668764`
5. **Observed Offsets:** 1295, 1296 (consecutive)
6. **Consumer Isolation Level:** `read_committed`

### Validation Prior to Bug

```
2026-02-02 19:34:48.946 [INFO ] [main] Validated 1000 records. Bugs detected: 0
2026-02-02 19:36:41.850 [INFO ] [main] Validated 2000 records. Bugs detected: 0
2026-02-02 19:40:29.041 [INFO ] [main] Validated 3000 records. Bugs detected: 0
```

The first 3000+ records were validated without detecting any inconsistency. The bug was triggered after approximately 10 minutes of processing under chaos conditions.

---

## Expected vs Actual Behavior

| Aspect | Expected (EOS Guarantee) | Actual (Observed) |
|--------|--------------------------|-------------------|
| Watermark for key-15 | Monotonically non-decreasing | Changed from 1770060668748 to 1770060668764 |
| Committed record uniqueness | Each committed record for a key reflects consistent state | Multiple committed records for same key show different watermark values |
| Read-committed visibility | Only finalized, consistent data visible | Validator saw two different values for same logical state |

---

## Chaos Events Timeline

| Time | Event |
|------|-------|
| 19:31:07 | Validator started |
| 19:31:08 | Validator subscribed to sink-topic (64 partitions) |
| 19:34:48 | 1000 records validated, 0 bugs |
| 19:36:41 | 2000 records validated, 0 bugs |
| 19:40:08 | Node -1 disconnected (coordinator) |
| 19:40:29 | 3000 records validated, 0 bugs |
| **19:41:34** | **BUG REPRODUCED** |

---

## Files Attached

| File | Description |
|------|-------------|
| `validator.log` | Validator consumer output showing bug detection |
| `stream-app-1.log` | First stream app instance logs |
| `stream-app-2.log` | Second stream app instance logs |
| `stream-app-3.log` | Third stream app instance logs |
| `kafka-1.log` | Broker 1 logs |
| `kafka-2.log` | Broker 2 logs |
| `kafka-3.log` | Broker 3 logs |

---

## Reproduction Rate

In the test run documented here, the bug was reproduced after:
- ~10 minutes of processing
- Multiple rebalance cycles (3 stream app instances starting sequentially)
- Intermittent network chaos injection during rebalances

---

## Related

- JIRA: KAFKA-17507
