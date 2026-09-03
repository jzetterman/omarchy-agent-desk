"""QML binding checks that cannot instantiate kit-backed components.

WindowRail.qml and AccountCard.qml import qs.Ui / qs.Commons, so qmltestrunner
cannot load them (G: QML tests import only QtQuick, QtTest, Format.js, Keys.js).
These greps are the binding-flow test for G2.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CriticalThresholdBindingTests(unittest.TestCase):
    def test_window_rail_exposes_critical_threshold(self):
        text = (ROOT / "WindowRail.qml").read_text(encoding="utf-8")
        self.assertIsNotNone(
            re.search(r"property\s+real\s+criticalThreshold:\s*0\.9", text),
            "WindowRail must expose property real criticalThreshold: 0.9",
        )
        self.assertIsNone(
            re.search(r"property\s+\w+\s+alarmAt\s*:", text),
            "alarmAt must be replaced by criticalThreshold",
        )
        self.assertRegex(text, r"used\s*>=\s*(root\.)?criticalThreshold")

    def test_account_card_forwards_critical_threshold(self):
        text = (ROOT / "AccountCard.qml").read_text(encoding="utf-8")
        self.assertIsNotNone(
            re.search(r"property\s+real\s+criticalThreshold:", text),
            "AccountCard must accept criticalThreshold",
        )
        self.assertGreaterEqual(
            text.count("criticalThreshold: root.criticalThreshold"),
            2,
            "both WindowRail instances must bind criticalThreshold",
        )

    def test_panel_passes_validated_critical_threshold(self):
        text = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        self.assertIn("criticalThreshold: root.validated.criticalThreshold", text)
