"""Data comparison and geography-specific map domains; no visual scaling.

Callers resolve source units/definitions using the metric registry first. A
matching catalog parent or equal numbers alone never establishes compatibility.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Iterable


@dataclass(frozen=True)
class MetricObservation:
    metric_id: str
    definition_id: str
    field_id: str
    geo_type: str
    geo_id: str
    period: str
    source: str
    source_release: str
    unit: str
    universe: str
    value: float | None
    statistic: str = 'count'
    adjustment: str = 'not_applicable'
    geo_vintage: str = 'not_applicable'
    quality: str = 'observed'
    provenance_kind: str = 'official'
    source_url: str = ''
    methodology_note: str = ''

    def to_dict(self):
        return asdict(self)


QUALITY_REASONS = {
    'missing': 'missing_observation',
    'suppressed': 'suppressed_observation',
    'geography_unavailable': 'unsupported_geography',
    'load_error': 'data_load_error',
    'invalid': 'invalid_observation',
    'sentinel': 'invalid_source_sentinel',
    'not_applicable': 'source_not_applicable',
}
COMPARISON_FIELDS = ('metric_id', 'definition_id', 'field_id', 'statistic', 'period', 'source',
                     'source_release', 'unit', 'universe', 'adjustment', 'geo_vintage', 'geo_type')


def value_problem(row: MetricObservation):
    if row.quality != 'observed':
        return QUALITY_REASONS.get(row.quality, 'unresolved_quality')
    if row.value is None:
        return 'missing_observation'
    if isinstance(row.value, bool) or not isinstance(row.value, (int, float)) or not math.isfinite(row.value):
        return 'invalid_observation'
    return None


def metadata_problems(row: MetricObservation):
    problems = [f'unresolved_{key}' for key in COMPARISON_FIELDS
                if not getattr(row, key) or getattr(row, key) in ('unknown', 'unresolved')]
    if not row.geo_id:
        problems.append('unresolved_geo_id')
    if row.unit in ('source_defined', 'unknown'):
        problems.append('unresolved_unit')
    return problems


def compare(left: MetricObservation, right: MetricObservation):
    """Return right minus left only for an exactly compatible numeric pair."""
    reasons = list(dict.fromkeys([*(metadata_problems(left)), *(metadata_problems(right))]))
    for side, row in (('left', left), ('right', right)):
        if problem := value_problem(row):
            reasons.append(side + '_' + problem)
    reasons.extend(key + '_mismatch' for key in COMPARISON_FIELDS if getattr(left, key) != getattr(right, key))
    if reasons:
        return {'comparable': False, 'reasons': reasons, 'difference': None, 'difference_unit': None}
    delta = right.value - left.value
    if not math.isfinite(delta):
        return {'comparable': False, 'reasons': ['nonfinite_difference'], 'difference': None, 'difference_unit': None}
    return {'comparable': True, 'reasons': [], 'difference': delta,
            'difference_unit': 'percentage_points' if left.unit in ('%', 'percent') else left.unit,
            'direction': 'right_minus_left'}


def summarize_domain(rows: Iterable[MetricObservation], *, geo_type: str):
    """Domain and competition ranks within one geography and one definition.

    Unknown/suppressed values are excluded with counted reasons. Mixed source,
    period, release, units or definitions fail closed instead of stretching the
    scale. A numeric zero is included. A singleton/constant domain remains valid
    with a zero range; rendering strategy belongs to the UI.
    """
    selected = [row for row in rows if row.geo_type == geo_type]
    excluded = {}
    accepted = []
    reasons = []
    if len({row.geo_id for row in selected}) != len(selected):
        reasons.append('duplicate_geography')
    for row in selected:
        problems = metadata_problems(row)
        reasons.extend(problems)
        if problem := value_problem(row):
            excluded[problem] = excluded.get(problem, 0) + 1
        else:
            accepted.append(row)
    if len({tuple(getattr(row, key) for key in COMPARISON_FIELDS) for row in selected}) > 1:
        reasons.append('incompatible_domain_observations')
    if reasons or not accepted:
        return {'valid': False, 'geo_type': geo_type, 'reasons': list(dict.fromkeys(reasons)) or ['no_observed_values'],
                'excluded': excluded, 'observed_count': len(accepted), 'minimum': None, 'maximum': None, 'ranks': {}}
    values = sorted(row.value for row in accepted)
    # Competition rank: equal values share rank; the next rank skips tied places.
    rank_by_value = {}
    for index, value in enumerate(reversed(values), start=1):
        rank_by_value.setdefault(value, index)
    ranks = {row.geo_id: rank_by_value[row.value] for row in accepted}
    return {'valid': True, 'geo_type': geo_type, 'reasons': [], 'excluded': excluded,
            'observed_count': len(accepted), 'minimum': values[0], 'maximum': values[-1],
            'median': values[len(values) // 2] if len(values) % 2 else (values[len(values)//2-1] + values[len(values)//2])/2,
            'range': values[-1] - values[0], 'ranks': ranks,
            'rank_order': 'descending_numeric_value', 'rank_population': [row.geo_id for row in sorted(accepted, key=lambda row: row.geo_id)],
            'note': 'Descriptive distribution; ranks indicate numerical order, not desirability. No population-weighted statistic or visual normalization inferred.'}
