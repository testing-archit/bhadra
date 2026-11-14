#!/usr/bin/env bash
# Shared display + audio server for every meeting this container joins.
# Each meeting session then creates its own PulseAudio sink (see
# meeting_session.py), so concurrent meetings never bleed into each other.
set -euo pipefail

rm -f /tmp/.X99-lock
# A restarted container keeps /tmp, and PulseAudio refuses to start ("Daemon
# already running") when its old pid file names a pid that now belongs to
# something else — which made every restart crash-loop.
rm -rf /tmp/pulse-*
Xvfb :99 -screen 0 1280x800x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
export DISPLAY=:99

pulseaudio -D --exit-idle-time=-1 --disallow-exit --log-target=file:/tmp/pulseaudio.log
for _ in $(seq 1 20); do pactl info >/dev/null 2>&1 && break; sleep 0.5; done

# Chromium's "microphone" is the monitor of a sink nothing plays into, so the
# bot can only ever send silence — even if Meet unmutes it.
pactl load-module module-null-sink sink_name=silence sink_properties=device.description=silence >/dev/null
pactl set-default-source silence.monitor

if [ ! -f "${STATE_DIR}/auth.json" ]; then
  echo "[entrypoint] WARNING: ${STATE_DIR}/auth.json missing — the bot will join as a guest that must be admitted."
fi

if [ "$#" -gt 0 ]; then
  # Ad hoc: ./entrypoint.sh --url https://meet.google.com/abc-defg-hij
  exec python3 meeting_session.py "$@"
fi
exec python3 scheduler.py
