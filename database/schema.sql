BEGIN;

CREATE SCHEMA IF NOT EXISTS usa_atlas;

CREATE TABLE usa_atlas.schema_metadata (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    schema_sha256 character(64) NOT NULL CHECK (schema_sha256 ~ '^[0-9a-f]{64}$')
);

INSERT INTO usa_atlas.schema_metadata (singleton, schema_sha256)
VALUES (true, :'schema_sha256');

CREATE TABLE IF NOT EXISTS usa_atlas.catalog_field (
    catalog_field_id text PRIMARY KEY CHECK (catalog_field_id ~ '^[0-9]{2}\.[0-9]{2}$'),
    catalog_label text NOT NULL,
    planned_state text NOT NULL CHECK (planned_state IN (
        'run_now', 'blocked_access', 'definition_required', 'source_required', 'license_required'
    )),
    rate_limit_profile text NOT NULL,
    source_release text NOT NULL,
    contract jsonb NOT NULL,
    contract_sha256 character(64) NOT NULL CHECK (contract_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS usa_atlas.ingest_run (
    ingest_id uuid PRIMARY KEY,
    source text NOT NULL,
    artifact_path text NOT NULL,
    artifact_sha256 character(64) NOT NULL CHECK (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    contract_sha256 character(64) NOT NULL CHECK (contract_sha256 ~ '^[0-9a-f]{64}$'),
    row_count bigint NOT NULL DEFAULT 0 CHECK (row_count >= 0),
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    status text NOT NULL CHECK (status IN ('loading', 'pass', 'fail')),
    error_code text
);

CREATE UNIQUE INDEX IF NOT EXISTS ingest_run_passed_artifact_idx
    ON usa_atlas.ingest_run (artifact_sha256) WHERE status = 'pass';

CREATE UNLOGGED TABLE IF NOT EXISTS usa_atlas.catalog_field_stage (
    catalog_field_id text PRIMARY KEY,
    catalog_label text NOT NULL,
    planned_state text NOT NULL,
    rate_limit_profile text NOT NULL,
    source_release text NOT NULL,
    contract jsonb NOT NULL,
    contract_sha256 character(64) NOT NULL
);

CREATE UNLOGGED TABLE IF NOT EXISTS usa_atlas.observation_stage (
    ingest_id uuid NOT NULL,
    geo_id text NOT NULL,
    geo_type text NOT NULL,
    period text NOT NULL,
    field_id text NOT NULL,
    catalog_field_id text NOT NULL,
    value double precision NOT NULL CHECK (
        value > '-Infinity'::double precision AND value < 'Infinity'::double precision
    ),
    unit text NOT NULL,
    source text NOT NULL,
    source_release text NOT NULL,
    source_url text NOT NULL,
    methodology_note text NOT NULL,
    retrieved_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS usa_atlas.source_resource (
    resource_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_url text NOT NULL UNIQUE CHECK (source_url ~ '^https://')
);

CREATE TABLE IF NOT EXISTS usa_atlas.methodology (
    methodology_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    methodology_note text NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS usa_atlas.observation_data (
    geo_id text NOT NULL,
    geo_type text NOT NULL,
    period text NOT NULL,
    field_id text NOT NULL,
    catalog_field_id text NOT NULL REFERENCES usa_atlas.catalog_field (catalog_field_id),
    value double precision NOT NULL CHECK (
        value > '-Infinity'::double precision AND value < 'Infinity'::double precision
    ),
    unit text NOT NULL,
    source text NOT NULL,
    source_release text NOT NULL,
    resource_id bigint NOT NULL REFERENCES usa_atlas.source_resource (resource_id),
    methodology_id bigint NOT NULL REFERENCES usa_atlas.methodology (methodology_id),
    retrieved_at timestamptz NOT NULL,
    ingest_id uuid NOT NULL REFERENCES usa_atlas.ingest_run (ingest_id),
    CONSTRAINT observation_pkey PRIMARY KEY (geo_id, period, field_id, source_release)
);

CREATE INDEX IF NOT EXISTS observation_lookup_idx
    ON usa_atlas.observation_data (catalog_field_id, geo_type, geo_id, period DESC)
    INCLUDE (value, unit, field_id, source_release);

CREATE INDEX IF NOT EXISTS observation_ingest_idx
    ON usa_atlas.observation_data (ingest_id);

-- Preserve the public reading contract while storing repeated provenance once.
CREATE VIEW usa_atlas.observation AS
SELECT o.geo_id, o.geo_type, o.period, o.field_id, o.catalog_field_id,
       o.value, o.unit, o.source, o.source_release, r.source_url,
       m.methodology_note, o.retrieved_at, o.ingest_id
FROM usa_atlas.observation_data o
JOIN usa_atlas.source_resource r USING (resource_id)
JOIN usa_atlas.methodology m USING (methodology_id);

CREATE OR REPLACE FUNCTION usa_atlas.finish_ingest(p_ingest_id uuid, p_expected_rows bigint)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    staged_rows bigint;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM usa_atlas.ingest_run
        WHERE ingest_id = p_ingest_id AND status = 'loading'
    ) THEN
        RAISE EXCEPTION 'unknown or non-loading ingest %', p_ingest_id;
    END IF;

    SELECT count(*) INTO staged_rows
    FROM usa_atlas.observation_stage
    WHERE ingest_id = p_ingest_id;

    IF staged_rows <> p_expected_rows THEN
        RAISE EXCEPTION 'staged row count %, expected %', staged_rows, p_expected_rows;
    END IF;

    IF (SELECT count(*) FROM usa_atlas.catalog_field_stage) <> 81 THEN
        RAISE EXCEPTION 'catalog stage must contain exactly 81 rows';
    END IF;

    INSERT INTO usa_atlas.catalog_field (
        catalog_field_id, catalog_label, planned_state, rate_limit_profile,
        source_release, contract, contract_sha256
    )
    SELECT catalog_field_id, catalog_label, planned_state, rate_limit_profile,
           source_release, contract, contract_sha256
    FROM usa_atlas.catalog_field_stage
    ON CONFLICT (catalog_field_id) DO UPDATE SET
        catalog_label = EXCLUDED.catalog_label,
        planned_state = EXCLUDED.planned_state,
        rate_limit_profile = EXCLUDED.rate_limit_profile,
        source_release = EXCLUDED.source_release,
        contract = EXCLUDED.contract,
        contract_sha256 = EXCLUDED.contract_sha256;

    INSERT INTO usa_atlas.source_resource (source_url)
    SELECT DISTINCT source_url FROM usa_atlas.observation_stage
    WHERE ingest_id = p_ingest_id
    ON CONFLICT (source_url) DO NOTHING;

    INSERT INTO usa_atlas.methodology (methodology_note)
    SELECT DISTINCT methodology_note FROM usa_atlas.observation_stage
    WHERE ingest_id = p_ingest_id
    ON CONFLICT (methodology_note) DO NOTHING;

    INSERT INTO usa_atlas.observation_data (
        geo_id, geo_type, period, field_id, catalog_field_id, value, unit,
        source, source_release, resource_id, methodology_id, retrieved_at, ingest_id
    )
    SELECT s.geo_id, s.geo_type, s.period, s.field_id, s.catalog_field_id, s.value, s.unit,
           s.source, s.source_release, r.resource_id, m.methodology_id, s.retrieved_at, s.ingest_id
    FROM usa_atlas.observation_stage s
    JOIN usa_atlas.source_resource r ON r.source_url = s.source_url
    JOIN usa_atlas.methodology m ON m.methodology_note = s.methodology_note
    WHERE s.ingest_id = p_ingest_id
    ON CONFLICT (geo_id, period, field_id, source_release) DO UPDATE SET
        geo_type = EXCLUDED.geo_type,
        catalog_field_id = EXCLUDED.catalog_field_id,
        value = EXCLUDED.value,
        unit = EXCLUDED.unit,
        source = EXCLUDED.source,
        resource_id = EXCLUDED.resource_id,
        methodology_id = EXCLUDED.methodology_id,
        retrieved_at = EXCLUDED.retrieved_at,
        ingest_id = EXCLUDED.ingest_id;

    UPDATE usa_atlas.ingest_run
    SET row_count = staged_rows, completed_at = clock_timestamp(), status = 'pass', error_code = NULL
    WHERE ingest_id = p_ingest_id;

    DELETE FROM usa_atlas.observation_stage WHERE ingest_id = p_ingest_id;
    TRUNCATE usa_atlas.catalog_field_stage;
    RETURN staged_rows;
END;
$$;


-- Automatic source pipeline, v3 additive extension.
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

COMMIT;
