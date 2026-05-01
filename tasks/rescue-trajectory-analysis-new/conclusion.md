# Conclusion

The 17 flips are not one bug. They cluster into three actionable env-hardening themes: clean global/SystemUI state, reset app-private state when snapshots are missing, and wait for UI/media surfaces to settle before the first observation. A smaller set are agent or serving failures that the Android harness can only mitigate indirectly.

## Categories

1. **Cat 1 — Init incompleteness, SystemUI / launcher residual state.** `clear_app_data` and snapshot restore touch app data, not notifications, launcher widgets, quick-settings surfaces, or stale overlays.
2. **Cat 2 — Init incompleteness, auxiliary tables and `shared_prefs`.** The task's primary files/tables are reset, but app prefs, last-opened-document state, sort/filter choices, or app DB rows survive.
3. **Cat 3 — Snapshot restore failure or absence.** `Skipping app snapshot loading` means the harness did not restore a canonical app state; without a fallback, prior state leaks.
4. **Cat 4 — A11y tree fetch failure.** `Could not get a11y tree` retries or empty/stale UI metadata degrade grounding and can consume timing budget.
5. **Cat 5 — Pixel-level / async UI fluctuation.** Same intended setup, but scroll physics, render timing, media thumbnails, or post-action screenshots differ.
6. **Cat 6 — Agent, serving, or harness-control failure.** The model hallucinates, loops, fails to terminate, or the LLM call itself errors. These are not Android state bugs, but some can be mitigated by harness policy.

## Task × Category matrix

Categories are not disjoint; a flip can involve both env state and agent fragility.

| Task | Cat 1 | Cat 2 | Cat 3 | Cat 4 | Cat 5 | Cat 6 |
|------|:-----:|:-----:|:-----:|:-----:|:-----:|:-----:|
| [01 TasksDueOnDate](01-tasks-due-on-date.md) | | x | | | x | |
| [02 ClockStopWatchRunning](02-clock-stopwatch-running.md) | x | | | | | |
| [03 TurnOffWifiAndTurnOnBluetooth](03-turn-off-wifi-bluetooth.md) | x | | | | | x |
| [04 SystemBluetoothTurnOn](04-system-bluetooth-turn-on.md) | x | | | | | x |
| [05 SystemBluetoothTurnOff](05-system-bluetooth-turn-off.md) | x | | | x | | x |
| [06 SystemWifiTurnOff](06-system-wifi-turn-off.md) | | | | x | x | x |
| [07 SystemBrightnessMax](07-system-brightness-max.md) | x | | | | | x |
| [08 SystemBrightnessMaxVerify](08-system-brightness-max-verify.md) | | | | | | x |
| [09 SimpleSmsResend](09-simple-sms-resend.md) | x | | | | | x |
| [10 OsmAndFavorite](10-osmand-favorite.md) | | | | | x | |
| [11 ContactsAddContact](11-contacts-add-contact.md) | x | | | | | x |
| [12 SimpleCalendarAddOneEvent](12-simple-calendar-add-event.md) | | | | | x | |
| [13 RetroPlayingQueue](13-retro-playing-queue.md) | | | | | x | x |
| [14 AudioRecorderRecordAudioWithFileName](14-audio-recorder-filename.md) | | x | x | | | |
| [15 MarkorCreateNoteFromClipboard](15-markor-create-from-clipboard.md) | | x | | | | x |
| [16 MarkorDeleteNote](16-markor-delete-note.md) | | x | | | | x |
| [17 MarkorTranscribeReceipt](17-markor-transcribe-receipt.md) | | | x | | x | x |

## Per-category recommendations

### Cat 1 — SystemUI / Launcher Residual State

**Why it matters:** Several first-frame failures were caused by stale notifications, Clock overlays, or quick-settings state that the target app setup never owned.

**Fix:** Add a pre-observation global cleanup step after app reset: dismiss notifications, close bubbles/overlays, return to launcher, wait briefly, and verify the foreground activity. Relevant init path: [`task_eval._initialize_apps`](../../MARS-Voyager/androidworld/android_world/task_evals/task_eval.py#L116) plus controller helpers around SystemUI cleanup.

### Cat 2 — Auxiliary App State

**Why it matters:** Clearing generated files is not enough when the app remembers last-opened screens, default file types, DB rows, or warnings in private app data.

**Fix:** For apps without a valid snapshot, fall back to `clear_app_data` before task-specific setup. Then explicitly seed prefs required by the task, such as Markor's desired file type or launch directory.

### Cat 3 — Snapshot Restore Failure / Absence

**Why it matters:** The log repeatedly shows `Skipping app snapshot loading`; that should not silently leave the task in an uncontrolled prior state.

**Fix:** Treat missing snapshots as a controlled branch, not a warning-only path. Either provide snapshots for all evaluated packages or call app-specific reset code and emit a structured setup status that can fail fast when canonical state cannot be guaranteed.

### Cat 4 — A11y Tree Fetch Failure

**Why it matters:** A11y retries are usually recoverable, but they change timing and can combine with tight budgets or stale observations.

**Fix:** Do not charge the agent a step for infrastructure-only observation failures. Cache the previous good screenshot separately from the current a11y tree and expose a clear "observation unavailable, retrying" path in the runner.

### Cat 5 — Pixel / Async UI Fluctuation

**Why it matters:** Many failures came from observing an app before it was idle: scrolling landed differently, search results were mid-render, or Gallery thumbnails had not populated.

**Fix:** Add app-idle waits after actions that launch apps, scroll large lists, or trigger async media/search UI. For Gallery tasks, force media scanning and thumbnail readiness before the agent sees the screen; for list tasks, prefer deterministic direct data queries or stable sorted views.

### Cat 6 — Agent / Serving / Harness-Control Failure

**Why it matters:** Some failures are not Android state bugs: the agent hallucinated, repeated dead actions, failed to terminate after success, or the LLM call errored.

**Fix:** Separate infra errors from task steps. Retry `Error calling LLM` on the same observation without consuming budget. For agent-control issues, consider auto-scoring at budget exhaustion when the evaluator already returns success, and add policy prompts/tools that encourage verifying action outcomes before repeating a coordinate tap.
