#!/usr/bin/env bash
set -euo pipefail

ADB="${ADB:-$HOME/Android/Sdk/platform-tools/adb}"
DEVICE="${DEVICE:-emulator-5554}"
SNAPSHOT_ROOT="${SNAPSHOT_ROOT:-/data/local/tmp/android_world/snapshots}"

PACKAGES=(
  com.example.androidworld
  com.dimowner.audiorecorder
  com.android.camera2
  com.android.chrome
  ca.zgrs.clipper
  com.google.android.deskclock
  com.google.android.contacts
  com.google.android.dialer
  com.arduia.expense
  com.google.android.documentsui
  net.cozic.joplin
  net.gsantner.markor
  de.dennisguse.opentracks
  net.osmand
  com.flauschcode.broccoli
  code.name.monkey.retromusic
  com.android.settings
  com.simplemobiletools.calendar.pro
  com.simplemobiletools.draw.pro
  com.simplemobiletools.gallery.pro
  com.simplemobiletools.smsmessenger
  org.videolan.vlc
)

echo "Using ADB: $ADB"
echo "Using device: $DEVICE"

"$ADB" -s "$DEVICE" wait-for-device
"$ADB" -s "$DEVICE" root >/dev/null || true
"$ADB" -s "$DEVICE" wait-for-device

PACKAGE_LIST=$(
  IFS=' '
  printf '%s' "${PACKAGES[*]}"
)

"$ADB" -s "$DEVICE" shell "set -eu
mkdir -p '$SNAPSHOT_ROOT'
for p in $PACKAGE_LIST; do
  if [ -d \"/data/data/\$p\" ]; then
    rm -rf '$SNAPSHOT_ROOT/'\"\$p\"
    mkdir -p '$SNAPSHOT_ROOT/'\"\$p\"
    cp -a \"/data/data/\$p/.\" '$SNAPSHOT_ROOT/'\"\$p/\"
    echo \"saved \$p\"
  else
    echo \"missing \$p\"
  fi
done
"

echo
echo "Snapshot directories:"
"$ADB" -s "$DEVICE" shell "ls -1 '$SNAPSHOT_ROOT'"
