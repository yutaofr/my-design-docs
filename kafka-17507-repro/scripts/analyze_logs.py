#!/usr/bin/env python3
import sys
import re
from collections import defaultdict

# Regex patterns for parsing Kafka Coordinator Trace Logs
# Example: [2024-02-02 10:00:00,123] TRACE [Transaction Coordinator id=1] Transition from PrepareCommit to CompleteCommit for transactionalId eos-repro-group-0-2 (kafka.coordinator.transaction.TransactionStateManager)
TRANSITION_PATTERN = re.compile(r'Transition from (\w+) to (\w+) for transactionalId (\S+)')

# Example: [2024-02-02 10:00:01] ... ProducerId: 100, ProducerEpoch: 5 ...
EPOCH_PATTERN = re.compile(r'ProducerId: (\d+), ProducerEpoch: (\d+)')

def analyze(log_file):
    print(f"Analyzing {log_file} for Transaction Anomalies...")
    
    # State tracking: txn_id -> list of (timestamp, old_state, new_state)
    transitions = defaultdict(list)
    # Epoch tracking: txn_id -> list of (timestamp, pid, epoch)
    epochs = defaultdict(list)
    
    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            # Extract Timestamp (simple extraction)
            timestamp = line.split(']')[0].strip('[') if ']' in line else "Unknown"
            
            # 1. Capture State Transitions
            m_trans = TRANSITION_PATTERN.search(line)
            if m_trans:
                old_state, new_state, txn_id = m_trans.groups()
                transitions[txn_id].append({
                    'ts': timestamp,
                    'old': old_state,
                    'new': new_state
                })
            
            # 2. Capture Producer Epoch bumps (often in HandleAddPartitionsToTxn or InitProducerId)
            # This logic depends on specific log formats, relying on generic epoch patterns usually found in TRACE
            if "kafka.coordinator.transaction" in line and "ProducerEpoch" in line:
                m_epoch = EPOCH_PATTERN.search(line)
                if m_epoch:
                     # Heuristic: try to find txn_id in the same line
                    parts = line.split()
                    txn_id = None
                    for p in parts:
                        if "eos-repro-group" in p:
                            txn_id = p.strip(',')
                            break
                    
                    if txn_id:
                        pid, epoch = m_epoch.groups()
                        epochs[txn_id].append({
                            'ts': timestamp,
                            'pid': pid,
                            'epoch': int(epoch)
                        })

    print(f"\nFound {len(transitions)} active Transaction IDs.")
    
    # Analyze for Bugs
    anomalies_found = False
    
    for txn_id, history in transitions.items():
        # Check 1: Unfinished Transactions (PrepareCommit without CompleteCommit)
        # In a bug scenario, we might see PrepareCommit -> (Crash) -> PrepareCommit (with same epoch)
        # or PrepareCommit -> CompleteAbort (Unexpected rollback)
        
        last_state = history[-1]['new']
        if last_state in ['PrepareCommit', 'PrepareAbort']:
            print(f"\n[SUSPICIOUS] TxnId {txn_id} ended in hung state: {last_state}")
            anomalies_found = True
            
        # Check 2: State Regression or unexpected jumps
        # Iterate history to see if we have valid cycles: Empty -> Ongoing -> Prepare -> Complete -> Empty/Ongoing
        for i in range(len(history) - 1):
            current = history[i]
            next_op = history[i+1]
            
            # Logic: If we see PrepareCommit, next SHOULD be CompleteCommit.
            # If we see PrepareCommit -> PrepareCommit (without Complete), it implies a retry or a zombie state.
            if current['new'] == 'PrepareCommit' and next_op['new'] == 'PrepareCommit':
                print(f"\n[BUG CANDIDATE] TxnId {txn_id} repeated PrepareCommit without Completion!")
                print(f"  At {current['ts']}: {current['old']} -> {current['new']}")
                print(f"  At {next_op['ts']}: {next_op['old']} -> {next_op['new']}")
                anomalies_found = True

    # Check Epoch Monotonicity
    for txn_id, epoch_hist in epochs.items():
        sorted_epochs = sorted(epoch_hist, key=lambda x: x['epoch'])
        # Simple check: did we see duplicate epochs for different PIDs? (Unlikely but bad)
        seen = set()
        for e in sorted_epochs:
            key = (e['pid'], e['epoch'])
            if key in seen:
                # Duplicate log entries are normal, but let's just print the timeline
                pass
            seen.add(key)
            
    if not anomalies_found:
        print("\nNo obvious state machine violations found in this log chunk.")
        print("However, check Validator logs for 'Mismatched Watermark' which confirms the data inconsistency.")
    else:
        print("\n!!! POTENTIAL TRANSACTION COORDINATOR BUG DETECTED !!!")
        print("See detailed suspicious events above.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: analyze_logs.py <log_file>")
        sys.exit(1)
    analyze(sys.argv[1])
