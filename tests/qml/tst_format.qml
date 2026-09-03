import QtQuick
import QtTest
import "../../Format.js" as Format

Item {
    id: root
    width: 400
    height: 200

    Text {
        id: guardedAuto
        textFormat: Text.AutoText
        text: Format.plain("<img src=x>")
    }
    Text {
        id: guardedPlain
        textFormat: Text.PlainText
        text: Format.plain("<img src=x>")
    }
    Text {
        id: unguarded
        textFormat: Text.AutoText
        text: "<img src=x>"
    }

    TestCase {
        name: "FormatTests"
        when: windowShown

        function test_percent_half_up() {
            compare(Format.percent(0.749), 75)
            compare(Format.percent(0.745), 75)
            compare(Format.percent(0.744), 74)
            compare(Format.percent(0.75), 75)
            compare(Format.percent(0.005), 1)
            compare(Format.percent(0.0), 0)
            compare(Format.percent(1.0), 100)
        }

        function test_countdown_one_minute_floor() {
            var now = Date.parse("2023-11-14T13:46:40Z")
            var under = new Date(now + 30 * 1000).toISOString()
            compare(Format.countdown(under, now), "1m")
            var exact = new Date(now + 60 * 1000).toISOString()
            compare(Format.countdown(exact, now), "1m")
        }

        function test_countdown_two_units() {
            var now = Date.parse("2023-11-14T13:46:40Z")
            var fiveDaysTwoHours = new Date(now + (5 * 86400 + 2 * 3600) * 1000).toISOString()
            compare(Format.countdown(fiveDaysTwoHours, now), "5d 2h")
            var threeHoursTwelve = new Date(now + (3 * 3600 + 12 * 60) * 1000).toISOString()
            compare(Format.countdown(threeHoursTwelve, now), "3h 12m")
        }

        function test_plain_width_matches_plaintext_twin() {
            verify(guardedAuto.implicitWidth === guardedPlain.implicitWidth)
            verify(unguarded.implicitWidth !== guardedPlain.implicitWidth)
        }

        function test_tooltip_window() {
            var now = Date.parse("2023-11-14T13:46:40Z")
            var top = {
                provider: "codex",
                providerName: "Codex",
                accountName: "work",
                kind: "window",
                label: "Weekly",
                used: 0.81,
                resetsAt: new Date(now + (5 * 86400 + 2 * 3600) * 1000).toISOString(),
                fetchedAt: new Date(now - 20 * 60 * 1000).toISOString()
            }
            var text = Format.tooltip(top, now, true)
            compare(text, "Agent Desk · Codex · work · weekly 81% · resets in 5d 2h · stale · 20 min ago")
        }
    }
}
