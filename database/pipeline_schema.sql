-- Additive v3 extension in the existing usa_atlas database.
-- Apply only through the coordinated schema/catalog-pin migration, under the
-- same loader locks as auto_ingest.py. This file is not a standalone bootstrap.
CREATE SCHEMA usa_atlas_pipeline;

CREATE TABLE usa_atlas_pipeline.dataset (
    dataset_key text PRIMARY KEY CHECK (length(dataset_key) BETWEEN 1 AND 512),
    kind text NOT NULL CHECK (kind IN ('observations','records')),
    source text NOT NULL,
    source_release text NOT NULL,
    scope jsonb NOT NULL,
    active_snapshot_id character(64) NOT NULL CHECK (active_snapshot_id ~ '^[0-9a-f]{64}$'),
    active_snapshot_at timestamptz NOT NULL,
    total_input_rows bigint NOT NULL CHECK (total_input_rows >= 0),
    latest_snapshot_id character(64),
    latest_snapshot_at timestamptz,
    completed_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE usa_atlas_pipeline.snapshot_batch (
    batch_id character(64) PRIMARY KEY CHECK (batch_id ~ '^[0-9a-f]{64}$'),
    dataset_key text NOT NULL REFERENCES usa_atlas_pipeline.dataset(dataset_key),
    snapshot_id character(64) NOT NULL CHECK (snapshot_id ~ '^[0-9a-f]{64}$'),
    snapshot_at timestamptz NOT NULL,
    start_row bigint NOT NULL CHECK (start_row >= 0),
    end_row_exclusive bigint NOT NULL CHECK (end_row_exclusive >= start_row),
    total_input_rows bigint NOT NULL CHECK (total_input_rows >= end_row_exclusive),
    manifest_sha256 character(64) NOT NULL CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    admission_sha256 character(64) NOT NULL CHECK (admission_sha256 ~ '^[0-9a-f]{64}$'),
    manifest jsonb NOT NULL,
    ingest_id uuid REFERENCES usa_atlas.ingest_run(ingest_id),
    numeric_rows bigint NOT NULL CHECK (numeric_rows >= 0),
    quality_rows bigint NOT NULL CHECK (quality_rows >= 0),
    record_rows bigint NOT NULL CHECK (record_rows >= 0),
    inserted_rows bigint NOT NULL DEFAULT 0 CHECK (inserted_rows >= 0),
    updated_rows bigint NOT NULL DEFAULT 0 CHECK (updated_rows >= 0),
    deleted_rows bigint NOT NULL DEFAULT 0 CHECK (deleted_rows >= 0),
    status text NOT NULL CHECK (status IN ('loading','pass')),
    loaded_at timestamptz,
    UNIQUE (dataset_key,snapshot_id,start_row)
);
CREATE INDEX pipeline_snapshot_lookup_idx
    ON usa_atlas_pipeline.snapshot_batch(dataset_key,snapshot_id,start_row,end_row_exclusive);
CREATE UNIQUE INDEX pipeline_snapshot_ingest_idx
    ON usa_atlas_pipeline.snapshot_batch(ingest_id) WHERE ingest_id IS NOT NULL;

CREATE TABLE usa_atlas_pipeline.generic_record (
    dataset_key text NOT NULL REFERENCES usa_atlas_pipeline.dataset(dataset_key),
    snapshot_id character(64) NOT NULL CHECK (snapshot_id ~ '^[0-9a-f]{64}$'),
    kind text NOT NULL CHECK (kind IN ('source_record','observation_quality')),
    record_key text NOT NULL CHECK (length(record_key) BETWEEN 1 AND 2048),
    payload jsonb NOT NULL,
    batch_id character(64) NOT NULL REFERENCES usa_atlas_pipeline.snapshot_batch(batch_id),
    PRIMARY KEY (dataset_key,snapshot_id,kind,record_key)
);
CREATE INDEX pipeline_record_batch_idx ON usa_atlas_pipeline.generic_record(batch_id);
CREATE INDEX pipeline_quality_key_idx ON usa_atlas_pipeline.generic_record(record_key)
    WHERE kind='observation_quality';

GRANT USAGE ON SCHEMA usa_atlas_pipeline TO usa_atlas_reader;
GRANT SELECT ON usa_atlas_pipeline.dataset,usa_atlas_pipeline.snapshot_batch,
    usa_atlas_pipeline.generic_record TO usa_atlas_reader;
