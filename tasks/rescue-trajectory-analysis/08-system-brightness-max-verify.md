# 08 — SystemBrightnessMaxVerify

## Quick links

- **Goal:** *"Turn brightness to the max value."*
- **History:** F → S (rescued at R1)
- **Step budget:** 10 (`max_n_steps`)
- **Evaluator:** [`_SystemBrightnessToggle.is_successful`](../../MARS-Voyager/androidworld/android_world/task_evals/single/system.py#L41) — `adb shell settings get system screen_brightness` must equal 255.
- **Setup:** [`SystemBrightnessMaxVerify.initialize_task`](../../MARS-Voyager/androidworld/android_world/task_evals/single/system.py#L80) — calls `adb_utils.set_brightness('max', ...)`. **Brightness is already at max before the agent does anything.**
- **Trajectory folder:** [`SystemBrightnessMaxVerify/`](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107_reformatted/SystemBrightnessMaxVerify/)
- **Image folder:** [`images/`](../../MARS-Voyager/eval_results/UI-Voyager/results/20260426203107/SystemBrightnessMaxVerify/images/)

## What "success" requires (evaluator)

`screen_brightness == 255` at terminate time. Because the precondition already sets brightness to max, **the agent could in principle succeed by simply calling `terminate(success)` immediately** — the eval only inspects the system state, not the trajectory. The "Verify" variant is essentially a free task; the only way to fail is to (a) actually lower the brightness somehow, or (b) burn the entire step budget without reaching a terminate.

## What the agent saw at the divergence step

R0 and R1 are byte-identical for steps 1–3 (same swipes, same hallucinated "I accidentally opened an app" reasoning). They diverge at step 4 — not because of the screenshot, but because **R0's vLLM endpoint became unreachable**:

| Round 0 (FAIL) | Round 1 (PASS) |
|---|---|
| Steps 1-3: same as R1; step 4 onwards: 5 consecutive `Error calling LLM` records (vLLM `connection refused`). Step 10 reached without ever calling terminate. | Steps 1-3: same as R0; step 4 swipes; step 5 `terminate(success)` — within budget. |

**Worker log around R0 step 4–8:**

```
[R0] Request error: HTTPConnectionPool(host='localhost', port=9000): Max retries exceeded
     with url: /v1/chat/completions (Caused by NewConnectionError("...Connection refused"))
[R0] [Worker 0][SystemBrightnessMaxVerify]  Completed step 5.
[R0] Request error: ... Connection refused
[R0] [Worker 0][SystemBrightnessMaxVerify]  Completed step 6.
[R0] Request error: ... Connection refused
[R0] [Worker 0][SystemBrightnessMaxVerify]  Completed step 7.
[R0] Request error: ... Connection refused
[R0] [Worker 0][SystemBrightnessMaxVerify]  Completed step 8.
[R0] [Worker 0][SystemBrightnessMaxVerify]  Completed step 9.
[R0] [Worker 0][SystemBrightnessMaxVerify]  Completed step 10.
```

## What actually happened

R0 burned steps 4–8 to vLLM connection failures (server at `localhost:9000` refused new connections — likely an OOM, restart, or transient network blip on the model server). Each failed call was logged as `Error calling LLM` in the trajectory's History field; the agent had no useful continuation reasoning during those steps. By step 9 the vLLM was back up, but the agent had only 1 step of budget left and produced more confused swiping rather than a terminate. The harness scored max-steps-reached as failure (no terminate signal).

R1 had no vLLM errors. The agent's hallucinated "I accidentally opened an app" loop was the same as R0 through step 3 — but at step 5 it called `terminate(success)`, which the eval scored against the still-max brightness → PASS.

The flip is fully attributable to the vLLM infra flake on R0. The Android env contributed nothing decisive: the same hallucination pattern played out in both rounds, but R1 reached terminate within budget.

## Android concepts introduced

- **Verify-style tasks.** Some AndroidWorld tasks have a `*Verify` variant where the precondition already satisfies the goal. They exist to test that the agent doesn't mess things up — but in practice they are also rescued by simply terminating early. Combined with the eval-side check being a single setting read, these tasks are nearly impossible to fail unless the agent (a) actively breaks the state, or (b) runs out of steps without terminating.

## Root cause and category

**Proximate cause:** vLLM server returned `Connection refused` for steps 5–8 of R0, burning the agent's entire remaining step budget on no-op records.

**Upstream environmental cause:** model-serving infra flake — not an Android-env issue at all. The Android env behaved similarly in both rounds.

**Categories:** **Cat 6 — pure LLM infra flake.** No Cat 1–5 contribution.

**Verdict:** **infra bug — should fix at the vLLM/serving layer, not in the Android harness.** Not an env-side problem. The harness *could* mitigate by catching `Error calling LLM` and not consuming a step (retry the same observation), but that's a harness-design discussion, not an Android-env fix.

## Suggested fix

1. **Make the harness retry on transient LLM errors instead of consuming a step.** If [`Qwen3VLAgent.step`](../../MARS-Voyager/androidworld/eval/agents/qwen_agent.py) gets an HTTP error from the LLM, it should retry the same screenshot/observation a few times with backoff before counting it as a step. This would also rescue the R0 trajectory in [§07 SystemBrightnessMax](07-system-brightness-max.md).
2. **Run the vLLM server with a healthcheck and auto-restart wrapper.** If the server dropped and recovered within a few seconds, a healthcheck-aware client would queue requests until ready.
3. **Independently, the underlying cause of `Connection refused`** (the vLLM server became unreachable mid-run) deserves investigation — was it OOM, GPU OOM, a SIGSEGV restart, or a network blip? The worker log only shows the symptom.
