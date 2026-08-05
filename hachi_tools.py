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
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            results = []
            for item in soup.find_all("div", class_="result__body")[:5]:
                title_el = item.find("a", class_="result__a")
                snippet_el = item.find("a", class_="result__snippet")
                title = title_el.get_text(strip=True) if title_el else ""
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                href = title_el.get("href", "") if title_el else ""
                if title or snippet:
                    results.append(f"• **{title}**: {snippet}" + (f" ({href})" if href else ""))
            if results:
                summary = f"**Web results for '{query}':**\n\n" + "\n".join(results)
                add_task(f"Web Search: {query}", "Success", summary[:300])
                return summary
    except Exception as e:
        logging.error(f"Web search error: {e}")
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
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return f"Could not fetch URL (HTTP {res.status_code}): {url}"

        soup = BeautifulSoup(res.text, "html.parser")

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
    """Get system CPU, RAM, and Battery status with accurate per-core CPU percentage."""
    try:
        # Per-core average calculation for 100% accurate Windows CPU readings
        per_cpu = psutil.cpu_percent(interval=0.15, percpu=True)
        cpu = round(sum(per_cpu) / len(per_cpu)) if per_cpu else round(psutil.cpu_percent(interval=0.15))
        
        ram = round(psutil.virtual_memory().percent)
        battery = psutil.sensors_battery()
        bat_str = f"{round(battery.percent)}%" if battery else "Desktop (No battery)"
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
    elif tool_name == "fetch_url":
        return fetch_url(arguments.get("url", ""))
    elif tool_name == "search_memory":
        return search_history(query=arguments.get("query"), date_str=arguments.get("date_str"))
    elif tool_name == "get_system_stats":
        return get_system_stats()
    return f"Tool {tool_name} not found."
