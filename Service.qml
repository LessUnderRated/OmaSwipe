import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Unified workspace management service:
// 1. Registers the three-finger horizontal touchpad swipe for workspaces 1..N.
// 2. Mirrors the 1:1 compositor workspace slide directly to the background wallpaper strip.
// 3. Each workspace permanently owns its theme: window borders and terminals stay in
//    their workspace's theme without flickering during workspace transitions.
// 4. Updating active workspace shifts the wallpaper strip and retints the top bar.
// 5. Updating theme/background on any workspace automatically saves it to that workspace.
Item {
  id: root

  property var shell: null
  property var manifest: null
  property var pluginRegistry: null

  readonly property string home: Quickshell.env("HOME")
  readonly property string pluginDir: home + "/.config/omarchy/plugins/lessunderrated.omaswipe"
  readonly property string configPath: home + "/.config/omarchy/omaswipe.json"
  readonly property string currentBackgroundLink: home + "/.local/state/omarchy/current/background"
  readonly property string currentThemeNamePath: home + "/.local/state/omarchy/current/theme.name"
  readonly property string manifestId: manifest && manifest.id ? manifest.id : "lessunderrated.omaswipe"

  property var config: Model.emptyConfig()
  property var themes: []
  property string currentThemeSlug: ""
  property string currentBackground: ""
  property int appliedWorkspace: 0
  property string appliedTheme: ""
  property int pendingWorkspaceId: 0
  property bool stripReady: false
  property bool tearingDown: false
  property bool wasEnabled: false
  readonly property string uninstallScript: home + "/.config/hypr/lessunderrated.omaswipe.uninstall.py"

  function teardownRuntime() {
    if (root.tearingDown) return
    root.tearingDown = true
    Quickshell.execDetached(["python3", root.uninstallScript, "--unless-enabled"])
  }

  onPluginRegistryChanged: {
    if (root.pluginRegistry && root.pluginRegistry.enabled === true)
      root.wasEnabled = true
  }

  Connections {
    target: root.pluginRegistry
    function onEnabledChanged() {
      if (!root.pluginRegistry) return
      if (root.pluginRegistry.enabled === true) {
        root.wasEnabled = true
        root.tearingDown = false
        return
      }
      if (root.wasEnabled) root.teardownRuntime()
    }
  }
  property bool applyingLook: false
  property bool configReady: false
  property bool initialLoadDone: false
  property var swipeState: ({ mon: "", wsId: 1, offset: 0, active: false })
  property bool swiping: false
  readonly property string swipeMon: swipeState ? (swipeState.mon || "") : ""
  readonly property int swipeWsId: swipeState ? (swipeState.wsId || 1) : 1
  readonly property real swipeOffset: swipeState ? (swipeState.offset || 0) : 0
  property var compositorOffsets: ({})
  property var compositorStates: ({})

  readonly property int workspaceCount: Model.normalizeWorkspaceCount(config.workspaceCount, Model.DEFAULT_WORKSPACES)

  readonly property var wallpaperPaths: {
    var cfg = root.config
    var n = root.workspaceCount
    var out = []
    for (var i = 1; i <= n; i++) {
      var bg = (cfg && cfg.workspaces && cfg.workspaces[String(i)]) ? cfg.workspaces[String(i)].background : ""
      out.push(bg || root.currentBackground || "")
    }
    return out
  }

  readonly property string gestureLua: {
    var persist = ""
    for (var i = 1; i <= root.workspaceCount; i++)
      persist += "hl.workspace_rule({ workspace = \"" + i + "\", persistent = true }) "
    return (
      "hl.config({ gestures = { workspace_swipe_create_new = false, workspace_swipe_forever = false } }) " +
      "if not _G.__omaswipe_ws_persist then " + persist + "_G.__omaswipe_ws_persist = true end " +
      "if not _G.__omaswipe_ws_swipe then " +
      "hl.gesture({ fingers = 3, direction = \"horizontal\", action = \"workspace\" }) " +
      "_G.__omaswipe_ws_swipe = true " +
      "end " +
      "local pl = (os.getenv(\"HOME\") or \"\") .. \"/.config/hypr/plugins/omaswipe-ws-offset.so\" " +
      "local f = io.open(pl, \"r\") if f then f:close() pcall(hl.plugin.load, pl) end " +
      "if _G.__omaswipe_ws_swipe then return \"present\" end return \"registered\""
    )
  }

  readonly property string clearGuardsLua:
    "_G.__omaswipe_ws_swipe = nil _G.__omaswipe_ws_persist = nil "

  property bool gestureRegistered: false
  property int gestureAttempts: 0
  readonly property bool luaReady: Hyprland.usingLua === true

  function registerGesture() {
    if (!luaReady) return
    if (gestureProc.running) return
    gestureProc.running = true
  }

  onLuaReadyChanged: registerGesture()

  function ensureRuntime() {
    if (!setupProc.running) setupProc.running = true
  }

  function syncRules() {
    if (!syncRulesProc.running) syncRulesProc.running = true
  }

  function syncWindows(force) {
    if (force) root.pendingForceSync = true
    if (syncWindowsProc.running) return
    var args = ["python3", root.pluginDir + "/assets.py", "sync-windows"]
    if (root.pendingForceSync) args.push("--force")
    root.pendingForceSync = false
    syncWindowsProc.command = args
    syncWindowsProc.running = true
  }

  function assignment(id) {
    return Model.assignment(root.config, id)
  }

  function currentRegularWorkspace() {
    var ws = Hyprland.focusedWorkspace
    if (!ws) return 1
    var id = Number(ws.id)
    if (!isFinite(id) || id < 1) return root.appliedWorkspace || 1
    return Model.clampWorkspaceId(id, root.workspaceCount)
  }

  function reloadThemes() {
    if (!themesProc.running) themesProc.running = true
  }

  function refreshBackground() {
    if (!backgroundProc.running) backgroundProc.running = true
  }

  property string pendingApplySlug: ""

  function loadTheme(slug) {
    if (!slug) return
    var theme = Model.themeBySlug(root.themes, slug)
    if (theme && theme.colorsRaw) {
      Color.loadColors(theme.colorsRaw)
      Color.loadShell(theme.shellRaw || "")
      if (applyBordersProc.running || applyShellProc.running) {
        root.pendingApplySlug = slug
        return
      }
      root.pendingApplySlug = ""
      applyBordersProc.command = ["python3", root.pluginDir + "/assets.py", "apply-borders", slug]
      applyBordersProc.running = true
      return
    }
    if (applyBordersProc.running || applyShellProc.running) {
      root.pendingApplySlug = slug
      return
    }
    root.pendingApplySlug = ""
    applyShellProc.command = ["python3", root.pluginDir + "/assets.py", "apply-shell", slug]
    applyShellProc.running = true
  }

  function flushPendingTheme() {
    if (!root.pendingApplySlug) return
    var slug = root.pendingApplySlug
    root.pendingApplySlug = ""
    root.loadTheme(slug)
  }

  function saveConfig(next) {
    root.config = next
    saveProc.command = ["python3", "-c",
      "from pathlib import Path\nimport sys\nPath(sys.argv[1]).parent.mkdir(parents=True, exist_ok=True)\nPath(sys.argv[1]).write_text(sys.argv[2])",
      root.configPath, JSON.stringify(next, null, 2) + "\n"]
    saveProc.running = true
  }

  function maybeSeed() {
    if (!root.configReady) return
    if (Model.hasAssignments(root.config)) return
    if (!root.currentThemeSlug || !root.currentBackground) return
    root.saveConfig(Model.seedAll(root.currentThemeSlug, root.currentBackground, root.workspaceCount))
    root.appliedWorkspace = root.currentRegularWorkspace()
    root.appliedTheme = root.currentThemeSlug
    root.syncRules()
    root.syncWindows()
  }

  property string pendingRecordTheme: ""
  Timer {
    id: recordThemeTimer
    interval: 80
    repeat: false
    onTriggered: {
      if (!root.configReady || !root.pendingRecordTheme) return
      var ws = root.currentRegularWorkspace()
      var slugToRecord = root.pendingRecordTheme
      root.pendingRecordTheme = ""
      var bgArg = root.pendingRecordBg || root.currentBackgroundLink
      root.pendingRecordBg = ""
      recordThemeProc.command = ["python3", root.pluginDir + "/assets.py", "record-theme", String(ws), slugToRecord, bgArg]
      recordThemeProc.running = true
    }
  }

  function recordUserThemeChange(newSlug) {
    if (!root.configReady || !newSlug) return
    var ws = root.currentRegularWorkspace()
    var look = root.assignment(ws)
    if (look.theme === newSlug) return
    root.appliedTheme = newSlug
    root.currentThemeSlug = newSlug
    root.pendingRecordTheme = newSlug
    recordThemeTimer.restart()
  }

  property string pendingRecordBg: ""
  Timer {
    id: recordBgTimer
    interval: 80
    repeat: false
    onTriggered: {
      if (!root.configReady || !root.pendingRecordBg) return
      var ws = root.currentRegularWorkspace()
      var bgToRecord = root.pendingRecordBg
      root.pendingRecordBg = ""
      recordBgProc.command = ["python3", root.pluginDir + "/assets.py", "record-background", String(ws), bgToRecord]
      recordBgProc.running = true
    }
  }

  function recordUserBackgroundChange(newBg) {
    if (!root.configReady || !newBg) return
    var ws = root.currentRegularWorkspace()
    var look = root.assignment(ws)
    if (Model.sameBackground(newBg, look.background)) return
    root.pendingRecordBg = newBg
    recordBgTimer.restart()
  }

  function applySwipeOffset(mon, wsId, val, active) {
    if (!mon || !isFinite(val))
      return

    if (!isFinite(wsId) || wsId < 1)
      wsId = (root.swipeState && root.swipeState.wsId) ? root.swipeState.wsId : 1

    root.swipeState = {
      mon: mon,
      wsId: wsId,
      offset: val,
      active: !!active
    }

    if (active) {
      root.swiping = true
      swipeSettleTimer.stop()
    } else {
      if (root.swiping) {
        if (Math.abs(val) < 0.5) {
          root.swiping = false
          swipeSettleTimer.stop()
          applyTimer.restart()
        } else {
          swipeSettleTimer.restart()
        }
      }
    }
  }

  function applyForWorkspace(id, force) {
    id = Model.clampWorkspaceId(id, root.workspaceCount)
    if (root.swiping && !force) {
      root.pendingWorkspaceId = id
      return
    }
    var look = root.assignment(id)
    if (!look.theme && !look.background) {
      root.appliedWorkspace = id
      return
    }
    if (!force && id === root.appliedWorkspace && look.theme === root.appliedTheme && (!look.background || look.background === root.currentBackground))
      return

    root.applyingLook = true
    applyUnlockTimer.restart()

    root.appliedWorkspace = id
    if (look.background && look.background !== root.currentBackground) {
      linkProc.command = ["ln", "-nsf", look.background, root.currentBackgroundLink]
      linkProc.running = true
      root.currentBackground = look.background
    }
    if (look.theme && look.theme !== root.appliedTheme) {
      root.appliedTheme = look.theme
      root.currentThemeSlug = look.theme
      root.loadTheme(look.theme)
    }
    syncWindowsTimer.restart()
  }

  Component.onCompleted: {
    if (root.pluginRegistry && root.pluginRegistry.enabled === true)
      root.wasEnabled = true
    root.ensureRuntime()
    root.registerGesture()
    root.reloadThemes()
    root.refreshBackground()
    forceSyncTimer.restart()
  }

  Component.onDestruction: {
    root.teardownRuntime()
  }

  Connections {
    target: Hyprland

    function onFocusedWorkspaceChanged() {
      var ws = Hyprland.focusedWorkspace
      var id = ws ? Number(ws.id) : 0
      if (id >= 1) root.pendingWorkspaceId = id
      if (!root.swiping) applyTimer.restart()
    }

    function onRawEvent(event) {
      if (event.name === "configreloaded") {
        root.gestureRegistered = false
        root.gestureAttempts = 0
        root.registerGesture()
        return
      }
      if (event.name === "omaswipe_ws_offset") {
        var parts = String(event.data || "").split(",")
        if (parts.length >= 4)
          root.applySwipeOffset(parts[0], parseInt(parts[1], 10), parseFloat(parts[2]), parts[3] === "1")
        else if (parts.length >= 3)
          root.applySwipeOffset(parts[0], parseInt(parts[1], 10), parseFloat(parts[2]), Math.abs(parseFloat(parts[2])) > 0.5)
        else if (parts.length >= 2)
          root.applySwipeOffset(parts[0], root.swipeWsId, parseFloat(parts[1]), Math.abs(parseFloat(parts[1])) > 0.5)
        return
      }
      if (event.name === "workspace") {
        var wid = parseInt(event.data, 10)
        if (isFinite(wid) && wid >= 1) {
          root.pendingWorkspaceId = wid
          if (!root.swiping) {
            var look = root.assignment(Model.clampWorkspaceId(wid, root.workspaceCount))
            if (look.theme && look.theme !== root.appliedTheme) {
              root.appliedTheme = look.theme
              root.currentThemeSlug = look.theme
              root.loadTheme(look.theme)
            }
          }
        }
        if (!root.swiping) applyTimer.restart()
        return
      }
      if (event.name === "openwindow" || event.name === "movewindow" || event.name === "movewindowv2") {
        syncWindowsTimer.restart()
        return
      }
      if (event.name === "focusedmon" || event.name === "createworkspace") {
        if (!root.swiping) applyTimer.restart()
        return
      }
      if (event.name === "configreloaded") {
        root.registerGesture()
        root.syncRules()
        root.syncWindows()
        return
      }
    }
  }

  Timer {
    id: swipeSettleTimer
    interval: 60
    onTriggered: {
      root.swiping = false
      root.swipeState = { mon: "", wsId: root.currentRegularWorkspace(), offset: 0, active: false }
      applyTimer.restart()
    }
  }

  Timer {
    id: applyTimer
    interval: 16
    onTriggered: {
      var id = root.pendingWorkspaceId || root.currentRegularWorkspace()
      root.pendingWorkspaceId = 0
      root.applyForWorkspace(id, false)
    }
  }

  Timer {
    id: applyUnlockTimer
    interval: 300
    onTriggered: root.applyingLook = false
  }

  Timer {
    id: startupTimer
    interval: 1500
    running: true
    onTriggered: root.initialLoadDone = true
  }

  property bool pendingForceSync: false

  Timer {
    id: forceSyncTimer
    interval: 450
    onTriggered: root.syncWindows(true)
  }

  Timer {
    id: syncWindowsTimer
    interval: 60
    onTriggered: {
      if (!root.swiping) root.syncWindows()
    }
  }

  Timer {
    id: stripReadyTimer
    interval: 80
    onTriggered: root.stripReady = true
  }

  FileView {
    path: root.currentBackgroundLink
    watchChanges: true
    printErrors: false
    onFileChanged: root.refreshBackground()
  }

  FileView {
    id: themeNameFile
    path: root.currentThemeNamePath
    watchChanges: true
    printErrors: false
    onLoaded: {
      var slug = String(text() || "").trim().toLowerCase().replace(/ /g, "-")
      if (!slug) return
      if (slug === root.appliedTheme) {
        root.currentThemeSlug = slug
        return
      }
      root.currentThemeSlug = slug
      root.maybeSeed()
      if (root.initialLoadDone && !root.applyingLook && root.configReady) {
        var ws = root.currentRegularWorkspace()
        var look = root.assignment(ws)
        if (look.theme !== slug) {
          root.recordUserThemeChange(slug)
        }
      }
    }
    onFileChanged: reload()
  }

  FileView {
    id: configFile
    path: root.configPath
    watchChanges: true
    printErrors: false
    onLoaded: {
      var next = Model.parseConfig(text())
      root.config = next
      root.configReady = true
      root.syncRules()
      root.syncWindows()
    }
    onLoadFailed: {
      root.config = Model.emptyConfig()
      root.configReady = true
      root.maybeSeed()
    }
    onFileChanged: reload()
  }

  Process {
    id: setupProc
    command: ["python3", root.pluginDir + "/assets.py", "setup"]
    onExited: root.registerGesture()
  }

  Process {
    id: gestureProc
    command: ["hyprctl", "repl", root.clearGuardsLua + root.gestureLua]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var out = String(text || "").trim()
        root.gestureAttempts = root.gestureAttempts + 1
        root.gestureRegistered = out === "registered" || out === "present"
      }
    }
  }

  Timer {
    interval: 2500
    repeat: true
    running: root.luaReady && !root.gestureRegistered && root.gestureAttempts < 8
    onTriggered: root.registerGesture()
  }

  Process {
    id: syncRulesProc
    command: ["python3", root.pluginDir + "/assets.py", "sync-rules"]
  }

  Process {
    id: syncWindowsProc
    command: ["python3", root.pluginDir + "/assets.py", "sync-windows"]
    onExited: {
      if (root.pendingForceSync) root.syncWindows(true)
    }
  }

  Process {
    id: recordThemeProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var raw = String(text || "").trim()
        if (raw) {
          var next = Model.parseConfig(raw)
          root.config = next
          var ws = root.currentRegularWorkspace()
          var look = Model.assignment(next, ws)
          if (look.background) root.currentBackground = look.background
        }
        forceSyncTimer.restart()
      }
    }
  }

  Process {
    id: recordBgProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var raw = String(text || "").trim()
        if (raw) {
          var next = Model.parseConfig(raw)
          root.config = next
          var ws = root.currentRegularWorkspace()
          var look = Model.assignment(next, ws)
          if (look.background) root.currentBackground = look.background
        }
      }
    }
  }

  Process {
    id: backgroundProc
    command: ["python3", root.pluginDir + "/assets.py", "realpath", root.currentBackgroundLink]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var path = String(text || "").trim()
        if (path) {
          var ws = root.currentRegularWorkspace()
          var look = root.assignment(ws)
          if (Model.sameBackground(path, look.background)) {
            root.currentBackground = look.background
          } else {
            if (root.initialLoadDone && !root.applyingLook && root.configReady) {
              root.recordUserBackgroundChange(path)
            }
          }
        }
        if (!root.stripReady) stripReadyTimer.restart()
        root.maybeSeed()
      }
    }
  }

  Process {
    id: themesProc
    command: ["python3", root.pluginDir + "/assets.py", "themes"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try { root.themes = JSON.parse(String(text || "[]")) } catch (e) { root.themes = [] }
        applyTimer.restart()
      }
    }
  }

  Process {
    id: applyShellProc
    onExited: root.flushPendingTheme()
  }
  Process {
    id: applyBordersProc
    onExited: root.flushPendingTheme()
  }
  Process { id: saveProc }
  Process { id: linkProc }

  IpcHandler {
    target: "lessunderrated.omaswipe"

    function ping(): string { return "ok" }

    function status(): string {
      return JSON.stringify({
        workspace: root.appliedWorkspace,
        theme: root.appliedTheme,
        background: root.currentBackground,
        swiping: root.swiping,
        swipeState: root.swipeState,
        offsets: root.compositorOffsets,
        workspaces: root.workspaceCount,
        config: root.config
      })
    }

    function reload(): string {
      configFile.reload()
      themeNameFile.reload()
      root.ensureRuntime()
      root.reloadThemes()
      root.refreshBackground()
      root.registerGesture()
      root.syncRules()
      root.syncWindows()
      return "ok"
    }
  }

  IpcHandler {
    target: "background"

    function refresh(): void {
      root.refreshBackground()
    }

    function set(path: string): void {
      if (!path || !root.initialLoadDone) return
      var ws = root.currentRegularWorkspace()
      var look = root.assignment(ws)
      if (!Model.sameBackground(path, look.background)) {
        root.recordUserBackgroundChange(path)
      }
    }

    function setInstant(path: string): void {
      set(path)
    }

    function transition(fromPath: string, path: string): void {
      set(path)
    }

    function themeTransition(fromPath: string, path: string, finalPath: string, colorsB64: string, shellB64: string): void {
      var targetBg = finalPath || path
      if (targetBg) set(targetBg)
    }
  }

  Variants {
    model: Quickshell.screens

    PanelWindow {
      id: panel
      required property var modelData

      screen: modelData
      visible: !remapGuard.remapping
      anchors { top: true; bottom: true; left: true; right: true }
      color: "#0a0a0c"
      exclusionMode: ExclusionMode.Ignore
      WlrLayershell.namespace: "omaswipe-wallpaper"
      WlrLayershell.layer: WlrLayer.Bottom
      WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
      mask: Region {}

      ScreenMoveRemap {
        id: remapGuard
        window: panel
      }

      readonly property var hyprlandMonitor: Hyprland.monitorFor(modelData)
      readonly property var visibleWorkspace: hyprlandMonitor ? hyprlandMonitor.activeWorkspace : null
      readonly property int workspaceId: {
        var ws = visibleWorkspace
        var id = ws ? Number(ws.id) : NaN
        if (!isFinite(id) || id < 1) return root.appliedWorkspace || 1
        return Model.clampWorkspaceId(id, root.workspaceCount)
      }
      readonly property real tileWidth: Math.max(panel.width, 1)

      readonly property var compositorState: {
        var map = root.compositorStates
        var mon = hyprlandMonitor
        var name = mon && mon.name ? String(mon.name) : ""
        return (map && name) ? map[name] : null
      }

      readonly property real targetX: {
        var s = root.swipeState
        var mon = hyprlandMonitor && hyprlandMonitor.name ? String(hyprlandMonitor.name) : ""
        if (s && s.active && mon && s.mon === mon && s.wsId >= 1) {
          var clampedWs = Model.clampWorkspaceId(s.wsId, root.workspaceCount)
          return -((clampedWs - 1) * panel.tileWidth) + s.offset
        }
        var st = compositorState
        if (st && typeof st.offset === "number" && isFinite(st.offset) && typeof st.wsId === "number" && st.wsId >= 1) {
          var clampedSt = Model.clampWorkspaceId(st.wsId, root.workspaceCount)
          return -((clampedSt - 1) * panel.tileWidth) + st.offset
        }
        return -((panel.workspaceId - 1) * panel.tileWidth)
      }

      Item {
        id: strip
        height: parent.height
        width: panel.tileWidth * root.workspaceCount
        x: panel.targetX

        Behavior on x {
          enabled: root.stripReady && panel.width > 0 && !root.swiping
          NumberAnimation { duration: 350; easing.type: Easing.OutQuint }
        }

        Repeater {
          model: root.workspaceCount
          Image {
            required property int index
            width: panel.tileWidth
            height: strip.height
            x: index * width
            source: Util.fileUrl(root.wallpaperPaths[index] || "")
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: true
            smooth: true
            mipmap: false
            sourceSize.width: Math.max(1, Math.round(panel.tileWidth * Screen.devicePixelRatio))
            sourceSize.height: Math.max(1, Math.round(panel.height * Screen.devicePixelRatio))
          }
        }
      }
    }
  }
}
