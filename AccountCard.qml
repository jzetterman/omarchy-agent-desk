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
    property real warningThreshold: 0.75
    property real criticalThreshold: 0.90
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

    implicitHeight: stack.implicitHeight + Style.spacing.rowPaddingX
    implicitWidth: 200

    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton
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
                if (ident.email) return String(ident.email)
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
            visible: root.stale
            text: Format.plain("stale" + (root.record && root.record.fetchedAt ? (" · " + Format.ago(root.record.fetchedAt, root.nowMs)) : ""))
            textFormat: Text.PlainText
            color: Qt.darker(root.foreground, 1.4)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
        }

        Column {
            width: parent.width
            spacing: Style.space(6)
            visible: root.loading

            Repeater {
                model: 3
                Rectangle {
                    width: parent.width
                    height: Math.max(Style.space(4), Math.round(Style.spacing.controlHeight * 0.14))
                    radius: height / 2
                    color: Style.selectedFillFor(root.foreground, Color.accent)
                }
            }
        }

        Text {
            width: parent.width
            visible: root.status === "no-limits"
            text: Format.plain(String((root.record && root.record.help) || "No rate limits on this plan"))
            textFormat: Text.PlainText
            color: Qt.darker(root.foreground, 1.4)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
        }

        Column {
            width: parent.width
            spacing: Style.space(6)
            visible: !root.loading && (root.status === "ok" || root.status === "rate-limited" || root.status === "offline" || root.status === "failed") && root.windows.length > 0

            Repeater {
                model: root.windows
                WindowRail {
                    required property var modelData
                    width: parent.width
                    window: modelData
                    nowMs: root.nowMs
                    foreground: root.foreground
                    urgent: root.urgent
                    fontFamily: root.fontFamily
                    warningThreshold: root.warningThreshold
                    criticalThreshold: root.criticalThreshold
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
                warningThreshold: root.warningThreshold
                criticalThreshold: root.criticalThreshold
                track: Style.selectedFillFor(root.foreground, Color.accent)
            }
        }

        BorderSurface {
            width: parent.width
            visible: root.status === "not-signed-in" || root.status === "expired" || root.status === "rate-limited" || root.status === "offline" || root.status === "failed"
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
                    var help = root.record && root.record.help ? String(root.record.help) : root.status
                    return help
                }
            }
        }
    }
}
