import unittest

from prepare_bls import canonical_period


class BLSPeriodTests(unittest.TestCase):
    def test_annual_m13_has_null_month_and_canonical_source_code(self):
        self.assertEqual(canonical_period("annual", "2025", "M13"),
                         ("annual", 2025, None, 2025, 2025, "2025-M13"))

    def test_monthly_periods_are_calendar_months(self):
        self.assertEqual(canonical_period("monthly", "2025-01", "M01"),
                         ("monthly", 2025, 1, 2025, 2025, "2025-M01"))
        self.assertEqual(canonical_period("monthly", "2025-12", "M12"),
                         ("monthly", 2025, 12, 2025, 2025, "2025-M12"))

    def test_m13_cannot_be_a_month(self):
        with self.assertRaisesRegex(ValueError, "unexpected BLS period"):
            canonical_period("monthly", "2025-13", "M13")

    def test_source_code_and_calendar_month_must_agree(self):
        with self.assertRaisesRegex(ValueError, "disagree"):
            canonical_period("monthly", "2025-02", "M01")


if __name__ == "__main__":
    unittest.main()
