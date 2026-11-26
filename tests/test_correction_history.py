"""A changed belief is not proof that the old value was ever true."""
import unittest

from memory_core.correction_reply import correction_kind


class CorrectionKindTests(unittest.TestCase):
    def test_beliefs_and_reports_do_not_establish_history(self):
        cases = [
            ('I used to think Mira Chen lived in Qinglan; now I know she lives in Starport', 'Qinglan', 'Starport'),
            ('我以前以为沈星河住青岚镇，现在知道他住星港', '青岚镇', '星港'),
            ('I previously believed Mira lived in Qinglan; now she lives in Starport.', 'Qinglan', 'Starport'),
            ('I assumed Mira previously lived in Qinglan; now she lives in Starport.', 'Qinglan', 'Starport'),
            ('Mira previously lived in Qinglan, or so I thought; now she lives in Starport.', 'Qinglan', 'Starport'),
            ('Previously I was told Mira lived in Qinglan. Now she lives in Starport.', 'Qinglan', 'Starport'),
            ('The records previously said Qinglan; now they say Starport.', 'Qinglan', 'Starport'),
            ('我过去认为沈星河住青岚镇，如今知道他住星港。', '青岚镇', '星港'),
            ('以前听说沈星河住青岚镇，现在知道是星港。', '青岚镇', '星港'),
            ('沈星河以前住青岚镇，这是我的猜测，现在住星港。', '青岚镇', '星港'),
            ('以前的记录是青岚镇，现在是星港。', '青岚镇', '星港'),
            ('以前记错成青岚镇，现在是星港。', '青岚镇', '星港'),
            ('Previously I did not live in Qinglan; now I live in Starport.', 'Qinglan', 'Starport'),
            # Values must belong to their respective clauses, not just occur somewhere.
            ('Previously Starport; now Qinglan.', 'Qinglan', 'Starport'),
        ]
        for source, old, new in cases:
            with self.subTest(source=source):
                self.assertEqual(correction_kind(source, old, new), 'correction')

    def test_explicit_real_changes_remain_history(self):
        for source, old, new in [
            ('Mira Chen previously lived in Qinglan and now lives in Starport.', 'Qinglan', 'Starport'),
            ('Mira used to live in Qinglan; now she lives in Starport.', 'Qinglan', 'Starport'),
            ('Mira formerly lived in Qinglan. Now she lives in Starport.', 'Qinglan', 'Starport'),
            ('Mira previously lived in Qinglan; now I know she lives in Starport.', 'Qinglan', 'Starport'),
            ('沈星河以前住青岚镇，现在住星港。', '青岚镇', '星港'),
            ('沈星河过去住青岚镇，如今住星港。', '青岚镇', '星港'),
            ('沈星河原来住青岚镇，搬到星港了。', '青岚镇', '星港'),
            ('沈星河以前住青岚镇，现在我知道他住星港。', '青岚镇', '星港'),
        ]:
            with self.subTest(source=source):
                self.assertEqual(correction_kind(source, old, new), 'state_change')

    def test_missing_ambiguous_and_identical_values_are_not_history(self):
        for source, old, new in [('', 'A', 'B'), ('以前A，现在B', '', 'B'),
                                 ('以前A，现在B', 'A', ''), ('以前A，现在A', 'A', 'A'),
                                 ('Mira lives in Starport, not Qinglan.', 'Qinglan', 'Starport')]:
            with self.subTest(source=source):
                self.assertEqual(correction_kind(source, old, new), 'correction')
