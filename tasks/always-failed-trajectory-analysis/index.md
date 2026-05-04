# Always-Failed Trajectory Analysis

Run `20260426203107` used retry orchestration with fixed `task_random_seed=42` and `temperature=0`. The 32 tasks in this directory failed every available retry attempt. This report mirrors the rescue trajectory analysis style, but looks for each task's **wall step** rather than a fail-to-success divergence.

## How to read this report

Each task file embeds the wall-step screenshots, links to formatted/raw trajectories, records R0-R4 step counts, and assigns one or more failure categories. Categories are intentionally non-exclusive because a task can be both compound and prematurely terminated, or both app-not-found and constraint-missed.

## Executive summary

| # | Task | Group | Steps R0-R4 | Det | Categories | Verdict | File |
|---:|---|---|---|---|---|---|---|
| 1 | BrowserDraw | Browser / game | 20/20/20/20/19 | D3 | canvas/game-capability, visual-grounding, premature-success | retry sometimes explores variants but all fail | [01-browser-draw.md](./01-browser-draw.md) |
| 2 | BrowserMaze | Browser / game | 20/20/20/20/20 | D3 | canvas/game-capability, visual-grounding | retry sometimes explores variants but all fail | [02-browser-maze.md](./02-browser-maze.md) |
| 3 | BrowserMultiply | Browser / game | 19/19/22/19/22 | D3 | canvas/game-capability, visual-grounding, compound-task, task-constraint-missed | retry sometimes explores variants but all fail | [03-browser-multiply.md](./03-browser-multiply.md) |
| 4 | CameraTakePhoto | Camera | 10/10/9/10/3 | D3 | premature-success | retry sometimes explores variants but all fail | [04-camera-take-photo.md](./04-camera-take-photo.md) |
| 5 | CameraTakeVideo | Camera | 10/10/10/10/8 | D3 | premature-success | retry sometimes explores variants but all fail | [05-camera-take-video.md](./05-camera-take-video.md) |
| 6 | ExpenseAddMultipleFromGallery | Expense import | 27/11/38/33/7 | D3 | premature-success, compound-task, task-constraint-missed | retry sometimes explores variants but all fail | [06-expense-add-multiple-from-gallery.md](./06-expense-add-multiple-from-gallery.md) |
| 7 | ExpenseAddMultipleFromMarkor | Expense import | 60/9/48/60/2 | D3 | premature-success, compound-task, task-constraint-missed | retry sometimes explores variants but all fail | [07-expense-add-multiple-from-markor.md](./07-expense-add-multiple-from-markor.md) |
| 8 | MarkorAddNoteHeader | Markor complex | 12/12/12/12/12 | D3 | compound-task, task-constraint-missed | retry sometimes explores variants but all fail | [08-markor-add-note-header.md](./08-markor-add-note-header.md) |
| 9 | MarkorChangeNoteContent | Markor complex | 12/12/12/11/12 | D3 | compound-task, task-constraint-missed | retry sometimes explores variants but all fail | [09-markor-change-note-content.md](./09-markor-change-note-content.md) |
| 10 | MarkorCreateNoteAndSms | Markor complex | 18/18/18/18/18 | D3 | app-not-found, compound-task, task-constraint-missed | retry sometimes explores variants but all fail | [10-markor-create-note-and-sms.md](./10-markor-create-note-and-sms.md) |
| 11 | MarkorMergeNotes | Markor complex | 78/20/47/78/78 | D3 | compound-task, task-constraint-missed | retry sometimes explores variants but all fail | [11-markor-merge-notes.md](./11-markor-merge-notes.md) |
| 12 | MarkorTranscribeVideo | Markor complex | 20/20/20/20/20 | D3 | app-not-found, compound-task, task-constraint-missed | retry sometimes explores variants but all fail | [12-markor-transcribe-video.md](./12-markor-transcribe-video.md) |
| 13 | NotesTodoItemCount | Notes info retrieval | 10/10/10/10/10 | D3 | app-not-found, visual-grounding | retry sometimes explores variants but all fail | [13-notes-todo-item-count.md](./13-notes-todo-item-count.md) |
| 14 | OsmAndTrack | OsmAnd | 22/15/65/21/24 | D3 | premature-success, compound-task, task-constraint-missed | retry sometimes explores variants but all fail | [14-osmand-track.md](./14-osmand-track.md) |
| 15 | RecipeAddMultipleRecipesFromImage | Recipe import | 60/60/60/18/12 | D3 | premature-success, compound-task, task-constraint-missed | retry sometimes explores variants but all fail | [15-recipe-add-multiple-recipes-from-image.md](./15-recipe-add-multiple-recipes-from-image.md) |
| 16 | RecipeAddMultipleRecipesFromMarkor | Recipe import | 21/9/15/15/19 | D3 | premature-success, compound-task, task-constraint-missed | retry sometimes explores variants but all fail | [16-recipe-add-multiple-recipes-from-markor.md](./16-recipe-add-multiple-recipes-from-markor.md) |
| 17 | RecipeAddMultipleRecipesFromMarkor2 | Recipe import | 6/60/60/60/10 | D3 | premature-success, compound-task, task-constraint-missed | retry sometimes explores variants but all fail | [17-recipe-add-multiple-recipes-from-markor2.md](./17-recipe-add-multiple-recipes-from-markor2.md) |
| 18 | RecipeDeleteDuplicateRecipes2 | Recipe delete | 9/11/11/9/24 | D3 | premature-success, compound-task, task-constraint-missed | retry sometimes explores variants but all fail | [18-recipe-delete-duplicate-recipes2.md](./18-recipe-delete-duplicate-recipes2.md) |
| 19 | RecipeDeleteDuplicateRecipes3 | Recipe delete | 7/9/9/7/34 | D3 | premature-success, compound-task, task-constraint-missed | retry sometimes explores variants but all fail | [19-recipe-delete-duplicate-recipes3.md](./19-recipe-delete-duplicate-recipes3.md) |
| 20 | RecipeDeleteMultipleRecipesWithConstraint | Recipe delete | 5/5/5/5/40 | D3 | premature-success, compound-task, visual-grounding, task-constraint-missed | retry sometimes explores variants but all fail | [20-recipe-delete-multiple-recipes-with-constraint.md](./20-recipe-delete-multiple-recipes-with-constraint.md) |
| 21 | RetroPlaylistDuration | Retro | 23/30/30/30/30 | D3 | app-not-found, compound-task, task-constraint-missed | retry sometimes explores variants but all fail | [21-retro-playlist-duration.md](./21-retro-playlist-duration.md) |
| 22 | SimpleCalendarEventsInNextWeek | Calendar | 10/9/10/10/10 | D3 | compound-task, task-constraint-missed | retry sometimes explores variants but all fail | [22-simple-calendar-events-in-next-week.md](./22-simple-calendar-events-in-next-week.md) |
| 23 | SimpleSmsReply | SMS | 12/12/12/12/12 | D3 | app-not-found | retry sometimes explores variants but all fail | [23-simple-sms-reply.md](./23-simple-sms-reply.md) |
| 24 | SimpleSmsReplyMostRecent | SMS | 12/12/12/12/12 | D3 | app-not-found | retry sometimes explores variants but all fail | [24-simple-sms-reply-most-recent.md](./24-simple-sms-reply-most-recent.md) |
| 25 | SimpleSmsSend | SMS | 12/12/12/12/12 | D3 | app-not-found | retry sometimes explores variants but all fail | [25-simple-sms-send.md](./25-simple-sms-send.md) |
| 26 | SimpleSmsSendClipboardContent | SMS | 12/12/12/12/- | D1 | app-not-found | retry cannot help | [26-simple-sms-send-clipboard-content.md](./26-simple-sms-send-clipboard-content.md) |
| 27 | SimpleSmsSendReceivedAddress | SMS | 18/18/18/18/18 | D3 | app-not-found, task-constraint-missed | retry sometimes explores variants but all fail | [27-simple-sms-send-received-address.md](./27-simple-sms-send-received-address.md) |
| 28 | SportsTrackerActivitiesOnDate | SportsTracker | 6/6/5/6/5 | D3 | premature-success, visual-grounding | retry sometimes explores variants but all fail | [28-sports-tracker-activities-on-date.md](./28-sports-tracker-activities-on-date.md) |
| 29 | SportsTrackerTotalDistanceForCategoryOverInterval | SportsTracker | 4/4/4/4/4 | D3 | premature-success, visual-grounding | retry sometimes explores variants but all fail | [29-sports-tracker-total-distance-for-category-over-interval.md](./29-sports-tracker-total-distance-for-category-over-interval.md) |
| 30 | SystemBrightnessMin | System | 9/9/7/7/8 | D3 | premature-success, visual-grounding | retry sometimes explores variants but all fail | [30-system-brightness-min.md](./30-system-brightness-min.md) |
| 31 | SystemCopyToClipboard | System | 7/8/8/8/8 | D3 | premature-success | retry sometimes explores variants but all fail | [31-system-copy-to-clipboard.md](./31-system-copy-to-clipboard.md) |
| 32 | TasksCompletedTasksForDate | Tasks app | 4/4/4/4/4 | D3 | premature-success, visual-grounding | retry sometimes explores variants but all fail | [32-tasks-completed-tasks-for-date.md](./32-tasks-completed-tasks-for-date.md) |

## Glossary

- **Wall step:** first durable point where the agent commits to a path that ends in failure in every retry round.
- **D1 strict:** all available rounds have the same step count and byte-identical assistant outputs at every step.
- **D3 unstable:** at least one available round diverges in step count or assistant output, but all variants still fail.
- **App-not-found:** repeated launcher/app-drawer search fails to reach the target app.
- **Premature-success:** the agent finalizes before verifying the evaluator-relevant state.
- **Compound-task:** the task has multiple independent legs or repeated item operations, and the agent completes only part of them.
- **Visual-grounding:** the core failure is reading or manipulating a visual state precisely.
