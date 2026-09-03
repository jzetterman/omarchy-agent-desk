import QtQuick
import QtTest
import "../../Keys.js" as Keys

Item {
    width: 100
    height: 100

    TestCase {
        name: "KeysListMode"

        function sampleSnapshot() {
            return {
                state: {
                    accounts: [
                        { id: "aa" + "0".repeat(30), provider: "claude", kind: "imported", name: "personal", createdAt: "t1" },
                        { id: "bb" + "0".repeat(30), provider: "claude", kind: "isolated", name: "work", createdAt: "t2" },
                        { id: "cc" + "0".repeat(30), provider: "codex", kind: "imported", name: "default", createdAt: "t3" }
                    ],
                    active: { claude: "aa" + "0".repeat(30), codex: "cc" + "0".repeat(30) }
                },
                providers: [
                    { id: "claude", name: "Claude Code", enabled: true, installed: true },
                    { id: "codex", name: "Codex", enabled: true, installed: true }
                ],
                firstProviderId: "claude"
            }
        }

        function test_cursor_walk_and_wrap() {
            var snap = sampleSnapshot()
            var state = Keys.createState()
            state = Keys.focusOnOpen(state, snap)
            compare(Keys.cards(snap)[state.cursorIndex].accountId, "aa" + "0".repeat(30))
            var r = Keys.move(state, 0, 1, snap)
            compare(r.state.cursorIndex, 1)
            r = Keys.move(r.state, 0, 1, snap)
            compare(r.state.cursorIndex, 2)
            r = Keys.move(r.state, 0, 1, snap)
            compare(r.state.cursorIndex, 0)
        }

        function test_section_jump() {
            var snap = sampleSnapshot()
            var state = Keys.focusOnOpen(Keys.createState(), snap)
            var r = Keys.move(state, 1, 0, snap)
            compare(Keys.cards(snap)[r.state.cursorIndex].providerId, "codex")
            r = Keys.move(r.state, -1, 0, snap)
            compare(Keys.cards(snap)[r.state.cursorIndex].providerId, "claude")
        }

        function test_activate_sets_active() {
            var snap = sampleSnapshot()
            var state = Keys.focusOnOpen(Keys.createState(), snap)
            state = Keys.move(state, 0, 1, snap).state
            var action = Keys.activate(state, snap)
            compare(action.type, "set-active")
            compare(action.accountId, "bb" + "0".repeat(30))
        }

        function test_escape_closes() {
            var state = Keys.createState()
            var action = Keys.closeRequested(state)
            compare(action.type, "close")
        }

        function test_r_refreshes() {
            var action = Keys.textKey(Keys.createState(), "r", sampleSnapshot())
            compare(action.type, "refresh")
        }

        function test_move_and_focus_return_fresh_state() {
            var snap = sampleSnapshot()
            var state = Keys.createState()
            var focused = Keys.focusOnOpen(state, snap)
            verify(focused !== state)
            compare(state.cursorIndex, 0)
            var moved = Keys.move(focused, 0, 1, snap)
            verify(moved.state !== focused)
            compare(focused.cursorIndex, 0)
            compare(moved.state.cursorIndex, 1)
        }

        function test_cards_filter_only_no_sort() {
            var snap = sampleSnapshot()
            snap.state.accounts = [
                { id: "bb" + "0".repeat(30), provider: "claude", kind: "isolated", name: "work", createdAt: "t2" },
                { id: "aa" + "0".repeat(30), provider: "claude", kind: "imported", name: "personal", createdAt: "t1" }
            ]
            var list = Keys.cards(snap)
            compare(list[0].accountId, "bb" + "0".repeat(30))
            compare(list[1].accountId, "aa" + "0".repeat(30))
        }
    }
}
