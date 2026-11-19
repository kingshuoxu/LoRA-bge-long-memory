"""Persistence and adapter binding regressions without loading model weights."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from memory_core.correction_store import (
    active_corrections,
    apply_corrections,
    discard_corrections,
    save_correction,
)


def fact(fact_id, value, **meta):
    return {"id": fact_id, "entity": "Test", "attr": "city", "value": value, **meta}


def record(*facts, name="expert_1000", writable=True):
    return SimpleNamespace(
        name=name,
        writable=writable,
        fact_memory={"facts": list(facts)},
        fact_bank=object(),
    )


class CorrectionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def test_immediate_reopen_and_missing_adapter(self):
        old = fact("a", "Old", source_conversations=[{"id": "origin"}])
        new = fact("b", "New", source_conversations=[{"id": "correction"}],
                   original_sources=[{"id": "origin"}])
        unrelated = fact("other", "Keep")
        save_correction(self.home, "expert_1000", old, new)
        for _ in range(2):  # Fresh disk record, still backed by original adapter.
            expert = record(old, unrelated)
            immutable = record(old, writable=False)
            apply_corrections(self.home, [expert, immutable])
            self.assertTrue(expert.correction_pending)
            self.assertIsNone(expert.fact_bank)
            self.assertEqual(expert.fact_memory["facts"], [
                {**old, "superseded": True, "superseded_by": "b"}, unrelated, new,
            ])
            self.assertEqual(immutable.fact_memory["facts"], [{**old, "superseded": True, "superseded_by": "b"}])
            self.assertTrue(immutable.correction_pending)
        self.assertEqual(apply_corrections(self.home, []), [])
        self.assertEqual(active_corrections(self.home)[0]["new_fact"], new)

    def test_correction_chain_and_successful_adapter_registration(self):
        original = fact("a", "Original")
        first = fact("b", "First")
        final = fact("c", "Final")
        save_correction(self.home, "expert_1000", original, first)
        save_correction(self.home, "expert_1000", first, final)
        registered = record(
            {**original, "superseded": True, "superseded_by": "b"},
            {**first, "superseded": True, "superseded_by": "c"}, final,
        )
        bank = registered.fact_bank
        expected = registered.fact_memory["facts"]
        apply_corrections(self.home, [registered])
        self.assertFalse(registered.correction_pending)
        self.assertIs(registered.fact_bank, bank)
        self.assertEqual(registered.fact_memory["facts"], expected)
        self.assertEqual([row["new_fact"] for row in active_corrections(self.home)], [final])
        stale = record(original, first)
        apply_corrections(self.home, [stale])
        self.assertTrue(stale.correction_pending)
        self.assertEqual(stale.fact_memory["facts"], expected)

    def test_failed_write_and_stale_proposal_do_not_replace_committed_value(self):
        old, new = fact("a", "Old"), fact("b", "New")
        save_correction(self.home, "expert_1000", old, new)
        with self.assertRaises(ValueError):
            save_correction(self.home, "expert_1000", old, fact("c", "Other"))
        with patch("memory_core.correction_store.atomic_write_json", side_effect=OSError):
            with self.assertRaises(OSError):
                save_correction(self.home, "expert_1000", new, fact("c", "Other"))
        self.assertEqual(active_corrections(self.home)[0]["new_fact"], new)

    def test_discard_is_scoped_to_deleted_expert(self):
        old, new = fact("a", "Old"), fact("b", "New")
        save_correction(self.home, "expert_1000", old, new)
        save_correction(self.home, "expert_1001", {**old, "entity": "Other"}, {**new, "entity": "Other"})
        discard_corrections(self.home, "expert_1000")
        self.assertEqual([row["expert"] for row in active_corrections(self.home)], ["expert_1001"])
        reused = record(old)
        apply_corrections(self.home, [reused])
        self.assertEqual(reused.fact_memory["facts"], [old])
