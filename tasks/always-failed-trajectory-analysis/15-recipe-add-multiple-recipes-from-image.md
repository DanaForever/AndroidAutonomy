# RecipeAddMultipleRecipesFromImage

## Quick links
- **Goal:** "Add the recipes from recipes.jpg in Simple Gallery Pro to the Broccoli recipe app."
- **History:** F/F/F/F/F
- **Step budget:** 60
- **Steps R0-R4:** 60/60/60/18/12
- **Termination:** agent-done
- **Determinism:** D3 unstable
- **Tags:** transcription, screen_reading, data_entry, complex_ui_understanding, parameterized
- **Evaluator:** [`RecipeAddMultipleRecipesFromImage class / inherited is_successful`](../../MARS-Voyager/androidworld/android_world/task_evals/single/recipe.py#L518) - evaluator source link or inherited evaluator class.
- **Setup:** [`RecipeAddMultipleRecipesFromImage.initialize_task`](../../MARS-Voyager/androidworld/android_world/task_evals/single/recipe.py#L533) - setup source link or inherited setup class.
- **Trajectory folder:** [formatted traces](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107_reformatted/RecipeAddMultipleRecipesFromImage)
- **Image folder:** [screenshots](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/RecipeAddMultipleRecipesFromImage/images)

## What success requires

The evaluator must observe the task-specific post-condition for: "Add the recipes from recipes.jpg in Simple Gallery Pro to the Broccoli recipe app.". The task template is: "Add the recipes from recipes.jpg in Simple Gallery Pro to the Broccoli recipe app.". In practical terms, the report should judge success by the source-linked evaluator rather than by the agent's self-report; a `terminate(success)` or `answer` action is only meaningful if the app state or returned answer matches that evaluator.

## Cross-round behavior

| Round | Steps | Terminal action | Wall-step action |
|---|---:|---|---|
| R0 | 60 | type {'action': 'type', 'text': 'Classic Margherita Pizza'} | I swiped up to open the app drawer to find the Simple Gallery Pro app. |
| R1 | 60 | type {'action': 'type', 'text': 'BBQ Chicken Quesadillas'} | I swiped up to open the app drawer to find the Simple Gallery Pro app. |
| R2 | 60 | swipe {'action': 'swipe', 'coordinate': [499, 817], 'coordinate2': [491, 292]} | Swipe up from the bottom of the screen to open the app drawer and locate the Simple Gallery Pro app. |
| R3 | 18 | terminate {'action': 'terminate', 'status': 'success'} | Swipe up from the bottom of the screen to open the app drawer and locate the Simple Gallery Pro app. |
| R4 | 12 | terminate {'action': 'terminate', 'status': 'success'} | I swiped up to open the app drawer to find the Simple Gallery Pro app. |

First divergent assistant step across available rounds: **step 1**. The wall step used for this file is **step 1** because it is the first durable point where the trace commits to the failure mode represented by `premature-success; compound-task; task-constraint-missed`.

## Wall step

### Round 0

![R0 step 1](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/RecipeAddMultipleRecipesFromImage/images/repeat00-step0-20260426215505-ETsvWVts4n.png)
*R0 step 1 - wall-step screenshot associated with the action below.*

Agent thought: "I need to add recipes from the "recipes.jpg" file in Simple Gallery Pro to the Broccoli recipe app. To do this, I first need to locate and open the Simple Gallery Pro app. Since it's not visible on the home screen, I performed a swipe up gesture to access the app drawer where all installed apps are listed."

Agent action: `I swiped up to open the app drawer to find the Simple Gallery Pro app.`

Tool call: `swipe {'action': 'swipe', 'coordinate': [499, 742], 'coordinate2': [493, 287]}`

### Round 4

![R4 step 1](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/RecipeAddMultipleRecipesFromImage/images/repeat04-step0-20260427043737-ETsvWVts4n.png)
*R4 step 1 - comparison screenshot at the same wall-step index when available.*

Agent thought: "I need to add recipes from the "recipes.jpg" file in Simple Gallery Pro to the Broccoli recipe app. To do this, I first need to locate and open the Simple Gallery Pro app. Since it's not visible on the home screen, I performed a swipe up gesture to access the app drawer where all installed apps are listed."

Agent action: `I swiped up to open the app drawer to find the Simple Gallery Pro app.`

Tool call: `swipe {'action': 'swipe', 'coordinate': [499, 742], 'coordinate2': [493, 287]}`

## What actually happened

The final action is `agent-done`, so the run ends before the trace shows a verified evaluator post-condition. The R0 wall-step action is `I swiped up to open the app drawer to find the Simple Gallery Pro app.`. The representative comparison round records `I swiped up to open the app drawer to find the Simple Gallery Pro app.` at the same step index, while the final available round ends with `I opened the Broccoli recipe app to confirm the addition of the recipes.`. This is enough to identify the repeated failure mechanism, but any claim about fine-grained UI state should be checked against the embedded screenshots and the raw image directory.

## Root cause and category

Categories: `premature-success`: the agent declares success or answers before observing the evaluator-relevant post-condition; `compound-task`: the task has multiple sequential legs or repeated item operations, and the trace completes only part of the required workflow; `task-constraint-missed`: the agent misses a stated constraint such as all items, ordering, filtering, exact duplicate handling, date range, or recipient/content matching.

Verdict: **retry sometimes explores variants but all fail**. The proximate failure is `premature-success; compound-task; task-constraint-missed`; the upstream issue is that the policy lacks the reliable procedure needed for this class of task before it exhausts the budget or finalizes prematurely.

## Suggested fix

Require a verification observation immediately before `terminate(success)` or `answer`, tied to the evaluator post-condition. Add a lightweight checklist/planning scaffold for multi-leg tasks and repeated item loops so completion is tracked before termination.
