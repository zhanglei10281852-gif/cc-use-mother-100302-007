"""校企联合实验室成果协同基础契约测试。"""

import unittest

from joint_lab import ResearchWorkPackage, unique_by_identity


class ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.values = {'package_code': 'package-code-001', 'program_code': 'program-code-001', 'lead_party': 'lead-party-001', 'state': 'draft'}

    def test_fingerprint_is_stable(self) -> None:
        left = ResearchWorkPackage(**self.values)
        right = ResearchWorkPackage(**dict(reversed(list(self.values.items()))))
        self.assertEqual(left.fingerprint(), right.fingerprint())

    def test_evolve_keeps_original(self) -> None:
        original = ResearchWorkPackage(**self.values)
        change_key = next(key for key, value in self.values.items() if isinstance(value, str))
        changed = original.evolve(**{change_key: "revised-value"})
        self.assertNotEqual(original.fingerprint(), changed.fingerprint())
        self.assertEqual(getattr(original, change_key), self.values[change_key])

    def test_conflicting_identity_is_rejected(self) -> None:
        first = ResearchWorkPackage(**self.values)
        changed_values = dict(self.values)
        change_key = next(key for key in self.values if key != "package_code")
        changed_values[change_key] = 2 if isinstance(changed_values[change_key], int) else "conflict"
        second = ResearchWorkPackage(**changed_values)
        with self.assertRaises(ValueError):
            unique_by_identity([first, second])


if __name__ == "__main__":
    unittest.main()
