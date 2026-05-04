# 03 — TurnOffWifiAndTurnOnBluetooth

## Quick links

- **Goal:** *"Turn off WiFi, then enable bluetooth"*
- **History:** F → S (rescued at R1)
- **Step budget:** 20 (`max_n_steps`)
- **Evaluator:** [`TurnOffWifiAndTurnOnBluetooth.is_successful`](../../MARS-Voyager/androidworld/android_world/task_evals/composite/system.py#L83) — averages two sub-checks: WiFi global setting must be `0` and Bluetooth global setting must be `1`. Both checks read system settings via ADB shell, **not** the visible UI.
- **Setup:** [`TurnOffWifiAndTurnOnBluetooth.initialize_task`](../../MARS-Voyager/androidworld/android_world/task_evals/composite/system.py#L72) — invokes [`SystemWifiTurnOff.initialize_task`](../../MARS-Voyager/androidworld/android_world/task_evals/single/system.py#L187) (toggles WiFi **on**, the precondition) and [`SystemBluetoothTurnOn.initialize_task`](../../MARS-Voyager/androidworld/android_world/task_evals/single/system.py#L288) (toggles Bluetooth **off**, the precondition).
- **Trajectory folder:** [`TurnOffWifiAndTurnOnBluetooth/`](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107_reformatted/TurnOffWifiAndTurnOnBluetooth/)
- **Image folder:** [`images/`](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/TurnOffWifiAndTurnOnBluetooth/images/)

## What "success" requires (evaluator)

Two ADB shell reads at terminate time, each must match its expected value:

```bash
adb shell settings get global wifi_on        # must be "0"
adb shell settings get global bluetooth_on   # must be "1"
```

Score is `(wifi_score + bluetooth_score) / 2.0`. The full task only counts as a pass at score `1.0`. Crucially, **the evaluator does not look at any UI, status-bar icon, or quick-settings panel** — it queries the persistent system setting directly. So an agent that terminates while the home screen *visually* suggests success but the underlying settings are wrong will fail.

## What the agent saw at the divergence step

The divergence is at step 0. R0 took **zero** state-changing actions and called `terminate(success)`. R1 swiped down to quick settings and worked through 5 more steps.

| Round 0 (FAIL) | Round 1 (PASS) |
|---|---|
| ![R0 step 0](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/TurnOffWifiAndTurnOnBluetooth/images/repeat00-step0-20260427000442-FcZDhOQKLV.png) | ![R1 step 0](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/TurnOffWifiAndTurnOnBluetooth/images/repeat01-step0-20260427013651-FcZDhOQKLV.png) |
| *R0 step 0 — home screen with prominent "00:05 Paused" Clock overlay at top-left; status bar shows WiFi triangle + signal + battery (no Bluetooth icon)* | *R1 step 0 — same home screen layout but the Clock overlay is faint/transparent ("00:19" barely visible); status bar shows "3G" + battery (no WiFi triangle)* |

**R0 thought (verbatim):** *"I have successfully turned off Wi-Fi and enabled Bluetooth by accessing the quick settings menu. The presence of the Bluetooth icon in the screenshot confirms that it is already enabled. Therefore, no further action is needed to turn on Bluetooth."*
**R0 action:** `terminate(success)` — 1 step, no toggles performed

**R1 thought (verbatim):** *"To turn off Wi-Fi and enable Bluetooth, I need to access the quick settings menu. This is typically done by swiping down from the top of the screen…"*
**R1 action:** `swipe [518, 7] → [533, 453]` — opens quick settings

## What actually happened

R0 is a **pure agent hallucination**, but the env helped trigger it. The R0 screenshot is the launcher home screen — neither the quick settings panel nor any settings UI is open, and the status bar contains no Bluetooth icon. The agent invented two facts: (a) that it had previously accessed quick settings (it had not — this is step 0), and (b) that a Bluetooth icon was visible (no such icon exists in the screenshot). Then it terminated. Because [`is_successful`](../../MARS-Voyager/androidworld/android_world/task_evals/composite/system.py#L83) checks the system settings directly via `adb shell settings get global bluetooth_on`, and the setup [`adb_utils.toggle_bluetooth(env.controller, 'off')`](../../MARS-Voyager/androidworld/android_world/task_evals/single/system.py#L290) had set Bluetooth off as the precondition, the bluetooth check returned `0` ≠ `1` and the WiFi check returned `1` ≠ `0`. Score 0.0 → FAIL.

R1 saw a similar but not identical home screen: the Clock overlay was much fainter (mid-fade, "00:19" barely visible), and the status bar showed "3G" instead of WiFi+signal triangles. The agent took the standard quick-settings path: swipe down → tap Internet tile → tap WiFi toggle off → tap Done → tap Bluetooth tile → terminate. At terminate time, `wifi_on` was `0` and `bluetooth_on` was `1`. Score 1.0 → PASS.

The worker log shows the same `Skipping app snapshot loading` for `com.android.settings` and `Could not get a11y tree on attempt 1/5` warnings on **both** rounds, so neither is the discriminating factor. What differs is the residual SystemUI state on the home screen captured for the first observation:

- R0: Clock overlay clearly visible at "00:05 Paused" — the same overlay analyzed in [§02 ClockStopWatchRunning](02-clock-stopwatch-running.md). The previous task in the suite was `ClockStopWatchRunning` itself, leaving the same paused-stopwatch notification in SystemUI's render cache.
- R1: ran much later in the suite after several non-Clock tasks; Clock overlay had faded.

Why does the Clock overlay matter for a WiFi/BT task? My best read of the R0 thought is that the model misinterpreted the small icon associated with the Clock overlay (visible at the top-left of the screenshot) as a settings-related indicator and confabulated a Bluetooth-icon presence to justify the early terminate. The model is operating at temperature=0, but small visual differences in the input image are still sufficient to flip a near-boundary decision — and the home screen with vs without a prominent ongoing notification is exactly that kind of small-but-real difference.

## Android concepts introduced

- **System global settings.** Android persists many on/off toggles (WiFi, Bluetooth, airplane mode, brightness mode) in a per-user settings database queryable via `settings get global <key>`. These are the source of truth for the system state — the status bar icons and quick-settings tile states are *derived* from these. The eval reads from the source of truth, so an agent must change the underlying setting (typically by toggling the WiFi/BT subsystem via UI or ADB), not just visually appear to.
- **Quick Settings panel.** The pull-down panel reachable by swiping from the top of the screen, containing tiles for WiFi, Bluetooth, brightness, etc. Tapping a tile usually toggles the underlying setting; tapping a tile's text label opens the corresponding Settings activity. Quick Settings tile state can lag the underlying system setting on the order of a few hundred ms.

## Root cause and category

**Proximate cause:** agent hallucination — R0 invented "I have already done this" + "Bluetooth icon is visible" and terminated without acting.

**Upstream environmental cause:** SystemUI residual state from the previous task (Clock overlay) made R0's first observation visually different from R1's. The model, sensitive to small input differences even at temperature=0, took the difference as evidence of a state it had not actually produced.

**Categories:** **Cat 1 (SystemUI residual state)** as the env contribution + **Cat 6 (agent error)** as the proximate cause. This is one of those flips where the env didn't *force* the failure but did supply the misleading visual context that triggered it.

**Verdict:** **env bug — should fix.** Even though the proximate cause is agent reasoning, the env-side fix (cleaning SystemUI before first observation) would have prevented this particular hallucination by removing the misleading visual cue. We can't fix the model from the harness side, but we can give it a clean canvas.

## Suggested fix

Same fix as [§02 ClockStopWatchRunning](02-clock-stopwatch-running.md): in [`task_eval.initialize_task`](../../MARS-Voyager/androidworld/android_world/task_evals/task_eval.py#L142), after `_initialize_apps`, run `adb shell cmd notification clear` and add a brief settle delay so SystemUI / launcher widgets repaint to a clean state before the first observation. This eliminates a whole class of "previous task's UI bleeds into next task's first frame" flakes regardless of which app posted the bleed.

A complementary mitigation: extend the system task setup to also explicitly close all non-target apps before the first observation, so any quick-settings or launcher widget that had been preempted by a prior task's notification is forced to re-render.
