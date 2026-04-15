#!/usr/bin/env python3
"""Android World Parallel Evaluation Script - MAI-UI Navigator

Runs AndroidWorld benchmark using the MAIUINaivigationAgent defined in
MAI-UI/src/mai_naivigation_agent.py. Mirrors test_android_world.py but swaps
the agent for a thin BaseEvalAgent wrapper around the MAI-UI navigator.
"""

import argparse
import json
import multiprocessing as mp
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

os.environ['GRPC_VERBOSITY'] = 'ERROR'
os.environ['GRPC_TRACE'] = 'none'

SCRIPT_DIR = Path(__file__).parent.absolute()
PROJECT_ROOT = SCRIPT_DIR
ANDROID_WORLD_PATH = PROJECT_ROOT / "androidworld"
ANDROID_ENV_PATH = PROJECT_ROOT / "android_env"
MAIUI_SRC_PATH = PROJECT_ROOT.parent / "MAI-UI" / "src"

sys.path.insert(0, str(ANDROID_WORLD_PATH))
sys.path.insert(0, str(ANDROID_ENV_PATH))
sys.path.insert(0, str(MAIUI_SRC_PATH))


def setup_logging(log_file: str):
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    class Tee:
        def __init__(self, *files):
            self.files = files
        def write(self, obj):
            for f in self.files:
                f.write(obj)
                f.flush()
        def flush(self):
            for f in self.files:
                f.flush()

    log_fp = open(log_file, 'w', encoding='utf-8')
    sys.stdout = Tee(sys.stdout, log_fp)
    sys.stderr = Tee(sys.stderr, log_fp)
    return log_file


def split_tasks(tasks: List[str], num_workers: int) -> List[List[str]]:
    chunks = [[] for _ in range(num_workers)]
    for i, task in enumerate(tasks):
        chunks[i % num_workers].append(task)
    return [c for c in chunks if c]


def get_all_tasks() -> List[str]:
    from android_world import registry
    reg = registry.TaskRegistry().get_registry(family='android_world')
    return list(reg.keys())


def _worker_reap_zombies():
    try:
        while True:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
    except (ChildProcessError, OSError):
        pass


def _zombie_reaper_thread(stop_event):
    while not stop_event.is_set():
        _worker_reap_zombies()
        stop_event.wait(5)


# ---------------------------------------------------------------------------
# MAI-UI eval agent wrapper
# ---------------------------------------------------------------------------

def _build_mai_ui_eval_agent(env, agent_cfg: Dict[str, Any], llm_cfg: Dict[str, Any]):
    """Construct a BaseEvalAgent that wraps MAIUINaivigationAgent."""
    import time as _time
    from PIL import Image
    import numpy as np
    from absl import logging

    from android_world.env import json_action
    from eval.agents.base_agent import BaseEvalAgent, AgentStepResult

    # Imported lazily so sys.path insertion (MAI-UI/src) has taken effect.
    from mai_naivigation_agent import MAIUINaivigationAgent

    class MAIUIEvalAgent(BaseEvalAgent):
        """BaseEvalAgent wrapper that delegates reasoning to MAI-UI navigator."""

        def __init__(
            self,
            env,
            llm_base_url: str,
            model_name: str,
            name: str = 'MAIUI-Agent',
            wait_after_action_seconds: float = 2.0,
            history_n: int = 3,
            temperature: float = 0.0,
            top_p: float = 1.0,
            top_k: int = -1,
            max_tokens: int = 2048,
        ):
            super().__init__(env, name, transition_pause=1.0)
            self.navigator = MAIUINaivigationAgent(
                llm_base_url=llm_base_url,
                model_name=model_name,
                runtime_conf={
                    'history_n': history_n,
                    'temperature': temperature,
                    'top_p': top_p,
                    'top_k': top_k,
                    'max_tokens': max_tokens,
                },
            )
            self.wait_after_action_seconds = wait_after_action_seconds

        def reset(self, go_home: bool = False) -> None:
            super().reset(go_home)
            self.navigator.reset()

        def step(self, goal: str, task_name: Optional[str] = None) -> AgentStepResult:
            step_data = {
                'goal': goal,
                'before_screenshot': None,
                'after_screenshot': None,
                'model_response': None,
                'action': None,
                'success': False,
            }

            logging.info(f'---------- MAI-UI Step {len(self.navigator.traj_memory.steps) + 1} ----------')

            state = self.get_post_transition_state()
            h, w = state.pixels.shape[0], state.pixels.shape[1]
            before = state.pixels.copy()
            step_data['before_screenshot'] = before
            screenshot_pil = Image.fromarray(before)

            try:
                prediction, action_json = self.navigator.predict(
                    goal, {'screenshot': screenshot_pil}
                )
                step_data['model_response'] = prediction
                logging.info(f'MAI-UI raw response: {prediction}')

                if not action_json or action_json.get('action') is None:
                    logging.warning('MAI-UI: no action parsed')
                    return AgentStepResult(done=False, data=step_data)

                action = self._to_json_action(action_json, w, h)
                step_data['action'] = action
                logging.info(f'MAI-UI parsed action: {action}')

                if action.action_type == 'status':
                    step_data['success'] = True
                    return AgentStepResult(done=True, data=step_data)

                self.env.execute_action(action)
                _time.sleep(self.wait_after_action_seconds)

                state_after = self.env.get_state(wait_to_stabilize=False)
                step_data['after_screenshot'] = state_after.pixels.copy()
                step_data['success'] = True

                if action.action_type == 'answer':
                    return AgentStepResult(done=True, data=step_data)

                return AgentStepResult(done=False, data=step_data)

            except Exception as e:
                logging.error(f'MAI-UI step error: {e}', exc_info=True)
                step_data['error'] = str(e)
                return AgentStepResult(done=False, data=step_data)

        def _to_json_action(self, a: Dict[str, Any], screen_w: int, screen_h: int):
            """Map MAI-UI action dict (normalized [0,1] coords) to JSONAction."""
            act = a.get('action', '')
            x = y = x_ = y_ = None
            text = direction = goal_status = app_name = None

            def denorm(c):
                return round(float(c[0]) * screen_w), round(float(c[1]) * screen_h)

            if act in ('click', 'long_press'):
                if 'coordinate' in a:
                    x, y = denorm(a['coordinate'])

            elif act == 'swipe':
                direction = a.get('direction')
                if 'coordinate' in a:
                    # MAI-UI emits an anchor + direction; android_world's swipe
                    # only honors anchors when both (x,y) and (x_,y_) are set,
                    # otherwise it swipes from screen center. Synthesize an
                    # end point so the anchor is respected.
                    x, y = denorm(a['coordinate'])
                    dx = int(0.3 * screen_w)
                    dy = int(0.3 * screen_h)
                    d = (direction or '').lower()
                    if d == 'up':
                        x_, y_ = x, max(0, y - dy)
                    elif d == 'down':
                        x_, y_ = x, min(screen_h - 1, y + dy)
                    elif d == 'left':
                        x_, y_ = max(0, x - dx), y
                    elif d == 'right':
                        x_, y_ = min(screen_w - 1, x + dx), y
                    else:
                        x_, y_ = -1, -1
                else:
                    x_, y_ = -1, -1

            elif act == 'drag':
                # Map drag -> swipe with explicit start/end coords.
                if 'start_coordinate' in a:
                    x, y = denorm(a['start_coordinate'])
                if 'end_coordinate' in a:
                    x_, y_ = denorm(a['end_coordinate'])
                act = 'swipe'

            elif act in ('open', 'open_app'):
                act = 'open_app'
                app_name = a.get('text', '') or a.get('app_name', '')

            elif act in ('type', 'input_text'):
                act = 'input_text'
                text = a.get('text', '')

            elif act == 'system_button':
                btn = str(a.get('button', '')).lower()
                act = {
                    'back': 'navigate_back',
                    'home': 'navigate_home',
                    'enter': 'keyboard_enter',
                }.get(btn, 'wait')

            elif act == 'terminate':
                act = 'status'
                goal_status = a.get('status', 'success')

            elif act == 'answer':
                text = a.get('text', '')
                if hasattr(self.env, 'interaction_cache'):
                    self.env.interaction_cache = text

            elif act in ('wait', 'double_click'):
                if act == 'double_click':
                    # No native double_click in android_world; fall back to click.
                    act = 'click'
                    if 'coordinate' in a:
                        x, y = denorm(a['coordinate'])

            else:
                logging.warning(f'MAI-UI: unknown action {act}, falling back to wait')
                act = 'wait'

            return json_action.JSONAction(
                action_type=act,
                direction=direction,
                x=x,
                y=y,
                x_=x_,
                y_=y_,
                text=text,
                goal_status=goal_status,
                app_name=app_name,
            )

    return MAIUIEvalAgent(
        env=env,
        llm_base_url=llm_cfg.get('base_url', 'http://localhost:8001/v1'),
        model_name=llm_cfg.get('model', 'MAI-UI'),
        name=agent_cfg.get('name', 'MAIUI-Agent'),
        wait_after_action_seconds=agent_cfg.get('wait_after_action_seconds', 2.0),
        history_n=agent_cfg.get('history_n', 3),
        temperature=llm_cfg.get('temperature', 0.0),
        top_p=llm_cfg.get('top_p', 1.0),
        top_k=llm_cfg.get('top_k', -1),
        max_tokens=llm_cfg.get('max_tokens', 2048),
    )


# ---------------------------------------------------------------------------
# Worker / main
# ---------------------------------------------------------------------------

def worker_process(
    worker_id: int,
    tasks: List[str],
    config: Dict[str, Any],
    console_port: int,
    grpc_port: int,
    adb_server_port: int,
    result_queue: mp.Queue,
    log_dir: str,
    repeat_id: int = 0,
):
    import threading
    stop_event = threading.Event()
    reaper_thread = threading.Thread(target=_zombie_reaper_thread, args=(stop_event,), daemon=True)
    reaper_thread.start()

    print(f'[Worker {worker_id}] Started, handling {len(tasks)} tasks (repeat={repeat_id})')
    print(f'[Worker {worker_id}] Ports: console={console_port}, grpc={grpc_port}, adb_server={adb_server_port}')
    print(f'[Worker {worker_id}] Tasks: {tasks}')

    worker_config = config.copy()
    worker_config['worker_id'] = worker_id
    worker_config['env'] = config.get('env', {}).copy()
    worker_config['env']['console_port'] = console_port
    worker_config['env']['grpc_port'] = grpc_port
    worker_config['env']['adb_server_port'] = adb_server_port
    worker_config['eval'] = config.get('eval', {}).copy()
    worker_config['eval']['tasks'] = tasks

    base_output = os.path.expanduser(worker_config['eval'].get('output_path', '~/android_world/runs'))
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    worker_config['eval']['checkpoint_dir'] = ''
    worker_config['eval']['output_path'] = os.path.join(
        base_output, f'repeat_{repeat_id:02d}', f'{timestamp}_worker_{worker_id}'
    )

    worker_config['agent'] = config.get('agent', {}).copy()
    worker_config['llm'] = config.get('llm', {}).copy()

    results = {
        'worker_id': worker_id,
        'repeat_id': repeat_id,
        'tasks': tasks,
        'success': 0,
        'total': 0,
        'failed_tasks': [],
        'success_tasks': [],
        'error': None,
    }

    runner = None
    try:
        from eval.runner import EvalRunner

        runner = EvalRunner(worker_config)

        print(f'[Worker {worker_id}] Initializing Android environment...')
        runner.setup_env()

        print(f'[Worker {worker_id}] Initializing MAI-UI Agent...')
        runner.agent = _build_mai_ui_eval_agent(
            env=runner.env,
            agent_cfg=worker_config.get('agent', {}),
            llm_cfg=worker_config.get('llm', {}),
        )

        print(f'[Worker {worker_id}] Creating task suite...')
        suite = runner.create_suite()

        print(f'[Worker {worker_id}] Starting evaluation...')
        episodes = runner.run(suite)

        for ep in episodes:
            results['total'] += 1
            task_name = ep.get('task_template', 'unknown')
            is_success = ep.get('is_successful', 0)
            if ep.get('exception_info') is None:
                if is_success > 0.5:
                    results['success'] += 1
                    results['success_tasks'].append(task_name)
                else:
                    results['failed_tasks'].append(task_name)

        results['episodes'] = episodes
        print(f'[Worker {worker_id}] Evaluation completed: {results["success"]}/{results["total"]}')

        if episodes:
            print(f'\n[Worker {worker_id}] Detailed statistics:')
            runner.get_results_summary()

    except Exception as e:
        import traceback
        results['error'] = traceback.format_exc()
        print(f'[Worker {worker_id}] Error: {e}')
        traceback.print_exc()

    finally:
        print(f'[Worker {worker_id}] Closing runner...')
        try:
            if runner is not None:
                runner.close()
        except Exception as e:
            print(f'[Worker {worker_id}] Error during close: {e}')
        print(f'[Worker {worker_id}] Runner closed.')

    stop_event.set()
    print(f'[Worker {worker_id}] Putting results to queue...')
    result_queue.put(results)
    print(f'[Worker {worker_id}] Results sent, exiting...')


def run_parallel_eval(
    config: Dict[str, Any],
    num_workers: int,
    start_port: int,
    adb_server_start_port: int = 5037,
    tasks: Optional[List[str]] = None,
    log_dir: str = 'logs',
    repeat_id: int = 0,
):
    if tasks is None:
        eval_tasks = config.get('eval', {}).get('tasks')
        tasks = eval_tasks if eval_tasks else get_all_tasks()

    print(f'Total tasks: {len(tasks)}')
    print(f'Num workers: {num_workers}')
    print(f'Current round: {repeat_id}')

    task_chunks = split_tasks(tasks, num_workers)
    actual_workers = len(task_chunks)

    print(f'Actual workers: {actual_workers}')
    for i, chunk in enumerate(task_chunks):
        print(f'  Worker {i}: {len(chunk)} tasks')

    result_queue = mp.Queue()
    start_time = time.time()

    processes = []
    for i, chunk in enumerate(task_chunks):
        console_port = start_port + i * 2
        grpc_port = 8554 + i
        adb_server_port = adb_server_start_port + i
        p = mp.Process(
            target=worker_process,
            args=(i, chunk, config, console_port, grpc_port, adb_server_port,
                  result_queue, log_dir, repeat_id),
        )
        processes.append(p)

    print(f'\nStarting {actual_workers} worker processes (repeat={repeat_id})...')
    for p in processes:
        p.start()
        time.sleep(5)

    print('Waiting for all processes to complete...\n')

    all_results = []
    finished_count = 0
    total_workers = len(processes)

    while finished_count < total_workers:
        while True:
            try:
                result = result_queue.get_nowait()
                all_results.append(result)
                print(f'[Main] Got result from worker {result["worker_id"]}')
            except Exception:
                break

        for p in processes:
            if p.exitcode is not None and not hasattr(p, '_already_reported'):
                print(f'[Main] Worker {p.pid} finished with exit code {p.exitcode}')
                p._already_reported = True
                finished_count += 1

        if finished_count < total_workers:
            time.sleep(1)
            still_running = sum(1 for p in processes if p.exitcode is None)
            if still_running > 0:
                print(f'[Main] Still waiting for {still_running} workers... (got {len(all_results)} results)')

    while True:
        try:
            result = result_queue.get_nowait()
            all_results.append(result)
            print(f'[Main] Got result from worker {result["worker_id"]}')
        except Exception:
            break

    for p in processes:
        try:
            if p.is_alive():
                p.terminate()
                p.join(timeout=5)
                if p.is_alive():
                    p.kill()
                    p.join(timeout=3)
            p.close()
        except Exception as e:
            print(f'[Main] Error closing process: {e}')

    reap_zombies()

    total_time = time.time() - start_time
    total_success = sum(r['success'] for r in all_results)
    total_tasks = sum(r['total'] for r in all_results)

    print('\n' + '=' * 60)
    print(f'Round {repeat_id} Summary')
    print('=' * 60)
    print(f'Total time: {total_time / 60:.1f} min')
    print(f'Total tasks: {total_tasks}')
    print(f'Successful tasks: {total_success}')
    if total_tasks > 0:
        print(f'Success rate: {total_success / total_tasks * 100:.1f}%')
    print('=' * 60)

    all_episodes = []
    for r in all_results:
        if 'episodes' in r and r['episodes']:
            all_episodes.extend(r['episodes'])

    if all_episodes:
        print('\n' + '=' * 60)
        print('Detailed Statistics')
        print('=' * 60)
        from android_world.suite_utils import process_episodes
        result_df = process_episodes(all_episodes, print_summary=True)
        csv_file = os.path.join(log_dir, 'detailed_results.csv')
        result_df.to_csv(csv_file)
        print(f'\nDetailed results saved to: {csv_file}')

    print('\nWorker Results:')
    for r in sorted(all_results, key=lambda x: x['worker_id']):
        status = 'OK' if r['error'] is None else 'FAIL'
        print(f"  Worker {r['worker_id']}: {r['success']}/{r['total']} [{status}]")
        if r['error']:
            print(f"    Error: {r['error'][:200]}...")

    all_failed = []
    for r in all_results:
        all_failed.extend(r['failed_tasks'])
    if all_failed:
        print(f'\nFailed tasks ({len(all_failed)}):')
        for task in all_failed:
            print(f'  - {task}')

    serializable_results = []
    for r in all_results:
        r_copy = r.copy()
        r_copy.pop('episodes', None)
        serializable_results.append(r_copy)

    summary_file = os.path.join(log_dir, f'parallel_summary_repeat_{repeat_id}.json')
    with open(summary_file, 'w') as f:
        json.dump({
            'total_time_seconds': total_time,
            'total_tasks': total_tasks,
            'total_success': total_success,
            'success_rate': total_success / total_tasks if total_tasks > 0 else 0,
            'num_workers': actual_workers,
            'repeat_id': repeat_id,
            'worker_results': serializable_results,
        }, f, indent=2)
    print(f'\nSummary saved to: {summary_file}')

    reap_zombies()


def parse_args():
    parser = argparse.ArgumentParser(description='Android World MAI-UI Parallel Evaluation')
    default_config = str(ANDROID_WORLD_PATH / "eval" / "configs" / "MAI-UI.yaml")
    parser.add_argument('--config', type=str, default=default_config)
    parser.add_argument('--num_workers', type=int, default=1)
    parser.add_argument('--start_port', type=int, default=5556)
    parser.add_argument('--adb_server_start_port', type=int, default=5037)
    parser.add_argument('--tasks', type=str, default=None)
    parser.add_argument('--tasks_file', type=str, default=None)
    parser.add_argument('--log_dir', type=str, default='logs')
    parser.add_argument('--repeat_id', type=int, default=0)
    parser.add_argument('--task_random_seed', type=int, default=None)
    return parser.parse_args()


def reap_zombies():
    try:
        while True:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
    except (ChildProcessError, OSError):
        pass


def cleanup_children(signum=None, frame=None):
    for child in mp.active_children():
        try:
            child.terminate()
            child.join(timeout=5)
            if child.is_alive():
                child.kill()
                child.join(timeout=3)
        except Exception as e:
            print(f'[Cleanup] Error terminating {child.pid}: {e}')
    try:
        while True:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
    except (ChildProcessError, OSError):
        pass
    if signum is not None:
        sys.exit(1)


def main():
    mp.set_start_method('fork', force=True)
    signal.signal(signal.SIGTERM, cleanup_children)
    signal.signal(signal.SIGINT, cleanup_children)

    args = parse_args()

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    os.makedirs(args.log_dir, exist_ok=True)
    log_file = os.path.join(args.log_dir, f'parallel_eval_{timestamp}.log')
    setup_logging(log_file)

    print('\n' + '=' * 60)
    print('Android World MAI-UI Parallel Evaluation')
    print('=' * 60)
    print(f'Config file: {args.config}')
    print(f'Num workers: {args.num_workers}')
    print(f'Start port: {args.start_port}')
    print(f'ADB server start port: {args.adb_server_start_port}')
    print(f'Log dir: {args.log_dir}')
    print(f'Current round: {args.repeat_id}')
    print('=' * 60 + '\n')

    from eval.configs import load_config, get_default_config
    config = load_config(args.config) if os.path.exists(args.config) else get_default_config()

    if args.task_random_seed is not None:
        config.setdefault('eval', {})['task_random_seed'] = args.task_random_seed
        print(f'Task random seed overridden to: {args.task_random_seed}')

    tasks = None
    if args.tasks_file:
        tasks = []
        with open(args.tasks_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    tasks.extend([t.strip() for t in line.split(',') if t.strip()])
    elif args.tasks:
        tasks = [t.strip() for t in args.tasks.split(',')]

    try:
        run_parallel_eval(
            config=config,
            num_workers=args.num_workers,
            start_port=args.start_port,
            adb_server_start_port=args.adb_server_start_port,
            tasks=tasks,
            log_dir=args.log_dir,
            repeat_id=args.repeat_id,
        )
    except KeyboardInterrupt:
        print('\nEvaluation interrupted by user')
    except Exception as e:
        print(f'\nEvaluation error: {e}')
        import traceback
        traceback.print_exc()
    finally:
        cleanup_children()


if __name__ == '__main__':
    main()
