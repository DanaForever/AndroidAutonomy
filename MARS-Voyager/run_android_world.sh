#!/bin/bash

# Android World Evaluation Script
# Evaluates VLM model performance on the Android World benchmark.
# Single-dimension repeat loop (no seed specification).
#
# Usage:
#   ./run_android_world.sh
#   NUM_WORKERS=16 CONFIG_NAME=Qwen3-VL-4B-Instruct ./run_android_world.sh
#
# Management:
#   tail -f logs/eval_*.log
#   kill $(cat logs/eval.pid)


# ==================== Basic Config ====================

CONFIG_NAME="${CONFIG_NAME:-UI-Voyager}"
MODEL_NAME="${MODEL_NAME:-UI-Voyager}"
NUM_WORKERS="${NUM_WORKERS:-1}"
START_PORT="${START_PORT:-5556}"
AVD_NAME="${AVD_NAME:-AndroidWorldAvd}"
N_REPEATS="${N_REPEATS:-1}"
TIMESTAMP=$(date +"%Y%m%d%H%M%S")
LOG_LEVEL="${LOG_LEVEL:-INFO}"
RETRY_FAILED_TASKS="${RETRY_FAILED_TASKS:-1}"
FAILED_TASK_MAX_STREAK="${FAILED_TASK_MAX_STREAK:-5}"
TASK_RANDOM_SEED="${TASK_RANDOM_SEED:-}"

# ==================== Path Config ====================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}"
cd "${PROJECT_ROOT}" || exit 1

ANDROID_WORLD_PATH="${PROJECT_ROOT}/androidworld"
CONFIG_FILE="${ANDROID_WORLD_PATH}/eval/configs/${CONFIG_NAME}.yaml"

LOG_DIR="${PROJECT_ROOT}/eval_results/${MODEL_NAME}/logs/${TIMESTAMP}"
MAIN_LOG="${LOG_DIR}/eval_${MODEL_NAME}_${NUM_WORKERS}workers.log"
PID_FILE="${LOG_DIR}/eval.pid"
EMU_PID_FILE="${LOG_DIR}/emulator_pids.txt"
AVD_COPIES_FILE="${LOG_DIR}/avd_copies.txt"
RETRY_STATE_FILE="${LOG_DIR}/retry_summary.json"
RETRY_TASK_DIR="${LOG_DIR}/retry_task_lists"

OUTPUT_PATH="${PROJECT_ROOT}/eval_results/${MODEL_NAME}/results/${TIMESTAMP}"

ANDROID_ENV_PATH="${PROJECT_ROOT}/android_env"

export PYTHONPATH="${ANDROID_WORLD_PATH}:${ANDROID_ENV_PATH}:${PYTHONPATH}"

# ==================== Emulator Config ====================

# EMULATOR_PATH="${EMULATOR_PATH:-/root/android/emulator/emulator}"
# ADB_PATH="${ADB_PATH:-$HOME/android/platform-tools/adb}"
# export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-/root/android}"
# export ANDROID_AVD_HOME="${ANDROID_AVD_HOME:-/root/android/avd}"

EMULATOR_PATH="${EMULATOR_PATH:-$HOME/Android/Sdk/emulator/emulator}"
ADB_PATH="${ADB_PATH:-$HOME/Android/Sdk/platform-tools/adb}"
export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}"
export ANDROID_AVD_HOME="${ANDROID_AVD_HOME:-$HOME/.android/avd}"

EMU_MEMORY=8192
EMU_CORES=4
EMU_WAIT_TIME=90
EMU_START_MAX_RETRIES=3

ADB_SERVER_START_PORT="${ADB_SERVER_START_PORT:-5037}"

# ==================== Helper Functions ====================

log() { echo "[$(date '+%H:%M:%S')] $*"; }

die() { log "Error: $*"; exit 1; }

reap_zombies() {
    local zombie_count=$(ps aux | awk '{if ($8 ~ /Z/) print $2}' | wc -l)
    if [[ $zombie_count -gt 100 ]]; then
        log "[WARNING] Found $zombie_count zombie processes, attempting to reap..."
        wait 2>/dev/null || true
        for ppid in $(ps aux | awk '{if ($8 ~ /Z/) print $3}' | sort -u); do
            [[ -n "$ppid" && "$ppid" != "1" ]] && kill -SIGCHLD "$ppid" 2>/dev/null || true
        done
        sleep 1
        local new_count=$(ps aux | awk '{if ($8 ~ /Z/) print $2}' | wc -l)
        log "[INFO] Zombie count: before=$zombie_count, after=$new_count"
    fi
}

# ==================== AVD Management ====================

create_avd_copy() {
    local worker_id=$1
    local target_avd="${AVD_NAME}_worker_${worker_id}"
    local source_dir="$ANDROID_AVD_HOME/${AVD_NAME}.avd"
    local target_dir="$ANDROID_AVD_HOME/${target_avd}.avd"
    local source_ini="$ANDROID_AVD_HOME/${AVD_NAME}.ini"
    local target_ini="$ANDROID_AVD_HOME/${target_avd}.ini"

    if [[ -d "$target_dir" && -f "$target_ini" ]]; then
        log "  [SKIP] AVD copy already exists: $target_avd"
        echo "$target_avd" >> "$AVD_COPIES_FILE"
        return 0
    fi

    rm -rf "$target_dir" "$target_ini"

    log "  [CREATE] AVD copy: $target_avd"
    cp -r "$source_dir" "$target_dir"
    cp "$source_ini" "$target_ini"
    sed -i "s|path=.*|path=${target_dir}|g" "$target_ini"
    sed -i "s|path.rel=.*|path.rel=avd/${target_avd}.avd|g" "$target_ini"
    [[ -f "$target_dir/hardware-qemu.ini" ]] && \
        sed -i "s|${AVD_NAME}|${target_avd}|g" "$target_dir/hardware-qemu.ini"

    echo "$target_avd" >> "$AVD_COPIES_FILE"
}

cleanup_avd_copies() {
    [[ ! -f "$AVD_COPIES_FILE" ]] && return
    log "Cleaning up AVD copies..."
    while read -r avd_name; do
        [[ "$avd_name" == *"_worker_"* ]] || continue
        rm -rf "$ANDROID_AVD_HOME/${avd_name}.avd" "$ANDROID_AVD_HOME/${avd_name}.ini"
        log "  [DELETE] $avd_name"
    done < "$AVD_COPIES_FILE"
    rm -f "$AVD_COPIES_FILE"
}

# ==================== Emulator Management ====================

kill_pids() {
    local pid_file=$1
    [[ ! -f "$pid_file" ]] && return
    while read -r pid; do
        [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
    done < "$pid_file"
    sleep 3
    while read -r pid; do
        [[ -n "$pid" ]] && kill -9 "$pid" 2>/dev/null || true
    done < "$pid_file"
}

start_adb_server() {
    local worker_id=$1
    local adb_server_port=$((ADB_SERVER_START_PORT + worker_id))
    timeout 10 "$ADB_PATH" -P "$adb_server_port" kill-server 2>/dev/null || true
    sleep 1
    timeout 15 "$ADB_PATH" -P "$adb_server_port" start-server 2>/dev/null || {
        log "  [WARN] Worker $worker_id: ADB server start timed out on port $adb_server_port"
        return 1
    }
    log "  [ADB] Worker $worker_id: ADB server started on port $adb_server_port"
}

stop_all_adb_servers() {
    log "Stopping all ADB servers..."
    for i in $(seq 0 $((NUM_WORKERS - 1))); do
        local adb_server_port=$((ADB_SERVER_START_PORT + i))
        timeout 10 "$ADB_PATH" -P "$adb_server_port" kill-server 2>/dev/null &
    done
    timeout 10 "$ADB_PATH" kill-server 2>/dev/null &
    local wait_start=$SECONDS
    while [[ $((SECONDS - wait_start)) -lt 30 ]] && jobs -r | grep -q .; do
        sleep 1
    done
    pkill -9 -f "adb.*kill-server" 2>/dev/null || true
    log "All ADB servers stopped"
}

cleanup() {
    log "Cleaning up resources..."
    reap_zombies
    kill_pids "$EMU_PID_FILE"
    pkill -f "emulator.*${AVD_NAME}" 2>/dev/null || true
    pkill -f "python.*test_android_world.py" 2>/dev/null || true
    sleep 2
    pkill -9 -f "python.*test_android_world.py" 2>/dev/null || true
    pkill -f "qemu-system-x86" 2>/dev/null || true
    sleep 1
    pkill -9 -f "qemu-system-x86" 2>/dev/null || true
    stop_all_adb_servers
    cleanup_avd_copies
    rm -f "$EMU_PID_FILE"
    wait 2>/dev/null || true
    reap_zombies
    log "Cleanup completed"
}

start_emulators() {
    log "Starting $NUM_WORKERS emulators..."
    local failed=0

    log "Creating AVD copies..."
    rm -f "$AVD_COPIES_FILE"
    for i in $(seq 0 $((NUM_WORKERS - 1))); do
        create_avd_copy "$i" || failed=$((failed + 1))
    done
    [[ $failed -gt 0 ]] && { log "Failed to create AVD copies: $failed"; return $failed; }

    log "Starting independent ADB servers..."
    for i in $(seq 0 $((NUM_WORKERS - 1))); do
        start_adb_server "$i"
    done
    sleep 2

    failed=0
    for i in $(seq 0 $((NUM_WORKERS - 1))); do
        local console_port=$((START_PORT + i * 2))
        local adb_port=$((console_port + 1))
        local grpc_port=$((8554 + i))
        local adb_server_port=$((ADB_SERVER_START_PORT + i))
        local worker_avd="${AVD_NAME}_worker_${i}"
        local emu_log="${LOG_DIR}/emulators/emu_${i}_port_${console_port}.log"

        local started=false
        for attempt in $(seq 1 $EMU_START_MAX_RETRIES); do
            ANDROID_ADB_SERVER_PORT="$adb_server_port" "$EMULATOR_PATH" \
                -adb-path "$ADB_PATH" \
                -gpu host \
                -no-audio -no-skin \
                -show-kernel -verbose \
                -avd "$worker_avd" \
                -memory $EMU_MEMORY \
                -cores $EMU_CORES \
                -grpc "$grpc_port" \
                -ports "${console_port},${adb_port}" \
                -snapshot default_boot \
                -feature AllowSnapshotMigration,MigratableSnapshotSave \
                > "$emu_log" 2>&1 &

            local emu_pid=$!
            echo "$emu_pid" >> "$EMU_PID_FILE"
            sleep 5

            if kill -0 "$emu_pid" 2>/dev/null; then
                log "  [OK] Worker $i: avd=$worker_avd, ports=($console_port,$adb_port,$grpc_port), adb_server=$adb_server_port, pid=$emu_pid"
                started=true
                break
            else
                log "  [FAIL] Worker $i failed to start (attempt $attempt/$EMU_START_MAX_RETRIES)"
                # [[ -f "$emu_log" ]] && tail -3 "$emu_log" | sed 's/^/    /'
                [[ -f "$emu_log" ]] && { echo "---- emulator log ($emu_log) ----"; tail -50 "$emu_log"; echo "-------------------------------"; }
                if [[ $attempt -lt $EMU_START_MAX_RETRIES ]]; then
                    log "  [RETRY] Worker $i: retrying in 3s..."
                    sleep 3
                fi
            fi
        done

        if [[ "$started" != "true" ]]; then
            log "  [GIVE UP] Worker $i: all $EMU_START_MAX_RETRIES attempts failed"
            failed=$((failed + 1))
        fi
    done

    return $failed
}

wait_emulators() {
    log "Waiting for emulators to start (${EMU_WAIT_TIME}s)..."
    sleep "$EMU_WAIT_TIME"

    ALIVE_WORKERS=0
    [[ -f "$EMU_PID_FILE" ]] && while read -r pid; do
        [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && ALIVE_WORKERS=$((ALIVE_WORKERS + 1))
    done < "$EMU_PID_FILE"

    log "Alive emulators: $ALIVE_WORKERS"
    [[ $ALIVE_WORKERS -eq 0 ]] && { log "Error: All emulators stopped"; return 1; }

    log "Checking ADB devices on each ADB server..."
    local total_devices=0
    for i in $(seq 0 $((NUM_WORKERS - 1))); do
        local adb_server_port=$((ADB_SERVER_START_PORT + i))
        local device_count
        device_count=$(timeout 10 $ADB_PATH -P "$adb_server_port" devices 2>/dev/null | grep -c "emulator-" | tail -1) || device_count=0
        [[ "$device_count" =~ ^[0-9]+$ ]] || device_count=0
        log "  [ADB] Server port $adb_server_port: $device_count device(s)"
        total_devices=$((total_devices + device_count))
    done

    if [[ $total_devices -eq 0 ]]; then
        log "Waiting for ADB devices (30s)..."
        sleep 30
        total_devices=0
        for i in $(seq 0 $((NUM_WORKERS - 1))); do
            local adb_server_port=$((ADB_SERVER_START_PORT + i))
            local device_count
            device_count=$(timeout 10 $ADB_PATH -P "$adb_server_port" devices 2>/dev/null | grep -c "emulator-" | tail -1) || device_count=0
            [[ "$device_count" =~ ^[0-9]+$ ]] || device_count=0
            total_devices=$((total_devices + device_count))
        done
    fi

    [[ $total_devices -eq 0 ]] && { log "Error: No ADB devices detected"; return 1; }
    log "Total detected devices: $total_devices"
    return 0
}

# ==================== Evaluation ====================

run_eval() {
    local workers=$1 repeat_id=$2 tasks_file=${3:-}
    log "Starting evaluation (workers=$workers, repeat=$repeat_id)..."

    local cmd=(
        python test_android_world.py
        --config "$CONFIG_FILE"
        --num_workers "$workers"
        --start_port "$START_PORT"
        --adb_server_start_port "$ADB_SERVER_START_PORT"
        --log_dir "$LOG_DIR"
        --repeat_id "$repeat_id"
    )
    [[ -n "$tasks_file" ]] && cmd+=(--tasks_file "$tasks_file")
    [[ -n "$TASK_RANDOM_SEED" ]] && cmd+=(--task_random_seed "$TASK_RANDOM_SEED")

    "${cmd[@]}"

    local ret=$?
    log "Evaluation completed (exit code: $ret)"
    return $ret
}

count_tasks_in_file() {
    local task_file=$1
    [[ -f "$task_file" ]] || { echo 0; return 0; }
    python - "$task_file" <<'PY'
import sys
from pathlib import Path

task_file = Path(sys.argv[1])
tasks = [
    line.strip()
    for line in task_file.read_text(encoding='utf-8').splitlines()
    if line.strip() and not line.strip().startswith('#')
]
print(len(tasks))
PY
}

write_retry_initial_tasks() {
    local task_file=$1
    python - "$CONFIG_FILE" "$task_file" <<'PY'
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
task_file = Path(sys.argv[2])

from eval.configs import load_config
from android_world import registry

config = load_config(str(config_path))
configured_tasks = config.get('eval', {}).get('tasks')
suite_family = config.get('eval', {}).get('suite_family', 'android_world')

if configured_tasks:
    tasks = list(dict.fromkeys(configured_tasks))
else:
    task_registry = registry.TaskRegistry()
    reg = task_registry.get_registry(family=suite_family)
    tasks = sorted(reg.keys())

task_file.parent.mkdir(parents=True, exist_ok=True)
task_file.write_text('\n'.join(tasks) + ('\n' if tasks else ''), encoding='utf-8')
print(len(tasks))
PY
}

create_retry_fallback_summary() {
    local repeat_id=$1
    local task_file=$2
    local summary_file=$3
    python - "$repeat_id" "$task_file" "$summary_file" <<'PY'
import json
import sys
from pathlib import Path

repeat_id = int(sys.argv[1])
task_file = Path(sys.argv[2])
summary_file = Path(sys.argv[3])
tasks = [
    line.strip()
    for line in task_file.read_text(encoding='utf-8').splitlines()
    if line.strip() and not line.strip().startswith('#')
]

summary = {
    'total_time_seconds': 0,
    'total_tasks': 0,
    'total_success': 0,
    'success_rate': 0,
    'num_workers': 0,
    'repeat_id': repeat_id,
    'worker_results': [{
        'worker_id': -1,
        'repeat_id': repeat_id,
        'tasks': tasks,
        'success': 0,
        'total': 0,
        'failed_tasks': [],
        'success_tasks': [],
        'unresolved_tasks': tasks,
        'error': 'Evaluation summary missing; all tasks treated as unresolved.',
    }],
}

summary_file.write_text(json.dumps(summary, indent=2), encoding='utf-8')
PY
}

process_retry_summary() {
    local summary_file=$1
    local state_file=$2
    local next_task_file=$3
    local repeat_id=$4
    local max_streak=$5
    python - "$summary_file" "$state_file" "$next_task_file" "$repeat_id" "$max_streak" <<'PY'
import json
import sys
from pathlib import Path

summary_file = Path(sys.argv[1])
state_file = Path(sys.argv[2])
next_task_file = Path(sys.argv[3])
repeat_id = int(sys.argv[4])
max_streak = int(sys.argv[5])

if state_file.exists():
    state = json.loads(state_file.read_text(encoding='utf-8'))
else:
    state = {
        'max_consecutive_failures': max_streak,
        'attempts_processed': [],
        'tasks': {},
    }

summary = json.loads(summary_file.read_text(encoding='utf-8'))
worker_results = summary.get('worker_results', [])

assigned = set()
success = set()
failed = set()
unresolved = set()

for worker in worker_results:
    tasks = set(worker.get('tasks') or [])
    success_tasks = set(worker.get('success_tasks') or [])
    failed_tasks = set(worker.get('failed_tasks') or [])
    unresolved_tasks = set(worker.get('unresolved_tasks') or [])

    assigned.update(tasks)
    success.update(success_tasks)
    failed.update(failed_tasks)
    unresolved.update(unresolved_tasks)

    uncategorized = tasks - success_tasks - failed_tasks - unresolved_tasks
    unresolved.update(uncategorized)

success -= failed | unresolved

for task in sorted(assigned):
    task_state = state['tasks'].setdefault(task, {
        'final_status': 'pending',
        'attempt_count': 0,
        'consecutive_failures': 0,
        'attempt_history': [],
    })

    if task in success:
        attempt_status = 'success'
    elif task in unresolved:
        attempt_status = 'unresolved'
    else:
        attempt_status = 'failed'

    task_state['attempt_count'] += 1
    task_state['attempt_history'].append({
        'attempt_id': repeat_id,
        'status': attempt_status,
    })
    task_state['last_status'] = attempt_status

    if attempt_status == 'success':
        task_state['final_status'] = 'success'
        task_state['consecutive_failures'] = 0
    else:
        if task_state.get('final_status') != 'success':
            task_state['consecutive_failures'] += 1
            if task_state['consecutive_failures'] >= max_streak:
                task_state['final_status'] = 'failed'
            else:
                task_state['final_status'] = 'pending'

pending_tasks = sorted(
    task for task, task_state in state['tasks'].items()
    if task_state.get('final_status') == 'pending'
)

state['attempts_processed'] = sorted(set(state.get('attempts_processed', [])) | {repeat_id})
state['last_processed_repeat_id'] = repeat_id
state['pending_tasks'] = pending_tasks
state['successful_tasks'] = sorted(
    task for task, task_state in state['tasks'].items()
    if task_state.get('final_status') == 'success'
)
state['failed_tasks'] = sorted(
    task for task, task_state in state['tasks'].items()
    if task_state.get('final_status') == 'failed'
)

next_task_file.parent.mkdir(parents=True, exist_ok=True)
next_task_file.write_text(
    '\n'.join(pending_tasks) + ('\n' if pending_tasks else ''),
    encoding='utf-8',
)
state_file.write_text(json.dumps(state, indent=2), encoding='utf-8')
print(len(pending_tasks))
PY
}

run_round_attempt() {
    local repeat_id=$1
    local tasks_file=${2:-}
    local round_label=${3:-$((repeat_id + 1))}

    log "========================================"
    log "Starting round ${round_label}"
    log "========================================"

    if [[ -n "$tasks_file" ]]; then
        local task_count
        task_count=$(count_tasks_in_file "$tasks_file")
        log "Round task file: $tasks_file ($task_count tasks)"
    fi

    log "Cleaning up previous round..."
    cleanup
    rm -f "$EMU_PID_FILE"
    sleep 5

    start_emulators
    local failed=$?
    [[ $((NUM_WORKERS - failed)) -eq 0 ]] && { log "Error: All emulators failed to start"; return 1; }
    [[ $failed -gt 0 ]] && log "Warning: $failed emulators failed to start"

    wait_emulators || { log "Error: Emulators not ready, skipping round"; return 1; }

    run_eval "$ALIVE_WORKERS" "$repeat_id" "$tasks_file" || log "Round ${round_label} evaluation error"

    reap_zombies
    log "Round ${round_label} completed"
    return 0
}

run_standard_mode() {
    for repeat_id in $(seq 0 $((N_REPEATS - 1))); do
        run_round_attempt "$repeat_id" "" "$((repeat_id + 1))/$N_REPEATS" || true
    done

    log "All $N_REPEATS rounds completed!"
}

run_retry_mode() {
    local repeat_id=0
    local current_tasks_file="${RETRY_TASK_DIR}/attempt_00_tasks.txt"
    local next_tasks_file
    local pending_count

    rm -f "$RETRY_STATE_FILE"
    mkdir -p "$RETRY_TASK_DIR"

    local initial_count
    initial_count=$(write_retry_initial_tasks "$current_tasks_file") || return 1
    log "Retry mode enabled: initial task set has $initial_count tasks"

    while true; do
        local current_count
        current_count=$(count_tasks_in_file "$current_tasks_file")
        if [[ "$current_count" -eq 0 ]]; then
            log "Retry mode: no pending tasks left"
            break
        fi

        run_round_attempt "$repeat_id" "$current_tasks_file" || true

        local summary_file="${LOG_DIR}/parallel_summary_repeat_${repeat_id}.json"
        if [[ ! -f "$summary_file" ]]; then
            log "Retry mode: summary missing for repeat $repeat_id, creating unresolved fallback"
            create_retry_fallback_summary "$repeat_id" "$current_tasks_file" "$summary_file"
        fi

        printf -v next_tasks_file "%s/attempt_%02d_tasks.txt" "$RETRY_TASK_DIR" $((repeat_id + 1))
        pending_count=$(process_retry_summary "$summary_file" "$RETRY_STATE_FILE" "$next_tasks_file" "$repeat_id" "$FAILED_TASK_MAX_STREAK")
        log "Retry mode: $pending_count task(s) still pending after attempt $repeat_id"

        if [[ "$pending_count" -eq 0 ]]; then
            break
        fi

        current_tasks_file="$next_tasks_file"
        repeat_id=$((repeat_id + 1))
    done

    log "Retry mode completed. Final summary: $RETRY_STATE_FILE"
}

# ==================== Pre-flight Checks ====================

print_header() {
    cat << EOF
==========================================
Android World Evaluation
==========================================
Time: $(date)
Config: ${CONFIG_FILE}
Model: ${CONFIG_NAME}
Workers: ${NUM_WORKERS}
Start port: ${START_PORT}
ADB Server start port: ${ADB_SERVER_START_PORT}
Repeats: ${N_REPEATS}
Retry failed tasks: ${RETRY_FAILED_TASKS}
Max failure streak: ${FAILED_TASK_MAX_STREAK}
Task random seed: ${TASK_RANDOM_SEED:-random}
==========================================
Log dir: ${LOG_DIR}
Output dir: ${OUTPUT_PATH}
==========================================
EOF
}

print_header

[[ ! -f "$CONFIG_FILE" ]] && {
    echo "Error: Config file not found: $CONFIG_FILE"
    echo "Available configs:"
    ls -1 "${ANDROID_WORLD_PATH}/eval/configs/"*.yaml 2>/dev/null | xargs -n1 basename | sed 's/.yaml$//'
    exit 1
}
[[ ! -f "$EMULATOR_PATH" ]] && die "Emulator not found: $EMULATOR_PATH"

echo "$ANDROID_AVD_HOME/$AVD_NAME.avd"
[[ ! -d "$ANDROID_AVD_HOME/$AVD_NAME.avd" ]] && die "AVD not found: $AVD_NAME"

mkdir -p "$LOG_DIR/emulators"
mkdir -p "$OUTPUT_PATH"
mkdir -p "$RETRY_TASK_DIR"
rm -f "$EMU_PID_FILE"
rm -f "$RETRY_STATE_FILE"

# Copy config to output dir as runtime config
RUNTIME_CONFIG_FILE="${OUTPUT_PATH}/config.yaml"
cp "$CONFIG_FILE" "$RUNTIME_CONFIG_FILE"
sed -i "s|sft_data_dir:.*|sft_data_dir: ${OUTPUT_PATH}|g" "$RUNTIME_CONFIG_FILE"
sed -i "s|model:.*|model: ${MODEL_NAME}|g" "$RUNTIME_CONFIG_FILE"
echo "Runtime config: $RUNTIME_CONFIG_FILE"
echo "model: $MODEL_NAME"
echo "sft_data_dir: $OUTPUT_PATH"

# Use runtime config
CONFIG_FILE="$RUNTIME_CONFIG_FILE"

# ==================== Main Process (Background) ====================

(
    trap cleanup EXIT INT TERM

    if [[ "$RETRY_FAILED_TASKS" == "1" ]]; then
        run_retry_mode
    else
        run_standard_mode
    fi
) > "$MAIN_LOG" 2>&1 &

MAIN_PID=$!
echo "$MAIN_PID" > "$PID_FILE"
disown "$MAIN_PID"

cat << EOF

==========================================
Evaluation started in background
==========================================
Main PID: $MAIN_PID
Log file: $MAIN_LOG
Output dir: $OUTPUT_PATH
==========================================

Commands:
  View logs: tail -f $MAIN_LOG
  Stop: kill \$(cat $PID_FILE)

You can safely disconnect the terminal now.
EOF
