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

CREATE TABLE IF NOT EXISTS usa_atlas.observation (
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
    source_url text NOT NULL CHECK (source_url ~ '^https://'),
    methodology_note text NOT NULL,
    retrieved_at timestamptz NOT NULL,
    ingest_id uuid NOT NULL REFERENCES usa_atlas.ingest_run (ingest_id),
    PRIMARY KEY (geo_id, period, field_id, source_release)
);

CREATE INDEX IF NOT EXISTS observation_lookup_idx
    ON usa_atlas.observation (catalog_field_id, geo_type, geo_id, period DESC)
    INCLUDE (value, unit, field_id, source_release);

CREATE INDEX IF NOT EXISTS observation_ingest_idx
    ON usa_atlas.observation (ingest_id);

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

    INSERT INTO usa_atlas.observation (
        geo_id, geo_type, period, field_id, catalog_field_id, value, unit,
        source, source_release, source_url, methodology_note, retrieved_at, ingest_id
    )
    SELECT geo_id, geo_type, period, field_id, catalog_field_id, value, unit,
           source, source_release, source_url, methodology_note, retrieved_at, ingest_id
    FROM usa_atlas.observation_stage
    WHERE ingest_id = p_ingest_id
    ON CONFLICT (geo_id, period, field_id, source_release) DO UPDATE SET
        geo_type = EXCLUDED.geo_type,
        catalog_field_id = EXCLUDED.catalog_field_id,
        value = EXCLUDED.value,
        unit = EXCLUDED.unit,
        source = EXCLUDED.source,
        source_url = EXCLUDED.source_url,
        methodology_note = EXCLUDED.methodology_note,
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

COMMIT;
