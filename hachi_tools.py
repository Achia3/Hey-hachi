import os
import sys
import subprocess
import glob
import webbrowser
import requests
import json
import psutil
import logging
import threading
import time
import shutil
import re
import winreg
from hachi_db import search_history, add_task

# logging is configured by hachi_app.py (only one basicConfig call)

# Prime psutil's CPU baseline at import so non-blocking cpu_percent(interval=None)
# reads reflect activity since launch (including the LLM work that just ran)
# instead of returning 0.0 on the first call.
try:
    psutil.cpu_percent(interval=None)
except Exception:
    pass

# App execution paths
APP_PATHS = {
    "discord": [
        r"C:\Users\{user}\AppData\Local\Discord\app-*\Discord.exe",
        "discord.exe",
    ],
    "steam": [
        r"C:\Program Files (x86)\Steam\steam.exe",
        r"C:\Program Files\Steam\steam.exe",
        "steam.exe",
    ],
    "vscode": [
        r"C:\Users\{user}\AppData\Local\Programs\Microsoft VS Code\Code.exe",
        r"C:\Program Files\Microsoft VS Code\Code.exe",
        "code",
    ],
    "spotify": [
        r"C:\Users\{user}\AppData\Roaming\Spotify\Spotify.exe",
        r"C:\Program Files\Spotify\Spotify.exe",
        "spotify.exe",
    ],
    "chatgpt": [
        r"C:\Users\{user}\AppData\Local\Programs\ChatGPT\ChatGPT.exe",
        r"C:\Program Files\ChatGPT\ChatGPT.exe",
        "ChatGPT.exe",
    ]
}

# Common-app aliases → real executable names (fixes "calculator" → calc, etc.)
APP_ALIASES = {
    "calculator": "calc",
    "calc": "calc",
    "paint": "mspaint",
    "paint 3d": "ms-paint",
    "wordpad": "write",
    "word pad": "write",
    "control panel": "control",
    "file explorer": "explorer",
    "explorer": "explorer",
    "this pc": "explorer",
    "settings": "ms-settings",
    "terminal": "wt",
    "powershell": "powershell",
    "cmd": "cmd",
    "command prompt": "cmd",
    "task manager": "taskmgr",
    "snipping tool": "SnippingTool",
    "photos": "ms-photos",
    "camera": "ms-camera",
    "mail": "ms-outlook",
    "clock": "ms-clock",
    "maps": "ms-maps",
    "microsoft edge": "msedge",
    "edge": "msedge",
    "notepad": "notepad",
}

def _resolve_app_paths(app_name: str):
    """Resolve via the Windows 'App Paths' registry — the standard mechanism that
    maps 'blender' → blender.exe for virtually every installed GUI app."""
    app = app_name.lower().strip()
    wanted = {app, f"{app}.exe"}
    base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    for hive, flags in ((winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
                        (winreg.HKEY_LOCAL_MACHINE, 0),
                        (winreg.HKEY_CURRENT_USER, 0)):
        try:
            key = winreg.OpenKey(hive, base, 0, winreg.KEY_READ | flags)
            try:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    sub = winreg.EnumKey(key, i).lower()
                    if sub in wanted or sub == f"{app}.exe":
                        try:
                            v = winreg.QueryValue(key, winreg.EnumKey(key, i))
                        except OSError:
                            continue
                        # App Paths values can be quoted
                        v = v.strip('"')
                        if v and os.path.exists(v):
                            return v
                        # value may include arguments after the exe path
                        if v and " " in v and os.path.exists(v.split(" ")[0]):
                            return v.split(" ")[0]
            finally:
                winreg.CloseKey(key)
        except OSError:
            continue
    return None


def _glob_program_files(app_name: str):
    """Recursively search %LOCALAPPDATA% + Program Files (+X86) for <query>.exe.
    Bounded to the first match to keep it fast. Returns a path or None."""
    name = app_name.lower().strip()
    exe_name = name if name.endswith(".exe") else f"{name}.exe"
    roots = set()
    for env in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        p = os.environ.get(env)
        if p and os.path.isdir(p):
            roots.add(p)
    for root in roots:
        try:
            for hit in glob.iglob(os.path.join(root, "**", exe_name), recursive=True):
                if os.path.isfile(hit):
                    return hit
        except Exception:
            continue
    return None


def _resolve_windows_app(app_name: str):
    """Resolve a Windows app name to an executable path.
    Order: aliases → shutil.which → system32 → App Paths registry. Returns path or None."""
    name = app_name.lower().strip()
    alias = APP_ALIASES.get(name, name)

    # 1. shutil.which handles PATH executables AND WindowsApps UWP aliases
    resolved = shutil.which(alias) or shutil.which(f"{alias}.exe")
    if resolved:
        return resolved

    # 2. Known system32 paths for classic Windows apps
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    for exe in (f"{alias}.exe", f"{name}.exe"):
        p = os.path.join(system32, exe)
        if os.path.exists(p):
            return p

    # 3. App Paths registry (covers most installed GUI apps)
    return _resolve_app_paths(name) or _resolve_app_paths(alias)

def get_app_path(app_name):
    """Resolve executable path for application."""
    if app_name not in APP_PATHS:
        return app_name
    username = os.getenv('USERNAME', 'User')
    for path_pattern in APP_PATHS[app_name]:
        path = path_pattern.replace("{user}", username)
        if '*' in path:
            matches = glob.glob(path)
            if matches:
                return matches[0]
        if os.path.exists(path):
            return path
    return APP_PATHS[app_name][-1]

def _lnk_target(path: str):
    """Resolve a .lnk shortcut's target executable via WScript.Shell. Returns a
    lowercase exe name (e.g. 'blender.exe') or None. Used to match shortcuts
    whose filename differs from the app name (e.g. 'Blender 3D.lnk')."""
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        shell = win32com.client.Dispatch("WScript.Shell")
        lnk = shell.CreateShortCut(path)
        target = (lnk.TargetPath or "")
        if target:
            return os.path.basename(target).lower()
    except Exception:
        pass
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
    return None


def find_app_in_start_menu(app_name: str):
    """Search Windows Start Menu shortcuts for any installed application.
    Covers all Start Menu roots (APPDATA, PROGRAMDATA, LOCALAPPDATA) and matches
    both the .lnk filename AND the shortcut's target exe."""
    search_dirs = [
        os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
        os.path.join(os.environ.get('PROGRAMDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
    ]
    app_lower = app_name.lower().strip()
    app_words = [w for w in app_lower.split() if w]
    best_match = None

    for base_dir in search_dirs:
        if not os.path.isdir(base_dir):
            continue
        for root, dirs, files in os.walk(base_dir):
            for f in files:
                if not f.lower().endswith('.lnk'):
                    continue
                name = f[:-4].lower()
                # Exact substring match on filename
                if app_lower in name or name in app_lower:
                    return os.path.join(root, f)
                # All words present (fuzzy)
                if app_words and all(w in name for w in app_words):
                    best_match = os.path.join(root, f)
                    continue
                # Match against the shortcut's TARGET exe (catches display-name mismatch)
                target = _lnk_target(os.path.join(root, f))
                if target:
                    t = os.path.splitext(target)[0]
                    if app_lower in t or t in app_lower or (app_words and all(w in t for w in app_words)):
                        return os.path.join(root, f)

    return best_match

def launch_app(app_name, args=None):
    """Launch app process with protocol fallbacks for 100% reliability on any PC.
    Returns a user-facing spoken confirmation (not a bare bool)."""
    if not app_name or not app_name.strip():
        return "No application specified to open."
    success_msg = f"Opening {app_name}."
    try:
        app_clean = app_name.lower().strip()

        if app_clean == "chatgpt":
            app_path = get_app_path("chatgpt")
            if os.path.exists(app_path):
                subprocess.Popen([app_path], shell=False)
            else:
                webbrowser.open("https://chatgpt.com")
            return success_msg

        if app_clean == "steam":
            if args and "-bigpicture" in args:
                try:
                    os.system("start steam://open/bigpicture")
                    return success_msg
                except Exception:
                    pass
            app_path = get_app_path("steam")
            if os.path.exists(app_path):
                cmd = [app_path] + (args if args else [])
                subprocess.Popen(cmd, shell=False)
                return success_msg
            else:
                os.system("start steam://open/main")
                return success_msg

        if app_clean == "spotify":
            app_path = get_app_path("spotify")
            if os.path.exists(app_path):
                subprocess.Popen([app_path], shell=False)
            else:
                os.system("start spotify:")
            return success_msg

        if app_clean == "discord":
            app_path = get_app_path("discord")
            if os.path.exists(app_path):
                subprocess.Popen([app_path], shell=False)
            else:
                os.system("start discord:")
            return success_msg

        # Try resolving the app path FIRST (alias-aware) — this is more reliable
        # than a Start Menu shortcut, which can match misleading utility shortcuts
        # (e.g. "VLC - reset preferences" instead of the actual player).
        app_path = _resolve_windows_app(app_name) or get_app_path(app_name)
        if app_path:
            try:
                cmd = [app_path]
                if args:
                    cmd.extend(args if isinstance(args, list) else [args])
                subprocess.Popen(cmd, shell=False)
                logging.info(f"Launched application: {app_name} ({app_path})")
                return success_msg
            except Exception as e:
                logging.warning(f"Popen failed for {app_name}: {e}")
                # Fall through to Start Menu + os.system fallback

    except Exception as e:
        logging.warning(f"Launch prep failed for {app_name}: {e}")

    # ── Unified fallback chain (always reached) ──────────────────────────
    # Try Start Menu shortcut discovery
    shortcut = find_app_in_start_menu(app_name)
    if shortcut:
        try:
            os.startfile(shortcut)
            logging.info(f"Launched via Start Menu shortcut: {shortcut}")
            return success_msg
        except Exception:
            pass

    # Try alias-aware resolution (calculator→calc, paint→mspaint, UWP aliases, etc.)
    resolved = _resolve_windows_app(app_name)
    if resolved:
        try:
            subprocess.Popen([resolved], shell=False)
            logging.info(f"Launched via resolve: {resolved}")
            return success_msg
        except Exception:
            pass

    # Try UWP / protocol handler via `start <alias>:`
    alias = APP_ALIASES.get(app_name.lower().strip(), app_name.lower().strip())
    if alias.startswith("ms-") or alias in ("wt",):
        try:
            os.system(f'start "" "{alias}:"')
            logging.info(f"Launched via UWP protocol: {alias}:")
            return success_msg
        except Exception:
            pass

    # Try globbing Program Files for <query>.exe (last-resort resolution)
    exe_path = _glob_program_files(app_name)
    if exe_path:
        try:
            subprocess.Popen([exe_path], shell=False)
            logging.info(f"Launched via Program Files glob: {exe_path}")
            return success_msg
        except Exception:
            pass

    # Final truthful fallback: os.startfile uses ShellExecute (resolves App Paths
    # + file associations) and RAISES on failure — so we never fake success.
    try:
        os.startfile(app_name)
        logging.info(f"Launched via os.startfile: {app_name}")
        return success_msg
    except Exception as e:
        logging.warning(f"Could not open {app_name} via any method: {e}")
        return f"Sorry, I couldn't find or open {app_name}."

def close_app(app_name: str):
    """Close ANY application running on Windows by process or app name."""
    if not app_name or not app_name.strip():
        return "No application specified to close."   # CRITICAL: empty name would match every process
    closed_any = False
    app_clean = app_name.lower().replace(".exe", "").strip()
    
    name_map = {
        "chrome": "chrome",
        "google chrome": "chrome",
        "notepad": "notepad",
        "calculator": "calc",
        "calc": "calc",
        "spotify": "spotify",
        "steam": "steam",
        "discord": "discord",
        "vs code": "code",
        "vscode": "code",
        "code": "code",
        # Microsoft Office
        "ms word": "winword",
        "word": "winword",
        "microsoft word": "winword",
        "ms excel": "excel",
        "excel": "excel",
        "microsoft excel": "excel",
        "ms powerpoint": "powerpnt",
        "powerpoint": "powerpnt",
        "microsoft powerpoint": "powerpnt",
        "ms outlook": "outlook",
        "outlook": "outlook",
        "microsoft outlook": "outlook",
        "ms teams": "teams",
        "teams": "teams",
        "microsoft teams": "teams",
        # Games / Riot
        "valorant": "valorant",
        "league of legends": "league",
        "league": "league",
        "lol": "league",
        "riot": "riot",
    }
    # Fall back to the shared launch alias map (calculator→calc, etc.) so close
    # and launch stay consistent.
    target_pattern = name_map.get(app_clean, APP_ALIASES.get(app_clean, app_clean))

    # Process FAMILIES: some apps are bundles of processes with different names.
    # "close valorant" must kill RiotClientServices + Valorant + Vanguard, not
    # just valorant.exe (which may not even be running if only the client is open).
    process_families = {
        "valorant": ["valorant", "riot", "vanguard", "riotclientservices", "riotclientcrashhandler"],
        "league": ["league", "riot", "leagueoflegends"],
        "riot": ["riot", "valorant", "vanguard", "league"],
        "chrome": ["chrome"],
    }
    family = process_families.get(target_pattern)

    terminated_list = []
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            pname = proc.info['name'].lower()
            if family:
                # match any process in the family
                matched = any(re.search(rf'\b{re.escape(f)}\b', pname, re.IGNORECASE) for f in family)
            else:
                # Word-boundary matching: "code" matches "Code.exe" but not "codec" or "decoder"
                target_escaped = re.escape(target_pattern)
                matched = bool(re.search(rf'\b{target_escaped}\b', pname, re.IGNORECASE))
            if matched:
                try:
                    proc.kill()
                except Exception:
                    pass
                subprocess.Popen(f'taskkill /F /T /IM "{proc.info["name"]}"', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                closed_any = True
                terminated_list.append(proc.info['name'])
                logging.info(f"Force killed process {pname} (PID: {proc.info['pid']})")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if closed_any:
        msg = f"Closed application(s): {', '.join(set(terminated_list))}."
    else:
        msg = f"Could not find any active process matching '{app_name}' to close."
        
    add_task(f"Close App: {app_name}", "Success" if closed_any else "Failed", msg)
    return msg

def shutdown_hachi():
    """Force stop Ollama background processes to free RAM and shutdown Hachi."""
    add_task("Shutdown Hachi", "Success", "Triggered force shutdown of Hachi & Ollama.")
    
    def _kill_task():
        time.sleep(2.5)  # Allow TTS to finish speaking farewell
        bat_path = os.path.join(os.path.dirname(__file__), "stop.bat")
        if os.path.exists(bat_path):
            subprocess.Popen(f'cmd.exe /c "{bat_path}"', shell=True)
        else:
            subprocess.Popen(['powershell', '-c', 'Get-Process -Name *ollama* -ErrorAction SilentlyContinue | Stop-Process -Force'], shell=False)
        os._exit(0)
            
    threading.Thread(target=_kill_task, daemon=True).start()
    return "Shutting down Hachi and force stopping Ollama to free system RAM. Paalam!"

def launch_mode(mode_name: str):
    """
    Launch specified assistant mode.
    Modes: 'gaming', 'study', 'movie', 'focus'

    Returns a string status message. For 'focus' mode, the message contains
    the special token '__START_POMODORO__' so the frontend knows to trigger
    the Pomodoro timer UI.
    """
    mode_clean = mode_name.lower().strip()
    status_msg = ""
    
    if "game" in mode_clean or "gaming" in mode_clean:
        # Gaming Mode: Steam + Discord only. Spotify is NOT opened automatically.
        launch_app("steam", args=["-bigpicture"])
        launch_app("discord")
        status_msg = "Gaming Mode activated. Launched Steam (Big Picture) and Discord. Ready to game!"
        
    elif "study" in mode_clean or "code" in mode_clean or "office" in mode_clean:
        launch_app("vscode")
        launch_app("chatgpt")
        launch_app("spotify")
        status_msg = "Study Mode activated. Launched VS Code, ChatGPT, and Spotify."
        
    elif "movie" in mode_clean or "watch" in mode_clean:
        webbrowser.open("https://youtube.com")
        webbrowser.open("https://netflix.com")
        status_msg = "Movie Mode activated. Opened YouTube and Netflix in browser."
        
    elif "focus" in mode_clean or "timer" in mode_clean:
        # Focus Mode: NO apps are launched automatically — just start the Pomodoro timer.
        # The special token triggers the frontend Pomodoro UI.
        status_msg = (
            "__START_POMODORO__ Focus Mode activated! "
            "Starting a 25-minute Pomodoro work session. "
            "Stay focused — I'll notify you when it's time for a break!"
        )
    else:
        status_msg = f"Unknown mode '{mode_name}'."
        
    add_task(f"Mode Request: {mode_name}", "Success", status_msg)
    return status_msg

def close_mode(mode_name: str):
    """Close applications associated with a mode (including Spotify which is opened in most modes)."""
    mode_clean = mode_name.lower().strip()
    closed = []

    def _try_close(app):
        result = close_app(app)
        if "Closed" in result:
            closed.append(app)

    if "game" in mode_clean or "gaming" in mode_clean:
        for app in ["steam", "discord"]:
            _try_close(app)
        msg = f"Closed gaming apps: {', '.join(closed) if closed else 'No active gaming apps found.'}"
    elif "study" in mode_clean:
        for app in ["code", "chatgpt", "spotify"]:
            _try_close(app)
        msg = f"Closed study apps: {', '.join(closed) if closed else 'No active study apps found.'}"
    elif "focus" in mode_clean:
        msg = "Focus Mode stopped. __STOP_POMODORO__ Your Pomodoro session has ended."
    else:
        msg = f"Closed apps for {mode_name}."

    add_task(f"Close Mode: {mode_name}", "Success", msg)
    return msg

_WMO_DESC = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog", 51: "Light drizzle", 53: "Drizzle",
    55: "Dense drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Slight rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain",
    67: "Freezing rain", 71: "Slight snow", 73: "Snow", 75: "Heavy snow",
    77: "Snow grains", 80: "Slight showers", 81: "Showers", 82: "Violent showers",
    85: "Slight snow showers", 86: "Snow showers", 95: "Thunderstorm",
    96: "Thunderstorm with hail", 99: "Severe thunderstorm with hail",
}


def _wmo_weather_desc(code: int) -> str:
    return _WMO_DESC.get(code, "Unknown conditions")


# Geocode cache (city name → (lat, lon)) — coordinates never change, cache forever.
_geo_cache: dict = {}
_geo_cache_lock = threading.Lock()
# Weather cache (city name → (timestamp, summary)) — avoid re-hitting the API within 5 min.
_weather_cache: dict = {}
_weather_cache_lock = threading.Lock()
_WEATHER_TTL = 300  # seconds


# Common cities resolved offline so the slow geocode step is skipped entirely
# for the places users actually ask about. Coordinates never change.
_BUILTIN_CITIES = {
    "manila": (14.5995, 120.9842),
    "quezon city": (14.6760, 121.0437),
    "makati": (14.5547, 121.0244),
    "cebu": (10.3157, 123.8854),
    "davao": (7.1907, 125.4553),
    "tokyo": (35.6762, 139.6503),
    "osaka": (34.6937, 135.5023),
    "seoul": (37.5665, 126.9780),
    "singapore": (1.3521, 103.8198),
    "hong kong": (22.3193, 114.1694),
    "new york": (40.7128, -74.0060),
    "los angeles": (34.0522, -118.2437),
    "san francisco": (37.7749, -122.4194),
    "london": (51.5074, -0.1278),
    "paris": (48.8566, 2.3522),
    "sydney": (-33.8688, 151.2093),
}


def _geocode(city: str):
    """Resolve a city name to (lat, lon). Built-in table first, then Nominatim.
    Results cached forever."""
    city = city.strip().lower()
    if city in _geo_cache:
        return _geo_cache[city]
    if city in _BUILTIN_CITIES:
        with _geo_cache_lock:
            _geo_cache[city] = _BUILTIN_CITIES[city]
        return _BUILTIN_CITIES[city]

    from urllib.parse import quote
    geo_url = f"https://nominatim.openstreetmap.org/search?q={quote(city)}&format=json&limit=1"
    try:
        geo_res = requests.get(geo_url, headers={"User-Agent": "HachiAI/1.0"}, timeout=5)
        if geo_res.status_code == 200:
            results = geo_res.json()
            if results:
                lat = float(results[0]["lat"])
                lon = float(results[0]["lon"])
                with _geo_cache_lock:
                    _geo_cache[city] = (lat, lon)
                return lat, lon
    except Exception as e:
        logging.warning(f"Geocode error for {city!r}: {e}")
    return None


def _weather_openmeteo(location: str, display: str):
    """Provider 1: Nominatim geocode + Open-Meteo forecast."""
    coords = _geocode(location)
    if not coords:
        return None
    lat, lon = coords
    w_url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
             f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code")
    w_res = requests.get(w_url, timeout=5)
    if w_res.status_code != 200:
        return None
    curr = w_res.json().get("current", {})
    temp_c = curr.get("temperature_2m")
    if temp_c is None:
        return None
    feels_c  = curr.get("apparent_temperature")
    humidity = curr.get("relative_humidity_2m")
    desc     = _wmo_weather_desc(curr.get("weather_code", 0))
    return (f"Current weather in {display}: {desc}, {round(temp_c)}°C "
            f"(Feels like {round(feels_c)}°C), Humidity: {humidity}%.")


def _weather_wttr(location: str, display: str):
    """Provider 2 (fallback): wttr.in JSON — takes the city name directly, no geocoding."""
    from urllib.parse import quote
    res = requests.get(f"https://wttr.in/{quote(location)}?format=j1", timeout=5)
    if res.status_code != 200:
        return None
    data = res.json()
    curr = data.get("current_condition") or []
    if not curr:
        return None
    curr = curr[0]
    temp_c   = curr.get("temp_C")
    if temp_c is None:
        return None
    desc     = curr.get("weatherDesc")[0]["value"]
    feels_c  = curr.get("FeelsLikeC")
    humidity = curr.get("humidity")
    return (f"Current weather in {display}: {desc}, {round(float(temp_c))}°C "
            f"(Feels like {round(float(feels_c))}°C), Humidity: {humidity}%.")


def get_weather(location: str = "Manila"):
    """Fetch current live weather via a provider chain (Open-Meteo → wttr.in),
    all free/no-key. Successes are cached so repeat asks are instant and the
    flaky hosts on this network are only hit once."""
    key = location.strip().lower()
    display = location.strip()

    with _weather_cache_lock:
        hit = _weather_cache.get(key)
    if hit and time.time() - hit[0] < _WEATHER_TTL:
        return hit[1]

    # Try providers in PARALLEL; take the first success. Each has a 5s HTTP
    # timeout. We early-exit WITHOUT waiting for the slower sibling (using `with`
    # here would block until both finish — that's what made it slow before).
    summary = None
    pool = None
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        pool = ThreadPoolExecutor(max_workers=2)
        futures = {pool.submit(p, key, display): p for p in (_weather_openmeteo, _weather_wttr)}
        for fut in as_completed(futures):
            try:
                candidate = fut.result()
            except Exception as e:
                logging.warning(f"Weather provider {futures[fut].__name__} error: {e}")
                continue
            if candidate:
                summary = candidate
                break
    except Exception as e:
        logging.warning(f"Weather provider dispatch error: {e}")
    finally:
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    if summary:
        with _weather_cache_lock:
            _weather_cache[key] = (time.time(), summary)
        add_task("Check Weather", "Success", summary)
        return summary

    return f"Unable to fetch live weather for {display} right now."

def search_web(query: str):
    """Perform live web search via DuckDuckGo JSON API (duckduckgo_search)."""
    try:
        from ddgs import DDGS
        
        logging.info(f"[Search Engine] Performing query: '{query}'")
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=6):
                title = r.get("title", "")
                snippet = r.get("body", "")
                href = r.get("href", "")
                if title or snippet:
                    results.append(f"• **{title}**: {snippet}" + (f" ({href})" if href else ""))
                    
        if results:
            summary = f"**Live Web Search results for '{query}':**\n\n" + "\n".join(results)
            add_task(f"Web Search: {query}", "Success", summary[:300])
            return summary
    except Exception as e:
        logging.error(f"DuckDuckGo search_web API error: {e}")
        
    return f"Searched web for '{query}', but could not retrieve live results right now."

def fetch_url(url: str):
    """
    Fetch and extract readable text content from a specific URL.
    Returns the main body text (first ~2000 chars) for the AI to summarize.
    """
    try:
        from bs4 import BeautifulSoup

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        # Stream and cap download size so multi-MB pages don't hang or blow memory
        res = requests.get(url, headers=headers, timeout=10, stream=True)
        if res.status_code != 200:
            res.close()
            return f"Could not fetch URL (HTTP {res.status_code}): {url}"

        MAX_BYTES = 1_500_000
        chunks = []
        size = 0
        for chunk in res.iter_content(chunk_size=65536):
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BYTES:
                break
        res.close()
        html_text = b"".join(chunks).decode("utf-8", errors="ignore")

        soup = BeautifulSoup(html_text, "html.parser")

        # Remove script, style, nav, footer noise
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()

        # Try to get main content area
        main = soup.find("article") or soup.find("main") or soup.find("div", {"id": "content"}) or soup.body
        if main:
            text = main.get_text(separator="\n", strip=True)
        else:
            text = soup.get_text(separator="\n", strip=True)

        # Clean up excess whitespace
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        cleaned = "\n".join(lines)[:2500]

        add_task(f"Fetch URL: {url[:60]}", "Success", f"Retrieved {len(cleaned)} chars")
        return f"**Content from {url}:**\n\n{cleaned}"
    except Exception as e:
        logging.error(f"fetch_url error for {url}: {e}")
        return f"Could not retrieve content from {url}: {e}"

def get_system_stats():
    """Get system date/time, CPU (total + busiest core), RAM, and Battery status.
    Uses a primed non-blocking read so the value reflects recent activity and
    per-core detail matches what Task Manager shows, instead of a fluky idle snapshot."""
    try:
        from datetime import datetime
        now_str = datetime.now().strftime("%A, %B %d, %Y %I:%M %p")

        cores = psutil.cpu_percent(interval=None, percpu=True)
        # If the module-level prime didn't run (or this is a fresh process), the
        # non-blocking read is all zeros — fall back to a real 0.5s sample.
        if not cores or all(c == 0.0 for c in cores):
            cores = psutil.cpu_percent(interval=0.5, percpu=True)

        cpu_total = round(sum(cores) / len(cores)) if cores else 0
        max_core  = round(max(cores)) if cores else 0

        ram = round(psutil.virtual_memory().percent)
        battery = psutil.sensors_battery()
        bat_str = f"{round(battery.percent)}%" if battery else "Desktop (No battery)"
        stats = (f"System Stats: Clock Time: {now_str}, CPU Usage: {cpu_total}% "
                 f"(busiest core: {max_core}%), RAM Usage: {ram}%, Battery: {bat_str}.")
        add_task("System Check", "Success", stats)
        return stats
    except Exception as e:
        logging.error(f"get_system_stats error: {e}")
        return "Could not retrieve system stats."

# Tool definitions for Ollama - MUST use {"type": "function", "function": {...}} wrapper format
AVAILABLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "launch_mode",
            "description": (
                "Launch a desktop mode based on user intent. "
                "Call this tool whenever the user IMPLIES they want to game, study, watch something, or focus/concentrate — "
                "even if they don't use the word 'mode'.\n"
                "Mode triggers and examples:\n"
                "  gaming: 'I wanna play', 'let's game', 'game time', 'i feel like playing', "
                "'boot up steam', 'let me play some games', 'ayaw ko mag-aral gusto ko mag-laro', "
                "'pag-laruin natin', 'start gaming', 'open steam', 'discord and steam'\n"
                "  study: 'time to study', 'let me study', 'I need to focus on school', "
                "'open vscode', 'mag-aral tayo', 'i need to do homework', 'study mode'\n"
                "  movie: 'watch a movie', 'movie time', 'let's watch something', 'i want to chill and watch', "
                "'movie night', 'manood tayo', 'stream something'\n"
                "  focus: 'start a timer', 'pomodoro', 'I need to concentrate', 'deep work', "
                "'25 minute timer', 'help me focus', 'focus mode', 'mag-focus tayo', 'work session'\n"
                "ALWAYS call this tool when intent is clear. Do not ask for confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode_name": {
                        "type": "string",
                        "description": "Exactly one of: gaming, study, movie, focus",
                        "enum": ["gaming", "study", "movie", "focus"]
                    }
                },
                "required": ["mode_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "close_mode",
            "description": (
                "Close/stop a desktop mode and its apps when user wants to stop, exit, end, or quit a mode. "
                "Examples: 'stop gaming', 'close game mode', 'done playing', 'exit study mode', "
                "'stop the timer', 'end focus session'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode_name": {"type": "string", "description": "Mode name to close e.g. gaming, study, focus"}
                },
                "required": ["mode_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "close_app",
            "description": "Close ANY specific running desktop application by name (e.g. Chrome, Notepad, Spotify, Steam, Calculator)",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "Name of application or process to close"}
                },
                "required": ["app_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "launch_app",
            "description": (
                "Open or launch ANY desktop application by name. "
                "Use when the user wants to open a specific app that is NOT a mode. "
                "Examples: chrome, notepad, league of legends, spotify, calculator, "
                "file explorer, word, excel, paint, obs, vlc, telegram, whatsapp."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "Name of the application to open"
                    }
                },
                "required": ["app_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "shutdown_hachi",
            "description": "Turn off and shutdown Hachi voice assistant, close application, and force stop Ollama background tasks to free RAM",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current live weather forecast and temperature",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City or country name, default Manila"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web via DuckDuckGo for real-time information, news, latest releases, or any topic the user asks about",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query terms"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch and read the content of a specific webpage URL to get detailed information from that page",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The full URL to fetch and read (e.g. https://example.com/article)"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "Check past user conversations, tasks, or activities logged in database",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keywords to search for"},
                    "date_str": {"type": "string", "description": "Date formatted YYYY-MM-DD"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_stats",
            "description": "Check CPU usage, RAM memory usage, and battery level of the PC",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]

def execute_tool_call(tool_name: str, arguments: dict):
    """Execute target tool by name and return string result."""
    logging.info(f"Executing Tool Call: {tool_name} with args {arguments}")
    arguments = arguments or {}
    # Tools that REQUIRE args must not fire with defaults when the model gave an
    # empty/malformed dict — otherwise "close_app" with {} would kill everything,
    # and "launch_mode" with {} would launch gaming unprompted.
    REQUIRED_ARGS = {
        "launch_mode": "mode_name",
        "close_mode": "mode_name",
        "launch_app": "app_name",
        "close_app": "app_name",
        "get_weather": "location",
        "search_web": "query",
        "fetch_url": "url",
    }
    if tool_name in REQUIRED_ARGS and not arguments.get(REQUIRED_ARGS[tool_name]):
        msg = f"Tool {tool_name} needs a value for '{REQUIRED_ARGS[tool_name]}' but none was provided."
        logging.warning(msg)
        return msg
    if tool_name == "launch_mode":
        return launch_mode(arguments.get("mode_name", "gaming"))
    elif tool_name == "close_mode":
        return close_mode(arguments.get("mode_name", "gaming"))
    elif tool_name == "launch_app":
        return launch_app(arguments.get("app_name", ""))
    elif tool_name == "close_app":
        return close_app(arguments.get("app_name", ""))
    elif tool_name == "shutdown_hachi":
        return shutdown_hachi()
    elif tool_name == "get_weather":
        return get_weather(arguments.get("location", "Manila"))
    elif tool_name == "search_web":
        res = search_web(arguments.get("query", ""))
        logging.info(f"Tool search_web result length: {len(res) if isinstance(res,str) else 'n/a'}")
        return res
    elif tool_name == "fetch_url":
        res = fetch_url(arguments.get("url", ""))
        logging.info(f"Tool fetch_url result length: {len(res) if isinstance(res,str) else 'n/a'}")
        return res
    elif tool_name == "search_memory":
        return search_history(query=arguments.get("query"), date_str=arguments.get("date_str"))
    elif tool_name == "get_system_stats":
        res = get_system_stats()
        logging.info(f"Tool get_system_stats: {res}")
        return res
    return f"Tool {tool_name} not found."
