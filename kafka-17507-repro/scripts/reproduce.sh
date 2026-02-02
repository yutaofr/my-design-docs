#!/bin/bash
set -e

cd "$(dirname "$0")/.."

echo "=== KAFKA-17507 Bug Reproduction ==="
echo "Strategy: Sequential instance startup to trigger rebalancing during processing"

echo "Building application image..."
docker compose build stream-app-1

echo "Starting Infrastructure (Kafka + Cassandra)..."
docker compose up -d zookeeper kafka-1 kafka-2 kafka-3 cassandra-1 cassandra-2 cassandra-3 cassandra-init

echo "Clearing any stale network chaos..."
for b in kafka-1 kafka-2 kafka-3; do
    docker compose exec -u root $b tc qdisc del dev eth0 root 2>/dev/null || true
done

echo "Waiting for Kafka Brokers to be reachable..."
for broker in kafka-1 kafka-2 kafka-3; do
    echo "Checking $broker:9092..."
    until docker compose exec zookeeper bash -c "cat < /dev/null > /dev/tcp/$broker/9092" 2>/dev/null; do
        echo "Waiting for $broker..."
        sleep 2
    done
done
echo "Kafka is ready."

echo "Pre-creating topics..."
docker compose exec kafka-1 kafka-topics --bootstrap-server localhost:9092 --create --topic source-topic --partitions 64 --replication-factor 3 --if-not-exists || true
docker compose exec kafka-1 kafka-topics --bootstrap-server localhost:9092 --create --topic sink-topic --partitions 64 --replication-factor 3 --if-not-exists || true

echo "Waiting for Cassandra Schema Init..."
docker compose logs -f cassandra-init | grep -q "Schema initialized"
echo "Cassandra ready."

echo "Starting Validator..."
docker compose up -d validator

echo "Injecting 640,000 messages (64 partitions × 10,000 messages)..."
docker compose run --rm injector

echo "=== Starting Stream Apps Sequentially (Triggering Rebalances) ==="

check_bug() {
    if docker compose logs validator 2>/dev/null | grep -q "BUG REPRODUCED"; then
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        echo "BUG REPRODUCED!"
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        
        echo "Dumping Broker Logs..."
        docker compose logs kafka-1 > kafka-1.log
        docker compose logs kafka-2 > kafka-2.log
        docker compose logs kafka-3 > kafka-3.log
        docker compose logs validator > validator.log
        
        echo "Dumping Stream App Logs..."
        docker compose logs stream-app-1 > stream-app-1.log
        docker compose logs stream-app-2 > stream-app-2.log
        docker compose logs stream-app-3 > stream-app-3.log
        
        echo "Running Root Cause Analysis..."
        python3 scripts/analyze_logs.py kafka-1.log || true
        python3 scripts/analyze_logs.py kafka-2.log || true
        python3 scripts/analyze_logs.py kafka-3.log || true
        
        echo "Evidence collected: kafka-*.log, validator.log"
        return 0
    fi
    return 1
}

echo "Starting stream-app-1 (initial instance, gets all 64 partitions)..."
docker compose up -d stream-app-1
echo "Waiting for stream-app-1 to start processing..."
sleep 15

check_bug && exit 1

echo "Starting stream-app-2 (triggers rebalance: 64 -> 32+32 partitions)..."
kafka_target="kafka-$((RANDOM % 3 + 1))"
echo "Injecting network chaos into $kafka_target during rebalance..."
docker compose exec -u root $kafka_target tc qdisc add dev eth0 root netem delay 150ms 50ms loss 10% 2>/dev/null || true

docker compose up -d stream-app-2
echo "Waiting for rebalance and state migration..."
sleep 20

docker compose exec -u root $kafka_target tc qdisc del dev eth0 root 2>/dev/null || true

check_bug && exit 1

echo "Starting stream-app-3 (triggers rebalance: 32+32 -> ~21+21+22 partitions)..."
kafka_target="kafka-$((RANDOM % 3 + 1))"
echo "Injecting network chaos into $kafka_target during rebalance..."
docker compose exec -u root $kafka_target tc qdisc add dev eth0 root netem delay 150ms 50ms loss 10% 2>/dev/null || true

docker compose up -d stream-app-3
echo "Waiting for rebalance and state migration..."
sleep 20

docker compose exec -u root $kafka_target tc qdisc del dev eth0 root 2>/dev/null || true

check_bug && exit 1

echo "=== Additional Chaos: Kill/Restart Cycles ==="
for i in {1..50}; do
    target="stream-app-$((RANDOM % 3 + 1))"
    kafka_target="kafka-$((RANDOM % 3 + 1))"
    
    echo "Cycle $i: Injecting network chaos into $kafka_target..."
    docker compose exec -u root $kafka_target tc qdisc add dev eth0 root netem delay 100ms 50ms loss 5% 2>/dev/null || true
    
    sleep 3
    
    echo "Cycle $i: Killing $target..."
    docker compose kill $target
    
    sleep 2
    
    echo "Cycle $i: Restarting $target..."
    docker compose start $target
    
    sleep 10
    
    docker compose exec -u root $kafka_target tc qdisc del dev eth0 root 2>/dev/null || true
    
    check_bug && exit 1
done

echo "=== Waiting for processing to complete ==="
sleep 30

check_bug && exit 1

echo "Checking final stats..."
docker compose logs validator | tail -20

if docker compose logs validator | grep -q "BUG REPRODUCED"; then
    echo "BUG REPRODUCED!"
    exit 1
else
    echo "Bug not reproduced in this run."
    exit 0
fi
