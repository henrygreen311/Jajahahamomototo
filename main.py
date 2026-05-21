import requests
import time
import signal
import sys
import subprocess
from datetime import datetime

MONITOR_URL = "https://x-monitor.qringgreen.workers.dev/"

handled_tweets = set()
VERBOSE        = "--verbose"  in sys.argv
LIKE_ONLY      = "--like"     in sys.argv
REPOST_ONLY    = "--repost"   in sys.argv

def handle_exit(sig, frame):
    print("\nShutting down gracefully...")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

def run_script(script, *args):
    cmd = ["python3", script] + list(args)
    if VERBOSE:
        cmd.append("--verbose")
    try:
        subprocess.run(cmd, check=False)
    except Exception as e:
        print(f"  [!] Failed to launch {script}: {e}")

def run():
    print("main.py started. Press Ctrl+C to stop.")

    if LIKE_ONLY:
        print("Mode: --like (skip poster_1.py, like original tweet directly)")
    elif REPOST_ONLY:
        print("Mode: --repost (skip poster_1.py and tw_like.py, repost only)")
    if VERBOSE:
        print("Verbose mode ON")

    while True:
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{ts}] Checking for new tweets...")

        try:
            tweets = requests.get(MONITOR_URL, timeout=30).json()
        except Exception as e:
            print(f"  Monitor error: {e}")
            time.sleep(60)
            continue

        if not tweets:
            print("  No recent tweets found.")
            time.sleep(60)
            continue

        for tweet in tweets:
            conversation_id = tweet.get("conversation_id_str")
            rest_id         = tweet.get("restId")
            if not conversation_id:
                continue

            if conversation_id in handled_tweets:
                print(f"  Already handled {conversation_id}, skipping.")
                continue

            print(f"  New tweet from {rest_id}: {conversation_id}")

            if REPOST_ONLY:
                print(f"  Launching reposter.py...")
                run_script("reposter.py", conversation_id)

            elif LIKE_ONLY:
                print(f"  Launching tw_like.py with conversation_id...")
                run_script("tw_like.py", conversation_id)

            else:
                # Normal mode: reply -> like -> repost
                print(f"  Launching poster_1.py...")
                run_script("poster_1.py", conversation_id)

                print(f"  Launching tw_like.py...")
                run_script("tw_like.py")

                print(f"  Launching reposter.py...")
                run_script("reposter.py", conversation_id)

            handled_tweets.add(conversation_id)

        time.sleep(60)

if __name__ == "__main__":
    run()