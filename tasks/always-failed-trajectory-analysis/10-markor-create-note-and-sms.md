# MarkorCreateNoteAndSms

## Quick links
- **Goal:** "Create a new note in Markor named glad_eagle_2023_05_21.txt with the following text: Better late than never.. Share the entire content of the note with the phone number +13660435839 via SMS using Simple SMS Messenger"
- **History:** F/F/F/F/F
- **Step budget:** 18
- **Steps R0-R4:** 18/18/18/18/18
- **Termination:** max-steps
- **Determinism:** D3 unstable
- **Tags:** multi_app, data_entry, parameterized
- **Evaluator:** [`MarkorCreateNoteAndSms.is_successful`](../../MARS-Voyager/androidworld/android_world/task_evals/composite/markor_sms.py#L60) - evaluator source link or inherited evaluator class.
- **Setup:** [`MarkorCreateNoteAndSms.initialize_task`](../../MARS-Voyager/androidworld/android_world/task_evals/composite/markor_sms.py#L45) - setup source link or inherited setup class.
- **Trajectory folder:** [formatted traces](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107_reformatted/MarkorCreateNoteAndSms)
- **Image folder:** [screenshots](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/MarkorCreateNoteAndSms/images)

## What success requires

The evaluator must observe the task-specific post-condition for: "Create a new note in Markor named glad_eagle_2023_05_21.txt with the following text: Better late than never.. Share the entire content of the note with the phone number +13660435839 via SMS using Simple SMS Messenger". The task template is: "Create a new note in Markor named {file_name} with the following text: {text}. Share the entire content of the note with the phone number {number} via SMS using Simple SMS Messenger". In practical terms, the report should judge success by the source-linked evaluator rather than by the agent's self-report; a `terminate(success)` or `answer` action is only meaningful if the app state or returned answer matches that evaluator.

## Cross-round behavior

| Round | Steps | Terminal action | Wall-step action |
|---|---:|---|---|
| R0 | 18 | click {'action': 'click', 'coordinate': [841, 306]} | Swipe up from the bottom of the screen to access the app drawer. |
| R1 | 18 | swipe {'action': 'swipe', 'coordinate': [499, 817], 'coordinate2': [491, 320]} | Swipe up from the bottom of the screen to access the app drawer. |
| R2 | 18 | click {'action': 'click', 'coordinate': [841, 306]} | Swipe up from the bottom of the screen to access the app drawer. |
| R3 | 18 | swipe {'action': 'swipe', 'coordinate': [499, 783], 'coordinate2': [491, 328]} | Swipe up from the bottom of the screen to access the app drawer. |
| R4 | 18 | swipe {'action': 'swipe', 'coordinate': [499, 817], 'coordinate2': [491, 320]} | Swipe up from the bottom of the screen to access the app drawer. |

First divergent assistant step across available rounds: **step 1**. The wall step used for this file is **step 1** because it is the first durable point where the trace commits to the failure mode represented by `app-not-found; compound-task; task-constraint-missed`.

## Wall step

### Round 0

![R0 step 1](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/MarkorCreateNoteAndSms/images/repeat00-step0-20260426211748-LgV8KrFxx7.png)
*R0 step 1 - wall-step screenshot associated with the action below.*

Agent thought: "I need to create a new note in Markor, but it is not visible on the home screen. I should access the app drawer or search for the Markor app to open it."

Agent action: `Swipe up from the bottom of the screen to access the app drawer.`

Tool call: `swipe {'action': 'swipe', 'coordinate': [499, 742], 'coordinate2': [491, 320]}`

### Round 4

![R4 step 1](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/MarkorCreateNoteAndSms/images/repeat04-step0-20260427042122-LgV8KrFxx7.png)
*R4 step 1 - comparison screenshot at the same wall-step index when available.*

Agent thought: "I need to create a new note in Markor, but it is not visible on the current screen. I should look for the Markor app icon or access the app drawer to open the app."

Agent action: `Swipe up from the bottom of the screen to access the app drawer.`

Tool call: `swipe {'action': 'swipe', 'coordinate': [499, 742], 'coordinate2': [491, 320]}`

## What actually happened

The trajectory repeatedly tries to locate the target app and exhausts the available budget (18/18/18/18/18) before reaching the evaluator-relevant screen. The R0 wall-step action is `Swipe up from the bottom of the screen to access the app drawer.`. The representative comparison round records `Swipe up from the bottom of the screen to access the app drawer.` at the same step index, while the final available round ends with `Swipe up on the screen to scroll down and reveal more apps in the app drawer.`. This is enough to identify the repeated failure mechanism, but any claim about fine-grained UI state should be checked against the embedded screenshots and the raw image directory.

## Root cause and category

Categories: `app-not-found`: the agent moves into launcher/app-drawer search behavior and spends the budget swiping or looking for the target app instead of using a reliable app search/open strategy; `compound-task`: the task has multiple sequential legs or repeated item operations, and the trace completes only part of the required workflow; `task-constraint-missed`: the agent misses a stated constraint such as all items, ordering, filtering, exact duplicate handling, date range, or recipient/content matching.

Verdict: **retry sometimes explores variants but all fail**. The proximate failure is `app-not-found; compound-task; task-constraint-missed`; the upstream issue is that the policy lacks the reliable procedure needed for this class of task before it exhausts the budget or finalizes prematurely.

## Suggested fix

Teach the agent to use launcher search or an explicit app-open primitive after one failed visual scan instead of repeated drawer swipes. Add a lightweight checklist/planning scaffold for multi-leg tasks and repeated item loops so completion is tracked before termination.
