# BrowserDraw

## Quick links
- **Goal:** "Open the file task.html in Downloads in the file manager; when prompted open it with Chrome. Then create a drawing using the three colors shown at the top and hit submit."
- **History:** F/F/F/F/F
- **Step budget:** 20
- **Steps R0-R4:** 20/20/20/20/19
- **Termination:** agent-done
- **Determinism:** D3 unstable
- **Tags:** game_playing, parameterized
- **Evaluator:** [`BrowserDraw class / inherited is_successful`](../../MARS-Voyager/androidworld/android_world/task_evals/single/browser.py#L445) - evaluator source link or inherited evaluator class.
- **Setup:** [`BrowserDraw class / inherited initialize_task`](../../MARS-Voyager/androidworld/android_world/task_evals/single/browser.py#L445) - setup source link or inherited setup class.
- **Trajectory folder:** [formatted traces](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107_reformatted/BrowserDraw)
- **Image folder:** [screenshots](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/BrowserDraw/images)

## What success requires

The evaluator must observe the task-specific post-condition for: "Open the file task.html in Downloads in the file manager; when prompted open it with Chrome. Then create a drawing using the three colors shown at the top and hit submit.". The task template is: "Open the file task.html in Downloads in the file manager; when prompted open it with Chrome. Then create a drawing using the three colors shown at the top and hit submit.". In practical terms, the report should judge success by the source-linked evaluator rather than by the agent's self-report; a `terminate(success)` or `answer` action is only meaningful if the app state or returned answer matches that evaluator.

## Cross-round behavior

| Round | Steps | Terminal action | Wall-step action |
|---|---:|---|---|
| R0 | 20 | click {'action': 'click', 'coordinate': [123, 246]} | Swipe up from the bottom of the screen to open the app drawer and locate the file manager. |
| R1 | 20 | click {'action': 'click', 'coordinate': [647, 171]} | Swipe up from the bottom of the screen to open the app drawer and locate the file manager. |
| R2 | 20 | click {'action': 'click', 'coordinate': [353, 171]} | Swipe up from the bottom of the screen to open the app drawer and locate the file manager. |
| R3 | 20 | click {'action': 'click', 'coordinate': [647, 171]} | Swipe up from the bottom of the screen to open the app drawer and locate the file manager. |
| R4 | 19 | terminate {'action': 'terminate', 'status': 'success'} | Tap on the 'task.html' file to open it. |

First divergent assistant step across available rounds: **step 1**. The wall step used for this file is **step 1** because it is the first durable point where the trace commits to the failure mode represented by `canvas/game-capability; visual-grounding; premature-success`.

## Wall step

### Round 0

![R0 step 1](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/BrowserDraw/images/repeat00-step0-20260426203705-2N2seYoylI.png)
*R0 step 1 - wall-step screenshot associated with the action below.*

Agent thought: "To open the file 'task.html' from the Downloads folder, I need to access the file manager first. Since it's not visible on the home screen, I should navigate to the app drawer or use a file management app."

Agent action: `Swipe up from the bottom of the screen to open the app drawer and locate the file manager.`

Tool call: `swipe {'action': 'swipe', 'coordinate': [499, 775], 'coordinate2': [491, 328]}`

### Round 4

![R4 step 1](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/BrowserDraw/images/repeat04-step0-20260427041036-2N2seYoylI.png)
*R4 step 1 - comparison screenshot at the same wall-step index when available.*

Agent thought: "I need to open the file 'task.html' from the Downloads folder to proceed with creating the drawing. Since I've already navigated to the correct directory, the next logical step is to initiate the process of opening the file."

Agent action: `Tap on the 'task.html' file to open it.`

Tool call: `click {'action': 'click', 'coordinate': [189, 69]}`

## What actually happened

The final action is `agent-done`, so the run ends before the trace shows a verified evaluator post-condition. The R0 wall-step action is `Swipe up from the bottom of the screen to open the app drawer and locate the file manager.`. The representative comparison round records `Tap on the 'task.html' file to open it.` at the same step index, while the final available round ends with `The task is completed successfully.`. This is enough to identify the repeated failure mechanism, but any claim about fine-grained UI state should be checked against the embedded screenshots and the raw image directory.

## Root cause and category

Categories: `canvas/game-capability`: the task requires browser canvas/game interaction or multi-step visual memory that the current agent does not handle reliably; `visual-grounding`: the failure depends on reading a UI state, icon, checkbox, slider, canvas, or numeric value more precisely than the agent manages; `premature-success`: the agent declares success or answers before observing the evaluator-relevant post-condition.

Verdict: **retry sometimes explores variants but all fail**. The proximate failure is `canvas/game-capability; visual-grounding; premature-success`; the upstream issue is that the policy lacks the reliable procedure needed for this class of task before it exhausts the budget or finalizes prematurely.

## Suggested fix

Treat browser canvas/game tasks as a separate capability gap; add task-specific tooling or visual grid extraction rather than generic tapping. Improve state readback prompts and use UI/a11y text or detail screens where available instead of guessing from icons or pixels.
