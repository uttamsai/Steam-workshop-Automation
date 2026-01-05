import os, re, json, time, requests, shutil
from datetime import datetime
from collections import Counter
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from http.cookiejar import MozillaCookieJar
from requests.cookies import create_cookie


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_ROOT = os.path.join(SCRIPT_DIR, "0 - output")
ensure_dir(OUTPUT_ROOT)

CONFIG = {
    "cookie_path": os.path.join(SCRIPT_DIR, "steam cookie.txt"),
    "use_cookies": True,      # set False to disable cookies entirely
    "base": "modlist",        # output folder name prefix
    "max_pages": 0,          # 0 = unlimited
    "delay": 0.4              # delay between page requests
}

# IO helpers 
def path_join(*parts):
    return os.path.join(*parts)

def write_lines(path, lines):
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path

def is_cookie_active(session) -> bool:
    """
    Robust login check: visit a page that requires auth and see if we get
    redirected to /login. If not redirected, cookies are active.
    """
    try:
        r = session.get("https://steamcommunity.com/my/edit", allow_redirects=True, timeout=20)
        return (r.status_code == 200) and ("login" not in r.url.lower())
    except Exception as e:
        print(f"[warn] Cookie check failed: {e}")
        return False

INVALID_FS_CHARS = '<>:"/\\|?*'

def sanitize_name(s: str) -> str:
    """Sanitize a string for Windows filesystem usage."""
    return "".join(c if c not in INVALID_FS_CHARS else "_" for c in s).strip().rstrip(".")

def detect_app_name(session, url: str) -> str | None:
    try:
        r = session.get(url, timeout=20)
        r.raise_for_status()
        html = r.text
    except Exception:
        return None

    m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not m:
        return None

    title = re.sub(r"\s+", " ", m.group(1)).strip()

    # Remove Steam workshop prefixes
    title = re.sub(r"(?i)steam\s*workshop\s*[:\-–]*\s*", "", title)
    title = re.sub(r"(?i)workshop\s*[:\-–]*\s*", "", title)

    # ✅ Remove trademark symbols
    title = title.replace("®", "").replace("™", "").replace("©", "")

    return sanitize_name(title)[:80] or None

UA = {"User-Agent": "Mozilla/5.0"}
RX_ID_URL = re.compile(r'filedetails/\?id=(\d+)')
RX_DATA_ATTR1 = re.compile(r'data-publishedfileid="(\d+)"')
RX_DATA_ATTR2 = re.compile(r'data-publishedfileid=\\"(\d+)\\"')
RX_APPID_QS = re.compile(r'(?:^|[?&])appid=(\d+)\b')
RX_APPID_ATTR = re.compile(r'data-appid="(\d+)"')
RX_APPID_ATTR_ESC = re.compile(r'data-appid=\\"(\d+)\\"')
RX_APPID_SCRIPT = re.compile(r'\b(BrowseAppId|PublishedFileService\.m_appid)\s*[:=]\s*["\']?(\d+)')

def _make_old_run_folder(root_dir: str) -> str:
    base = os.path.join(root_dir, "old runs")
    os.makedirs(base, exist_ok=True)
    day = datetime.now().strftime("%Y-%m-%d")
    target = os.path.join(base, day)
    if not os.path.exists(target):
        os.makedirs(target, exist_ok=True)
        return target
    # avoid collisions on multiple runs in the same day
    n = 2
    while True:
        alt = os.path.join(base, f"{day} ({n})")
        if not os.path.exists(alt):
            os.makedirs(alt, exist_ok=True)
            return alt
        n += 1


def archive_current_outputs(root_dir: str, paths: list[str]):
    """
    If any of the given paths exist, move them into today's 'old runs/<date>' folder.
    """
    to_move = [p for p in paths if os.path.exists(p)]
    if not to_move:
        return
    old_run_dir = _make_old_run_folder(root_dir)
    for p in to_move:
        shutil.move(p, os.path.join(old_run_dir, os.path.basename(p)))

def write_original_run_date_if_missing(root_dir: str):
    """
    Creates 'original_run_date.txt' the first time this game-appid folder is used.
    Does nothing on subsequent runs.
    """
    marker = os.path.join(root_dir, "run_date.txt")
    if not os.path.exists(marker):
        with open(marker, "w", encoding="utf-8") as f:
            f.write(datetime.now().isoformat(timespec="seconds"))


def set_page_param(raw_url, page_num):
    u = urlparse(raw_url)
    q = parse_qs(u.query)
    q["p"] = [str(page_num)]
    new_q = urlencode({k: v[0] for k, v in q.items()})
    return urlunparse((u.scheme, u.netloc, u.path, u.params, new_q, u.fragment))

def load_cookies(session, path):
    path = path.strip().strip('"').strip("'")
    if not os.path.exists(path):
        raise FileNotFoundError(f"cookies file not found: {path}")
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        head = fh.read(200)
    if head.lstrip().startswith("# Netscape"):
        jar = MozillaCookieJar()
        jar.load(path, ignore_discard=True, ignore_expires=True)
        session.cookies = jar
        return "netscape"
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        text = fh.read().strip()
    if text.startswith("{") or text.startswith("["):
        data = json.loads(text)
        if isinstance(data, dict):
            data = [data]
        loaded = 0
        for c in data:
            if not c.get("domain") or c.get("name") is None or c.get("value") is None:
                continue
            ck = create_cookie(domain=c["domain"], name=c["name"], value=c["value"],
                               path=c.get("path", "/"), secure=bool(c.get("secure", False)),
                               rest={"HttpOnly": c.get("httpOnly", False)})
            session.cookies.set_cookie(ck)
            loaded += 1
        if loaded == 0:
            raise ValueError("no usable cookies in JSON file")
        return "json"
    raise ValueError("unrecognized cookies format (expected Netscape or JSON)")

def extract_ids(html):
    ids = set(RX_ID_URL.findall(html))
    ids.update(RX_DATA_ATTR1.findall(html))
    ids.update(RX_DATA_ATTR2.findall(html))
    return ids

def looks_empty(html):
    for s in ("There are no items", "No items found", "This profile is private",
              "You must be logged in to view this content", "This item is private"):
        if s in html:
            return True
    return False

def fetch_ids(session, url, max_pages, delay):
    seen = set()
    empty_streak = 0
    p = 1
    unlimited = not max_pages or max_pages <= 0  # True if 0 or None

    while True:
        page_url = set_page_param(url, p)
        try:
            r = session.get(page_url, timeout=25)
            r.raise_for_status()
        except Exception as e:
            print(f"[warn] Page {p} failed: {e}")
            break
        html = r.text
        ids = extract_ids(html)
        new = [i for i in ids if i not in seen]
        if new:
            seen.update(new)
            print(f"[+] Page {p}: +{len(new)} (total {len(seen)})")
            empty_streak = 0
        else:
            empty_streak += 1
            print(f"[i] Page {p}: no new items (streak {empty_streak})")

        if looks_empty(html) or empty_streak >= 2:
            print("[i] Listing exhausted. Stopping.")
            break

        # Stop if we have a finite max_pages and reached it
        if not unlimited and p >= max_pages:
            print(f"[info] Reached configured max_pages ({max_pages}). Stopping.")
            break

        p += 1
        time.sleep(delay)

    return seen

def detect_appid(url, session):
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    if "appid" in q and q["appid"][0].isdigit():
        return q["appid"][0]
    try:
        r = session.get(set_page_param(url, 1), timeout=25)
        r.raise_for_status()
        html = r.text
    except Exception:
        return None
    cands = []
    cands += RX_APPID_QS.findall(html)
    cands += RX_APPID_ATTR.findall(html)
    cands += RX_APPID_ATTR_ESC.findall(html)
    cands += [m[1] for m in RX_APPID_SCRIPT.findall(html)]
    nums = [x for x in cands if x.isdigit()]
    return Counter(nums).most_common(1)[0][0] if nums else None

def fetch_titles_via_api(ids):
    """
    Batch-queries Steam's GetPublishedFileDetails API for titles.
    Returns: dict[str id] -> str title
    """
    if not ids:
        return {}
    url = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
    titles = {}
    BATCH = 100  # API lets 100 per call
    for i in range(0, len(ids), BATCH):
        batch = ids[i:i + BATCH]
        payload = {"itemcount": len(batch)}
        for j, wid in enumerate(batch):
            payload[f"publishedfileids[{j}]"] = str(wid)
        try:
            r = requests.post(url, data=payload, timeout=30)
            r.raise_for_status()
            js = r.json()
            for it in js.get("response", {}).get("publishedfiledetails", []):
                if it.get("result") == 1:
                    titles[str(it["publishedfileid"])] = (it.get("title") or "").strip()
        except Exception as e:
            print(f"[warn] title lookup failed for batch {i//BATCH+1}: {e}")
    return titles

# Main 
def main():
    print("=== Steam Workshop Scraper (organized outputs) ===")

    url = input("Paste any Workshop LISTING URL: ").strip()

    if not (url.startswith("https://steamcommunity.com/") and "workshop" in url):
        print("❌ Invalid Steam Workshop URL.")
        return
 
    cookie_path = CONFIG["cookie_path"]
    use_cookies = CONFIG["use_cookies"]
    base       = CONFIG["base"]
    max_pages  = CONFIG["max_pages"]
    delay      = CONFIG["delay"]

    # Detect AppID (and a readable game name) before setting paths
    s_meta = requests.Session()
    s_meta.headers.update(UA)
    if use_cookies and cookie_path:
        try:
            load_cookies(s_meta, cookie_path)
        except Exception:
            pass

    appid = detect_appid(url, s_meta)
    game_name = detect_app_name(s_meta, url) or (f"AppID_{appid}" if appid else None)

    # Root output dir: "<base> Steam Workshop Mods"
    # Root output dir: "<Game> - <appid>"  (no "Mod links")
    if appid and game_name:
        root_dir = os.path.join(OUTPUT_ROOT, f"{game_name} - {appid}")
    elif appid:
        root_dir = os.path.join(OUTPUT_ROOT, f"AppID - {appid}")
    else:
        root_dir = os.path.join(OUTPUT_ROOT, base)

    LISTS_SUBDIR = "lists"
    data_dir = os.path.join(root_dir, LISTS_SUBDIR)
    os.makedirs(data_dir, exist_ok=True)

    print("\n--- Fetching Workshop Listing ---")

    all_ids = set()
    cookies_loaded = False

    if use_cookies and cookie_path:
        s = requests.Session()
        s.headers.update(UA)
        try:
            fmt = load_cookies(s, cookie_path)
            print(f"✅ Loaded cookies ({fmt}) from {cookie_path}")
            if is_cookie_active(s):
                print("✅ Cookies active — fetching WITH cookies...")
                all_ids = fetch_ids(s, url, max_pages, delay)
                cookies_loaded = True
            else:
                print("⚠️ Cookies inactive — using NO cookies.")
        except Exception as e:
            print(f"⚠️ Failed to load cookies — using NO cookies: {e}")

    if not cookies_loaded:
        s_plain = requests.Session()
        s_plain.headers.update(UA)
        print("➡️ Fetching WITHOUT cookies...")
        all_ids = fetch_ids(s_plain, url, max_pages, delay)

    if not all_ids:
        print("❌ No items found.")
        return

    sorted_all = sorted(all_ids)

    # Output file paths
    ids_path        = path_join(data_dir, "ids.txt")
    ids_titles_path = path_join(data_dir, "ids_titles.txt")
    urls_path       = path_join(data_dir, "urls.txt")

    # Record original run date if this is the first time for this game/appid
    write_original_run_date_if_missing(root_dir)

    # Move previous run’s files into 'old runs/<YYYY-MM-DD>'
    archive_current_outputs(root_dir, [ids_path, ids_titles_path, urls_path])

    # Fetch titles and build lines AFTER archiving old files
    titles = fetch_titles_via_api(sorted_all)
    id_title_lines = [f"{mid}\t{titles.get(str(mid), '')}" for mid in sorted_all]

    # Write current run files
    write_lines(ids_path,  sorted_all)
    write_lines(urls_path, [f"https://steamcommunity.com/sharedfiles/filedetails/?id={x}" for x in sorted_all])
    write_lines(ids_titles_path, id_title_lines)

    print(f"\n✅ Saved ({len(sorted_all)}) to:\n"
        f"  • {ids_path}\n"
        f"  • {urls_path}\n"
        f"  • {ids_titles_path}")



if __name__ == "__main__":
    main()