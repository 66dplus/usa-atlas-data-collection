# Geographic depth roadmap

Date: 20 September 2026
Status: product direction recorded for future collection work

## Goal

Collect every indicator at the deepest official, methodologically defensible geography
available from its source.

- **Minimum target:** city-equivalent coverage, normally a Census `place`, for every
  indicator whose source publishes it.
- **Preferred target:** below-city coverage through Census tracts and block groups.
- **Source ceiling:** retain ZIP/ZCTA, agency, utility, metro, monitor, or point records
  when that is the deepest native level, without relabeling them as cities or districts.
- **Non-negotiable rule:** never copy, divide, interpolate, or spatially assign a coarse
  value to a finer geography unless a documented methodology explicitly defines that
  derivation and exposes its uncertainty and coverage.

This is a future collection and UI roadmap, not authorization to start a bulk run.

## Canonical geography ladder

| Level | Meaning | Intended use |
| --- | --- | --- |
| `nation` | Entire United States | Summary cards and national comparisons, not a choropleth layer |
| `state` | State, DC, or territory | Current national overview |
| `county` | County or county equivalent | Current local drill-down floor |
| `county_subdivision` | Minor civil division where applicable | Source-specific intermediate layer |
| `place` | Census incorporated or census-designated place | Nationally comparable city/town layer and minimum product goal |
| `zcta` | Census ZIP Code Tabulation Area | Postal-area analysis; not interchangeable with USPS ZIP codes |
| `tract` | Census tract | Stable small-area layer suitable for many city subareas |
| `block_group` | Subdivision of a tract | Preferred deepest national layer for ACS Detailed Tables |
| `block` | Census block | Decennial counts and boundaries only where published; not a general ACS layer |
| `metro` | Metropolitan statistical area | Regional indicators that do not resolve to a city or county |
| `agency` | Reporting law-enforcement or administrative agency | Native operational geography; requires a coverage/crosswalk model before area mapping |
| `monitor` / `point` | Sensor or facility location | Point layer; area aggregates require an explicit aggregation method |

An ordinary named neighbourhood is not a single nationally standardized statistical
geography. For nationwide comparisons, `tract` and `block_group` are the defensible
below-city layers. Named neighbourhoods may be added later through a versioned,
city-specific boundary registry, with their source and overlap rules shown in the UI.

Official GEOIDs must be stored with the geography type, parent GEOID, and boundary
vintage. A `place`, police agency, USPS ZIP, ZCTA, tract, and neighbourhood must never
share a type merely because they are all perceived as “local.”

## Current baseline

The PostgreSQL snapshot currently contains:

| Native level | Observations | Distinct series | Current UI |
| --- | ---: | ---: | --- |
| State | 6,956 | 24 | Displayed |
| County | 176,867 | 12 | Displayed |
| ZIP | 827,595 | 30 | Stored but not displayed |
| EPA monitor | 19,583 | 795 | Stored but not displayed |

The UI data API currently admits only `state` and `county`. The unfinished Census run
already targets `state`, `county`, `place`, and `tract`, but incomplete Census output is
not admitted to PostgreSQL. These counts are a dated baseline, not permanent targets.

## Deepest useful level by source

| Source | Current collection | Deeper official level to pursue | Required caution |
| --- | --- | --- | --- |
| Census ACS 5-year | State, county, place, tract run in progress | ZCTA and block group; Detailed Tables are published down to block group | Keep estimate/MOE pairs, annotations, release and boundary vintage; small-area uncertainty must be visible |
| CDC PLACES | County | Place, census tract, and ZCTA datasets | These are model-based small-area estimates; retain confidence limits and data-value type |
| BLS LAUS | State and county | Usually stop at county for this series | Do not substitute metro or city series with different definitions |
| FBI CDE / UCR | State | Reporting agency plus official city/county agency tables | An agency is not a city polygon; retain ORI, agency type, reporting coverage and estimation status; avoid overlapping agency totals |
| IRS SOI | USPS ZIP | Preserve ZIP; optionally map through a versioned ZIP/ZCTA crosswalk | ZIPs are delivery routes, not stable polygons or cities; crosswalks can be many-to-many |
| EPA AirData | Monitor | Preserve monitor; derive county/city summaries only with a documented statistic and spatial rule | Multiple monitors, standards, durations and methods cannot be silently averaged |
| USDA Food Environment Atlas | County | Stop at county unless a separate official local source is selected | Do not infer city values from county values |
| BEA RPP | State and metro | Stop at native state/metro release | Metro is not a city and may cross state boundaries |
| EIA electricity | State, sector, utility identifiers where published | Preserve native utility/sector detail; add smaller geography only from an official compatible release | Utility service territories do not equal city or county boundaries |

Primary references:

- [Census ACS 5-year datasets](https://www.census.gov/data/developers/data-sets/acs-5year.html): nation, state, county, place, ZCTA, tract, and block-group availability.
- [Census GEOID definitions](https://www.census.gov/programs-surveys/geography/guidance/geo-identifiers.html): typed identifiers and hierarchy.
- [CDC PLACES data portal](https://www.cdc.gov/places/tools/explore-places-data-portal.html): county, place, tract, and ZCTA releases.
- [FBI Crime Data Explorer](https://cde.ucr.cjis.gov/LATEST/webapp/): national, state, and reporting-agency crime data.

## Delivery sequence

### G1 — Complete and admit the existing Census run

- Finish the resumable Census collection already covering state, county, place, and
  tract.
- Verify every normalized source artifact, uniqueness key, estimate/MOE pairing, and
  source/boundary vintage before database admission.
- Record coverage counts by geography and catalog field; incomplete output never
  counts as a completed finer layer.

### G2 — Reach the minimum city layer

- Treat Census `place` as the default nationwide city-equivalent geography.
- Add current place boundaries and parent relationships to the geography dimension.
- Extend the map API and renderer beyond its current state/county filter.
- Add CDC PLACES `place` data for eligible health indicators.
- Display the exact geography label (`Place`, not generic `City`) when the distinction
  matters.

### G3 — Add defensible below-city layers

- Complete Census tract ingestion and add tract boundaries.
- Extend eligible ACS Detailed Tables to `block_group`.
- Add CDC PLACES tract data and confidence intervals.
- Implement drill-down as `state → place/county → tract → block group`, while allowing
  tracts that cross or sit outside place boundaries to remain truthfully represented.
- Apply minimum zoom levels, vector tiling, lazy loading, and query bounds so national
  small-area data are never sent to the browser in one response.

### G4 — Add non-hierarchical local layers

- Expose IRS ZIP/ZCTA, EPA monitor, BEA metro, EIA utility, and FBI agency data as their
  own typed layers.
- Build versioned crosswalk tables separately from native observations.
- Every derived area value records the crosswalk version, weighting basis, aggregation
  formula, coverage ratio, and source observations.

### G5 — Optional named neighbourhoods

- Add a city only when an authoritative or clearly licensed boundary set exists.
- Store city, boundary source, version, effective dates, and overlap/gap behavior.
- Never present city-specific neighbourhood boundaries as nationally comparable.
- Prefer tract/block-group views when no defensible neighbourhood definition exists.

## Data and UI requirements

1. A geography dimension owns canonical type, GEOID/native ID, name, parent,
   boundary vintage, and boundary source.
2. Native observations remain immutable. Crosswalk-derived observations live in a
   separate provenance-bearing layer.
3. Each field declares its deepest native level and every UI card shows the level
   actually displayed.
4. Suppression, missingness, margins of error, confidence intervals, reporting
   coverage, and model-based status remain queryable—not flattened into a value.
5. The map never substitutes a state value for a county, a county value for a city,
   or a city value for a tract.
6. Boundary/data vintage mismatch is visible and tested.
7. Source collection and boundary downloads remain resumable, hash-bound, and
   deduplicated before database admission.

## Observable completion targets

- **GD1 — Inventory:** all 81 catalog indicators record the deepest official native
  geography available, the selected release, and why any finer level is unavailable.
- **GD2 — City minimum:** every eligible Census and CDC PLACES indicator can be queried
  and rendered for Census places without inference from county/state values.
- **GD3 — Below city:** eligible ACS and CDC PLACES indicators can be queried and
  rendered at tract; eligible ACS Detailed Tables reach block group.
- **GD4 — Geography integrity:** tests reject type collisions and undocumented
  state→county, county→place, ZIP→ZCTA, agency→city, and monitor→area substitutions.
- **GD5 — Provenance and quality:** each returned observation exposes release,
  retrieval time, boundary vintage, native/derived status, and applicable uncertainty
  or coverage metadata.
- **GD6 — Product behavior:** the UI offers only levels actually available for the
  selected indicator and labels them precisely; empty finer levels remain empty.
- **GD7 — Scale:** bounded national, city, tract, and block-group queries meet an agreed
  latency/response-size budget without loading the complete small-area dataset into the
  browser.

The intended end state is therefore not merely “more county data.” It is a typed,
source-faithful geographic system whose normal floor is the city/place level and whose
best-supported indicators continue through tract and block group.
