"""OpenBeavs v2 Development Orchestrator.

Starts all 3 development services concurrently in a single terminal:
1. Backend (FastAPI Chat & Chris, port 8000)
2. Registry (A2A Agent Selection Service, port 8001)
3. Frontend (SvelteKit Chat UI, port 5173)

Provides colored output prefixes, graceful Ctrl+C handling, and a 'stop' command
that terminates all lingering processes by port.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

# Paths relative to repository root
ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIR = ROOT_DIR / "frontend"

DEFAULT_PORTS = [8000, 8010, 8001, 5173]


def get_backend_port() -> int:
    """Read configured backend port from backend/.env or return default 8010."""
    env_file = BACKEND_DIR / ".env"
    if env_file.exists():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("CHRIS_PUBLIC_URL=") or line.startswith("CHRIS_A2A_URL="):
                        val = line.split("=", 1)[1].strip()
                        from urllib.parse import urlsplit

                        parsed = urlsplit(val)
                        if parsed.port:
                            return parsed.port
        except Exception:
            pass
    return 8010

# ANSI colors for nice terminal output
COLORS = {
    "backend": "\033[94m",   # Blue
    "registry": "\033[93m",  # Yellow
    "frontend": "\033[92m",  # Green
    "system": "\033[95m",    # Magenta
    "reset": "\033[0m",
}


def stop_processes_on_ports(ports=None):
    """Find and kill any processes listening on the development ports."""
    if ports is None:
        ports = DEFAULT_PORTS

    print(f"{COLORS['system']}[system] Stopping processes listening on ports {ports}...{COLORS['reset']}")
    killed_pids = set()

    try:
        output = subprocess.check_output("netstat -ano -p tcp", shell=True).decode("utf-8", errors="ignore")
        for line in output.splitlines():
            for port in ports:
                # Match e.g. " 127.0.0.1:8000 " or " 0.0.0.0:8000 " or " [::]:8000 "
                if f":{port} " in line and "LISTENING" in line:
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        pid = parts[-1]
                        if pid.isdigit() and pid not in ("0", str(os.getpid())):
                            killed_pids.add(pid)
    except Exception as e:
        print(f"Error querying netstat: {e}")

    if not killed_pids:
        print(f"{COLORS['system']}[system] No lingering processes found on ports {ports}. Ports are clean!{COLORS['reset']}")
        return

    for pid in killed_pids:
        try:
            # /T terminates process and all child processes, /F forces termination
            subprocess.run(f"taskkill /F /T /PID {pid}", shell=True, capture_output=True)
            print(f"{COLORS['system']}[system] Killed PID {pid}{COLORS['reset']}")
        except Exception as e:
            print(f"{COLORS['system']}[system] Failed to kill PID {pid}: {e}{COLORS['reset']}")

    print(f"{COLORS['system']}[system] Development ports are now clean.{COLORS['reset']}")


def stream_output(pipe, prefix, color):
    """Read lines from process pipe and print with colored prefix."""
    try:
        for line in iter(pipe.readline, ""):
            if not line:
                break
            sys.stdout.write(f"{color}[{prefix}]{COLORS['reset']} {line}")
            sys.stdout.flush()
    except Exception:
        pass


def start_services():
    """Start all 3 services (backend, registry, frontend) concurrently."""
    # First ensure ports are clear
    stop_processes_on_ports()

    py_exec = sys.executable
    backend_port = get_backend_port()

    services = [
        {
            "name": "backend",
            "cmd": [py_exec, "-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", str(backend_port)],
            "cwd": str(BACKEND_DIR),
            "color": COLORS["backend"],
        },
        {
            "name": "registry",
            "cmd": [
                py_exec,
                "-m",
                "uvicorn",
                "app.registry.a2a_app:create_standalone_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                "8001",
            ],
            "cwd": str(BACKEND_DIR),
            "color": COLORS["registry"],
            "env": {
                **os.environ,
                "REGISTRY_PUBLIC_URL": os.environ.get("REGISTRY_PUBLIC_URL", "http://127.0.0.1:8001"),
                "REGISTRY_A2A_AUTH": os.environ.get("REGISTRY_A2A_AUTH", "dev"),
            },
        },
        {
            "name": "frontend",
            "cmd": "npm run dev",
            "cwd": str(FRONTEND_DIR),
            "color": COLORS["frontend"],
            "shell": True,
            "env": {
                **os.environ,
                "BACKEND_ORIGIN": f"http://127.0.0.1:{backend_port}",
            },
        },
    ]

    print(f"\n{COLORS['system']}════════════════════════════════════════════════════════════════")
    print("  🚀 Starting OpenBeavs v2 Development Environment (All 3 Services)")
    print(f"  - Backend:  http://127.0.0.1:{backend_port} (FastAPI Chat & Chris A2A)")
    print("  - Registry: http://127.0.0.1:8001 (A2A Expert Selection Service)")
    print("  - Frontend: http://127.0.0.1:5173 (SvelteKit Chat UI)")
    print("  Press Ctrl+C to stop all services.")
    print(f"════════════════════════════════════════════════════════════════{COLORS['reset']}\n")

    processes = []
    threads = []

    try:
        for s in services:
            is_shell = s.get("shell", False)
            cmd = s["cmd"]
            env = s.get("env", os.environ)
            # On Windows, using CREATE_NEW_PROCESS_GROUP allows clean signal management
            p = subprocess.Popen(
                cmd,
                cwd=s["cwd"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                shell=is_shell,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )
            processes.append((s["name"], p))

            t = threading.Thread(target=stream_output, args=(p.stdout, s["name"], s["color"]), daemon=True)
            t.start()
            threads.append(t)

        # Wait while processes run
        while True:
            time.sleep(0.5)
            for name, p in processes:
                ret = p.poll()
                if ret is not None and ret != 0:
                    print(f"\n{COLORS['system']}[system] Service '{name}' exited with code {ret}.{COLORS['reset']}")

    except KeyboardInterrupt:
        print(f"\n{COLORS['system']}[system] Received shutdown signal. Terminating services...{COLORS['reset']}")
    finally:
        for name, p in processes:
            try:
                if sys.platform == "win32":
                    subprocess.run(f"taskkill /F /T /PID {p.pid}", shell=True, capture_output=True)
                else:
                    p.terminate()
            except Exception:
                pass
        stop_processes_on_ports()
        print(f"{COLORS['system']}[system] All services stopped.{COLORS['reset']}")


def main():
    if len(sys.argv) > 1 and sys.argv[1].lower() in ("stop", "kill", "down"):
        stop_processes_on_ports()
    elif len(sys.argv) > 1 and sys.argv[1].lower() in ("start", "run", "dev", "up"):
        start_services()
    else:
        # Default action: start
        start_services()


if __name__ == "__main__":
    main()
