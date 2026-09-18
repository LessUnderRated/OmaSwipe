var DEFAULT_WORKSPACES = 5
var MAX_WORKSPACES = 10
var CONFIG_VERSION = 1

function normalizeWorkspaceCount(value, fallback) {
  var n = Math.round(Number(value))
  if (!isFinite(n)) return fallback === undefined ? DEFAULT_WORKSPACES : fallback
  return Math.max(1, Math.min(MAX_WORKSPACES, n))
}

function emptyConfig() {
  return { version: CONFIG_VERSION, workspaces: {} }
}

function parseConfig(text) {
  if (!text) return emptyConfig()
  var data = null
  try { data = JSON.parse(text) } catch (e) { return emptyConfig() }
  if (!data || typeof data !== "object") return emptyConfig()
  var workspaces = data.workspaces && typeof data.workspaces === "object" ? data.workspaces : {}
  var out = emptyConfig()
  var count = normalizeWorkspaceCount(data.workspaceCount, DEFAULT_WORKSPACES)
  out.workspaceCount = count
  Object.keys(workspaces).forEach(function(key) {
    var id = Math.round(Number(key))
    if (!isFinite(id) || id < 1 || id > MAX_WORKSPACES) return
    var entry = workspaces[key] || {}
    out.workspaces[String(id)] = {
      theme: String(entry.theme || "").trim(),
      background: String(entry.background || "").trim()
    }
  })
  return out
}

function assignment(config, id) {
  var entry = config && config.workspaces ? config.workspaces[String(id)] : null
  if (!entry) return { theme: "", background: "" }
  return { theme: entry.theme || "", background: entry.background || "" }
}

function setAssignment(config, id, theme, background) {
  var next = parseConfig(JSON.stringify(config && config.workspaces ? config : emptyConfig()))
  if (config && config.workspaceCount) next.workspaceCount = normalizeWorkspaceCount(config.workspaceCount, DEFAULT_WORKSPACES)
  next.workspaces[String(id)] = {
    theme: String(theme || "").trim(),
    background: String(background || "").trim()
  }
  return next
}

function backgroundFor(config, id, fallback) {
  var bg = assignment(config, id).background
  return bg || fallback || ""
}

function sameBackground(p1, p2) {
  if (!p1 || !p2) return false
  if (p1 === p2) return true
  var b1 = String(p1).split("/").pop()
  var b2 = String(p2).split("/").pop()
  return Boolean(b1 && b2 && b1 === b2)
}

function clampWorkspaceId(id, count) {
  var n = Math.round(Number(id))
  var max = normalizeWorkspaceCount(count, DEFAULT_WORKSPACES)
  if (!isFinite(n) || n < 1) return 1
  return Math.max(1, Math.min(max, n))
}

function hexRgb(value) {
  var m = String(value || "").trim().match(/^#?([0-9A-Fa-f]{6})/)
  return m ? m[1].toLowerCase() : ""
}

function colorToRgb(value) {
  if (value === undefined || value === null) return ""
  if (typeof value === "string") return hexRgb(value)
  var r = Math.round(Number(value.r) * 255)
  var g = Math.round(Number(value.g) * 255)
  var b = Math.round(Number(value.b) * 255)
  if (![r, g, b].every(function(n) { return isFinite(n) })) return ""
  return ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1)
}

function hasAssignments(config) {
  var workspaces = config && config.workspaces ? config.workspaces : {}
  return Object.keys(workspaces).length > 0
}

function seedAll(theme, background, count) {
  var next = emptyConfig()
  var n = normalizeWorkspaceCount(count, DEFAULT_WORKSPACES)
  next.workspaceCount = n
  for (var i = 1; i <= n; i++) {
    next.workspaces[String(i)] = {
      theme: String(theme || "").trim(),
      background: String(background || "").trim()
    }
  }
  return next
}

function themeBySlug(themes, slug) {
  var list = themes || []
  for (var i = 0; i < list.length; i++) if (list[i] && list[i].slug === slug) return list[i]
  return null
}
