# Rescue Trajectory Analysis (Run `20260426203107`)

## Why this report exists

In eval run `20260426203107`, 17 tasks failed in round 0 and succeeded in a later retry round. Since the model is run with `temperature=0` and the task seeds are fixed, **any divergence between rounds implies an environmental difference** unless the serving stack itself is nondeterministic. This report goes screen-by-screen, source-link-by-source-link through each flip to identify what differed and whether it represents an env bug we should fix before treating eval scores as reliable.

## How to read this report

Each task file contains quick links, the evaluator's success condition, FAIL/PASS screenshots at the divergence point, the chronological explanation, Android concepts, a root-cause category, and a concrete fix suggestion. Function names in prose are in `backticks`, and first references link to source. Screenshots are embedded with paths relative to this folder so they render in VSCode preview.

Verdicts are intentionally direct:

- **env bug — should fix:** the harness presented materially different state that should be made deterministic.
- **mostly agent-side — env mitigation worth doing:** the agent made the proximate mistake, but env cleanup would reduce the trap.
- **infra bug — should fix outside Android harness:** non-Android serving or tooling failure.

Category definitions and recommendations are in [`conclusion.md`](conclusion.md).

## Executive summary

| # | Task | Rescued | Category(ies) | Verdict | File |
|--:|------|:------:|---------------|---------|------|
| 01 | TasksDueOnDate | R3 | Cat 5 primary; Cat 2 possible | env bug — should fix | [01](01-tasks-due-on-date.md) |
| 02 | ClockStopWatchRunning | R1 | Cat 1 | env bug — should fix | [02](02-clock-stopwatch-running.md) |
| 03 | TurnOffWifiAndTurnOnBluetooth | R1 | Cat 1 + Cat 6 | env bug — should fix | [03](03-turn-off-wifi-bluetooth.md) |
| 04 | SystemBluetoothTurnOn | R2 | Cat 1 + Cat 6 | env bug — should fix; evaluator caveat | [04](04-system-bluetooth-turn-on.md) |
| 05 | SystemBluetoothTurnOff | R1 | Cat 1 + Cat 4 + Cat 6 | mostly agent error — env mitigation worth doing | [05](05-system-bluetooth-turn-off.md) |
| 06 | SystemWifiTurnOff | R1 | Cat 5 + Cat 4 + Cat 6 | env bug — should fix | [06](06-system-wifi-turn-off.md) |
| 07 | SystemBrightnessMax | R2 | Cat 1 + Cat 6 | env bug — should fix | [07](07-system-brightness-max.md) |
| 08 | SystemBrightnessMaxVerify | R1 | Cat 6 | infra bug — fix serving/LLM retry handling | [08](08-system-brightness-max-verify.md) |
| 09 | SimpleSmsResend | R1 | Cat 1 + Cat 6 | env bug — should fix | [09](09-simple-sms-resend.md) |
| 10 | OsmAndFavorite | R1 | Cat 5 | env bug — should fix | [10](10-osmand-favorite.md) |
| 11 | ContactsAddContact | R1 | Cat 1 + Cat 6 | env bug — should fix | [11](11-contacts-add-contact.md) |
| 12 | SimpleCalendarAddOneEvent | R1 | Cat 5 | env bug — should fix | [12](12-simple-calendar-add-event.md) |
| 13 | RetroPlayingQueue | R1 | Cat 5 + Cat 6 | mostly agent-side — env mitigation marginal | [13](13-retro-playing-queue.md) |
| 14 | AudioRecorderRecordAudioWithFileName | R1 | Cat 2 + Cat 3 | env bug — should fix | [14](14-audio-recorder-filename.md) |
| 15 | MarkorCreateNoteFromClipboard | R1 | Cat 2 + Cat 6 | env bug — should fix | [15](15-markor-create-from-clipboard.md) |
| 16 | MarkorDeleteNote | R2 | Cat 2 + Cat 6 | mostly agent-side — env mitigation worth doing | [16](16-markor-delete-note.md) |
| 17 | MarkorTranscribeReceipt | R2 | Cat 5 + Cat 3 + Cat 6 | env bug — should fix | [17](17-markor-transcribe-receipt.md) |

## Glossary of Android concepts

- **Foreground activity** — the Android screen currently receiving user input; see [§02](02-clock-stopwatch-running.md#android-concepts-introduced).
- **Accessibility tree (a11y tree)** — structured UI metadata exposed to automation; see [§02](02-clock-stopwatch-running.md#android-concepts-introduced).
- **`pm clear` vs force-stop** — clearing app data differs from stopping a running process or clearing SystemUI state; see [§02](02-clock-stopwatch-running.md#android-concepts-introduced).
- **At-a-Glance widget / SystemUI residual state** — launcher or notification surfaces can persist after app data resets; see [§02](02-clock-stopwatch-running.md#android-concepts-introduced).
- **Quick-settings tile state** — Wi-Fi/Bluetooth tiles are SystemUI-controlled and can lag or vary across gestures; see [§03](03-turn-off-wifi-bluetooth.md#android-concepts-introduced).
- **Gesture non-determinism** — the same swipe can land differently when animation/physics timing differs; see [§06](06-system-wifi-turn-off.md#android-concepts-introduced).
- **Async render timing** — screenshot capture before an app has settled can show a mid-load state; see [§10](10-osmand-favorite.md#android-concepts-introduced).
- **Stale DB vs disk files** — app database rows can survive while referenced files are gone; see [§14](14-audio-recorder-filename.md#android-concepts-introduced).
- **Material dropdown menu interaction** — dropdowns need an open-then-select sequence and can fail under coordinate-only tapping; see [§15](15-markor-create-from-clipboard.md#android-concepts-introduced).
- **Last-opened document state** — editors can reopen stale files from app prefs even when task files were regenerated; see [§16](16-markor-delete-note.md#android-concepts-introduced).
- **Media scanner / thumbnail cache** — gallery apps depend on Android media indexing and cached thumbnails; see [§17](17-markor-transcribe-receipt.md#android-concepts-introduced).
