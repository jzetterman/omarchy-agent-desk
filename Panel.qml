import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Format.js" as Format
import "Keys.js" as Keys

// Bar icon, readout, and Claude usage panel. Root is qs.Ui.Panel.

Panel {
    id: root
    moduleName: "io.github.jzetterman.agent-desk"
    ipcTarget: "io.github.jzetterman.agent-desk"
    manageIpc: false

    readonly property color foreground: bar ? bar.foreground : Color.foreground
    readonly property color urgent: bar ? bar.urgent : Color.urgent
    readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
    readonly property string pluginDir: resolvePluginDir()

    property double nowMs: Date.now()
    property var keyState: Keys.createState()
    property bool cursorActive: false
    property bool captionLatched: false
    property string latchedCaption: ""

    readonly property var validated: validatedSettings()
    readonly property var snap: desk.snapshot
    readonly property var readout: (snap && snap.readout) ? snap.readout : { used: null, level: "none", top: null }
    readonly property bool readoutOn: validated.readout === true
    readonly property bool showReadout: readoutOn && !root.vertical && readout.used !== null && readout.used !== undefined
    readonly property bool staleTop: {
        if (!readout.top || !readout.top.fetchedAt) return false
        var t = Date.parse(readout.top.fetchedAt)
        if (!isFinite(t)) return false
        return (nowMs - t) / 1000 > validated.refreshIntervalSec
    }

    implicitWidth: barRow.implicitWidth
    implicitHeight: barRow.implicitHeight

    // Plugin directory from this file's URL so the runner path is local.
    function resolvePluginDir() {
        var url = String(Qt.resolvedUrl("."))
        if (url.indexOf("file://") === 0) url = url.substring(7)
        if (url.length > 1 && url.charAt(url.length - 1) === "/")
            url = url.substring(0, url.length - 1)
        return url
    }

    // Clamp and default every C.6 setting. Defaults live here because the shell ignores the manifest.
    function validatedSettings() {
        var interval = Number(setting("refreshIntervalSec", 900))
        if (!isFinite(interval)) interval = 900
        if (interval < 60) interval = 60
        var warning = Number(setting("warningThreshold", 0.75))
        if (!isFinite(warning)) warning = 0.75
        var critical = Number(setting("criticalThreshold", 0.90))
        if (!isFinite(critical)) critical = 0.90
        if (warning < 0) warning = 0
        if (warning > 1) warning = 1
        if (critical < 0) critical = 0
        if (critical > 1) critical = 1
        if (warning > critical) warning = critical
        var readoutFlag = setting("readout", true)
        if (typeof readoutFlag !== "boolean") readoutFlag = true
        var scope = setting("readoutScope", "active")
        if (scope !== "active" && scope !== "all") scope = "active"
        var order = setting("providerOrder", ["claude", "codex", "grok"])
        if (!Array.isArray(order)) order = ["claude", "codex", "grok"]
        var cleaned = []
        var seen = {}
        for (var i = 0; i < order.length; i++) {
            if (typeof order[i] !== "string") continue
            if (seen[order[i]]) continue
            seen[order[i]] = true
            cleaned.push(order[i])
        }
        var enabled = setting("providerEnabled", {})
        if (typeof enabled !== "object" || enabled === null || Array.isArray(enabled)) enabled = {}
        var enabledClean = {}
        for (var key in enabled) {
            if (typeof enabled[key] === "boolean") enabledClean[key] = enabled[key]
        }
        return {
            refreshIntervalSec: interval,
            warningThreshold: warning,
            criticalThreshold: critical,
            readout: readoutFlag,
            readoutScope: scope,
            providerOrder: cleaned,
            providerEnabled: enabledClean
        }
    }

    // sRGB channel to linear luminance, used to pick the light-surface mark.
    function colorChannelLuminance(value) {
        var channel = Number(value)
        if (!isFinite(channel)) return 0
        return channel <= 0.03928 ? channel / 12.92 : Math.pow((channel + 0.055) / 1.055, 2.4)
    }

    // Rec. 709 luminance of a Qt color.
    function colorLuminance(color) {
        return 0.2126 * colorChannelLuminance(color.r)
            + 0.7152 * colorChannelLuminance(color.g)
            + 0.0722 * colorChannelLuminance(color.b)
    }

    // Plugin mark, light twin first on a light bar.
    function barMarkSource() {
        var surface = Color.bar.background
        var light = colorLuminance(surface) >= 0.5
        return Qt.resolvedUrl(light ? "assets/agent-desk-light.svg" : "assets/agent-desk.svg")
    }

    // Provider mark path for a section header.
    function sectionMarkSource(p) {
        if (!p) return ""
        var surface = Color.popups.background
        var light = colorLuminance(surface) >= 0.5
        var path = light && p.markLightPath ? p.markLightPath : p.markPath
        return path ? Util.fileUrl(path) : ""
    }

    // Providers in the setting order, then leftover ids sorted.
    function orderedProviders() {
        var list = (snap && snap.providers) ? snap.providers.slice() : []
        var order = validated.providerOrder
        var out = []
        var seen = {}
        for (var i = 0; i < order.length; i++) {
            for (var j = 0; j < list.length; j++) {
                if (list[j].id === order[i] && !seen[list[j].id]) {
                    out.push(list[j])
                    seen[list[j].id] = true
                }
            }
        }
        var rest = []
        for (var k = 0; k < list.length; k++) {
            if (!seen[list[k].id]) rest.push(list[k])
        }
        rest.sort(function(a, b) { return String(a.id).localeCompare(String(b.id)) })
        return out.concat(rest)
    }

    // Card order: imported first, then isolated by createdAt.
    function accountsFor(providerId) {
        var accounts = (snap && snap.state && snap.state.accounts) ? snap.state.accounts : []
        var imported = []
        var isolated = []
        for (var i = 0; i < accounts.length; i++) {
            if (accounts[i].provider !== providerId) continue
            if (accounts[i].kind === "imported") imported.push(accounts[i])
            else isolated.push(accounts[i])
        }
        isolated.sort(function(a, b) { return String(a.createdAt || "").localeCompare(String(b.createdAt || "")) })
        return imported.concat(isolated)
    }

    // Flat visual index of a card, matching Keys.cards.
    function visualIndex(providerId, accountId) {
        var list = Keys.cards(snap)
        for (var i = 0; i < list.length; i++) {
            if (list[i].providerId === providerId && list[i].accountId === accountId) return i
        }
        return -1
    }

    // Run a Keys.State action against the runner or the panel.
    function applyAction(action) {
        if (!action) return
        if (action.type === "set-active") desk.send({ cmd: "set-active", accountId: action.accountId })
        else if (action.type === "refresh") desk.send({ cmd: "refresh", accountId: "all", manual: true })
        else if (action.type === "close") root.close()
        else if (action.type === "cursor") keyState = keyState
    }

    // Default hero caption: account count and last refresh age.
    function liveCaption() {
        var accounts = (snap && snap.state && snap.state.accounts) ? snap.state.accounts : []
        var n = accounts.length
        var latest = 0
        var records = (snap && snap.records) ? snap.records : {}
        for (var id in records) {
            var t = Date.parse(records[id].fetchedAt || records[id].collectedAt || "")
            if (isFinite(t) && t > latest) latest = t
        }
        var age = latest ? Format.ago(new Date(latest).toISOString(), nowMs) : "never"
        return n + " account" + (n === 1 ? "" : "s") + " · refreshed " + age
    }

    // Latched caption wins until the panel closes.
    function heroCaption() {
        if (captionLatched && latchedCaption) return latchedCaption
        return liveCaption()
    }

    onOpenedChanged: {
        if (opened) {
            nowMs = Date.now()
            captionLatched = false
            latchedCaption = ""
            keyState = Keys.focusOnOpen(Keys.createState(), snap)
            cursorActive = false
            desk.send({ cmd: "refresh", accountId: "all", manual: true })
            Qt.callLater(function() { keyCatcher.forceActiveFocus() })
        }
    }

    onSettingsChanged: desk.settings = validatedSettings()

    Connections {
        target: desk
        function onCaptionTextChanged() {
            if (desk.captionText) {
                root.latchedCaption = desk.captionText
                root.captionLatched = true
            }
        }
    }

    Service {
        id: desk
        settings: root.validated
        pluginDir: root.pluginDir
    }

    Row {
        id: barRow
        spacing: Style.space(2)

        BarIconButton {
            id: button
            bar: root.bar
            active: root.readout.level === "critical"
            foreground: root.readout.level === "warning"
                ? Qt.tint(root.bar ? root.bar.barForeground : Color.foreground, Util.alpha(root.urgent, 0.6))
                : (root.bar ? root.bar.barForeground : Color.foreground)
            tooltipText: Format.plain(Format.tooltip(root.readout.top, root.nowMs, root.staleTop))
            iconComponent: Component {
                Image {
                    anchors.fill: parent
                    source: root.barMarkSource()
                    fillMode: Image.PreserveAspectFit
                    sourceSize.width: Style.bar.iconCanvas * 2
                    sourceSize.height: Style.bar.iconCanvas * 2
                }
            }
            onPressed: function(b) {
                if (b === Qt.RightButton) desk.send({ cmd: "refresh", accountId: "all", manual: true })
                else if (b === Qt.MiddleButton) desk.send({ cmd: "next" })
                else root.toggle()
            }
        }

        Text {
            visible: root.showReadout
            anchors.verticalCenter: parent.verticalCenter
            text: Format.percent(root.readout.used) + "%"
            textFormat: Text.PlainText
            color: root.readout.level === "critical" ? root.urgent
                 : (root.readout.level === "warning" ? Qt.tint(root.foreground, Util.alpha(root.urgent, 0.6)) : root.foreground)
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
        }
    }

    Timer {
        interval: 30000
        running: root.opened
        repeat: true
        onTriggered: root.nowMs = Date.now()
    }

    IpcHandler {
        target: root.ipcTarget
        function open(): void { root.open() }
        function close(): void { root.close() }
        function show(): void { root.open() }
        function hide(): void { root.close() }
        function toggle(): void { root.toggle() }
        function refresh(): string {
            desk.send({ cmd: "refresh", accountId: "all", manual: true })
            return "ok"
        }
        function next(): string {
            desk.send({ cmd: "next" })
            return "ok"
        }
    }

    KeyboardPanel {
        id: panel
        anchorItem: button
        owner: root
        bar: root.bar
        open: root.opened
        focusTarget: keyCatcher
        contentWidth: panel.fittedContentWidth(Style.space(380))
        contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(640))

        PanelKeyCatcher {
            id: keyCatcher
            anchors.fill: parent

            onMoveRequested: function(dx, dy) {
                root.cursorActive = true
                var result = Keys.move(root.keyState, dx, dy, root.snap)
                root.keyState = result.state
                root.applyAction(result.action)
            }
            onActivateRequested: root.applyAction(Keys.activate(root.keyState, root.snap))
            onCloseRequested: root.applyAction(Keys.closeRequested(root.keyState))
            onTabRequested: function(direction) { root.switchPanel(direction) }
            onTextKey: function(t) { root.applyAction(Keys.textKey(root.keyState, t, root.snap)) }

            Flickable {
                id: panelFlick
                anchors.fill: parent
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                contentWidth: width
                contentHeight: column.implicitHeight
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                Column {
                    id: column
                    width: panelFlick.width
                    spacing: Style.space(12)

                    Item {
                        id: hero
                        width: parent.width
                        implicitHeight: Math.max(titleRow.implicitHeight + captionLine.implicitHeight + Style.space(6), openBtn.implicitHeight)

                        Text {
                            id: captionLine
                            anchors.left: parent.left
                            anchors.right: openBtn.left
                            anchors.rightMargin: Style.space(8)
                            anchors.top: parent.top
                            text: Format.plain(root.heroCaption())
                            textFormat: Text.PlainText
                            color: Qt.darker(root.foreground, 1.4)
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.caption
                            font.bold: true
                            font.letterSpacing: 1.2
                            elide: Text.ElideRight
                        }

                        Row {
                            id: titleRow
                            anchors.left: parent.left
                            anchors.top: captionLine.bottom
                            anchors.topMargin: Style.space(4)
                            spacing: Style.space(8)

                            Text {
                                text: "Agent"
                                textFormat: Text.PlainText
                                color: root.foreground
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.title
                                font.bold: true
                            }
                            Image {
                                width: 14
                                height: 14
                                anchors.verticalCenter: parent.verticalCenter
                                source: root.barMarkSource()
                                fillMode: Image.PreserveAspectFit
                            }
                            Text {
                                text: "Desk"
                                textFormat: Text.PlainText
                                color: root.foreground
                                font.family: root.fontFamily
                                font.pixelSize: Style.font.title
                                font.bold: true
                            }
                        }

                        Button {
                            id: openBtn
                            anchors.right: parent.right
                            anchors.top: parent.top
                            visible: !!root.snap.firstProviderId
                            text: "Open terminal"
                            iconText: ""
                            bordered: true
                            foreground: root.foreground
                            fontFamily: root.fontFamily
                            onClicked: {
                                var pid = root.snap.firstProviderId
                                var aid = root.snap.state && root.snap.state.active ? root.snap.state.active[pid] : ""
                                if (aid) desk.send({ cmd: "launch", accountId: aid })
                            }
                        }
                    }

                    BorderSurface {
                        width: parent.width
                        visible: root.snap.error === "state-unreadable"
                        color: Util.alpha(root.urgent, 0.10)
                        borderSpec: Border.flat(Util.alpha(root.urgent, 0.35), 1)
                        implicitHeight: recoverText.implicitHeight + Style.space(16)
                        Text {
                            id: recoverText
                            anchors.fill: parent
                            anchors.margins: Style.space(8)
                            text: "Agent Desk state is unreadable · nothing was deleted · fix or move ~/.config/omarchy/agent-desk/state.json"
                            textFormat: Text.PlainText
                            wrapMode: Text.WordWrap
                            color: root.foreground
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.body
                        }
                    }

                    BorderSurface {
                        width: parent.width
                        visible: root.snap.error === "runner-stopped" || root.snap.error === "runner-locked"
                        color: Util.alpha(root.urgent, 0.10)
                        borderSpec: Border.flat(Util.alpha(root.urgent, 0.35), 1)
                        implicitHeight: runnerText.implicitHeight + Style.space(16)
                        Text {
                            id: runnerText
                            anchors.fill: parent
                            anchors.margins: Style.space(8)
                            text: root.snap.error === "runner-locked"
                                ? "Another runner holds runner.lock"
                                : "Runner stopped · see runner.log"
                            textFormat: Text.PlainText
                            wrapMode: Text.WordWrap
                            color: root.foreground
                            font.family: root.fontFamily
                            font.pixelSize: Style.font.body
                        }
                    }

                    Repeater {
                        id: sectionRepeater
                        model: root.snap.error === "state-unreadable" ? [] : root.orderedProviders()

                        Column {
                            id: section
                            required property var modelData
                            required property int index
                            width: column.width
                            spacing: Style.space(10)
                            visible: modelData.enabled !== false

                            Row {
                                spacing: Style.space(8)
                                Image {
                                    width: 12
                                    height: 12
                                    anchors.verticalCenter: parent.verticalCenter
                                    source: root.sectionMarkSource(section.modelData)
                                    fillMode: Image.PreserveAspectFit
                                }
                                PanelSectionHeader {
                                    text: Format.plain(String(section.modelData.name || "").toUpperCase())
                                    foreground: root.foreground
                                    fontFamily: root.fontFamily
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: {
                                        var accts = root.accountsFor(section.modelData.id)
                                        var activeId = root.snap.state && root.snap.state.active ? root.snap.state.active[section.modelData.id] : ""
                                        var rec = activeId && root.snap.records ? root.snap.records[activeId] : null
                                        var plan = rec && rec.identity ? rec.identity.plan : ""
                                        return Format.plain(plan || "")
                                    }
                                    textFormat: Text.PlainText
                                    color: Qt.darker(root.foreground, 1.4)
                                    font.family: root.fontFamily
                                    font.pixelSize: Style.font.caption
                                }
                            }

                            BorderSurface {
                                width: parent.width
                                visible: section.modelData.installed === false
                                implicitHeight: hintText.implicitHeight + Style.space(16)
                                Text {
                                    id: hintText
                                    anchors.fill: parent
                                    anchors.margins: Style.space(8)
                                    text: Format.plain(String(section.modelData.installHint || ""))
                                    textFormat: Text.PlainText
                                    wrapMode: Text.WordWrap
                                    color: root.foreground
                                    font.family: root.fontFamily
                                    font.pixelSize: Style.font.body
                                }
                            }

                            Repeater {
                                model: section.modelData.installed === false ? [] : root.accountsFor(section.modelData.id)
                                AccountCard {
                                    required property var modelData
                                    required property int index
                                    width: section.width
                                    account: modelData
                                    record: root.snap.records ? root.snap.records[modelData.id] : null
                                    provider: section.modelData
                                    nowMs: root.nowMs
                                    refreshIntervalSec: root.validated.refreshIntervalSec
                                    warningThreshold: root.validated.warningThreshold
                                    criticalThreshold: root.validated.criticalThreshold
                                    urgent: root.urgent
                                    fontFamily: root.fontFamily
                                    foreground: root.foreground
                                    isActive: root.snap.state && root.snap.state.active && root.snap.state.active[section.modelData.id] === modelData.id
                                    cardIndex: root.visualIndex(section.modelData.id, modelData.id)
                                    hasCursor: root.cursorActive && root.keyState.cursorIndex === cardIndex
                                    onActivated: desk.send({ cmd: "set-active", accountId: modelData.id })
                                    onHoveredCard: function(idx) {
                                        root.cursorActive = true
                                        var s = root.keyState
                                        s.cursorIndex = idx
                                        root.keyState = s
                                    }
                                }
                            }

                            PanelSeparator {
                                visible: section.index < sectionRepeater.count - 1
                                foreground: root.foreground
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        visible: {
                            var list = root.orderedProviders()
                            if (list.length === 0) return true
                            for (var i = 0; i < list.length; i++) if (list[i].enabled !== false) return false
                            return true
                        }
                        text: "Enable a provider: omarchy bar set io.github.jzetterman.agent-desk providerEnabled"
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        color: Qt.darker(root.foreground, 1.4)
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.body
                    }
                }
            }
        }
    }
}
