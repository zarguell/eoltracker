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

    def test_vendor_wording_variants_reach_the_right_milestone(self):
        # big-ip publishes both dates but labels them "End of Technical Support";
        # the terminal date must map to eol, while software-development end
        # must never become end of sale.
        dates = milestones({"releaseDate": "2026-05-05", "eoasFrom": "2029-05-05", "eolFrom": "2029-05-05"},
                           {"eoas": "End of Software Development", "eol": "End of Technical Support"})
        self.assertEqual(dates["eol"], "2029-05-05")
        self.assertIsNone(dates["eos"])

    def test_label_wording_is_normalized_not_matched_exactly(self):
        for label in ("End-of-life Date", "End Of Life", "end-of-life"):
            dates = milestones({"eolFrom": "2030-01-01"}, {"eol": label})
            self.assertEqual(dates["eol"], "2030-01-01", label)

    def test_security_and_technical_support_is_not_security_support(self):
        # internet-explorer: a security+technical label is a full support end
        # (eol), not a security-only deadline.
        dates = milestones({"eolFrom": "2022-06-15"}, {"eol": "Security and technical support"})
        self.assertEqual(dates["eol"], "2022-06-15")
        self.assertIsNone(dates["eossec"])

    def test_discontinued_does_not_imply_end_of_sales(self):
        dates = milestones({"discontinuedFrom": "2027-01-01"}, {"discontinued": "Discontinued"})
        self.assertIsNone(dates["eos"])
