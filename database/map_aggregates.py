"""Provenance-bearing national selection and narrowly defined derived totals.

Pure functions; never store these results over official source observations.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import math
from typing import Iterable

try:
    from .map_quality import MetricObservation, metadata_problems, value_problem
except ImportError:
    from map_quality import MetricObservation, metadata_problems, value_problem


US_STATE_FIPS = frozenset('01 02 04 05 06 08 09 10 11 12 13 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 44 45 46 47 48 49 50 51 53 54 55 56'.split())
OREGON_COUNTY_FIPS = frozenset(f'41{code:03d}' for code in range(1, 72, 2))


def canonical_national(row: MetricObservation):
    if row.geo_type == 'nation' and row.geo_id in ('US', '1', '0100000US'):
        return True
    return row.geo_type == 'state' and ((row.source == 'bea_rpp' and row.geo_id == '00000')
                                      or (row.source == 'eia' and row.geo_id == 'US'))


def _binding(rows):
    records = sorted((row.to_dict() for row in rows), key=lambda item: json.dumps(item, sort_keys=True))
    encoded = json.dumps(records, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return {'input_count': len(records), 'input_sha256': hashlib.sha256(encoded).hexdigest(),
            'inputs': records}


def select_national(rows: Iterable[MetricObservation], reference: MetricObservation):
    """Only select one published US observation for the requested exact snapshot.

    National values outside that period/release/definition are not fallbacks.
    Even identical duplicates are ambiguous until provenance is resolved.
    """
    keys = ('metric_id', 'definition_id', 'field_id', 'statistic', 'period', 'source', 'source_release',
            'unit', 'universe', 'adjustment', 'geo_vintage')
    reference_problems = metadata_problems(reference)
    if reference_problems:
        return {'available': False, 'reason': 'unresolved_reference_metadata', 'details': reference_problems}
    candidates = [row for row in rows if canonical_national(row) and row.provenance_kind == 'official'
                  and all(getattr(row, key) == getattr(reference, key) for key in keys)]
    if not candidates:
        return {'available': False, 'reason': 'no_compatible_published_national_observation'}
    if len(candidates) != 1:
        return {'available': False, 'reason': 'ambiguous_published_national_observation'}
    chosen = candidates[0]
    if problem := value_problem(chosen):
        return {'available': False, 'reason': problem}
    return {'available': True, 'observation': replace(chosen, geo_type='nation', geo_id='US').to_dict(),
            'provenance': {'kind': 'official', 'source_geo_type': chosen.geo_type,
                           'source_geo_id': chosen.geo_id, **_binding(candidates)}}


def _validate_components(rows, expected_geographies, *, geo_type, field_id, metric_id, unit):
    reasons = []
    if any(row.geo_type != geo_type for row in rows):
        reasons.append('mixed_or_incorrect_geography_levels')
    if any(row.field_id != field_id or row.metric_id != metric_id for row in rows):
        reasons.append('incorrect_component_definition')
    if any(row.unit != unit for row in rows):
        reasons.append('incorrect_component_unit')
    actual = {row.geo_id for row in rows}
    if len(actual) != len(rows):
        reasons.append('duplicate_component_geography')
    if actual != set(expected_geographies):
        reasons.append('incomplete_or_unexpected_geography_coverage')
    for row in rows:
        # These two fiscal/labor aggregations validate a complete, disjoint
        # fixed FIPS roster directly and perform no geometry join. An unknown
        # boundary vintage stays explicit; it still blocks map comparison.
        reasons.extend(problem for problem in metadata_problems(row)
                       if problem != 'unresolved_geo_vintage')
        if problem := value_problem(row):
            reasons.append(problem)
    keys = ('definition_id', 'statistic', 'period', 'source', 'source_release', 'universe', 'adjustment', 'geo_vintage')
    if len({tuple(getattr(row, key) for key in keys) for row in rows}) != 1:
        reasons.append('incompatible_component_metadata')
    return list(dict.fromkeys(reasons))


def derive_national_unemployment(unemployed: Iterable[MetricObservation], labor_force: Iterable[MetricObservation]):
    """Σ unemployed / Σ labor force × 100 for exactly the 50 states and DC.

    Do not pass Puerto Rico, national, or county observations. State LASST series
    are seasonally adjusted: the result is explicitly a sum-of-states estimate,
    not a CPS official national rate or the arithmetic mean of state rates.
    """
    numerator, denominator = list(unemployed), list(labor_force)
    reasons = _validate_components(numerator, US_STATE_FIPS, geo_type='state', field_id='03.06:unemployment', metric_id='unemployment_count', unit='persons')
    reasons += _validate_components(denominator, US_STATE_FIPS, geo_type='state', field_id='03.06:labor_force', metric_id='labor_force_count', unit='persons')
    common = ('period', 'source', 'source_release', 'universe', 'adjustment', 'geo_vintage')
    if numerator and denominator and any(getattr(numerator[0], key) != getattr(denominator[0], key) for key in common):
        reasons.append('numerator_denominator_metadata_mismatch')
    if any(row.source != 'bls_laus' or row.statistic != 'count' for row in numerator + denominator):
        reasons.append('incorrect_component_source_or_statistic')
    if any(value_problem(row) is None and row.value < 0 for row in numerator + denominator):
        reasons.append('negative_component')
    if not reasons:
        num_by_geo = {row.geo_id: row.value for row in numerator}
        den_by_geo = {row.geo_id: row.value for row in denominator}
        if any(den_by_geo[geo] <= 0 or num_by_geo[geo] > den_by_geo[geo] for geo in US_STATE_FIPS):
            reasons.append('invalid_state_numerator_or_denominator')
    if reasons:
        return {'available': False, 'reason': 'invalid_aggregate_inputs', 'details': list(dict.fromkeys(reasons)),
                'value': None}
    try:
        total_unemployed, total_labor_force = math.fsum(row.value for row in numerator), math.fsum(row.value for row in denominator)
    except OverflowError:
        return {'available': False, 'reason': 'nonfinite_aggregate', 'value': None}
    rate = total_unemployed / total_labor_force * 100
    result = replace(numerator[0], metric_id='unemployment_rate', definition_id='sum_50_states_dc_unemployed_over_labor_force_v1',
                     field_id='derived:03.06:us_sum_states_rate', geo_type='nation', geo_id='US', unit='%',
                     value=rate, statistic='share', provenance_kind='derived', source_url='',
                     methodology_note='Sum unemployed / sum labor force × 100 for 50 states + DC; Puerto Rico and counties excluded. Not an official CPS national rate.')
    return {'available': True, 'observation': result.to_dict(),
            'provenance': {'kind': 'derived', 'formula': 'sum(unemployed)/sum(labor_force)*100',
                           'numerator': total_unemployed, 'denominator': total_labor_force,
                           'geographies': sorted(US_STATE_FIPS), **_binding(numerator + denominator)}}


def derive_oregon_published_agi(rows: Iterable[MetricObservation], *, disclosure_reviewed: bool,
                                source_state_total: float | None = None):
    """Sum disclosed published county values, retaining suppression caveats.

    A full geographic roster does not establish complete underlying tax amounts.
    The same-publication county-code-000 total is reconciliation evidence only.
    """
    rows = list(rows)
    reasons = _validate_components(rows, OREGON_COUNTY_FIPS, geo_type='county',
                                   field_id='07.01:A00100:county_sum_agi_stubs_1_8',
                                   metric_id='published_total_agi', unit='thousand_USD')
    if any(row.source != 'irs_soi' or row.statistic != 'amount' for row in rows):
        reasons.append('incorrect_component_source_or_statistic')
    if any(row.source_release != 'IRS-SOI-COUNTY-2023' or row.period != '2023' for row in rows):
        reasons.append('unreviewed_agi_publication')
    if not disclosure_reviewed:
        reasons.append('source_disclosure_rules_not_reviewed')
    if reasons:
        return {'available': False, 'value': None, 'reason': 'invalid_aggregate_inputs', 'details': list(dict.fromkeys(reasons))}
    try:
        total = math.fsum(row.value for row in rows)
    except OverflowError:
        return {'available': False, 'value': None, 'reason': 'nonfinite_aggregate'}
    reconciliation = None
    if source_state_total is not None:
        if isinstance(source_state_total, bool) or not isinstance(source_state_total, (int, float)) or not math.isfinite(source_state_total):
            return {'available': False, 'value': None, 'reason': 'invalid_source_state_total'}
        reconciliation = {'source_state_total': source_state_total, 'difference': total-source_state_total,
                          'matches': total == source_state_total,
                          'basis': 'Excluded county-code-000 rows from the same county publication, not another IRS state series.'}
        if not reconciliation['matches']:
            return {'available': False, 'value': None, 'reason': 'source_state_reconciliation_mismatch',
                    'reconciliation': reconciliation}
    return {'available': True, 'status': 'derived_published_cell_sum', 'usable_as_full_statewide_tax_total': False,
            'value': total, 'unit': 'thousand_USD', 'geo_type': 'state', 'geo_id': '41',
            'metric_id': 'published_total_agi', 'definition_id': 'sum_disclosed_oregon_county_agi_v1',
            'period': rows[0].period, 'source_release': rows[0].source_release,
            'geographic_coverage_complete': True, 'underlying_tax_amount_complete': None,
            'provenance': {'kind': 'derived', 'formula': 'sum(disclosed_published_county_A00100)',
                           'geographies': sorted(OREGON_COUNTY_FIPS), **_binding(rows)},
            'reconciliation': reconciliation,
            'limitations': ['Published disclosure-protected AGI cells only; merged/excluded/dominance-protected cells cannot be reverse engineered.',
                            'County-file state total is not interchangeable with the native IRS state statistical publication.',
                            'Tax-return-address geography and filing population, not all residents.',
                            'Source dollars are in thousands; no per-return denominator selected.']}
