package com.repro;

import com.datastax.oss.driver.api.core.CqlSession;
import com.datastax.oss.driver.api.core.cql.PreparedStatement;
import com.datastax.oss.driver.api.core.cql.ResultSet;
import com.datastax.oss.driver.api.core.cql.Row;
import com.datastax.oss.driver.api.core.ConsistencyLevel;
import com.datastax.oss.driver.api.core.cql.BoundStatement;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.common.serialization.Serdes;
import org.apache.kafka.streams.KafkaStreams;
import org.apache.kafka.streams.KeyValue;
import org.apache.kafka.streams.StreamsBuilder;
import org.apache.kafka.streams.StreamsConfig;
import org.apache.kafka.streams.kstream.KStream;
import org.apache.kafka.streams.kstream.Produced;
import org.apache.kafka.streams.kstream.Transformer;
import org.apache.kafka.streams.processor.ProcessorContext;
import org.apache.kafka.streams.state.KeyValueStore;
import org.apache.kafka.streams.state.StoreBuilder;
import org.apache.kafka.streams.state.Stores;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.File;
import java.net.InetSocketAddress;
import java.time.Duration;
import java.util.Properties;

public class StreamApp {
    private static final Logger log = LoggerFactory.getLogger(StreamApp.class);

    public static void main(String[] args) {
        String bootstrapServers = System.getenv().getOrDefault("BOOTSTRAP_SERVERS", "kafka-1:9092");
        String appId = System.getenv().getOrDefault("APP_ID", "eos-repro-app");
        String sourceTopic = System.getenv().getOrDefault("SOURCE_TOPIC", "source-topic");
        String sinkTopic = System.getenv().getOrDefault("SINK_TOPIC", "sink-topic");
        String cassandraContact = System.getenv().getOrDefault("CASSANDRA_CONTACT", "cassandra-1");
        boolean cleanState = Boolean.parseBoolean(System.getenv().getOrDefault("CLEAN_STATE", "false"));

        if (cleanState) {
            File stateDir = new File("/tmp/kafka-streams");
            if (stateDir.exists()) {
                deleteRecursively(stateDir);
                log.info("Cleaned state directory: {}", stateDir);
            }
        }

        Properties props = new Properties();
        props.put(StreamsConfig.APPLICATION_ID_CONFIG, appId);
        props.put(StreamsConfig.BOOTSTRAP_SERVERS_CONFIG, bootstrapServers);
        props.put(StreamsConfig.DEFAULT_KEY_SERDE_CLASS_CONFIG, Serdes.String().getClass());
        props.put(StreamsConfig.DEFAULT_VALUE_SERDE_CLASS_CONFIG, Serdes.String().getClass());
        props.put(StreamsConfig.PROCESSING_GUARANTEE_CONFIG, StreamsConfig.EXACTLY_ONCE_V2);
        props.put(StreamsConfig.NUM_STREAM_THREADS_CONFIG, 2);
        props.put(StreamsConfig.NUM_STANDBY_REPLICAS_CONFIG, 1);
        props.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");

        // AGGRESSIVE CHAOS CONFIGURATION
        props.put(StreamsConfig.COMMIT_INTERVAL_MS_CONFIG, 100);
        props.put(ConsumerConfig.SESSION_TIMEOUT_MS_CONFIG, 6000);
        props.put(ConsumerConfig.HEARTBEAT_INTERVAL_MS_CONFIG, 2000);
        props.put(ConsumerConfig.MAX_POLL_INTERVAL_MS_CONFIG, 30000);
        props.put(ConsumerConfig.MAX_POLL_RECORDS_CONFIG, 1);
        props.put(StreamsConfig.producerPrefix("transaction.timeout.ms"), 5000);
        props.put(StreamsConfig.producerPrefix("delivery.timeout.ms"), 10000);
        props.put(StreamsConfig.producerPrefix("request.timeout.ms"), 5000);

        // Replication for internal topics
        props.put(StreamsConfig.REPLICATION_FACTOR_CONFIG, 3);
        props.put(StreamsConfig.producerPrefix(org.apache.kafka.clients.producer.ProducerConfig.ACKS_CONFIG), "all");

        StreamsBuilder builder = new StreamsBuilder();

        // Define State Store
        String storeName = "watermark-store";
        StoreBuilder<KeyValueStore<String, Long>> storeBuilder = Stores.keyValueStoreBuilder(
                Stores.persistentKeyValueStore(storeName),
                Serdes.String(),
                Serdes.Long()).withLoggingEnabled(new java.util.HashMap<>());

        builder.addStateStore(storeBuilder);

        KStream<String, String> source = builder.stream(sourceTopic);

        source.transform(() -> new WatermarkTransformer(storeName, cassandraContact), storeName)
                .to(sinkTopic, Produced.with(Serdes.String(), Serdes.String()));

        KafkaStreams streams = new KafkaStreams(builder.build(), props);
        streams.start();

        Runtime.getRuntime().addShutdownHook(new Thread(streams::close));
    }

    private static void deleteRecursively(File file) {
        if (file.isDirectory()) {
            File[] children = file.listFiles();
            if (children != null) {
                for (File child : children) {
                    deleteRecursively(child);
                }
            }
        }
        file.delete();
    }

    public static class WatermarkTransformer implements Transformer<String, String, KeyValue<String, String>> {
        private final String storeName;
        private final String cassandraContact;
        private KeyValueStore<Integer, Long> store;
        private ProcessorContext context;

        private CqlSession session;
        private PreparedStatement selectStmt;
        private PreparedStatement insertStmt;

        public WatermarkTransformer(String storeName, String cassandraContact) {
            this.storeName = storeName;
            this.cassandraContact = cassandraContact;
        }

        @Override
        public void init(ProcessorContext context) {
            this.context = context;
            this.store = (KeyValueStore<Integer, Long>) context.getStateStore(storeName);

            // Connect to Cassandra
            this.session = CqlSession.builder()
                    .addContactPoint(new InetSocketAddress(cassandraContact, 9042))
                    .withLocalDatacenter("datacenter1")
                    .build();

            // Prepare statements
            this.selectStmt = session.prepare("SELECT watermark FROM repro.state WHERE id = ?");
            this.insertStmt = session.prepare("INSERT INTO repro.state (id, watermark) VALUES (?, ?)");
        }

        @Override
        public KeyValue<String, String> transform(String key, String value) {
            // IN KAFKA-17507, the state store regresses.
            // We track the watermark as max(stored_watermark, current_record_timestamp).
            // In EOS, the output should NEVER decrease for the same key.

            long recordTimestamp = context.timestamp();
            int recordPartition = context.partition();
            Long storedWatermark = store.get(recordPartition);

            // LOGIC: newWatermark = max(stored_watermark, current_record_timestamp)
            long currentWatermark = (storedWatermark == null) ? 0L : storedWatermark;
            long newWatermark = Math.max(currentWatermark, recordTimestamp);

            store.put(recordPartition, newWatermark);

            // Double-check against Cassandra to verify regression immediately
            BoundStatement selectBound = selectStmt.bind(key).setConsistencyLevel(ConsistencyLevel.QUORUM);
            ResultSet rs = session.execute(selectBound);
            Row row = rs.one();

            int status = 1; // 1 = OK, 3 = REGRESSION (BUG)
            if (row != null) {
                long cassandraWatermark = row.getLong("watermark");
                if (newWatermark != cassandraWatermark) {
                    status = 3;
                    log.error("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!");
                    log.error("BUG REPRODUCED: STATE STORE REGRESSION DETECTED");
                    log.error("TaskID={}, Key={}, Cassandra(Truth)={}, StateStore(Regressed)={}",
                            context.taskId(), key, cassandraWatermark, newWatermark);
                    log.error("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!");
                }
            } else {
                BoundStatement insertBound = insertStmt.bind(key, newWatermark)
                        .setConsistencyLevel(ConsistencyLevel.QUORUM);
                session.execute(insertBound);
            }

            try {
                Thread.sleep(100);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }

            return new KeyValue<>(key, newWatermark + "," + status);
        }

        @Override
        public void close() {
            if (session != null)
                session.close();
        }
    }
}
