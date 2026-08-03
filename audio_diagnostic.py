"""
HACHI Audio Diagnostic Tool
Helps troubleshoot microphone and speech recognition issues
"""

import speech_recognition as sr
import pyaudio
from pprint import pprint

def list_audio_devices():
    """List all available audio devices"""
    print("\n" + "="*60)
    print("AVAILABLE AUDIO DEVICES")
    print("="*60)
    
    p = pyaudio.PyAudio()
    device_count = p.get_device_count()
    
    if device_count == 0:
        print("❌ No audio devices found!")
        return
    
    print(f"Found {device_count} audio device(s):\n")
    
    for i in range(device_count):
        info = p.get_device_info_by_index(i)
        device_type = "INPUT" if info['maxInputChannels'] > 0 else "OUTPUT"
        print(f"[{i}] {info['name']}")
        print(f"    Type: {device_type}")
        print(f"    Channels: {info['maxInputChannels']} input, {info['maxOutputChannels']} output")
        print(f"    Sample Rate: {info['defaultSampleRate']}")
        print()
    
    p.terminate()

def test_microphone():
    """Test microphone input"""
    print("\n" + "="*60)
    print("TESTING MICROPHONE INPUT")
    print("="*60)
    
    recognizer = sr.Recognizer()
    
    try:
        with sr.Microphone() as source:
            print("\n🎤 Microphone detected!")
            print("Adjusting for ambient noise...")
            recognizer.adjust_for_ambient_noise(source, duration=2)
            print("✓ Noise adjustment complete")
            
            print("\n📝 Please speak now (you have 5 seconds)...")
            print("Say something like: 'Hello, this is a test'")
            
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=5)
            print("✓ Audio captured!")
            
            print("\nAttempting to recognize speech...")
            try:
                text = recognizer.recognize_google(audio)
                print(f"✅ Recognized: '{text}'")
                return True
            except sr.UnknownValueError:
                print("❌ Could not understand audio (speech unclear)")
                return False
            except sr.RequestError as e:
                print(f"❌ API Error: {e}")
                print("   This might be a network issue with Google Speech API")
                return False
                
    except Exception as e:
        print(f"❌ Microphone Error: {e}")
        print("   Check if microphone is connected and enabled")
        return False

def test_speech_engines():
    """Test text-to-speech engines"""
    print("\n" + "="*60)
    print("TESTING TEXT-TO-SPEECH")
    print("="*60)
    
    import pyttsx3
    
    try:
        engine = pyttsx3.init()
        print("✓ pyttsx3 initialized")
        
        # Get available voices
        voices = engine.getProperty('voices')
        print(f"✓ Found {len(voices)} voice(s)")
        
        # Test speech
        print("\n🔊 Testing voice output...")
        engine.say("Hello, this is Hachi. Audio test successful.")
        engine.runAndWait()
        print("✓ Text-to-speech works!")
        
        return True
    except Exception as e:
        print(f"❌ Text-to-speech Error: {e}")
        return False

def main():
    print("\n")
    print(" " * 60)
    print("  HACHI - AUDIO DIAGNOSTIC TOOL")
    print(" " * 60)
    
    # List devices
    list_audio_devices()
    
    # Test microphone
    mic_ok = test_microphone()
    
    # Test TTS
    tts_ok = test_speech_engines()
    
    # Summary
    print("\n" + "="*60)
    print("DIAGNOSTIC SUMMARY")
    print("="*60)
    print(f"Microphone:        {'✅ OK' if mic_ok else '❌ FAILED'}")
    print(f"Text-to-Speech:    {'✅ OK' if tts_ok else '❌ FAILED'}")
    
    if mic_ok and tts_ok:
        print("\n✅ All systems ready! You can now run: python hachi_gui.py")
    else:
        print("\n⚠️  Some issues detected. Please fix them before running Hachi.")
        
        if not mic_ok:
            print("\n📋 MICROPHONE FIXES:")
            print("  1. Check if microphone is connected")
            print("  2. Go to Settings > Sound > Volume and Test microphone")
            print("  3. Make sure Hachi app has microphone permission")
            print("  4. Try a different microphone if available")
        
        if not tts_ok:
            print("\n📋 TEXT-TO-SPEECH FIXES:")
            print("  1. Check System Sound Settings")
            print("  2. Ensure speakers are connected and working")
            print("  3. Check volume levels")

if __name__ == "__main__":
    main()
