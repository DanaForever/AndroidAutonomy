# Plan — Investigate Snapshot Loading as a Universal Init Fix

## Context

Across the 17 rescued tasks in [`tasks/rescue-trajectory-analysis-new/`](../rescue-trajectory-analysis-new/) and the always-failed tasks in [`tasks/my_report.md`](../my_report.md), per-task suggestions were drafted, but the same warning appears repeatedly in the worker log for many of them:

```
WARNING:absl:Skipping app snapshot loading : Snapshot not found in
    /data/data/android_world/snapshots/<package_name>
```

Hypothesis (the user's): **if the snapshot loaded successfully, many init-related failures would disappear at once**, removing the need for per-task patches. This plan exists to test that hypothesis end-to-end before we commit to either path:

- a single, universal fix (make snapshots exist and load), or
- the per-task fixes already drafted in `conclusion.md`.

Today's behavior — `_initialize_apps` catches the missing-snapshot `RuntimeError` and silently continues ([`task_eval.py:116`](../../MARS-Voyager/androidworld/android_world/task_evals/task_eval.py#L116)) — means the previous task's `/data/data/<pkg>` state leaks into the next task. That is the most plausible upstream cause for a large fraction of "state leakage" symptoms in the analyses.

## Why this might be a universal fix (and where it isn't)

Cross-referencing [`conclusion.md`](../rescue-trajectory-analysis-new/conclusion.md):

| Cat | Symptom | Would a working snapshot fix it? |
|----:|---------|----------------------------------|
| 1 | SystemUI / launcher residual state | **No.** Snapshots only restore `/data/data/<pkg>`; they don't touch SystemUI, notifications, At-a-Glance, or quick-settings. |
| 2 | Auxiliary tables, `shared_prefs` | **Yes.** `restore_snapshot` overwrites the whole app data directory, including `shared_prefs/`. |
| 3 | Snapshot restore failure / absence | **Yes — by definition.** |
| 4 | A11y tree fetch failure | **No.** Independent infra failure. |
| 5 | Pixel-level / async UI fluctuation | **Partly.** A canonical fresh state can reduce some async drift (e.g. cold-start animations are more reproducible than warm-start), but scroll physics / render timing is independent. |
| 6 | Agent / serving / harness control | **No.** |

So the universal-fix hypothesis is roughly: **fixing snapshots collapses Cat 2 + Cat 3 entirely, and partially attenuates Cat 5**. Cat 1, 4, 6 still need their own treatment.

This is worth quantifying before we either ship per-task patches or commit to a snapshot rebuild.

## Debate — "wouldn't a working snapshot just reset the whole emulator?"

**Your intuition (paraphrased):** a snapshot is a checkpoint of the emulator at a known good moment. Loading it puts the whole device back into that state. So for `ClockStopWatchRunning`, loading the snapshot would give us a fresh emulator with no leaked overlay from the previous task. Therefore one fix — make snapshots load — should kill most "residual state" failures across the board.

**My pushback:** that intuition is correct *for* a true emulator-level snapshot (what QEMU / `emulator -snapshot` / Android Studio "Snapshots" gives you — full RAM + disk + framebuffer of the VM). But the thing called "snapshot" in this codebase is **not** an emulator snapshot. It is a per-app data-directory backup. Read the implementation:

- [`app_snapshot.save_snapshot(app_name, env)`](../../MARS-Voyager/androidworld/android_world/utils/app_snapshot.py#L54): copies `/data/data/<package>` into the configured snapshot root on the *running* emulator. In this branch that root is `/data/local/tmp/android_world/snapshots/<package>`. No RAM, no other apps, no SystemUI, no kernel state.
- [`app_snapshot.restore_snapshot(app_name, env)`](../../MARS-Voyager/androidworld/android_world/utils/app_snapshot.py#L81): force-stops the app via [`adb_utils.close_app`](../../MARS-Voyager/androidworld/android_world/utils/app_snapshot.py#L93), wipes `/data/data/<package>`, then copies the saved tree back. Again, only the app's own data directory.
- The path constant: [`device_constants.SNAPSHOT_DATA = "/data/local/tmp/android_world/snapshots"`](../../MARS-Voyager/androidworld/android_world/env/device_constants.py#L26). Confirms it's a directory inside the live FS, not a VM image.
- Which apps get restored: only the ones declared in `task.app_names`. See the loop in [`task_eval._initialize_apps`](../../MARS-Voyager/androidworld/android_world/task_evals/task_eval.py#L116) — `for app_name in self.app_names: restore_snapshot(app_name, env.controller)`.

So "loading the snapshot" in this code = `pm clear`-style reset of one app's `/data/data/<pkg>` directory, then file copy. It does **not** reset:

- The launcher process (`com.google.android.apps.nexuslauncher`) and its render cache.
- SystemUI (`com.android.systemui`) — notifications, quick-settings tile state, bubbles, recents.
- AppWidget host state (the At-a-Glance widget that leaked the stopwatch overlay in [`02-clock-stopwatch-running.md`](../rescue-trajectory-analysis-new/02-clock-stopwatch-running.md) is rendered by the launcher, not by DeskClock).
- Other apps not declared in the current task's `app_names`.
- Global Android settings (Wi-Fi/Bluetooth tile state, brightness, screen timeout, datetime — handled separately by [`datetime_utils`](../../MARS-Voyager/androidworld/android_world/utils/) and quick-settings code paths).

**Walk through your ClockStopWatch example with this in mind.** `ClockStopWatchRunning.app_names = ("clock",)` ([`clock.py:114`](../../MARS-Voyager/androidworld/android_world/task_evals/single/clock.py#L114)). If the snapshot existed and loaded:
1. `restore_snapshot("clock", env.controller)` runs.
2. It calls `close_app` on `com.google.android.deskclock` → force-stop. Force-stop does dispatch notification cancellation for that package.
3. It clears `/data/data/com.google.android.deskclock` and copies the saved baseline back.
4. `restorecon` + `chmod 777` ([`app_snapshot.py:114-125`](../../MARS-Voyager/androidworld/android_world/utils/app_snapshot.py#L114)).

Now look at what [`02-clock-stopwatch-running.md`](../rescue-trajectory-analysis-new/02-clock-stopwatch-running.md) says the residual actually was: the **Pixel launcher's At-a-Glance widget**, which is owned by `com.google.android.apps.nexuslauncher` and **renders cached RemoteViews** from the previously-posted DeskClock notification. The widget's render thread doesn't redraw until it receives a `onNotificationRemoved` callback. The notification cancellation from step 2 is *asynchronous and crosses process boundaries* — the launcher's redraw can lag the `restore_snapshot` return by hundreds of ms, which is exactly the race window that produced the R0 failure. **So even with a perfect, fully-working snapshot, that specific overlay can still leak**, because the leak is in the launcher process's cache, not in DeskClock's `/data/data`.

The other categories where the user's intuition *is* essentially right:
- **Cat 2 (auxiliary tables / shared_prefs):** the leaked state lives in `/data/data/<the_task's_app>/shared_prefs/` or `/data/data/<the_task's_app>/databases/`. A working snapshot rewrites that directory. Fixed.
- **Cat 3 (snapshot absence):** trivially fixed.
- Some Cat 5 cases where async drift is actually rooted in a non-canonical app data dir: also helped.

The cases where the intuition breaks:
- **Cat 1** (the ClockStopWatch class of bug): residual is in *another* process — launcher, SystemUI, or a different app's data — that the per-app snapshot does not touch.
- **Cat 4 / Cat 6:** unrelated to app data state.

**What would actually match your mental model.** A *true* QEMU emulator snapshot — saved with `adb emu avd snapshot save <name>` and restored with `adb emu avd snapshot load <name>` (or via `emulator -snapshot <name>`) — would freeze and restore RAM + all process state + SystemUI + launcher cache. That would close the Cat 1 gap as well. Tradeoffs: snapshot save/load takes seconds-to-tens-of-seconds, the snapshot file is large (hundreds of MB to GBs per AVD per snapshot), and the multi-worker AVD-copy flow in `run_android_world.sh` would need to be reworked to ship those snapshots per-worker. So it's a heavier intervention than fixing the per-app snapshot path, and probably not worth doing as the first step — but it's the design that *would* make your one-fix-fixes-all hypothesis literally true.

**Conclusion of the debate.** Your hypothesis is right *if and only if* "snapshot" means full-VM checkpoint. In this codebase it doesn't. The naming is misleading. Fixing the existing snapshot mechanism removes Cat 2 + Cat 3 entirely, but Cat 1 (the ClockStopWatch case you raised) needs either (a) extra global cleanup steps in `initialize_task` — clear notifications, close bubbles, return to launcher and wait for redraw — or (b) a switch to true emulator-level snapshots.

## Why snapshots are missing (initial finding, to confirm)

Snapshots are produced only by [`setup.setup_app`](../../MARS-Voyager/androidworld/android_world/env/setup_device/setup.py#L119), which calls [`app_snapshot.save_snapshot`](../../MARS-Voyager/androidworld/android_world/utils/app_snapshot.py#L54). That path runs only when the env is launched with `emulator_setup=True` ([`env_launcher.setup_env`](../../MARS-Voyager/androidworld/android_world/env/env_launcher.py#L95)).

The eval runner hardcodes `emulator_setup=False` ([`runner.py:54`](../../MARS-Voyager/androidworld/eval/runner.py#L54)). So eval runs never create snapshots. Snapshots only exist if a prior, separate one-time setup pass baked them into the AVD image we're cloning per worker. The recurring "Snapshot not found" lines for apps like DeskClock, AudioRecorder, and others suggest the base AVD was never given a complete setup pass — or the snapshots were lost when AVDs were copied / reset.

This needs to be confirmed empirically (Phase 1) before designing the fix.

## Investigation Plan

### Phase 1 — Quantify the impact and confirm root cause (read-only)

Goal: produce numbers, not opinions, for the universal-fix question.

1. **Snapshot inventory on a live emulator.**
   - Boot one worker AVD using the existing `run_android_world.sh` flow (or `adb shell` into a running one).
   - Run `adb shell ls /data/local/tmp/android_world/snapshots/` and record which packages have snapshots vs. which don't.
   - Cross-reference against the apps used by the 116 tasks (the task → `app_names` mapping is in each task class under [`task_evals/`](../../MARS-Voyager/androidworld/android_world/task_evals/)).
   - **Deliverable:** `tasks/snapshot-universal-fix/snapshot-inventory.md` — a table: `app_name | snapshot present? | # tasks affected`.

2. **Worker-log audit.**
   - Grep `eval_results/UI-Voyager/logs/20260426203107/eval_UI-Voyager_1workers.log` for `Skipping app snapshot loading` and bucket by package.
   - For each `(task, round)` pair in the 17 rescued tasks and the 32 always-failed tasks, record whether a snapshot warning fired during its `initialize_task` window.
   - **Deliverable:** append a `snapshot_warning_fired` column to the executive table in [`rescue-trajectory-analysis-new/index.md`](../rescue-trajectory-analysis-new/index.md) (or a parallel sheet in this folder).

3. **Counterfactual check on a small set.**
   - Pick 3–5 tasks where the analysis tags Cat 2 or Cat 3 (e.g. `AudioRecorderRecordAudioWithFileName`, `MarkorDeleteNote`, `MarkorCreateNoteFromClipboard`).
   - Manually create a snapshot for the relevant package (run `setup.setup_app` for that one app on the worker AVD, or call `save_snapshot` directly via a Python REPL with `PYTHONPATH` set per the project's CLAUDE.md).
   - Re-run just those tasks via `python test_android_world.py --num_workers 1 --start_port 5556` against a config that filters to the chosen task IDs.
   - Record whether the failure mode disappears.
   - **Deliverable:** `tasks/snapshot-universal-fix/counterfactual-results.md`.

### Phase 2 — Design the universal fix (only if Phase 1 confirms impact)

Two parallel changes, each independently shippable:

**A. Make snapshots exist for every evaluated app.**
- Add a one-time setup flow under [`setup_apps/`](setup_apps/) that the user runs against the base AVD before eval (or set `emulator_setup=True` for the very first run and persist the resulting AVD).
- Recover snapshots with [`setup_apps/recover_snapshots.sh`](setup_apps/recover_snapshots.sh), which copies app data into `/data/local/tmp/android_world/snapshots`.
- Verify the snapshots survive the AVD-copy step in `run_android_world.sh` (they're in the userdata partition and *should* be cloned, but this needs a quick adb check after copy).

**B. Make missing-snapshot a hard error, not a warning.**
- Change [`task_eval._initialize_apps`](../../MARS-Voyager/androidworld/android_world/task_evals/task_eval.py#L116) so that when `restore_snapshot` raises `RuntimeError`, the harness either:
  - falls back to `clear_app_data(<pkg>)` (deterministic empty state), and / or
  - emits a structured per-task setup error that fails the task fast instead of running it on leaked state.
- This gives us a deterministic floor even when (B) is incomplete.

The two changes together close Cat 2 + Cat 3 from `conclusion.md`. Cat 1 (SystemUI residual state) still needs its own pre-observation cleanup hook — out of scope for this plan but flagged.

### Phase 3 — Verification (after fix is implemented)

1. Re-run a slice of the eval on the rescued + always-failed task lists with the snapshot fix in place; compare round-0 success rates pre/post.
2. Confirm the worker log no longer contains `Skipping app snapshot loading` for the targeted packages.
3. Re-walk the `rescue-trajectory-analysis-new/` task files and mark which Cat 2 / Cat 3 verdicts flip from "env bug — should fix" to "resolved by snapshot fix".

## Critical Files (read-only references)

- Snapshot save/restore: [`app_snapshot.py`](../../MARS-Voyager/androidworld/android_world/utils/app_snapshot.py) (`save_snapshot` L54, `restore_snapshot` L81)
- Snapshot path constant: [`device_constants.SNAPSHOT_DATA`](../../MARS-Voyager/androidworld/android_world/env/device_constants.py#L26) = `/data/local/tmp/android_world/snapshots`
- Init path: [`task_eval._initialize_apps`](../../MARS-Voyager/androidworld/android_world/task_evals/task_eval.py#L116)
- Setup path: [`setup.setup_app`](../../MARS-Voyager/androidworld/android_world/env/setup_device/setup.py#L119), [`setup.setup_apps`](../../MARS-Voyager/androidworld/android_world/env/setup_device/setup.py#L165)
- Snapshot bootstrap docs/script: [`setup_apps/instructions.md`](setup_apps/instructions.md), [`setup_apps/recover_snapshots.sh`](setup_apps/recover_snapshots.sh)
- Setup gate: [`env_launcher.setup_env`](../../MARS-Voyager/androidworld/android_world/env/env_launcher.py#L95) (`emulator_setup` flag)
- Where the gate is closed in eval: [`eval/runner.py:54`](../../MARS-Voyager/androidworld/eval/runner.py#L54)
- Worker log: `MARS-Voyager/eval_results/UI-Voyager/logs/20260426203107/eval_UI-Voyager_1workers.log`
- Existing per-task analyses: [`tasks/rescue-trajectory-analysis-new/`](../rescue-trajectory-analysis-new/), [`tasks/my_report.md`](../my_report.md)

## Open Questions (resolve before Phase 2)

1. Was the base AVD ever given a full `setup_apps` pass? If yes, where did the snapshots go? If no, that's the immediate fix.
2. Does the AVD copy step in `run_android_world.sh` preserve `/data/local/tmp/android_world/snapshots/`?
3. For tasks that *don't* warn about missing snapshots (where the snapshot loaded fine), do we still see Cat 2 leakage? If yes, the universal-fix hypothesis is weaker than expected and the per-task fixes remain necessary.

## Out of Scope

- Cat 1 (SystemUI / launcher residual state), Cat 4 (a11y), Cat 5 (pixel/async), Cat 6 (agent/serving) — none of these are addressed by snapshots; they keep their existing per-category recommendations.
- No model / prompt changes.
- No re-running the full 116-task suite as part of this plan; only targeted re-runs in Phase 1 step 3.

## Structured Debate — Three Rounds (subagents)

To stress-test the universal-fix hypothesis, two adversarial subagents argued PRO and CON across three rounds. Full transcripts below; verdict at the end of this section.

### Round 1 — Opening Arguments

#### PRO R1 — Opening

The hypothesis: most env-init failures trace to the silent `Skipping app snapshot loading` path. Two coupled fixes are required:

1. **Make snapshots exist for every evaluated app.** [`eval/runner.py:54`](../../MARS-Voyager/androidworld/eval/runner.py#L54) hardcodes `emulator_setup=False`, so [`save_snapshot`](../../MARS-Voyager/androidworld/android_world/utils/app_snapshot.py#L54) never runs at eval time. Snapshots only exist if the base AVD was pre-baked.
2. **Harden the fallback.** [`task_eval._initialize_apps`](../../MARS-Voyager/androidworld/android_world/task_evals/task_eval.py#L116) currently swallows the `RuntimeError` and proceeds on poisoned state. Replace with `clear_app_data` + structured failure flag.

Cat 2 + Cat 3 are definitionally about app-private state. Concrete tasks: 14 AudioRecorder (stale DB row), 15/16/17 Markor (shared_prefs, last-opened-doc, missing snapshot), 01 TasksDueOnDate. Markor/Recipe/Tasks/Notes always-failed clusters compound with leaked shared_prefs.

**Counter to "per-app snapshot ≠ full-VM":** [`restore_snapshot`](../../MARS-Voyager/androidworld/android_world/utils/app_snapshot.py#L93) already calls `close_app` (`am force-stop`), which dispatches `NotificationManager.cancelAll()`. That cancellation is what the launcher's RemoteViews cache needs. A 200ms post-restore wait closes the race. For genuinely-cross-process Cat 1 cases, the QEMU snapshot path is feasible — heavier but the same conceptual fix at a deeper layer.

**Scoreboard:** ≥5 rescued tasks directly + always-failed Markor/Recipe cluster + Cat 1 bite via force-stop + nondeterminism removed.

#### CON R1 — Opening

The PRO position rests on a name. "Snapshot" in this codebase is a per-app `/data/data` backup, not a VM checkpoint.

[`save_snapshot`](../../MARS-Voyager/androidworld/android_world/utils/app_snapshot.py#L54) `cp -r`'s `/data/data/<package>` into [`SNAPSHOT_DATA = "/data/data/android_world/snapshots"`](../../MARS-Voyager/androidworld/android_world/env/device_constants.py#L26) on the live emulator. [`restore_snapshot`](../../MARS-Voyager/androidworld/android_world/utils/app_snapshot.py#L81) does close_app + wipe + copy back. No RAM, no SystemUI, no launcher, no other packages. The loop in [`_initialize_apps`](../../MARS-Voyager/androidworld/android_world/task_evals/task_eval.py#L116) iterates only `self.app_names` — for `ClockStopWatchRunning.app_names = ("clock",)` ([`clock.py:114`](../../MARS-Voyager/androidworld/android_world/task_evals/single/clock.py#L114)), only DeskClock is touched.

The conclusion.md matrix shows **only 4 of 17 rescued tasks (14, 15, 16, 17) carry Cat 2/3** — the only categories the existing snapshot mechanism addresses. The other 13:
- **02 ClockStopWatchRunning** ([detail](../rescue-trajectory-analysis-new/02-clock-stopwatch-running.md)): leaked state was the **Pixel launcher's At-a-Glance widget** (owned by `com.google.android.apps.nexuslauncher`). DeskClock snapshot restore would not touch it.
- **03/04/05 Bluetooth + 06 Wifi:** quick-settings tile state lives in SystemUI. 03/04 also include Cat 6 hallucinations.
- **07/08 Brightness:** global Settings.System value, not in `/data/data/<app>`.
- **09/11:** Cat 1 + Cat 6.
- **01/10/12/13:** Cat 5 — pixel/async fluctuation.

Always-failed totals from [`my_report.md`](../my_report.md): 17 premature, 9 app-not-found drawer-loops, 18 compound, 8 visual. Six are the SMS Messenger drawer-loop — the agent never reaches the app. No `/data/data` restore fixes that.

**QEMU escalation:** seconds per task across 116 tasks; hundreds of MB to GBs per AVD; `AndroidWorldAvd_worker_<i>` copy flow in `run_android_world.sh` would need rework; `loadvm` tears the running VM out from under the gRPC/ADB session AndroidEnv holds. Heavier rebuild than PRO proposes.

**Bound:** ~4/17 rescued, ~0/32 always-failed. Useful, not universal.

### Round 2 — Rebuttals

#### PRO R2 — Rebuttal

CON's argument rests on three slippages: (1) treating "primary cause" tags as exhaustive, (2) treating the *current* `app_names` configuration as a property of the mechanism, (3) treating env-induced agent error as agent failure.

1. **Tagging artifact.** Pull worker logs for tasks 02, 03, 04, 06, 07, 08 — `Skipping app snapshot loading` fires in every one during init. That means `_initialize_apps` fell through and the app's `/data/data` was never reset between episodes. Reset DeskClock cleanly and the 02 widget race has nothing stale to latch onto.
2. **SystemUI/tile claim is self-defeating.** `BluetoothAdapter.isEnabled()` reflects radio state owned by `com.android.bluetooth` — which appears in NO task's `app_names`. The fix is one line per task_eval subclass: add the package. The mechanism scales; the configuration is undersized.
3. **Notification race is a missing await.** Add bounded poll on `cmd notification list` until drains (cap 2s). Closes race deterministically. Hook point already exists.
4. **"Always-failed = agent failure" misreads upstream causes.** In several drawer-loop traces the first observation shows a residual dialog/notification fragment occluding the launcher icon. Even 30% conversion on 9 drawer-loop tasks = 3 more rescues.
5. **QEMU not as exotic as CON suggests.** AndroidEnv reconnects after emulator bounces (multi-worker flow exercises this). Same fix at lower layer, available as fallback.

**Revised bound:** ~13 of 49.

#### CON R2 — Rebuttal

PRO's R1 quietly mutates from "fix snapshot loading" into "ship two new interventions plus a QEMU rewrite."

1. **Force-stop misidentifies the actor.** The leaking notification in 02 was posted by the **previous task** (`ClockStopWatchPausedVerify`). By the time `ClockStopWatchRunning.initialize_task` runs, the prior task is already torn down. `restore_snapshot` only force-stops the *current* task's `app_names`. If the residual notification's owning package isn't in the new task's declared apps, force-stop never fires on the right target. The "snapshot fix collaterally fixes Cat 1" claim is wrong on the call graph.
2. **Launcher race remains.** Even when force-stop fires on the right package, the launcher's RemoteViews redraw is async on `onNotificationRemoved`. PRO's "200ms wait" is an admission: a fix bolted on *outside* snapshot semantics.
3. **Hardened fallback is NEW behavior.** [`task_eval.py:124-125`](../../MARS-Voyager/androidworld/android_world/task_evals/task_eval.py#L124) currently just `logger.warning` + continue — there is no `clear_app_data` call. PRO's fallback is net-new behavior smuggled in as "fixing snapshot loading."
4. **Per-app keyed mechanism can't see cross-task contamination.** If task N pollutes app X and task N+1 doesn't declare X, restoring N+1's snapshots literally cannot touch X. Structural limit.
5. **QEMU pivot is bait-and-switch.** Different mechanism, different cost (snapshot file size, ADB session continuity), different failure modes. "We need a bigger hammer when small one misses" ≠ "one universal fix."

**What PRO gets right:** flipping `emulator_setup` is correct. Replacing the silent `RuntimeError` swallow with `clear_app_data` is correct. Both should ship. But these resolve Cat 2 and parts of Cat 3 — not Cat 1, not cross-task undeclared-app contamination, not agent-side failures. Bound holds.

### Round 3 — Closings (with concessions)

#### PRO R3 — Closing

Real concessions first:

- **Force-stop call graph (CON #1): conceded.** I overclaimed. The Cat 1 dividend from force-stop only holds when the polluting package happens to be declared by the next task — minority case across a randomized suite. Real but small.
- **Smuggled cleanup (CON #3): conceded.** Calling `clear_app_data` from the fallback is genuinely *new* behavior. Two coupled changes, not "fixing" one path.
- **Undeclared-app contamination (CON #4): conceded as a hard structural limit.** Per-app snapshots keyed on `task.app_names` cannot, even in principle, scrub state in apps the next task doesn't name. SystemUI tiles, Bluetooth daemon state, notification-listener registrations from undeclared packages are blind to snapshot restore. Needs a different mechanism (global reset, allowlist scrub, or QEMU-level rollback).
- **QEMU pivot (CON #5): conceded as a separate intervention.** Different layer, different cost, different failure surface. Not "the same fix, deeper."
- **Launcher poll (CON #2): held narrowly.** A bounded poll on `cmd notification list` is ~10 LOC inside the snapshot/restore boundary. The slope from "one poll" to "per-category sleeps everywhere" is not automatic.

**Refined position:** Fixing snapshot creation + hardening the fallback to actually clear declared-app state addresses a **plurality, not a majority**, of init errors. The residual — undeclared-app contamination, SystemUI/tile state, notification daemons — is structural and needs a different mechanism.

**Final position:** Snapshot-loading fix plus coupled fallback cleanup is the highest-ROI single intervention and should ship first, but it is a plurality fix, not a universal one, and the undeclared-app residual genuinely requires a separate mechanism.

#### CON R3 — Closing

Where PRO earned ground:

- **Correlation evidence (PRO #1):** the warning does fire for tasks 02, 03, 04, 06, 07, 08 during init. Matrix tags don't close the question. The re-tag is exactly what Phase 1 step 3 of this plan prescribes. Don't assume the conversion; measure it.
- **Mechanism extends to `com.android.bluetooth` (PRO #2):** conceded that adding it to relevant `app_names` is correct and the mechanism does extend cleanly. What I won't concede is the framing — this is per-task configuration work, audited subclass by subclass. The mechanism scales; the rollout doesn't, without effort. That's exactly the per-task labor the "universal" pitch was meant to avoid.
- **Bounded notification poll (PRO #3):** real, deterministic, ship it. But it's a post-reset cleanup hook on Cat 1, not a snapshot semantic. Separable.
- **Drawer-loop conversion (PRO #4):** plausible; remains unfalsified until traces are replayed. Don't bank rescues you haven't measured.
- **AndroidEnv reconnect (PRO #5):** granted on worker spawn. `loadvm` mid-episode is still a different operational profile (uptime jumps, timer-driven services re-anchor). Not exotic; not free.

**Refined position:** The snapshot reset is net-positive and should ship. But the "universal" claim only holds once you bundle it with: `app_names` auditing per task, a post-restore notification/SystemUI drain, and a re-tag pass on the always-failed cluster. At that point the bundle deserves a different name than "snapshot fix" — because three of the four interventions aren't snapshot semantics.

**Final position:** Ship the snapshot reset as one of four interventions in a bundle, but stop calling the bundle "the snapshot fix" and stop promising universality before the re-tag measurement is in.

---

## Verdict (post-debate, for skimming)

**Both sides converged.** The original "fix snapshot loading = universal init fix" hypothesis was overclaimed; the mirror "snapshot fix is nearly useless" was also wrong. The honest position sits in the middle.

### What the debate established

| Claim | Verdict |
|-------|---------|
| Fixing snapshot loading is a *single* intervention | **False.** It requires at minimum two coupled changes (make snapshots exist + harden the silent fallback in [`_initialize_apps`](../../MARS-Voyager/androidworld/android_world/task_evals/task_eval.py#L116)). |
| It cleanly resolves Cat 2 + Cat 3 (~4 rescued tasks directly) | **True.** This is the floor of expected value. |
| It collaterally fixes Cat 1 via `restore_snapshot`'s force-stop dispatching notification cancellation | **Mostly false.** Force-stop only fires on the *next task's* declared `app_names`; the polluting package from the prior task is rarely the same. The Cat 1 dividend is small and depends on lucky package overlap. |
| Per-app snapshot can scrub cross-task contamination from undeclared packages | **False — structural limit.** SystemUI, launcher widget cache, daemons from undeclared apps are unreachable by per-app `/data/data` restore. |
| The SystemUI/tile-state limit is a *configuration* gap (missing `com.android.bluetooth` etc. from `app_names`), not a *mechanism* gap | **True, but disqualifies the "universal" framing** — fixing it requires per-task `app_names` audits, the exact per-task labor the universal pitch was meant to avoid. |
| QEMU-level (`emulator -snapshot`) is "the same fix at a deeper layer" | **False.** Different mechanism, different cost (seconds per load, hundreds of MB), different failure modes (`loadvm` mid-episode disrupts gRPC/ADB session continuity in ways worker-spawn does not). It's a separate intervention worth considering on its own merits. |
| Always-failed cluster (32 tasks, dominated by drawer-loop / premature-terminate / compound-budget) is significantly addressable by snapshot fix | **Probably false, but unmeasured.** The "leaked state caused the agent hallucination" theory is plausible for some traces but needs the empirical re-run in Phase 1 step 3 before counting rescues. |

### What to do (action verdict)

**Ship, in this order, as a bundle — and stop calling it "the snapshot fix":**

1. **Make snapshots exist for every evaluated app.** Flip `emulator_setup` once on the base AVD; verify snapshots survive the per-worker AVD copy in `run_android_world.sh`. ([`runner.py:54`](../../MARS-Voyager/androidworld/eval/runner.py#L54), [`env_launcher.py:95`](../../MARS-Voyager/androidworld/android_world/env/env_launcher.py#L95), [`setup.py:119`](../../MARS-Voyager/androidworld/android_world/env/setup_device/setup.py#L119))
2. **Harden the fallback in [`_initialize_apps`](../../MARS-Voyager/androidworld/android_world/task_evals/task_eval.py#L116):** on `RuntimeError`, call `clear_app_data(<pkg>)` instead of swallowing the warning. Emit a structured setup-status flag so missing snapshots fail fast rather than running on poisoned state.
3. **Audit `app_names` per task** for SystemUI-adjacent residuals: add `com.android.bluetooth`, `com.android.systemui` etc. to tasks that touch those surfaces. Per-subclass work; not glamorous.
4. **Add a post-restore cleanup hook** at the end of [`restore_snapshot`](../../MARS-Voyager/androidworld/android_world/utils/app_snapshot.py#L81) (or in `_initialize_apps` after the loop): bounded poll on `cmd notification list`, dismiss launcher overlays, settle delay capped at ~2s. This is the Cat 1 mitigation `conclusion.md` already proposed.
5. **Run the empirical re-tag from Phase 1 step 3** *before* claiming any cross-cluster rescues. Don't bank the drawer-loop conversion until the traces are replayed.

**Defer:** QEMU-level (`emulator -snapshot`) rollback. Real fallback if (1)–(4) prove insufficient, but not the first intervention.

### TL;DR

> **Snapshot-loading fix is the highest-ROI single intervention but it is a plurality fix, not a universal one. The "universal" framing requires bundling it with three other interventions, at which point the bundle deserves a different name. Ship the bundle; do the empirical re-tag before claiming wider impact.**
