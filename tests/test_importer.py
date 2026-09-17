import unittest
from engine.importer import date_value, milestones


class MilestoneTests(unittest.TestCase):
    def test_boolean_status_does_not_invent_a_date(self):
        self.assertIsNone(date_value(True))
        self.assertIsNone(date_value(False))
        with self.assertRaises(ValueError):
            date_value("2026-02-30")

    def test_generic_support_is_not_security_support(self):
        dates = milestones({"eolFrom": "2027-01-01"}, {"eol": "Support"})
        self.assertEqual(dates["eol"], "2027-01-01")
        self.assertIsNone(dates["eossec"])

    def test_unknown_extension_does_not_shorten_total_support(self):
        dates = milestones({"eolFrom": "2027-01-01", "eoesFrom": None},
                           {"eol": "Security Support", "eoes": "Extended Support"})
        self.assertEqual(dates["eossec"], "2027-01-01")
        self.assertIsNone(dates["eol"])

    def test_extended_security_updates_extend_security_deadline(self):
        dates = milestones({"eolFrom": "2027-01-01", "eoesFrom": "2029-01-01"},
                           {"eol": "Security Support", "eoes": "Extended Security Updates"})
        self.assertEqual(dates["eossec"], "2029-01-01")
        self.assertEqual(dates["eol"], "2029-01-01")

    def test_discontinued_does_not_imply_end_of_sales(self):
        dates = milestones({"discontinuedFrom": "2027-01-01"}, {"discontinued": "Discontinued"})
        self.assertIsNone(dates["eos"])
