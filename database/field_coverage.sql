-- Read-only live coverage of the 81 catalog indicators.
-- Run with psql --csv -P footer=off and redirect stdout to a dated CSV.
-- Each level means at least one numeric observation exists for that indicator.
BEGIN READ ONLY;
SET LOCAL statement_timeout = '30s';
SET LOCAL lock_timeout = '2s';
SELECT c.catalog_field_id, c.catalog_label, c.planned_state,
       EXISTS (SELECT 1 FROM usa_atlas.observation_data o
               WHERE o.catalog_field_id=c.catalog_field_id) AS has_numeric,
       EXISTS (SELECT 1 FROM usa_atlas.observation_data o
               WHERE o.catalog_field_id=c.catalog_field_id AND o.geo_type='block_group') AS block_group,
       EXISTS (SELECT 1 FROM usa_atlas.observation_data o
               WHERE o.catalog_field_id=c.catalog_field_id AND o.geo_type='tract') AS tract,
       EXISTS (SELECT 1 FROM usa_atlas.observation_data o
               WHERE o.catalog_field_id=c.catalog_field_id AND o.geo_type='county') AS county,
       EXISTS (SELECT 1 FROM usa_atlas.observation_data o
               WHERE o.catalog_field_id=c.catalog_field_id AND o.geo_type='state') AS state,
       EXISTS (SELECT 1 FROM usa_atlas.observation_data o
               WHERE o.catalog_field_id=c.catalog_field_id AND o.geo_type='nation') AS nation,
       EXISTS (SELECT 1 FROM usa_atlas.observation_data o
               WHERE o.catalog_field_id=c.catalog_field_id AND o.geo_type='place') AS place,
       EXISTS (SELECT 1 FROM usa_atlas.observation_data o
               WHERE o.catalog_field_id=c.catalog_field_id AND o.geo_type='zip') AS zip,
       EXISTS (SELECT 1 FROM usa_atlas.observation_data o
               WHERE o.catalog_field_id=c.catalog_field_id AND o.geo_type='monitor') AS monitor
FROM usa_atlas.catalog_field c ORDER BY c.catalog_field_id;
ROLLBACK;
