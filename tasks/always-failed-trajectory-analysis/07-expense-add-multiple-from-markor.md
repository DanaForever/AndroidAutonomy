# ExpenseAddMultipleFromMarkor

## Quick links
- **Goal:** "Go through the transactions in my_expenses.txt in Markor. Log the reimbursable transactions in the pro expense."
- **History:** F/F/F/F/F
- **Step budget:** 60
- **Steps R0-R4:** 60/9/48/60/2
- **Termination:** agent-done
- **Determinism:** D3 unstable
- **Tags:** transcription, repetition, multi_app, data_entry, memorization, parameterized
- **Evaluator:** [`ExpenseAddMultipleFromMarkor class / inherited is_successful`](../../MARS-Voyager/androidworld/android_world/task_evals/single/expense.py#L328) - evaluator source link or inherited evaluator class.
- **Setup:** [`ExpenseAddMultipleFromMarkor.initialize_task`](../../MARS-Voyager/androidworld/android_world/task_evals/single/expense.py#L342) - setup source link or inherited setup class.
- **Trajectory folder:** [formatted traces](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107_reformatted/ExpenseAddMultipleFromMarkor)
- **Image folder:** [screenshots](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/ExpenseAddMultipleFromMarkor/images)

## What success requires

The evaluator must observe the task-specific post-condition for: "Go through the transactions in my_expenses.txt in Markor. Log the reimbursable transactions in the pro expense.". The task template is: "Go through the transactions in my_expenses.txt in Markor. Log the reimbursable transactions in the arduia pro expense.". In practical terms, the report should judge success by the source-linked evaluator rather than by the agent's self-report; a `terminate(success)` or `answer` action is only meaningful if the app state or returned answer matches that evaluator.

## Cross-round behavior

| Round | Steps | Terminal action | Wall-step action |
|---|---:|---|---|
| R0 | 60 | click {'action': 'click', 'coordinate': [123, 578]} | Swipe up or access the app drawer to locate and open the Markor app. |
| R1 | 9 | answer {'action': 'answer', 'text': "The first transaction, 'New Jacket,' is marked as 'Reimburseable.'"} | Swipe up from the bottom of the screen to open the app drawer and locate the Markor app. |
| R2 | 48 | terminate {'action': 'terminate', 'status': 'success'} | Swipe up from the bottom of the screen to open the app drawer and locate the Markor app. |
| R3 | 60 | click {'action': 'click', 'coordinate': [499, 662]} | Swipe up from the bottom of the screen to open the app drawer and locate the Markor app. |
| R4 | 2 | terminate {'action': 'terminate', 'status': 'success'} | I tapped on the menu icon to access the option for opening the file. |

First divergent assistant step across available rounds: **step 1**. The wall step used for this file is **step 1** because it is the first durable point where the trace commits to the failure mode represented by `premature-success; compound-task; task-constraint-missed`.

## Wall step

### Round 0

![R0 step 1](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/ExpenseAddMultipleFromMarkor/images/repeat00-step0-20260426205445-Rh3pesjLE8.png)
*R0 step 1 - wall-step screenshot associated with the action below.*

Agent thought: "I need to Markor to find the transactions in my_expenses.txt and log the reimbursable ones. Since I'm currently on the home screen, my first step should be to locate and open the Markor app. It might be in the app drawer or on another home screen page."

Agent action: `Swipe up or access the app drawer to locate and open the Markor app.`

Tool call: `swipe {'action': 'swipe', 'coordinate': [499, 738], 'coordinate2': [493, 320]}`

### Round 4

![R4 step 1](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/ExpenseAddMultipleFromMarkor/images/repeat04-step0-20260427041804-Rh3pesjLE8.png)
*R4 step 1 - comparison screenshot at the same wall-step index when available.*

Agent thought: "I need to access the file "my_expenses.txt" in Markor to review the transactions and identify which ones are reimbursable. Since I'm currently in the app, I should navigate to the section where I can open the file."

Agent action: `I tapped on the menu icon to access the option for opening the file.`

Tool call: `click {'action': 'click', 'coordinate': [170, 69]}`

## What actually happened

The final action is `agent-done`, so the run ends before the trace shows a verified evaluator post-condition. The R0 wall-step action is `Swipe up or access the app drawer to locate and open the Markor app.`. The representative comparison round records `I tapped on the menu icon to access the option for opening the file.` at the same step index, while the final available round ends with `I reviewed the transactions in \"my_expenses.txt\" to identify and log the reimbursable ones.`. This is enough to identify the repeated failure mechanism, but any claim about fine-grained UI state should be checked against the embedded screenshots and the raw image directory.

## Root cause and category

Categories: `premature-success`: the agent declares success or answers before observing the evaluator-relevant post-condition; `compound-task`: the task has multiple sequential legs or repeated item operations, and the trace completes only part of the required workflow; `task-constraint-missed`: the agent misses a stated constraint such as all items, ordering, filtering, exact duplicate handling, date range, or recipient/content matching.

Verdict: **retry sometimes explores variants but all fail**. The proximate failure is `premature-success; compound-task; task-constraint-missed`; the upstream issue is that the policy lacks the reliable procedure needed for this class of task before it exhausts the budget or finalizes prematurely.

## Suggested fix

Require a verification observation immediately before `terminate(success)` or `answer`, tied to the evaluator post-condition. Add a lightweight checklist/planning scaffold for multi-leg tasks and repeated item loops so completion is tracked before termination.
