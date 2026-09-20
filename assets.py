#!/usr/bin/env python3
import base64
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys

HOME = os.environ.get("HOME", "")
XDG_CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
OMARCHY = os.environ.get("OMARCHY_PATH", "/usr/share/omarchy")
PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
PLUGIN_ID = "lessunderrated.omaswipe"
HYPR_PLUGIN_NAME = "omaswipe-ws-offset"
HYPR_PLUGIN_SO = os.path.join(XDG_CONFIG, "hypr", "plugins", f"{HYPR_PLUGIN_NAME}.so")
HYPR_SNIPPET = os.path.join(XDG_CONFIG, "hypr", f"{PLUGIN_ID}.lua")
UNINSTALL_DST = os.path.join(XDG_CONFIG, "hypr", f"{PLUGIN_ID}.uninstall.py")
THEME_HOOK_NAME = f"{PLUGIN_ID}.hook"
THEME_HOOK_DST = os.path.join(XDG_CONFIG, "omarchy", "hooks", "theme-set.d", THEME_HOOK_NAME)
USER_THEMES = os.path.join(HOME, ".config/omarchy/themes")
STOCK_THEMES = os.path.join(OMARCHY, "themes")
USER_BGS = os.path.join(HOME, ".config/omarchy/backgrounds")
CURRENT_THEME_DIR = os.path.join(HOME, ".local/state/omarchy/current/theme")
CURRENT_THEME_NAME = os.path.join(HOME, ".local/state/omarchy/current/theme.name")
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
MEDIA_EXT = IMAGE_EXT | {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi"}


def slug_to_label(slug):
    return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-") if part)


def list_theme_slugs():
    slugs = set()
    for root in (STOCK_THEMES, USER_THEMES):
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            path = os.path.join(root, name)
            if os.path.isdir(path) or os.path.islink(path):
                slugs.add(name)
    return sorted(slugs)


def theme_dirs(slug):
    dirs = []
    stock = os.path.join(STOCK_THEMES, slug)
    user = os.path.join(USER_THEMES, slug)
    if os.path.isdir(stock):
        dirs.append(stock)
    if os.path.isdir(user):
        dirs.append(user)
    return dirs


def first_file(slug, filename):
    for folder in reversed(theme_dirs(slug)):
        path = os.path.join(folder, filename)
        if os.path.isfile(path):
            return path
    return ""


def theme_background_files(slug):
    """Stock then user-overlay theme backgrounds. User filenames win."""
    files = {}
    for src_root in (
        os.path.join(STOCK_THEMES, slug, "backgrounds"),
        os.path.join(USER_THEMES, slug, "backgrounds"),
    ):
        if not os.path.isdir(src_root):
            continue
        try:
            names = os.listdir(src_root)
        except OSError:
            continue
        for name in names:
            ext = os.path.splitext(name)[1].lower()
            if ext not in MEDIA_EXT:
                continue
            src = os.path.join(src_root, name)
            if not os.path.isfile(src) and not os.path.islink(src):
                continue
            real = os.path.realpath(src)
            if os.path.isfile(real):
                files[name] = real
    return files


def write_theme_name(slug):
    try:
        os.makedirs(os.path.dirname(CURRENT_THEME_NAME), exist_ok=True)
        with open(CURRENT_THEME_NAME, "w") as handle:
            handle.write(slug + "\n")
    except OSError:
        pass


def staged_background_files(dest):
    files = {}
    if not os.path.isdir(dest):
        return files
    try:
        names = os.listdir(dest)
    except OSError:
        return files
    for name in names:
        path = os.path.join(dest, name)
        if not os.path.isfile(path) and not os.path.islink(path):
            continue
        try:
            files[name] = os.path.realpath(path)
        except OSError:
            continue
    return files


def stage_theme_backgrounds(slug):
    """Keep Omarchy's background picker pointed at this workspace's theme.

    omarchy-theme-bg-switcher lists ~/.local/state/omarchy/current/theme/backgrounds,
    which is only rebuilt by a full `omarchy theme set`. Workspace switches only
    retint the shell, so without this the picker keeps showing the last fully
    applied theme's images.
    """
    slug = (slug or "").strip().lower().replace(" ", "-")
    if not slug:
        return False

    dest = os.path.join(CURRENT_THEME_DIR, "backgrounds")
    desired = theme_background_files(slug)
    current = staged_background_files(dest)
    if current == desired:
        write_theme_name(slug)
        return True

    os.makedirs(CURRENT_THEME_DIR, exist_ok=True)
    tmp = dest + ".staging"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    try:
        for name, real in desired.items():
            os.symlink(real, os.path.join(tmp, name))
        backup = dest + ".old"
        shutil.rmtree(backup, ignore_errors=True)
        if os.path.lexists(dest):
            os.rename(dest, backup)
        os.rename(tmp, dest)
        shutil.rmtree(backup, ignore_errors=True)
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)
        backup = dest + ".old"
        if not os.path.isdir(dest) and os.path.isdir(backup):
            try:
                os.rename(backup, dest)
            except OSError:
                pass
        return False

    write_theme_name(slug)
    return True


def cmd_stage_backgrounds(slug):
    stage_theme_backgrounds(slug)


def cmd_bg_switcher(slug):
    stage_theme_backgrounds(slug)
    os.execvp("omarchy-theme-bg-switcher", ["omarchy-theme-bg-switcher"])


def list_backgrounds(slug):
    seen = set()
    names = set()
    out = []
    search = [os.path.join(USER_BGS, slug)]
    user_theme = os.path.join(USER_THEMES, slug, "backgrounds")
    stock_theme = os.path.join(STOCK_THEMES, slug, "backgrounds")
    search.extend([user_theme, stock_theme])
    for folder in search:
        if not os.path.isdir(folder):
            continue
        try:
            files = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in files:
            if os.path.splitext(name)[1].lower() not in IMAGE_EXT:
                continue
            if name in names:
                continue
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                continue
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            names.add(name)
            out.append(path)
    return out


def read_text(path):
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                return handle.read()
        except OSError:
            pass
    return ""


def theme_payload(slug):
    colors = first_file(slug, "colors.toml")
    shell = first_file(slug, "shell.toml")
    return {
        "slug": slug,
        "label": slug_to_label(slug),
        "colors": colors,
        "shell": shell,
        "colorsRaw": read_text(colors),
        "shellRaw": read_text(shell),
        "backgrounds": list_backgrounds(slug),
    }


def cmd_themes():
    items = []
    for slug in list_theme_slugs():
        items.append(theme_payload(slug))
    print(json.dumps(items))


def cmd_theme_files(slug):
    print(json.dumps(theme_payload(slug)))


def is_ephemeral_path(path):
    if not path:
        return True
    real = os.path.realpath(path)
    return "/.local/state/omarchy/current/" in path or "/.local/state/omarchy/current/" in real


def theme_of_background(path):
    if not path:
        return ""
    m = re.search(r"/(?:themes/([^/]+)/backgrounds|backgrounds/([^/]+))/", path)
    if m:
        slug = m.group(1) or m.group(2)
        if slug != "current":
            return slug
    return ""


def resolve_background(theme_slug, path):
    # If path is tied to another theme, it should not be kept when switching themes
    bg_theme = theme_of_background(path)
    if bg_theme and theme_slug and bg_theme != theme_slug:
        path = ""

    # 1. If it is already a permanent valid file (not in ephemeral state), keep it
    if path and not is_ephemeral_path(path):
        real = os.path.realpath(path)
        if os.path.isfile(real):
            return real

    # 2. If ephemeral or missing, find the durable file by its basename
    name = os.path.basename(path) if path else ""
    if name:
        if theme_slug:
            for cand in list_backgrounds(theme_slug):
                if os.path.basename(cand) == name and os.path.isfile(cand):
                    return os.path.realpath(cand)
        for slug in list_theme_slugs():
            for cand in list_backgrounds(slug):
                if os.path.basename(cand) == name and os.path.isfile(cand):
                    return os.path.realpath(cand)

    # 3. Fallback: first background of the theme
    if theme_slug:
        bgs = list_backgrounds(theme_slug)
        if bgs and os.path.isfile(bgs[0]):
            return os.path.realpath(bgs[0])

    return ""


def cmd_fix_config(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    workspaces = data.get("workspaces") or {}
    for entry in workspaces.values():
        if not isinstance(entry, dict):
            continue
        entry["background"] = resolve_background(entry.get("theme") or "", entry.get("background") or "")
    print(json.dumps(data))


def parse_accent_muted(colors_path):
    accent, muted = None, None
    if colors_path and os.path.isfile(colors_path):
        with open(colors_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not accent:
                    m = re.match(r'^\s*accent\s*=\s*["\']?#?([0-9a-fA-F]{6})', line)
                    if m: accent = m.group(1)
                if not muted:
                    m = re.match(r'^\s*muted\s*=\s*["\']?#?([0-9a-fA-F]{6})', line)
                    if m: muted = m.group(1)
                if not accent:
                    m = re.match(r'^\s*color4\s*=\s*["\']?#?([0-9a-fA-F]{6})', line)
                    if m: accent = m.group(1)
    return accent, muted


def cmd_sync_rules():
    config_file = os.path.join(HOME, ".config/omarchy/omaswipe.json")
    if not os.path.isfile(config_file):
        return
    try:
        with open(config_file, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return
    workspaces = cfg.get("workspaces") or {}
    lua_lines = []
    for ws_str, entry in workspaces.items():
        slug = (entry.get("theme") or "").strip().lower().replace(" ", "-")
        if not slug:
            continue
        colors_path = first_file(slug, "colors.toml")
        accent, muted = parse_accent_muted(colors_path)
        if accent:
            mut_str = f" rgba({muted}aa)" if muted else ""
            lua_lines.append(f'hl.window_rule({{ match = {{ workspace = "{ws_str}" }}, border_color = "rgb({accent}){mut_str}" }})')
    if lua_lines:
        subprocess.run(["hyprctl", "repl", "\n".join(lua_lines)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def iter_descendants(pid):
    try:
        kids = subprocess.check_output(["pgrep", "-P", str(pid)], text=True).split()
    except Exception:
        return
    for kid in kids:
        yield kid
        yield from iter_descendants(kid)


def ptys_for_pid(pid):
    found = set()
    pids = [str(pid)] + list(iter_descendants(pid))
    for proc in pids:
        fd_dir = f"/proc/{proc}/fd"
        try:
            names = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in names:
            try:
                target = os.readlink(os.path.join(fd_dir, fd))
            except OSError:
                continue
            if target.startswith("/dev/pts/"):
                found.add(target)
    return found


def osc_for_theme(slug, cache):
    if slug in cache:
        return cache[slug]
    colors_path = first_file(slug, "colors.toml")
    osc = b""
    if colors_path and os.path.isfile(colors_path):
        try:
            osc = subprocess.check_output(["omarchy-theme-osc", colors_path], stderr=subprocess.DEVNULL)
        except Exception:
            osc = b""
    cache[slug] = osc
    return osc


def write_osc(tty, osc):
    if not osc:
        return False
    try:
        fd = os.open(tty, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        os.write(fd, osc)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def cmd_sync_windows(force=False):
    config_file = os.path.join(HOME, ".config/omarchy/omaswipe.json")
    if not os.path.isfile(config_file):
        return
    try:
        with open(config_file, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return
    workspaces = cfg.get("workspaces") or {}
    ws_themes = {int(k): (v.get("theme") or "").strip().lower().replace(" ", "-") for k, v in workspaces.items() if v.get("theme")}

    try:
        clients = json.loads(subprocess.check_output(["hyprctl", "-j", "clients"], text=True))
    except Exception:
        return

    cache_path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "omaswipe-tty-themes.json")
    tty_themes = {}
    if not force and os.path.isfile(cache_path):
        try:
            with open(cache_path) as f:
                tty_themes = json.load(f)
        except Exception:
            tty_themes = {}

    osc_cache = {}
    changed = False

    for client in clients:
        cls = str(client.get("class") or "")
        if not cls.startswith("foot"):
            continue
        ws = client.get("workspace", {}).get("id")
        pid = client.get("pid")
        theme = ws_themes.get(ws)
        if not theme or not pid:
            continue
        osc = osc_for_theme(theme, osc_cache)
        if not osc:
            continue
        for tty in ptys_for_pid(pid):
            if not force and tty_themes.get(tty) == theme:
                continue
            if write_osc(tty, osc):
                tty_themes[tty] = theme
                changed = True

    if force or changed:
        try:
            with open(cache_path, "w") as f:
                json.dump(tty_themes, f)
        except Exception:
            pass


def apply_hypr_borders(slug):
    colors_path = first_file(slug, "colors.toml")
    accent, muted = parse_accent_muted(colors_path)
    lua_parts = []
    if accent:
        lua_parts.append(f'["col.active_border"] = "rgb({accent})"')
    if muted:
        lua_parts.append(f'["col.inactive_border"] = "rgba({muted}aa)"')
    if lua_parts:
        lua_cmd = f'hl.config({{ general = {{ {", ".join(lua_parts)} }} }})'
        subprocess.run(["hyprctl", "repl", lua_cmd], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    stage_theme_backgrounds(slug)


def cmd_apply_borders(slug):
    slug = slug.strip().lower().replace(" ", "-")
    if slug:
        apply_hypr_borders(slug)


def cmd_apply_shell(slug):
    slug = slug.strip().lower().replace(" ", "-")
    if not slug:
        return
    colors_path = first_file(slug, "colors.toml")
    shell_path = first_file(slug, "shell.toml")

    colors_b64 = ""
    if colors_path and os.path.isfile(colors_path):
        with open(colors_path, "rb") as f:
            colors_b64 = base64.b64encode(f.read()).decode("ascii")

    shell_b64 = ""
    if shell_path and os.path.isfile(shell_path):
        with open(shell_path, "rb") as f:
            shell_b64 = base64.b64encode(f.read()).decode("ascii")

    subprocess.run(["omarchy-shell", "shell", "applyTheme", colors_b64, shell_b64], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    apply_hypr_borders(slug)


def update_config(modifier_fn):
    config_file = os.path.join(HOME, ".config/omarchy/omaswipe.json")
    os.makedirs(os.path.dirname(config_file), exist_ok=True)
    with open(config_file, "a+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        f.seek(0)
        try:
            content = f.read().strip()
            cfg = json.loads(content) if content else {"version": 1, "workspaces": {}, "workspaceCount": 5}
        except Exception:
            cfg = {"version": 1, "workspaces": {}, "workspaceCount": 5}

        cfg = modifier_fn(cfg) or cfg

        f.seek(0)
        f.truncate()
        json.dump(cfg, f, indent=2)
        f.write("\n")
        f.flush()
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return cfg


def cmd_record_theme(ws, slug, bg_path=None):
    ws_str = str(ws).strip()
    slug = slug.strip().lower().replace(" ", "-")
    if not ws_str or not slug:
        return

    if not bg_path:
        current_link = os.path.join(HOME, ".local/state/omarchy/current/background")
        if os.path.islink(current_link):
            try:
                bg_path = os.readlink(current_link)
            except Exception:
                pass

    resolved_bg = resolve_background(slug, bg_path)

    def modifier(cfg):
        workspaces = cfg.setdefault("workspaces", {})
        entry = workspaces.setdefault(ws_str, {})
        entry["theme"] = slug
        entry["background"] = resolved_bg
        return cfg

    cfg = update_config(modifier)

    if resolved_bg:
        current_link = os.path.join(HOME, ".local/state/omarchy/current/background")
        try:
            tmp_link = current_link + ".tmp"
            if os.path.lexists(tmp_link):
                os.remove(tmp_link)
            os.symlink(resolved_bg, tmp_link)
            os.replace(tmp_link, current_link)
        except Exception:
            pass

    cmd_sync_rules()
    cmd_sync_windows(force=True)
    cmd_apply_shell(slug)
    print(json.dumps(cfg))


def cmd_record_background(ws, bg_path):
    ws_str = str(ws).strip()
    if not ws_str or not bg_path:
        return

    theme_file = CURRENT_THEME_NAME
    curr_theme = ""
    if os.path.isfile(theme_file):
        try:
            with open(theme_file) as f:
                curr_theme = f.read().strip()
        except Exception:
            pass

    def modifier(cfg):
        workspaces = cfg.setdefault("workspaces", {})
        entry = workspaces.setdefault(ws_str, {})
        theme = entry.get("theme") or curr_theme or theme_of_background(bg_path)
        durable_bg = resolve_background(theme, bg_path)
        if durable_bg:
            entry["background"] = durable_bg
        return cfg

    cfg = update_config(modifier)
    entry = cfg.get("workspaces", {}).get(ws_str, {})
    durable_bg = entry.get("background", "")

    if durable_bg:
        current_link = os.path.join(HOME, ".local/state/omarchy/current/background")
        try:
            tmp_link = current_link + ".tmp"
            if os.path.lexists(tmp_link):
                os.remove(tmp_link)
            os.symlink(durable_bg, tmp_link)
            os.replace(tmp_link, current_link)
        except Exception:
            pass

    print(json.dumps(cfg))


def cmd_realpath(path):
    if not path:
        print("")
        return
    theme_file = CURRENT_THEME_NAME
    slug = ""
    if os.path.isfile(theme_file):
        try:
            with open(theme_file) as f:
                slug = f.read().strip()
        except Exception:
            pass
    resolved = resolve_background(slug, path)
    print(resolved if resolved else os.path.realpath(path))


HYPR_SNIPPET_TEXT = r"""-- Managed by omaswipe. Safe to delete if you remove the plugin.
-- Allows and loads the compositor helper that publishes live workspace swipe offsets.

hl.permission(".*/\\.config/hypr/plugins/omaswipe-ws-offset\\.so", "plugin", "allow")

do
  local path = (os.getenv("HOME") or "") .. "/.config/hypr/plugins/omaswipe-ws-offset.so"
  local file = io.open(path, "r")
  if file then
    file:close()
    pcall(hl.plugin.load, path)
  end
end

hl.layer_rule({
  match = { namespace = "omarchy-background" },
  order = 0,
})

hl.layer_rule({
  match = { namespace = "omaswipe-wallpaper" },
  no_anim = true,
  animation = "none",
  order = 100,
})
"""


def plugin_dir():
    return PLUGIN_DIR


def hyprland_include_flags():
    flags = []
    pkg = shutil.which("pkg-config")
    if pkg:
        try:
            out = subprocess.check_output(
                [pkg, "--cflags", "hyprland", "pixman-1", "libdrm", "hyprutils"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            if out:
                flags.extend(out.split())
        except subprocess.CalledProcessError:
            pass

    user = os.environ.get("USER") or ""
    candidates = [
        os.path.join("/var/cache/hyprpm", user, "headersRoot", "include") if user else "",
        "/usr/include",
    ]
    for include_root in candidates:
        if not include_root or not os.path.isdir(include_root):
            continue
        hyprland = os.path.join(include_root, "hyprland")
        if os.path.isdir(hyprland):
            flags.extend([
                f"-I{include_root}",
                f"-I{os.path.join(hyprland, 'protocols')}",
                f"-I{hyprland}",
                f"-I{os.path.join(hyprland, 'src')}",
            ])
            break
    return flags


def hyprland_lib_flags():
    pkg = shutil.which("pkg-config")
    if not pkg:
        return ["-lhyprutils"]
    try:
        out = subprocess.check_output(
            [pkg, "--libs", "hyprland"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if out:
            return out.split()
    except subprocess.CalledProcessError:
        pass
    return ["-lhyprutils"]


def extra_hypr_plugin_libs():
    return [
        "-laquamarine", "-lhyprcursor", "-lhyprgraphics", "-lhyprlang", "-lhyprutils",
        "-ldrm", "-lEGL", "-lcairo", "-lxkbcommon", "-linput", "-lwayland-server",
        "-lm", "-lxcb-icccm", "-lxcb-composite", "-lxcb-xfixes", "-lxcb-render",
        "-lxcb-res", "-lxcb-errors", "-lxcb",
    ]


def compile_hypr_plugin():
    src = os.path.join(PLUGIN_DIR, "hypr-plugin", "main.cpp")
    if not os.path.isfile(src):
        print("hypr-plugin source missing", file=sys.stderr)
        return False

    cxx = os.environ.get("CXX") or shutil.which("g++") or shutil.which("clang++")
    if not cxx:
        print("no C++ compiler found (g++ or clang++)", file=sys.stderr)
        return False

    os.makedirs(os.path.dirname(HYPR_PLUGIN_SO), exist_ok=True)
    cmd = [
        cxx, "-shared", "-fPIC", "--no-gnu-unique", "-std=c++23", "-O2",
        "-DWLR_USE_UNSTABLE",
        *hyprland_include_flags(),
        "-o", HYPR_PLUGIN_SO,
        src,
        *hyprland_lib_flags(),
        *extra_hypr_plugin_libs(),
    ]
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        print("failed to compile Hyprland helper plugin", file=sys.stderr)
        return False
    os.chmod(HYPR_PLUGIN_SO, 0o755)
    return True


def load_hypr_plugin():
    if not os.path.isfile(HYPR_PLUGIN_SO):
        return False
    hyprctl = shutil.which("hyprctl")
    if not hyprctl:
        return False
    subprocess.run([hyprctl, "plugin", "unload", HYPR_PLUGIN_SO], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    result = subprocess.run([hyprctl, "plugin", "load", HYPR_PLUGIN_SO], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def install_theme_hook():
    src = os.path.join(PLUGIN_DIR, "hooks", "theme-set.hook")
    if not os.path.isfile(src):
        return False
    os.makedirs(os.path.dirname(THEME_HOOK_DST), exist_ok=True)
    body = (
        "#!/bin/bash\n"
        "# Managed by omaswipe. Re-applies per-workspace terminal colors\n"
        "# after a global theme change so windows stay pinned to their workspace look.\n"
        f"exec python3 {json.dumps(os.path.join(PLUGIN_DIR, 'assets.py'))} sync-windows --force\n"
    )
    with open(THEME_HOOK_DST, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.chmod(THEME_HOOK_DST, 0o755)
    return True


def install_hypr_snippet():
    os.makedirs(os.path.dirname(HYPR_SNIPPET), exist_ok=True)
    with open(HYPR_SNIPPET, "w", encoding="utf-8") as fh:
        fh.write(HYPR_SNIPPET_TEXT)
    return True


def install_uninstall_script():
    src = os.path.join(PLUGIN_DIR, "uninstall.py")
    if not os.path.isfile(src):
        return False
    os.makedirs(os.path.dirname(UNINSTALL_DST), exist_ok=True)
    shutil.copy2(src, UNINSTALL_DST)
    os.chmod(UNINSTALL_DST, 0o755)
    return True


def hyprland_lua_already_loads_helper():
    path = os.path.join(XDG_CONFIG, "hypr", "hyprland.lua")
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return False
    return (
        f"{PLUGIN_ID}.lua" in text
        or "omaswipe-ws-offset" in text
        or "omaswipe-wallpaper" in text
    )


def ensure_hyprland_snippet_loaded():
    if hyprland_lua_already_loads_helper():
        return True
    path = os.path.join(XDG_CONFIG, "hypr", "hyprland.lua")
    line = 'pcall(dofile, (os.getenv("HOME") or "") .. "/.config/hypr/lessunderrated.omaswipe.lua")\n'
    marker = "-- omaswipe helper (permission, load, wallpaper layer)"
    try:
        existing = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
    except OSError:
        existing = ""
    if marker in existing or f"{PLUGIN_ID}.lua" in existing:
        return True
    with open(path, "a", encoding="utf-8") as fh:
        if existing and not existing.endswith("\n"):
            fh.write("\n")
        fh.write("\n" + marker + "\n")
        fh.write(line)
    return True


def cmd_setup():
    ok_plugin = compile_hypr_plugin()
    ok_hook = install_theme_hook()
    ok_snippet = install_hypr_snippet()
    ok_uninstall = install_uninstall_script()
    ensure_hyprland_snippet_loaded()
    loaded = load_hypr_plugin() if ok_plugin else False
    print(json.dumps({
        "plugin": HYPR_PLUGIN_SO if ok_plugin else "",
        "hook": THEME_HOOK_DST if ok_hook else "",
        "snippet": HYPR_SNIPPET if ok_snippet else "",
        "uninstall": UNINSTALL_DST if ok_uninstall else "",
        "loaded": loaded,
    }))
    if not ok_plugin:
        sys.exit(1)


def cmd_teardown():
    src = os.path.join(PLUGIN_DIR, "uninstall.py")
    script = UNINSTALL_DST if os.path.isfile(UNINSTALL_DST) else src
    if not os.path.isfile(script):
        print("uninstall script missing", file=sys.stderr)
        sys.exit(1)
    result = subprocess.run([sys.executable, script])
    if result.returncode != 0:
        sys.exit(result.returncode or 1)


def main():
    if len(sys.argv) < 2:
        print("usage: assets.py themes | theme-files <slug> | apply-shell <slug> | apply-borders <slug> | sync-rules | sync-windows [--force] | record-theme <ws> <slug> | record-background <ws> <path> | fix-config <file> | realpath <file> | stage-backgrounds <slug> | bg-switcher <slug> | setup | teardown", file=sys.stderr)
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "themes":
        cmd_themes()
    elif cmd == "theme-files" and len(sys.argv) > 2:
        cmd_theme_files(sys.argv[2])
    elif cmd == "apply-shell" and len(sys.argv) > 2:
        cmd_apply_shell(sys.argv[2])
    elif cmd == "apply-borders" and len(sys.argv) > 2:
        cmd_apply_borders(sys.argv[2])
    elif cmd == "sync-rules":
        cmd_sync_rules()
    elif cmd == "sync-windows":
        cmd_sync_windows(force="--force" in sys.argv[2:])
    elif cmd == "record-theme" and len(sys.argv) > 3:
        cmd_record_theme(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
    elif cmd == "record-background" and len(sys.argv) > 3:
        cmd_record_background(sys.argv[2], sys.argv[3])
    elif cmd == "fix-config" and len(sys.argv) > 2:
        cmd_fix_config(sys.argv[2])
    elif cmd == "realpath" and len(sys.argv) > 2:
        cmd_realpath(sys.argv[2])
    elif cmd == "stage-backgrounds" and len(sys.argv) > 2:
        cmd_stage_backgrounds(sys.argv[2])
    elif cmd == "bg-switcher" and len(sys.argv) > 2:
        cmd_bg_switcher(sys.argv[2])
    elif cmd == "setup":
        cmd_setup()
    elif cmd == "teardown":
        cmd_teardown()
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
