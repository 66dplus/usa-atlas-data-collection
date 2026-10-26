-- Candidate reader v2 bootstrap used only for contract fixtures and review.
-- It is not a production migration and does not change the released v1 schema.
CREATE SCHEMA usa_atlas;

CREATE TABLE usa_atlas.catalog_field (
    catalog_field_id text PRIMARY KEY,
    catalog_label text NOT NULL,
    planned_state text NOT NULL,
    rate_limit_profile text NOT NULL,
    source_release text NOT NULL,
    contract jsonb NOT NULL,
    contract_sha256 character(64) NOT NULL
);

CREATE TABLE usa_atlas.ingest_run (
    ingest_id uuid PRIMARY KEY,
    source text NOT NULL,
    artifact_path text NOT NULL,
    artifact_sha256 character(64) NOT NULL,
    contract_sha256 character(64) NOT NULL,
    row_count bigint NOT NULL,
    started_at timestamptz NOT NULL,
    completed_at timestamptz,
    status text NOT NULL,
    error_code text
);

CREATE TABLE usa_atlas.reader_observation (
    observation_id text PRIMARY KEY,
    dataset_id text NOT NULL,
    field_id text NOT NULL,
    catalog_field_id text NOT NULL REFERENCES usa_atlas.catalog_field(catalog_field_id),
    geo_id text NOT NULL,
    geo_type text NOT NULL CHECK (geo_type IN ('nation','state','county','congressional_district')),
    state_fips character(2),
    district_code character(2),
    boundary_vintage smallint,
    congress_session text,
    is_at_large boolean NOT NULL DEFAULT false,
    period_kind text NOT NULL CHECK (period_kind IN ('monthly','annual','multi_year')),
    period_year smallint NOT NULL,
    period_month smallint CHECK (period_month BETWEEN 1 AND 12),
    period_start_year smallint NOT NULL,
    period_end_year smallint NOT NULL,
    source_period_code text,
    value numeric,
    unit text NOT NULL,
    quality_status text NOT NULL CHECK (quality_status IN
        ('observed','no_election','missing','suppressed','invalid','nonmapping_geography')),
    source_value_status text NOT NULL CHECK (source_value_status IN
        ('observed','missing','suppressed','invalid')),
    geography_mapping_status text NOT NULL CHECK (geography_mapping_status IN
        ('mapped','nonmapping_geography','vintage_unresolved')),
    raw_estimate text,
    raw_estimate_moe text,
    raw_denominator text,
    raw_denominator_moe text,
    denominator_value numeric,
    source text NOT NULL,
    source_release text NOT NULL,
    source_url text NOT NULL,
    source_sha256 character(64) NOT NULL,
    methodology_note text NOT NULL,
    retrieved_at timestamptz NOT NULL,
    ingest_id uuid NOT NULL REFERENCES usa_atlas.ingest_run(ingest_id),
    UNIQUE NULLS NOT DISTINCT (dataset_id,field_id,geo_type,geo_id,period_kind,period_year,
            period_month,period_start_year,period_end_year,source_release),
    CHECK (period_start_year <= period_end_year),
    CHECK ((period_kind = 'monthly' AND period_month BETWEEN 1 AND 12
            AND period_start_year = period_year AND period_end_year = period_year)
        OR (period_kind = 'annual' AND period_month IS NULL
            AND period_start_year = period_year AND period_end_year = period_year)
        OR (period_kind = 'multi_year' AND period_month IS NULL
            AND period_start_year < period_end_year)),
    CHECK (quality_status <> 'observed' OR (source_value_status = 'observed' AND value IS NOT NULL)),
    CHECK (quality_status <> 'no_election' OR value IS NULL),
    CHECK (quality_status <> 'missing' OR value IS NULL),
    CHECK (quality_status <> 'suppressed' OR value IS NULL),
    CHECK (quality_status <> 'invalid' OR value IS NULL),
    CHECK (geo_type <> 'congressional_district' OR (state_fips IS NOT NULL AND district_code IS NOT NULL AND boundary_vintage IS NOT NULL AND congress_session IS NOT NULL)),
    CHECK (quality_status <> 'no_election' OR source_value_status <> 'observed')
);

CREATE TABLE usa_atlas.geography_boundary (
    geo_id text NOT NULL,
    geo_type text NOT NULL CHECK (geo_type = 'congressional_district'),
    state_fips character(2) NOT NULL,
    district_code character(2) NOT NULL,
    congress_session text NOT NULL,
    boundary_vintage smallint NOT NULL,
    is_at_large boolean NOT NULL,
    seat_type text NOT NULL CHECK (seat_type IN ('voting_district','nonvoting_delegate','unassigned_area')),
    label text NOT NULL,
    geometry_source_url text NOT NULL,
    geometry_source_sha256 character(64) NOT NULL,
    geometry_record_sha256 character(64) NOT NULL,
    source_release text NOT NULL,
    source_status text NOT NULL CHECK (source_status = 'candidate_not_admitted'),
    ingest_id uuid NOT NULL REFERENCES usa_atlas.ingest_run(ingest_id),
    PRIMARY KEY (geo_id,boundary_vintage,congress_session),
    CHECK (geo_id = state_fips || district_code),
    CHECK (is_at_large = (district_code = '00'))
);

CREATE TABLE usa_atlas.election_contest (
    contest_id text PRIMARY KEY,
    office text NOT NULL CHECK (office IN ('president','senate','house')),
    election_year smallint NOT NULL,
    election_date date,
    stage text NOT NULL,
    is_special boolean NOT NULL,
    is_runoff boolean NOT NULL,
    geography_type text NOT NULL CHECK (geography_type IN ('county','state','congressional_district')),
    geo_id text NOT NULL,
    state_fips character(2),
    district_code character(2),
    boundary_vintage smallint,
    congress_session text,
    result_mode text NOT NULL,
    reported_total_votes bigint,
    source_release text NOT NULL,
    source_url text NOT NULL,
    source_sha256 character(64) NOT NULL,
    source_version text NOT NULL,
    quality_status text NOT NULL CHECK (quality_status IN
        ('observed','no_election','missing','suppressed','invalid','nonmapping_geography')),
    geography_mapping_status text NOT NULL CHECK (geography_mapping_status IN
        ('mapped','nonmapping_geography','vintage_unresolved')),
    party_aggregation_status text NOT NULL CHECK (party_aggregation_status IN
        ('validated','quarantined','not_evaluated')),
    quarantine_reasons text[] NOT NULL DEFAULT ARRAY[]::text[],
    methodology_note text NOT NULL,
    ingest_id uuid NOT NULL REFERENCES usa_atlas.ingest_run(ingest_id),
    UNIQUE NULLS NOT DISTINCT (office,election_year,stage,is_special,is_runoff,geography_type,geo_id,
            boundary_vintage,congress_session,result_mode,source_release),
    CHECK ((office = 'house' AND geography_type = 'congressional_district') OR (office = 'senate' AND geography_type = 'state') OR (office = 'president' AND geography_type = 'county')),
    CHECK (quality_status <> 'no_election' OR reported_total_votes IS NULL),
    CHECK (quality_status <> 'observed' OR reported_total_votes IS NOT NULL)
);

CREATE TABLE usa_atlas.election_candidate (
    contest_id text NOT NULL REFERENCES usa_atlas.election_contest(contest_id),
    source_row_id text NOT NULL,
    candidate_id text,
    candidate_label text NOT NULL,
    candidate_kind text NOT NULL CHECK (candidate_kind IN
        ('candidate','ballot_or_other','source_aggregate','unclassified')),
    party_original text,
    party_normalized text,
    candidatevotes_raw text NOT NULL,
    totalvotes_raw text NOT NULL,
    candidate_votes bigint,
    source_total_votes bigint,
    result_mode text NOT NULL,
    write_in boolean,
    fusion_ticket boolean,
    source_version text NOT NULL,
    quality_status text NOT NULL CHECK (quality_status IN
        ('observed','missing','suppressed','invalid')),
    quarantine_reason text,
    ingest_id uuid NOT NULL REFERENCES usa_atlas.ingest_run(ingest_id),
    PRIMARY KEY (contest_id,source_row_id),
    CHECK (quality_status <> 'observed' OR candidate_votes IS NOT NULL)
);

CREATE TABLE usa_atlas.election_availability (
    office text NOT NULL CHECK (office IN ('president','senate','house')),
    election_year smallint NOT NULL,
    geography_type text NOT NULL CHECK (geography_type IN ('county','state','congressional_district')),
    geo_id text NOT NULL,
    boundary_vintage smallint,
    congress_session text,
    stage text NOT NULL,
    is_special boolean NOT NULL,
    is_runoff boolean NOT NULL,
    quality_status text NOT NULL CHECK (quality_status IN
        ('observed','no_election','missing','suppressed','invalid','nonmapping_geography')),
    source_release text NOT NULL,
    reason text NOT NULL,
    ingest_id uuid NOT NULL REFERENCES usa_atlas.ingest_run(ingest_id),
    UNIQUE NULLS NOT DISTINCT (office,election_year,geography_type,geo_id,boundary_vintage,
                               congress_session,stage,is_special,is_runoff,source_release),
    availability_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY
);
