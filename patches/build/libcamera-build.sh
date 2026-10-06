#!/bin/sh
# Runs inside a throwaway build container: sources in /src, output in /out.
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq >/dev/null
apt-get install -y -qq meson ninja-build g++ pkg-config python3-yaml python3-ply python3-jinja2 libyaml-dev libssl-dev openssl libudev-dev libevent-dev libdrm-dev libjpeg-dev libegl-dev libgles-dev libepoxy-dev libtiff-dev libdw-dev git >/dev/null 2>&1
cd /src
meson setup /build --prefix=/usr/local --libdir=lib/x86_64-linux-gnu --buildtype=release \
  -Dpipelines=simple -Dipas=simple -Dcam=enabled -Dlc-compliance=disabled -Dv4l2=enabled \
  -Dgstreamer=disabled -Dqcam=disabled -Dpycamera=disabled -Ddocumentation=disabled -Dtest=false -Dtracing=disabled > /setup.log 2>&1 || { tail -40 /setup.log; exit 1; }
grep -iE "egl|gles|SoftISP|Enabled pipelines|Enabled IPA|cam application|V4L2 emulation" /setup.log | head
ninja -C /build 2>&1 | tail -3
DESTDIR=/out meson install -C /build --no-rebuild >/dev/null 2>&1
find /out -type f | sed 's|^/out||' | sort
