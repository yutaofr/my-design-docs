package com.repro;

import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.ConsumerRecords;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.common.serialization.StringDeserializer;

import java.time.Duration;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import java.util.Properties;

public class Validator {
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

        System.out.println("Validator started (read_committed)...");

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
                    System.err.println("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!");
                    System.err.println("BUG REPRODUCED: INCONSISTENT WATERMARK REGRESSION (Read Committed)");
                    System.err.println("Key: " + key);
                    System.err.println("Last Committed Watermark: " + lastWatermark);
                    System.err.println("New Committed Watermark : " + newWatermark);
                    System.err.println("Offset: " + record.offset() + ", Partition: " + record.partition());
                    System.err.println("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!");
                }

                // If StreamApp itself detected the regression via Cassandra
                if (status == 3) {
                    System.err.println("[StreamApp Signal] State store regression detected for key: " + key);
                }

                if (lastWatermark == null) {
                    lastWatermarkPerKey.put(key, newWatermark);
                }

                if (totalRecords % 1000 == 0) {
                    System.out.println("Validated " + totalRecords + " records. Bugs detected: " + bugsDetected);
                }
            }
        }
    }
}