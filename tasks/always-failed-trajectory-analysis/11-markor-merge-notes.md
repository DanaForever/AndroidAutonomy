# MarkorMergeNotes

## Quick links
- **Goal:** "Merge the contents of Markor notes active_mouse_copy.md, backup_neat_nest.txt and bKCr_silly_umbrella.md (in the same order) into a new Markor note named CFR0t5ao and save it. Add a new line between the content of each note."
- **History:** F/F/F/F/F
- **Step budget:** 78
- **Steps R0-R4:** 78/20/47/78/78
- **Termination:** max-steps
- **Determinism:** D3 unstable
- **Tags:** data_edit, data_entry, parameterized
- **Evaluator:** [`MarkorMergeNotes.is_successful`](../../MARS-Voyager/androidworld/android_world/task_evals/single/markor.py#L603) - evaluator source link or inherited evaluator class.
- **Setup:** [`MarkorMergeNotes.initialize_task`](../../MARS-Voyager/androidworld/android_world/task_evals/single/markor.py#L562) - setup source link or inherited setup class.
- **Trajectory folder:** [formatted traces](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107_reformatted/MarkorMergeNotes)
- **Image folder:** [screenshots](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/MarkorMergeNotes/images)

## What success requires

The evaluator must observe the task-specific post-condition for: "Merge the contents of Markor notes active_mouse_copy.md, backup_neat_nest.txt and bKCr_silly_umbrella.md (in the same order) into a new Markor note named CFR0t5ao and save it. Add a new line between the content of each note.". The task template is: "Merge the contents of Markor notes {file1_name}, {file2_name} and {file3_name} (in the same order) into a new Markor note named {new_file_name} and save it. Add a new line between the content of each note.". In practical terms, the report should judge success by the source-linked evaluator rather than by the agent's self-report; a `terminate(success)` or `answer` action is only meaningful if the app state or returned answer matches that evaluator.

## Cross-round behavior

| Round | Steps | Terminal action | Wall-step action |
|---|---:|---|---|
| R0 | 78 | type {'action': 'type', 'text': 'The content of the file'} | Tap on the Markor app icon to open the application. |
| R1 | 20 | terminate {'action': 'terminate', 'status': 'success'} | Tap on the Markor app icon to open the application. |
| R2 | 47 | terminate {'action': 'terminate', 'status': 'success'} | Tap on the Markor app icon to open the application. |
| R3 | 78 |  | Tap on the Markor app icon to open the application. |
| R4 | 78 | swipe {'action': 'swipe', 'coordinate': [499, 817], 'coordinate2': [491, 292]} | Swipe up on the screen to scroll through the app drawer and locate the Markor app. |

First divergent assistant step across available rounds: **step 2**. The wall step used for this file is **step 2** because it is the first durable point where the trace commits to the failure mode represented by `compound-task; task-constraint-missed`.

## Wall step

### Round 0

![R0 step 2](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/MarkorMergeNotes/images/repeat00-step1-20260426212540-ldei9fN1FY.png)
*R0 step 2 - wall-step screenshot associated with the action below.*

Agent thought: "To achieve the goal of merging specific notes in Markor, I need to first open the Markor app. The icon for Markor is visible on the screen, so my next step should be to tap on it to launch the application."

Agent action: `Tap on the Markor app icon to open the application.`

Tool call: `click {'action': 'click', 'coordinate': [608, 867]}`

### Round 4

![R4 step 2](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/MarkorMergeNotes/images/repeat04-step1-20260427042321-ldei9fN1FY.png)
*R4 step 2 - comparison screenshot at the same wall-step index when available.*

Agent thought: "I need to open the Markor app to proceed with merging the notes. The app icon is not visible on the screen, so I should look for it in the app drawer or swipe up to access more apps."

Agent action: `Swipe up on the screen to scroll through the app drawer and locate the Markor app.`

Tool call: `swipe {'action': 'swipe', 'coordinate': [499, 742], 'coordinate2': [491, 320]}`

## What actually happened

The trace spends its budget on only part of a multi-leg or repeated-item workflow, leaving later constraints unresolved. The R0 wall-step action is `Tap on the Markor app icon to open the application.`. The representative comparison round records `Swipe up on the screen to scroll through the app drawer and locate the Markor app.` at the same step index, while the final available round ends with `Swipe up on the screen to scroll down and locate the notes that need to be merged.`. This is enough to identify the repeated failure mechanism, but any claim about fine-grained UI state should be checked against the embedded screenshots and the raw image directory.

## Root cause and category

Categories: `compound-task`: the task has multiple sequential legs or repeated item operations, and the trace completes only part of the required workflow; `task-constraint-missed`: the agent misses a stated constraint such as all items, ordering, filtering, exact duplicate handling, date range, or recipient/content matching.

Verdict: **retry sometimes explores variants but all fail**. The proximate failure is `compound-task; task-constraint-missed`; the upstream issue is that the policy lacks the reliable procedure needed for this class of task before it exhausts the budget or finalizes prematurely.

## Suggested fix

Add a lightweight checklist/planning scaffold for multi-leg tasks and repeated item loops so completion is tracked before termination. Make the agent restate and check every explicit constraint before finalizing.
