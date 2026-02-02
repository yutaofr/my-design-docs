package com.repro;

import org.apache.kafka.clients.admin.AdminClient;
import org.apache.kafka.clients.admin.AdminClientConfig;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerConfig;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.serialization.StringSerializer;

import java.util.Properties;

public class Injector {
    public static void main(String[] args) throws Exception {
        String bootstrapServers = System.getenv().getOrDefault("BOOTSTRAP_SERVERS", "kafka-1:9092");
        String topic = System.getenv().getOrDefault("SOURCE_TOPIC", "source-topic");

        Properties props = new Properties();
        props.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrapServers);
        props.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        props.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, StringSerializer.class.getName());
        props.put(ProducerConfig.ACKS_CONFIG, "all");
        props.put(ProducerConfig.ENABLE_IDEMPOTENCE_CONFIG, "true");
        props.put(ProducerConfig.LINGER_MS_CONFIG, "10");

        KafkaProducer<String, String> producer = new KafkaProducer<>(props);

        int numPartitions = 64;
        int messagesPerPartition = 10000;

        System.out.println("Starting injection of " + (numPartitions * messagesPerPartition) + " messages...");

        for (int p = 0; p < numPartitions; p++) {
            for (int i = 1; i <= messagesPerPartition; i++) {
                // Use a monotonically increasing timestamp
                String key = "key-" + p + "-" + i;

                producer.send(new ProducerRecord<>(topic, key, "val-" + p + "-" + i));
            }
            System.out.println("Filled partition " + p);
        }

        producer.flush();
        producer.close();
        System.out.println("Injection complete.");
    }
}