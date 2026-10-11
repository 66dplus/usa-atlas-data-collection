"""Exercise checked source calculations through aggregate/comparison consumers."""
import json
from pathlib import Path
import unittest

from full.map_metrics import calculate, comparison_record
from database.map_aggregates import derive_national_unemployment, derive_oregon_published_agi
from database.map_quality import MetricObservation, compare, summarize_domain

EVIDENCE = Path(__file__).resolve().parents[1] / 'research/2026-10-11'


def checked_observation(metric_id, rows, *, vintage, adjustment='not_applicable'):
    result = calculate(metric_id, rows)
    return MetricObservation(**comparison_record(result, geo_vintage=vintage, adjustment=adjustment))


class MapMetricIntegrationTests(unittest.TestCase):
    def test_acs_formula_bridge_compares_states_with_percentage_point_difference(self):
        rows = json.loads((EVIDENCE / 'map-metrics/prod-formula-inputs.json').read_text())['rows']
        oregon = checked_observation('bachelors-degree-exact-share',
                                    [r for r in rows if r['catalog_field_id'] == '03.01' and r['geo_id'] == '41'],
                                    vintage='ACS-2024')
        # A second state with the same source snapshot exercises the contract;
        # this synthetic observation is not used as live California evidence.
        california = checked_observation('bachelors-degree-exact-share', [
            dict(field_id='03.01:B15003_001E', geo_id='06', geo_type='state', year=2024,
                 source='census_acs', source_release='2024-acs-acs5', unit='source_defined', value=100),
            dict(field_id='03.01:B15003_022E', geo_id='06', geo_type='state', year=2024,
                 source='census_acs', source_release='2024-acs-acs5', unit='source_defined', value=25),
        ], vintage='ACS-2024')
        result = compare(oregon, california)
        self.assertTrue(result['comparable'])
        self.assertEqual(result['difference_unit'], 'percentage_points')
        self.assertAlmostEqual(result['difference'], 25 - 690053 / 3044782 * 100)

    def test_live_bls_counts_flow_through_definitions_into_weighted_national_rate(self):
        evidence = json.loads((EVIDENCE / 'map-aggregates/aggregate-evidence.json').read_text())['national_unemployment']
        components = [checked_observation(row['metric_id'], [row], vintage=row['geo_vintage'],
                                          adjustment=row['adjustment']) for row in evidence['provenance']['inputs']]
        result = derive_national_unemployment(
            [r for r in components if r.metric_id == 'unemployment_count'],
            [r for r in components if r.metric_id == 'labor_force_count'])
        self.assertTrue(result['available'])
        self.assertEqual(result['provenance']['numerator'], 7064407)
        self.assertEqual(result['provenance']['denominator'], 170575454)
        self.assertEqual(result['observation']['value'], evidence['observation']['value'])
        self.assertEqual(result['observation']['provenance_kind'], 'derived')

    def test_live_irs_amounts_keep_source_units_and_unknown_map_vintage(self):
        evidence = json.loads((EVIDENCE / 'map-aggregates/aggregate-evidence.json').read_text())['oregon_agi']
        components = [checked_observation('published_total_agi', [row], vintage=row['geo_vintage'])
                      for row in evidence['provenance']['inputs']]
        result = derive_oregon_published_agi(components, disclosure_reviewed=True,
                                           source_state_total=evidence['value'])
        self.assertTrue(result['available'])
        self.assertEqual(result['value'], 181860432)
        self.assertEqual(result['unit'], 'thousand_USD')
        self.assertFalse(result['usable_as_full_statewide_tax_total'])
        domain = summarize_domain(components, geo_type='county')
        self.assertFalse(domain['valid'])
        self.assertIn('unresolved_geo_vintage', domain['reasons'])


if __name__ == '__main__':
    unittest.main()
