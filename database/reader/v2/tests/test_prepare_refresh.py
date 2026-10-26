import unittest
from decimal import Decimal
import hashlib
import tempfile
from pathlib import Path

from database.reader.v2 import prepare_refresh
from database.reader.v2.prepare_refresh import validate_medical_rate


class RefreshContractTests(unittest.TestCase):
    def setUp(self):
        self.row = {"year":"2024", "denominator_year":"2024", "denominator_kind":"age_13_plus",
                    "numerator":"688", "denominator":"4377632", "value":"15.71625938406882990621413586",
                    "status":"prepared_local"}

    def test_valid_age13_plus_2024_rate_matches_same_year_pep(self):
        quality, value, numerator, denominator = validate_medical_rate(
            self.row, 2024, "age_13_plus", "4377632")
        self.assertEqual(quality, "observed")
        self.assertEqual(value, Decimal(self.row["value"]))
        self.assertEqual((numerator, denominator), (Decimal("688"), Decimal("4377632")))

    def test_wrong_denominator_year_is_rejected(self):
        row = {**self.row, "denominator_year":"2023"}
        with self.assertRaisesRegex(ValueError, "event year"):
            validate_medical_rate(row, 2024, "age_13_plus", "4377632")

    def test_wrong_population_age_band_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "incorrect age-population"):
            validate_medical_rate(self.row, 2024, "under_18", "4377632")

    def test_pep_denominator_must_match_same_geography_year_and_age(self):
        with self.assertRaisesRegex(ValueError, "does not equal matching PEP"):
            validate_medical_rate(self.row, 2024, "age_13_plus", "4377633")

    def test_source_suppression_stays_null(self):
        row = {**self.row, "status":"source_suppressed", "value":""}
        quality, value, _, _ = validate_medical_rate(row, 2024, "age_13_plus", "4377632")
        self.assertEqual(quality, "suppressed")
        self.assertIsNone(value)

    def test_nonnative_national_total_is_missing_not_a_published_rate(self):
        quality, value, _, _ = validate_medical_rate(
            self.row, 2024, "age_13_plus", "4377632", native_denominator=False)
        self.assertEqual(quality, "missing")
        self.assertIsNone(value)

    def test_native_national_pep_row_is_accepted_by_exact_selector_and_year(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pep.csv"
            path.write_text("SEX,AGE,POPESTIMATE2023,POPESTIMATE2024\n0,999,336755052,340003797\n", encoding="utf-8")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            previous = prepare_refresh.NATIVE_PEP_SHA256
            prepare_refresh.NATIVE_PEP_SHA256 = digest
            try:
                self.assertEqual(prepare_refresh.native_national_population(path, digest, 2023, 336755052), 336755052)
                self.assertEqual(prepare_refresh.native_national_population(path, digest, 2024, 340003797), 340003797)
            finally:
                prepare_refresh.NATIVE_PEP_SHA256 = previous

    def test_native_national_pep_rejects_wrong_value(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pep.csv"
            path.write_text("SEX,AGE,POPESTIMATE2023\n0,999,336755052\n", encoding="utf-8")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            previous = prepare_refresh.NATIVE_PEP_SHA256
            prepare_refresh.NATIVE_PEP_SHA256 = digest
            try:
                with self.assertRaisesRegex(ValueError, "differs from expected"):
                    prepare_refresh.native_national_population(path, digest, 2023, 336755051)
            finally:
                prepare_refresh.NATIVE_PEP_SHA256 = previous

    def test_native_national_pep_rejects_absent_or_ambiguous_selector(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pep.csv"
            path.write_text("SEX,AGE,POPESTIMATE2023\n0,0,100\n", encoding="utf-8")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            previous = prepare_refresh.NATIVE_PEP_SHA256
            prepare_refresh.NATIVE_PEP_SHA256 = digest
            try:
                with self.assertRaisesRegex(ValueError, "absent or ambiguous"):
                    prepare_refresh.native_national_population(path, digest, 2023)
                path.write_text("SEX,AGE,POPESTIMATE2023\n0,999,1\n0,999,1\n", encoding="utf-8")
                duplicate_digest = hashlib.sha256(path.read_bytes()).hexdigest()
                prepare_refresh.NATIVE_PEP_SHA256 = duplicate_digest
                with self.assertRaisesRegex(ValueError, "absent or ambiguous"):
                    prepare_refresh.native_national_population(path, duplicate_digest, 2023)
            finally:
                prepare_refresh.NATIVE_PEP_SHA256 = previous

    def test_native_pep_requires_pinned_source_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pep.csv"
            path.write_text("SEX,AGE,POPESTIMATE2023\n0,999,336755052\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum"):
                prepare_refresh.native_national_population(path, "0" * 64, 2023)

    def test_national_age_denominators_are_verified_from_native_age_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pep.csv"
            rows = ["SEX,AGE,POPESTIMATE2023", "0,999,1000"]
            rows.extend(f"0,{age},{age + 1}" for age in range(18))
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            previous = prepare_refresh.NATIVE_PEP_SHA256
            prepare_refresh.NATIVE_PEP_SHA256 = digest
            try:
                self.assertEqual(prepare_refresh.native_national_age_population(path, digest, 2023, "age_13_plus", 909), 909)
                self.assertEqual(prepare_refresh.native_national_age_population(path, digest, 2023, "under_18", 171), 171)
                with self.assertRaisesRegex(ValueError, "differs from expected"):
                    prepare_refresh.native_national_age_population(path, digest, 2023, "under_18", 170)
            finally:
                prepare_refresh.NATIVE_PEP_SHA256 = previous

    def test_national_age_denominator_refuses_incomplete_source_ages(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pep.csv"
            path.write_text("SEX,AGE,POPESTIMATE2023\n0,999,1000\n0,0,1\n", encoding="utf-8")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            previous = prepare_refresh.NATIVE_PEP_SHA256
            prepare_refresh.NATIVE_PEP_SHA256 = digest
            try:
                with self.assertRaisesRegex(ValueError, "age 0-12.*incomplete"):
                    prepare_refresh.native_national_age_population(path, digest, 2023, "age_13_plus")
            finally:
                prepare_refresh.NATIVE_PEP_SHA256 = previous


if __name__ == "__main__":
    unittest.main()
