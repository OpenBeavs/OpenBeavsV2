"""OpenBeavs v2 development orchestrator, in a single terminal.

``python scripts/dev.py start`` starts the four services that ``start-dev.py`` starts,
from the same folders, environments, ports and settings, and prints each one's output
with a colored prefix:

1. Agent Registry (A2A expert selection and admin API, port 8001)
2. Conversation Agent (Chris, A2A, port 8000)
3. Application Services (the Chat System's HTTPS API, port 8010), reloaded on edits
4. Web UI (SvelteKit, port 8080 or 5173, as ``start-dev.py`` chooses)

``python scripts/dev.py start <folder>...`` starts only the named services:
``agent-registry``, ``conversation-agent``, ``application-services``, ``web-ui``.
Either form first stops whatever is listening on the ports it is about to use.
Ctrl+C stops what it started.

``python scripts/dev.py stop`` stops whatever is listening on any port the stack uses.
"""

import importlib.util
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def _load_launcher():
    """``start-dev.py`` holds the one definition of the services; load it as a module."""
    spec = importlib.util.spec_from_file_location("start_dev", ROOT_DIR / "start-dev.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launcher = _load_launcher()

# ANSI colors for nice terminal output
COLORS = {
    "agent-registry": "\033[93m",        # Yellow
    "conversation-agent": "\033[96m",    # Cyan
    "application-services": "\033[94m",  # Blue
    "web-ui": "\033[92m",                # Green
    "system": "\033[95m",                # Magenta
    "reset": "\033[0m",
}


def system(message: str) -> None:
    print(f"{COLORS['system']}[system] {message}{COLORS['reset']}", flush=True)


def stack_ports() -> list[int]:
    """Every port a start may have used: the Web UI takes 8080 or 5173, by the settings."""
    return sorted(set(launcher.get_ports()) | {5173, 8080})


def listening_pids(ports) -> set[int]:
    """The processes listening on any of ``ports``."""
    pids = set()
    if sys.platform == "win32":
        output = subprocess.run(["netstat", "-ano", "-p", "tcp"], check=False,
                                capture_output=True, text=True, errors="ignore").stdout
        for line in output.splitlines():
            parts = line.split()
            # e.g. "TCP  127.0.0.1:8000  0.0.0.0:0  LISTENING  1234"
            if (len(parts) >= 5 and parts[3] == "LISTENING" and parts[4].isdigit()
                    and any(parts[1].endswith(f":{port}") for port in ports)):
                pids.add(int(parts[4]))
    elif shutil.which("lsof") is None:
        system("lsof is not installed, so the processes on the ports cannot be found.")
    else:
        for port in ports:
            output = subprocess.run(["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
                                    check=False, capture_output=True, text=True).stdout
            pids.update(int(pid) for pid in output.split() if pid.isdigit())
    pids.discard(0)
    pids.discard(os.getpid())
    return pids


def stop_processes_on_ports(ports=None) -> None:
    """Stop every process listening on ``ports`` (by default, every port the stack uses)."""
    ports = stack_ports() if ports is None else ports
    pids = listening_pids(ports)
    if not pids:
        system(f"Nothing is listening on ports {ports}.")
        return
    for pid in pids:
        try:
            if sys.platform == "win32":
                # /T stops the process and its children, /F forces it.
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], check=False,
                               capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
            system(f"Stopped PID {pid}")
        except OSError as error:
            system(f"Failed to stop PID {pid}: {error}")
    deadline = time.monotonic() + 10
    while listening_pids(ports) and time.monotonic() < deadline:
        time.sleep(0.25)
    if sys.platform != "win32":
        for pid in listening_pids(ports):
            os.kill(pid, signal.SIGKILL)
            system(f"Killed PID {pid}, which ignored the request to stop")
    system(f"Ports {ports} are free.")


def stream_output(pipe, prefix, color):
    """Read lines from process pipe and print with colored prefix."""
    try:
        for line in iter(pipe.readline, ""):
            sys.stdout.write(f"{color}[{prefix}]{COLORS['reset']} {line}")
            sys.stdout.flush()
    except (OSError, ValueError):
        pass


def start_services(selected: list[str]) -> int:
    """Start the named services (every one when none is named) and supervise them."""
    node = shutil.which("node") or "node"
    services = [(cwd.name, port, name, cwd, command) for (name, cwd, command), port
                in zip(launcher.service_specs(node), launcher.get_ports())]
    known = [key for key, *_ in services]
    unknown = [key for key in selected if key not in known]
    if unknown:
        print(f"Unknown service {', '.join(unknown)}. Choose from: {', '.join(known)}.")
        return 2
    if selected:
        services = [service for service in services if service[0] in selected]

    missing = launcher.missing_requirements([cwd for _, _, _, cwd, _ in services])
    if missing:
        print("Missing: " + "; ".join(missing) + ". Follow README.md first.")
        return 1

    # First ensure the ports are clear.
    ports = [port for _, port, _, _, _ in services] if selected else stack_ports()
    stop_processes_on_ports(ports)

    env = {**launcher.local_environment(), "PYTHONUNBUFFERED": "1"}
    print(f"\n{COLORS['system']}{'═' * 64}")
    print("  Starting the OpenBeavs v2 development environment")
    for key, port, name, _, _ in services:
        print(f"  - {name}: http://127.0.0.1:{port}")
    print("  Press Ctrl+C to stop.")
    print(f"{'═' * 64}{COLORS['reset']}\n", flush=True)

    processes = []
    try:
        for key, _, _, cwd, command in services:
            if cwd == launcher.APPLICATION_SERVICES:
                command = [*command, "--reload"]
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )
            processes.append((key, process))
            threading.Thread(target=stream_output, args=(process.stdout, key, COLORS[key]),
                             daemon=True).start()

        while True:
            time.sleep(0.5)
            for key, process in processes:
                if process.poll() is not None:
                    system(f"Service '{key}' exited with code {process.returncode}; "
                           "stopping the others.")
                    # 0 when it was stopped on request, as by "scripts/dev.py stop".
                    stopped = (0, -signal.SIGTERM, -signal.SIGINT)
                    return 0 if process.returncode in stopped else 1
    except KeyboardInterrupt:
        print()
        system("Received shutdown signal. Terminating services...")
        return 0
    finally:
        for _, process in processes:
            if process.poll() is None:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                                   check=False, capture_output=True)
                else:
                    process.terminate()
        for _, process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        stop_processes_on_ports(ports)
        system("All services stopped.")


def main() -> int:
    command = sys.argv[1].lower() if len(sys.argv) > 1 else "start"
    if command in ("stop", "kill", "down"):
        stop_processes_on_ports()
        return 0
    if command in ("start", "run", "dev", "up"):
        return start_services(sys.argv[2:])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
