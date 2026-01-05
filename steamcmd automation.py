import os
import re
import json
import time
import requests
import subprocess
import getpass

CONFIG = {
    "skip_already_downloaded": True,  # skip what’s already installed
    "check_updates": True,            # also skip if up to date (ACF vs remote)
    "require_nonempty_on_disk": True  # only consider installed if folder has files/size
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_ROOT = os.path.join(SCRIPT_DIR, "0 - output")

steamcmd_exe = os.path.join(SCRIPT_DIR, "steamcmd", "steamcmd.exe")
RUN_DIR = os.path.join(SCRIPT_DIR, "steamcmd", "run")
os.makedirs(RUN_DIR, exist_ok=True)

def read_ids(path):
    ids = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line.isdigit():
                ids.append(line)
    return ids

def get_installed_ids(appid):
    """Return set of installed Workshop IDs from the app's ACF file."""
    acf_path = os.path.join(SCRIPT_DIR, "steamcmd", "steamapps", "workshop", f"appworkshop_{appid}.acf")
    if not os.path.exists(acf_path):
        return set()
    with open(acf_path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    return set(re.findall(r'"(\d+)"\s*\{[^}]*"timeupdated"', text))

def _find_modlink_folders():
    out = []
    if os.path.isdir(OUTPUT_ROOT):
        for name in os.listdir(OUTPUT_ROOT):
            full = os.path.join(OUTPUT_ROOT, name)
            # match folders whose name ends with " - <digits>"
            if os.path.isdir(full) and re.search(r"\s-\s\d+$", name):
                out.append(full)
    return sorted(out)

def content_dir_for_app(appid: str) -> str:
    """Path where SteamCMD puts workshop content for appid."""
    return os.path.join(SCRIPT_DIR, "steamcmd", "steamapps", "workshop", "content", str(appid))

def mod_folder_path(appid: str, modid: str) -> str:
    return os.path.join(content_dir_for_app(appid), str(modid))

def folder_has_content(path: str) -> bool:
    """Return True if folder exists and contains at least one file with non-zero size."""
    if not os.path.isdir(path):
        return False
    for root, _, files in os.walk(path):
        for fn in files:
            try:
                if os.path.getsize(os.path.join(root, fn)) > 0:
                    return True
            except OSError:
                pass
    return False

def get_installed_map(appid: str) -> dict:
    """
    Parse appworkshop_<appid>.acf and return { id: timeupdated_int }.
    """
    acf_path = os.path.join(SCRIPT_DIR, "steamcmd", "steamapps", "workshop", f"appworkshop_{appid}.acf")
    if not os.path.isfile(acf_path):
        return {}
    with open(acf_path, "r", encoding="utf-8", errors="ignore") as f:
        txt = f.read()

    out = {}
    # Match blocks like:  "<id>" { ... "timeupdated" "<num>" ... }
    for m in re.finditer(r'"\s*(\d{6,})\s*"\s*{\s*([^}]*)}', txt, flags=re.S):
        mid = m.group(1)
        block = m.group(2)
        tu = 0
        mt = re.search(r'"\s*timeupdated\s*"\s*"\s*(\d+)\s*"', block)
        if mt:
            try:
                tu = int(mt.group(1))
            except:
                tu = 0
        out[mid] = tu
    return out

def fetch_remote_timeupdated(ids: list[str]) -> dict[str, int]:
    """
    Call ISteamRemoteStorage/GetPublishedFileDetails to get each id's 'time_updated'.
    Returns { id: time_updated_int }. Unknown → 0.
    """
    if not ids:
        return {}
    url = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
    out = {}
    BATCH = 100
    for i in range(0, len(ids), BATCH):
        chunk = ids[i:i+BATCH]
        data = {"itemcount": len(chunk)}
        for idx, mid in enumerate(chunk):
            data[f"publishedfileids[{idx}]"] = mid
        try:
            r = requests.post(url, data=data, timeout=25)
            r.raise_for_status()
            j = r.json()
            for item in j.get("response", {}).get("publishedfiledetails", []):
                mid = str(item.get("publishedfileid", ""))
                tu = int(item.get("time_updated", 0) or 0)
                if mid:
                    out[mid] = tu
        except Exception as e:
            print(f"[warn] time_updated fetch failed for {len(chunk)} ids: {e}")
        time.sleep(0.25)
    return out

def _choose_folder():
    folders = _find_modlink_folders()
    if not folders:
        print(f'No "<Game> - <AppID>" folders found in "{OUTPUT_ROOT}".')
        return None
    if len(folders) == 1:
        print(f'Found: {os.path.basename(folders[0])}')
        return folders[0]
    print("Select an output folder:")
    for i, p in enumerate(folders, 1):
        print(f"  {i}. {os.path.basename(p)}")
    while True:
        s = input("Enter number: ").strip()
        if s.isdigit() and 1 <= int(s) <= len(folders):
            return folders[int(s) - 1]
        print("Invalid choice. Try again.")

def ask_file():
    """Return (ids_file_path, chosen_folder) pointing to ids.txt in the selected folder."""
    folder = _choose_folder()
    if not folder:
        return None, None

    # Prefer new structure: <Game - AppID>/lists/ids.txt
    new_path = os.path.join(folder, "lists", "ids.txt")
    if os.path.exists(new_path):
        print("Using ids.txt in 'lists' subfolder.")
        return new_path, folder

    # Fallback: <Game - AppID>/ids.txt (legacy)
    legacy_path = os.path.join(folder, "ids.txt")
    if os.path.exists(legacy_path):
        print("Using ids.txt in selected folder.")
        return legacy_path, folder

    print("No ids.txt found in 'lists' or folder root.")
    return None, folder

def ask_appid(folder):
    # "<Game>-<appid> Mod links"
    name = os.path.basename(folder)
    m = re.search(r"\s-\s(\d+)$", name)
    if m:
        return m.group(1)
    # fallback to manual if parsing fails
    while True:
        a = input("Enter AppID: ").strip()
        if a.isdigit():
            return a
        print("Invalid AppID. Try again.\n")

if __name__ == "__main__":
    print("=== Simple SteamCMD Mod Downloader ===")

    steam_username = input("Steam username: ").strip()
    if not steam_username:
        print("Username required.")
        exit()

    steam_password = input("Steam password: ")

    ids_file, chosen_folder = ask_file()
    if not ids_file:
        print("No ids.txt found; exiting.")
        raise SystemExit(1)

    appid = ask_appid(chosen_folder)

    ids = read_ids(ids_file)
    print(f"\nLoaded {len(ids)} IDs.\n")

    # Filter out installed & up-to-date mods; force re-download for empty folders
    if CONFIG.get("skip_already_downloaded", True):
        installed_map = get_installed_map(appid)  # {id: timeupdated_int}
        if installed_map:
            installed_ids = set(installed_map.keys())

            # 4a) If required, drop “installed” items whose on-disk folders are empty
            if CONFIG.get("require_nonempty_on_disk", True):
                actually_present = set()
                empty_or_missing = set()
                for mid in installed_ids:
                    if folder_has_content(mod_folder_path(appid, mid)):
                        actually_present.add(mid)
                    else:
                        empty_or_missing.add(mid)
                if empty_or_missing:
                    print(f"[disk] {len(empty_or_missing)} installed ids have empty/missing folders → will re-download those.")
            else:
                actually_present = installed_ids
                empty_or_missing = set()

            # Base new set: anything not in actually_present is brand-new
            new_ids = [i for i in ids if i not in actually_present]

            # 4b) Update check: include installed-but-outdated
            if CONFIG.get("check_updates", True):
                to_check = [i for i in ids if i in actually_present]
                remote_map = fetch_remote_timeupdated(to_check)
                need_update = []
                up_to_date = 0
                for mid in to_check:
                    local_t = installed_map.get(mid, 0)
                    remote_t = remote_map.get(mid, 0)
                    if remote_t > local_t:
                        need_update.append(mid)
                    else:
                        up_to_date += 1
                # force re-download for empty/missing even if up-to-date
                need_redownload = list(empty_or_missing)
                pending = new_ids + need_update + need_redownload
                # De-duplicate while preserving order from original ids
                seen = set()
                pending = [x for x in ids if x in set(pending) and (x not in seen and not seen.add(x))]
                print(f"[acf] Installed: {len(installed_ids)} | Up-to-date: {up_to_date} | Need update: {len(need_update)} | "
                    f"Empty/missing: {len(empty_or_missing)} | New: {len(new_ids)}")
                print(f"[acf] Will fetch {len(pending)} items.")
                ids = pending
            else:
                # No update check: fetch newly missing + empty/missing
                base = new_ids + list(empty_or_missing)
                seen = set()
                pending = [x for x in ids if x in set(base) and (x not in seen and not seen.add(x))]
                skipped = len(ids) - len(pending)
                print(f"[acf] Skipping {skipped} already downloaded mods (including empty/missing requeue). {len(pending)} left to fetch.")
                ids = pending
        else:
            print("[acf] No ACF file or no installed mods found — proceeding with all IDs.")


    # Write a runscript next to the IDs file
    runscript_path = os.path.join(RUN_DIR, "steamcmd_run.txt")
    with open(runscript_path, "w", encoding="utf-8") as f:
        for modid in ids:
            f.write(f"workshop_download_item {appid} {modid}\n")
        f.write("quit\n")

    # Call steamcmd once, pointing to the runscript
    cmd = [steamcmd_exe, "+login", steam_username, steam_password, "+runscript", runscript_path]

    print("\nRunning SteamCMD...\n")
    subprocess.run(cmd)

    # After SteamCMD completes, check ACF presence and on-disk content
    installed_after_map = get_installed_map(appid)
    installed_after_ids = set(installed_after_map.keys())
    failed = []
    for mid in ids:
        folder_ok = folder_has_content(mod_folder_path(appid, mid))
        in_acf = (mid in installed_after_ids)
        if not (folder_ok and in_acf):
            failed.append(mid)

    if failed:
        print(f"\n⚠️ {len(failed)} mods failed or are empty. Writing to failed_ids.txt...")
        fail_path = os.path.join(chosen_folder, "failed_ids.txt")
        with open(fail_path, "w", encoding="utf-8") as f:
            f.write("\n".join(failed))
        print(f"  • Saved list to {fail_path}")
    else:
        print("\n✅ All mods appear to have downloaded correctly and contain files!")



