# My Report

## Set up 
random seed 42, 5 retry rounds each (next round reruns failed tasks from previous rounds). final accuracy 84/116.

## Flip tasks
17 tasks flipped from fail to pass across 5 rounds. detailed analysis is in [rescue-trajectory-analysis/](./rescue-trajectory-analysis/) folder.

- [01 TasksDueOnDate](./rescue-trajectory-analysis-new/01-tasks-due-on-date.md): same scrolling behavior to the same env leads to non-deterministic outcome
- [02 ClockStopWatchRunning](./rescue-trajectory-analysis-new/02-clock-stopwatch-running.md): state leakage from previous task creates an overlay that confuses the model and leads to hallucinated success at step 0
- [03 TurnOffWifiAndTurnOnBluetooth](./rescue-trajectory-analysis-new/03-turn-off-wifi-bluetooth.md): pure hallucination of the model - claim success while seeing the home screen. the same overlay with different values leads to different actions in different rounds, which shows how sensitive the model is to small visual differences in the input image.
- [04 SystemBluetoothTurnOn](./rescue-trajectory-analysis-new/04-system-bluetooth-turn-on.md): pure hallucination in R0, the screenshot shows home screen without the bluetooth icon but the model thoughts "I have successfully turned on the Bluetooth by accessing the quick settings menu. the presence of the Bluetooth icon in the screenshot confirms that it is already enabled". in R1 it clicks on the wrong place and hallucinates success. in R2 it does not directly toggle the bluetooth but opens the bluetooth settings page, which has a side effect of turning on bluetooth, so it succeeds by luck. 
- [05 SystemBluetoothTurnOffVerify](./rescue-trajectory-analysis-new/05-system-bluetooth-turn-off-verify.md): in R0 the agent clicks on the bluetooth tile twice, which toggles it off then on again. in R1 the agent clicks on the bluetooth tile three times, which toggles it off --> success by luck. different initial state as R0 contains state leakage from previous task. --> grounding error: the agent should be able to read the state of the bluetooth tile and adjust its actions accordingly, but it seems to just click without understanding the consequences. 
- [06 SystemWifiTurnOff](./rescue-trajectory-analysis-new/06-system-wifi-turn-off.md): the same swipe scrolling down gesture produced different system responses on different rounds - open quick access panel in R1 but not in R0, which leads to different trajectories and outcomes. the model in R0 then thinks it accidentally open camera (understanding issue), then consumes the step budget trying to close it.


## Always failed tasks

32 tasks failed across all 5 retry rounds. Failures fall into four non-exclusive clusters.

Tasks can belong to multiple clusters (totals exceed 32).

- **Premature** — agent calls `terminate(success)` before the side-effect is verified;
  evaluator scores 0 because the goal was not actually achieved.
- **App not found** — agent enters the app drawer and loops swiping, never locating the target
  app (Simple SMS Messenger, Joplin, Retro Music); hits step budget in the drawer.
- **Compound** — task has two or more sequential legs; agent completes leg 1 but exhausts
  budget or terminates early before finishing later legs.
- **Visual/grounding error** — agent misreads visual state (checkbox, icon, slider position) or
  cannot interact precisely with the screen (canvas drawing, pixel-grid navigation).

| Task | Goal | Premature | App not found | Compound | Visual/grounding Error | Error Description | Suggested Fix |
|------|------|:---------:|:-------------:|:--------:|:----------------:|-------------------|---------------|
| SimpleSmsReply | Reply to a contact with a specific message in Simple SMS Messenger | | x | | | Agent loops swiping in app drawer to locate Simple SMS Messenger app but never finds it, exhausts step budget. | ... |
| SimpleSmsReplyMostRecent | Reply to the most recent SMS with a specific message | | x | | | Same as above — Simple SMS Messenger not found in drawer. | ... |
| SimpleSmsSend | Send a specific message to a phone number via Simple SMS Messenger | | x | | | Same as above — Simple SMS Messenger not found in drawer. | ... |
| SimpleSmsSendClipboardContent | Send clipboard contents as SMS via Simple SMS Messenger | | x | | | Same as above — Simple SMS Messenger not found in drawer. | ... |
| SimpleSmsSendReceivedAddress | Forward an address from a received SMS to another number | | x | | | Cannot locate Simple SMS Messenger. | ... |
| NotesTodoItemCount | Count to-dos in a specific folder in Joplin | | | | x | Need to click on "Health" folder but agent repeatedly clicks on "Home" folder instead. | ... |
| RetroPlaylistDuration | Create a playlist in Retro Music with total duration in a target range | | x | x | | Retro Music not found in drawer; multi-step playlist creation (add songs, check duration, adjust) exceeds budget even when app is reached. | ... |
| CameraTakePhoto | Take one photo | x | | | | Agent calls `terminate(success)` immediately after tapping the shutter without waiting for the photo to be saved and verified. | ... |
| CameraTakeVideo | Take one video | x | | | | Same premature termination pattern — stops before video save is confirmed. | ... |
| OsmAndTrack | Save a track with 4 ordered waypoints in OsmAnd | x | | x | | Agent terminates after adding fewer than 4 waypoints; the multi-waypoint flow (open map → long-press → repeat × 4 → save) overruns the step budget. | ... |
| ExpenseAddMultipleFromGallery | Add expenses from an image in Gallery to the Expense app | x | | x | | Terminates after entering only a subset of expenses; reading multiple items from an image and entering them one-by-one overruns the budget. | ... |
| ExpenseAddMultipleFromMarkor | Add expenses listed in a Markor file to the Expense app | x | | x | | Same — partial entry then premature termination; cross-app reading and repeated form submission overruns the budget. | ... |
| MarkorCreateNoteAndSms | Create a note in Markor and share its content via Simple SMS Messenger | | x | x | | Simple SMS Messenger not found for the share leg; even when Markor note is created successfully, the SMS step fails. | ... |
| MarkorAddNoteHeader | Add a Markdown header to a note in Markor | | | x | | Agent navigates to the note but fails to insert the header syntax before the step budget is exhausted. | ... |
| MarkorChangeNoteContent | Replace the content of a note in Markor with new text | | | x | | Agent opens the note but cannot complete select-all → replace within the step budget. | ... |
| MarkorMergeNotes | Merge two notes into one file in Markor | | | x | | Reading content from the source note and appending it to the destination requires too many steps; budget exhausted mid-task. | ... |
| MarkorTranscribeVideo | Transcribe a video using VLC and save the transcript as a Markor note | | x | x | | VLC or Simple SMS Messenger not found; four-leg task (open VLC → watch → type transcript → save in Markor) far exceeds the step budget. | ... |
| RecipeAddMultipleRecipesFromImage | Add all recipes from an image to the Broccoli recipe app | x | | x | | Adds a partial set of recipes then calls `terminate(success)`; parsing multiple recipes from an image and entering each one individually overruns the budget. | ... |
| RecipeAddMultipleRecipesFromMarkor | Add recipes from a text file in Markor to Broccoli | x | | x | | Same pattern — partial entries, early termination; cross-app read loop exhausts the budget. | ... |
| RecipeAddMultipleRecipesFromMarkor2 | Add filtered recipes from a Markor file to Broccoli | x | | x | | Agent adds unfiltered or only some matching recipes then terminates early; filtering logic inside a step loop exceeds the budget. | ... |
| RecipeDeleteDuplicateRecipes2 | Delete duplicate recipes in Broccoli, keeping one copy each | x | | x | | Deletes a subset of duplicates, then calls `terminate(success)` before the full deduplication pass is complete. | ... |
| RecipeDeleteDuplicateRecipes3 | Delete duplicate recipes in Broccoli, keeping one copy each | x | | x | | Same as above — partial deletion followed by premature success claim. | ... |
| RecipeDeleteMultipleRecipesWithConstraint | Delete Broccoli recipes that contain a specific ingredient in directions | x | | x | x | Agent misidentifies which recipes match the ingredient constraint (visual/grounding error) and terminates before all qualifying recipes are deleted. | ... |
| SimpleCalendarEventsInNextWeek | List all events in the next calendar week (Mon–Sun) in Simple Calendar Pro | | | x | | Agent struggles with the Mon–Sun week boundary and spends most of the budget navigating; terminates without returning a complete list. | ... |
| SystemBrightnessMin | Set screen brightness to its minimum value | x | | | x | Agent cannot reliably detect the minimum slider position and terminates claiming success while brightness is still above minimum. | ... |
| SystemCopyToClipboard | Copy a specific string to the clipboard | x | | | | Agent selects partial text or the wrong element, then calls `terminate(success)` before the correct string is in the clipboard. | ... |
| TasksCompletedTasksForDate | List completed tasks for a specific day in the Tasks app | x | | | x | Agent misreads the completed-task list (visual/grounding error) and terminates with an incorrect or incomplete count. | ... |
| SportsTrackerActivitiesOnDate | List activity types performed on a specific date in OpenTracks | x | | | x | Agent misidentifies activity entries for the target date and terminates with a wrong or incomplete list. | ... |
| SportsTrackerTotalDistanceForCategoryOverInterval | Sum total distance for a sport category over a date range in OpenTracks | x | | | x | Agent cannot accurately read and accumulate distance values across multiple entries; terminates with an incorrect total. | ... |
| BrowserDraw | Open task.html in Chrome and draw the requested shape on the canvas | x | | | x | Agent cannot interact precisely with the HTML canvas (tap coordinates map incorrectly); terminates claiming the shape is drawn when it is not. | ... |
| BrowserMaze | Open task.html in Chrome and navigate a pixel-grid maze to the exit | | | | x | Agent cannot parse the pixel-grid walls and path; navigates into walls or circles indefinitely without reaching the exit. | ... |
| BrowserMultiply | Click a button 5 times in Chrome, record each number shown, enter their product | | | x | x | Agent loses track of intermediate numbers across button clicks (visual/grounding error) and cannot compute or enter the correct product. | ... |
| **Total** | | **17** | **9** | **18** | **8** | | |

**Finding** 
- **Simple SMS Messenger app-drawer failure (6 tasks):** `SimpleSmsReply`, `SimpleSmsReplyMostRecent`, `SimpleSmsSend`, `SimpleSmsSendClipboardContent`, `SimpleSmsSendReceivedAddress`, and `MarkorCreateNoteAndSms` all fail for the same reason: by the last step the model is still issuing repeated `swipe-up` actions in the app drawer trying to find "Simple SMS Messenger" and never reaches the app. For `MarkorCreateNoteAndSms`, leg 1 (create Markor note) typically succeeds, but leg 2 (share via SMS) hits the same blocker.
- 


**Thoughts**
- Many failures are due to agent not being aware of it stucking in a loop (e.g. app drawer swiping, repeatedly clicking the wrong folder in Joplin, ...). One reason might be the agent only gets history of the last step, so it doesn't have the full context of the previous steps to realize it's repeating. Another reason might be the model's temperature is set to 0, so it may be more prone to getting stuck in loops without the randomness to break out.
- The model DOES hallucinate and is sensitive to small visual differences(see [`TurnOffWifiAndTurnOnBluetooth/`](../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107_reformatted/TurnOffWifiAndTurnOnBluetooth/))
