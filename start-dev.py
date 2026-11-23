"""Start the four OpenBeavs services for local development, and supervise them.

On Windows each service opens in its own console; elsewhere they share this terminal.
``scripts/dev.py`` and the ``Makefile`` start the services from the definitions here.
"""

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AGENT_REGISTRY = ROOT / "agent-registry"
CONVERSATION_AGENT = ROOT / "chat-system/conversation-agent"
APPLICATION_SERVICES = ROOT / "chat-system/application-services"
WEB_UI = ROOT / "chat-system/web-ui"
VITE = WEB_UI / "node_modules/vite/bin/vite.js"


def get_frontend_port() -> int:
    """Read the Web UI's port from FRONTEND_PORT, MICROSOFT_REDIRECT_URI, or default 5173."""
    if "FRONTEND_PORT" in os.environ:
        try:
            return int(os.environ["FRONTEND_PORT"])
        except ValueError:
            pass
    env_file = ROOT / ".env"
    if env_file.is_file():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("FRONTEND_PORT="):
                        return int(line.split("=", 1)[1].strip())
                    if line.startswith("MICROSOFT_REDIRECT_URI="):
                        from urllib.parse import urlsplit

                        p = urlsplit(line.split("=", 1)[1].strip()).port
                        if p:
                            return p
        except Exception:
            pass
    return 5173


def get_ports() -> tuple[int, ...]:
    """Each service's port, in the order ``service_specs`` lists the services."""
    return (8001, 8000, 8010, get_frontend_port())


def venv_python(folder: Path) -> Path:
    """The Python interpreter of the virtual environment in ``folder``."""
    return folder / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def service_specs(node: str) -> list[tuple[str, Path, list[str]]]:
    """Start each Python service from its own folder, with that folder's environment.

    Each service then opens its own SQLite file (``DATABASE_URL`` is relative to the
    folder it starts in), and all of them read the one ``.env`` at the repository root.
    """
    frontend_port = str(get_frontend_port())
    return [
        ("Agent Registry", AGENT_REGISTRY, [str(venv_python(AGENT_REGISTRY)), "-m",
         "uvicorn", "agent_registry.a2a_app:create_standalone_app", "--factory",
         "--host", "127.0.0.1", "--port", "8001"]),
        ("Conversation Agent", CONVERSATION_AGENT, [str(venv_python(CONVERSATION_AGENT)),
         "-m", "conversation_agent.run"]),
        ("Application Services", APPLICATION_SERVICES,
         [str(venv_python(APPLICATION_SERVICES)), "-m", "uvicorn",
          "application_services.main:app", "--host", "127.0.0.1", "--port", "8010"]),
        ("Web UI", WEB_UI, [node, str(VITE),
         "--host", "127.0.0.1", "--port", frontend_port, "--strictPort"]),
    ]


def missing_requirements(folders: list[Path]) -> list[str]:
    """The setup README.md describes that has not been done for the services in ``folders``."""
    missing = []
    for folder in folders:
        name = folder.relative_to(ROOT).as_posix()
        if folder == WEB_UI:
            if not shutil.which("node"):
                missing.append("Node.js 22 or later")
            elif not VITE.is_file():
                missing.append(f"{name}/node_modules (run npm ci in {name}/)")
        elif not venv_python(folder).is_file():
            missing.append(f"{name}/.venv (run uv sync --locked in {name}/)")
    return missing


def local_environment() -> dict[str, str]:
    """Override only local routing; inherit credentials without printing them."""
    return {
        **os.environ,
        "CHRIS_PUBLIC_URL": "http://127.0.0.1:8000",
        "CHRIS_A2A_URL": "http://127.0.0.1:8000/chris/a2a/",
        "REGISTRY_PUBLIC_URL": "http://127.0.0.1:8001",
        "REGISTRY_A2A_URL": "http://127.0.0.1:8001/a2a/registry",
        "BACKEND_ORIGIN": "http://127.0.0.1:8010",
    }


def check_ports() -> None:
    """Fail before starting anything when a required local port is occupied."""
    for port in get_ports():
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                raise RuntimeError(f"Port {port} is unavailable. Stop its server first.") from None


def stop_services(processes: list[subprocess.Popen]) -> None:
    """Stop every child, including after partial startup or a service failure."""
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    for process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main() -> int:
    """Use separate Windows consoles while retaining direct child supervision."""
    missing = missing_requirements([AGENT_REGISTRY, CONVERSATION_AGENT,
                                    APPLICATION_SERVICES, WEB_UI])
    if missing:
        print("Missing: " + "; ".join(missing) + ". Follow README.md first.")
        return 1
    node = shutil.which("node")

    processes = []
    try:
        check_ports()
        env = local_environment()
        specs = service_specs(node)
        for name, cwd, command in specs:
            print(f"Starting {name}...", flush=True)
            # Direct children keep shutdown reliable without intermediate shells.
            # Other platforms retain the original shared-terminal behavior.
            options = {}
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.lpTitle = f"OpenBeavs - {name}"
                options = {
                    "creationflags": subprocess.CREATE_NEW_CONSOLE,
                    "startupinfo": startupinfo,
                }
            processes.append(subprocess.Popen(command, cwd=cwd, env=env, **options))
        f_port = get_frontend_port()
        print(f"Web UI: http://localhost:{f_port} | "
              "Application Services: http://127.0.0.1:8010/docs\n"
              "Services are starting. Keep this launcher open. "
              "Press Ctrl+C here to stop all four.", flush=True)
        while True:
            for (name, _, _), process in zip(specs, processes):
                if process.poll() is not None:
                    print(f"{name} exited ({process.returncode}); stopping the stack.")
                    return 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping the stack...")
        return 0
    except (OSError, RuntimeError) as error:
        print(f"Startup failed: {error}")
        return 1
    finally:
        stop_services(processes)


if __name__ == "__main__":
    raise SystemExit(main())
