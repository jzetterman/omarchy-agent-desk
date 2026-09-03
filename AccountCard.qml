import QtQuick
import qs.Commons
import qs.Ui
import "Format.js" as Format

// One account card: name, meta, active mark, rails, and designed status states.

CursorSurface {
    id: root

    property var account: ({})
    property var record: null
    property var provider: ({})
    property double nowMs: Date.now()
    property int refreshIntervalSec: 900
    property color urgent: Color.urgent
    property string fontFamily: Style.font.family
    property int cardIndex: 0

    signal activated()
    signal hoveredCard(int index)

    current: isActive
    property bool isActive: false

    readonly property string status: record && record.status ? record.status : ""
    readonly property bool stale: {
        if (!record || !record.fetchedAt) return false
        var t = Date.parse(record.fetchedAt)
        if (!isFinite(t)) return false
        return (nowMs - t) / 1000 > refreshIntervalSec
    }
    readonly property var windows: record && record.windows ? record.windows : []
    readonly property bool loading: record === null || record === undefined
    property var railIds: []

    readonly property var statusLabels: ({
        "not-signed-in": "Not signed in",
        "expired": "Sign-in expired",
        "rate-limited": "Rate limited",
        "offline": "Offline",
        "failed": "Failed"
    })
    readonly property bool statusStripHasAge: {
        var s = root.status
        return (s === "rate-limited" || s === "offline" || s === "failed")
            && !!(root.record && root.record.fetchedAt)
    }

    onWindowsChanged: syncRailIds()
    Component.onCompleted: syncRailIds()

    function syncRailIds() {
        var w = windows
        var ids = []
        for (var i = 0; i < w.length; i++) ids.push(w[i].id || String(i))
        if (ids.join("\n") !== railIds.join("\n"))
            railIds = ids
    }

    function windowById(wid) {
        var w = windows
        for (var i = 0; i < w.length; i++) {
            if ((w[i].id || String(i)) === wid) return w[i]
        }
        return null
    }

    implicitHeight: stack.implicitHeight + Style.spacing.rowPaddingX
    implicitWidth: parent ? parent.width : 0

    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton
        cursorShape: Qt.PointingHandCursor
        onClicked: root.activated()
        onEntered: root.hoveredCard(root.cardIndex)
    }

    Column {
        id: stack
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: Style.space(10)
        anchors.rightMargin: Style.space(10)
        anchors.topMargin: Style.spacing.rowPaddingX / 2
        spacing: Style.space(1)

        Item {
            width: parent.width
            height: Math.max(nameLabel.implicitHeight, activeMark.implicitHeight)

            Text {
                id: nameLabel
                anchors.left: parent.left
                anchors.right: activeMark.left
                anchors.rightMargin: Style.space(6)
                anchors.verticalCenter: parent.verticalCenter
                text: Format.plain(String((root.account && root.account.name) || ""))
                textFormat: Text.PlainText
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                font.bold: true
                elide: Text.ElideRight
            }

            Text {
                id: activeMark
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                visible: root.isActive
                text: "󰄬"
                textFormat: Text.PlainText
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.icon
            }
        }

        Text {
            id: meta
            width: parent.width
            visible: metaText !== ""
            text: Format.plain(metaText)
            textFormat: Text.PlainText
            color: Qt.darker(root.foreground, 1.4)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
            readonly property string metaText: {
                var ident = root.record && root.record.identity ? root.record.identity : null
                if (!ident) return ""
                var name = String((root.account && root.account.name) || "")
                // R21: email only when it differs from the name; else org; else nothing.
                if (ident.email && String(ident.email) !== name) return String(ident.email)
                if (ident.org) return String(ident.org)
                return ""
            }
        }

        Text {
            width: parent.width
            visible: !!(root.record && root.record.sameAccountAs)
            text: Format.plain(root.record && root.record.sameAccountAs ? ("same account as " + String(root.record.sameAccountAs.name || "")) : "")
            textFormat: Text.PlainText
            color: Qt.darker(root.foreground, 1.4)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
        }

        Text {
            width: parent.width
            visible: root.stale && !root.statusStripHasAge
            text: Format.plain("stale" + (root.record && root.record.fetchedAt ? (" · " + Format.ago(root.record.fetchedAt, root.nowMs)) : ""))
            textFormat: Text.PlainText
            color: Qt.darker(root.foreground, 1.4)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
        }

        Text {
            width: parent.width
            visible: root.status === "no-limits"
            text: Format.plain(String((root.record && root.record.help) || ""))
            textFormat: Text.PlainText
            color: Qt.darker(root.foreground, 1.4)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
        }

        Column {
            width: parent.width
            spacing: Style.space(6)
            visible: root.loading
            topPadding: Style.space(5)

            Repeater {
                model: 3
                Column {
                    width: parent.width
                    spacing: Style.space(4)

                    Rectangle {
                        width: parent.width * 0.4
                        height: Style.font.body
                        radius: 2
                        color: Style.selectedFillFor(root.foreground, Color.accent)
                    }
                    Rectangle {
                        width: parent.width
                        height: Math.max(Style.space(4), Math.round(Style.spacing.controlHeight * 0.14))
                        radius: height / 2
                        color: Style.selectedFillFor(root.foreground, Color.accent)
                    }
                    Rectangle {
                        width: parent.width * 0.3
                        height: Style.font.caption
                        radius: 2
                        color: Style.selectedFillFor(root.foreground, Color.accent)
                    }
                }
            }
        }

        Column {
            width: parent.width
            spacing: Style.space(6)
            topPadding: Style.space(5)
            visible: !root.loading && (root.status === "ok" || root.status === "rate-limited" || root.status === "offline" || root.status === "failed") && root.windows.length > 0

            Repeater {
                model: root.railIds
                WindowRail {
                    required property var modelData
                    width: parent.width
                    window: root.windowById(modelData)
                    nowMs: root.nowMs
                    foreground: root.foreground
                    urgent: root.urgent
                    fontFamily: root.fontFamily
                    track: Style.selectedFillFor(root.foreground, Color.accent)
                }
            }

            WindowRail {
                visible: !!(root.record && root.record.balance)
                width: parent.width
                balance: root.record ? root.record.balance : null
                nowMs: root.nowMs
                foreground: root.foreground
                urgent: root.urgent
                fontFamily: root.fontFamily
                track: Style.selectedFillFor(root.foreground, Color.accent)
            }
        }

        BorderSurface {
            width: parent.width
            visible: !!statusLine.statusText
            color: Util.alpha(root.urgent, 0.10)
            borderSpec: Border.flat(Util.alpha(root.urgent, 0.35), 1)
            implicitHeight: statusLine.implicitHeight + Style.space(8)

            Text {
                id: statusLine
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Style.space(8)
                anchors.rightMargin: Style.space(8)
                text: Format.plain(statusText)
                textFormat: Text.PlainText
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                wrapMode: Text.WordWrap
                readonly property string statusText: {
                    var label = root.statusLabels[root.status] || ""
                    if (!label) return ""
                    if (root.statusStripHasAge)
                        return label + " · " + Format.ago(root.record.fetchedAt, root.nowMs)
                    return label
                }
            }
        }
    }
}
