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
from hachi_db import search_history, add_task

_log_path = os.path.join(os.path.dirname(__file__), "hachi.log")
logging.basicConfig(filename=_log_path, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

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

def get_app_path(app_name):
    """Resolve executable path for application."""
    if app_name not in APP_PATHS:
        return app_name
    username = os.getenv('USERNAME', 'User')
    for path_pattern in APP_PATHS[app_name]:
        path = path_pattern.format(user=username)
        if '*' in path:
            matches = glob.glob(path)
            if matches:
                return matches[0]
        if os.path.exists(path):
            return path
    return APP_PATHS[app_name][-1]

def launch_app(app_name, args=None):
    """Launch app process with protocol fallbacks for 100% reliability on any PC."""
    try:
        app_clean = app_name.lower().strip()
        
        if app_clean == "chatgpt":
            app_path = get_app_path("chatgpt")
            if os.path.exists(app_path):
                subprocess.Popen([app_path], shell=False)
            else:
                webbrowser.open("https://chatgpt.com")
            return True

        if app_clean == "steam":
            if args and "-bigpicture" in args:
                try:
                    os.system("start steam://open/bigpicture")
                    return True
                except Exception:
                    pass
            app_path = get_app_path("steam")
            if os.path.exists(app_path):
                cmd = [app_path] + (args if args else [])
                subprocess.Popen(cmd, shell=False)
                return True
            else:
                os.system("start steam://open/main")
                return True

        if app_clean == "spotify":
            app_path = get_app_path("spotify")
            if os.path.exists(app_path):
                subprocess.Popen([app_path], shell=False)
            else:
                os.system("start spotify:")
            return True

        if app_clean == "discord":
            app_path = get_app_path("discord")
            if os.path.exists(app_path):
                subprocess.Popen([app_path], shell=False)
            else:
                os.system("start discord:")
            return True

        app_path = get_app_path(app_name)
        cmd = [app_path]
        if args:
            cmd.extend(args if isinstance(args, list) else [args])
        subprocess.Popen(cmd, shell=False)
        logging.info(f"Launched application: {app_name}")
        return True
    except Exception as e:
        logging.error(f"Failed to launch {app_name}, trying system start fallback: {e}")
        try:
            os.system(f'start {app_name}')
            return True
        except Exception:
            return False

def close_app(app_name: str):
    """Close ANY application running on Windows by process or app name."""
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
        "code": "code"
    }
    target_pattern = name_map.get(app_clean, app_clean)
    
    terminated_list = []
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            pname = proc.info['name'].lower()
            if target_pattern in pname:
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
    """
    mode_clean = mode_name.lower().strip()
    status_msg = ""
    
    if "game" in mode_clean or "gaming" in mode_clean:
        launch_app("steam", args=["-bigpicture"])
        launch_app("discord")
        launch_app("spotify")
        status_msg = "Gaming Mode activated. Launched Steam (Big Picture), Discord, and Spotify."
        
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
        launch_app("spotify")
        status_msg = "Focus Mode activated. Launched Spotify. Your Pomodoro timer is now showing on screen."
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
        for app in ["steam", "discord", "spotify"]:
            _try_close(app)
        msg = f"Closed gaming apps: {', '.join(closed) if closed else 'No active gaming apps found.'}"
    elif "study" in mode_clean:
        for app in ["code", "chatgpt", "spotify"]:
            _try_close(app)
        msg = f"Closed study apps: {', '.join(closed) if closed else 'No active study apps found.'}"
    elif "focus" in mode_clean:
        for app in ["spotify"]:
            _try_close(app)
        msg = f"Closed focus mode apps: {', '.join(closed) if closed else 'No active focus apps found.'}"
    else:
        msg = f"Closed apps for {mode_name}."

    add_task(f"Close Mode: {mode_name}", "Success", msg)
    return msg

def get_weather(location: str = "Manila"):
    """Fetch current live weather and temperature for location."""
    try:
        url = f"https://wttr.in/{location}?format=j1"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            curr = data['current_condition'][0]
            temp_c = curr['temp_C']
            weather_desc = curr['weatherDesc'][0]['value']
            feels_c = curr['FeelsLikeC']
            humidity = curr['humidity']
            summary = (
                f"Current weather in {location}: {weather_desc}, {temp_c}°C (Feels like {feels_c}°C), "
                f"Humidity: {humidity}%."
            )
            add_task("Check Weather", "Success", summary)
            return summary
    except Exception as e:
        logging.error(f"Weather fetch error: {e}")
    return f"Unable to fetch live weather for {location} right now."

def search_web(query: str):
    """Perform live web search via DuckDuckGo HTML scraping with BeautifulSoup."""
    try:
        from urllib.parse import quote
        from bs4 import BeautifulSoup

        safe_query = quote(query)
        url = f"https://html.duckduckgo.com/html/?q={safe_query}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        res = requests.get(url, headers=headers, timeout=6)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            snippets = []
            for a in soup.find_all("a", class_="result__snippet"):
                text = a.get_text(strip=True)
                if text:
                    snippets.append(text)
                if len(snippets) >= 3:
                    break
            if snippets:
                summary = f"Web results for '{query}': " + " ".join(snippets)
                add_task(f"Web Search: {query}", "Success", summary[:250])
                return summary
    except Exception as e:
        logging.error(f"Web search error: {e}")
    return f"Searched web for '{query}', but could not retrieve live results right now."

def get_system_stats():
    """Get system CPU, RAM, and Battery status."""
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory().percent
        battery = psutil.sensors_battery()
        bat_str = f"{battery.percent}%" if battery else "Desktop (No battery)"
        stats = f"System Stats: CPU Usage: {cpu}%, RAM Usage: {ram}%, Battery: {bat_str}."
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
            "description": "Launch desktop modes based on user intent (gaming, study, movie, focus)",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode_name": {"type": "string", "description": "Mode name to launch: gaming, study, movie, focus"}
                },
                "required": ["mode_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "close_mode",
            "description": "Close apps associated with a mode when user wants to stop or exit",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode_name": {"type": "string", "description": "Mode name to close e.g. gaming, study"}
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
            "description": "Scrape or search the web for real-time information, news, or latest releases",
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
    if tool_name == "launch_mode":
        return launch_mode(arguments.get("mode_name", "gaming"))
    elif tool_name == "close_mode":
        return close_mode(arguments.get("mode_name", "gaming"))
    elif tool_name == "close_app":
        return close_app(arguments.get("app_name", ""))
    elif tool_name == "shutdown_hachi":
        return shutdown_hachi()
    elif tool_name == "get_weather":
        return get_weather(arguments.get("location", "Manila"))
    elif tool_name == "search_web":
        return search_web(arguments.get("query", ""))
    elif tool_name == "search_memory":
        return search_history(query=arguments.get("query"), date_str=arguments.get("date_str"))
    elif tool_name == "get_system_stats":
        return get_system_stats()
    return f"Tool {tool_name} not found."
