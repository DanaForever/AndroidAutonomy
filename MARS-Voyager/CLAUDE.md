# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MARS-Voyager is an evaluation framework for **UI-Voyager**, a self-evolving mobile GUI agent. It evaluates VLM models on the AndroidWorld benchmark (116 tasks across 20 Android apps). The framework supports multi-worker parallel evaluation using Android emulators and an OpenAI-compatible LLM API (typically served by vLLM).

## Environment Setup

```bash
# Python deps
pip install -r androidworld/requirements.txt
python3 android_env/setup.py install

# Recommended conda env
conda create -n uivoyager python=3.11
conda activate uivoyager
```

Set `PYTHONPATH` when running scripts manually:
```bash
export PYTHONPATH="$(pwd)/androidworld:$(pwd)/android_env:$PYTHONPATH"
```

## Running Evaluations

**Start vLLM server (on GPU machine):**
```bash
CUDA_VISIBLE_DEVICES=0 python -m vllm.entrypoints.openai.api_server \
  --model MarsXL/UI-Voyager --served-model-name UI-Voyager \
  --host 0.0.0.0 --port 8000 --tensor-parallel-size 1 \
  --max-model-len 200000 --gpu-memory-utilization 0.95
```

**SSH tunnel (if server is remote):**
```bash
ssh -N -L 8000:127.0.0.1:8000 <username>@<server-ip>
```

**Run evaluation (spawns emulators and workers in background):**
```bash
NUM_WORKERS=4 CONFIG_NAME=UI-Voyager MODEL_NAME=UI-Voyager ./run_android_world.sh
```

**Monitor and stop:**
```bash
tail -f eval_results/<MODEL>/logs/<TIMESTAMP>/eval_<MODEL>_<N>workers.log
./stop_android_world.sh eval_results/<MODEL>/logs/<TIMESTAMP>
```

**Run directly without the shell wrapper (single worker for debugging):**
```bash
python test_android_world.py \
  --config androidworld/eval/configs/UI-Voyager.yaml \
  --num_workers 1 --start_port 5556
```

## Key Environment Variables

| Variable | Default | Description |
|---|---|---|
| `NUM_WORKERS` | 1 | Parallel emulator workers |
| `CONFIG_NAME` | `UI-Voyager` | Config file (without `.yaml`) |
| `MODEL_NAME` | `UI-Voyager` | Label for results directory |
| `START_PORT` | 5556 | First emulator console port |
| `AVD_NAME` | `AndroidWorldAvd` | Base Android Virtual Device name |
| `EMULATOR_PATH` | `~/Android/Sdk/emulator/emulator` | Path to emulator binary |
| `ANDROID_AVD_HOME` | `~/.android/avd` | AVD storage directory |

## Architecture

The codebase has three layers:

### 1. `android_env/` — Emulator Control (DeepMind's AndroidEnv)
Low-level Python API for controlling Android emulators via gRPC. Handles screenshots, touch events, and accessibility tree data. Treat as a library dependency — rarely modified.

### 2. `androidworld/` — Task Benchmark (Google's AndroidWorld)
Defines the 116 evaluation tasks, task registry, episode runner, and checkpointer. The custom evaluation code lives in `androidworld/eval/`.

### 3. `androidworld/eval/` — Custom Evaluation Framework

**Agent layer** (`eval/agents/`):
- `base_agent.py`: Abstract `BaseEvalAgent` inheriting from AndroidEnv's agent base class. Defines the `step()` interface.
- `qwen_agent.py`: Concrete `Qwen3VLAgent` — captures screenshot, builds prompt with action history, calls LLM client, parses returned action, executes it. Controls history window (`history_len`) and optional SFT data collection.

**LLM client layer** (`eval/clients/`):
- `base_client.py`: Abstract client interface.
- `openai_client.py`: REST client compatible with vLLM's OpenAI API. Handles image encoding (base64 PNG), retries, and streaming config.

**Runner** (`eval/runner.py`):
- `EvalRunner` class: initializes environment from config, instantiates agent, iterates through the task suite, collects per-task metrics, and writes results.

**Entry points:**
- `run_android_world.sh` — orchestrates everything: copies AVDs for each worker, starts isolated ADB servers and emulators, launches `test_android_world.py` in the background.
- `test_android_world.py` — multiprocessing script that distributes tasks across workers; each worker runs its own `EvalRunner`.
- `stop_android_world.sh` — kills emulators, workers, and ADB servers; cleans up AVD copies.

### Configuration

YAML configs in `androidworld/eval/configs/` (e.g., `UI-Voyager.yaml`) control three sections:
- `env`: emulator paths and ports
- `llm`: vLLM endpoint URL, model name, temperature
- `agent`: prompt template, history length, SFT data directory
- `eval`: task suite, output path, random seed

The shell script copies the selected config to `eval_results/<MODEL>/results/<TIMESTAMP>/config.yaml` and patches `model` and `sft_data_dir` fields before running.

### Multi-worker Port Layout

For `N` workers starting at port `START_PORT` (default 5556):
- Worker `i` gets console port `START_PORT + i*2`, ADB port `START_PORT + i*2 + 1`, gRPC port `8554 + i`, and ADB server port `5037 + i`.
- Each worker gets its own AVD copy named `AndroidWorldAvd_worker_<i>`.

## Output Structure

```
eval_results/
└── <MODEL_NAME>/
    ├── logs/<TIMESTAMP>/
    │   ├── eval_<MODEL>_<N>workers.log   # main log
    │   ├── eval.pid
    │   ├── emulators/                    # per-emulator logs
    │   └── merged_summary/              # aggregated results
    └── results/<TIMESTAMP>/
        ├── config.yaml                  # runtime config snapshot
        └── sft_rollouts/               # SFT training data (if enabled)
```

## Task Step Budgets

`budget = int(10 * complexity)` where `complexity = optimal_steps / 5` (human-measured optimal from `detailed_results.csv`), giving each task **2× the human optimal**.

## Inspecting Trajectories

Use `eval_results/format_trajectory.py` to convert `.jsonl` trajectory files into human-readable text. Run `python3 eval_results/format_trajectory.py --help` for usage.

## Adding a New Agent or Model

1. Add a YAML config in `androidworld/eval/configs/` (copy an existing one).
2. If using a different model architecture, subclass `BaseEvalAgent` in `eval/agents/` and implement `step()`.
3. Register the new agent type in `eval/runner.py` where agents are instantiated.
4. Update `llm.base_url` and `llm.model` in the config to point to the vLLM server.
