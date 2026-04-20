# UI-Voyager Setup Guide

This guide covers the setup and execution for UI-Voyager distributed evaluation across a server and local machine.

## Architecture Overview

- **Server**: Runs the vLLM API server hosting the UI-Voyager model
- **Local Machine**: Runs the Android emulator and evaluation tasks that connect to the server

---

## Part 1: Server Setup (vLLM API Server)

### Step 1: Create vLLM Environment

Create a new conda environment for vLLM:

```bash
conda create -n vllm python=3.10
conda activate vllm
```

### Step 2: Install Dependencies

Install vLLM and the latest Hugging Face Transformers:

```bash
pip install vllm
pip install git+https://github.com/huggingface/transformers.git
```

### Step 3: Start the vLLM API Server

Launch the OpenAI-compatible API server with the UI-Voyager model:

```bash
CUDA_VISIBLE_DEVICES=0 python -m vllm.entrypoints.openai.api_server \
  --model MarsXL/UI-Voyager \
  --served-model-name UI-Voyager \
  --host 0.0.0.0 \
  --port 8000 \
  --tensor-parallel-size 1 \
  --max-model-len 200000 \
  --gpu-memory-utilization 0.95
```

**Parameters explanation:**
- `--model MarsXL/UI-Voyager`: The model to serve
- `--served-model-name UI-Voyager`: Name used by clients to request the model
- `--host 0.0.0.0`: Listen on all network interfaces
- `--port 8000`: API server port
- `--tensor-parallel-size 1`: Number of GPUs for tensor parallelism
- `--max-model-len 200000`: Maximum context length
- `--gpu-memory-utilization 0.95`: GPU memory utilization ratio

Once started, the API server will be accessible at `http://<server-ip>:8000`

---

## Part 2: Local Machine Setup

### Prerequisites

Ensure you have the following installed:
- Android SDK with emulator tools
- Python 3.8+
- Git

### Step 1: Prepare Android Emulator (AVD)

You must have an Android Virtual Device (AVD) available. Follow the [AndroidWorld installation guide](https://github.com/google-research/android_world).

**Default assumptions:**
- AVD_NAME: `AndroidWorldAvd`
- Emulator path: `$HOME/Android/Sdk/emulator/emulator`
- AVD storage: `$HOME/.android/avd`

If your setup differs, override these variables when running the evaluation script.

### Step 2: Create UI-Voyager Environment

Create a new conda environment for the evaluation:

```bash
conda create -n uivoyager python=3.11
conda activate uivoyager
```

### Step 3: Install Dependencies

```bash
pip install -r androidworld/requirements.txt
python3 android_env/setup.py install
```

### Step 4: Configure the Evaluation

Edit the config file: `androidworld/eval/configs/UI-Voyager.yaml`

Key sections to verify/update:

- **`env.*`**: Emulator paths and ports
  - `emulator_path`: Path to emulator binary
  - `adb_path`: Path to ADB
  - `emulator_port`: AVD emulator port
  
- **`llm.*`**: LLM endpoint configuration
  - `api_key`: OpenAI API key (can be dummy string for local server)
  - `base_url`: Server address (e.g., `http://<server-ip>:8000/v1`)
  - `model_name`: `UI-Voyager` (must match `--served-model-name` from server)

- **`agent.*`**: Agent parameters
  - `prompt_name`: Prompt template name
  - `action_loop_params`: Action generation parameters
  - `history_length`: Context history length
  - `sft_data_dir`: Directory for SFT rollouts

- **`eval.*`**: Evaluation suite
  - `task_suite`: Which AndroidWorld tasks to run
  - `output_path`: Where to save results

### Step 5: Run Evaluation

#### Single Worker (for testing):

```bash
EMULATOR_PATH="$HOME/Android/Sdk/emulator/emulator" \
ANDROID_AVD_HOME="$HOME/.android/avd" \
NUM_WORKERS=1 CONFIG_NAME=UI-Voyager MODEL_NAME=UI-Voyager \
./run_android_world.sh
```

#### Parallel Evaluation (4 workers):

```bash
EMULATOR_PATH="$HOME/Android/Sdk/emulator/emulator" \
ANDROID_AVD_HOME="$HOME/.android/avd" \
NUM_WORKERS=4 CONFIG_NAME=UI-Voyager MODEL_NAME=UI-Voyager \
./run_android_world.sh
```

**Environment variables:**
- `NUM_WORKERS`: Number of parallel evaluation workers
- `EMULATOR_PATH`: Path to Android emulator binary
- `ANDROID_AVD_HOME`: Directory containing AVD definitions
- `CONFIG_NAME`: Configuration file name (without `.yaml`)
- `MODEL_NAME`: Model identifier for results organization

### Step 6: Monitor and Stop Evaluation

After launching, the script will output:
- Main process ID
- Log file path
- Output artifacts directory

#### View Logs:

```bash
tail -f /path/to/eval_results/<MODEL_NAME>/logs/<TIMESTAMP>/eval.log
```

#### Stop Running Evaluation:

Using the log directory path (recommended):

```bash
./stop_android_world.sh /path/to/eval_results/<MODEL_NAME>/logs/<TIMESTAMP>
```

Or manually:

```bash
kill "$(cat eval_results/<MODEL_NAME>/logs/<TIMESTAMP>/eval.pid)"
```

---

## Output Structure

After evaluation completes, results are organized as:

```
eval_results/
└── <MODEL_NAME>/
    ├── logs/
    │   └── <TIMESTAMP>/
    │       ├── eval.log          # Main evaluation log
    │       ├── eval.pid          # Process ID
    │       └── merged_summary/   # Aggregated results
    └── results/
        └── <TIMESTAMP>/
            ├── config.yaml       # Runtime configuration
            └── sft_rollouts/     # SFT data (if enabled)
```

---

## Troubleshooting

### Connection Issues
- Verify the server is running: `curl http://<server-ip>:8000/v1/models`
- Check firewall allows port 8000
- Ensure `base_url` in config matches server address

### Out of Memory
- Reduce `--max-model-len` on server
- Decrease `NUM_WORKERS` on local machine
- Reduce `--gpu-memory-utilization`

### AVD Issues
- Ensure AVD is created: `emulator -list-avds`
- Check emulator path is correct
- Verify `$ANDROID_AVD_HOME` directory exists

### Python Dependencies
- Install missing packages: `pip install -r androidworld/requirements.txt`
- Check Python version compatibility (3.8+)

---

## Quick Reference

| Task | Command |
|------|---------|
| Start server | `CUDA_VISIBLE_DEVICES=0 python -m vllm.entrypoints.openai.api_server --model MarsXL/UI-Voyager --served-model-name UI-Voyager --host 0.0.0.0 --port 8000 --tensor-parallel-size 1 --max-model-len 200000 --gpu-memory-utilization 0.95` |
| Run evaluation (1 worker) | `EMULATOR_PATH="$HOME/Android/Sdk/emulator/emulator" ANDROID_AVD_HOME="$HOME/.android/avd" NUM_WORKERS=1 CONFIG_NAME=UI-Voyager MODEL_NAME=UI-Voyager ./run_android_world.sh` |
| Run evaluation (4 workers) | `EMULATOR_PATH="$HOME/Android/Sdk/emulator/emulator" ANDROID_AVD_HOME="$HOME/.android/avd" NUM_WORKERS=4 CONFIG_NAME=UI-Voyager MODEL_NAME=UI-Voyager ./run_android_world.sh` |
| Stop evaluation | `./stop_android_world.sh /path/to/eval_results/<MODEL_NAME>/logs/<TIMESTAMP>` |

---

## Additional Resources

- [UI-Voyager Paper](https://arxiv.org/pdf/2603.24533)
- [Hugging Face Model](https://huggingface.co/MarsXL/UI-Voyager)
- [AndroidWorld Documentation](https://github.com/google-research/android_world)
- [android_env Setup](https://github.com/google-deepmind/android_env)
