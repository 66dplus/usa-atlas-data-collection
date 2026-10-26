# Politics and AIAN preparation (candidate)

This package prepares local candidate artifacts from the read-only `politics-native` research materials. It never admits data. Run `python3 full/politics_20261026/prepare.py`; outputs and geometry are written under `/tmp/usa-maps-data-flow-20261026/reader-results` only. Inputs are validated against pinned SHA-256 hashes and are never copied into the repository.

The three MEDSL histories remain complete: President 2000–2024 (94,151 source rows), House 1976–2024 (33,805), and Senate 1976–2024 (3,945). Source candidatevotes and per-row totalvotes text are preserved. `reported_total_votes` must be selected once at contest grain. TOTAL mode is used for party shares; subtotals must not be added to it. Ambiguous fusion/repeated candidate rows and unclassified aggregates require quarantine before a contest can be marked validated. Source `version`, stage, special, runoff, mode, original party, and normalized party are preserved.

Field mapping: existing `01.04` is extended for AIAN broad share using B02010_001E / B01003_001E from the same 2024 ACS 5-year table. New election fields are `12.01` President, `12.02` Senate, `12.03` House. The broad AIAN measure includes AIAN alone or in combination, all Hispanic origins; overlapping race responses mean shares do not sum to 100%. Raw E/M fields and special codes remain. The U.S. 7,990,799 input is only a prepared-file control, not independent source validation.

AIAN county matching is exact FIPS only. Parent precheck found 3,133 matched source county IDs, 11 source-only IDs (Alaska Chugach/Copper River and nine Connecticut planning regions), and nine map-only IDs. Source-only values remain explicit nonmapping records; no county geometry substitution or reallocation is performed. ACS source geography does not match the Census 2017 map in those cases.

The congressional geometry comes from the Census 2024 Cartographic Boundary File for the 119th Congress, `cb_2024_us_cd119_500k.zip` (SHA-256 `2b4238aed7e865df75d0c9cfcd8dffa1b79007b24519ecc4b213e683078b031a`). Local GeoJSON and per-feature geometry hashes are inventoried outside the repository. At-large features use district code `00`; code `98` is a nonvoting delegate. No `ZZ` unassigned geometry is synthesized. These boundaries are only suitable for matching 2024 contests, not historical elections.

## Readiness and provenance

- President mirror: SHA-256 `9299583148f5f8264baf50b5d929c260699c46d915909b13ea3c3850918946f8`, 10,222,208 bytes; parent verified its MD5 `bd6661282936006b4ef4f5ee71418f3e` and byte count against public Dataverse metadata for VOQCHQ. Metadata version/license are recorded in the local readiness manifest.
- Senate public download: bytes/SHA-256 match prepared mirror (`d4492e286046f73b111cf5706ee02be4c305897898317818afd06c0ac8a464e0`); Dataverse metadata MD5 differs, so metadata-vs-download checksum inconsistency remains documented.
- House mirror checksum differs from official Dataverse metadata (mirror MD5 `50718aa65ac2652a2f08f45998433c66`, metadata MD5 `a9566ac393913a1af343284e837c17bb`). Direct official download requires guestbook submission; no submission was made. Byte identity remains unresolved, so production source readiness is blocked.
- Census API without key returned a missing-key response. Prepared source hashes are retained; no credentials were read or used.
- No production DB admission, no reader release, no v2 tag, and no application edits are part of this candidate.
