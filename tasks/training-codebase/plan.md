# Training Codebase for GUI Agent Research

## Context

The repo currently has a working **evaluation** pipeline (android_world via MARS-Voyager, with Qwen3-VL-4B-Instruct as the eval target) but no **training** code. The team's research goal is to iterate on GUI agents — new benchmarks, model architectures, RL losses — which requires owning the training stack.

**What's in the repo today:**
- [`MARS-Voyager/`](../../MARS-Voyager/) — eval harness driving android_world with [`Qwen3VLAgent`](../../MARS-Voyager/androidworld/eval/agents/qwen_agent.py) calling a vLLM server.
- [`MAI-UI/`](../../MAI-UI/), [`UI-Venus/`](../../UI-Venus/), [`MobileWorld/`](../../MobileWorld/) — inference/eval frameworks only. No SFT/RL code, no losses, no optimizers. UI-Venus's [README](../../UI-Venus/README.md) describes a mid-training + online-RL recipe but ships only inference scripts.

**What's missing:** an external training framework, a small SFT data path, a checkpoint round-trip into the existing vLLM eval, and (phase 2) an online-RL loop wrapping android_world.

**Target outcome:** Two milestones — (1) a dummy SFT run on Qwen3-VL-4B that produces a checkpoint scoring on android_world; (2) a working GRPO loop with android_world as the live env, ready as a substrate for the team's research (custom rewards, new losses, new architectures).

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Base model | **Qwen3-VL-4B-Instruct** | Same checkpoint UI-Voyager evaluates ([`androidworld/eval/configs/Qwen3-VL-4B-Instruct.yaml`](../../MARS-Voyager/androidworld/eval/configs/Qwen3-VL-4B-Instruct.yaml)). Trained weights drop directly into the existing vLLM eval. |
| Paradigm | **SFT → online RL** | SFT validates pipeline (tokenizer, chat template, image preprocessing, eval round-trip) and produces a sane RL init / KL reference. Cold-start RL on a 4B base produces near-zero parseable actions and zero gradient signal. Mirrors UI-Venus's mid-training → online-RL recipe at a smaller scale. |
| Compute | **Single node, 4-8 GPUs** | Comfortable for 4B full-param SFT and small-scale GRPO with co-located vLLM rollout. |
| Framework | **verl** | See below. |

### Why verl

- **One stack for both phases.** SFT (`fsdp_sft_trainer`) and multi-turn agentic GRPO/PPO live in the same repo, avoiding a framework migration when phase 2 lands.
- **Multi-turn agent rollouts are first-class.** verl's rollout interface lets us plug a Python env (`reset`/`step`) directly into the trainer, which is exactly the shape of android_world. TRL's GRPOTrainer is single-turn and would require a custom rollout loop.
- **Community traction in agent-RL is strongest.** Recent open agent-RL work (SkyRL, rLLM, Search-R1, ReSearch, GUI-agent RL repros in the UI-TARS lineage) ships on verl. Reading and reproducing those papers is materially easier on the same stack.
- **VLM support matches the alternatives at the SFT layer** and exceeds them at the RL layer for full-trajectory rollouts with per-step images.
- **Cost we accept:** heavier YAML config, Ray cluster, and a 1-4 week lag behind TRL when brand-new Qwen models drop (verl needs vLLM support + verl-side glue to land first). Acceptable because the day-one-on-new-Qwen use case is rare and TRL's SFT lead disappears once we move to RL (vLLM bottleneck hits everyone equally).

## Plan

### Phase 1 — Stand up verl + SFT a dummy

**Goal:** trained Qwen3-VL-4B checkpoint that loads in the existing UI-Voyager vLLM eval and beats the off-the-shelf baseline by a non-zero margin on a small android_world subset.

1. **Vendor verl into the repo** at [`training/verl/`](../../training/verl/) (git submodule or pinned clone). Document the commit pin.
2. **Build a small SFT dataset.** See sub-plans:
   - [`sft-data/plan.md`](./sft-data/plan.md) — `sft_v0`, the breadth-first build that mines all existing successful rollouts (2,250 steps over 97 tasks). ✅ done. Validates the build pipeline but spreads demos too thinly (~23 steps/task) to overfit any single task.
   - [`sft-data/overfit-10-tasks.html`](./sft-data/overfit-10-tasks.html) — `sft_v0.1`, the depth-first build. Picks 10 tasks, generates ~30 param-varied rollouts per task via `n_task_combinations=30` in [`demos_overfit10.yaml`](../../MARS-Voyager/androidworld/eval/configs/demos_overfit10.yaml), rebuilds the parquet, and runs a 3-seed base-vs-SFT eval (mean success rate) via [`eval_overfit10_base.yaml`](../../MARS-Voyager/androidworld/eval/configs/eval_overfit10_base.yaml) and [`eval_overfit10_sft.yaml`](../../MARS-Voyager/androidworld/eval/configs/eval_overfit10_sft.yaml). **This is the dataset Phase 1 SFT actually trains on.**
   - Optionally mix in a public GUI dataset (AITZ, AndroidControl, GUIAct) for breadth — deferred until after the overfit signal is observed.
3. **Configure verl SFT.** Start from verl's `examples/sft/` Qwen-VL recipe. Match [`qwen_agent.py`](../../MARS-Voyager/androidworld/eval/agents/qwen_agent.py)'s chat template and action grammar exactly so trained outputs parse downstream.
4. **Eval round-trip.** Serve the trained checkpoint with the same vLLM command UI-Voyager uses. Run a small android_world subset (~10 tasks) via [`test_android_world.py`](../../MARS-Voyager/test_android_world.py). Confirm action format, no template drift, and a measurable score.
5. **Deliverable:** [`training/verl/`](../../training/verl/), [`training/configs/sft_qwen3vl_4b.yaml`](../../training/configs/sft_qwen3vl_4b.yaml), [`training/data/build_sft_from_trajectories.py`](../../training/data/build_sft_from_trajectories.py), a [`training/README.md`](../../training/README.md) with the run command, and one logged training + eval run.

**Critical files to author or modify:**
- [`training/data/build_sft_from_trajectories.py`](../../training/data/build_sft_from_trajectories.py) (new) — reuses prompt builder logic from [`MARS-Voyager/androidworld/eval/agents/qwen_agent.py`](../../MARS-Voyager/androidworld/eval/agents/qwen_agent.py).
- [`training/configs/sft_qwen3vl_4b.yaml`](../../training/configs/sft_qwen3vl_4b.yaml) (new) — verl FSDP SFT config.
- [`training/scripts/run_sft.sh`](../../training/scripts/run_sft.sh) (new).
- [`training/README.md`](../../training/README.md) (new).

### Phase 2 — Online RL with android_world in the loop

**Goal:** GRPO trainer driving Qwen3-VL-4B through full android_world trajectories, with task success as the trajectory-level reward and the SFT checkpoint as both init and KL reference.

1. **Wrap android_world as a verl rollout env.** Implement verl's agent-rollout interface around [`MARS-Voyager/androidworld/android_world/`](../../MARS-Voyager/androidworld/android_world/). The wrapper exposes `reset(task)`, `step(action) -> (obs, done, info)`, and produces the same `(image, prompt)` observation [`qwen_agent.py`](../../MARS-Voyager/androidworld/eval/agents/qwen_agent.py) already builds. Reuse [`episode_runner.py`](../../MARS-Voyager/androidworld/android_world/episode_runner.py) and [`env_launcher.py`](../../MARS-Voyager/androidworld/android_world/env/env_launcher.py).
2. **Rollout infrastructure.** Co-locate vLLM rollout workers with one or more emulators. Decide on emulator parallelism (likely 1 emulator per rollout worker, fewer than 8 to leave headroom for the FSDP trainer).
3. **Reward.** v0 = task success (binary, end-of-trajectory) using android_world's existing success checkers. v1 plug-in points: per-step format reward, grounding reward, intermediate-state rewards.
4. **GRPO config.** SFT checkpoint as init and KL reference. Group size, KL coefficient, clip ratio from verl's GRPO defaults — tune after first stable run.
5. **Deliverable:** [`training/envs/android_world_env.py`](../../training/envs/android_world_env.py), [`training/configs/grpo_qwen3vl_4b.yaml`](../../training/configs/grpo_qwen3vl_4b.yaml), a logged GRPO run, and a side-by-side android_world score: SFT vs SFT+GRPO.

**Critical files to author:**
- [`training/envs/android_world_env.py`](../../training/envs/android_world_env.py) (new) — verl rollout wrapper around android_world.
- [`training/rewards/task_success.py`](../../training/rewards/task_success.py) (new) — v0 reward.
- [`training/configs/grpo_qwen3vl_4b.yaml`](../../training/configs/grpo_qwen3vl_4b.yaml) (new).
- [`training/scripts/run_grpo.sh`](../../training/scripts/run_grpo.sh) (new).

### Phase 3 — Research plug-in points

Once phases 1 and 2 are stable, the codebase exposes seams for the research agenda:

- **New RL losses.** verl's loss is configurable; subclass the GRPO loss in [`training/losses/`](../../training/losses/).
- **New rewards.** Drop new modules into [`training/rewards/`](../../training/rewards/) and reference from the GRPO config.
- **New model architectures.** verl's actor is a HF `transformers` model — swap in custom `Qwen3VLForXxx` subclasses under [`training/models/`](../../training/models/).
- **New benchmarks.** Add env wrappers under [`training/envs/`](../../training/envs/) mirroring the android_world wrapper.

## Verification

End-to-end checks for phase 1 (in order):

1. **Data sanity:** [`build_sft_from_trajectories.py`](../../training/data/build_sft_from_trajectories.py) produces N samples; spot-check 5 samples for correct image paths, prompt format matching [`qwen_agent.py`](../../MARS-Voyager/androidworld/eval/agents/qwen_agent.py), and parseable target action.
2. **SFT smoke:** verl SFT runs for ~100 steps on the 4-8 GPU node without OOM, loss decreases monotonically over the first epoch.
3. **Checkpoint round-trip:** trained checkpoint loads in vLLM with the same launch command as the off-the-shelf model. Single-shot prompt produces a parseable action string.
4. **android_world eval:** [`test_android_world.py`](../../MARS-Voyager/test_android_world.py) `--config <pointing at trained checkpoint>` completes ≥10 tasks; score is logged and is non-zero.
5. **Regression guard:** off-the-shelf Qwen3-VL-4B-Instruct still scores its known baseline on the same 10-task subset (sanity check that we haven't broken eval).

Phase 2 verification adds: emulator + vLLM + trainer co-existence on one node without resource contention; a stable GRPO run for ≥500 steps with reward trending up; final SFT+GRPO checkpoint scores higher than SFT-only on the same android_world subset.

## Open questions to resolve in execution

- Which Qwen3-VL-4B-Instruct revision matches what's currently served in the eval pipeline? (Pin the same HF revision for training.)
- Volume of usable SFT data from existing trajectories — may need to supplement with a public GUI dataset.
- vLLM version compatibility between verl's rollout pin and the eval server's pin (avoid two incompatible vLLMs in the same env).
