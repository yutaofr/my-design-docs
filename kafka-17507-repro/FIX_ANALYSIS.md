# Fix Analysis: KAFKA-17507 / KAFKA-18943

## Issue Summary
The reproduction suite successfully demonstrated an **EOS (Exactly-Once Semantics) Violation** where duplicate records were committed to the output topic. The behavior corresponds to **Dirty Promotion**, where a record is re-processed using "future" state.

## Identified Fix
**[KAFKA-18943] Kafka Streams incorrectly commits TX during task revocation**
- **Version Fixed:** Apache Kafka 3.9.1 (Confluent Platform 7.9.1-ccs).

## Root Cause Mechanism: "Fetch Replay + Persistent Dirty State"

The duplication is caused by a race condition where the client re-processes data (Replay) while inheriting invalid/uncommitted local state (Persistent Dirty State).

### The Sequence of Events (Derived from Logs)

1.  **The "Phantom" Commit (Message 1 - Val 383):**
    -   `stream-app-1` (Producer 1009) processed the batch containing Message 383 (Offset ~2842).
    -   **Broker Log Evidence:** The transaction for `sink-topic-42` was **ABORTED** at `15:52:23` due to timeout (`PrepareAbort` -> `CompleteAbort`).
    -   **The Bug:** Despite the **ABORT**, the Data (383) became **visible** to downstream consumers (`read_committed`).
    -   **The Offset Failure:** Because of the Abort, the **Consumer Group Offset** correctly rolled back (or never advanced) and stayed at **2059** (the last successful commit by Producer 6 at 15:50:54).

2.  **The Trigger (Rebalance & Fetch Replay):**
    -   `stream-app-2` took ownership.
    -   It fetched checking the broker's offset.
    -   Result: Broker returned **2059** (because the 15:52 transaction aborted).
    -   `stream-app-2` fetched from 2059, re-processing the batch containing 383. **(The Replay)**

3.  **The Dirty State (State Leak):**
    -   `stream-app-2` (using Sticky Assignment) reused the local state directory.
    -   The local RocksDB store *still contained* the updates from the "Phantom" transaction (Value 403). It was not rolled back.

4.  **The Zombie Commit (Message 2 - Val 403):**
    -   `stream-app-2` re-processed the "Replayed" record (383) against the "Future" state (403).
    -   Result: `max(stored_403, input_383) = 403`. **(Dirty Promotion)**
    -   KAFKA-18943 allows this "Zombie" transaction to be committed, creating the duplicate.

## Conclusion
The logs provide definitive proof:
-   **Broker:** `stream-app-1` Transaction **ABORTED** (explaining why offset didn't advance).
-   **Validator:** Data **VISIBLE** (proving atomicity violation/leak).
-   **Client:** **REPLAY** from old offset + **DIRTY STATE** (creating duplicated/corrupt data).

KAFKA-18943 fixes this by ensuring strict fencing and task closure, preventing the "Leaky Abort" and ensuring atomic Commit/Abort behavior during revocation.

## Recommendation
Upgrade to **Confluent Platform 7.9.1-ccs** (Kafka 3.9.1) or later.
