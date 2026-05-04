# Conclusion — Always-Failed Trajectory Analysis

The 32 always-failed tasks are not one failure mode. They cluster around app launch/search, premature finalization, compound workflow tracking, and visual/canvas grounding. Retry alone is not enough: D1 tasks repeat the same trajectory, while D3 tasks explore variants that still end in failure.

## Determinism summary

| Class | Count | Meaning |
|---|---:|---|
| D1 strict | 1 | Byte-identical assistant outputs across all available rounds; retry is wasted for the observed policy/env state. |
| D3 unstable | 31 | Rounds diverge, but every variant still fails. |

## Category matrix

| Task | App not found | Premature | Compound | Visual | Canvas/game | Env/a11y | Constraint missed |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| [BrowserDraw](./01-browser-draw.md) |  | x |  | x | x |  |  |
| [BrowserMaze](./02-browser-maze.md) |  |  |  | x | x |  |  |
| [BrowserMultiply](./03-browser-multiply.md) |  |  | x | x | x |  | x |
| [CameraTakePhoto](./04-camera-take-photo.md) |  | x |  |  |  |  |  |
| [CameraTakeVideo](./05-camera-take-video.md) |  | x |  |  |  |  |  |
| [ExpenseAddMultipleFromGallery](./06-expense-add-multiple-from-gallery.md) |  | x | x |  |  |  | x |
| [ExpenseAddMultipleFromMarkor](./07-expense-add-multiple-from-markor.md) |  | x | x |  |  |  | x |
| [MarkorAddNoteHeader](./08-markor-add-note-header.md) |  |  | x |  |  |  | x |
| [MarkorChangeNoteContent](./09-markor-change-note-content.md) |  |  | x |  |  |  | x |
| [MarkorCreateNoteAndSms](./10-markor-create-note-and-sms.md) | x |  | x |  |  |  | x |
| [MarkorMergeNotes](./11-markor-merge-notes.md) |  |  | x |  |  |  | x |
| [MarkorTranscribeVideo](./12-markor-transcribe-video.md) | x |  | x |  |  |  | x |
| [NotesTodoItemCount](./13-notes-todo-item-count.md) | x |  |  | x |  |  |  |
| [OsmAndTrack](./14-osmand-track.md) |  | x | x |  |  |  | x |
| [RecipeAddMultipleRecipesFromImage](./15-recipe-add-multiple-recipes-from-image.md) |  | x | x |  |  |  | x |
| [RecipeAddMultipleRecipesFromMarkor](./16-recipe-add-multiple-recipes-from-markor.md) |  | x | x |  |  |  | x |
| [RecipeAddMultipleRecipesFromMarkor2](./17-recipe-add-multiple-recipes-from-markor2.md) |  | x | x |  |  |  | x |
| [RecipeDeleteDuplicateRecipes2](./18-recipe-delete-duplicate-recipes2.md) |  | x | x |  |  |  | x |
| [RecipeDeleteDuplicateRecipes3](./19-recipe-delete-duplicate-recipes3.md) |  | x | x |  |  |  | x |
| [RecipeDeleteMultipleRecipesWithConstraint](./20-recipe-delete-multiple-recipes-with-constraint.md) |  | x | x | x |  |  | x |
| [RetroPlaylistDuration](./21-retro-playlist-duration.md) | x |  | x |  |  |  | x |
| [SimpleCalendarEventsInNextWeek](./22-simple-calendar-events-in-next-week.md) |  |  | x |  |  |  | x |
| [SimpleSmsReply](./23-simple-sms-reply.md) | x |  |  |  |  |  |  |
| [SimpleSmsReplyMostRecent](./24-simple-sms-reply-most-recent.md) | x |  |  |  |  |  |  |
| [SimpleSmsSend](./25-simple-sms-send.md) | x |  |  |  |  |  |  |
| [SimpleSmsSendClipboardContent](./26-simple-sms-send-clipboard-content.md) | x |  |  |  |  |  |  |
| [SimpleSmsSendReceivedAddress](./27-simple-sms-send-received-address.md) | x |  |  |  |  |  | x |
| [SportsTrackerActivitiesOnDate](./28-sports-tracker-activities-on-date.md) |  | x |  | x |  |  |  |
| [SportsTrackerTotalDistanceForCategoryOverInterval](./29-sports-tracker-total-distance-for-category-over-interval.md) |  | x |  | x |  |  |  |
| [SystemBrightnessMin](./30-system-brightness-min.md) |  | x |  | x |  |  |  |
| [SystemCopyToClipboard](./31-system-copy-to-clipboard.md) |  | x |  |  |  |  |  |
| [TasksCompletedTasksForDate](./32-tasks-completed-tasks-for-date.md) |  | x |  | x |  |  |  |

## Category counts

- **app-not-found:** 9 tasks. The agent moves into launcher/app-drawer search behavior and spends the budget swiping or looking for the target app instead of using a reliable app search/open strategy.
- **premature-success:** 17 tasks. The agent declares success or answers before observing the evaluator-relevant post-condition.
- **compound-task:** 17 tasks. The task has multiple sequential legs or repeated item operations, and the trace completes only part of the required workflow.
- **visual-grounding:** 9 tasks. The failure depends on reading a ui state, icon, checkbox, slider, canvas, or numeric value more precisely than the agent manages.
- **canvas/game-capability:** 3 tasks. The task requires browser canvas/game interaction or multi-step visual memory that the current agent does not handle reliably.
- **task-constraint-missed:** 18 tasks. The agent misses a stated constraint such as all items, ordering, filtering, exact duplicate handling, date range, or recipient/content matching.

## Prioritized recommendations

| # | Recommendation | Primary categories | Why it matters |
|---:|---|---|---|
| 1 | Use launcher search or direct app-open fallback after one failed app scan | app-not-found | Unblocks SMS, Notes/Joplin, Retro, and the SMS leg of Markor workflows. |
| 2 | Require evaluator-oriented verification before finalization | premature-success | Prevents short traces that claim success after only partial action execution. |
| 3 | Add explicit checklist state for compound and repeated-item tasks | compound-task, task-constraint-missed | Keeps multi-leg tasks from dropping later constraints or stopping after one item. |
| 4 | Prefer text/a11y/detail views for visual facts before answering | visual-grounding | Reduces wrong checkbox, icon, slider, and numeric-read answers. |
| 5 | Separate browser canvas/game tasks into a specialized capability track | canvas/game-capability | Generic mobile tapping is not sufficient for canvas drawing, maze navigation, and multi-number memory tasks. |

## Verification checklist

- `retry_summary.json` filter yields 32 always-failed tasks.
- Every task file considers all available `repeat_*_fail.jsonl` files.
- Every task file embeds at least one wall-step screenshot.
- `index.md` and this matrix include all 32 tasks.
- Source links should be spot-checked because inherited evaluator/setup methods may resolve to class-level links when methods are inherited.
