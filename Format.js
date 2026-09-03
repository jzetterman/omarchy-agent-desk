.pragma library

// Countdown, percent rounding, tooltip text, and the R31 markup guard.

// Integer percent, round half up from used × 100.
function percent(used) {
    var n = Number(used)
    if (!isFinite(n) || n < 0) return 0
    if (n > 1) n = 1
    return Math.round(n * 100)
}

// Largest two units down to minutes. minuteLabel is "m" or " min".
function twoUnits(totalMin, minuteLabel) {
    var days = Math.floor(totalMin / (60 * 24))
    var hours = Math.floor((totalMin % (60 * 24)) / 60)
    var mins = totalMin % 60
    var parts = []
    if (days > 0) parts.push(days + "d")
    if (hours > 0 && parts.length < 2) parts.push(hours + "h")
    if (mins > 0 && parts.length < 2) parts.push(mins + minuteLabel)
    return parts.join(" ")
}

// Largest two units down to minutes. Under one minute is "1m". Past is "resetting".
function countdown(resetsAt, nowMs) {
    var t = Date.parse(resetsAt)
    if (!isFinite(t)) return ""
    var ms = t - nowMs
    if (!(ms > 0)) return "resetting"
    var totalMin = Math.floor(ms / 60000)
    if (totalMin < 1) return "1m"
    return twoUnits(totalMin, "m") || "1m"
}

// Age of a timestamp, same unit rules as countdown. Minutes read "20 min ago".
function ago(fetchedAt, nowMs) {
    var t = Date.parse(fetchedAt)
    if (!isFinite(t)) return ""
    var ms = nowMs - t
    if (!(ms > 0)) return "just now"
    var totalMin = Math.max(1, Math.floor(ms / 60000))
    return (twoUnits(totalMin, " min") || "1 min") + " ago"
}

// Local clock time with timezone name, used on rail hover.
function exactReset(resetsAt) {
    var d = new Date(resetsAt)
    if (isNaN(d.getTime())) return ""
    return d.toLocaleTimeString(Qt.locale(), "h:mm AP t")
}

// Remaining amount with unit, e.g. "6.00 USD" or "6 credits".
function balance(b) {
    if (!b) return ""
    var remaining = Number(b.remaining)
    if (!isFinite(remaining)) remaining = 0
    var precision = parseInt(b.precision, 10)
    if (!isFinite(precision) || precision < 0) precision = 0
    var unit = b.unit ? String(b.unit) : "credits"
    var value = remaining.toFixed(precision)
    return value + " " + unit
}

// Insert U+200B after < and & so kit AutoText cannot flip to rich text.
function plain(s) {
    var text = s === undefined || s === null ? "" : String(s)
    return text.replace(/[<&]/g, function(ch) { return ch + "\u200B" })
}

// Bar hover text: plugin, provider, account, window or balance, optional stale age.
function tooltip(top, nowMs, stale) {
    if (!top) return "Agent Desk"
    var parts = ["Agent Desk"]
    if (top.providerName || top.provider) parts.push(top.providerName || top.provider)
    if (top.accountName) parts.push(top.accountName)
    if (top.kind === "balance") {
        var rem = top.remaining
        var unit = top.unit || "credits"
        var precision = parseInt(top.precision, 10)
        if (!isFinite(precision) || precision < 0) precision = 0
        var shown = isFinite(Number(rem)) ? Number(rem).toFixed(precision) : "0"
        parts.push("remaining " + shown + (unit ? " " + unit : ""))
        if (top.funded && top.spent !== undefined && top.spent !== null)
            parts.push(percent(top.used) + "% used")
    } else {
        var label = String(top.label || "").toLowerCase()
        parts.push(label + " " + percent(top.used) + "%")
        if (top.resetsAt) parts.push("resets in " + countdown(top.resetsAt, nowMs))
    }
    if (stale) parts.push("stale · " + ago(top.fetchedAt, nowMs))
    return parts.join(" · ")
}
