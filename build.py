import re
import sys

hachi_path = 'c:/Users/AxeilAchia/Desktop/HEY hachi/Hey-hachi/hachi.html'
index_path = 'c:/Users/AxeilAchia/Desktop/HEY hachi/Hey-hachi/templates/index.html'

try:
    with open(hachi_path, 'r', encoding='utf-8') as f:
        hachi = f.read()

    with open(index_path, 'r', encoding='utf-8') as f:
        index = f.read()
except Exception as e:
    print(f'Error reading files: {e}')
    sys.exit(1)

# Extract JS from index.html
match = re.search(r'(<script>\s*// ============================================================\s*// DOM refs.*?)</script>', index, re.DOTALL)
if match:
    js_code = match.group(1)
else:
    print('JS not found')
    sys.exit(1)

# Extract hachi CSS
css_match = re.search(r'(<style>.*?</style>)', hachi, re.DOTALL)
hachi_css = css_match.group(1) if css_match else ''

# Extract hachi loader
loader_match = re.search(r'(<div class="loader-screen".*?</div>\s*</div>\s*</div>)', hachi, re.DOTALL)
loader_html = loader_match.group(1) if loader_match else ''

new_html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Hachi 1.0</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
{hachi_css}
<style>
  /* Added CSS for messages and bubbles */
  .messages {{ display:flex; flex-direction:column; gap:16px; padding: 20px; width: 100%; max-width: 700px; margin: 0 auto; }}
  .msg {{ display:flex; flex-direction:column; max-width:88%; animation:rise .3s ease both; }}
  @keyframes rise {{ from{{ opacity:0; transform:translateY(8px); }} to{{ opacity:1; transform:translateY(0); }} }}
  .msg.user {{ align-self:flex-end; align-items:flex-end; }}
  .msg.assistant {{ align-self:flex-start; align-items:flex-start; }}
  .bubble {{ padding:12px 16px; border-radius:var(--radius-lg); font-size:15px; line-height:1.65; word-break:break-word; }}
  .msg.user .bubble {{ background:var(--accent); color:#fff; border-bottom-right-radius:5px; font-weight: 500; }}
  .msg.assistant .bubble {{ background:var(--bg-elevated); border:1px solid var(--border); color:var(--text); border-bottom-left-radius:5px; box-shadow: 0 4px 12px rgba(28,26,21,0.05); }}
  .meta {{ font-family:var(--font-mono); font-size:11px; color:var(--text-faint); margin-top:5px; padding:0 3px; }}
  .tool-badge {{ font-family:var(--font-mono); font-size:10px; background:var(--accent-soft); border:1px solid rgba(200,146,46,0.3); color:var(--accent); border-radius:6px; padding:2px 7px; margin-top:5px; display:inline-block; }}
  .typing {{ display:flex; gap:4px; padding:12px 15px; background:var(--bg-elevated); border:1px solid var(--border); border-radius:var(--radius-lg); border-bottom-left-radius:5px; width:fit-content; }}
  .typing span {{ width:6px; height:6px; border-radius:50%; background:var(--text-dim); animation:bounce 1.1s infinite ease-in-out; }}
  .typing span:nth-child(2) {{ animation-delay:.15s; }}
  .typing span:nth-child(3) {{ animation-delay:.3s; }}
  
  .bubble h1, .bubble h2, .bubble h3 {{ font-family:var(--font-display); font-weight:600; margin:12px 0 6px; line-height:1.3; }}
  .bubble h1 {{ font-size:17px; }}
  .bubble h2 {{ font-size:15px; color:var(--accent-ink); }}
  .bubble h3 {{ font-size:14px; color:var(--text-dim); }}
  .bubble p {{ margin:6px 0; }}
  .bubble p:first-child {{ margin-top:0; }}
  .bubble p:last-child {{ margin-bottom:0; }}
  .bubble ul, .bubble ol {{ margin:6px 0 6px 18px; }}
  .bubble li {{ margin:3px 0; line-height:1.55; }}
  .bubble strong {{ color:var(--accent-ink); font-weight:600; }}
  .bubble em {{ color:var(--text-dim); font-style:italic; }}
  .bubble code {{ background:rgba(28,26,21,0.04); border:1px solid var(--border); border-radius:4px; padding:1px 5px; font-family:var(--font-mono); font-size:13px; color:var(--accent); }}
  .bubble pre {{ background:rgba(28,26,21,0.03); border:1px solid var(--border); border-radius:10px; padding:12px; overflow-x:auto; margin:8px 0; }}
  .bubble pre code {{ background:none; border:none; padding:0; color:var(--text); }}
  .bubble blockquote {{ border-left:3px solid var(--accent); padding-left:12px; margin:8px 0; color:var(--text-dim); font-style:italic; }}
  .bubble hr {{ border:none; border-top:1px solid var(--border); margin:10px 0; }}
  .bubble a {{ color:var(--accent); text-decoration:underline; text-underline-offset:2px; }}

  /* Pomodoro and Toast */
  .pomo-dot {{ width: 6px; height: 6px; border-radius: 50%; border: 1px solid var(--text-faint); }}
  .pomo-dot.done {{ background: var(--accent); border-color: var(--accent); }}
  .toast {{ position: absolute; top: 16px; left: 50%; transform: translateX(-50%) translateY(-70px); background: var(--accent-soft); border: 1px solid var(--accent); color: var(--accent); padding: 8px 16px; border-radius: 20px; font-family: var(--font-mono); font-size: 12px; transition: transform .35s ease; z-index: 30; white-space: nowrap; pointer-events: none; }}
  .toast.show {{ transform: translateX(-50%) translateY(0); }}
  .pomo-notify {{ position: absolute; inset: 0; z-index: 40; background: rgba(246,244,238,0.7); backdrop-filter: blur(6px); display: none; flex-direction: column; align-items: center; justify-content: center; gap: 16px; animation: fadeIn .3s ease; }}
  .pomo-notify.show {{ display: flex; }}
  @keyframes fadeIn {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
  .pomo-notify-card {{ background: var(--bg-elevated); border: 1px solid var(--border-strong); border-radius: var(--radius-lg); padding: 32px 36px; text-align: center; max-width: 320px; box-shadow: 0 20px 46px -18px rgba(28,26,21,0.24); }}
  .pomo-notify-icon {{ font-size: 48px; margin-bottom: 12px; }}
  .pomo-notify-title {{ font-family: var(--font-display); font-size: 20px; font-weight: 700; margin-bottom: 8px; color: var(--text); }}
  .pomo-notify-sub {{ font-family: var(--font-body); font-size: 14px; color: var(--text-dim); margin-bottom: 20px; }}
  .pomo-notify-btn {{ padding: 10px 24px; border-radius: 12px; border: none; background: var(--accent); color: #fff; font-family: var(--font-display); font-size: 14px; font-weight: 600; cursor: pointer; transition: transform .15s; }}
  .pomo-notify-btn:hover {{ transform: scale(1.03); }}
  .pomo-notify-btn.secondary {{ background: transparent; border: 1px solid var(--border-strong); color: var(--text-dim); margin-left: 8px; }}
  .voice-transcript {{ width: 100%; min-height: 52px; max-height: 100px; overflow-y: auto; background: rgba(28,26,21,0.03); border: 1px solid var(--border); border-radius: 14px; padding: 10px 14px; font-family: var(--font-body); font-size: 13px; color: var(--text-dim); text-align: center; transition: all .3s; margin-bottom: 12px; }}
  .voice-transcript.heard {{ color: var(--text); border-color: var(--accent); background: var(--accent-soft); }}
  .voice-transcript.interim {{ color: var(--accent); border-color: rgba(200,146,46,0.3); }}
  .stt-badge {{ font-family: var(--font-mono); font-size: 9px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-faint); background: rgba(28,26,21,0.03); border: 1px solid var(--border); border-radius: 6px; padding: 2px 8px; margin-top: 6px; display: inline-block; }}
</style>
</head>
<body>
{loader_html}

<div class="app" id="appEl" data-voice="idle">
  <!-- Sidebar -->
  <aside class="sidebar">
    <div class="sidebar-top">
      <div class="logo">
        <div class="logo-mark">
          <svg viewBox="0 0 28 28" fill="none">
            <path d="M14 2 L25 8 V20 L14 26 L3 20 V8 Z" stroke="#1c1a15" stroke-width="1.6" stroke-linejoin="round"/>
            <path d="M14 2 V26 M3 8 L25 20 M25 8 L3 20" stroke="#c8922e" stroke-width="1.1" stroke-linejoin="round"/>
          </svg>
        </div>
        <span class="logo-name">Hachi</span>
      </div>
      <button class="collapse-btn" title="Toggle sidebar">
        <svg viewBox="0 0 24 24" fill="none"><rect x="3" y="4" width="18" height="16" rx="3" stroke="currentColor" stroke-width="1.6"/><path d="M9 4v16" stroke="currentColor" stroke-width="1.6"/></svg>
      </button>
    </div>

    <div class="nav-group">
      <button class="nav-item active">
        <svg viewBox="0 0 24 24" fill="none"><path d="M20 12a8 8 0 11-3.2-6.4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><path d="M8 12h6M8 9h4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>
        Chat
      </button>
      <button class="nav-item" id="chip-focus" onclick="triggerMode('focus', this)">⏱️ Focus</button>
      <button class="nav-item" id="chip-gaming" onclick="triggerMode('gaming', this)">🎮 Gaming</button>
      <button class="nav-item" id="chip-study" onclick="triggerMode('study', this)">📚 Study</button>
      <button class="nav-item" id="chip-movie" onclick="triggerMode('movie', this)">🎬 Movie</button>
    </div>

    <div class="side-action" onclick="clearChat()">
      <svg viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
      New Chat
    </div>

    <div class="sidebar-spacer"></div>
    
    <!-- Pomodoro Banner (in sidebar bottom) -->
    <div class="pomodoro-banner" id="pomodoroBanner" style="display:none; flex-direction:column; gap:5px; background:var(--bg-elevated); border:1px solid var(--border); padding:12px; border-radius:var(--radius-md); margin-bottom:12px;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <span id="pomoLabel" style="font-size:10px; font-weight:600; text-transform:uppercase; color:var(--text-dim); letter-spacing:0.06em;">Work Session</span>
            <span id="pomoIcon">🍅</span>
        </div>
        <div id="pomoTimer" style="font-family:var(--font-display); font-size:24px; font-weight:600; color:var(--accent);">25:00</div>
        <div class="pomo-sessions" id="pomoSessions" style="display:flex; gap:4px; margin-top:2px;">
            <span class="pomo-dot" id="pd1"></span>
            <span class="pomo-dot" id="pd2"></span>
            <span class="pomo-dot" id="pd3"></span>
            <span class="pomo-dot" id="pd4"></span>
        </div>
        <div style="display:flex; gap:6px; margin-top:8px;">
            <button id="pomoPauseBtn" onclick="togglePomodoro()" style="flex:1; padding:4px 0; border-radius:8px; border:1px solid var(--border); background:transparent; color:var(--text-dim); font-family:var(--font-mono); font-size:11px; cursor:pointer; transition:all 0.15s;">⏸ Pause</button>
            <button id="pomoStopBtn" onclick="stopPomodoro()" style="flex:1; padding:4px 0; border-radius:8px; border:1px solid var(--border); background:transparent; color:var(--text-dim); font-family:var(--font-mono); font-size:11px; cursor:pointer; transition:all 0.15s;">✕ Stop</button>
        </div>
    </div>

    <div class="status-indicator" style="font-family:var(--font-mono); font-size:11px; display:flex; align-items:center; gap:6px; color:var(--text-dim); padding: 0 10px;">
      <span class="status-dot" id="micDot" style="width:6px;height:6px;border-radius:50%;background:#f87171; box-shadow: 0 0 8px #f87171;"></span>
      <span id="micStatus">mic...</span>
    </div>
  </aside>

  <!-- Main -->
  <div class="main" style="overflow-y: auto;">
    <div class="topbar">
      <div class="model-select">
        <svg viewBox="0 0 24 24" fill="none" style="width:14px;height:14px;margin-right:6px;"><path d="M12 3v6M12 15v6M4.2 7l5.2 3M14.6 14l5.2 3M4.2 17l5.2-3M14.6 10l5.2-3" stroke="currentColor" stroke-width="2"/></svg>
        Hachi 1.0
      </div>
      <div></div>
    </div>

    <div class="hero" style="flex:none; padding: 0 24px 20px; z-index: 10;">
      <svg class="honeycomb" viewBox="0 0 560 320" fill="none">
        <g stroke="#1c1a15" stroke-width="1" opacity="0.5">
          <path d="M180 40 L230 68 L230 124 L180 152 L130 124 L130 68 Z"/>
          <path d="M280 20 L330 48 L330 104 L280 132 L230 104 L230 48 Z"/>
          <path d="M380 40 L430 68 L430 124 L380 152 L330 124 L330 68 Z"/>
          <path d="M230 124 L280 152 L280 208 L230 236 L180 208 L180 152 Z"/>
          <path d="M330 124 L380 152 L380 208 L330 236 L280 208 L280 152 Z"/>
        </g>
      </svg>

      <div class="hero-inner">
        <h1 class="hero-title" id="heroTitle"></h1>
        <p class="hero-sub">Interact with <b>Hachi</b> and explore the boundless creative world</p>

        <div class="composer">
          <div class="composer-box">
            <textarea id="inputField" placeholder="Ask Hachi to build something..." rows="1" onkeydown="handleKey(event)"></textarea>
            <div class="composer-tools">
              <div class="tools-left"></div>
              <div class="tools-right">
                <button class="mic-btn" id="micBtn" title="Voice mode" onclick="openVoice()">
                  <svg viewBox="0 0 24 24" fill="none"><path d="M12 15a3 3 0 003-3V6a3 3 0 10-6 0v6a3 3 0 003 3z" stroke="currentColor" stroke-width="1.8"/><path d="M19 11a7 7 0 01-14 0M12 18v3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
                </button>
                <button class="send-btn" id="sendBtn" title="Send" onclick="sendMessage()">
                  <svg viewBox="0 0 24 24" fill="none"><path d="M12 19V5M5 12l7-7 7 7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Messages -->
    <div class="messages" id="messages" style="z-index: 5; position: relative;">
        <div class="msg assistant">
            <div class="bubble">Kamusta! Ako si <strong>Hachi</strong>, ang iyong AI assistant. Magtanong ka ng kahit ano, or tap the mic button to start a voice conversation! Say <strong>"Hey Hachi"</strong> anytime to activate voice mode 🎤</div>
            <div class="meta">Hachi · Ready</div>
        </div>
    </div>

    <!-- Voice overlay -->
    <div class="voice-overlay" id="voiceOverlay">
      <div class="voice-top">
        <div class="voice-status"><span class="dot" id="voiceDot"></span><span id="voiceStatusText">Listening</span></div>
        <div class="voice-timer" id="voiceTimer">00:00</div>
      </div>

      <div style="display:flex; flex-direction:column; align-items:center; gap:20px; width:100%; max-width: 400px;">
        <div class="orb-wrap">
          <div class="hex-ring h1"><svg viewBox="0 0 100 100"><path d="M50 4 L90 27 V73 L50 96 L10 73 V27 Z" stroke="#c8922e" stroke-width="1.3" fill="none"/></svg></div>
          <div class="hex-ring h2"><svg viewBox="0 0 100 100"><path d="M50 4 L90 27 V73 L50 96 L10 73 V27 Z" stroke="#c8922e" stroke-width="1.3" fill="none"/></svg></div>
          <div class="hex-ring h3"><svg viewBox="0 0 100 100"><path d="M50 4 L90 27 V73 L50 96 L10 73 V27 Z" stroke="#c8922e" stroke-width="1.3" fill="none"/></svg></div>
          <div class="orb-core">
            <div class="bar"></div><div class="bar"></div><div class="bar"></div><div class="bar"></div><div class="bar"></div>
          </div>
        </div>

        <div class="voice-transcript" id="voiceTranscript">Speak whenever you're ready…</div>

        <div>
          <div class="voice-caption" id="voiceCaption">Listening…</div>
          <div class="voice-sub" id="voiceSub">Speak whenever you're ready</div>
          <div style="text-align:center"><span class="stt-badge" id="sttBadge">🎤 Web Speech API</span></div>
        </div>
      </div>

      <div class="voice-bottom">
        <button class="voice-ctrl" id="muteBtn" title="Mute" onclick="toggleMute()">
          <svg viewBox="0 0 24 24" fill="none"><path d="M12 15a3 3 0 003-3V6a3 3 0 10-6 0v6a3 3 0 003 3z" stroke="currentColor" stroke-width="1.8"/><path d="M19 11a7 7 0 01-14 0M12 18v3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        </button>
        <button class="voice-ctrl end" title="End voice mode" onclick="closeVoice()">
          <svg viewBox="0 0 24 24" fill="none"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>
        </button>
        <button class="voice-ctrl" title="Switch to text" onclick="closeVoice()">
          <svg viewBox="0 0 24 24" fill="none"><path d="M4 5h16v11H8l-4 4V5z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>
        </button>
      </div>
    </div>
  </div>
</div>

<!-- Wake-word toast notification -->
<div class="toast" id="wakeToast">🎤 Hey Hachi detected!</div>

<!-- Pomodoro session complete notification -->
<div class="pomo-notify" id="pomoNotify">
    <div class="pomo-notify-card">
        <div class="pomo-notify-icon" id="pomoNotifyIcon">🍅</div>
        <div class="pomo-notify-title" id="pomoNotifyTitle">Session Complete!</div>
        <div class="pomo-notify-sub" id="pomoNotifyMsg">Great work! Time for a 5-minute break.</div>
        <div>
            <button class="pomo-notify-btn" id="pomoNotifyAction" onclick="pomoNextAction()">Start Break ☕</button>
            <button class="pomo-notify-btn secondary" onclick="stopPomodoro()">Stop</button>
        </div>
    </div>
</div>

{js_code}

<script>
  /* Build the hover-animated hero title from words */
  const titleWords = ["What", "can", "I", "do", "for", "you?"];
  const heroTitle = document.getElementById('heroTitle');
  titleWords.forEach(w => {{
    const span = document.createElement('span');
    span.className = 'word';
    span.textContent = w;
    heroTitle.appendChild(span);
  }});

  /* Loader logic */
  (function(){{
    const loaderScreen = document.getElementById('loaderScreen');
    const appScreen = document.querySelector('.app');
    if(!loaderScreen) return;
    requestAnimationFrame(function(){{
      requestAnimationFrame(function(){{ loaderScreen.classList.add('visible'); }});
    }});
    setTimeout(function(){{
      loaderScreen.classList.add('split');
      if(appScreen) appScreen.classList.add('revealed');
      setTimeout(function(){{ loaderScreen.style.display = 'none'; }}, 1500);
    }}, 4000);
  }})();
</script>

</body>
</html>
'''

try:
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(new_html)
    print('Done writing index.html')
except Exception as e:
    print(f'Failed to write: {e}')
    sys.exit(1)
