.pragma library

// Pure keyboard model. Phase 1 is list mode: cursor walk, set-active, refresh, Escape.

// Fresh list-mode keyboard state.
function createState() {
    return { mode: "list", cursorIndex: 0 }
}

// Visual card list across enabled provider sections, imported then isolated.
function cards(snapshot) {
    var out = []
    if (!snapshot) return out
    var providers = snapshot.providers || []
    var accounts = (snapshot.state && snapshot.state.accounts) ? snapshot.state.accounts : []
    for (var i = 0; i < providers.length; i++) {
        var p = providers[i]
        if (p.enabled === false) continue
        var group = []
        for (var j = 0; j < accounts.length; j++) {
            if (accounts[j].provider === p.id) group.push(accounts[j])
        }
        var imported = []
        var isolated = []
        for (var k = 0; k < group.length; k++) {
            if (group[k].kind === "imported") imported.push(group[k])
            else isolated.push(group[k])
        }
        isolated.sort(function(a, b) { return String(a.createdAt || "").localeCompare(String(b.createdAt || "")) })
        var ordered = imported.concat(isolated)
        for (var c = 0; c < ordered.length; c++) {
            out.push({
                providerId: p.id,
                accountId: ordered[c].id,
                sectionIndex: i,
                notInstalled: false
            })
        }
        if (ordered.length === 0) {
            out.push({
                providerId: p.id,
                accountId: null,
                sectionIndex: i,
                notInstalled: p.installed === false
            })
        }
    }
    return out
}

// Focus the active card of the first provider, else the first row.
function focusOnOpen(state, snapshot) {
    var list = cards(snapshot)
    var target = snapshot && snapshot.state && snapshot.state.active
        ? snapshot.state.active[snapshot.firstProviderId]
        : null
    var idx = 0
    if (target) {
        for (var i = 0; i < list.length; i++) {
            if (list[i].accountId === target) { idx = i; break }
        }
    }
    state.cursorIndex = idx
    state.mode = "list"
    return state
}

// j/k walk cards (wrap); h/l jump to the first card of the next/previous section.
function move(state, dx, dy, snapshot) {
    var list = cards(snapshot)
    if (list.length === 0) return { state: state, action: null }
    if (dy !== 0) {
        var next = state.cursorIndex + dy
        next = ((next % list.length) + list.length) % list.length
        state.cursorIndex = next
        return { state: state, action: { type: "cursor" } }
    }
    if (dx !== 0) {
        var current = list[state.cursorIndex] || list[0]
        var want = current.sectionIndex + dx
        for (var i = 0; i < list.length; i++) {
            var idx = dx > 0 ? i : list.length - 1 - i
            if (dx > 0 && list[idx].sectionIndex >= want && list[idx].sectionIndex !== current.sectionIndex) {
                state.cursorIndex = idx
                return { state: state, action: { type: "cursor" } }
            }
            if (dx < 0 && list[idx].sectionIndex <= want && list[idx].sectionIndex !== current.sectionIndex) {
                var first = idx
                while (first > 0 && list[first - 1].sectionIndex === list[idx].sectionIndex) first--
                state.cursorIndex = first
                return { state: state, action: { type: "cursor" } }
            }
        }
    }
    return { state: state, action: null }
}

// Enter/Space: set the focused card active.
function activate(state, snapshot) {
    var list = cards(snapshot)
    var card = list[state.cursorIndex]
    if (!card || !card.accountId) return { type: "noop" }
    return { type: "set-active", accountId: card.accountId }
}

// Escape closes the panel in list mode.
function closeRequested(state) {
    return { type: "close" }
}

// Letter keys. Phase 1 honors r (refresh).
function textKey(state, t, snapshot) {
    if (t === "r" || t === "R") return { type: "refresh" }
    return null
}
