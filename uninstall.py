#!/usr/bin/env python3
"""Remove compositor/runtime files installed by omaswipe.

This copy lives outside the plugin directory so `omarchy plugin remove`
can still clean up after it deletes ~/.config/omarchy/plugins/<id>/.
"""
import os
import shutil
import subprocess
import sys

HOME = os.environ.get("HOME", "")
XDG_CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
PLUGIN_ID = "omaswipe"
HYPR_PLUGIN_SO = os.path.join(XDG_CONFIG, "hypr", "plugins", "omaswipe-ws-offset.so")
HYPR_SNIPPET = os.path.join(XDG_CONFIG, "hypr", f"{PLUGIN_ID}.lua")
UNINSTALL_DST = os.path.join(XDG_CONFIG, "hypr", f"{PLUGIN_ID}.uninstall.py")
THEME_HOOK_DST = os.path.join(XDG_CONFIG, "omarchy", "hooks", "theme-set.d", f"{PLUGIN_ID}.hook")
HYPRLAND_LUA = os.path.join(XDG_CONFIG, "hypr", "hyprland.lua")
MARKER = "-- omaswipe helper (permission, load, wallpaper layer)"
DOFILE = 'pcall(dofile, (os.getenv("HOME") or "") .. "/.config/hypr/omaswipe.lua")'
UNSET_GESTURE = (
    "_G.__omaswipe_ws_swipe = nil _G.__omaswipe_ws_persist = nil "
    'pcall(function() hl.gesture({ fingers = 3, direction = "horizontal", action = "unset" }) end)'
)


def hyprctl(*args):
    binary = shutil.which("hyprctl")
    if not binary:
        return
    subprocess.run([binary, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def remove_hyprland_snippet_load():
    try:
        existing = open(HYPRLAND_LUA, encoding="utf-8").read() if os.path.isfile(HYPRLAND_LUA) else ""
    except OSError:
        return
    if not existing:
        return
    lines = existing.splitlines(keepends=True)
    out = []
    skip_following_blank = False
    for line in lines:
        stripped = line.strip()
        if stripped == MARKER or stripped == DOFILE:
            skip_following_blank = True
            continue
        if skip_following_blank and stripped == "":
            skip_following_blank = False
            continue
        skip_following_blank = False
        out.append(line)
    text = "".join(out).rstrip() + ("\n" if existing.endswith("\n") or out else "")
    if text != existing:
        with open(HYPRLAND_LUA, "w", encoding="utf-8") as fh:
            fh.write(text)


def plugin_is_enabled_in_shell_config():
    path = os.path.join(XDG_CONFIG, "omarchy", "shell.json")
    try:
        with open(path, encoding="utf-8") as fh:
            import json
            config = json.load(fh)
    except (OSError, ValueError):
        return False
    disabled = config.get("disabledPlugins") or []
    if PLUGIN_ID in disabled:
        return False
    for entry in config.get("plugins") or []:
        ident = entry.get("id") if isinstance(entry, dict) else entry
        if ident == PLUGIN_ID:
            return True
    return False


def restore_stock_wallpaper():
    bg_link = os.path.join(HOME, ".local/state/omarchy/current/background")
    bg = os.path.realpath(bg_link) if os.path.lexists(bg_link) else ""
    setter = shutil.which("omarchy-theme-bg-set")
    if setter and bg and os.path.exists(bg):
        subprocess.run([setter, bg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    if "--unless-enabled" in sys.argv and plugin_is_enabled_in_shell_config():
        print("skip")
        return 0
    hyprctl("repl", UNSET_GESTURE)
    if os.path.isfile(HYPR_PLUGIN_SO):
        hyprctl("plugin", "unload", HYPR_PLUGIN_SO)
    for path in (HYPR_PLUGIN_SO, THEME_HOOK_DST, HYPR_SNIPPET):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    remove_hyprland_snippet_load()
    restore_stock_wallpaper()
    hyprctl("reload")
    try:
        os.remove(UNINSTALL_DST)
    except FileNotFoundError:
        pass
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
