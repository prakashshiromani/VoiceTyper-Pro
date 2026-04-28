"""
VoiceTyper Pro — v18 (Speed Edition)
-------------------------------------
Major performance overhaul:
- Near-zero keyboard typing delay
- Parallel audio recognition workers
- Disabled dynamic energy threshold to prevent speech drops
- Faster clipboard injection for Hindi/special chars
"""

import threading
import queue
import time
import sys
import re
import tkinter as tk
from tkinter import ttk

import speech_recognition as sr
import pyperclip
import keyboard

# --- 1. CONFIG & PALETTE ---
LANGUAGE        = "en-IN"
TOGGLE_HOTKEY   = "ctrl+space"

C_BG      = "#1A1D23"
C_MID     = "#2A2E38"
C_CYAN    = "#00F5FF"
C_LIGHT   = "#E0E6ED"
C_GREY    = "#707A8A"
BTN_START = "#00D48A"
BTN_STOP  = "#FF4C5E"

# --- 2. GLOBAL STATE ---
recognizer = sr.Recognizer()
# SPEED TUNING:
# pause_threshold: How long (sec) of silence to wait before considering the phrase complete.
# Lower = faster response after you stop speaking. 0.4 is snappy but not choppy.
recognizer.pause_threshold            = 0.4
recognizer.non_speaking_duration      = 0.3
recognizer.phrase_threshold           = 0.1
recognizer.energy_threshold           = 300
# Disable dynamic adjustment — prevents the recognizer from raising the threshold
# so high that it stops hearing you (the main cause of "sometimes doesn't type").
recognizer.dynamic_energy_threshold   = False

try: mic = sr.Microphone()
except: print("Mic error"); sys.exit(1)

listening      = False
session_id     = 0
audio_queue    = queue.Queue(maxsize=30)   # Larger buffer so audio is never dropped
NUM_WORKERS    = 3                         # Parallel recognition threads

# UI Widgets
root       = None
popup      = None
main_frame = None
btn_lbl    = None
dot_cv     = None
lang_var   = None
sens_var   = None
chips      = {}

# Animation
p_active   = False
p_alpha    = 0.0
p_dir      = 1

# --- 3. CORE LOGIC ---

def smart_polish(text):
    # Expanded list of common fillers
    fillers = [
        r'\bum+\b', r'\buh+\b', r'\bah+\b', r'\blike\b', 
        r'\byou know\b', r'\bactually\b', r'\bbasically\b', 
        r'\bso\b', r'\bI mean\b'
    ]
    for f in fillers: text = re.sub(f, '', text, flags=re.IGNORECASE)
    
    low = text.lower().strip()
    
    # Integrated Voice Commands
    if "new line" in low: 
        keyboard.press_and_release("enter")
        return ""
    if "backspace" in low or "erase that" in low: 
        keyboard.press_and_release("backspace")
        return ""
    if "tab space" in low:
        keyboard.press_and_release("tab")
        return ""
        
    text = text.strip()
    # Improved capitalization: handle cases where speech might start with a lowercase letter
    if len(text) > 0:
        text = text[0].upper() + text[1:]
    return text

def type_text(text):
    text = smart_polish(text)
    if not text: return
    try:
        try:
            # ASCII path: delay reduced from 0.012 → 0.002 (6x faster keyboard simulation)
            text.encode("ascii"); keyboard.write(text + " ", delay=0.002)
        except:
            # Non-ASCII (Hindi/special chars): use clipboard injection
            # Sleeps reduced from 40ms → 20ms for faster paste
            old = pyperclip.paste()
            pyperclip.copy(text + " ")
            time.sleep(0.02)
            keyboard.press_and_release("ctrl+v")
            time.sleep(0.02)
            try: pyperclip.copy(old)
            except: pass
    except: pass

# --- 4. ULTIMATE WINDOW MANAGEMENT (v17) ---

def apply_rounded_corners():
    try:
        from ctypes import windll, c_int, byref, sizeof
        # We need the HWND of the popup Toplevel
        HWND = windll.user32.GetParent(popup.winfo_id())
        windll.dwmapi.DwmSetWindowAttribute(HWND, 33, byref(c_int(2)), sizeof(c_int))
    except: pass

def minimize_window():
    """Minimizes the invisible root, which automatically hides the UI Toplevel."""
    print("[UI] Minimizing via Master Handle...")
    root.iconify()

def on_master_map(event):
    """When the master window is restored from taskbar, show the UI again."""
    if str(event.widget) == "." and popup:
        popup.deiconify()
        popup.lift()
        apply_rounded_corners()

def on_master_unmap(event):
    """When master window is minimized, hide the UI Toplevel."""
    if str(event.widget) == "." and popup:
        popup.withdraw()

# --- 5. ENGINE LOOPS ---

def listen_loop():
    global listening
    sid = session_id
    try:
        with mic as source:
            # Reduced from 0.3s → 0.1s — faster startup, still effective
            recognizer.adjust_for_ambient_noise(source, duration=0.1)
            while listening and session_id == sid:
                try:
                    # timeout=0.5: don't wait too long for speech to begin
                    # phrase_time_limit=8: cap phrases at 8s to avoid stalls
                    audio = recognizer.listen(source, timeout=0.5, phrase_time_limit=8)
                    if not listening or session_id != sid: break
                    audio_queue.put((audio, sid))  # blocking put — never drop chunks
                except sr.WaitTimeoutError:
                    pass  # Normal: no speech in this window, keep looping
                except: pass
    except: pass

def proc_worker(sid):
    """A single recognition worker — runs in its own thread."""
    while True:
        try:
            item = audio_queue.get(timeout=0.5)
        except queue.Empty:
            # If listening stopped and queue is drained, exit worker
            if not listening:
                break
            continue
        audio, audio_sid = item
        if audio_sid != sid:
            audio_queue.task_done()
            continue
        try:
            lang = lang_var.get() if lang_var.get() != "auto" else None
            text = recognizer.recognize_google(audio, language=lang)
            if text: type_text(text)
        except sr.UnknownValueError:
            pass  # Speech not understood — normal, skip silently
        except sr.RequestError:
            pass  # Network issue — skip
        except: pass
        finally:
            audio_queue.task_done()
    safe(lambda: toggle_active(False))

# --- 6. UI CONTROLS ---

def safe(fn):
    try:
        if root and root.winfo_exists(): root.after(0, fn)
    except: pass

def toggle_active(active):
    global is_active, p_active
    is_active = active; p_active = active
    if active:
        main_frame.config(highlightbackground=C_CYAN)
        btn_lbl.config(bg=BTN_STOP, text="■  STOP (Listening)")
    else:
        main_frame.config(highlightbackground=C_MID)
        btn_lbl.config(bg=BTN_START, text="▶  START (Ctrl+Space)")
        safe(lambda: dot_cv.itemconfig("dot", fill=C_MID))

def toggle_voice(*_):
    global listening, session_id
    if not listening:
        listening = True
        session_id += 1
        toggle_active(True)
        # 1 listener thread captures audio
        threading.Thread(target=listen_loop, daemon=True).start()
        # NUM_WORKERS parallel threads process audio simultaneously
        # so one slow API call doesn't block the next chunk
        for _ in range(NUM_WORKERS):
            threading.Thread(target=proc_worker, args=(session_id,), daemon=True).start()
    else:
        listening = False
        session_id += 1

# --- 7. UI CONSTRUCTION ---

class LangChip(tk.Label):
    def __init__(self, parent, text, code):
        super().__init__(parent, text=text, bg=C_MID, fg=C_LIGHT, font=("Segoe UI", 7, "bold"), padx=6, pady=2, cursor="hand2")
        self.code = code
        self.bind("<Button-1>", lambda e: self.select())
    def select(self):
        lang_var.set(self.code)
        for chip in chips.values(): chip.update_look()
    def update_look(self):
        self.config(bg=C_CYAN if lang_var.get() == self.code else C_MID, fg=C_BG if lang_var.get() == self.code else C_LIGHT)

def pulse():
    global p_alpha, p_dir
    if p_active and dot_cv:
        p_alpha += 0.08 * p_dir
        if p_alpha >= 1.0: p_alpha=1.0; p_dir=-1
        elif p_alpha <= 0.2: p_alpha=0.2; p_dir=1
        c = f"#{0:02x}{int(0xF5*p_alpha):02x}{int(0xFF*p_alpha):02x}"
        safe(lambda: dot_cv.itemconfig("dot", fill=c))
        main_frame.config(highlightbackground=c)
    if root: root.after(50, pulse)

def update_mic_level():
    if energy_lbl and energy_lbl.winfo_exists():
        val = int(recognizer.energy_threshold)
        col = BTN_START if val < 1000 else "#FFB347" if val < 2500 else BTN_STOP
        energy_lbl.config(text=f"mic: {val}", fg=col)
        cap = int(800 + (sens_var.get() - 1) * 400)
        if recognizer.energy_threshold > cap: recognizer.energy_threshold = cap
        root.after(100, update_mic_level)

def build_ui():
    global root, popup, main_frame, energy_lbl, btn_lbl, dot_cv, lang_var, sens_var

    # MASTER WINDOW (Invisible Taskbar Manager)
    root = tk.Tk()
    root.title("VT Pro")
    root.geometry("1x1+0+0")
    root.attributes("-alpha", 0.0) # Completely invisible
    root.bind("<Map>", on_master_map)
    root.bind("<Unmap>", on_master_unmap)

    # UI WINDOW (The Premium Micro UI)
    popup = tk.Toplevel(root)
    popup.overrideredirect(True) # Permanent borderless
    popup.attributes("-topmost", True)
    popup.configure(bg=C_BG)

    apply_rounded_corners()

    W, H = 210, 155
    sw, sh = popup.winfo_screenwidth(), popup.winfo_screenheight()
    popup.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")

    popup.bind("<Button-1>", lambda e: setattr(popup, "_dx", e.x) or setattr(popup, "_dy", e.y))
    popup.bind("<B1-Motion>", lambda e: popup.geometry(f"+{popup.winfo_x()+e.x-popup._dx}+{popup.winfo_y()+e.y-popup._dy}"))

    main_frame = tk.Frame(popup, bg=C_BG, highlightthickness=2, highlightbackground=C_MID)
    main_frame.pack(fill="both", expand=True, padx=2, pady=2)

    # --- Header ---
    hdr = tk.Frame(main_frame, bg=C_BG)
    hdr.pack(fill="x", padx=8, pady=(8, 4))
    
    # Blinking Dot on Far Left
    dot_cv = tk.Canvas(hdr, width=10, height=10, bg=C_BG, highlightthickness=0)
    dot_cv.pack(side="left", padx=(0, 5))
    dot_cv.create_oval(1, 1, 9, 9, fill=C_MID, tags="dot")

    tk.Label(hdr, text="Voice", bg=C_BG, fg=C_CYAN, font=("Segoe UI", 9, "bold")).pack(side="left")
    tk.Label(hdr, text="Typer pro", bg=C_BG, fg=C_LIGHT, font=("Segoe UI", 8)).pack(side="left")
    
    # Buttons Container
    box = tk.Frame(hdr, bg=C_BG)
    box.pack(side="right")
    
    # Larger Click Hitboxes for Min/Close
    mn = tk.Label(box, text=" — ", bg=C_BG, fg=C_GREY, font=("Segoe UI", 10, "bold"), cursor="hand2")
    mn.pack(side="left")
    mn.bind("<Button-1>", lambda e: minimize_window())
    mn.bind("<Enter>", lambda e: mn.config(fg=C_CYAN))
    mn.bind("<Leave>", lambda e: mn.config(fg=C_GREY))
    
    cl = tk.Label(box, text=" ✕ ", bg=C_BG, fg=C_GREY, font=("Segoe UI", 10, "bold"), cursor="hand2")
    cl.pack(side="left")
    cl.bind("<Button-1>", lambda e: sys.exit(0))
    cl.bind("<Enter>", lambda e: cl.config(fg=BTN_STOP))
    cl.bind("<Leave>", lambda e: cl.config(fg=C_GREY))

    tk.Frame(main_frame, bg=C_MID, height=1).pack(fill="x")

    # --- Body ---
    body = tk.Frame(main_frame, bg=C_BG)
    body.pack(fill="both", expand=True, padx=10, pady=5)

    btn_lbl = tk.Label(body, text="▶  START (Ctrl+Space)", bg=BTN_START, fg="white", font=("Segoe UI", 8, "bold"), cursor="hand2", pady=5)
    btn_lbl.pack(fill="x")
    btn_lbl.bind("<Button-1>", lambda e: toggle_voice())

    lang_var = tk.StringVar(value="en-IN")
    r1 = tk.Frame(body, bg=C_BG); r1.pack(pady=(6, 0))
    for t, c in [("Auto", "auto"), ("Hindi", "hi-IN"), ("Eng", "en-IN")]:
        ch = LangChip(r1, t, c); ch.pack(side="left", padx=2); chips[c] = ch
    for ch in chips.values(): ch.update_look()

    r2 = tk.Frame(body, bg=C_BG); r2.pack(pady=(4, 0))
    tk.Label(r2, text="Sen: Whisper", bg=C_BG, fg=C_CYAN, font=("Segoe UI", 6)).pack(side="left")
    sens_var = tk.IntVar(value=3)
    s = ttk.Style(); s.theme_use("clam")
    s.configure("C.Horizontal.TScale", background=C_BG, troughcolor=C_MID, sliderthickness=10)
    ttk.Scale(r2, from_=1, to=10, variable=sens_var, length=60, style="C.Horizontal.TScale").pack(side="left", padx=2)
    tk.Label(r2, text="Noise", bg=C_BG, fg=BTN_STOP, font=("Segoe UI", 6)).pack(side="left")

    # --- Status Bar ---
    status_bar = tk.Frame(body, bg=C_BG)
    status_bar.pack(side="bottom", fill="x", pady=(10, 5))

    energy_lbl = tk.Label(status_bar, text="mic: --", bg=C_BG, fg=BTN_START, font=("Segoe UI", 7))
    energy_lbl.pack(side="left", padx=(2, 0))

    tk.Label(status_bar, text="  |  ", bg=C_BG, fg=C_MID, font=("Segoe UI", 7)).pack(side="left")

    shortcut_lbl = tk.Label(status_bar, text=f"Hotkey: {TOGGLE_HOTKEY.upper()}", bg=C_BG, fg=C_LIGHT, font=("Segoe UI", 7))
    shortcut_lbl.pack(side="left")

    keyboard.add_hotkey(TOGGLE_HOTKEY, lambda: root.after(0, toggle_voice))
    root.after(80, pulse); root.after(100, update_mic_level)
    root.mainloop()

if __name__ == "__main__":
    build_ui()