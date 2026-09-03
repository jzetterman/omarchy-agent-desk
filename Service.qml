import QtQuick
import Quickshell
import Quickshell.Io

// Runner bridge: Process + SplitParser, snapshot property, restart policy.

Item {
    id: root

    property var settings: ({})
    property string pluginDir: ""

    property var snapshot: ({
        state: { accounts: [], active: ({}), routing: { installed: false } },
        records: ({}),
        providers: [],
        firstProviderId: null,
        readout: { used: null, level: "none", top: null },
        pathProbe: "pending",
        login: null,
        providerErrors: [],
        error: null,
        generation: 0
    })

    property string captionText: ""
    property var exitTimes: []
    property int lockRetries: 0
    property int restartBackoffMs: 1000

    function settingsCommand() {
        return {
            cmd: "settings",
            refreshIntervalSec: settings.refreshIntervalSec,
            providerOrder: settings.providerOrder,
            providerEnabled: settings.providerEnabled,
            warningThreshold: settings.warningThreshold,
            criticalThreshold: settings.criticalThreshold,
            readoutScope: settings.readoutScope
        }
    }

    function send(obj) {
        if (!proc.running) {
            if (obj && obj.cmd === "refresh") {
                exitTimes = []
                lockRetries = 0
                proc.running = true
            }
            return
        }
        proc.write(JSON.stringify(obj) + "\n")
    }

    function handleLine(line) {
        var parsed
        try { parsed = JSON.parse(line) } catch (e) { return }
        if (!parsed || !parsed.event) return
        if (parsed.event === "snapshot") {
            root.snapshot = parsed
        } else if (parsed.event === "caption") {
            root.captionText = parsed.text || ""
        }
    }

    function scheduleRestart(exitCode) {
        if (exitCode === 75) {
            lockRetries += 1
            if (lockRetries > 10) {
                var locked = Object.assign({}, root.snapshot)
                locked.error = "runner-locked"
                root.snapshot = locked
            }
            restartTimer.interval = 1000
            restartTimer.restart()
            return
        }
        lockRetries = 0
        var now = Date.now()
        var kept = []
        for (var i = 0; i < exitTimes.length; i++) {
            if (now - exitTimes[i] < 60000) kept.push(exitTimes[i])
        }
        kept.push(now)
        exitTimes = kept
        if (kept.length >= 5) {
            var stopped = Object.assign({}, root.snapshot)
            stopped.error = "runner-stopped"
            root.snapshot = stopped
            return
        }
        restartTimer.interval = Math.min(30000, 1000 * Math.pow(2, kept.length - 1))
        restartTimer.restart()
    }

    function onStarted() {
        send(settingsCommand())
        send({ cmd: "snapshot" })
    }

    onSettingsChanged: {
        if (proc.running)
            send(settingsCommand())
    }

    Process {
        id: proc
        command: ["python3", root.pluginDir + "/bin/agent-desk-runner", "serve"]
        stdinEnabled: true
        running: root.pluginDir !== ""
        stdout: SplitParser {
            onRead: function(data) { root.handleLine(data) }
        }
        onStarted: root.onStarted()
        onExited: function(exitCode, exitStatus) { root.scheduleRestart(exitCode) }
    }

    Timer {
        id: restartTimer
        interval: 1000
        repeat: false
        onTriggered: proc.running = true
    }
}
