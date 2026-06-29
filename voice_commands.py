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

class VoiceCommandsManager:
    def __init__(self, parent):
        self.parent = parent
        self.commands = parent.settings.get("voice_commands", {})
        self.listening = False
        self.use_wake_word = False
        self.WAKE_WORD = "компьютер"
        self.audio_queue = queue.Queue()
        self.audio_stream = None
        self.p = None
        self.recognizer = None
        self._settings_win = None
        self._migrate_old_commands()

    def _migrate_old_commands(self):
        migrated = False
        for phrase, value in list(self.commands.items()):
            if isinstance(value, str):
                self.commands[phrase] = {"type": "builtin", "value": value}
                migrated = True
        if migrated:
            self.parent.settings["voice_commands"] = self.commands
            self.parent.save_settings()

    def start_listening(self):
        if self.listening:
            return
        if self.parent.shared_model is None:
            self.parent.after(1000, self.start_listening)
            return
        self.listening = True
        threading.Thread(target=self._listen, daemon=True).start()
        print("[voice_commands] Слушатель голосовых команд запущен (Vosk)")

    def stop_listening(self):
        self.listening = False
        if self.audio_stream:
            try:
                self.audio_stream.stop_stream()
                self.audio_stream.close()
            except:
                pass
        if self.p:
            try:
                self.p.terminate()
            except:
                pass
        self.p = None
        self.audio_stream = None

    def _resample(self, data, input_rate, output_rate=16000):
        if input_rate == output_rate:
            return data
        duration = len(data) / input_rate
        old_indices = np.linspace(0, len(data) - 1, int(duration * output_rate))
        new_data = np.interp(old_indices, np.arange(len(data)), data)
        return new_data.astype(np.int16)

    def _listen(self):
        try:
            self.p = pyaudio.PyAudio()
            dev_index = self.parent.selected_voice_device  # или другое поле с индексом
            if dev_index == -1:
                dev_info = self.p.get_default_input_device_info()
            else:
                dev_info = self.p.get_device_info_by_index(dev_index)
            print(f"[voice_commands] Устройство ввода: {dev_info['name']}")
            channels = min(dev_info['maxInputChannels'], 1)
            rate = int(dev_info['defaultSampleRate'])
            print(f"[voice_commands] Частота: {rate}, каналов: {channels}")

            self.recognizer = KaldiRecognizer(self.parent.shared_model, 16000)
            self.recognizer.SetWords(True)

            self.audio_stream = self.p.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                input=True,
                frames_per_buffer=1024,
                stream_callback=self._audio_callback
            )
            self.audio_stream.start_stream()
            print("[voice_commands] Аудиопоток запущен")
        except Exception as e:
            print(f"[voice_commands] Ошибка инициализации аудио: {e}")
            self.listening = False
            return

        while self.listening:
            try:
                data = self.audio_queue.get(timeout=0.5)
                audio = np.frombuffer(data, dtype=np.int16)
                if channels > 1:
                    audio = audio.reshape(-1, channels).mean(axis=1).astype(np.int16)
                if rate != 16000:
                    audio = self._resample(audio, rate, 16000)
                if self.recognizer.AcceptWaveform(audio.tobytes()):
                    res = json.loads(self.recognizer.Result())
                    text = res.get("text", "").strip()
                    if text:
                        print(f"[voice_commands] Распознано: {text}")
                        self._process_text(text)
                else:
                    partial = json.loads(self.recognizer.PartialResult())
                    part = partial.get("partial", "").strip()
                    if part:
                        print(f"[voice_commands] Частично: {part}")
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[voice_commands] Ошибка в цикле: {e}")
        self.stop_listening()

    def _audio_callback(self, in_data, frame_count, time_info, status):
        if self.listening:
            self.audio_queue.put(in_data)
        return (None, pyaudio.paContinue)

    def _process_text(self, text):
        text = text.lower().strip()
        print(f"[voice_commands] Обработка: {text}")

        if self.use_wake_word:
            if not text.startswith(self.WAKE_WORD):
                return
            text = text[len(self.WAKE_WORD):].strip()
            if not text:
                return

        matched_action = None
        max_len = 0

        for phrase, data in self.commands.items():
            if phrase in text and len(phrase) > max_len:
                max_len = len(phrase)
                if data["type"] == "builtin":
                    matched_action = lambda d=data: self._execute_builtin(d["value"])
                elif data["type"] == "script":
                    script_name = data["value"]
                    if script_name in self.parent.script_launcher.buttons:
                        matched_action = lambda s=script_name: self.parent.script_launcher.run_script(s)

        for phrase, combo in self.parent.hotkey_cmd.get_commands().items():
            if phrase in text and len(phrase) > max_len:
                max_len = len(phrase)
                matched_action = lambda c=combo: send_hotkey(c)

        if matched_action:
            print(f"[voice_commands] Выполняется действие")
            matched_action()
        else:
            print("[voice_commands] Нет совпадения для команд")

    def _execute_builtin(self, action):
        if action == "Включить субтитры":
            self.parent.subtitles_var.set(True)
            self.parent.start_subtitles()
        elif action == "Выключить субтитры":
            self.parent.subtitles_var.set(False)
            self.parent.stop_subtitles()
        elif action == "Включить голосовой ввод":
            self.parent.voice_typing_var.set(True)
            self.parent.start_voice_typing()
        elif action == "Выключить голосовой ввод":
            self.parent.voice_typing_var.set(False)
            self.parent.stop_voice_typing()
        elif action == "Включить трекинг головы":
            self.parent.head_control_var.set(True)
            self.parent.start_head_tracking()
        elif action == "Выключить трекинг головы":
            self.parent.head_control_var.set(False)
            self.parent.stop_head_tracking()
        elif action == "Включить цветокоррекцию":
            self.parent.color_correction_var.set(True)
            self.parent.start_color_correction()
        elif action == "Выключить цветокоррекцию":
            self.parent.color_correction_var.set(False)
            self.parent.stop_color_correction()
        elif action == "Открыть профиль":
            self.parent.show_profile()
        elif action == "Выйти из аккаунта":
            self.parent.logout()
        elif action == "Открыть настройки программы":
            self.parent.open_program_settings()
        elif action == "Открыть настройки субтитров":
            self.parent.open_subtitle_settings()
        elif action == "Открыть настройки голосового ввода":
            self.parent.open_voice_settings()
        elif action == "Открыть настройки трекинга головы":
            self.parent.open_head_settings()
        elif action == "Открыть настройки цветокоррекции":
            self.parent.open_color_correction_settings()
        elif action == "Открыть боковое меню":
            self.parent.open_menu()
        elif action == "Закрыть боковое меню":
            self.parent.close_menu()
        elif action == "Открыть инструкцию":
            self.parent.open_instructions_window()
        elif action == "Управление голосовыми командами":
            self.show_settings_window()
        elif action == "Управление комбинациями клавиш":
            self.parent.hotkey_cmd.show_settings_window()
        elif action == "Управление кнопками запуска":
            self.parent.script_launcher.show_settings_window()

    def show_settings_window(self):
        if self._settings_win is not None and self._settings_win.winfo_exists():
            self._settings_win.lift()
            self._settings_win.focus_force()
            return
        win = tb.Toplevel(self.parent)
        win.title("Голосовые команды")
        win.geometry("550x650")
        win.resizable(False, False)
        win.transient(self.parent)
        win.grab_set()
        self._settings_win = win

        def on_close():
            self._settings_win = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", on_close)

        builtin_actions = [
            "Включить субтитры", "Выключить субтитры", "Включить голосовой ввод", "Выключить голосовой ввод",
            "Включить трекинг головы", "Выключить трекинг головы", "Включить цветокоррекцию", "Выключить цветокоррекцию",
            "Открыть профиль", "Выйти из аккаунта", "Открыть настройки программы", "Открыть настройки субтитров",
            "Открыть настройки голосового ввода", "Открыть настройки трекинга головы", "Открыть настройки цветокоррекции",
            "Открыть боковое меню", "Закрыть боковое меню", "Открыть инструкцию", "Управление голосовыми командами",
            "Управление комбинациями клавиш", "Управление кнопками запуска"
        ]

        frame = tb.Frame(win, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        settings_lf = tb.LabelFrame(frame, text=" Параметры фильтрации ")
        settings_lf.pack(fill=tk.X, pady=(0, 10), padx=5, ipady=5, ipadx=5)

        wake_var = tk.BooleanVar(value=self.use_wake_word)
        def toggle_wake(): self.use_wake_word = wake_var.get()
        wake_chk = tb.Checkbutton(settings_lf, text="Использовать активационное слово ('компьютер')",
                                  variable=wake_var, command=toggle_wake)
        wake_chk.pack(anchor=tk.W, pady=5, padx=5)

        tb.Label(frame, text="Фраза для распознавания:").pack(anchor=tk.W, pady=(0,5))
        phrase_frame = tb.Frame(frame)
        phrase_frame.pack(fill=tk.X, pady=2)
        phrase_entry = tb.Entry(phrase_frame)
        phrase_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))

        def voice_input_phrase():
            if self.parent.shared_model is None:
                messagebox.showerror("Ошибка", "Модель Vosk не загружена!")
                return

            def listen():
                p = pyaudio.PyAudio()
                stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000,
                                input=True, frames_per_buffer=8192)
                rec = KaldiRecognizer(self.parent.shared_model, 16000)

                self.parent.after(0, lambda: messagebox.showinfo("Запись", "Произнесите команду"))

                frames = []
                for _ in range(0, int(16000 / 8192 * 5)):
                    data = stream.read(8192, exception_on_overflow=False)
                    if rec.AcceptWaveform(data):
                        break

                result_json = rec.Result()
                text = json.loads(result_json).get("text", "")

                self.parent.after(0, lambda: phrase_entry.delete(0, tk.END))
                self.parent.after(0, lambda: phrase_entry.insert(0, text))

                stream.stop_stream()
                stream.close()
                p.terminate()

            threading.Thread(target=listen, daemon=True).start()

        mic_btn = tb.Button(phrase_frame, text="🎤", width=3, command=voice_input_phrase)
        mic_btn.pack(side=tk.RIGHT)

        tb.Label(frame, text="Выберите действие:").pack(anchor=tk.W, pady=(10,0))
        def get_actions():
            buttons = list(self.parent.script_launcher.buttons.keys())
            return builtin_actions + buttons

        action_combo = ttk.Combobox(frame, values=get_actions(), state="readonly")
        action_combo.pack(fill=tk.X, pady=5)

        listbox_keys = []
        listbox_frame = tb.Frame(frame)
        listbox_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        listbox = tk.Listbox(listbox_frame, font=("Courier New", 10))
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = tb.Scrollbar(listbox_frame, orient=tk.VERTICAL, command=listbox.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.configure(yscrollcommand=scroll.set)

        def refresh():
            listbox.delete(0, tk.END)
            listbox_keys.clear()
            for phrase, data in self.commands.items():
                listbox_keys.append(phrase)
                if data["type"] == "builtin":
                    listbox.insert(tk.END, f"🗣 {phrase:<22} ➔  ⚙️ {data['value']}")
                else:
                    listbox.insert(tk.END, f"🗣 {phrase:<22} ➔  📜 [Сценарий] {data['value']}")

        def add():
            phrase = phrase_entry.get().strip().lower()
            action = action_combo.get()
            if not phrase or not action:
                messagebox.showwarning("Ошибка", "Заполните оба поля", parent=win)
                return
            if action in builtin_actions:
                self.commands[phrase] = {"type": "builtin", "value": action}
            else:
                self.commands[phrase] = {"type": "script", "value": action}
            self.parent.settings["voice_commands"] = self.commands
            self.parent.save_settings()
            refresh()
            phrase_entry.delete(0, tk.END)
            action_combo.set('')

        def delete():
            sel = listbox.curselection()
            if sel:
                index = sel[0]
                phrase = listbox_keys[index]
                if phrase in self.commands:
                    del self.commands[phrase]
                    self.parent.settings["voice_commands"] = self.commands
                    self.parent.save_settings()
                    refresh()
            else:
                messagebox.showwarning("Внимание", "Выберите команду для удаления", parent=win)

        btn_add = tb.Button(frame, text="Добавить команду", bootstyle="success", command=add)
        btn_add.pack(fill=tk.X, pady=3)
        btn_del = tb.Button(frame, text="Удалить выбранное", bootstyle="danger", command=delete)
        btn_del.pack(fill=tk.X, pady=3)

        refresh()