# SportsTrackerTotalDistanceForCategoryOverInterval

## Quick links
- **Goal:** "What was the total distance covered for swimming activities in the OpenTracks app from October 08 to October 14? Express your answer as a single number in meters rounded to the nearest integer."
- **History:** F/F/F/F/F
- **Step budget:** 4
- **Steps R0-R4:** 4/4/4/4/4
- **Termination:** answer
- **Determinism:** D3 unstable
- **Tags:** search, parameterized, math_counting
- **Evaluator:** [`SportsTrackerTotalDistanceForCategoryOverInterval dynamic task / InformationRetrieval.is_successful`](../../MARS-Voyager/androidworld/android_world/task_evals/information_retrieval/information_retrieval.py#L109) - dynamic task; prompt and criteria are defined in [tasks.textproto](../../MARS-Voyager/androidworld/android_world/task_evals/information_retrieval/proto/tasks.textproto#L2932).
- **Setup:** [`SportsTrackerTotalDistanceForCategoryOverInterval dynamic task / InformationRetrieval.initialize_task`](../../MARS-Voyager/androidworld/android_world/task_evals/information_retrieval/information_retrieval.py#L82) - initializes app-specific state from the task proto.
- **Trajectory folder:** [formatted traces](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107_reformatted/SportsTrackerTotalDistanceForCategoryOverInterval)
- **Image folder:** [screenshots](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/SportsTrackerTotalDistanceForCategoryOverInterval/images)

## What success requires

The evaluator must observe the task-specific post-condition for: "What was the total distance covered for swimming activities in the OpenTracks app from October 08 to October 14? Express your answer as a single number in meters rounded to the nearest integer.". The task template is: "What was the total distance covered for {category} activities in the OpenTracks app from {start_date} to {end_date}? Express your answer in meters as a single integer.". In practical terms, the report should judge success by the source-linked evaluator rather than by the agent's self-report; a `terminate(success)` or `answer` action is only meaningful if the app state or returned answer matches that evaluator.

## Cross-round behavior

| Round | Steps | Terminal action | Wall-step action |
|---|---:|---|---|
| R0 | 4 | answer {'action': 'answer', 'text': '10994'} | The total distance covered for swimming activities on October 8 is 4.35 + 2.49 = 6.84 miles, which is approximately 10994 meters. |
| R1 | 4 | answer {'action': 'answer', 'text': '10994'} | The total distance covered for swimming activities on October 8 is 4.35 + 2.49 = 6.84 miles, which is approximately 10994 meters. |
| R2 | 4 | answer {'action': 'answer', 'text': '10994'} | The total distance covered for swimming activities on October 8 is 4.35 + 2.49 = 6.84 miles, which is approximately 10994 meters. |
| R3 | 4 | answer {'action': 'answer', 'text': '10994'} | The total distance covered for swimming activities on October 8 is 4.35 + 2.49 = 6.84 miles, which is approximately 10994 meters. |
| R4 | 4 | answer {'action': 'answer', 'text': '10994'} | The total distance covered for swimming activities on October 8 is 4.35 + 2.49 = 6.84 miles, which is approximately 10994 meters. |

First divergent assistant step across available rounds: **step 3**. The wall step used for this file is **step 4** because it is the first durable point where the trace commits to the failure mode represented by `premature-success; visual-grounding`.

## Wall step

### Round 0

![R0 step 4](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/SportsTrackerTotalDistanceForCategoryOverInterval/images/repeat00-step3-20260426230814-cLA2cYVmcW.png)
*R0 step 4 - wall-step screenshot associated with the action below.*

Agent thought: "I need to find the total distance covered for swimming activities from October 08 to October 14. I've identified two swimming activities on October 8: "Active Rest Day" (4.35 mi) and "More tired than usual today" (2.49 mi). I will add these distances together to get the total."

Agent action: `The total distance covered for swimming activities on October 8 is 4.35 + 2.49 = 6.84 miles, which is approximately 10994 meters.`

Tool call: `answer {'action': 'answer', 'text': '10994'}`

### Round 4

![R4 step 4](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/SportsTrackerTotalDistanceForCategoryOverInterval/images/repeat04-step3-20260427050611-cLA2cYVmcW.png)
*R4 step 4 - comparison screenshot at the same wall-step index when available.*

Agent thought: "I need to find the total distance covered for swimming activities from October 08 to October 14. I've identified two swimming activities on October 8: "Active Rest Day" (4.35 mi) and "More tired than usual today" (2.49 mi). I will add these distances together to get the total."

Agent action: `The total distance covered for swimming activities on October 8 is 4.35 + 2.49 = 6.84 miles, which is approximately 10994 meters.`

Tool call: `answer {'action': 'answer', 'text': '10994'}`

## What actually happened

The final action is `answer`, so the run ends before the trace shows a verified evaluator post-condition. The R0 wall-step action is `The total distance covered for swimming activities on October 8 is 4.35 + 2.49 = 6.84 miles, which is approximately 10994 meters.`. The representative comparison round records `The total distance covered for swimming activities on October 8 is 4.35 + 2.49 = 6.84 miles, which is approximately 10994 meters.` at the same step index, while the final available round ends with `The total distance covered for swimming activities on October 8 is 4.35 + 2.49 = 6.84 miles, which is approximately 10994 meters.`. This is enough to identify the repeated failure mechanism, but any claim about fine-grained UI state should be checked against the embedded screenshots and the raw image directory.

## Root cause and category

Categories: `premature-success`: the agent declares success or answers before observing the evaluator-relevant post-condition; `visual-grounding`: the failure depends on reading a UI state, icon, checkbox, slider, canvas, or numeric value more precisely than the agent manages.

Verdict: **retry sometimes explores variants but all fail**. The proximate failure is `premature-success; visual-grounding`; the upstream issue is that the policy lacks the reliable procedure needed for this class of task before it exhausts the budget or finalizes prematurely.

## Suggested fix

Require a verification observation immediately before `terminate(success)` or `answer`, tied to the evaluator post-condition. Improve state readback prompts and use UI/a11y text or detail screens where available instead of guessing from icons or pixels.
