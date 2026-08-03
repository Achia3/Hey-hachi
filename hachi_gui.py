import tkinter as tk
from tkinter import scrolledtext, messagebox
import threading
import logging
import speech_recognition as sr
import pyttsx3
import ollama
import time
from datetime import datetime
from typing import Optional
import sys

# Configure logging
logging.basicConfig(
    filename="hachi.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# Test Ollama connection
def check_ollama_connection():
    """Check if Ollama is running and accessible"""
    try:
        response = ollama.list()
        return True, "Connected"
    except Exception as e:
        return False, str(e)

class HachiAI:
    """
    HACHI - Advanced Voice-Enabled AI Assistant
    - GUI-based interface with voice interaction
    - Wake word detection: "Hey, Hachi"
    - Real-time voice input/output
    """
    
    def __init__(self, root):
        self.root = root
        self.root.title("HACHI - AI Voice Assistant")
        self.root.geometry("800x600")
        self.root.configure(bg="#1e1e1e")
        
        # Initialize voice components
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 4000
        self.recognizer.dynamic_energy_threshold = True
        self.engine = pyttsx3.init()
        self.engine.setProperty("rate", 150)  # Speed of speech
        
        # Find best microphone
        self.microphone_index = self.find_best_microphone()
        
        # AI Configuration
        self.ai_name = "Hachi"
        self.wake_word = "hey hachi"
        self.model = "qwen2.5:3b"
        self.ollama_host = "http://localhost:11434"
        
        # State tracking
        self.is_listening = False
        self.is_speaking = False
        self.conversation_history = []
        
        self.setup_gui()
        
    def setup_gui(self):
        """Setup the GUI interface"""
        # Header
        header_frame = tk.Frame(self.root, bg="#2d2d2d", height=80)
        header_frame.pack(fill=tk.X, padx=0, pady=0)
        header_frame.pack_propagate(False)
        
        title_label = tk.Label(
            header_frame,
            text="🎤 HACHI - AI Voice Assistant",
            font=("Helvetica", 24, "bold"),
            bg="#2d2d2d",
            fg="#00ff00"
        )
        title_label.pack(pady=20)
        
        status_label = tk.Label(
            header_frame,
            text="Say 'Hey, Hachi' to activate",
            font=("Helvetica", 12),
            bg="#2d2d2d",
            fg="#00d4ff"
        )
        status_label.pack()
        self.status_label = status_label
        
        # Main content frame
        content_frame = tk.Frame(self.root, bg="#1e1e1e")
        content_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        # Conversation display
        conv_label = tk.Label(
            content_frame,
            text="Conversation Log:",
            font=("Helvetica", 11, "bold"),
            bg="#1e1e1e",
            fg="#ffffff"
        )
        conv_label.pack(anchor=tk.W, pady=(0, 5))
        
        self.conversation_display = scrolledtext.ScrolledText(
            content_frame,
            height=15,
            width=80,
            bg="#2d2d2d",
            fg="#00ff00",
            font=("Courier", 10),
            wrap=tk.WORD
        )
        self.conversation_display.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        self.conversation_display.config(state=tk.DISABLED)
        
        # Control buttons frame
        button_frame = tk.Frame(content_frame, bg="#1e1e1e")
        button_frame.pack(fill=tk.X)
        
        # Start listening button
        self.listen_btn = tk.Button(
            button_frame,
            text="🎤 Start Listening",
            command=self.start_listening,
            bg="#00ff00",
            fg="#000000",
            font=("Helvetica", 11, "bold"),
            padx=20,
            pady=10,
            relief=tk.RAISED
        )
        self.listen_btn.pack(side=tk.LEFT, padx=5)
        
        # Stop button
        self.stop_btn = tk.Button(
            button_frame,
            text="⏹ Stop",
            command=self.stop_listening,
            bg="#ff6b6b",
            fg="#ffffff",
            font=("Helvetica", 11, "bold"),
            padx=20,
            pady=10,
            relief=tk.RAISED,
            state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
        # Clear button
        clear_btn = tk.Button(
            button_frame,
            text="🗑 Clear Log",
            command=self.clear_log,
            bg="#4a90e2",
            fg="#ffffff",
            font=("Helvetica", 11, "bold"),
            padx=20,
            pady=10,
            relief=tk.RAISED
        )
        clear_btn.pack(side=tk.LEFT, padx=5)
        
        # Footer
        footer_label = tk.Label(
            self.root,
            text="Status: Ready | Make sure Ollama is running",
            font=("Helvetica", 9),
            bg="#2d2d2d",
            fg="#888888"
        )
        footer_label.pack(fill=tk.X, padx=10, pady=10)
        self.footer_label = footer_label
        
    def find_best_microphone(self) -> int:
        """Find the best available microphone"""
        try:
            import pyaudio
            p = pyaudio.PyAudio()
            
            # Preferred microphones in order
            preferred = ["Razer BlackShark", "Microphone (USB", "Microphone"]
            
            device_count = p.get_device_count()
            default_device = None
            
            # First pass: look for preferred microphones
            for i in range(device_count):
                info = p.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0:  # Input device
                    device_name = info['name']
                    for pref in preferred:
                        if pref.lower() in device_name.lower():
                            p.terminate()
                            return i
                    if default_device is None:
                        default_device = i
            
            # Fallback to first available input device
            if default_device is not None:
                p.terminate()
                return default_device
            
            p.terminate()
            return None  # No input device found
            
        except Exception as e:
            logging.error(f"Error finding microphone: {e}")
            return None
        
    def display_message(self, sender: str, message: str):
        """Display a message in the conversation log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        self.conversation_display.config(state=tk.NORMAL)
        if sender == "You":
            self.conversation_display.insert(tk.END, f"[{timestamp}] {sender}: ", "user")
            self.conversation_display.insert(tk.END, f"{message}\n", "user_text")
        else:
            self.conversation_display.insert(tk.END, f"[{timestamp}] {sender}: ", "ai")
            self.conversation_display.insert(tk.END, f"{message}\n", "ai_text")
        
        self.conversation_display.see(tk.END)
        self.conversation_display.config(state=tk.DISABLED)
        
    def clear_log(self):
        """Clear the conversation log"""
        self.conversation_display.config(state=tk.NORMAL)
        self.conversation_display.delete(1.0, tk.END)
        self.conversation_display.config(state=tk.DISABLED)
        self.conversation_history = []
        
    def listen_for_audio(self) -> Optional[str]:
        """Listen for audio input and convert to text"""
        try:
            # Use specific microphone if found, otherwise default
            if self.microphone_index is not None:
                source = sr.Microphone(device_index=self.microphone_index)
            else:
                source = sr.Microphone()
            
            with source as mic_source:
                self.update_status("🎤 Listening...", "#ffff00")
                self.root.update()
                
                # Adjust for ambient noise (shorter duration for responsiveness)
                self.recognizer.adjust_for_ambient_noise(mic_source, duration=0.5)
                
                # Listen for audio with longer timeout for voice detection
                try:
                    audio = self.recognizer.listen(
                        mic_source, 
                        timeout=15,  # Wait up to 15 seconds to start speaking
                        phrase_time_limit=15  # Allow up to 15 seconds of speech
                    )
                except sr.WaitTimeoutError:
                    self.update_status("⏰ Timeout - No audio detected. Try again.", "#ffff00")
                    self.log_event("Timeout waiting for audio")
                    return None
                
                self.update_status("🔄 Processing audio...", "#ffff00")
                self.root.update()
                
                # Recognize speech using Google API
                try:
                    text = self.recognizer.recognize_google(audio)
                    self.log_event(f"Recognized: {text}")
                    return text.lower()
                except sr.UnknownValueError:
                    self.update_status("❌ Could not understand. Speak more clearly.", "#ff6b6b")
                    self.log_event("Could not understand audio input")
                    return None
                except sr.RequestError as e:
                    self.update_status(f"❌ API Error: {str(e)[:50]}", "#ff6b6b")
                    self.log_event(f"Recognition API error: {e}")
                    return None
                
        except Exception as e:
            self.update_status(f"❌ Microphone error: {str(e)[:50]}", "#ff6b6b")
            self.log_event(f"Microphone error: {e}")
            return None
    
    def detect_wake_word(self, text: str) -> bool:
        """Check if wake word is detected in text"""
        # More flexible matching - accepts "hey hachi" or "hey hach"
        if not text:
            return False
        
        words = text.split()
        
        # Look for "hey" followed by "hach*" (hachi, hach, etc)
        for i in range(len(words) - 1):
            if words[i].lower() == "hey":
                next_word = words[i + 1].lower()
                # Match "hachi", "hach", "haci", etc
                if next_word.startswith("hach"):
                    self.log_event(f"Wake word matched: {words[i]} {next_word}")
                    return True
        
        return False
    
    def get_ai_response(self, user_input: str) -> str:
        """Get response from Ollama AI model"""
        try:
            self.update_status("🤖 Hachi is thinking...", "#00d4ff")
            self.root.update()
            
            response = ollama.chat(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": user_input
                    }
                ]
            )
            
            return response['message']['content'].strip()
            
        except Exception as e:
            self.log_event(f"AI Response error: {e}")
            return f"I encountered an error: {str(e)}"
    
    def speak(self, text: str):
        """Convert text to speech"""
        try:
            self.is_speaking = True
            self.update_status("🔊 Hachi is speaking...", "#ff6b6b")
            self.root.update()
            
            self.engine.say(text)
            self.engine.runAndWait()
            
            self.is_speaking = False
            
        except Exception as e:
            self.log_event(f"Text-to-speech error: {e}")
        
    def start_listening(self):
        """Start the voice listening loop"""
        if self.is_listening:
            return
        
        self.is_listening = True
        self.listen_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        
        # Start listening in a separate thread
        thread = threading.Thread(target=self.listening_loop, daemon=True)
        thread.start()
    
    def listening_loop(self):
        """Main listening loop"""
        self.display_message("System", f"{self.ai_name} is ready. Waiting for activation...")
        self.log_event("Listening loop started")
        
        while self.is_listening:
            try:
                # Listen for audio
                audio_text = self.listen_for_audio()
                
                if audio_text is None:
                    time.sleep(0.5)
                    continue
                
                # Display what was heard
                self.display_message("You (heard)", audio_text)
                self.log_event(f"Detected audio: {audio_text}")
                
                # Check for wake word
                if self.detect_wake_word(audio_text):
                    self.update_status("✅ Activated! Listening to command...", "#00ff00")
                    self.display_message("System", "✓ Wake word detected! Say your command...")
                    self.log_event("Wake word detected, waiting for command")
                    
                    # Listen for the actual command
                    time.sleep(0.5)
                    command_text = self.listen_for_audio()
                    
                    if command_text and command_text.strip():
                        self.log_event(f"Command received: {command_text}")
                        self.display_message("You", command_text)
                        
                        # Get AI response
                        self.log_event("Requesting AI response...")
                        response = self.get_ai_response(command_text)
                        
                        if response:
                            self.log_event(f"AI Response: {response}")
                            self.display_message(self.ai_name, response)
                            
                            # Speak the response (non-blocking in thread)
                            speak_thread = threading.Thread(
                                target=self.speak,
                                args=(response,),
                                daemon=True
                            )
                            speak_thread.start()
                            
                            logging.info(f"User: {command_text}")
                            logging.info(f"Hachi: {response}")
                            
                            self.update_status("Ready for next command", "#00ff00")
                        else:
                            self.log_event("No response from AI")
                            self.display_message("System", "❌ Sorry, I couldn't generate a response.")
                            self.update_status("Ready for next command", "#00ff00")
                    else:
                        self.log_event("No command received after wake word")
                        self.display_message("System", "⏰ No command detected. Say 'Hey, Hachi' again.")
                        self.update_status("Waiting for activation...", "#ffff00")
                    
                    # Short pause before resuming
                    time.sleep(1)
                else:
                    self.update_status("Waiting for 'Hey, Hachi'...", "#ffff00")
                    time.sleep(0.5)
                    
            except Exception as e:
                self.log_event(f"Listening loop error: {e}")
                self.update_status(f"❌ Error: {str(e)[:40]}", "#ff6b6b")
                time.sleep(2)
    
    def stop_listening(self):
        """Stop the listening loop"""
        self.is_listening = False
        self.listen_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.update_status("⏹ Stopped", "#ff6b6b")
        self.display_message("System", "Listening stopped.")
    
    def update_status(self, status: str, color: str = "#00ff00"):
        """Update the status label"""
        self.status_label.config(text=status, fg=color)
        self.footer_label.config(text=f"Status: {status}")
    
    def log_event(self, message: str):
        """Log an event"""
        logging.info(message)
        print(f"[LOG] {message}")

def main():
    # Check Ollama before creating GUI
    is_connected, status = check_ollama_connection()
    
    if not is_connected:
        print(f"❌ Ollama Connection Failed: {status}")
        print("\n⚠️  IMPORTANT: Please start Ollama first:")
        print("   1. Open a new PowerShell window")
        print("   2. Run: ollama serve")
        print("   3. Then run this script again")
        
        # Still create GUI to show error
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Ollama Connection Error",
            f"Cannot connect to Ollama at localhost:11434\n\n{status}\n\n"
            "Please start Ollama first by running:\n\norama serve"
        )
        root.destroy()
        sys.exit(1)
    
    # If Ollama is connected, proceed with GUI
    try:
        root = tk.Tk()
        app = HachiAI(root)
        root.mainloop()
    except Exception as e:
        print(f"❌ Error starting Hachi: {e}")
        logging.error(f"Startup error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
