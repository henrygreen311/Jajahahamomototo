import requests
import json
import sys
import time
import signal
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

SUPABASE_URL = "https://gcmoppkkplzztiayvbdk.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdjbW9wcGtrcGx6enRpYXl2YmRrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE2MTg5MTMsImV4cCI6MjA4NzE5NDkxM30.ZSgnOL471BMBIeDMlOp-RhuXGLk51rqDNektdoYHmC4"
BEARER       = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
GRAPHQL_ID   = "lI07N6Otwv1PhnEgXILM7A"

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

VERBOSE = "--verbose" in sys.argv

def handle_exit(sig, frame):
    print("\ntw_like.py shutting down.")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

# ── DB ────────────────────────────────────────────────────────────────────────

def get_accounts():
    res = requests.get(
        f"{SUPABASE_URL}/rest/v1/x-monitor?select=id,name,cookie,x_csrf_token",
        headers=SUPABASE_HEADERS,
    )
    data = res.json()
    if not isinstance(data, list):
        print(f"DB accounts error: {data}")
        return []
    return [a for a in data if a.get("cookie") and a.get("x_csrf_token")]

def get_recent_reply_ids():
    # Fetch all successful rows with a reply_id — filter by time locally
    res = requests.get(
        f"{SUPABASE_URL}/rest/v1/x-monitor-used-posts"
        f"?select=reply_id,updated_at"
        f"&status=eq.success"
        f"&reply_id=neq.null",
        headers=SUPABASE_HEADERS,
    )
    data = res.json()
    if not isinstance(data, list):
        print(f"DB reply_ids error: {data}")
        return []

    now     = datetime.now(timezone.utc)
    cutoff  = now - timedelta(minutes=5)
    ids     = []

    for row in data:
        updated_at = row.get("updated_at")
        reply_id   = row.get("reply_id")
        if not updated_at or not reply_id:
            continue
        try:
            # Supabase returns e.g. "2026-05-19T01:52:42.058588+00:00"
            ts = datetime.fromisoformat(updated_at)
            if ts >= cutoff:
                ids.append(reply_id)
        except Exception as e:
            print(f"Could not parse updated_at '{updated_at}': {e}")
            continue

    ids = list(set(ids))
    print(f"Found {len(ids)} reply_id(s) updated in the last 5 minutes.")
    return ids

# ── Like ──────────────────────────────────────────────────────────────────────

def like_tweet(account, tweet_id):
    payload = {
        "variables": {"tweet_id": tweet_id},
        "queryId":   GRAPHQL_ID,
    }
    res = requests.post(
        f"https://x.com/i/api/graphql/{GRAPHQL_ID}/FavoriteTweet",
        headers={
            "Cookie":                    account["cookie"],
            "X-Csrf-Token":              account["x_csrf_token"],
            "Authorization":             f"Bearer {BEARER}",
            "User-Agent":                "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
            "Accept":                    "*/*",
            "Accept-Language":           "en-US,en;q=0.5",
            "Content-Type":              "application/json",
            "X-Twitter-Auth-Type":       "OAuth2Session",
            "X-Twitter-Client-Language": "en",
            "X-Twitter-Active-User":     "yes",
            "Origin":                    "https://x.com",
            "Referer":                   "https://x.com/",
        },
        json=payload,
    )
    return res.status_code, res.json()

def process_account(account, tweet_ids):
    account_name = account["name"]
    for tweet_id in tweet_ids:
        try:
            status, response = like_tweet(account, tweet_id)
            errors = response.get("errors") if isinstance(response, dict) else None

            if status == 200 and not errors:
                print(f"{account_name}: liked {tweet_id}")
            else:
                code = errors[0].get("code") if errors else status
                msg  = errors[0].get("message", str(response)) if errors else str(response)
                print(f"{account_name}: failed {tweet_id} | code {code}: {msg}")
                if VERBOSE:
                    print(json.dumps(response, indent=2))
        except Exception as e:
            print(f"{account_name}: error on {tweet_id}: {e}")

        time.sleep(1)

# ── Main ──────────────────────────────────────────────────────────────────────

def run(tweet_ids=None):
    print("tw_like.py started.")

    accounts = get_accounts()
    if not accounts:
        print("No accounts in DB.")
        sys.exit(0)

    if tweet_ids is None:
        tweet_ids = get_recent_reply_ids()

    if not tweet_ids:
        print("No tweet IDs to like.")
        sys.exit(0)

    print(f"Liking {len(tweet_ids)} tweet(s) across {len(accounts)} account(s).")

    with ThreadPoolExecutor(max_workers=len(accounts)) as executor:
        futures = {
            executor.submit(process_account, account, tweet_ids): account["name"]
            for account in accounts
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"Worker error for {name}: {e}")

    print("tw_like.py done.")
    sys.exit(0)

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        run(tweet_ids=args)
    else:
        run()