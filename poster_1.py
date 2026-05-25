import requests
import json
import random
import sys
import signal
import hashlib
import mimetypes
import os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

SUPABASE_URL = "https://gcmoppkkplzztiayvbdk.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdjbW9wcGtrcGx6enRpYXl2YmRrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE2MTg5MTMsImV4cCI6MjA4NzE5NDkxM30.ZSgnOL471BMBIeDMlOp-RhuXGLk51rqDNektdoYHmC4"
BEARER       = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
GRAPHQL_ID   = "H-t2v_HvFR07ZBP9aOeKoA"
IMAGES_DIR   = "images"
MAX_WORKERS  = 5

PROXY_BASE   = "https://poster.qringgreen.workers.dev"

# Files that post with images (multi-image allowed)
IMAGE_COMMENT_FILES = [
    "comments/tc-comments.json",
    "comments/tg_comments.json",
]

# Files that post with exactly 1 image
SINGLE_IMAGE_COMMENT_FILES = [
    "comments/shd_comments.json",
]

# Files that post text only
TEXT_COMMENT_FILES = [
    "comments/xtl_comments.json",
    "comments/dl_comments.json",
]

IMAGE_PREFIX_MAP = {
    "comments/tc-comments.json":  "tweet-chain",
    "comments/tg_comments.json":  "tweet-generator",
    "comments/shd_comments.json": "shadowban",
}

SUPABASE_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
}

VERBOSE = False

def handle_exit(sig, frame):
    print("\nposter_1.py shutting down.")
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
    return requests.post(proxy_url, headers=merged, **kwargs)

def proxied_get(url, headers, **kwargs):
    parsed    = urlparse(url)
    proxy_url = PROXY_BASE + url[len(f"https://{parsed.netloc}"):]
    merged    = {**headers, "X-Target-Host": parsed.netloc}
    return requests.get(proxy_url, headers=merged, **kwargs)

# ── User Agents ───────────────────────────────────────────────────────────────

def load_user_agents(filepath="user_agents.txt"):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
    except FileNotFoundError:
        log_info("user_agents.txt not found, using fallback UAs.")
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

def ua_label(user_agent):
    if "Edg/" in user_agent or "Edge" in user_agent:
        return "Edge"
    if "Firefox" in user_agent:
        return "Firefox"
    if "Chrome" in user_agent:
        return "Chrome"
    return "Unknown"

# ── Headers ───────────────────────────────────────────────────────────────────

def build_request_headers(account, user_agent, referer="https://x.com/compose/post"):
    is_firefox = "Firefox" in user_agent
    return {
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
        "X-Client-Transaction-Id":   "IsQ5HjokzFsTNjSQFDarnZJ13YZl6YDqau05CICTKJieZF0I0bo0nsgM+aFOLL/RrpMp4CfP5jou5W0pBvBlaCoe3xfyIQ",
        "Origin":                    "https://x.com",
        "Referer":                   referer,
        "Sec-Fetch-Dest":            "empty",
        "Sec-Fetch-Mode":            "cors",
        "Sec-Fetch-Site":            "same-origin",
        "Sec-Gpc":                   "1" if is_firefox else "0",
    }

def build_upload_headers(account, user_agent):
    is_firefox = "Firefox" in user_agent
    return {
        "Authorization":       f"Bearer {BEARER}",
        "X-Csrf-Token":        account["x_csrf_token"],
        "X-Twitter-Auth-Type": "OAuth2Session",
        "Cookie":              account["cookie"],
        "User-Agent":          user_agent,
        "Accept":              "*/*",
        "Accept-Language":     "en-US,en;q=0.5",
        "Origin":              "https://x.com",
        "Referer":             "https://x.com/",
        "Sec-Fetch-Dest":      "empty",
        "Sec-Fetch-Mode":      "cors",
        "Sec-Fetch-Site":      "same-site",
        "Sec-Gpc":             "1" if is_firefox else "0",
    }

# ── DB ────────────────────────────────────────────────────────────────────────

def get_accounts():
    res = requests.get(
        f"{SUPABASE_URL}/rest/v1/x-monitor?select=id,name,cookie,x_csrf_token",
        headers=SUPABASE_HEADERS,
    )
    return [a for a in res.json() if a.get("cookie") and a.get("x_csrf_token")]

def get_account_state(account_id):
    res = requests.get(
        f"{SUPABASE_URL}/rest/v1/x-monitor-used-posts?account_id=eq.{account_id}",
        headers=SUPABASE_HEADERS,
    )
    data = res.json()
    return data[0] if data else None

def upsert_account_state(account_id, comment_file, post_id, status, reply_id=None, error=None):
    payload = {
        "account_id":   account_id,
        "comment_file": comment_file,
        "post_id":      post_id,
        "status":       status,
        "reply_id":     reply_id,
        "error":        error,
    }
    if reply_id:
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()

    existing = get_account_state(account_id)
    if existing:
        res = requests.patch(
            f"{SUPABASE_URL}/rest/v1/x-monitor-used-posts?account_id=eq.{account_id}",
            headers=SUPABASE_HEADERS,
            json=payload,
        )
    else:
        res = requests.post(
            f"{SUPABASE_URL}/rest/v1/x-monitor-used-posts",
            headers=SUPABASE_HEADERS,
            json=payload,
        )
    return res.status_code in [200, 201, 204]

def increment_block_count(account_id, error_code):
    state         = get_account_state(account_id)
    current_count = state.get("block_count", 0) if state else 0
    payload = {
        "account_id":  account_id,
        "block_count": current_count + 1,
        "block_code":  error_code,
    }
    if state:
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/x-monitor-used-posts?account_id=eq.{account_id}",
            headers=SUPABASE_HEADERS,
            json=payload,
        )
    else:
        requests.post(
            f"{SUPABASE_URL}/rest/v1/x-monitor-used-posts",
            headers=SUPABASE_HEADERS,
            json=payload,
        )

# ── Comments ──────────────────────────────────────────────────────────────────

def load_comments(file):
    try:
        with open(file, "r", encoding="utf-8", errors="replace") as f:
            content = f.read().strip()
        if not content:
            return []
        return json.loads(content)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def pick_comment(account_state, comment_files, exclude_post_id=None):
    used_file    = account_state.get("comment_file") if account_state else None
    used_post_id = account_state.get("post_id")      if account_state else None

    comment_file = random.choice(comment_files)
    comments     = load_comments(comment_file)
    if not comments:
        return None, None

    available = [
        c for c in comments
        if not (comment_file == used_file and c["id"] == used_post_id)
        and c["id"] != exclude_post_id
    ]
    if not available:
        available = comments

    return comment_file, random.choice(available)

# ── Images ────────────────────────────────────────────────────────────────────

def get_images_for_comment_file(comment_file):
    prefix = IMAGE_PREFIX_MAP.get(comment_file)
    if not prefix or not os.path.isdir(IMAGES_DIR):
        return []
    return [
        os.path.join(IMAGES_DIR, f)
        for f in os.listdir(IMAGES_DIR)
        if prefix in f and os.path.isfile(os.path.join(IMAGES_DIR, f))
    ]

def upload_image(filepath, account, user_agent, account_name):
    with open(filepath, "rb") as f:
        image_bytes = f.read()

    mime_type, _ = mimetypes.guess_type(filepath)
    if not mime_type:
        mime_type = "image/jpeg"

    md5            = hashlib.md5(image_bytes).hexdigest()
    upload_headers = build_upload_headers(account, user_agent)
    json_upload_headers = {
        **upload_headers,
        "Content-Type":              "application/json",
        "X-Twitter-Active-User":     "yes",
        "X-Twitter-Client-Language": "en",
    }

    # INIT
    resp = proxied_post(
        "https://upload.x.com/i/media/upload.json",
        headers=upload_headers,
        params={
            "command":        "INIT",
            "total_bytes":    len(image_bytes),
            "media_type":     mime_type,
            "media_category": "tweet_image",
        },
    )
    if resp.status_code not in [200, 201, 202]:
        log(account_name, f"Image INIT failed ({resp.status_code}): {resp.text[:200]}")
        return None

    media_id = resp.json().get("media_id_string")
    if not media_id:
        log(account_name, "Image INIT returned no media_id")
        return None

    # APPEND
    resp = proxied_post(
        "https://upload.x.com/i/media/upload.json",
        headers=upload_headers,
        params={
            "command":          "APPENDMULTI",
            "media_id":         media_id,
            "segment_indexes":  0,
            "max_segment_size": len(image_bytes),
            "media_md5":        md5,
        },
        files={"media": ("blob", image_bytes, "application/octet-stream")},
    )
    if resp.status_code not in [200, 201, 202, 204]:
        log(account_name, f"Image APPEND failed ({resp.status_code}): {resp.text[:200]}")
        return None

    # FINALIZE
    resp = proxied_post(
        "https://upload.x.com/i/media/upload.json",
        headers=upload_headers,
        params={"command": "FINALIZE", "media_id": media_id},
    )
    if resp.status_code not in [200, 201, 202]:
        log(account_name, f"Image FINALIZE failed ({resp.status_code}): {resp.text[:200]}")
        return None

    # Metadata
    proxied_post(
        "https://x.com/i/api/1.1/media/metadata/create.json",
        headers=json_upload_headers,
        json={
            "media_id": media_id,
            "allow_download_status": {"allow_download": "true"},
        },
    )

    return media_id

def upload_images_for_comment(comment_file, account, user_agent, account_name):
    images = get_images_for_comment_file(comment_file)
    if not images:
        return []

    # shd_comments.json: always exactly 1 image
    # IMAGE_COMMENT_FILES: 1 or 2 images
    if comment_file in SINGLE_IMAGE_COMMENT_FILES:
        count = 1
    else:
        count = random.randint(1, min(2, len(images)))

    selected  = random.sample(images, min(count, len(images)))
    media_ids = []
    for img in selected:
        media_id = upload_image(img, account, user_agent, account_name)
        if media_id:
            media_ids.append(media_id)
            log(account_name, f"Uploaded {os.path.basename(img)} -> media_id {media_id}")
    return media_ids

# ── Tweet ─────────────────────────────────────────────────────────────────────

def post_reply(account, conversation_id, text, media_ids, user_agent):
    media_entities = [{"media_id": mid, "tagged_users": []} for mid in (media_ids or [])]

    payload = {
        "variables": {
            "tweet_text": text,
            "reply": {
                "in_reply_to_tweet_id":   conversation_id,
                "exclude_reply_user_ids": [],
            },
            "media": {
                "media_entities":     media_entities,
                "possibly_sensitive": False,
            },
            "semantic_annotation_ids":     [],
            "disallowed_reply_options":    None,
            "semantic_annotation_options": {"source": "Unknown"},
        },
        "features": {
            "premium_content_api_read_enabled": False,
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
            "responsive_web_grok_analyze_post_followups_enabled": True,
            "rweb_cashtags_composer_attachment_enabled": True,
            "responsive_web_jetfuel_frame": True,
            "responsive_web_grok_share_attachment_enabled": True,
            "responsive_web_grok_annotations_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "rweb_conversational_replies_downvote_enabled": False,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "content_disclosure_indicator_enabled": True,
            "content_disclosure_ai_generated_indicator_enabled": True,
            "responsive_web_grok_show_grok_translated_post": True,
            "responsive_web_grok_analysis_button_from_backend": True,
            "post_ctas_fetch_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": False,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "responsive_web_profile_redirect_enabled": False,
            "rweb_tipjar_consumption_enabled": False,
            "verified_phone_label_enabled": False,
            "articles_preview_enabled": True,
            "rweb_cashtags_enabled": True,
            "responsive_web_grok_community_note_auto_translation_is_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "responsive_web_grok_image_annotation_enabled": True,
            "responsive_web_grok_imagine_annotation_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
        },
        "queryId": GRAPHQL_ID,
    }

    res = proxied_post(
        f"https://x.com/i/api/graphql/{GRAPHQL_ID}/CreateTweet",
        headers=build_request_headers(account, user_agent),
        json=payload,
    )
    return res.status_code, res.json()

def extract_reply_id(response):
    errors = response.get("errors")
    if errors:
        code    = errors[0].get("code")
        message = errors[0].get("message", "Unknown error")
        return None, code, message
    try:
        reply_id = response["data"]["create_tweet"]["tweet_results"]["result"]["rest_id"]
        return reply_id, None, None
    except (KeyError, TypeError):
        preview = json.dumps(response)[:300]
        return None, None, f"Unexpected response: {preview}"

# ── Per-account worker ────────────────────────────────────────────────────────

def process_account(account, conversation_id):
    account_id    = account["id"]
    account_name  = account["name"]
    account_state = get_account_state(account_id)

    user_agent = pick_user_agent()
    browser    = ua_label(user_agent)

    log(account_name, f"Starting | Browser: {browser}")

    # Weighted pool: image (multi), single-image, or text-only
    pool_choice = random.choices(
        ["image", "single_image", "text"],
        weights=[40, 30, 30],
        k=1,
    )[0]

    if pool_choice == "image":
        comment_pool = IMAGE_COMMENT_FILES
    elif pool_choice == "single_image":
        comment_pool = SINGLE_IMAGE_COMMENT_FILES
    else:
        comment_pool = TEXT_COMMENT_FILES

    success       = False
    last_file     = None
    last_comment  = None
    last_status   = None
    last_response = None
    exclude_post  = None

    for attempt in range(1, 4):
        comment_file, comment = pick_comment(
            account_state,
            comment_files   = comment_pool,
            exclude_post_id = exclude_post,
        )

        if not comment_file or not comment:
            log(account_name, "No comment available, skipping.")
            break

        last_file    = comment_file
        last_comment = comment

        media_ids = []
        needs_image = (
            comment_file in IMAGE_COMMENT_FILES or
            comment_file in SINGLE_IMAGE_COMMENT_FILES
        )
        if needs_image:
            media_ids = upload_images_for_comment(comment_file, account, user_agent, account_name)
            if not media_ids:
                log(account_name, f"Attempt {attempt}: Image upload failed, retrying with different comment.")
                exclude_post = comment["id"]
                continue

        source = os.path.basename(comment_file).replace(".json", "")
        log(account_name, f"Attempt {attempt}: Posting from '{source}' | Images: {len(media_ids)}")

        try:
            last_status, last_response = post_reply(
                account, conversation_id, comment["text"], media_ids, user_agent
            )
        except Exception as e:
            log(account_name, f"Attempt {attempt}: Request error: {e}")
            exclude_post = comment["id"]
            continue

        if last_status == 200:
            reply_id, api_error_code, api_error_msg = extract_reply_id(last_response)

            if api_error_code in [226, 344]:
                log(account_name, f"Blocked by X (error {api_error_code}): {api_error_msg}")
                increment_block_count(account_id, api_error_code)
                break

            if reply_id:
                ok = upsert_account_state(
                    account_id   = account_id,
                    comment_file = comment_file,
                    post_id      = comment["id"],
                    status       = "success",
                    reply_id     = reply_id,
                )
                log(account_name, f"Reply posted | reply_id: {reply_id} | DB: {'saved' if ok else 'failed'}")
                success = True
                break
            else:
                log(account_name, f"Attempt {attempt}: {api_error_msg}, retrying.")
                exclude_post = comment["id"]
        else:
            log(account_name, f"Attempt {attempt}: HTTP {last_status}, retrying.")
            exclude_post = comment["id"]

    if not success and last_file and last_comment:
        last_error_code = None
        if last_response:
            errors = last_response.get("errors", [{}])
            last_error_code = errors[0].get("code") if errors else None
        if last_error_code not in [226, 344]:
            ok = upsert_account_state(
                account_id   = account_id,
                comment_file = last_file,
                post_id      = last_comment["id"],
                status       = f"failed_{last_status}",
                error        = str(last_response),
            )
            log(account_name, f"All attempts failed | DB: {'saved' if ok else 'failed'}")

    return account_name, success

# ── Main ──────────────────────────────────────────────────────────────────────

def run(conversation_id):
    log_info(f"poster_1.py started | Tweet: {conversation_id} | Agents loaded: {len(USER_AGENTS)}")
    if VERBOSE:
        log_info("Verbose mode ON")

    accounts = get_accounts()
    if not accounts:
        log_info("No accounts found in DB.")
        sys.exit(0)

    log_info(f"Processing {len(accounts)} accounts (up to {MAX_WORKERS} concurrent)")
    print()

    results = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_account, account, conversation_id): account["name"]
            for account in accounts
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                acct_name, success = future.result()
                results[acct_name] = success
            except Exception as e:
                log_info(f"Worker error for {name}: {e}")
                results[name] = False

    print()
    succeeded = sum(1 for v in results.values() if v)
    log_info(f"Done. {succeeded}/{len(accounts)} accounts succeeded.")

    for name, ok in results.items():
        print(f"  {'OK' if ok else 'FAILED'}  {name}")

    sys.exit(0)

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Usage: python3 poster_1.py <conversation_id> [--verbose]")
        sys.exit(1)

    conversation_id = args[0]
    VERBOSE         = "--verbose" in args

    run(conversation_id)