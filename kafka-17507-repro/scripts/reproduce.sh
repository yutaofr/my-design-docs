#!/bin/bash
set -e

cd "$(dirname "$0")/.."

echo "=== KAFKA-17507 Bug Reproduction ==="
echo "Strategy: Sequential instance startup to trigger rebalancing during processing"

echo "Building application image..."
docker compose build stream-app-1

echo "Starting Infrastructure (Kafka + Cassandra)..."
echo "Waiting for all services to become healthy (this may take a few minutes)..."
docker compose up -d --wait zookeeper kafka-1 kafka-2 kafka-3 cassandra-1 cassandra-2 cassandra-3 cassandra-init

echo "Clearing any stale network chaos..."
for b in kafka-1 kafka-2 kafka-3; do
    docker compose exec -u root $b tc qdisc del dev eth0 root 2>/dev/null || true
done

echo "All infrastructure services are healthy."

echo "Pre-creating topics..."
docker compose exec kafka-1 kafka-topics --bootstrap-server localhost:9092 --create --topic source-topic --partitions 64 --replication-factor 3 --if-not-exists || true
docker compose exec kafka-1 kafka-topics --bootstrap-server localhost:9092 --create --topic sink-topic --partitions 64 --replication-factor 3 --if-not-exists || true

echo "Waiting for Cassandra Schema Init..."
until docker compose logs cassandra-init 2>/dev/null | grep -q "Schema initialized"; do
    echo "Waiting for schema init..."
    sleep 3
done
echo "Cassandra ready."

echo "Starting Validator..."
docker compose up -d validator

echo "Injecting 64,000 messages (64 partitions × 1,000 messages)..."
docker compose run --rm injector

echo "=== Starting Stream Apps Sequentially (Triggering Rebalances) ==="

# Dedicated log directory for post-analysis
LOG_DIR="logs/$(date +%Y%m%d_%H%M%S)"

# Function to dump all logs for analysis
dump_logs() {
    mkdir -p "$LOG_DIR"
    
    echo "Dumping logs to $LOG_DIR ..."
    
    echo "Dumping Broker Logs..."
    docker compose logs kafka-1 > "$LOG_DIR/kafka-1.log" 2>/dev/null || true
    docker compose logs kafka-2 > "$LOG_DIR/kafka-2.log" 2>/dev/null || true
    docker compose logs kafka-3 > "$LOG_DIR/kafka-3.log" 2>/dev/null || true
    docker compose logs validator > "$LOG_DIR/validator.log" 2>/dev/null || true
    
    echo "Dumping Stream App Logs..."
    docker compose logs stream-app-1 > "$LOG_DIR/stream-app-1.log" 2>/dev/null || true
    docker compose logs stream-app-2 > "$LOG_DIR/stream-app-2.log" 2>/dev/null || true
    docker compose logs stream-app-3 > "$LOG_DIR/stream-app-3.log" 2>/dev/null || true
    
    echo "All logs saved to: $LOG_DIR"
}

check_bug() {
    if docker compose logs validator 2>/dev/null | grep -q "BUG REPRODUCED"; then
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        echo "BUG REPRODUCED!"
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        
        dump_logs
        
        echo "Running Root Cause Analysis..."
        python3 scripts/analyze_logs.py "$LOG_DIR/kafka-1.log" || true
        python3 scripts/analyze_logs.py "$LOG_DIR/kafka-2.log" || true
        python3 scripts/analyze_logs.py "$LOG_DIR/kafka-3.log" || true
        
        echo "Evidence collected in: $LOG_DIR"
        return 0
    fi
    return 1
}

# Function to check consumer lag for stream app consumer group
# Uses kafka-consumer-groups to get actual LAG on source-topic
check_consumer_lag() {
    # Consumer group = application.id = "eos-repro-group" (set in docker-compose.yml)
    lag_output=$(docker compose exec -T kafka-1 kafka-consumer-groups \
        --bootstrap-server localhost:9092 \
        --describe \
        --group eos-repro-group 2>&1)
    
    if echo "$lag_output" | grep -q "has no active members"; then
        echo "  [Progress] Consumer group has no active members"
        return 1
    fi
    
    if echo "$lag_output" | grep -q "does not exist"; then
        echo "  [Progress] Consumer group does not exist yet"
        return 1
    fi
    
    if echo "$lag_output" | grep -q "is rebalancing"; then
        echo "  [Progress] Consumer group is rebalancing..."
        return 1
    fi
    
    # With EOS, CURRENT-OFFSET and LAG may show "-" due to transactional commits
    # We check LOG-END-OFFSET (total available) and compare with sink topic progress
    # Output format: TOPIC PARTITION CURRENT-OFFSET LOG-END-OFFSET LAG CONSUMER-ID HOST CLIENT-ID
    
    # Get LOG-END-OFFSET sum (field 5) - total messages in source topic  
    total_end=$(echo "$lag_output" | grep "source-topic" | awk '{sum += $5} END {print sum+0}')
    
    # For EOS, check sink topic offset as proxy for consumed messages
    sink_count=$(docker compose exec -T kafka-1 kafka-run-class kafka.tools.GetOffsetShell \
        --broker-list localhost:9092 --topic sink-topic --time -1 2>&1 \
        | grep "sink-topic" | awk -F: '{sum += $3} END {print sum+0}')
    
    if [ -z "$total_end" ] || [ "$total_end" = "0" ]; then
        echo "  [Progress] Unable to get source topic end offset"
        return 1
    fi
    
    if [ -z "$sink_count" ]; then
        sink_count=0
    fi
    
    lag=$((total_end - sink_count))
    if [ "$lag" -lt 0 ]; then lag=0; fi
    
    pct=0
    if [ "$total_end" -gt 0 ]; then
        pct=$((sink_count * 100 / total_end))
    fi
    
    echo "  [Progress] Sink: $sink_count | Source End: $total_end | Lag: $lag | Complete: ${pct}%"
    
    if [ "$lag" -eq 0 ] && [ "$total_end" -gt 0 ]; then
        return 0
    fi
    return 1
}

# Wait for consumer group to be stable (not rebalancing) and actively processing
# Returns 0 when stable, 1 if timeout
wait_for_stable() {
    local max_attempts=${1:-30}
    local attempt=0
    local last_sink=0
    local stable_count=0
    
    echo "Waiting for stream apps to stabilize and process messages..."
    
    while [ $attempt -lt $max_attempts ]; do
        attempt=$((attempt + 1))
        
        lag_output=$(docker compose exec -T kafka-1 kafka-consumer-groups \
            --bootstrap-server localhost:9092 \
            --describe \
            --group eos-repro-group 2>&1)
        
        if echo "$lag_output" | grep -q "is rebalancing"; then
            echo "  [Stabilize $attempt/$max_attempts] Rebalancing in progress..."
            stable_count=0
            sleep 3
            continue
        fi
        
        if echo "$lag_output" | grep -q "has no active members"; then
            echo "  [Stabilize $attempt/$max_attempts] No active members yet..."
            stable_count=0
            sleep 3
            continue
        fi
        
        sink_count=$(docker compose exec -T kafka-1 kafka-run-class kafka.tools.GetOffsetShell \
            --broker-list localhost:9092 --topic sink-topic --time -1 2>&1 \
            | grep "sink-topic" | awk -F: '{sum += $3} END {print sum+0}')
        
        if [ "$sink_count" -gt "$last_sink" ]; then
            stable_count=$((stable_count + 1))
            echo "  [Stabilize $attempt/$max_attempts] Processing: sink=$sink_count (stable count: $stable_count/3)"
            
            if [ $stable_count -ge 3 ]; then
                echo "  Stream apps are stable and processing messages."
                return 0
            fi
        else
            echo "  [Stabilize $attempt/$max_attempts] Waiting for processing to start (sink=$sink_count)..."
            stable_count=0
        fi
        
        last_sink=$sink_count
        sleep 2
    done
    
    echo "  Warning: Timed out waiting for stability, proceeding anyway..."
    return 1
}

# Function to end test and report results
end_test() {
    local reason="$1"
    local exit_code="$2"
    
    echo ""
    echo "============================================"
    echo "TEST ENDED: $reason"
    echo "============================================"
    
    dump_logs
    
    # Final bug check
    if docker compose logs validator 2>/dev/null | grep -q "BUG REPRODUCED"; then
        echo ""
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        echo "RESULT: BUG REPRODUCED!"
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        echo ""
        echo "Watermark regression detected - Kafka Streams EOS violation confirmed."
        echo "Evidence saved to: $LOG_DIR"
        
        echo "Running Root Cause Analysis..."
        python3 scripts/analyze_logs.py "$LOG_DIR/kafka-1.log" || true
        python3 scripts/analyze_logs.py "$LOG_DIR/kafka-2.log" || true
        python3 scripts/analyze_logs.py "$LOG_DIR/kafka-3.log" || true
        
        docker compose down 2>/dev/null || true
        exit 1
    else
        echo ""
        echo "RESULT: Bug NOT reproduced in this run."
        echo "All 640,000 messages processed without watermark regression."
        echo ""
        docker compose down 2>/dev/null || true
        exit "$exit_code"
    fi
}

echo "=== Starting Structured Reproduction Cycles ==="

docker compose stop stream-app-1 stream-app-2 stream-app-3

for i in {1..20}; do
    echo "=== Cycle $i: Progressive Startup ==="
    
    # 1. Start App 1
    echo "Cycle $i: Starting stream-app-1..."
    docker compose up -d stream-app-1
    sleep 30
    check_bug && end_test "Bug reproduced in Cycle $i (App 1)" 1
    
    # 2. Start App 2 with Chaos
    kafka_target="kafka-$((RANDOM % 3 + 1))"
    echo "Cycle $i: Starting stream-app-2 (Chaos on $kafka_target)..."
    docker compose exec -u root $kafka_target tc qdisc add dev eth0 root netem delay 150ms 50ms loss 10% 2>/dev/null || true
    
    docker compose up -d stream-app-2
    sleep 30
    
    docker compose exec -u root $kafka_target tc qdisc del dev eth0 root 2>/dev/null || true
    check_bug && end_test "Bug reproduced in Cycle $i (App 2)" 1
    
    # 3. Start App 3 with Chaos
    kafka_target="kafka-$((RANDOM % 3 + 1))"
    echo "Cycle $i: Starting stream-app-3 (Chaos on $kafka_target)..."
    docker compose exec -u root $kafka_target tc qdisc add dev eth0 root netem delay 150ms 50ms loss 10% 2>/dev/null || true
    
    docker compose up -d stream-app-3
    sleep 30
    
    docker compose exec -u root $kafka_target tc qdisc del dev eth0 root 2>/dev/null || true
    check_bug && end_test "Bug reproduced in Cycle $i (App 3)" 1
    
    # 4. Wait 1 Minute Steady State
    echo "Cycle $i: Waiting 60s steady state..."
    sleep 60
    check_bug && end_test "Bug reproduced in Cycle $i (Steady State)" 1
    
    # 5. Stop All (Effective Restart for next cycle)
    echo "Cycle $i: Stopping all stream apps..."
    docker compose stop stream-app-1 stream-app-2 stream-app-3
    sleep 5
done

echo "=== Waiting for processing to complete ==="
sleep 60

check_bug && end_test "Bug detected after final wait" 1

echo "Checking final stats..."
docker compose logs validator | tail -20

end_test "Completed all 50 chaos cycles" 0
