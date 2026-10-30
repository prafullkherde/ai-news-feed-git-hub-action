import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import Main


class PredictionVerificationTests(unittest.TestCase):
    def setUp(self):
        self.prices = pd.Series(
            [101, 102, 103, 104, 105, 106],
            index=pd.date_range("2026-10-07", periods=6, freq="D"),
        )

    def test_zero_and_non_finite_targets_are_skipped(self):
        entries = [
            {
                "date": "2026-10-06",
                "price_at_prediction": 100,
                "predicted_next_day_price": 0,
                "predicted_next_week_price": float("nan"),
                "verified_next_day": None,
                "verified_next_week": None,
            }
        ]

        updated, checked = Main.verify_past_predictions(entries, self.prices)

        self.assertEqual(checked, 0)
        self.assertIsNone(updated[0]["verified_next_day"])
        self.assertIsNone(updated[0]["verified_next_week"])

    def test_valid_targets_are_verified(self):
        entries = [
            {
                "date": "2026-10-06",
                "price_at_prediction": 100,
                "predicted_next_day_price": 105,
                "predicted_next_week_price": 110,
                "verified_next_day": None,
                "verified_next_week": None,
            }
        ]

        updated, checked = Main.verify_past_predictions(entries, self.prices)

        self.assertEqual(checked, 2)
        self.assertEqual(updated[0]["verified_next_day"]["actual_price"], 101)
        self.assertEqual(updated[0]["verified_next_day"]["error_pct"], -3.81)
        self.assertEqual(updated[0]["verified_next_week"]["actual_price"], 105)


class MarketDataTests(unittest.TestCase):
    def test_invalid_close_values_are_removed_and_three_month_return_is_not_faked(self):
        history = pd.DataFrame(
            {"Close": [0, float("nan"), 100, 101]},
            index=pd.date_range("2026-10-01", periods=4, freq="D"),
        )

        with patch.object(Main.yf, "Ticker") as ticker_factory:
            ticker = ticker_factory.return_value
            ticker.history.return_value = history
            ticker.info = {}
            ticker.news = []

            _, technicals, _, closes = Main.get_market_data("EXAMPLE")

        self.assertEqual(technicals["last_close"], 101)
        self.assertIsNone(technicals["3mo_return_pct"])
        self.assertEqual(closes.tolist(), [100, 101])

    def test_history_without_positive_closes_is_rejected(self):
        history = pd.DataFrame({"Close": [0, float("nan")]})

        with patch.object(Main.yf, "Ticker") as ticker_factory:
            ticker_factory.return_value.history.return_value = history

            with self.assertRaisesRegex(RuntimeError, "No valid positive closing prices"):
                Main.get_market_data("EXAMPLE")


if __name__ == "__main__":
    unittest.main()
