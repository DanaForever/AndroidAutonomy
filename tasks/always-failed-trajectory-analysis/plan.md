# Plan — Screenshot-Grounded Analysis for 32 Always-Failed Tasks

## Summary

Create a fresh rescue-style documentation set under `tasks/always-failed-trajectory-analysis/` for the 32 tasks from run `20260426203107` that failed all retry attempts.

The report will be image-grounded and source-linked, matching `tasks/rescue-trajectory-analysis-new/plan.md`: one overview, one conclusion, and one per-task markdown file for every always-failed task. Instead of finding a fail-to-success divergence step, each task will identify the **wall step**: the first step where the agent commits to a path that fails in every retry round.

Primary deliverable path:

```text
tasks/always-failed-trajectory-analysis/plan.md
```

## Output Layout

```text
tasks/always-failed-trajectory-analysis/
├── plan.md
├── index.md
├── conclusion.md
├── 01-browser-draw.md
├── 02-browser-maze.md
├── 03-browser-multiply.md
├── 04-camera-take-photo.md
├── 05-camera-take-video.md
├── 06-expense-add-multiple-from-gallery.md
├── 07-expense-add-multiple-from-markor.md
├── 08-markor-add-note-header.md
├── 09-markor-change-note-content.md
├── 10-markor-create-note-and-sms.md
├── 11-markor-merge-notes.md
├── 12-markor-transcribe-video.md
├── 13-notes-todo-item-count.md
├── 14-osmand-track.md
├── 15-recipe-add-multiple-recipes-from-image.md
├── 16-recipe-add-multiple-recipes-from-markor.md
├── 17-recipe-add-multiple-recipes-from-markor2.md
├── 18-recipe-delete-duplicate-recipes2.md
├── 19-recipe-delete-duplicate-recipes3.md
├── 20-recipe-delete-multiple-recipes-with-constraint.md
├── 21-retro-playlist-duration.md
├── 22-simple-calendar-events-in-next-week.md
├── 23-simple-sms-reply.md
├── 24-simple-sms-reply-most-recent.md
├── 25-simple-sms-send.md
├── 26-simple-sms-send-clipboard-content.md
├── 27-simple-sms-send-received-address.md
├── 28-sports-tracker-activities-on-date.md
├── 29-sports-tracker-total-distance-for-category-over-interval.md
├── 30-system-brightness-min.md
├── 31-system-copy-to-clipboard.md
└── 32-tasks-completed-tasks-for-date.md
```

## Per-Task File Template

Each task file will use this structure:

```markdown
# <Task name>

## Quick links
- **Goal:** "<exact goal text from log>"
- **History:** F/F/F/F/F
- **Step budget:** <n>
- **Steps R0-R4:** <n>/<n>/<n>/<n>/<n or missing>
- **Termination:** max-steps / agent-done / answer
- **Determinism:** D1 strict / D3 unstable
- **Evaluator:** [`<ClassName>.is_successful`](<relative source link>) - one-sentence check
- **Setup:** [`<ClassName>.initialize_task`](<relative source link>) - one-sentence setup
- **Trajectory folder:** [formatted traces](<relative path>)
- **Image folder:** [screenshots](<relative path>)

## What success requires
Plain-English evaluator explanation, grounded in source links.

## Cross-round behavior
Short table of R0-R4 step counts, terminal actions, and first divergent step if any.

## Wall step

### Round 0
![R0 step N](<relative image path>)
*R0 step N - caption*

Agent thought: "..."
Agent action: `<action>`

### Representative comparison round
![R<n> step N](<relative image path>)
*R<n> step N - caption*

Agent thought: "..."
Agent action: `<action>`

## What actually happened
Chronological explanation of the failure mode, backed by embedded screenshots, trajectory text, logs, and evaluator source.

## Root cause and category
One paragraph with category tags:
- app-not-found
- premature-success
- compound-task
- visual-grounding
- canvas/game-capability
- env/a11y-flake
- task-constraint-missed

Explicit verdict:
**retry cannot help** / **retry sometimes explores variants but all fail** / **needs env fix**.

## Suggested fix
Concrete one-line or short-paragraph fix, tied to the observed wall step.
```

## Evidence Rules

- Every UI claim must be backed by an embedded screenshot that was visually inspected.
- Use image paths relative to each task file:
  `../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/<TaskName>/images/<file>.png`
- Use formatted trajectories first:
  `../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107_reformatted/<TaskName>/repeat_*.txt`
- Fall back to raw JSONL when formatted traces omit detail:
  `../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/<TaskName>/repeat_*.jsonl`
- Check worker logs for each task slice:
  `../../MARS-Voyager/eval_results/UI-Voyager/logs/20260426203107/eval_UI-Voyager_1workers.log`
- Link evaluator and setup source from:
  `../../MARS-Voyager/androidworld/android_world/task_evals/`

## Index And Conclusion

`index.md` will include:
- Context for run `20260426203107`
- Exact filter defining the 32 always-failed tasks
- How to read the report
- Executive table with task, group, determinism, root cause, fixability, and task-file link
- Glossary of Android concepts introduced across task files

`conclusion.md` will include:
- Category matrix: 32 tasks x failure categories
- Determinism summary: D1 strict vs D3 unstable
- Retry-waste analysis for D1 tasks
- Prioritized recommendations, ordered by estimated tasks unblocked
- Short list of likely prompt-only fixes versus harness/env fixes

## Workflow

Proceed directly through all 32 tasks without a separate sample-review checkpoint.

For each task:
1. Read all available formatted trajectories.
2. Fall back to raw JSONL for missing details, exact actions, and screenshot names.
3. Identify the wall step.
4. Open and inspect the wall-step screenshots.
5. Read evaluator and setup source.
6. Check the worker log slice for env/a11y/snapshot signals.
7. Write the per-task file using the shared template.
8. Update `index.md` and `conclusion.md` after the full task set is complete.

## Verification

- Confirm always-failed task list from `retry_summary.json` is exactly 32.
- For each task, verify all available `repeat_*_fail.jsonl` files are considered.
- Confirm every task file embeds at least one wall-step screenshot.
- Confirm every evaluator/setup link resolves to the correct source.
- Confirm `index.md` table matches all per-task verdicts.
- Confirm `conclusion.md` category matrix has all 32 tasks and every task has at least one category.

## Assumptions

- The new analysis should not overwrite `tasks/always-failed-analysis/report.md`.
- The new directory should mirror `tasks/rescue-trajectory-analysis-new/` in depth and style.
- The task set is fixed to run `20260426203107`.
- No eval reruns or source-code fixes are in scope; this is a documentation and investigation artifact only.
- There is no sample-first approval gate; all 32 analyses are produced in one pass.
