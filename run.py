#!/usr/bin/env python
"""
Telegram Reminder & Calendar Bot - Consolidated Launcher Script
This script provides a unified method to start all required services:
- Redis server (if not running)
- FastAPI application
- Celery worker
- Celery beat scheduler
- Ngrok tunnel for exposing the API
- Telegram webhook configuration (automatically sets up webhook URL)

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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
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
        # Common Redis installation paths on Windows
        redis_paths = [
            r"C:\Program Files\Redis\redis-server.exe",
            r"C:\Program Files (x86)\Redis\redis-server.exe",
            r"C:\Redis\redis-server.exe",
            # Add more potential paths as needed
        ]
        
        # Check if redis-cli.exe is in PATH (might indicate redis-server.exe is too)
        redis_cli = shutil.which("redis-cli.exe")
        if redis_cli:
            potential_server = os.path.join(os.path.dirname(redis_cli), "redis-server.exe")
            if os.path.exists(potential_server):
                return potential_server
        
        # Check the common paths
        for path in redis_paths:
            if os.path.exists(path):
                return path
                
        # If no Redis executable found, try to use the name directly (might be in PATH)
        return "redis-server.exe"
    else:
        # On Unix systems, try to find redis-server in PATH
        redis_server = shutil.which("redis-server")
        if redis_server:
            return redis_server
        return "redis-server"  # Assume it's in PATH

def find_ngrok_executable():
    """Find ngrok executable based on platform."""
    ngrok_cmd = "ngrok.exe" if platform.system() == "Windows" else "ngrok"
    ngrok_path = shutil.which(ngrok_cmd)
    if ngrok_path:
        return ngrok_path
    
    # Additional search paths for ngrok
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
    
    return ngrok_cmd  # Return base command as last resort

def is_redis_running():
    """Check if Redis server is already running."""
    try:
        import redis
        r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        return True
    except (redis.exceptions.ConnectionError, ImportError):
        return False

#Disabling Redis server start on Render
# def start_redis_server():
#     """Start Redis server if it's not already running."""
#     global redis_process
    
#     # Skip if in Docker (assume Redis is managed separately)
#     if is_docker():
#         logger.info("Running in Docker - assuming Redis is managed by Docker Compose")
#         return None
        
#     # Skip if Redis is already running
#     if is_redis_running():
#         logger.info("Redis server is already running")
#         return None
    
#     redis_executable = find_redis_executable()
#     logger.info(f"Starting Redis server using {redis_executable}")
    
#     try:
#         redis_process = subprocess.Popen(
#             [redis_executable],
#             stdout=subprocess.PIPE,
#             stderr=subprocess.PIPE,
#             text=True,
#             bufsize=1,
#             universal_newlines=True
#         )
#         processes.append(redis_process)
        
#         # Start threads to read and log output
#         def log_output(stream, level):
#             for line in stream:
#                 logger.log(level, f"[Redis] {line.strip()}")
#                 if stop_event.is_set():
#                     break
        
#         threading.Thread(target=log_output, args=(redis_process.stdout, logging.INFO), daemon=True).start()
#         threading.Thread(target=log_output, args=(redis_process.stderr, logging.ERROR), daemon=True).start()
        
#         # Give Redis a moment to start
#         time.sleep(2)
        
#         # Verify Redis is now running
#         if is_redis_running():
#             logger.info("Redis server started successfully")
#             return redis_process
#         else:
#             logger.error("Redis server failed to start properly")
#             if redis_process.poll() is None:
#                 redis_process.terminate()
#             return None
            
#     except Exception as e:
#         logger.error(f"Failed to start Redis server: {e}")
#         return None

def start_redis_server():
    """Disable starting Redis server on Render."""
    logger.info("Skipping Redis server start - using external Redis on Render")
    return None


def start_ngrok_tunnel(port):
    """Start ngrok tunnel to expose the local server to the internet."""
    global ngrok_process, ngrok_url
    
    # Skip if in Docker and not explicitly requested to use ngrok
    if is_docker() and not os.getenv("USE_NGROK", "").lower() in ("true", "1", "yes"):
        logger.info("Running in Docker - skipping ngrok tunnel unless USE_NGROK is set")
        return None
    
    ngrok_executable = find_ngrok_executable()
    logger.info(f"Starting ngrok tunnel using {ngrok_executable}")
    
    try:
        # Start ngrok process
        ngrok_process = subprocess.Popen(
            [ngrok_executable, "http", str(port), "--log=stdout"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        processes.append(ngrok_process)
        
        # Start thread to read and log output
        def log_output(stream, level):
            for line in stream:
                logger.log(level, f"[ngrok] {line.strip()}")
                if stop_event.is_set():
                    break
        
        threading.Thread(target=log_output, args=(ngrok_process.stdout, logging.INFO), daemon=True).start()
        threading.Thread(target=log_output, args=(ngrok_process.stderr, logging.ERROR), daemon=True).start()
        
        # Give ngrok a moment to start
        time.sleep(2)
        
        # Get the public URL from the ngrok API
        try:
            with urlopen("http://localhost:4040/api/tunnels") as response:
                data = json.loads(response.read().decode())
                tunnels = data.get('tunnels', [])
                if tunnels:
                    ngrok_url = tunnels[0]['public_url']
                    logger.info(f"ngrok tunnel established: {ngrok_url}")
                    
                    # Set environment variable for webhook URL
                    os.environ["WEBHOOK_URL"] = ngrok_url
                    logger.info(f"Set WEBHOOK_URL environment variable to {ngrok_url}")
                    
                    return ngrok_process
                else:
                    logger.error("No ngrok tunnels found")
                    return None
        except Exception as e:
            logger.error(f"Failed to get ngrok URL: {e}")
            return None
            
    except Exception as e:
        logger.error(f"Failed to start ngrok: {e}")
        return None

def configure_telegram_webhook(webhook_url):
    """Configure Telegram webhook using the TelegramWebhookManager."""
    try:
        # Import the TelegramWebhookManager class
        from webhook_manager import TelegramWebhookManager
        
        # Create a webhook manager instance
        webhook_manager = TelegramWebhookManager()
        
        # Construct the full webhook URL (add /webhook endpoint if not present)
        if not webhook_url.endswith('/api/webhook'):
            webhook_url = webhook_url.rstrip('/') + '/api/webhook'
        
        logger.info(f"Configuring Telegram webhook at: {webhook_url}")
        
        # Set up the webhook
        result = webhook_manager.register_webhook(webhook_url)
        
        if not result.get("error"):
            logger.info("Telegram webhook configured successfully!")
            return True
        else:
            registration_error = result.get("message", "Unknown error")
            logger.error(f"Failed to configure Telegram webhook: {registration_error}")
            return False
    
    except ImportError:
        logger.error("Could not import TelegramWebhookManager. Please ensure telegram_webhook_manager.py is in your project.")
        return False
    except Exception as e:
        logger.error(f"Error configuring Telegram webhook: {e}")
        return False

def check_prerequisites() -> bool:
    """Verify all prerequisites are installed and available."""
    logger.info("Checking prerequisites...")
    
    # Check Python version
    python_version = sys.version_info
    if python_version.major < 3 or (python_version.major == 3 and python_version.minor < 9):
        logger.error("Python 3.9 or higher is required")
        return False
    
    # Check for Redis - start it if needed
    if not is_redis_running():
        redis_proc = start_redis_server()
        if not redis_proc and not is_docker():
            logger.error("Redis server is not running and could not be started")
            return False
    else:
        logger.info("Redis server is running")
    
    # Check for required environment variables
    required_env_vars = [
        "TELEGRAM_BOT_TOKEN"
    ]
    
    # In Docker, these might be set differently or at runtime
    if not is_docker():
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]
        if missing_vars:
            logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
            logger.error("Please add them to your .env file")
            return False
    
    # Check for ngrok
    ngrok_executable = find_ngrok_executable()
    if not shutil.which(ngrok_executable):
        logger.warning(f"ngrok not found at {ngrok_executable}")
        logger.warning("Please install ngrok to expose the app to the internet")
        logger.warning("The app will still run locally without ngrok")
    else:
        logger.info(f"ngrok found at {ngrok_executable}")
    
    # Check if database needs initialization
    try:
        from database import init_db, check_db_initialized
        if not check_db_initialized():
            logger.info("Initializing database...")
            init_db()
    except ImportError:
        logger.error("Could not import database module. Make sure it's in the project path.")
        return False
    
    return True

def run_command(cmd: List[str], name: str) -> Optional[subprocess.Popen]:
    """Run a system command in a subprocess."""
    try:
        logger.info(f"Starting {name}...")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        processes.append(process)
        
        # Start threads to read and log output
        def log_output(stream, level):
            for line in stream:
                logger.log(level, f"[{name}] {line.strip()}")
                if stop_event.is_set():
                    break
        
        threading.Thread(target=log_output, args=(process.stdout, logging.INFO), daemon=True).start()
        threading.Thread(target=log_output, args=(process.stderr, logging.ERROR), daemon=True).start()
        
        return process
    except Exception as e:
        logger.error(f"Failed to start {name}: {e}")
        return None

def start_celery_worker() -> Optional[subprocess.Popen]:
    """Start the Celery worker process."""
    return run_command(
        ["celery", "-A", "services.scheduler.celery_app", "worker", "--loglevel=info","--pool=solo"],
        "Celery Worker"
    )

def start_celery_beat() -> Optional[subprocess.Popen]:
    """Start the Celery beat scheduler."""
    return run_command(
        ["celery", "-A", "services.scheduler.celery_app", "beat", "--loglevel=info"],
        "Celery Beat"
    )

def start_fastapi_app() -> Optional[subprocess.Popen]:
    """Start the FastAPI application."""
    # Get host and port from environment or use defaults
    host = os.getenv("HOST", "0.0.0.0")
    port = os.getenv("PORT", "8000")
    
    return run_command(
        ["uvicorn", "main:app", "--host", host, "--port", port],
        "FastAPI App"
    )

def load_env_file():
    """Load environment variables from .env file if present."""
    # Skip in Docker (environment variables should be passed to the container)
    if is_docker():
        logger.info("Running in Docker - skipping .env file loading")
        return
        
    try:
        from dotenv import load_dotenv
        load_dotenv()
        logger.info("Loaded environment variables from .env file")
        
    except ImportError:
        logger.warning("python-dotenv not installed. Ensure environment variables are set manually.")

def check_process_health(process, name):
    """Check if a process is still running."""
    if process and process.poll() is not None:
        logger.error(f"{name} has exited with code {process.returncode}")
        return False
    return True

def cleanup():
    """Terminate all running processes."""
    logger.info("Shutting down all services...")
    
    # Signal all processes to terminate
    for process in processes:
        if process.poll() is None:  # If process is still running
            process.terminate()
    
    # Wait for processes to terminate gracefully
    timeout = 5
    deadline = time.time() + timeout
    
    while time.time() < deadline:
        if all(process.poll() is not None for process in processes):
            break
        time.sleep(0.1)
    
    # Force kill any remaining processes
    for process in processes:
        if process.poll() is None:
            process.kill()
    
    logger.info("All services have been shut down")

def signal_handler(sig, frame):
    """Handle termination signals."""
    logger.info(f"Received signal {sig}")
    stop_event.set()
    cleanup()
    sys.exit(0)
    
def main():
    """Main function to start all services."""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Log environment
    if is_docker():
        logger.info("Running in Docker environment")
    else:
        logger.info(f"Running on {platform.system()} platform")
    
    # Load environment variables
    load_env_file()
    
    # Check prerequisites
    if not check_prerequisites():
        logger.error("Failed to meet prerequisites. Exiting.")
        return 1
    
    # Start services
    port = int(os.getenv("PORT", "8000"))
    
    # Start ngrok tunnel first to establish webhook URL
    start_ngrok_tunnel(port)
    
    # Configure Telegram webhook if ngrok URL is available
    if ngrok_url and not is_docker():
        webhook_configured = configure_telegram_webhook(ngrok_url)
        if webhook_configured:
            logger.info("Telegram webhook configured successfully")
        else:
            logger.warning("Telegram webhook configuration failed, continuing startup")
    
    # Start the application services
    worker = start_celery_worker()
    beat = start_celery_beat()
    app = start_fastapi_app()
    
    if not all([worker, beat, app]):
        logger.error("Failed to start all services. Cleaning up...")
        stop_event.set()
        cleanup()
        return 1
    
    try:
        # Monitor services and keep the main thread alive
        logger.info("All services started successfully")
        logger.info("Telegram Reminder & Calendar Bot is now running")
        
        if ngrok_url:
            logger.info(f"Your webhook URL is: {ngrok_url}")
            logger.info("This URL has been automatically configured for your Telegram bot")
        else:
            logger.info(f"Local server running at http://localhost:{port}")
            logger.info("You'll need to configure an accessible webhook URL for Telegram callbacks")
        
        logger.info("Press Ctrl+C to stop all services")
        
        while not stop_event.is_set():
            # Check if any process has terminated unexpectedly
            if not check_process_health(worker, "Celery Worker") or \
               not check_process_health(beat, "Celery Beat") or \
               not check_process_health(app, "FastAPI App") or \
               (ngrok_process and not check_process_health(ngrok_process, "ngrok")):
                logger.error("One or more services have terminated unexpectedly")
                stop_event.set()
                break
            
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        stop_event.set()
        cleanup()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())