import os
import sys
import time
import argparse
import subprocess
import shutil

#  helpers

def run(cmd, capture=False):
    """Run a shell command, return (returncode, stdout)."""
    result = subprocess.run(
        cmd, shell=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    return result.returncode, (result.stdout or b"").decode().strip()


def section(title):
    print(f"\n{'─'*52}")
    print(f"  {title}")
    print(f"{'─'*52}")


# Redis management

def redis_is_running():
    code, out = run("redis-cli ping", capture=True)
    return code == 0 and out.strip() == "PONG"


def docker_is_running():
    code, _ = run("docker info", capture=True)
    return code == 0


def start_redis_docker():
    section("Starting Redis via Docker Compose")
    code, _ = run("docker compose up -d")
    if code != 0:
        return False
    # wait for health check
    for i in range(10):
        time.sleep(2)
        if redis_is_running():
            print(" Redis is up (Docker)")
            return True
        print(f"  Waiting for Redis … ({i+1}/10)")
    return False


def start_redis_homebrew():
    section("Starting Redis via Homebrew")
    if not shutil.which("brew"):
        return False
    # install if needed
    code, _ = run("brew list redis", capture=True)
    if code != 0:
        print("  Installing Redis via Homebrew …")
        run("brew install redis")
    run("brew services start redis")
    time.sleep(3)
    if redis_is_running():
        print(" Redis is up (Homebrew)")
        return True
    return False


def ensure_redis():
    """Try Docker first, fall back to Homebrew."""
    section("Checking Redis")

    if redis_is_running():
        print(" Redis already running")
        return "already_running"

    if docker_is_running():
        print("  Docker is available — starting Redis container …")
        if start_redis_docker():
            return "docker"
        print("  Docker start failed — trying Homebrew …")

    if start_redis_homebrew():
        return "homebrew"

    return None


def stop_redis(method):
    if method == "docker":
        section("Stopping Redis container")
        run("docker compose down")
        print(" Redis container stopped")
    elif method == "homebrew":
        section("Stopping Redis service")
        run("brew services stop redis")
        print(" Redis service stopped")


#  run scripts

def run_script(path, label):
    section(label)
    code = subprocess.call([sys.executable, path])
    if code != 0:
        print(f"{label} exited with code {code}")
        return False
    return True


# main

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-llm",   action="store_true",
                        help="Skip LLM query generation (no API key needed)")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Leave Redis running after script finishes")
    args = parser.parse_args()

    print("so_analytics — Bonus Orchestrator")
  

    # Step 1: Start Redis
    redis_method = ensure_redis()
    if not redis_method:
        print("\n Could not start Redis.")
        print("     Install Docker Desktop  : https://www.docker.com/products/docker-desktop")
        print("     Or install Homebrew Redis: brew install redis")
        sys.exit(1)

    results = {}

    # Step 2: Redis cache demo
    results["redis_cache"] = run_script("bonus/redis_cache.py", "Redis Cache Demo")

    # Step 3: LLM query generation
    if args.skip_llm:
        section("LLM Query Generation")
        print("  [SKIPPED] --skip-llm flag set")
        results["llm"] = None
    elif not os.getenv("ANTHROPIC_API_KEY"):
        section("LLM Query Generation")
        print("  [SKIPPED] ANTHROPIC_API_KEY not set in .env")
        print("  Add it to .env and run:  python bonus/llm_query_gen.py")
        results["llm"] = None
    else:
        results["llm"] = run_script("bonus/llm_query_gen.py", "LLM Query Generation")

    # Step 4: Cleanup
    if not args.no_cleanup and redis_method not in ("already_running",):
        stop_redis(redis_method)

    # Summary
    if results["redis_cache"]:
        print("\n  Output files:")
        print("    bonus/redis_cache.py   → terminal output (screenshot for report)")
        if results["llm"]:
            print("    llm_evidence.json      → prompts + responses (include in report)")


if __name__ == "__main__":
    main()
