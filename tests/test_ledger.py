"""事件账本哈希链测试。"""

import unittest

from joint_lab.events import GENESIS_HASH, Event, Ledger


class LedgerTests(unittest.TestCase):
    def test_append_builds_hash_chain(self) -> None:
        ledger = Ledger()
        first = ledger.append("TYPE_A", {"k": 1}, "2026-01-01T00:00:00+00:00")
        second = ledger.append("TYPE_B", {"k": 2}, "2026-01-01T00:00:01+00:00")
        self.assertEqual(first.prev_hash, GENESIS_HASH)
        self.assertEqual(second.prev_hash, first.hash)
        self.assertNotEqual(first.hash, second.hash)
        self.assertTrue(ledger.verify())

    def test_tampered_data_breaks_verification(self) -> None:
        ledger = Ledger()
        first = ledger.append("TYPE_A", {"k": 1}, "2026-01-01T00:00:00+00:00")
        ledger.append("TYPE_B", {"k": 2}, "2026-01-01T00:00:01+00:00")
        forged = Event(
            seq=first.seq,
            at=first.at,
            type=first.type,
            data={"k": 999},
            prev_hash=first.prev_hash,
            hash=first.hash,
        )
        ledger._events[0] = forged  # 模拟账本文件被篡改
        self.assertFalse(ledger.verify())

    def test_broken_chain_is_rejected_on_load(self) -> None:
        ledger = Ledger()
        ledger.append("TYPE_A", {"k": 1}, "2026-01-01T00:00:00+00:00")
        items = ledger.to_list()
        items.append(
            {
                "seq": 2,
                "at": "2026-01-01T00:00:01+00:00",
                "type": "TYPE_B",
                "data": {},
                "prev_hash": "0" * 64,
                "hash": "0" * 64,
            }
        )
        with self.assertRaises(ValueError):
            Ledger.from_list(items)

    def test_roundtrip_preserves_events(self) -> None:
        ledger = Ledger()
        ledger.append("TYPE_A", {"k": "值", "n": [1, 2]}, "2026-01-01T00:00:00+00:00")
        ledger.append("TYPE_B", {"k": 2}, "2026-01-01T00:00:01+00:00")
        restored = Ledger.from_list(ledger.to_list())
        self.assertEqual(restored.to_list(), ledger.to_list())
        self.assertTrue(restored.verify())

    def test_empty_ledger_is_valid(self) -> None:
        self.assertTrue(Ledger().verify())


if __name__ == "__main__":
    unittest.main()
