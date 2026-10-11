"""Failure-mode tests for opt-in data consumers, independent of production."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

try:
    from .map_aggregates import US_STATE_FIPS, OREGON_COUNTY_FIPS, derive_national_unemployment, derive_oregon_published_agi, select_national
    from .map_quality import MetricObservation, compare, summarize_domain
except ImportError:
    from map_aggregates import US_STATE_FIPS, OREGON_COUNTY_FIPS, derive_national_unemployment, derive_oregon_published_agi, select_national
    from map_quality import MetricObservation, compare, summarize_domain


def observation(**changes):
    base = dict(metric_id='unemployment_count', definition_id='laus_unemployed_v1',
                field_id='03.06:unemployment', geo_type='state', geo_id='41',
                period='2024-M12', source='bls_laus', source_release='BLS-LAUS-2024',
                unit='persons', universe='civilian_noninstitutional_population_age_16_plus',
                value=10, statistic='count', adjustment='seasonally_adjusted',
                source_url='https://api.bls.gov/publicAPI/v2/timeseries/data/')
    return MetricObservation(**(base | changes))


def state_components():
    numerator = [observation(geo_id=geo, value=1 if geo != '06' else 90) for geo in sorted(US_STATE_FIPS)]
    denominator = [observation(geo_id=geo, value=10 if geo != '06' else 1000,
                               metric_id='labor_force_count', definition_id='laus_labor_force_v1',
                               field_id='03.06:labor_force') for geo in sorted(US_STATE_FIPS)]
    return numerator, denominator


def agi_components():
    return [observation(geo_id=geo, geo_type='county', period='2023',
                        metric_id='published_total_agi', definition_id='irs_published_agi_county_v1',
                        field_id='07.01:A00100:county_sum_agi_stubs_1_8',
                        source='irs_soi', source_release='IRS-SOI-COUNTY-2023',
                        unit='thousand_USD', universe='tax_returns_in_county_publication',
                        value=100, statistic='amount', adjustment='not_applicable')
            for geo in sorted(OREGON_COUNTY_FIPS)]


class NationalSelectionTest(unittest.TestCase):
    def test_exact_official_and_source_geo_aliases(self):
        reference = observation(metric_id='rpp', definition_id='rpp_all_items_v1', field_id='02.10',
                                source='bea_rpp', source_release='BEA-SARPP-2024', period='2024',
                                unit='index_us_100', value=103.361, statistic='index', adjustment='not_applicable')
        native = replace(reference, geo_id='00000', value=100)
        result = select_national([native], reference)
        self.assertEqual(result['observation']['geo_type'], 'nation')
        self.assertEqual(result['observation']['geo_id'], 'US')
        self.assertEqual(result['provenance']['source_geo_id'], '00000')

    def test_wrong_series_period_release_are_not_national_fallbacks(self):
        reference = observation()
        for change in ({'field_id': '03.06:employment'}, {'period': '2024-M11'},
                       {'source_release': 'BLS-LAUS-2023'}, {'provenance_kind': 'derived'}):
            with self.subTest(change=change):
                candidate = replace(reference, geo_id='US', geo_type='nation', **change)
                self.assertFalse(select_national([candidate], reference)['available'])

    def test_ambiguous_suppressed_and_unknown_metadata(self):
        reference = observation()
        native = replace(reference, geo_id='US', geo_type='nation')
        self.assertFalse(select_national([native, native], reference)['available'])
        self.assertEqual(select_national([replace(native, quality='suppressed', value=None)], reference)['reason'], 'suppressed_observation')
        self.assertFalse(select_national([native], replace(reference, universe='unknown'))['available'])


class UnemploymentAggregateTest(unittest.TestCase):
    def test_weighted_counts_not_mean_state_rates_and_provenance(self):
        numerator, denominator = state_components()
        result = derive_national_unemployment(numerator, denominator)
        self.assertAlmostEqual(result['observation']['value'], 140/1500*100)
        simple_mean = (50*10+9)/51
        self.assertNotAlmostEqual(result['observation']['value'], simple_mean)
        self.assertEqual(result['observation']['provenance_kind'], 'derived')
        self.assertEqual(result['provenance']['input_count'], 102)
        self.assertEqual(result['provenance']['geographies'], sorted(US_STATE_FIPS))
        json.dumps(result, allow_nan=False)

    def test_missing_dc_puerto_rico_and_duplicate_fail(self):
        numerator, denominator = state_components()
        for bad in ([row for row in numerator if row.geo_id != '11'],
                    numerator + [replace(numerator[0], geo_id='72')], numerator + [numerator[0]]):
            self.assertFalse(derive_national_unemployment(bad, denominator)['available'])

    def test_mixed_county_rows_and_quality_fail(self):
        numerator, denominator = state_components()
        for change in ({'geo_type': 'county'}, {'unit': '%'}, {'quality': 'suppressed', 'value': None},
                       {'value': float('nan')}, {'value': True}, {'value': '20'}, {'value': -1},
                       {'period': '2023-M12'}, {'source_release': 'BLS-LAUS-2025'}, {'adjustment': 'not_seasonally_adjusted'}):
            with self.subTest(change=change):
                bad = [replace(numerator[0], **change)] + numerator[1:]
                self.assertFalse(derive_national_unemployment(bad, denominator)['available'])

    def test_bad_denominator_or_cross_metadata_fail(self):
        numerator, denominator = state_components()
        for value in (0, -2, .5):
            bad = [replace(denominator[0], value=value)] + denominator[1:]
            self.assertFalse(derive_national_unemployment(numerator, bad)['available'])
        bad = [replace(row, source_release='BLS-LAUS-2023') for row in denominator]
        self.assertFalse(derive_national_unemployment(numerator, bad)['available'])


class AgiAggregateTest(unittest.TestCase):
    def test_disclosed_sum_and_reconciliation_are_explicit(self):
        rows = agi_components()
        result = derive_oregon_published_agi(rows, disclosure_reviewed=True, source_state_total=3600)
        self.assertTrue(result['available'])
        self.assertEqual(result['value'], 3600)
        self.assertEqual(result['unit'], 'thousand_USD')
        self.assertTrue(result['geographic_coverage_complete'])
        self.assertIsNone(result['underlying_tax_amount_complete'])
        self.assertTrue(result['reconciliation']['matches'])
        self.assertIn('no per-return denominator', result['limitations'][-1])

    def test_signed_agi_is_valid_but_missing_or_suppressed_is_not_zero(self):
        rows = agi_components()
        signed = [replace(rows[0], value=-50)] + rows[1:]
        self.assertEqual(derive_oregon_published_agi(signed, disclosure_reviewed=True)['value'], 3450)
        for bad in (rows[:-1], [replace(rows[0], quality='suppressed', value=None)] + rows[1:],
                    rows + [replace(rows[0], geo_id='41000', geo_type='state')]):
            self.assertFalse(derive_oregon_published_agi(bad, disclosure_reviewed=True)['available'])

    def test_review_and_same_publication_reconciliation_are_required(self):
        rows = agi_components()
        self.assertFalse(derive_oregon_published_agi(rows, disclosure_reviewed=False)['available'])
        self.assertEqual(derive_oregon_published_agi(rows, disclosure_reviewed=True, source_state_total=100)['reason'], 'source_state_reconciliation_mismatch')
        self.assertFalse(derive_oregon_published_agi([replace(row, period='2024') for row in rows], disclosure_reviewed=True)['available'])


class ComparisonAndDomainsTest(unittest.TestCase):
    def test_share_differences_are_percentage_points(self):
        left = observation(unit='%', statistic='share', value=4.7)
        right = replace(left, geo_id='06', value=5.4)
        result = compare(left, right)
        self.assertTrue(result['comparable'])
        self.assertAlmostEqual(result['difference'], .7)
        self.assertEqual(result['difference_unit'], 'percentage_points')

    def test_each_comparison_key_and_quality_reason_matters(self):
        row = observation()
        for key in ('field_id', 'metric_id', 'definition_id', 'unit', 'source', 'source_release',
                    'period', 'universe', 'adjustment', 'geo_type', 'geo_vintage', 'statistic'):
            with self.subTest(key=key):
                self.assertFalse(compare(row, replace(row, **{key: 'different'}))['comparable'])
        for quality, expected in (('missing', 'missing_observation'), ('suppressed', 'suppressed_observation'),
                                  ('geography_unavailable', 'unsupported_geography'), ('load_error', 'data_load_error')):
            result = compare(row, replace(row, quality=quality, value=None))
            self.assertIn('right_'+expected, result['reasons'])
        self.assertFalse(compare(replace(row, unit='source_defined'), replace(row, unit='source_defined'))['comparable'])

    def test_source_quality_states_preserve_sentinels_and_not_applicable(self):
        row = observation()
        for quality, expected in (('sentinel', 'invalid_source_sentinel'), ('not_applicable', 'source_not_applicable')):
            self.assertIn('right_' + expected, compare(row, replace(row, quality=quality, value=None))['reasons'])

    def test_domains_do_not_mix_states_counties_or_missing_values(self):
        state = observation(value=10)
        rows = [state, replace(state, geo_id='06', value=20),
                replace(state, geo_id='41051', geo_type='county', value=1000000),
                replace(state, geo_id='01', quality='suppressed', value=None)]
        result = summarize_domain(rows, geo_type='state')
        self.assertEqual((result['minimum'], result['maximum'], result['median']), (10,20,15))
        self.assertEqual(result['ranks'], {'41': 2, '06': 1})
        self.assertEqual(result['excluded'], {'suppressed_observation': 1})
        self.assertEqual(summarize_domain(rows, geo_type='county')['maximum'], 1000000)

    def test_ties_zero_constant_and_empty_domains(self):
        rows = [observation(geo_id=geo, value=value) for geo,value in [('01',10),('02',10),('04',0)]]
        result = summarize_domain(rows, geo_type='state')
        self.assertEqual(result['ranks'], {'01':1,'02':1,'04':3})
        self.assertEqual(result['minimum'], 0)
        self.assertEqual(summarize_domain([observation(value=0)], geo_type='state')['range'], 0)
        self.assertFalse(summarize_domain([], geo_type='state')['valid'])

    def test_domains_fail_for_unresolved_and_incompatible_inputs(self):
        row = observation()
        for bad in ([row,row], [row,replace(row,geo_id='06',period='2024-M11')],
                    [row,replace(row,geo_id='06',field_id='03.06:employment')],
                    [replace(row,unit='source_defined')], [replace(row,geo_vintage='unknown')]):
            self.assertFalse(summarize_domain(bad, geo_type='state')['valid'])


if __name__ == '__main__':
    unittest.main()
