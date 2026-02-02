package com.repro;

import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.ConsumerRecords;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Duration;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import java.util.Properties;

public class Validator {
    private static final Logger log = LoggerFactory.getLogger(Validator.class);

    public static void main(String[] args) {
        String bootstrapServers = System.getenv().getOrDefault("BOOTSTRAP_SERVERS", "kafka-1:9092");
        String sinkTopic = System.getenv().getOrDefault("SINK_TOPIC", "sink-topic");

        Properties props = new Properties();
        props.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrapServers);
        props.put(ConsumerConfig.GROUP_ID_CONFIG, "validator-group-" + System.currentTimeMillis());
        props.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        props.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        props.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");

        // CRITICAL: Use read_committed to verify EOS
        props.put(ConsumerConfig.ISOLATION_LEVEL_CONFIG, "read_committed");

        KafkaConsumer<String, String> consumer = new KafkaConsumer<>(props);
        consumer.subscribe(Collections.singletonList(sinkTopic));

        // Track the maximum watermark seen for each key
        Map<String, Long> lastWatermarkPerKey = new HashMap<>();
        long totalRecords = 0;
        long bugsDetected = 0;

        log.info("Validator started (read_committed)...");

        while (true) {
            ConsumerRecords<String, String> records = consumer.poll(Duration.ofMillis(1000));
            for (ConsumerRecord<String, String> record : records) {
                totalRecords++;
                String key = record.key();
                String[] parts = record.value().split(",");
                long newWatermark = Long.parseLong(parts[0]);
                int status = Integer.parseInt(parts[1]);

                Long lastWatermark = lastWatermarkPerKey.get(key);

                if (lastWatermark != null && newWatermark != lastWatermark) {
                    bugsDetected++;
                    log.error("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!");
                    log.error("BUG REPRODUCED: INCONSISTENT WATERMARK REGRESSION (Read Committed)");
                    log.error("Key: {}, Last: {}, New: {}, Offset: {}, Partition: {}", 
                        key, lastWatermark, newWatermark, record.offset(), record.partition());
                    log.error("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!");
                }

                // If StreamApp itself detected the regression via Cassandra
                if (status == 3) {
                    log.error("[StreamApp Signal] State store regression detected for key: {}", key);
                }

                if (lastWatermark == null) {
                    lastWatermarkPerKey.put(key, newWatermark);
                }

                if (totalRecords % 1000 == 0) {
                    log.info("Validated {} records. Bugs detected: {}", totalRecords, bugsDetected);
                }
            }
        }
    }
}