# 13 — RetroPlayingQueue

## Quick links

- **Goal:** *"Add the following songs, in order, City of Stars, Dreamer's Awake, Moonlight Sonata, Echoes of Silence, Forever Young to my playing queue in Retro Music."*
- **History:** F → S (rescued at R1)
- **Step budget:** 30 (`max_n_steps`)
- **Evaluator:** [`RetroPlayingQueue`](../../MARS-Voyager/androidworld/android_world/task_evals/single/retro_music.py#L190) — checks Retro Music's playing queue contains the 5 specified songs in the specified order.
- **Trajectory folder:** [`RetroPlayingQueue/`](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107_reformatted/RetroPlayingQueue/)
- **Image folder:** [`images/`](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/RetroPlayingQueue/images/)

## What "success" requires (evaluator)

The Retro Music app's persisted playing-queue state must contain exactly the 5 specified songs in the listed order. Both completeness and order matter.

## What the agent saw at the divergence step

Both rounds executed effectively the same plan: open app drawer → tap Retro Music → tap search → for each of the 5 songs: type name, tap result, tap "add to queue" menu, dismiss. The action sequences are nearly identical for many steps; the divergence is **subtle and cumulative**:

- **Step 4** (search icon tap): R0 `click [79, 97]`, R1 `click [79, 96]` — 1 pixel apart.
- **Steps 5-7** (City of Stars): both rounds same coordinates, both succeed.
- **Steps 9-11** (Dreamer's Awake): R0 typed once and clicked an item; R1 typed twice (second type after a clear) before clicking. Different intermediate state.
- **Steps 17-19** (Echoes of Silence): R0 entered a `type → click → type` loop and never moved past this song.
- R0 reached step 26 still trying to add the 4th song; trajectory ended without all 5 added in correct order.
- R1 completed all 5 songs in 28 steps and terminated.

Because both rounds went through nearly identical UIs and made nearly identical decisions, isolating "the divergence step" is harder here than for other tasks. The most concrete observation: **the same search-result-tap coordinates produced different downstream UI states across rounds**, suggesting that the search results page rendered slightly differently (different scroll position, different highlighted item, different render timing) between rounds, and small layout differences accumulated into a bigger trajectory divergence by the time the 4th–5th song was being processed.

## What actually happened

A surface-level explanation — that the 1px difference at the search-icon tap is what diverged the trajectories — is plausible but cannot be fully validated from the trajectory alone. What is observable: the same gesture-driven workflow produced different outcomes across rounds because of cumulative tiny layout/timing differences, with the failure surfacing as repeated `type → click → type` loops at songs the agent couldn't successfully add. The 30-step budget was exceeded effectively when the agent stuck on song 4.

The worker log shows `Skipping app snapshot loading` for `code.name.monkey.retromusic` for both rounds; no a11y warnings. Env-side conditions are otherwise comparable.

## Android concepts introduced

- **Cumulative coordinate drift.** When an agent uses pixel coordinates against a UI that re-renders frequently (search-as-you-type, scrolled lists), even sub-pixel layout differences across runs can compound: each tap lands on a slightly different element, the next screen renders slightly differently, the next tap is slightly off again. By the 10th–20th step in such a flow, the two trajectories are visiting different screens.

## Root cause and category

**Proximate cause:** cumulative drift between R0 and R1's trajectories due to small layout/timing differences in Retro Music's search result rendering. R0 stuck in a type-click-type loop on the 4th song; R1 completed all 5.

**Upstream environmental cause:** combination of pixel-level rendering fluctuation (Cat 5) and the fact that the agent's coordinate-grounded plan has no "did the action achieve what I expected?" check before proceeding (Cat 6 / agent design).

**Categories:** **Cat 5 (cumulative pixel drift)** + **Cat 6 (agent doesn't verify outcomes between sub-tasks).**

**Verdict:** **mostly agent-side — env mitigation marginal.** Pixel-level fluctuations in third-party apps' search UIs are hard to pin down to a single env-side fix. The agent's own resilience (verify after each song-add, use a11y tree to confirm queue contents) is the better lever.

## Suggested fix

1. **Have the agent verify each song was added before proceeding** to the next. The current pattern is "type → click → click → next song"; adding "verify queue contents now contains N items" between songs would catch failures like R0's stuck loop early.
2. **Use a11y tree for result selection** instead of pixel-coordinate clicks. The a11y tree exposes the search results as named elements; tapping by content-description rather than coordinates removes the cumulative drift problem.
3. Cleaning the env init (Cat 1 fix) is unlikely to help this task specifically since the failure is mid-trajectory, not at step 0.
