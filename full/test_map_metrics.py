import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

try:
    from . import map_metrics as metrics
except ImportError:
    import map_metrics as metrics

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "research/2026-10-11/map-metrics"


def observation(variable, value, *, parent="03.01", year=2024, **changes):
    row = {"field_id": parent + ":" + variable, "catalog_field_id": parent, "geo_id": "41", "geo_type": "state",
           "year": year, "source": "census_acs", "source_release": "2024-acs-acs5", "unit": "source_defined",
           "value": value, "source_url": "https://api.census.gov/data/2024/acs/acs5"}
    row.update(changes)
    return row


class CheckedFormulaTests(unittest.TestCase):
    def setUp(self):
        self.inputs = json.loads((EVIDENCE / "prod-formula-inputs.json").read_text())["rows"]

    def rows(self, parent, geo="41"):
        return [r for r in self.inputs if r["catalog_field_id"] == parent and r["geo_id"] == geo]

    def test_all_definitions_match_frozen_official_metadata(self):
        self.assertEqual(metrics.validate_definitions(), [])
        document = metrics.load_definitions()
        d = next(d for d in document["definitions"] if d["metric_id"] == "bachelors-degree-exact-share")
        d["formula"]["numerator"] = {"B15003_023E": 1}
        d["label_assertions"] = {"B15003_023E": "Bachelor's degree"}
        self.assertTrue(any("label mismatch" in error for error in metrics.validate_definitions(document)))

    def test_live_oregon_bachelors_is_exact_category_not_total_or_cumulative(self):
        result = metrics.calculate("bachelors-degree-exact-share", self.rows("03.01"))
        self.assertEqual(result["numerator"], 690053)
        self.assertEqual(result["denominator"], 3044782)
        self.assertAlmostEqual(result["value"], 22.663461620569223)
        self.assertEqual(result["unit"], "%")
        self.assertEqual(result["definition_id"], "map:bachelors-degree-exact-share:v1")
        self.assertIn("03.01:B15003_022E", result["input_field_ids"])

    def test_live_high_school_and_no_diploma_partition_universe(self):
        high = metrics.calculate("high-school-or-higher-share", self.rows("03.04"))
        low = metrics.calculate("no-high-school-diploma-share", self.rows("03.05"))
        self.assertEqual(high["numerator"], 2796561)
        self.assertEqual(low["numerator"], 248221)
        self.assertEqual(high["numerator"] + low["numerator"], high["denominator"])
        self.assertAlmostEqual(high["value"] + low["value"], 100)

    def test_live_rent_burden_excludes_not_computed(self):
        rows = self.rows("02.06")
        values = {r["field_id"].split(":")[1]: r["value"] for r in rows}
        result = metrics.calculate("rent-burden-30-plus-share", rows)
        self.assertEqual(result["numerator"], 312174)
        self.assertEqual(result["denominator"], values["B25070_001E"] - values["B25070_011E"])
        self.assertAlmostEqual(result["value"], 52.478478165487395)
        self.assertNotEqual(result["denominator"], values["B25070_001E"])

    def test_live_ratio_and_owner_share_have_different_meanings(self):
        rows = self.rows("02.07")
        ratio = metrics.calculate("owner-renter-ratio", rows)
        owner = metrics.calculate("owner-occupied-share", rows)
        renter = metrics.calculate("renter-occupied-share", rows)
        self.assertEqual(ratio["denominator"], 630439)
        self.assertEqual(owner["denominator"], 1718422)
        self.assertAlmostEqual(ratio["value"], 1.7257545932278935)
        self.assertAlmostEqual(owner["value"] + renter["value"], 100)

    def test_live_poverty_universe_is_not_total_population(self):
        result = metrics.calculate("poverty-share", self.rows("02.08"))
        self.assertEqual(result["numerator"], 498380)
        self.assertEqual(result["denominator"], 4173206)
        self.assertNotEqual(result["denominator"], 4254293)
        self.assertAlmostEqual(result["value"], 11.94237715559692)

    def test_live_200k_households_is_a_share_of_households(self):
        result = metrics.calculate("households-income-200k-plus-share", self.rows("02.09"))
        self.assertEqual(result["numerator"], 218500)
        self.assertEqual(result["denominator"], 1718422)
        self.assertAlmostEqual(result["value"], 12.715153786438954)

    def test_live_national_formula_uses_nation_components(self):
        result = metrics.calculate("bachelors-degree-exact-share", self.rows("03.01", "US"))
        self.assertEqual(result["geo_type"], "nation")
        self.assertEqual(result["numerator"], 49868171)
        self.assertEqual(result["denominator"], 230807303)

    def test_integer_year_admission_shape_and_raw_inputs_are_preserved(self):
        rows = [observation("B15003_001E", 100), observation("B15003_022E", 20)]
        before = copy.deepcopy(rows)
        result = metrics.calculate("bachelors-degree-exact-share", rows)
        self.assertEqual(result["value"], 20)
        self.assertEqual(result["period"], "2024")
        self.assertEqual(result["raw_components"], {"B15003_001E": 100, "B15003_022E": 20})
        self.assertEqual(rows, before)

    def test_missing_component_and_zero_denominator_remain_distinct(self):
        missing = metrics.calculate("bachelors-degree-exact-share", [observation("B15003_001E", 100)])
        zero = metrics.calculate("bachelors-degree-exact-share", [observation("B15003_001E", 0), observation("B15003_022E", 0)])
        self.assertEqual(missing["status"], "missing_component")
        self.assertEqual(missing["geo_id"], "41")
        self.assertEqual(zero["status"], "zero_denominator")
        self.assertIsNone(zero["value"])

    def test_suppression_carries_raw_status_not_zero(self):
        rows = [observation("B15003_001E", 100), observation("B15003_022E", None, quality_status="suppressed", raw_value="**")]
        result = metrics.calculate("bachelors-degree-exact-share", rows)
        self.assertEqual(result["status"], "suppressed")
        self.assertEqual(result["raw_component"]["raw_value"], "**")
        self.assertIsNone(result["value"])

    def test_acs_sentinels_nonfinite_booleans_and_over_universe_are_rejected(self):
        for value in [-666666666, float("inf"), float("nan"), True, 101]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                metrics.calculate("bachelors-degree-exact-share", [observation("B15003_001E", 100), observation("B15003_022E", value)])

    def test_duplicate_and_mixed_metadata_are_rejected(self):
        rows = [observation("B15003_001E", 100), observation("B15003_022E", 20)]
        with self.assertRaisesRegex(ValueError, "duplicate_component"):
            metrics.calculate("bachelors-degree-exact-share", rows + [rows[1]])
        for key, wrong in [("source_release", "2023-acs-acs5"), ("year", 2023), ("geo_id", "06"), ("unit", "%")]:
            changed = copy.deepcopy(rows)
            changed[1][key] = wrong
            with self.subTest(key=key), self.assertRaises(ValueError):
                metrics.calculate("bachelors-degree-exact-share", changed)

    def test_shared_source_variable_under_other_parent_is_not_consumed(self):
        rows = [observation("B15003_001E", 100), observation("B15003_022E", 20), observation("B15003_001E", 999, parent="03.04")]
        self.assertEqual(metrics.calculate("bachelors-degree-exact-share", rows)["value"], 20)

    def test_moe_formula_and_negative_radicand_fallback(self):
        rows = [observation("B15003_001E", 100), observation("B15003_022E", 20),
                observation("B15003_001M", 10), observation("B15003_022M", 5)]
        result = metrics.calculate("bachelors-degree-exact-share", rows)
        self.assertAlmostEqual(result["margin_of_error"], 21 ** .5)
        self.assertEqual(result["uncertainty_method"], "approximate_90pct_subset_proportion")
        rows[-1]["value"] = 1
        result = metrics.calculate("bachelors-degree-exact-share", rows)
        self.assertAlmostEqual(result["margin_of_error"], 5 ** .5)
        self.assertEqual(result["uncertainty_method"], "approximate_90pct_ratio_fallback")
        rows[-1]["value"] = -555555555
        self.assertIsNone(metrics.calculate("bachelors-degree-exact-share", rows)["margin_of_error"])

    def test_signed_irs_amount_and_display_conversion_are_explicit(self):
        row = {"field_id": "07.01:A00100:county_sum_agi_stubs_1_8", "catalog_field_id": "07.01", "geo_type": "county", "geo_id": "41001",
               "year": 2023, "source": "irs_soi", "source_release": "IRS-SOI-COUNTY-2023", "unit": "thousand_USD", "value": -123.5}
        result = metrics.calculate("agi-county-total", [row])
        self.assertEqual(result["value"], -123500)
        self.assertEqual(result["unit"], "USD")
        self.assertEqual(result["raw_components"][row["field_id"]], -123.5)
        raw = metrics.calculate("published_total_agi", [row])
        self.assertEqual(raw["value"], -123.5)
        self.assertEqual(raw["unit"], "thousand_USD")

    def test_comparison_bridge_retains_definition_and_requires_metadata(self):
        result = metrics.calculate("bachelors-degree-exact-share", self.rows("03.01"))
        record = metrics.comparison_record(result, geo_vintage="ACS-2024")
        self.assertEqual(record["definition_id"], result["definition_id"])
        self.assertEqual(record["field_id"], "derived:03.01:bachelors-degree-exact-share:v1")
        self.assertEqual(record["statistic"], "share")
        self.assertEqual(record["unit"], "%")
        with self.assertRaisesRegex(ValueError, "metadata_unresolved"):
            metrics.comparison_record(result, geo_vintage="")

    def test_frozen_runtime_files_match_manifest(self):
        manifest = json.loads((EVIDENCE / "runtime-evidence/manifest.json").read_text())
        for row in manifest["files"]:
            payload = (EVIDENCE / "runtime-evidence" / row["evidence_path"]).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), row["sha256"])

    def test_registry_rebuild_is_deterministic_and_covers_exact_35(self):
        spec = importlib.util.spec_from_file_location("metric_registry_builder", EVIDENCE / "build_registry.py")
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        expected = json.loads((EVIDENCE / "metric-registry.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            import shutil
            copied = Path(directory) / "evidence"
            shutil.copytree(EVIDENCE, copied)
            with mock.patch.object(builder, "HERE", copied):
                actual = builder.build()
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual["fields"]), 35)
        self.assertEqual({f["catalog_field_id"] for f in actual["fields"] if f["status"] == "product_selection_required"},
                         {"01.02", "01.03", "01.04", "01.06", "01.07", "01.08"})
        for row in actual["fields"]:
            self.assertNotEqual(row["restored_selected_unit"], "source_defined")


if __name__ == "__main__":
    unittest.main()
