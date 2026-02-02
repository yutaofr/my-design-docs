CREATE KEYSPACE IF NOT EXISTS repro WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 3};

CREATE TABLE IF NOT EXISTS repro.state (
    id text PRIMARY KEY,
    watermark bigint
);
