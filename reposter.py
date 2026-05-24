import requests
import random
import sys
import signal
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

SUPABASE_URL = "https://gcmoppkkplzztiayvbdk.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdjbW9wcGtrcGx6enRpYXl2YmRrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE2MTg5MTMsImV4cCI6MjA4NzE5NDkxM30.ZSgnOL471BMBIeDMlOp-RhuXGLk51rqDNektdoYHmC4"
BEARER       = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
GRAPHQL_ID   = "mbRO74GrOvSfRcJnlMapnQ"
MAX_WORKERS  = 5

PROXY_BASE   = "https://poster.qringgreen.workers.dev"

SUPABASE_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
}

VERBOSE = "--verbose" in sys.argv

def handle_exit(sig, frame):
    print("\nreposter.py shutting down.")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)

# ── Logging ───────────────────────────────────────────────────────────────────

LOG_LOCK = __import__("threading").Lock()

def log(account_name, message):
    ts = datetime.now().strftime("%H:%M:%S")
    with LOG_LOCK:
        print(f"[{ts}] {account_name}: {message}")

def log_info(message):
    ts = datetime.now().strftime("%H:%M:%S")
    with LOG_LOCK:
        print(f"[{ts}] {message}")

# ── Proxy ─────────────────────────────────────────────────────────────────────

def proxied_post(url, headers, **kwargs):
    parsed    = urlparse(url)
    proxy_url = PROXY_BASE + url[len(f"https://{parsed.netloc}"):]
    merged    = {**headers, "X-Target-Host": parsed.netloc}
    res       = requests.post(proxy_url, headers=merged, **kwargs)

    raw = res.text.strip()
    if not raw:
        return res.status_code, None

    try:
        return res.status_code, res.json()
    except Exception:
        return res.status_code, {"_raw": raw[:300]}

# ── User Agents ───────────────────────────────────────────────────────────────

def load_user_agents(filepath="user_agents.txt"):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
    except FileNotFoundError:
        return [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
        ]
    filtered = [l for l in lines if any(k in l for k in ["Chrome", "Firefox", "Edg/", "Edge"])]
    return filtered if filtered else lines

USER_AGENTS = load_user_agents()

def pick_user_agent():
    return random.choice(USER_AGENTS)

def ua_label(ua):
    if "Edg/" in ua or "Edge" in ua: return "Edge"
    if "Firefox" in ua:              return "Firefox"
    if "Chrome" in ua:               return "Chrome"
    return "Unknown"

# ── DB ────────────────────────────────────────────────────────────────────────

def get_accounts():
    res = requests.get(
        f"{SUPABASE_URL}/rest/v1/x-monitor?select=id,name,cookie,x_csrf_token",
        headers=SUPABASE_HEADERS,
    )
    data = res.json()
    if not isinstance(data, list):
        log_info(f"DB accounts error: {data}")
        return []
    return [a for a in data if a.get("cookie") and a.get("x_csrf_token")]

# ── Retweet ───────────────────────────────────────────────────────────────────

def retweet(account, tweet_id, user_agent):
    is_firefox = "Firefox" in user_agent
    headers = {
        "Cookie":                    account["cookie"],
        "X-Csrf-Token":              account["x_csrf_token"],
        "Authorization":             f"Bearer {BEARER}",
        "User-Agent":                user_agent,
        "Accept":                    "*/*",
        "Accept-Language":           "en-US,en;q=0.5",
        "Content-Type":              "application/json",
        "X-Twitter-Auth-Type":       "OAuth2Session",
        "X-Twitter-Client-Language": "en",
        "X-Twitter-Active-User":     "yes",
		"X-Client-Transaction-Id":  "jXYRGKk63lXeBAXYDGjdz0JllxiOUL/75BMlSJp9N/tsRFYAEtkI891sx7Cr3Fv+5kaZT4i6qm6vm9wqyOIwvO+aPmB0jg",
        "Origin":                    "https://x.com",
        "Referer":                   "https://x.com/home",
        "Sec-Fetch-Dest":            "empty",
        "Sec-Fetch-Mode":            "cors",
        "Sec-Fetch-Site":            "same-origin",
        "Sec-Gpc":                   "1" if is_firefox else "0",
    }
    payload = {
        "variables": {"tweet_id": tweet_id},
        "queryId":   GRAPHQL_ID,
    }
    return proxied_post(
        f"https://x.com/i/api/graphql/{GRAPHQL_ID}/CreateRetweet",
        headers=headers,
        json=payload,
    )

# ── Per-account worker ────────────────────────────────────────────────────────

def process_account(account, tweet_id):
    account_name = account["name"]
    user_agent   = pick_user_agent()

    log(account_name, f"Starting | Browser: {ua_label(user_agent)}")

    try:
        status, response = retweet(account, tweet_id, user_agent)

        if response is None:
            log(account_name, f"Failed | Empty response (HTTP {status})")
            return

        if "_raw" in response:
            log(account_name, f"Failed | Non-JSON (HTTP {status}): {response['_raw']}")
            return

        errors = response.get("errors") if isinstance(response, dict) else None

        if status == 200 and not errors:
            try:
                retweet_id = response["data"]["create_retweet"]["retweet_results"]["result"]["rest_id"]
                log(account_name, f"Retweeted | retweet_id: {retweet_id}")
            except (KeyError, TypeError):
                log(account_name, "Retweeted (no retweet_id in response)")
        else:
            code = errors[0].get("code")    if errors else status
            msg  = errors[0].get("message") if errors else str(response)
            log(account_name, f"Failed | code {code}: {str(msg)[:200]}")
            if VERBOSE:
                log(account_name, json.dumps(response, indent=2))

    except Exception as e:
        log(account_name, f"Error: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────

def run(tweet_id):
    log_info(f"reposter.py started | Tweet: {tweet_id}")

    accounts = get_accounts()
    if not accounts:
        log_info("No accounts in DB.")
        return

    log_info(f"Retweeting with {len(accounts)} accounts (up to {MAX_WORKERS} concurrent)")
    print()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_account, account, tweet_id): account["name"]
            for account in accounts
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
            except Exception as e:
                log_info(f"Worker error for {name}: {e}")

    print()
    log_info("reposter.py done.")

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("Usage: python3 reposter.py <tweet_id> [--verbose]")
        sys.exit(1)

    run(args[0])