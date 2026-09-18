#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/event/EventBus.hpp>
#include <hyprland/src/output/Monitor.hpp>
#include <hyprland/src/desktop/Workspace.hpp>
#include <hyprland/src/managers/EventManager.hpp>

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <unordered_map>

static HANDLE              PHANDLE = nullptr;
static CHyprSignalListener g_renderListener;
static CHyprSignalListener g_swipeBeginListener;
static CHyprSignalListener g_swipeEndListener;
static bool                g_swiping = false;

struct MonitorState {
    int64_t wsId    = 1;
    double  offset  = 0.0;
    bool    swiping = false;
};

static std::unordered_map<std::string, MonitorState> g_states;

static void onSwipeBegin(IPointer::SSwipeBeginEvent e, Event::SCallbackInfo& info) {
    if (e.fingers >= 3)
        g_swiping = true;
}

static void onSwipeEnd(IPointer::SSwipeEndEvent e, Event::SCallbackInfo& info) {
    g_swiping = false;
}

static void onPreRender(PHLMONITOR monitor) {
    if (!monitor)
        return;

    const std::string name = monitor->m_name.empty() ? std::to_string(monitor->m_id) : monitor->m_name;
    double            x    = 0.0;
    int64_t           wsId = 1;
    bool              anim = false;

    if (const auto workspace = monitor->m_activeWorkspace) {
        if (workspace->m_id >= 1)
            wsId = workspace->m_id;

        anim = workspace->m_renderOffset->isBeingAnimated();
        if (!anim && !g_swiping && std::fabs(workspace->m_renderOffset->value().x) < 0.5)
            x = 0.0;
        else
            x = workspace->m_renderOffset->value().x;
    }

    const bool active = g_swiping || anim || (std::fabs(x) >= 0.5);

    auto it = g_states.find(name);
    if (it != g_states.end() && it->second.wsId == wsId && std::fabs(it->second.offset - x) < 0.05 && it->second.swiping == active)
        return;

    g_states[name] = {wsId, x, active};
    if (g_pEventManager) {
        char buf[64];
        std::snprintf(buf, sizeof(buf), "%s,%lld,%.2f,%d", name.c_str(), (long long)wsId, x, active ? 1 : 0);
        g_pEventManager->postEvent(SHyprIPCEvent{"omaswipe_ws_offset", buf});
    }
}

APICALL EXPORT std::string PLUGIN_API_VERSION() {
    return HYPRLAND_API_VERSION;
}

APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE handle) {
    PHANDLE   = handle;
    g_swiping = false;
    g_states.clear();

    g_renderListener     = Event::bus()->m_events.render.pre.listen(onPreRender);
    g_swipeBeginListener = Event::bus()->m_events.gesture.swipe.begin.listen(onSwipeBegin);
    g_swipeEndListener   = Event::bus()->m_events.gesture.swipe.end.listen(onSwipeEnd);

    return {"omaswipe-ws-offset", "Publishes workspace swipe offset for the wallpaper strip", "LessUnderRated", "0.8"};
}

APICALL EXPORT void PLUGIN_EXIT() {
    g_renderListener.reset();
    g_swipeBeginListener.reset();
    g_swipeEndListener.reset();
    g_states.clear();
}
