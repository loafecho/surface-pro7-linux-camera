#!/bin/sh
# Runs inside a throwaway build container: sources in /src, output in /out.
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null
apt-get install -y -qq meson ninja-build g++ pkg-config libudev-dev libdbus-1-dev python3 libglib2.0-dev libncurses-dev libcap-dev libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev >/dev/null
cp -a /sysroot/usr/local/. /usr/local/
ldconfig
cd /src
export PKG_CONFIG_PATH=/usr/local/lib/x86_64-linux-gnu/pkgconfig
meson setup /build -Dauto_features=disabled -Dlibcamera=enabled -Dudev=enabled -Dspa-plugins=enabled -Dsession-managers=[] -Dexamples=disabled -Dtests=disabled -Dman=disabled -Ddocs=disabled >/build.log 2>&1 || { tail -40 /build.log; exit 1; }
ninja -C /build spa/plugins/libcamera/libspa-libcamera.so 2>&1 | tail -5
cp /build/spa/plugins/libcamera/libspa-libcamera.so /out/
