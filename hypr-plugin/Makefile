PLUGIN := $(HOME)/.config/hypr/plugins/omaswipe-ws-offset.so
SRC := main.cpp
CXX ?= g++

CXXFLAGS += -shared -fPIC --no-gnu-unique -std=c++23 -O2 -DWLR_USE_UNSTABLE
PKG_CFLAGS := $(shell pkg-config --cflags hyprland pixman-1 libdrm hyprutils 2>/dev/null)
PKG_LIBS := $(shell pkg-config --libs hyprland 2>/dev/null)
HYPRPM_INCLUDE := $(wildcard /var/cache/hyprpm/$(USER)/headersRoot/include)

ifneq ($(HYPRPM_INCLUDE),)
CXXFLAGS += -I$(HYPRPM_INCLUDE) \
	-I$(HYPRPM_INCLUDE)/hyprland/protocols \
	-I$(HYPRPM_INCLUDE)/hyprland \
	-I$(HYPRPM_INCLUDE)/hyprland/src
endif

CXXFLAGS += $(PKG_CFLAGS)
LDFLAGS += $(PKG_LIBS)
LDFLAGS += -laquamarine -lhyprcursor -lhyprgraphics -lhyprlang -lhyprutils \
	-ldrm -lEGL -lcairo -lxkbcommon -linput -lwayland-server -lm \
	-lxcb-icccm -lxcb-composite -lxcb-xfixes -lxcb-render -lxcb-res -lxcb-errors -lxcb

.PHONY: all clean

all: $(PLUGIN)

$(PLUGIN): $(SRC)
	mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -o $@ $< $(LDFLAGS)

clean:
	rm -f $(PLUGIN)
