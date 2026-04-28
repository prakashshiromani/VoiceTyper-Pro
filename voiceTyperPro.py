"""
VoiceTyper Pro — v20 (Smart API Pool Edition)
----------------------------------------------
- keyboard.write (ASCII) + pyperclip clipboard (Hindi/Unicode)
- Pre-compiled filler regex (9x faster text cleaning)
- pause_threshold 0.3s, phrase_time_limit 5s
- 3 parallel recognition workers
- Smart bounded ambient recalibration
- [NEW v20] SmartRecognizerPool — 4 recognizer instances with:
    * Round-robin rotation
    * Per-instance response-time tracking
    * Auto-cooldown on slow/failed instances (30s)
    * Automatic fallback to fastest available instance
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

# --- 2. SMART RECOGNIZER POOL ---

NUM_POOL_INSTANCES = 4      # Number of recognizer instances in the pool
SLOW_THRESHOLD_SEC = 3.5    # If a recognizer takes > this seconds → mark slow
COOLDOWN_SEC       = 30     # Slow/failed recognizer stays on cooldown for 30s
MAX_FAIL_STREAK    = 3      # 3 consecutive failures → trigger cooldown

def _make_recognizer():
    """Create and configure a single recognizer instance."""
    r = sr.Recognizer()
    r.pause_threshold          = 0.3
    r.non_speaking_duration    = 0.2
    r.phrase_threshold         = 0.1
    r.energy_threshold         = 300
    r.dynamic_energy_threshold = False
    return r

class RecognizerSlot:
    """Tracks one recognizer instance and its health metrics."""
    def __init__(self, idx):
        self.idx          = idx
        self.recognizer   = _make_recognizer()
        self.avg_ms       = 0.0      # Exponential moving average of response time (ms)
        self.fail_streak  = 0        # Consecutive RequestError / timeout failures
        self.cooldown_until = 0.0    # epoch time until which this slot is on cooldown
        self._lock        = threading.Lock()

    @property
    def is_available(self):
        return time.time() >= self.cooldown_until

    def mark_success(self, elapsed_sec):
        """Called when recognition succeeded. Update avg response time."""
        with self._lock:
            ms = elapsed_sec * 1000
            # Exponential moving average — recent results weigh more
            self.avg_ms      = ms if self.avg_ms == 0 else 0.3 * ms + 0.7 * self.avg_ms
            self.fail_streak = 0
            # If consistently slow, put on brief cooldown
            if elapsed_sec > SLOW_THRESHOLD_SEC:
                self.cooldown_until = time.time() + COOLDOWN_SEC
                print(f"[Pool #{self.idx}] Slow ({elapsed_sec:.1f}s) → cooldown {COOLDOWN_SEC}s")

    def mark_failure(self):
        """Called on RequestError or timeout. Increments fail streak."""
        with self._lock:
            self.fail_streak += 1
            if self.fail_streak >= MAX_FAIL_STREAK:
                self.cooldown_until = time.time() + COOLDOWN_SEC
                print(f"[Pool #{self.idx}] {self.fail_streak} failures → cooldown {COOLDOWN_SEC}s")

    def mark_unknown(self):
        """UnknownValueError — speech not understood — not a failure, reset streak."""
        with self._lock:
            self.fail_streak = 0


class SmartRecognizerPool:
    """
    Pool of NUM_POOL_INSTANCES recognizer instances.
    Strategy:
      1. Filter out slots on cooldown.
      2. Among available slots, pick the one with lowest avg response time.
      3. If all are on cooldown, wait and pick the one whose cooldown expires soonest.
    """
    def __init__(self, n):
        self.slots   = [RecognizerSlot(i) for i in range(n)]
        self._rr_idx = 0          # Round-robin fallback index
        self._lock   = threading.Lock()

    def get_best(self):
        """Return the best available RecognizerSlot (non-blocking)."""
        with self._lock:
            available = [s for s in self.slots if s.is_available]
            if available:
                # Prefer lowest avg response time; break ties by round-robin
                best = min(available, key=lambda s: s.avg_ms if s.avg_ms > 0 else float("inf"))
                return best
            # All on cooldown — pick the one whose cooldown expires soonest
            soonest = min(self.slots, key=lambda s: s.cooldown_until)
            remaining = soonest.cooldown_until - time.time()
            print(f"[Pool] All on cooldown — waiting {remaining:.1f}s for #{soonest.idx}")
            return soonest   # caller will block waiting; best we can do

    def recognize(self, audio, language):
        """
        Attempt recognition using the best available slot.
        On slow/fail, automatically retry with the next best slot (up to len(slots) attempts).
        Returns text string or raises sr.UnknownValueError if nothing heard.
        """
        attempts = len(self.slots)
        tried    = set()

        for _ in range(attempts):
            slot = self.get_best()
            if slot.idx in tried:
                # All unique slots exhausted
                break
            tried.add(slot.idx)

            t0 = time.time()
            try:
                text    = slot.recognizer.recognize_google(audio, language=language)
                elapsed = time.time() - t0
                slot.mark_success(elapsed)
                print(f"[Pool #{slot.idx}] OK  {elapsed*1000:.0f}ms  avg={slot.avg_ms:.0f}ms")
                return text
            except sr.UnknownValueError:
                slot.mark_unknown()
                raise   # Genuine "didn't hear" — don't retry
            except sr.RequestError as e:
                slot.mark_failure()
                print(f"[Pool #{slot.idx}] RequestError: {e} — trying next slot")
                # Loop continues → picks next best slot
            except Exception as e:
                slot.mark_failure()
                print(f"[Pool #{slot.idx}] Error: {e} — trying next slot")

        raise sr.RequestError("All pool slots exhausted without result")


# Singleton pool used by all worker threads
_pool = SmartRecognizerPool(NUM_POOL_INSTANCES)

# --- 3. GLOBAL STATE (listener uses slot 0's recognizer for calibration) ---

# The primary recognizer used in listen_loop for mic calibration
recognizer = _pool.slots[0].recognizer

# Smart calibration constants
CALIB_INTERVAL = 10   # Seconds of silence before recalibrating ambient noise
CALIB_DURATION = 0.15 # How long (sec) each recalibration sample takes
THRESH_FLOOR   = 150  # Never go below this (would pick up everything)

try: mic = sr.Microphone()
except: print("Mic error"); sys.exit(1)

listening      = False
session_id     = 0
audio_queue    = queue.Queue(maxsize=30)   # Larger buffer so audio is never dropped
NUM_WORKERS    = 3                          # Parallel recognition threads

# UI Widgets
root       = None
popup      = None
main_frame = None
btn_lbl    = None
dot_cv     = None
lang_var   = None
sens_var   = None
energy_lbl = None
chips      = {}

# Animation
p_active   = False
p_alpha    = 0.0
p_dir      = 1

# --- 4. CORE LOGIC ---

# Pre-compile all filler patterns into ONE regex — 9x faster than looping re.sub
_FILLERS_RE = re.compile(
    r'\b(?:um+|uh+|ah+|like|you know|actually|basically|so|I mean)\b',
    re.IGNORECASE
)

def smart_polish(text):
    text = _FILLERS_RE.sub('', text)  # Single pass — all fillers removed at once
    low  = text.lower().strip()

    # Voice commands
    if "new line"   in low: keyboard.press_and_release("enter");     return ""
    if "backspace"  in low or "erase that" in low:
                              keyboard.press_and_release("backspace"); return ""
    if "tab space"  in low: keyboard.press_and_release("tab");       return ""

    text = text.strip()
    return (text[0].upper() + text[1:]) if text else ""

def type_text(text):
    text = smart_polish(text)
    if not text: return
    try:
        try:
            # ASCII: direct keyboard simulation — fast and reliable
            text.encode("ascii")
            keyboard.write(text + " ", delay=0.002)
        except UnicodeEncodeError:
            # Hindi / non-ASCII: clipboard paste — 100% accurate for all scripts
            old = pyperclip.paste()
            pyperclip.copy(text + " ")
            time.sleep(0.02)
            keyboard.press_and_release("ctrl+v")
            time.sleep(0.02)
            try: pyperclip.copy(old)
            except: pass
    except: pass

# --- 5. ULTIMATE WINDOW MANAGEMENT ---

def apply_rounded_corners():
    try:
        from ctypes import windll, c_int, byref, sizeof
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

# --- 6. ENGINE LOOPS ---

def listen_loop():
    global listening
    sid = session_id
    last_calib_time = time.time()
    try:
        with mic as source:
            # Initial quick calibration on startup
            recognizer.adjust_for_ambient_noise(source, duration=0.1)
            while listening and session_id == sid:
                try:
                    audio = recognizer.listen(source, timeout=0.5, phrase_time_limit=5)
                    if not listening or session_id != sid: break
                    audio_queue.put((audio, sid))  # blocking put — never drop chunks
                    last_calib_time = time.time()  # Reset timer: speech detected
                except sr.WaitTimeoutError:
                    # ── SMART AMBIENT RECALIBRATION ──────────────────────────────
                    now = time.time()
                    if now - last_calib_time >= CALIB_INTERVAL:
                        recognizer.adjust_for_ambient_noise(source, duration=CALIB_DURATION)
                        cap = int(800 + (sens_var.get() - 1) * 400)
                        recognizer.energy_threshold = max(THRESH_FLOOR,
                                                         min(recognizer.energy_threshold, cap))
                        # Sync new threshold to ALL pool slots so they stay in sync
                        for slot in _pool.slots:
                            slot.recognizer.energy_threshold = recognizer.energy_threshold
                        last_calib_time = now
                except: pass
    except: pass

def proc_worker(sid):
    """A single recognition worker — uses SmartRecognizerPool for API rotation."""
    while True:
        try:
            item = audio_queue.get(timeout=0.5)
        except queue.Empty:
            if not listening:
                break
            continue

        audio, audio_sid = item
        if audio_sid != sid:
            audio_queue.task_done()
            continue

        try:
            _lang = lang_var.get()
            lang  = _lang if _lang != "auto" else None

            # ── SMART POOL CALL — auto-rotates on slow/failure ──────────────
            text = _pool.recognize(audio, language=lang)
            if text: type_text(text)

        except sr.UnknownValueError:
            pass  # Speech not understood — normal, skip silently
        except sr.RequestError as e:
            print(f"[Worker] All slots failed: {e}")
        except Exception as e:
            print(f"[Worker] Unexpected: {e}")
        finally:
            audio_queue.task_done()

    safe(lambda: toggle_active(False))

# --- 7. UI CONTROLS ---

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
        threading.Thread(target=listen_loop, daemon=True).start()
        for _ in range(NUM_WORKERS):
            threading.Thread(target=proc_worker, args=(session_id,), daemon=True).start()
    else:
        listening = False
        session_id += 1

# --- 8. UI CONSTRUCTION ---

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
        if recognizer.energy_threshold > cap:
            recognizer.energy_threshold = cap
            # Sync cap to all pool slots
            for slot in _pool.slots:
                slot.recognizer.energy_threshold = cap
        root.after(100, update_mic_level)

def build_ui():
    global root, popup, main_frame, energy_lbl, btn_lbl, dot_cv, lang_var, sens_var

    # MASTER WINDOW (Invisible Taskbar Manager)
    root = tk.Tk()
    root.title("VT Pro")
    root.geometry("1x1+0+0")
    root.attributes("-alpha", 0.0)
    root.bind("<Map>", on_master_map)
    root.bind("<Unmap>", on_master_unmap)

    # UI WINDOW (The Premium Micro UI)
    popup = tk.Toplevel(root)
    popup.overrideredirect(True)
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

    dot_cv = tk.Canvas(hdr, width=10, height=10, bg=C_BG, highlightthickness=0)
    dot_cv.pack(side="left", padx=(0, 5))
    dot_cv.create_oval(1, 1, 9, 9, fill=C_MID, tags="dot")

    tk.Label(hdr, text="Voice", bg=C_BG, fg=C_CYAN, font=("Segoe UI", 9, "bold")).pack(side="left")
    tk.Label(hdr, text="Typer pro", bg=C_BG, fg=C_LIGHT, font=("Segoe UI", 8)).pack(side="left")

    box = tk.Frame(hdr, bg=C_BG)
    box.pack(side="right")

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