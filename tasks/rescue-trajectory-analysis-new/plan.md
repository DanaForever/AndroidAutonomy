# Plan — Re-investigate the 17 Result-Flip Tasks

## Context

In the eval run `20260426203107`, 17 tasks failed in round 0 and succeeded in a later retry round. **Since `temperature=0` and the task seeds are fixed, any divergence between rounds implies an environmental difference** — the model itself is deterministic given identical observations, so a result flip is direct evidence that the env presented something different across rounds.

This re-investigation goes round-by-round, screen-by-screen for each of the 17 tasks to identify exactly what differed and why. The end deliverable is a categorized list of root causes with concrete fix suggestions, suitable for the team to act on when hardening the eval harness.

Goal: produce a **trustworthy, image-grounded, source-linked** report that lets a reader (new to Android dev) understand exactly why each flip happened and whether each is an environment bug that should be fixed before the eval can be considered reliable.

## Output Layout

Everything lives under `tasks/rescue-trajectory-analysis-new/` (this folder).

```
tasks/rescue-trajectory-analysis-new/
├── plan.md                           # this file
├── index.md                          # overview + exec summary table + glossary
├── conclusion.md                     # categorization + per-category recommendations
├── 01-tasks-due-on-date.md
├── 02-clock-stopwatch-running.md     # SAMPLE — drafted FIRST for style approval
├── 03-turn-off-wifi-bluetooth.md
├── 04-system-bluetooth-turn-on.md
├── 05-system-bluetooth-turn-off.md
├── 06-system-wifi-turn-off.md
├── 07-system-brightness-max.md
├── 08-system-brightness-max-verify.md
├── 09-simple-sms-resend.md
├── 10-osmand-favorite.md
├── 11-contacts-add-contact.md
├── 12-simple-calendar-add-event.md
├── 13-retro-playing-queue.md
├── 14-audio-recorder-filename.md
├── 15-markor-create-from-clipboard.md
├── 16-markor-delete-note.md
└── 17-markor-transcribe-receipt.md
```

## Per-Task File Template

Every task file follows this exact structure so the report is uniform and scannable:

```markdown
# <Task name>

## Quick links
- **Goal:** "<exact goal text from log>"
- **History:** F → ... → S (rescued at R<n>)
- **Step budget:** <n>
- **Evaluator:** [`<ClassName>.is_successful`](<link to file:line>) — what it checks (1 sentence)
- **Setup:** [`<ClassName>.initialize_task`](<link to file:line>) — what it does (1 sentence)
- **Trajectory folder:** [link to formatted `.txt` folder](<relative path>)
- **Image folder:** [link to `images/` folder](<relative path>)

## What "success" requires (evaluator)
2-4 sentence plain-English explanation of the pass criterion, with code link. Includes a minimal code snippet only if it clarifies (e.g. "needs both `Pause` and `Lap` buttons present in DeskClock activity").

## What the agent saw at the divergence step

### Round 0 (FAIL)
![R0 step N](<relative path to png>)
*R0 step N — one-line caption*

Agent's thought (verbatim, trimmed): "..."
Agent's action: `<action>`

### Round <rescue> (PASS)
![R<rescue> step N](<relative path to png>)
*R<rescue> step N — one-line caption*

Agent's thought (verbatim): "..."
Agent's action: `<action>`

## What actually happened
4-8 sentences. Tells the story chronologically. Cites the screenshot evidence ("the home screen shows a small overlay reading '00:05 Paused' at the top-left, not the Clock app foreground"). Quotes log lines (e.g. `Skipping app snapshot loading`) when they are present in the worker log around this task's timestamp. Names specific functions involved as inline links.

## Android concept(s) introduced (if any)
Brief explanations (≤3 sentences each) of any Android primitive a non-Android-dev needs to follow the analysis. Examples used across the report: AccessibilityService / a11y tree, SharedPreferences, AppWidget, At-a-Glance widget, force-stop vs clear_app_data, NotificationListener, Bubbles, foreground activity. Each concept is defined the FIRST time it appears in the report and thereafter referred to by name with an italic note like *(see Bubbles, §02)*.

## Root cause and category
One short paragraph naming the proximate cause and the upstream environmental cause. Tags one of the categories defined in `conclusion.md`. Explicit verdict: **"env bug — should fix"** / **"agent error — out of scope"** / **"acceptable variance — no fix needed"**.

## Suggested fix (if env bug)
Concrete and minimal. Either a 1-3 sentence change description with the file path (e.g. "after `clear_app_data` in [`_close_clock_app`](...), add a 500ms wait then `cmd notification clear_all` to drop the SystemUI bubble before observation") or "no fix needed because <reason>".
```

## Image-Embedding Rules

- **Relative paths** from each task .md file: `../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/<TaskName>/images/<file>.png`. Verified to render in VSCode markdown preview.
- **Embed only**: (a) the divergence-step screenshot from the FAIL round, (b) the divergence-step screenshot from the PASS round, (c) up to 2 supporting screenshots when a follow-on step is essential to the explanation (e.g. step 1 of `MarkorDeleteNote` R0 where the trash misclick at y=6 is the actual failure point).
- Side-by-side comparison: 2-column markdown table with images in cells when comparing FAIL vs PASS at the same step index.
- Caption every embedded image with `*R<n> step <i> — <one-line description>*` immediately below.

## Source-Linking Rules

- Every mentioned function gets an inline link on first reference per file: `` [`func_name`](relative-path-to-source.py#L<line>) ``.
- Use **relative paths from the task .md file** to the source: e.g. `../../MARS-Voyager/androidworld/android_world/task_evals/single/clock.py#L25`.
- Each task file links to **its evaluator's `is_successful`** and **its `initialize_task`** at the top (Quick links section).
- Function names referenced in prose (not links) use backticks.

## Hard Rule — No Claim Without Pixel Evidence

Since `temperature=0` and seeds are fixed, every result flip points to an env difference visible somewhere in the screenshots. Identifying it requires actually looking at the pixels:

- **Every claim about what is on screen** must be backed by the analyst (me) having actually opened the PNG via the Read tool — which renders it visually in context, exactly as I did in this session for `ClockStopWatchRunning` (where I could see the "00:05 Paused" overlay in R0 and the "Sun, Oct 15" date widget in R1 occupying the same screen position).
- The task file must **embed** the screenshot for any claim it makes about UI state. If a claim is made and no screenshot is shown, that's a bug in the report.
- If a screenshot is ambiguous or doesn't actually support the claim, the task file must say so explicitly ("the screenshot does not unambiguously show X; the conclusion is therefore tentative") rather than papering over it.
- Action coordinates from the JSONL are NOT a substitute for looking at the screenshot. Coordinates only tell us where the agent tapped, not what was at that location.

## Investigation Workflow Per Task

For each task:

1. **Read both/all rounds of the formatted trajectory** in `eval_results/UI-Voyager/results/20260426203107_reformatted/<TaskName>/` — human-readable form of the JSONL.
2. **Identify the divergence step** by walking step indices and finding the first index where the assistant's thought OR action differs. (Recall the framing: `temperature=0` + fixed seeds ⇒ any divergence is environmental.)
3. **Open both screenshots at the divergence step** (and any earlier step that determined the divergence) using the Read tool — actually look at pixels, not just the action coordinates.
4. **Read the evaluator** at [`MARS-Voyager/androidworld/android_world/task_evals/...`](../../MARS-Voyager/androidworld/android_world/task_evals/) to confirm what success requires.
5. **Read the task's `initialize_task`** and any per-app setup utility (e.g. `task_app_utils.setup_task_state`) to know what state is supposed to be guaranteed at round start.
6. **Grep the worker log** `eval_results/UI-Voyager/logs/20260426203107/eval_UI-Voyager_1workers.log` for the task's `task_id` and surrounding window — confirm/refute presence of `Skipping app snapshot loading`, `Could not get a11y tree`, exception traces. Every log-event citation in the task file must be backed by an actual line found here.
7. **Write the task file** following the template. If the cause is unclear after these steps, say so explicitly rather than speculate.

## Sample-Task Workflow (do FIRST, get approval BEFORE remaining 16)

Pick `ClockStopWatchRunning` as the sample because:
- Trajectories are very short (2 steps fail, 5 steps pass) — small surface area.
- Evaluator and setup code already analyzed in this session — no fresh investigation overhead, so the focus is on **format**.
- Touches multiple Android concepts (AccessibilityService, AppWidget vs At-a-Glance, force-stop vs clear_app_data, NotificationListener) — exercises the "Android concept" formatting block well.

Steps:
1. Write `02-clock-stopwatch-running.md` only.
2. Also write a **stub** `index.md` and `conclusion.md` so the linking style across files is visible.
3. Stop and request review. Iterate on style/length/depth based on feedback.
4. Only after approval, proceed to remaining 16 tasks.

## Index File Structure (`index.md`)

- 1-paragraph context: states the `temperature=0` + fixed-seeds framing — any flip implies an env difference — as the motivation for going screenshot-by-screenshot through 17 cases.
- "How to read this report" — explains the per-task template, image conventions, link conventions, category tags.
- Executive summary table: 17 rows, columns = `Task | Rescued at | Category(ies) | Verdict (fix/no-fix) | Link to file`.
- Glossary of Android concepts (collected from the per-task files), each with one-line definition and a link to the first task file where it is explained in detail.

## Conclusion File Structure (`conclusion.md`)

Categories (initial hypothesis based on prior session work — to be refined as analysis proceeds):

1. **Init incompleteness — SystemUI / launcher residual state.** `clear_app_data` and `restore_snapshot` only touch the app's own `/data/data/<pkg>` tree. Notifications, At-a-Glance widget, AppWidget RemoteViews, Bubbles, and quick-settings tile state survive into the next round.
2. **Init incompleteness — auxiliary tables and `shared_prefs`.** `clear_task_db` etc. only wipe the primary table; sort/filter/last-view state in shared_prefs persists across rounds and changes UI layout.
3. **Snapshot restore failure (transient ADB / gRPC).** `Skipping app snapshot loading` events that genuinely change app DB content because the snapshot was never applied.
4. **A11y tree fetch failure.** `Could not get a11y tree` events that produced empty observations or stale trees, derailing the agent.
5. **Pixel-level UI fluctuation.** Same DB, same prefs — but layout/scroll/widget render differs by a few pixels and the agent's coordinate-based action lands differently. Probably the largest "no fix needed" bucket.
6. **Pure agent error / non-determinism beyond env.** Cases where rounds ran on identical observations but the model still flipped (would suggest non-determinism in the model serving — should be rare given temperature=0).

**Categories are not necessarily disjoint** — one flip can plausibly involve, e.g., both SystemUI residual state (cat 1) and pixel-level layout drift (cat 5). To handle this cleanly, `conclusion.md` will use a **task × category matrix** instead of per-category task lists:

```
| Task                          | Cat 1 | Cat 2 | Cat 3 | Cat 4 | Cat 5 | Cat 6 |
|-------------------------------|:-----:|:-----:|:-----:|:-----:|:-----:|:-----:|
| TasksDueOnDate                |       |   x   |       |       |   x   |       |
| ClockStopWatchRunning         |   x   |       |       |       |       |       |
| ...                           |       |       |       |       |       |       |
```

Each row's task name links to its task file; each column header links to the category definition below. Below the matrix, each category gets:

- Definition (1-2 sentences).
- Why it matters for eval reliability (1-2 sentences).
- Suggested fix or mitigation (concrete: file paths to change, or "test infrastructure change", or "accept and document").

## Verification

The report is a documentation artifact, not code, so verification is human review:

1. **Style sanity (after sample task):** open `02-clock-stopwatch-running.md` in VSCode preview. Confirm: images render, all source links navigate to the correct file:line, Android concepts are explained intuitively, the verdict line is unambiguous.
2. **Per-task check (during analysis):** for each task, the analyst (me) cross-checks claims against (a) raw `.jsonl`, (b) screenshots, (c) source code at the cited line — no claim should be left ungrounded.
3. **Final pass (after all 17):** read `index.md` end-to-end. Confirm executive table verdicts match the per-task verdicts. Confirm every category in `conclusion.md` has at least one task in its column and every task row in the matrix has at least one mark.
4. **Optional spot-check by user:** pick any 2 task files at random and verify against the source data; if either is wrong, re-audit the rest.

## Critical Files (read-only references)

- Trajectories (formatted): `MARS-Voyager/eval_results/UI-Voyager/results/20260426203107_reformatted/<TaskName>/repeat_*.txt`
- Trajectories (raw): `MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/<TaskName>/repeat_*.jsonl`
- Screenshots: `MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/<TaskName>/images/`
- Worker log: `MARS-Voyager/eval_results/UI-Voyager/logs/20260426203107/eval_UI-Voyager_1workers.log`
- Per-task summaries: `MARS-Voyager/eval_results/UI-Voyager/logs/20260426203107/parallel_summary_repeat_*.json`
- Retry summary: `MARS-Voyager/eval_results/UI-Voyager/logs/20260426203107/retry_summary.json`
- Evaluators: `MARS-Voyager/androidworld/android_world/task_evals/single/*.py`, `MARS-Voyager/androidworld/android_world/task_evals/information_retrieval/*.py`, `MARS-Voyager/androidworld/android_world/task_evals/composite/*.py`
- Init machinery: [`task_eval._initialize_apps`](../../MARS-Voyager/androidworld/android_world/task_evals/task_eval.py#L116), [`app_snapshot.restore_snapshot`](../../MARS-Voyager/androidworld/android_world/utils/app_snapshot.py#L81), [`get_a11y_tree`](../../MARS-Voyager/androidworld/android_world/env/android_world_controller.py#L60).

## Out of Scope

- No source code changes. Fix suggestions in `conclusion.md` are recommendations only.
- No re-running of the eval. Analysis is purely on the existing artifacts of run `20260426203107`.
- Other rescue rounds (run timestamps other than `20260426203107`) — out of scope unless cross-run comparison is needed to confirm a hypothesis.
