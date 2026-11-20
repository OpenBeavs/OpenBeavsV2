"""Launch each service in its own Windows console, supervised by this terminal."""

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def get_frontend_port() -> int:
    """Read frontend port from FRONTEND_PORT, MICROSOFT_REDIRECT_URI, or default 5173."""
    if "FRONTEND_PORT" in os.environ:
        try:
            return int(os.environ["FRONTEND_PORT"])
        except ValueError:
            pass
    env_file = ROOT / "backend/.env"
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
    return (8001, 8000, 8010, get_frontend_port())


def service_specs(python: str, node: str) -> list[tuple[str, Path, list[str]]]:
    """Keep Python services in backend so they share its dotenv and SQLite file."""
    backend = ROOT / "backend"
    frontend_port = str(get_frontend_port())
    return [
        ("Registry", backend, [python, "-m", "uvicorn",
         "app.registry.a2a_app:create_standalone_app", "--factory",
         "--host", "127.0.0.1", "--port", "8001"]),
        ("Chris", backend, [python, "-m", "app.chris.run"]),
        ("Backend", backend, [python, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", "8010"]),
        ("Frontend", ROOT / "frontend", [node,
         str(ROOT / "frontend/node_modules/vite/bin/vite.js"),
         "--host", "127.0.0.1", "--port", frontend_port, "--strictPort"]),
    ]


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
    python = ROOT / "backend/.venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    node = shutil.which("node")
    if not python.is_file() or not node or not (
        ROOT / "frontend/node_modules/vite/bin/vite.js"
    ).is_file():
        print("Missing backend/.venv, Node.js, or frontend dependencies. "
              "Follow docs/registry.md first.")
        return 1

    processes = []
    try:
        check_ports()
        env = local_environment()
        specs = service_specs(str(python), node)
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
        print(f"Frontend: http://localhost:{f_port} | Backend: http://127.0.0.1:8010/docs\n"
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
