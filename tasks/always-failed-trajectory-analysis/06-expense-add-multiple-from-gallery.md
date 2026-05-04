# ExpenseAddMultipleFromGallery

## Quick links
- **Goal:** "Add the expenses from expenses.jpg in Simple Gallery Pro to pro expense."
- **History:** F/F/F/F/F
- **Step budget:** 38
- **Steps R0-R4:** 27/11/38/33/7
- **Termination:** agent-done
- **Determinism:** D3 unstable
- **Tags:** multi_app, screen_reading, data_entry, information_retrieval, parameterized
- **Evaluator:** [`ExpenseAddMultipleFromGallery class / inherited is_successful`](../../MARS-Voyager/androidworld/android_world/task_evals/single/expense.py#L362) - evaluator source link or inherited evaluator class.
- **Setup:** [`ExpenseAddMultipleFromGallery.initialize_task`](../../MARS-Voyager/androidworld/android_world/task_evals/single/expense.py#L378) - setup source link or inherited setup class.
- **Trajectory folder:** [formatted traces](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107_reformatted/ExpenseAddMultipleFromGallery)
- **Image folder:** [screenshots](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/ExpenseAddMultipleFromGallery/images)

## What success requires

The evaluator must observe the task-specific post-condition for: "Add the expenses from expenses.jpg in Simple Gallery Pro to pro expense.". The task template is: "Add the expenses from expenses.jpg in Simple Gallery Pro to pro expense.". In practical terms, the report should judge success by the source-linked evaluator rather than by the agent's self-report; a `terminate(success)` or `answer` action is only meaningful if the app state or returned answer matches that evaluator.

## Cross-round behavior

| Round | Steps | Terminal action | Wall-step action |
|---|---:|---|---|
| R0 | 27 | terminate {'action': 'terminate', 'status': 'success'} | The task is completed successfully. |
| R1 | 11 | terminate {'action': 'terminate', 'status': 'success'} | The task is completed successfully. |
| R2 | 38 | terminate {'action': 'terminate', 'status': 'success'} | Tap on the 'Political' expense entry to view its details and find the option to add it to the Pro Expense app. |
| R3 | 33 | terminate {'action': 'terminate', 'status': 'success'} | Scroll down to locate the file 'expenses.jpg'. |
| R4 | 7 | terminate {'action': 'terminate', 'status': 'success'} | The task is completed successfully. |

First divergent assistant step across available rounds: **step 1**. The wall step used for this file is **step 27** because it is the first durable point where the trace commits to the failure mode represented by `premature-success; compound-task; task-constraint-missed`.

## Wall step

### Round 0

![R0 step 27](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/ExpenseAddMultipleFromGallery/images/repeat00-step26-20260426205434-2t9Ft3uOJM.png)
*R0 step 27 - wall-step screenshot associated with the action below.*

Agent thought: "The goal was to add the expenses from 'expenses.jpg' to the Pro Expense app. The current screenshot shows that the file has been successfully added, as indicated by the list of expenses displayed on the screen. There is no further action required to complete the task."

Agent action: `The task is completed successfully.`

Tool call: `terminate {'action': 'terminate', 'status': 'success'}`

### Round 3

![R3 step 27](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/ExpenseAddMultipleFromGallery/images/repeat03-step26-20260427031021-2t9Ft3uOJM.png)
*R3 step 27 - comparison screenshot at the same wall-step index when available.*

Agent thought: "The goal is to add the file 'expenses.jpg' to the pro expense folder. The current screen shows the Simple Gallery Pro app with the search bar active, indicating that I need to locate the file first. Since it's not visible in the current view, I should scroll down to find it."

Agent action: `Scroll down to locate the file 'expenses.jpg'.`

Tool call: `swipe {'action': 'swipe', 'coordinate': [499, 706], 'coordinate2': [491, 206]}`

## What actually happened

The final action is `agent-done`, so the run ends before the trace shows a verified evaluator post-condition. The R0 wall-step action is `The task is completed successfully.`. The representative comparison round records `Scroll down to locate the file 'expenses.jpg'.` at the same step index, while the final available round ends with `The task is completed successfully.`. This is enough to identify the repeated failure mechanism, but any claim about fine-grained UI state should be checked against the embedded screenshots and the raw image directory.

## Root cause and category

Categories: `premature-success`: the agent declares success or answers before observing the evaluator-relevant post-condition; `compound-task`: the task has multiple sequential legs or repeated item operations, and the trace completes only part of the required workflow; `task-constraint-missed`: the agent misses a stated constraint such as all items, ordering, filtering, exact duplicate handling, date range, or recipient/content matching.

Verdict: **retry sometimes explores variants but all fail**. The proximate failure is `premature-success; compound-task; task-constraint-missed`; the upstream issue is that the policy lacks the reliable procedure needed for this class of task before it exhausts the budget or finalizes prematurely.

## Suggested fix

Require a verification observation immediately before `terminate(success)` or `answer`, tied to the evaluator post-condition. Add a lightweight checklist/planning scaffold for multi-leg tasks and repeated item loops so completion is tracked before termination.
