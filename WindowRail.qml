import QtQuick
import qs.Commons
import qs.Ui
import "Format.js" as Format

// One rail: label, 4 px meter, percent, countdown/exact-time swap.

Item {
    id: root

    property var window: null
    property var balance: null
    property double nowMs: Date.now()
    property color foreground: Color.foreground
    property color urgent: Color.urgent
    property color track: Style.selectedFillFor(foreground, Color.accent)
    property string fontFamily: Style.font.family
    property real warningThreshold: 0.75
    property real criticalThreshold: 0.90

    readonly property real used: {
        if (balance) return Number(balance.used || 0)
        if (window) return Number(window.used || 0)
        return 0
    }
    readonly property bool alarming: used >= criticalThreshold
    readonly property real thickness: Math.max(Style.space(4), Math.round(Style.spacing.controlHeight * 0.14))

    implicitHeight: Math.max(label.implicitHeight, percentLabel.implicitHeight) + thickness + Style.space(6) + caption.implicitHeight
    implicitWidth: 200

    Text {
        id: label
        anchors.left: parent.left
        anchors.top: parent.top
        text: Format.plain(root.balance ? "Balance" : String((root.window && root.window.label) || ""))
        textFormat: Text.PlainText
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
    }

    Text {
        id: percentLabel
        anchors.right: parent.right
        anchors.top: parent.top
        text: Format.percent(root.used) + "%"
        textFormat: Text.PlainText
        color: root.alarming ? root.urgent : root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
    }

    Item {
        id: meter
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: label.bottom
        anchors.topMargin: Style.space(2)
        height: root.thickness

        Rectangle {
            id: meterTrack
            anchors.fill: parent
            radius: height / 2
            color: root.track
        }

        Rectangle {
            anchors.left: meterTrack.left
            anchors.verticalCenter: meterTrack.verticalCenter
            height: meterTrack.height
            radius: meterTrack.radius
            width: meterTrack.width * Math.max(0, Math.min(1, root.used))
            color: root.alarming ? root.urgent : root.foreground
            Behavior on width {
                NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
            }
        }
    }

    Text {
        id: caption
        textFormat: Text.PlainText
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: meter.bottom
        anchors.topMargin: Style.space(2)
        text: {
            if (hover.containsMouse && root.window && root.window.resetsAt)
                return Format.exactReset(root.window.resetsAt)
            if (root.balance) return Format.balance(root.balance)
            if (root.window && root.window.resetsAt) return Format.countdown(root.window.resetsAt, root.nowMs)
            return ""
        }
        color: Qt.darker(root.foreground, 1.4)
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
    }

    MouseArea {
        id: hover
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
    }
}
