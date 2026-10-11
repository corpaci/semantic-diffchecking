"""Identifier and structural-equality regressions; no ETP data files needed.

Run from the repository root: python3 -m unittest discover -s oracle -v
"""
import unittest

from normalizer import (
    OutsideFragment, ParseFailure, analyze, canonical_key, parse_equation,
)


def key(text):
    return canonical_key(parse_equation(text))


class UnicodeIdentifiers(unittest.TestCase):
    def test_supported_names_preserve_spelling(self):
        pairs = [
            ("l", "I"), ("_x1", "y_2"), ("α", "β"),
            ("a", "а"),              # Latin / Cyrillic
            ("x", "х"),              # Latin / Cyrillic
            ("I", "Ι"),              # Latin / Greek
            ("x", "𝑥"),              # ordinary / mathematical italic
            ("a", "ａ"),              # ordinary / fullwidth
            ("I", "Ⅰ"),              # Latin / Unicode letter number
            ("é", "e\u0301"),         # precomposed / decomposed
            ("x₁", "x₂"), ("x²", "x2"),
            ("变量一", "变量二"), ("क", "कि"),
            ("x\u203fy", "x_y"),      # Unicode / ASCII connector
        ]
        for a, b in pairs:
            with self.subTest(a=a, b=b):
                result = analyze(f"{a} * {b} = {a}")
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["variables"], [a, b])
                self.assertEqual(result["parsed"], f"{a} ◇ {b} = {a}")
                self.assertEqual(result["canonical_key"], key("x * y = x"))

    def test_confusables_cannot_merge_or_split_occurrences(self):
        for a, b in [("a", "а"), ("x", "𝑥"), ("é", "e\u0301"),
                     ("x₁", "x1"), ("A", "a"), ("K", "K")]:
            with self.subTest(a=a, b=b):
                distinct = key(f"{a} * {b} = {a}")
                merged = key(f"{a} * {a} = {a}")
                changed_occurrence = key(f"{a} * {b} = {b}")
                self.assertNotEqual(distinct, merged)
                self.assertNotEqual(distinct, changed_occurrence)

    def test_renaming_and_reversal_apply_across_entire_law(self):
        self.assertEqual(key("x = y * (x * y)"), key("β ⊕ (α ⊕ β) = α"))
        self.assertNotEqual(key("x = y * (x * y)"), key("β ⊕ (α ⊕ α) = α"))

    def test_unicode_function_names(self):
        self.assertEqual(key("σ(α, β) = α"), key("x * y = x"))
        self.assertEqual(key("𝑓(x₁, x₂) = x₁"), key("x * y = x"))
        with self.assertRaises(OutsideFragment):
            parse_equation("f(α, β) = 𝑓(α, β)")

    def test_quantifiers_use_unicode_identifier_rules(self):
        prefixes = [
            "∀ α β, ", "∀α, β: ", r"\forall α β. ",
            "for all α, β, ", "for every α β: ", "for any α β. ",
            "∀ α: ∀ β: ",
        ]
        for prefix in prefixes:
            with self.subTest(prefix=prefix):
                self.assertEqual(key(prefix + "α * β = α"), key("x * y = x"))
        self.assertEqual(key("∀ e\u0301, x₁: e\u0301 * x₁ = e\u0301"),
                         key("x * y = x"))

    def test_quantifier_comma_does_not_consume_equation(self):
        for formula in ["α = β", "σ(α, β) = α", "(α * β) = α"]:
            with self.subTest(formula=formula):
                self.assertEqual(key("∀ α, β, " + formula), key(formula))
        self.assertEqual(key("for all x y, x * y = x"), key("x * y = x"))
        self.assertEqual(key("forall * x = forall"), key("x * y = x"))

    def test_wrappers_preserve_unicode_spelling(self):
        text = r"$\mathrm{α} \oplus \mathbf{а} = \mathrm{α}$"
        self.assertEqual(analyze(text)["variables"], ["α", "а"])
        self.assertEqual(key(text), key("x * y = x"))

    def test_numeric_literals_are_still_rejected(self):
        for value in ["0", "12", "١", "１"]:
            with self.subTest(value=value), self.assertRaises(OutsideFragment):
                parse_equation(f"α * {value} = α")

    def test_invalid_starts_controls_and_symbols_are_rejected(self):
        for text in ["\u0301x = x", "₁x = x", "😀 = x",
                     "x\u200by = x", "x\u200dy = x", "x\u202ey = x"]:
            with self.subTest(text=text), self.assertRaises(ParseFailure):
                parse_equation(text)

    def test_structure_and_fragment_checks_remain_strict(self):
        with self.assertRaises(ParseFailure):
            parse_equation("α * β * γ = α")
        for text in ["α * β = β + α", "α = β = γ", "α ≠ β"]:
            with self.subTest(text=text), self.assertRaises(OutsideFragment):
                parse_equation(text)
        self.assertNotEqual(key("α * (β * γ) = α"), key("(α * β) * γ = α"))
        self.assertNotEqual(key("α * β = α"), key("β * α = α"))


if __name__ == "__main__":
    unittest.main()
