import threading
import json
import queue
import tkinter as tk
from tkinter import ttk, messagebox
import ttkbootstrap as tb
import pyaudio
import ctypes
import time
import numpy as np
from vosk import KaldiRecognizer

KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_KEYUP = 0x0002

VK_CODES = {
    'backspace': 0x08, 'tab': 0x09, 'enter': 0x0D, 'shift': 0x10, 'ctrl': 0x11, 'alt': 0x12,
    'capslock': 0x14, 'esc': 0x1B, 'space': 0x20, 'pageup': 0x21, 'pagedown': 0x22,
    'end': 0x23, 'home': 0x24, 'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28,
    'printscreen': 0x2C, 'insert': 0x2D, 'delete': 0x2E,
    'win': 0x5B, 'apps': 0x5D,
}
for i in range(1, 25):
    VK_CODES[f'f{i}'] = 0x70 + i - 1
for c in '0123456789':
    VK_CODES[c] = ord(c)
for c in 'abcdefghijklmnopqrstuvwxyz':
    VK_CODES[c] = ord(c.upper())

def get_vk_code(key):
    key_lower = key.lower()
    if key_lower in VK_CODES:
        return VK_CODES[key_lower]
    if len(key) == 1 and key.isalnum():
        return ord(key.upper())
    raise ValueError(f"Неизвестная клавиша: {key}")

def send_hotkey(combo):
    keys = combo.lower().split('+')
    if not keys:
        return
    main_key = keys[-1]
    modifiers = keys[:-1]
    user32 = ctypes.windll.user32
    for mod in modifiers:
        vk = get_vk_code(mod)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYDOWN, 0)
        time.sleep(0.01)
    vk_main = get_vk_code(main_key)
    user32.keybd_event(vk_main, 0, KEYEVENTF_KEYDOWN, 0)
    time.sleep(0.02)
    user32.keybd_event(vk_main, 0, KEYEVENTF_KEYUP, 0)
    for mod in reversed(modifiers):
        vk = get_vk_code(mod)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.01)

def resample(data, old_rate, new_rate):
    duration = len(data) / old_rate
    new_len = int(duration * new_rate)
    old_indices = np.linspace(0, len(data)-1, new_len)
    new_data = np.interp(old_indices, np.arange(len(data)), data)
    return new_data.astype(np.int16)

class HotkeyCommandsManager:
    def __init__(self, parent):
        self.parent = parent
        self.commands = parent.settings.get("hotkey_commands", {})
        self._recording = False
        self._virtual_keys = []
        self._settings_win = None

    def get_commands(self):
        return self.commands

    def record_combination(self, entry_widget, parent_win):
        if self._recording:
            return
        self._recording = True
        entry_widget.config(state="normal")
        entry_widget.delete(0, tk.END)
        entry_widget.insert(0, "Используйте виртуальную клавиатуру...")
        entry_widget.config(state="readonly")
        self._start_virtual_keyboard(entry_widget, parent_win)

    def _start_virtual_keyboard(self, entry_widget, parent_win):
        self._virtual_keys = []
        kb_win = tb.Toplevel(parent_win)
        kb_win.title("Виртуальная клавиатура")
        kb_win.geometry("1000x500")
        kb_win.resizable(False, False)
        kb_win.transient(parent_win)
        kb_win.grab_set()

        def on_close():
            self._recording = False
            kb_win.destroy()
        kb_win.protocol("WM_DELETE_WINDOW", on_close)

        display_var = tk.StringVar(value="")
        display_entry = tb.Entry(kb_win, textvariable=display_var, state="readonly", font=("Segoe UI", 12))
        display_entry.pack(pady=10, padx=10, fill=tk.X)

        main_frame = tb.Frame(kb_win)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        rows = [
            ['F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12'],
            ['Esc', '1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '-', '=', 'Backspace'],
            ['Tab', 'q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p', '[', ']', '\\'],
            ['Caps', 'a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', ';', "'", 'Enter'],
            ['Shift', 'z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.', '/', 'Shift'],
            ['Ctrl', 'Win', 'Alt', 'Space', 'Alt', 'Win', 'Ctrl'],
            ['Up', 'Down', 'Left', 'Right', 'Home', 'End', 'PageUp', 'PageDown', 'Insert', 'Delete']
        ]

        key_map = {
            'Space': 'space', 'Enter': 'enter', 'Tab': 'tab', 'Backspace': 'backspace', 
            'Caps': 'caps lock', 'Shift': 'shift', 'Ctrl': 'ctrl', 'Alt': 'alt', 'Win': 'win', 
            'Up': 'up', 'Down': 'down', 'Left': 'left', 'Right': 'right', 
            'Home': 'home', 'End': 'end', 'PageUp': 'page up', 'PageDown': 'page down', 
            'Insert': 'insert', 'Delete': 'delete', 'Esc': 'esc',
            'PrtSc': 'print screen', 'ScrollLock': 'scroll lock', 'Pause': 'pause',
            'F1': 'f1', 'F2': 'f2', 'F3': 'f3', 'F4': 'f4', 'F5': 'f5', 'F6': 'f6',
            'F7': 'f7', 'F8': 'f8', 'F9': 'f9', 'F10': 'f10', 'F11': 'f11', 'F12': 'f12',
            '1': '1', '2': '2', '3': '3', '4': '4', '5': '5', 
            '6': '6', '7': '7', '8': '8', '9': '9', '0': '0', '-': '-', '=': '=',
            'q': 'q', 'w': 'w', 'e': 'e', 'r': 'r', 't': 't', 'y': 'y', 'u': 'u', 'i': 'i', 'o': 'o', 'p': 'p',
            'a': 'a', 's': 's', 'd': 'd', 'f': 'f', 'g': 'g', 'h': 'h', 'j': 'j', 'k': 'k', 'l': 'l',
            'z': 'z', 'x': 'x', 'c': 'c', 'v': 'v', 'b': 'b', 'n': 'n', 'm': 'm',
            '[': '[', ']': ']', '\\': '\\',
            ';': ';', "'": "'",
            ',': ',', '.': '.', '/': '/'
        }

        for i in range(1, 13):
            key_map[f'F{i}'] = f'f{i}'

        def add_key(key):
            normalized = key_map.get(key, key.lower())
            self._virtual_keys.append(normalized)
            display_var.set('+'.join(self._virtual_keys))

        def clear_keys():
            self._virtual_keys.clear()
            display_var.set('')

        def confirm():
            if not self._virtual_keys:
                messagebox.showwarning("Ошибка", "Не выбрана ни одна клавиша", parent=kb_win)
                return
            combo = '+'.join(self._virtual_keys)
            self._recording = False
            entry_widget.config(state="normal")
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, combo)
            entry_widget.config(state="readonly")
            kb_win.destroy()

        def cancel():
            self._recording = False
            kb_win.destroy()

        for row in rows:
            row_frame = tb.Frame(main_frame)
            row_frame.pack(pady=2, fill=tk.X)
            cols = len(row)
            for c_idx, key in enumerate(row):
                width = 6
                if key in ['Backspace', 'Enter', 'Shift', 'Caps']:
                    width = 8
                elif key == 'Space':
                    width = 30
                btn = tb.Button(row_frame, text=key, width=width, command=lambda k=key: add_key(k))
                btn.grid(row=0, column=c_idx, padx=1, sticky='ew')
            for c_idx in range(cols):
                row_frame.columnconfigure(c_idx, weight=1)

        ctrl_frame = tb.Frame(main_frame)
        ctrl_frame.pack(pady=10)
        tb.Button(ctrl_frame, text="Очистить", bootstyle="warning", command=clear_keys).pack(side=tk.LEFT, padx=5)
        tb.Button(ctrl_frame, text="Подтвердить", bootstyle="success", command=confirm).pack(side=tk.LEFT, padx=5)
        tb.Button(ctrl_frame, text="Отмена", bootstyle="secondary", command=cancel).pack(side=tk.LEFT, padx=5)

    def _record_phrase_vosk(self, entry_widget, parent_win):
        def listen():
            try:
                p = pyaudio.PyAudio()
                dev_info = p.get_default_input_device_info()
                channels = min(dev_info['maxInputChannels'], 1)
                rate = int(dev_info['defaultSampleRate'])
                model = self.parent.shared_model
                if model is None:
                    parent_win.after(0, lambda: messagebox.showerror("Ошибка", "Модель Vosk не загружена", parent=parent_win))
                    return
                recognizer = KaldiRecognizer(model, 16000)
                recognizer.SetWords(True)

                stream = p.open(format=pyaudio.paInt16,
                                channels=channels,
                                rate=rate,
                                input=True,
                                frames_per_buffer=1024)
                stream.start_stream()

                parent_win.after(0, lambda: messagebox.showinfo("Запись", "Говорите фразу...", parent=parent_win))

                frames = []
                for _ in range(int(rate / 1024 * 4)):
                    data = stream.read(1024, exception_on_overflow=False)
                    frames.append(data)
                stream.stop_stream()
                stream.close()
                p.terminate()

                audio_data = b''.join(frames)
                audio = np.frombuffer(audio_data, dtype=np.int16)
                if channels > 1:
                    audio = audio.reshape(-1, channels).mean(axis=1).astype(np.int16)
                if rate != 16000:
                    audio = resample(audio, rate, 16000)
                if recognizer.AcceptWaveform(audio.tobytes()):
                    res = json.loads(recognizer.Result())
                    text = res.get("text", "").strip()
                else:
                    res = json.loads(recognizer.PartialResult())
                    text = res.get("partial", "").strip()
                if text:
                    parent_win.after(0, lambda: entry_widget.delete(0, tk.END))
                    parent_win.after(0, lambda: entry_widget.insert(0, text))
                else:
                    parent_win.after(0, lambda: messagebox.showwarning("Ошибка", "Не удалось распознать речь", parent=parent_win))
            except Exception as e:
                parent_win.after(0, lambda: messagebox.showerror("Ошибка", f"Ошибка записи: {e}", parent=parent_win))
        threading.Thread(target=listen, daemon=True).start()

    def show_settings_window(self):
        if self._settings_win is not None and self._settings_win.winfo_exists():
            self._settings_win.lift()
            self._settings_win.focus_force()
            return
        win = tb.Toplevel(self.parent)
        win.title("Голосовые комбинации клавиш")
        win.geometry("600x550")
        win.resizable(False, False)
        win.transient(self.parent)
        win.grab_set()
        self._settings_win = win

        def on_close():
            self._settings_win = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", on_close)

        frame = tb.Frame(win, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        tb.Label(frame, text="Фраза для активации:").pack(anchor=tk.W, pady=(0,5))
        phrase_frame = tb.Frame(frame)
        phrase_frame.pack(fill=tk.X, pady=2)
        phrase_entry = tb.Entry(phrase_frame)
        phrase_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))

        mic_btn = tb.Button(phrase_frame, text="🎤", width=3,
                            command=lambda: self._record_phrase_vosk(phrase_entry, win))
        mic_btn.pack(side=tk.RIGHT)

        tb.Label(frame, text="Комбинация клавиш:").pack(anchor=tk.W, pady=(10,0))
        hotkey_frame = tb.Frame(frame)
        hotkey_frame.pack(fill=tk.X, pady=2)
        hotkey_entry = tb.Entry(hotkey_frame, state="readonly")
        hotkey_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        btn_virtual = tb.Button(hotkey_frame, text="⌨️ Вирт. клав.", bootstyle="outline-secondary",
                                command=lambda: self.record_combination(hotkey_entry, win))
        btn_virtual.pack(side=tk.LEFT, padx=2)

        listbox_keys = []
        list_frame = tb.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        listbox = tk.Listbox(list_frame, font=("Courier New", 10))
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = tb.Scrollbar(list_frame, orient=tk.VERTICAL, command=listbox.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.configure(yscrollcommand=scroll.set)

        def refresh():
            listbox.delete(0, tk.END)
            listbox_keys.clear()
            for phrase, combo in self.commands.items():
                listbox_keys.append(phrase)
                listbox.insert(tk.END, f"🗣 {phrase:<22} ➔  ⌨️ {combo}")

        def add():
            phrase = phrase_entry.get().strip().lower()
            combo = hotkey_entry.get()
            if not phrase or not combo or combo == "Используйте виртуальную клавиатуру...":
                messagebox.showwarning("Ошибка", "Заполните фразу и комбинацию", parent=win)
                return
            self.commands[phrase] = combo
            self.parent.settings["hotkey_commands"] = self.commands
            self.parent.save_settings()
            refresh()
            phrase_entry.delete(0, tk.END)
            hotkey_entry.config(state="normal")
            hotkey_entry.delete(0, tk.END)
            hotkey_entry.config(state="readonly")

        def delete():
            sel = listbox.curselection()
            if sel:
                index = sel[0]
                phrase = listbox_keys[index]
                if phrase in self.commands:
                    del self.commands[phrase]
                    self.parent.settings["hotkey_commands"] = self.commands
                    self.parent.save_settings()
                    refresh()
            else:
                messagebox.showwarning("Внимание", "Выберите комбинацию для удаления", parent=win)

        btn_add = tb.Button(frame, text="Добавить комбинацию", bootstyle="success", command=add)
        btn_add.pack(fill=tk.X, pady=3)
        btn_del = tb.Button(frame, text="Удалить выбранное", bootstyle="danger", command=delete)
        btn_del.pack(fill=tk.X, pady=3)

        refresh()