"""QML binding checks that cannot instantiate kit-backed components.

WindowRail.qml, AccountCard.qml, Panel.qml, and Service.qml import qs.Ui /
qs.Commons / Quickshell, so qmltestrunner cannot load them (G: QML tests import
only QtQuick, QtTest, Format.js, Keys.js). These greps are the binding-flow
test for G2. They live here, not in test_qml_plaintext.sh, because CI runs
unittest discover and not bin/check.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def block(text: str, start: str) -> str:
    """Text from `start` to the matching closing brace."""
    i = text.index(start)
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    raise AssertionError(f"unbalanced block at {start!r}")


class StatusStripBindingTests(unittest.TestCase):
    def test_account_card_status_strip_appends_help(self):
        # R25 / plan F: not-signed-in, expired, and failed without a cache show
        # the record's help line after the label.
        text = (ROOT / "AccountCard.qml").read_text(encoding="utf-8")
        status = block(text, "readonly property string statusText: {")
        self.assertRegex(status, r"record\.help")
        self.assertIn('" · "', status)


class CaptionLatchBindingTests(unittest.TestCase):
    def test_service_emits_caption_signal_and_panel_latches_it(self):
        # Plan F caption latch: a repeated caption must latch again after a
        # reopen, so Service delivers captions as a signal, not a property.
        service = (ROOT / "Service.qml").read_text(encoding="utf-8")
        self.assertRegex(service, r"signal\s+caption\(string\s+text\)")
        self.assertRegex(service, r"root\.caption\(")
        self.assertNotIn("captionText", service)
        panel = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        self.assertRegex(panel, r"function\s+onCaption\(text\)")
        self.assertNotIn("captionText", panel)


class CardVisibilityPredicateTests(unittest.TestCase):
    def test_panel_uses_keys_shows_cards(self):
        # One predicate decides which sections hold cards (Keys.cards,
        # visualIndex, and the card repeater must agree).
        panel = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        visual = block(panel, "function visualIndex(providerId, accountId) {")
        self.assertIn("Keys.showsCards(", visual)
        self.assertNotIn("enabled === false", visual)
        self.assertIn("model: Keys.showsCards(section.provider)", panel)


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
