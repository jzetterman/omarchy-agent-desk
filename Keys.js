.pragma library

// Pure keyboard model. Phase 1 is list mode: cursor walk, set-active, refresh, Escape.

function _copyState(state) {
    return { mode: state && state.mode ? state.mode : "list", cursorIndex: state && state.cursorIndex ? state.cursorIndex : 0 }
}

// Fresh list-mode keyboard state.
function createState() {
    return { mode: "list", cursorIndex: 0 }
}

// One owner of the state shape: hover and keys both go through here.
function setCursor(state, index) {
    var next = _copyState(state)
    next.cursorIndex = index
    return next
}

// One predicate for "this section holds cards": Panel's card repeater and
// visualIndex use it too, so the cursor never counts a hidden card.
function showsCards(provider) {
    return !!provider && provider.enabled !== false && provider.installed !== false
}

// Visual card list across provider sections that show cards. Accounts are
// already in card order in the snapshot; this only filters by provider. A
// section with no accounts contributes no row, so j/k and h/l skip it (R26).
function cards(snapshot) {
    var out = []
    if (!snapshot) return out
    var providers = snapshot.providers || []
    var accounts = (snapshot.state && snapshot.state.accounts) ? snapshot.state.accounts : []
    for (var i = 0; i < providers.length; i++) {
        var p = providers[i]
        if (!showsCards(p)) continue
        var ordered = []
        for (var j = 0; j < accounts.length; j++) {
            if (accounts[j].provider === p.id) ordered.push(accounts[j])
        }
        for (var c = 0; c < ordered.length; c++) {
            out.push({ providerId: p.id, accountId: ordered[c].id, sectionIndex: i })
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
    var next = _copyState(state)
    next.cursorIndex = idx
    next.mode = "list"
    return next
}

// j/k walk cards (wrap); h/l jump to the first card of the next/previous
// section that has cards (no wrap).
function move(state, dx, dy, snapshot) {
    var list = cards(snapshot)
    var next = _copyState(state)
    if (list.length === 0) return { state: next, action: null }
    if (dy !== 0) {
        var wrapped = next.cursorIndex + dy
        wrapped = ((wrapped % list.length) + list.length) % list.length
        next.cursorIndex = wrapped
        return { state: next, action: { type: "cursor" } }
    }
    if (dx !== 0) {
        var current = list[next.cursorIndex] || list[0]
        var want = current.sectionIndex + dx
        for (var i = 0; i < list.length; i++) {
            var idx = dx > 0 ? i : list.length - 1 - i
            if (dx > 0 && list[idx].sectionIndex >= want && list[idx].sectionIndex !== current.sectionIndex) {
                next.cursorIndex = idx
                return { state: next, action: { type: "cursor" } }
            }
            if (dx < 0 && list[idx].sectionIndex <= want && list[idx].sectionIndex !== current.sectionIndex) {
                var first = idx
                while (first > 0 && list[first - 1].sectionIndex === list[idx].sectionIndex) first--
                next.cursorIndex = first
                return { state: next, action: { type: "cursor" } }
            }
        }
    }
    return { state: next, action: null }
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
