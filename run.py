#!/usr/bin/env python
"""
WhatsApp Reminder & Calendar Bot - Consolidated Launcher Script
This script provides a unified method to start all required services:
- Redis server (if not running)
- FastAPI application
- Celery worker
- Celery beat scheduler
- Ngrok tunnel for exposing the API

Supports both local development and Docker environments.
"""

import os
import sys
import time
import signal
import subprocess
import threading
import logging
import platform
import shutil
import json
from urllib.request import urlopen
from contextlib import contextmanager
from typing import List, Optional
import asyncio # <--- IMPORT asyncio HERE
import config
ASYNC_DATABASE_URL=config.ASYNC_DATABASE_URL # <--- Import your config here
# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()],
    encoding='utf-8'
)
logger = logging.getLogger("launcher")

# Global variables to track subprocesses
processes = []
stop_event = threading.Event()
redis_process = None
ngrok_process = None
ngrok_url = None

def is_docker():
    """Check if running inside a Docker container."""
    path = '/proc/self/cgroup'
    return os.path.exists('/.dockerenv') or (
        os.path.isfile(path) and any('docker' in line for line in open(path))
    )

def find_redis_executable():
    """Find Redis executable based on platform."""
    if platform.system() == "Windows":
        redis_paths = [
            r"C:\Program Files\Redis\redis-server.exe",
            r"C:\Program Files (x86)\Redis\redis-server.exe",
            r"C:\Redis\redis-server.exe",
        ]
        redis_cli = shutil.which("redis-cli.exe")
        if redis_cli:
            potential_server = os.path.join(os.path.dirname(redis_cli), "redis-server.exe")
            if os.path.exists(potential_server):
                return potential_server
        for path in redis_paths:
            if os.path.exists(path):
                return path
        return "redis-server.exe"
    else:
        redis_server = shutil.which("redis-server")
        if redis_server:
            return redis_server
        return "redis-server"

def find_ngrok_executable():
    """Find ngrok executable based on platform."""
    ngrok_cmd = "ngrok.exe" if platform.system() == "Windows" else "ngrok"
    ngrok_path = shutil.which(ngrok_cmd)
    if ngrok_path:
        return ngrok_path
    if platform.system() == "Windows":
        paths = [
            os.path.join(os.environ.get("USERPROFILE", ""), "ngrok", "ngrok.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "ngrok", "ngrok.exe")
        ]
    else:
        paths = [
            "/usr/local/bin/ngrok",
            "/usr/bin/ngrok",
            os.path.join(os.environ.get("HOME", ""), "ngrok")
        ]
    for path in paths:
        if os.path.exists(path):
            return path
    return ngrok_cmd

def is_redis_running():
    """Check if Redis server is already running."""
    try:
        import redis
        r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        return True
    except (redis.exceptions.ConnectionError, ImportError):
        return False

def start_redis_server():
    """Start Redis server if it's not already running."""
    global redis_process
    if is_docker():
        logger.info("Running in Docker - assuming Redis is managed by Docker Compose")
        return None
    if is_redis_running():
        logger.info("Redis server is already running")
        return None

    redis_executable = find_redis_executable()
    logger.info(f"Starting Redis server using {redis_executable}")
    try:
        redis_process = subprocess.Popen(
            [redis_executable],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        processes.append(redis_process)
        def log_output(stream, level):
            for line in stream:
                logger.log(level, f"[Redis] {line.strip()}")
                if stop_event.is_set(): break
        threading.Thread(target=log_output, args=(redis_process.stdout, logging.INFO), daemon=True).start()
        threading.Thread(target=log_output, args=(redis_process.stderr, logging.ERROR), daemon=True).start()
        time.sleep(2)
        if is_redis_running():
            logger.info("Redis server started successfully")
            return redis_process
        else:
            logger.error("Redis server failed to start properly")
            if redis_process.poll() is None: redis_process.terminate()
            return None
    except Exception as e:
        logger.error(f"Failed to start Redis server: {e}")
        return None

def start_ngrok_tunnel(port):
    """Start ngrok tunnel to expose the local server to the internet."""
    global ngrok_process, ngrok_url
    if is_docker() and not os.getenv("USE_NGROK", "").lower() in ("true", "1", "yes"):
        logger.info("Running in Docker - skipping ngrok tunnel unless USE_NGROK is set")
        return None

    ngrok_executable = find_ngrok_executable()
    logger.info(f"Starting ngrok tunnel using {ngrok_executable}")
    try:
        ngrok_process = subprocess.Popen(
            [ngrok_executable, "http", str(port), "--log=stdout"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        processes.append(ngrok_process)
        def log_output(stream, level):
            for line in stream:
                logger.log(level, f"[ngrok] {line.strip()}")
                if stop_event.is_set(): break
        threading.Thread(target=log_output, args=(ngrok_process.stdout, logging.INFO), daemon=True).start()
        threading.Thread(target=log_output, args=(ngrok_process.stderr, logging.ERROR), daemon=True).start()
        time.sleep(3) # Increased sleep slightly
        try:
            with urlopen("http://localhost:4040/api/tunnels") as response:
                data = json.loads(response.read().decode())
                https_tunnels = [t for t in data.get('tunnels', []) if t['proto'] == 'https']
                if https_tunnels:
                    ngrok_url = https_tunnels[0]['public_url']
                    logger.info(f"ngrok tunnel established: {ngrok_url}")
                    os.environ["WEBHOOK_URL"] = ngrok_url
                    logger.info(f"Set WEBHOOK_URL environment variable to {ngrok_url}")
                    return ngrok_process
                else:
                    logger.error("No HTTPS ngrok tunnels found")
                    # Fallback to check for any tunnel if needed, but HTTPS is preferred
                    all_tunnels = data.get('tunnels', [])
                    if all_tunnels:
                       ngrok_url = all_tunnels[0]['public_url']
                       logger.warning(f"Found non-HTTPS ngrok tunnel: {ngrok_url}. HTTPS is recommended.")
                       os.environ["WEBHOOK_URL"] = ngrok_url
                       logger.info(f"Set WEBHOOK_URL environment variable to {ngrok_url}")
                       return ngrok_process
                    else:
                       logger.error("No ngrok tunnels found at all.")
                       return None
        except Exception as e:
            logger.error(f"Failed to get ngrok URL from API (http://localhost:4040): {e}")
            # Attempt to parse ngrok logs as a fallback (less reliable)
            # This part is complex and might need adjustment based on ngrok's log format
            return None
    except Exception as e:
        logger.error(f"Failed to start ngrok: {e}")
        return None

def check_prerequisites() -> bool:
    """Verify all prerequisites are installed and available."""
    logger.info("Checking prerequisites...")
    python_version = sys.version_info
    if python_version.major < 3 or (python_version.major == 3 and python_version.minor < 9):
        logger.error("Python 3.9 or higher is required")
        return False

    if not is_redis_running():
        redis_proc = start_redis_server()
        if not redis_proc and not is_docker():
            logger.error("Redis server is not running and could not be started")
            return False
    else:
        logger.info("Redis server is running")

    required_env_vars = [
        "GEMINI_API_KEY",
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_BUSINESS_ACCOUNT_ID", # Assuming this is needed, adjust if not
        "TELEGRAM_BOT_TOKEN" # Added based on later usage
    ]
    if not is_docker():
        missing_vars = [var for var in required_env_vars if not os.getenv(var) ]
        if missing_vars:
            logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
            logger.error("Please add them to your .env file or set them manually")
            return False

    ngrok_executable = find_ngrok_executable()
    if not shutil.which(ngrok_executable) and not is_docker():
        logger.warning(f"ngrok not found using command '{ngrok_executable}' or in PATH.")
        logger.warning("If you need to expose the app externally, please install ngrok.")
    else:
        logger.info(f"ngrok check passed (executable: {ngrok_executable})")

    # --- Database Check using asyncio.run ---
    try:
        logger.info("Checking database connection and initialization...")
        # Import database functions here to avoid circular imports if run.py is imported elsewhere
        from database import init_db, check_db_initialized

        # Use asyncio.run() to execute the async check function
        is_initialized = asyncio.run(check_db_initialized())

        if not is_initialized:
            logger.info("Database tables not found. Initializing database...")
            # Use asyncio.run() to execute the async init function
            asyncio.run(init_db())
            logger.info("Database initialized successfully.")
        else:
            logger.info("Database appears to be initialized.")

    except ImportError:
        logger.error("Could not import database module. Ensure 'database' package is correct.")
        return False
    except Exception as e:
        logger.error(f"Error during database check/initialization: {e}")
        # Log more details if possible, e.g., connection errors
        if "Connection refused" in str(e) or "could not connect" in str(e):
             logger.error("Could not connect to the database. Is the database server running?")
             logger.error(f"Database URL: {ASYNC_DATABASE_URL}")
        return False
    # --- End Database Check ---

    logger.info("Prerequisites check passed.")
    return True

def run_command(cmd: List[str], name: str) -> Optional[subprocess.Popen]:
    """Run a system command in a subprocess and log its output."""
    try:
        logger.info(f"Starting {name} with command: {' '.join(cmd)}")
        # Use os.environ directly for environment variables
        process_env = os.environ.copy()
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
            encoding='utf-8', # Explicitly set encoding
            errors='replace', # Handle potential encoding errors in output
            env=process_env # Pass environment
        )
        processes.append(process)

        def log_output(stream, level, proc_name):
            try:
                for line in iter(stream.readline, ''):
                    if stop_event.is_set(): break
                    logger.log(level, f"[{proc_name}] {line.strip()}")
                stream.close()
            except Exception as e:
                 logger.error(f"Error reading output from {proc_name}: {e}")


        threading.Thread(target=log_output, args=(process.stdout, logging.INFO, name), daemon=True).start()
        threading.Thread(target=log_output, args=(process.stderr, logging.ERROR, name), daemon=True).start()

        # Short delay to check if the process started correctly
        time.sleep(1)
        if process.poll() is not None:
             logger.error(f"{name} failed to start or exited immediately with code {process.returncode}.")
             # Log stderr for clues if possible (might already be logged by thread)
             return None

        logger.info(f"{name} started successfully (PID: {process.pid}).")
        return process

    except FileNotFoundError:
         logger.error(f"Failed to start {name}: Command '{cmd[0]}' not found. Is it installed and in PATH?")
         return None
    except Exception as e:
        logger.error(f"Failed to start {name}: {e}")
        return None


def start_celery_worker() -> Optional[subprocess.Popen]:
    """Start the Celery worker process."""
    # Using --pool=solo can help with debugging on Windows sometimes
    # Ensure services.scheduler.celery_app points to your Celery app instance
    pool_option = "--pool=solo" if platform.system() == "Windows" else "--pool=prefork" # Use prefork (default) on Linux/macOS
    return run_command(
        [sys.executable, "-m", "celery", "-A", "services.scheduler.celery_app", "worker", pool_option, "--loglevel=info"],
        "Celery Worker"
    )

def start_celery_beat() -> Optional[subprocess.Popen]:
    """Start the Celery beat scheduler."""
     # Ensure services.scheduler.celery_app points to your Celery app instance
    # Add --scheduler django_celery_beat.schedulers:DatabaseScheduler if using DB scheduler
    return run_command(
        [sys.executable, "-m", "celery", "-A", "services.scheduler.celery_app", "beat", "--loglevel=info", "--pidfile="],
        "Celery Beat"
    )

def start_fastapi_app() -> Optional[subprocess.Popen]:
    """Start the FastAPI application using Uvicorn."""
    host = os.getenv("HOST", "0.0.0.0")
    port = os.getenv("PORT", "8000")
    # Use sys.executable to ensure using the same Python interpreter
    # Add --reload only if needed for development
    cmd = [sys.executable, "-m", "uvicorn", "main:app", "--host", host, "--port", port]
    if os.getenv("UVICORN_RELOAD", "false").lower() == "true":
         cmd.append("--reload")
         logger.info("Starting FastAPI with --reload enabled.")
    return run_command(cmd, "FastAPI App")

def load_env_file():
    """Load environment variables from .env file if present."""
    if is_docker():
        logger.info("Running in Docker - skipping .env file loading")
        return
    try:
        from dotenv import load_dotenv
        env_path = '.env'
        if os.path.exists(env_path):
            load_dotenv(dotenv_path=env_path, override=True) # Override ensures .env takes precedence
            logger.info("Loaded environment variables from .env file")
        else:
            logger.warning(".env file not found. Relying on system environment variables.")
    except ImportError:
        logger.warning("python-dotenv not installed. Cannot load .env file.")
    except Exception as e:
        logger.error(f"Error loading .env file: {e}")


def check_process_health(process, name):
    """Check if a process is still running."""
    if process and process.poll() is not None:
        logger.error(f"{name} has exited unexpectedly with code {process.returncode}")
        return False
    return True

def cleanup():
    """Terminate all running subprocesses."""
    logger.info("Shutting down all services...")
    stop_event.set() # Signal threads to stop logging

    # Terminate processes in reverse order of startup (optional, but sometimes helps)
    procs_to_terminate = list(reversed(processes))

    for process in procs_to_terminate:
        if process and process.poll() is None:  # If process is still running
            logger.info(f"Terminating process {process.pid}...")
            try:
                 # Try graceful termination first
                 if platform.system() == "Windows":
                     # Sending CTRL+C equivalent on Windows is complex, use terminate
                     process.terminate()
                 else:
                     process.send_signal(signal.SIGTERM)
            except Exception as e:
                 logger.warning(f"Could not send SIGTERM to process {process.pid}: {e}")
                 try:
                     process.terminate() # Fallback to terminate
                 except Exception as e2:
                     logger.error(f"Could not terminate process {process.pid}: {e2}")


    # Wait for processes to terminate
    timeout = 10 # Increased timeout
    deadline = time.time() + timeout
    logger.info(f"Waiting up to {timeout} seconds for processes to shut down...")

    remaining_processes = [p for p in procs_to_terminate if p and p.poll() is None]
    while remaining_processes and time.time() < deadline:
        time.sleep(0.2)
        remaining_processes = [p for p in procs_to_terminate if p and p.poll() is None]

    # Force kill any remaining processes
    force_killed = False
    for process in procs_to_terminate:
        if process and process.poll() is None:
            logger.warning(f"Process {process.pid} did not terminate gracefully. Forcing kill.")
            try:
                process.kill()
                force_killed = True
            except Exception as e:
                logger.error(f"Could not force kill process {process.pid}: {e}")

    if force_killed:
         logger.warning("Some processes were force-killed.")
    else:
         logger.info("All processes terminated.")

    logger.info("Cleanup complete.")


def signal_handler(sig, frame):
    """Handle termination signals."""
    logger.warning(f"Received signal {signal.Signals(sig).name}. Initiating shutdown...")
    if not stop_event.is_set(): # Prevent double execution
        stop_event.set()
        # Run cleanup in a separate thread to avoid blocking the signal handler
        cleanup_thread = threading.Thread(target=cleanup)
        cleanup_thread.start()
        # Give cleanup thread some time before exiting main thread
        cleanup_thread.join(timeout=15)
    # sys.exit might be handled by the caller or implicitly after handler returns


def set_telegram_webhook(webhook_url: str):
    """Set the Telegram bot webhook."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not set. Cannot configure webhook automatically.")
        return

    # Ensure the webhook URL points to your specific webhook endpoint
    # Assuming your FastAPI endpoint is at /api/webhook/telegram
    # Adjust the path '/api/webhook' if your endpoint is different
    full_webhook_url = f"{webhook_url}/api/webhook" #<-- ADJUST THIS PATH if needed
    telegram_api_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"

    logger.info(f"Attempting to set Telegram webhook to: {full_webhook_url}")

    try:
        # Using subprocess to run curl
        cmd = ["curl", "-s", "-X", "POST", "-H", "Content-Type: application/json",
               "-d", json.dumps({"url": full_webhook_url}), telegram_api_url]
        logger.debug(f"Running command: {' '.join(cmd)}")

        # Capture output to check result
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=10)

        if result.returncode == 0:
            try:
                response_data = json.loads(result.stdout)
                if response_data.get("ok"):
                    logger.info(f"Successfully set Telegram webhook: {response_data.get('description')}")
                else:
                    logger.error(f"Failed to set Telegram webhook. API Response: {result.stdout.strip()}")
            except json.JSONDecodeError:
                 logger.error(f"Failed to parse Telegram API response: {result.stdout.strip()}")
        else:
            logger.error(f"Failed to set Telegram webhook. curl command failed with code {result.returncode}.")
            logger.error(f"Stderr: {result.stderr.strip()}")
            logger.error(f"Stdout: {result.stdout.strip()}")

    except subprocess.TimeoutExpired:
         logger.error("Setting Telegram webhook timed out.")
    except FileNotFoundError:
         logger.error("Failed to set Telegram webhook: 'curl' command not found. Please install curl.")
    except Exception as e:
        logger.error(f"An unexpected error occurred while setting Telegram webhook: {e}")

def main():
    """Main function to start all services."""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if is_docker(): logger.info("Running in Docker environment")
    else: logger.info(f"Running on {platform.system()} platform")

    load_env_file()

    if not check_prerequisites():
        logger.error("Failed prerequisite checks. Exiting.")
        return 1

    port = int(os.getenv("PORT", "8000"))

    # Start ngrok tunnel first if needed (ngrok_url will be set globally)
    if not is_docker() or os.getenv("USE_NGROK", "").lower() in ("true", "1", "yes"):
        start_ngrok_tunnel(port) # ngrok_url is set globally if successful
    else:
        logger.info("Skipping ngrok tunnel based on environment (Docker/USE_NGROK).")


    # Start application services
    worker = start_celery_worker()
    beat = start_celery_beat()
    app = start_fastapi_app()

    # Allow a brief moment for processes to potentially fail early
    time.sleep(2)

    # Check if essential services started
    if not all([worker, beat, app]):
        logger.error("One or more essential services (Celery Worker, Celery Beat, FastAPI App) failed to start.")
        if not stop_event.is_set(): # Trigger cleanup if not already triggered
            stop_event.set()
            cleanup()
        return 1

    # --- Post-startup actions ---
    if ngrok_url:
        logger.info(f"Ngrok tunnel active: {ngrok_url}")
        logger.info("Attempting to auto-configure Telegram webhook...")
        set_telegram_webhook(ngrok_url) # Attempt to set webhook
        # Add similar calls here if you need to configure WhatsApp webhook automatically
        # e.g., configure_whatsapp_webhook(ngrok_url)
    else:
        host = os.getenv("HOST", "localhost") # Use localhost if bound to 0.0.0.0 for display
        if host == "0.0.0.0": host = "localhost" # Or get local IP if needed
        logger.info(f"Local server running at http://{host}:{port}")
        logger.warning("Ngrok tunnel not active or failed.")
        logger.warning("You may need to manually configure webhook URLs (Telegram, WhatsApp) if external access is required.")

    logger.info("--- WhatsApp Reminder & Calendar Bot is RUNNING ---")
    logger.info("Press Ctrl+C to stop all services")

    try:
        while not stop_event.is_set():
            if not check_process_health(worker, "Celery Worker") or \
               not check_process_health(beat, "Celery Beat") or \
               not check_process_health(app, "FastAPI App") or \
               (ngrok_process and not check_process_health(ngrok_process, "ngrok")):
                logger.error("One or more monitored services have terminated unexpectedly. Initiating shutdown.")
                stop_event.set()
                break
            time.sleep(2) # Check health every 2 seconds

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Initiating shutdown...")
        if not stop_event.is_set():
             stop_event.set() # Ensure stop event is set

    finally:
        logger.info("Starting final cleanup...")
        cleanup() # Ensure cleanup runs
        logger.info("Shutdown sequence finished.")

    # Determine exit code based on whether shutdown was graceful or due to error
    # This is tricky with signal handling; often just exiting 0 after cleanup is fine.
    # If a critical process failed, main might return 1 from the earlier check.
    return 0 # Or return 1 if a critical failure occurred before the loop

if __name__ == "__main__":
    # Ensure asyncio event loop policy is set correctly for Windows if needed
    # if platform.system() == "Windows":
    #      asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(main())