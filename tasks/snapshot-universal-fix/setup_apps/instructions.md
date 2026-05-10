# AndroidWorld App Snapshot Bootstrap

This procedure prepares the base `AndroidWorldAvd` so worker AVD copies can restore app state during eval.

The working snapshot root for this repo is:

```text
/data/local/tmp/android_world/snapshots
```

Do not use `/data/data/android_world/snapshots`: Android may remove non-package directories under `/data/data` across reboots.

## 0. Sanity Checks

Use the SDK ADB, not Ubuntu's older `/usr/bin/adb`.

```bash
export PATH="$HOME/Android/Sdk/platform-tools:$PATH"
hash -r

which adb
adb version
```

`which adb` should print:

```text
/home/thivux/Android/Sdk/platform-tools/adb
```

Confirm the AVD and emulator exist:

```bash
ls ~/.android/avd/AndroidWorldAvd.avd ~/.android/avd/AndroidWorldAvd.ini
ls ~/Android/Sdk/emulator/emulator
```

If an old emulator is still running, stop it first:

```bash
pgrep -af "emulator|qemu-system|AndroidWorldAvd"
```

Prefer a clean stop from ADB when possible:

```bash
adb -s emulator-5554 emu kill
```

If ADB cannot see it and a stale `qemu-system-x86_64` process remains, stop that process before booting a new emulator.

## 1. Boot The Base AVD

In one terminal:

```bash
~/Android/Sdk/emulator/emulator \
  -avd AndroidWorldAvd \
  -gpu swiftshader_indirect \
  -no-audio -no-skin \
  -grpc 8554 \
  -ports 5554,5555 \
  -no-snapshot
```

Notes:

- `-gpu swiftshader_indirect` avoids host GPU failures seen with `-gpu host`.
- `-no-snapshot` cold-boots the AVD instead of restoring a QEMU snapshot.
- Ports `5554,5555` and gRPC `8554` match the runner defaults.
- Leave this terminal open while setup runs.

Wait until Android fully boots, then verify:

```bash
adb devices -l
```

You should see:

```text
emulator-5554 device
```

If it is `offline`, run:

```bash
adb kill-server
adb start-server
adb devices -l
```

## 2. Run The Setup Pass

In a second terminal:

```bash
cd /home/thivux/code/vinai/GUI_agent/AndroidAutonomy/MARS-Voyager
conda activate uivoyager

export PATH="$HOME/Android/Sdk/platform-tools:$PATH"
hash -r
export PYTHONPATH="$(pwd)/androidworld:$(pwd)/android_env:$PYTHONPATH"

python androidworld/minimal_task_runner.py \
  --perform_emulator_setup=True \
  --console_port=5554 \
  --adb_path="$HOME/Android/Sdk/platform-tools/adb" \
  --task=ContactsAddContact 2>&1 | tee ~/setup_apps.log
```

What this does:

- Installs and opens each AndroidWorld app.
- Runs each app's first-time setup flow.
- Attempts to save app data snapshots.
- Starts the throwaway `ContactsAddContact` task after setup finishes.

The throwaway task may fail if no model server is running at `localhost:8001`. That is fine. App setup is complete once the final app, `org.videolan.vlc`, has been configured.

If the runner pauses with `[PAUSED] Setup failed for ...`, inspect the emulator, finish the visible setup prompt, then press Enter in the runner terminal.

Known manual choices:

- Chrome: choose `Use without an account`, then `No thanks` for notifications.
- Contacts notification prompt: choose `Don't allow` / `Don’t allow`.
- Markor: if already on the main file browser, press Enter in the runner terminal.
- Simple Gallery Pro: if already on the gallery screen, press Enter in the runner terminal.
- Simple SMS Messenger: if already in the SMS inbox, press Enter in the runner terminal.

## 3. Recover Snapshots Into The Persistent Path

After setup, while the emulator is still booted, run from repo root:

```bash
cd /home/thivux/code/vinai/GUI_agent/AndroidAutonomy
tasks/snapshot-universal-fix/setup_apps/recover_snapshots.sh
```

This copies:

```text
/data/data/<package>/
```

to:

```text
/data/local/tmp/android_world/snapshots/<package>/
```

The script should print `saved ...` for each expected package and then list the snapshot directories.

## 4. Verify Snapshots

```bash
adb -s emulator-5554 root
adb -s emulator-5554 shell ls /data/local/tmp/android_world/snapshots/
```

Expected directories include:

```text
com.android.chrome
com.google.android.contacts
com.simplemobiletools.gallery.pro
com.simplemobiletools.smsmessenger
org.videolan.vlc
```

## 5. Cleanly Stop And Reboot-Test

Cleanly stop the emulator so userdata is flushed:

```bash
adb -s emulator-5554 emu kill
```

Start it again with the same boot command from step 1, then verify the persistent path again:

```bash
adb -s emulator-5554 root
adb -s emulator-5554 shell ls /data/local/tmp/android_world/snapshots/
```

If the directories are still there after reboot, the base AVD is ready.

## 6. Run Eval

```bash
cd /home/thivux/code/vinai/GUI_agent/AndroidAutonomy/MARS-Voyager
NUM_WORKERS=4 CONFIG_NAME=UI-Voyager MODEL_NAME=UI-Voyager ./run_android_world.sh
```

`run_android_world.sh` copies the base AVD into worker AVDs. Each copy should contain the persistent snapshots.

To check logs after a run:

```bash
grep "Skipping app snapshot" eval_results/UI-Voyager/logs/<TIMESTAMP>/eval_*.log | wc -l
```

A successful bootstrap should reduce missing snapshot warnings to zero or close to zero.

## Troubleshooting

- `adb server version doesn't match this client`: ensure `which adb` is `$HOME/Android/Sdk/platform-tools/adb`, then run `hash -r`, `adb kill-server`, and `adb start-server`.
- `Running multiple emulators with the same AVD`: another `AndroidWorldAvd` process is already running. Check with `pgrep -af "emulator|qemu-system|AndroidWorldAvd"`.
- `adb: device offline`: restart ADB with `adb kill-server && adb start-server`, then wait for boot to finish.
- `/data/data/android_world/snapshots` is missing: expected for this repo. Use `/data/local/tmp/android_world/snapshots`.
- Snapshots disappear after reboot: rerun `tasks/snapshot-universal-fix/setup_apps/recover_snapshots.sh`, verify `/data/local/tmp/android_world/snapshots`, then stop with `adb emu kill`.
