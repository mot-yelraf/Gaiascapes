"""Run blocking provider operations in disposable, deadline-bound processes.

Only local, trusted Python objects cross the private subprocess pipes. Built-in
clients return their updated capture state only after a completed operation;
timed-out workers are killed and reaped before another attempt can start.
"""

from contextlib import redirect_stdout, suppress
import asyncio
import importlib
import os
import pickle
import subprocess
import sys
import tempfile
import threading


IN_WORKER = False
BUILTIN_CLIENTS = {
    ('gaiascapes_host.usgs', 'UsgsClient'),
    ('gaiascapes_host.open_meteo', 'OpenMeteoMarineClient'),
    ('gaiascapes_host.open_meteo', 'OpenMeteoStormClient'),
    ('gaiascapes_host.noaa_glm', 'NoaaGlmClient'),
    ('gaiascapes_host.eumetsat_li', 'EumetsatLiClient'),
    ('gaiascapes_host.xeno_canto', 'XenoCantoClient'),
    ('gaiascapes_host.commons_birdsong', 'CommonsBirdsongClient'),
    ('gaiascapes_host.sanctsound', 'SanctSoundClient'),
}


def supports_isolation(client) -> bool:
    """Identify built-in clients whose state can cross a process boundary."""
    return (type(client).__module__, type(client).__name__) in BUILTIN_CLIENTS


def run_operation(operation, timeout):
    """Execute a trusted operation, killing and reaping it on timeout."""
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join(str(path) for path in sys.path if path)
    payload = pickle.dumps(operation)
    with tempfile.TemporaryDirectory(prefix="gaia-worker-") as pending:
        env['TMPDIR'] = pending
        with subprocess.Popen(
            [sys.executable, '-c', 'from gaiascapes_host.worker import main; main()'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env,
        ) as process:
            try:
                output, _ = process.communicate(payload, timeout=timeout)
            except BaseException:
                process.kill()
                process.communicate()
                raise
            if process.returncode:
                raise RuntimeError(f'Provider worker exited unexpectedly ({process.returncode})')
            return pickle.loads(output)


async def call_client(client, method, args=(), timeout=45):
    """Run a built-in client, stopping its process on timeout or cancellation."""
    state = {key: value for key, value in vars(client).items() if key not in {'_lock', '_now'}}
    baseline = {key: pickle.dumps(value) for key, value in state.items()}
    observed_now = client._now() if hasattr(client, '_now') else None
    operation = ('client', type(client).__module__, type(client).__name__, state, observed_now, method, args)
    payload = pickle.dumps(operation)
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join(str(path) for path in sys.path if path)
    with tempfile.TemporaryDirectory(prefix=".gaia-worker-", dir=state.get('media_dir')) as pending:
        env['TMPDIR'] = pending
        env['GAIASCAPES_WORKER_TEMP_DIR'] = pending
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-c', 'from gaiascapes_host.worker import main; main()',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, env=env,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(payload), timeout)
        except BaseException as exc:
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
            await process.communicate()
            if isinstance(exc, asyncio.TimeoutError):
                raise TimeoutError(f'Provider {method} exceeded {timeout:g} seconds; worker restarted') from None
            raise
        if process.returncode:
            raise RuntimeError(f'Provider worker exited unexpectedly ({process.returncode})')
        result, changes, error = pickle.loads(output)
        if any(pickle.dumps(vars(client).get(key)) != value for key, value in baseline.items()):
            raise RuntimeError('Provider state changed during operation; result discarded')
        for key, value in changes.items():
            setattr(client, key, value)
        if error is not None:
            raise error
        return result


def main():
    """Serve one private operation and return its result through stdout."""
    global IN_WORKER
    IN_WORKER = True
    operation = pickle.load(sys.stdin.buffer)
    with redirect_stdout(sys.stderr):
        mode, module, name, *arguments = operation
        target = getattr(importlib.import_module(module), name)
        changes = {}
        try:
            if mode == 'client':
                state, observed_now, method, args = arguments
                target = target.__new__(target)
                target.__dict__.update(state)
                target._lock = threading.Lock()
                if observed_now is not None:
                    target._now = lambda: observed_now
                before = {key: pickle.dumps(value) for key, value in state.items()}
                try:
                    result = getattr(target, method)(*args)
                finally:
                    changes = {key: value for key, value in vars(target).items()
                               if key not in {'_lock', '_now'}
                               and pickle.dumps(value) != before.get(key)}
            else:
                args, kwargs = arguments
                result = target(*args, **kwargs)
            response = (result, changes, None)
        except Exception as exc:
            response = (None, changes, exc)
    pickle.dump(response, sys.stdout.buffer)
