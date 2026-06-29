import tkinter as tk
from tkinter import ttk, messagebox
import ttkbootstrap as tb
import json
import os
import threading
import sys
import urllib.request
import zipfile
import shutil
import time
import winreg
import copy
from PIL import Image
from pygrabber.dshow_graph import FilterGraph
from head_tracking import HeadTracker
from subtitles import SubtitlesEngine
from voice_input import VoiceInputEngine
from color_correction import ColorCorrectionOverlay
from vosk import Model
import pyaudiowpatch as pa
from tkinter import font as tkfont
import pystray
from pystray import MenuItem as item
from voice_commands import VoiceCommandsManager
from hotkey_commands import HotkeyCommandsManager
from script_launcher import ScriptLauncherManager

class AssistiveSuite(tb.Window):
    def __init__(self):
        self.settings_file = "settings.json"
        self.settings = self.load_settings()

        super().__init__(themename="darkly")
        self.title("Инклюзивный ассистент")
        self.geometry("800x700")
        self.minsize(800, 700)

        self.color_correction_var = tk.BooleanVar(value=False)
        self.subtitles_var = tk.BooleanVar(value=False)
        self.voice_typing_var = tk.BooleanVar(value=False)
        self.head_control_var = tk.BooleanVar(value=False)

        self.menu_open = False
        self.menu_on_hover_var = tk.BooleanVar(value=self.settings["app"].get("menu_on_hover", True))
        self.menu_on_hover_var.trace_add('write', self.save_menu_on_hover)

        self.menu_frame = None
        self.hover_detector = None
        self.menu_canvas = None
        self.menu_scrollbar = None
        self.menu_inner = None

        self.engine = None
        self.overlay_sub = None
        self.subtitle_alpha = 0.8
        self.selected_device_index = None
        self.model_loaded = False
        self.model_loading = False
        self.font_family = "Segoe UI"
        self.font_size = 14
        self.subtitle_history = []
        self.subtitles_active = False
        self.partial_text = ""

        self.voice_engine = None
        self.voice_active = False
        self.voice_paused = False
        self.selected_voice_device = self.settings.get("voice_input", {}).get("device_index", -1)
        self.voice_level = 0
        self.shared_model = None
        self.voice_engine = VoiceInputEngine(self)

        self.color_correction_type = "protanomaly"
        self.color_intensity = 0.7
        self.color_gain = 0.7
        self.color_correction_overlay = ColorCorrectionOverlay(
            correction_type=self.color_correction_type,
            intensity=self.color_intensity,
            gain=self.color_gain
        )

        self.head_tracker = None
        self.head_invert_x = True
        self.head_swap_eyes = True
        self.head_ear_threshold = 0.21
        self.head_click_duration = 0.2
        self.head_long_press_duration = 0.8
        self.head_sensitivity_x = 10.0
        self.head_sensitivity_y = 12.0
        self.head_precision_ms = 100
        self.head_camera_index = 1
        self.head_reset_blinks = 2
        self.head_reset_time = 2.0
        self.last_blink_time_l = 0
        self.is_held_l = False
        self.blink_count_l = 0
        self.last_single_blink_time_l = 0
        self.blink_counter_l = 0
        self.blink_counter_r = 0

        self.voice_cmd = VoiceCommandsManager(self)
        self.hotkey_cmd = HotkeyCommandsManager(self)
        self.script_launcher = ScriptLauncherManager(self)

        self.start_with_windows_var = tk.BooleanVar(value=False)
        self.minimize_to_tray_var = tk.BooleanVar(value=False)

        self.last_subtitle_toggle_time = 0
        self.status_frame = tb.Frame(self, height=30)
        self.status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_label_main = tb.Label(self.status_frame, text="Загрузка модели...", font=("Segoe UI", 9))
        self.status_label_main.pack(side=tk.LEFT, padx=10)
        self.progressbar_main = ttk.Progressbar(self.status_frame, mode='indeterminate', length=150)
        self.progressbar_main.pack(side=tk.RIGHT, padx=10)

        self.main_container = tb.Frame(self)
        self.main_container.pack(fill=tk.BOTH, expand=True)

        self.content_frame = tb.Frame(self.main_container)
        self.content_frame.pack(fill=tk.BOTH, expand=True, padx=(70, 20), pady=(15, 20))

        self.btn_show_menu = tk.Button(
            self.main_container, text="<", font=("Segoe UI", 16),
            bg="#2d2d2d", fg="white", relief="flat", bd=0,
            command=self.toggle_menu
        )
        self.btn_show_menu.place(x=5, rely=0.5, anchor="w", width=30, height=60)

        self.create_function_cards()
        self.create_side_menu()
        self.create_hover_detector()
        self.bind_hover_events()
        self.disable_switches_until_model_loaded()
        self.color_correction_overlay.start()

        self.start_model_loading()
        self.apply_settings()

        self.voice_cmd.start_listening()

    def load_settings(self):
        default = {
            "app": {"theme": "darkly", "menu_on_hover": True},
            "subtitles": {
                "alpha": 0.8, 
                "font_family": "Segoe UI", 
                "font_size": 14, 
                "device_index": None,
                "buffer_size": 512,
                "queue_timeout": 0.05,
                "vosk_timeout": 0.4
            },
            "voice_input": {"device_index": 0},
            "head_tracking": {
                "camera_index": 1, "sensitivity_x": 10.0, "sensitivity_y": 12.0,
                "invert_x": True, "swap_eyes": True, "precision_interval_ms": 100,
                "reset_blinks": 2, "reset_time": 2.0
            },
            "color_correction": {"type": "deuteranomaly", "intensity": 0.7, "gain": 0.7},
            "voice_commands": {},
            "hotkey_commands": {},
            "script_buttons": {},
            "minimize_to_tray": False,
            "start_with_windows": False
        }
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                def update_dict(d, u):
                    for k, v in u.items():
                        if isinstance(v, dict):
                            d[k] = update_dict(d.get(k, {}), v)
                        else:
                            d[k] = v
                    return d
                update_dict(default, loaded)
                return default
            except Exception as e:
                return default
        else:
            self.save_settings(default)
            return default

    def save_menu_on_hover(self, *args):
        self.settings["app"]["menu_on_hover"] = self.menu_on_hover_var.get()
        self.save_settings()

    def save_settings(self, settings=None):
        if settings is None:
            settings = self.settings
        try:
            # 1. Локальная запись в файл (как и было)
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4, ensure_ascii=False)
            
            # 2. ИДЕАЛЬНОЕ МЕСТО: Автоматическая отправка на сервер
            self.send_settings_to_server()
            
        except Exception as e:
            pass

    def apply_settings(self):
        s = self.settings
        theme = s["app"]["theme"]
        if self.style.theme.name != theme:
            self.style.theme_use(theme)
        self.subtitle_alpha = s["subtitles"]["alpha"]
        self.sub_buffer_size = s["subtitles"].get("buffer_size", 512)
        self.sub_queue_timeout = s["subtitles"].get("queue_timeout", 0.05)
        self.sub_vosk_timeout = s["subtitles"].get("vosk_timeout", 0.4)

        self.font_family = s["subtitles"]["font_family"]
        self.font_size = s["subtitles"]["font_size"]
        self.selected_device_index = s["subtitles"]["device_index"]
        self.selected_voice_device = s["voice_input"]["device_index"]
        ht = s["head_tracking"]
        self.head_camera_index = ht["camera_index"]
        self.head_sensitivity_x = ht["sensitivity_x"]
        self.head_sensitivity_y = ht["sensitivity_y"]
        self.head_invert_x = ht["invert_x"]
        self.head_swap_eyes = ht["swap_eyes"]
        self.head_precision_ms = ht["precision_interval_ms"]
        self.head_reset_blinks = ht["reset_blinks"]
        self.head_reset_time = ht["reset_time"]
        cc = s["color_correction"]
        self.color_correction_type = cc["type"]
        self.color_intensity = cc["intensity"]
        self.color_gain = cc["gain"]
        self.minimize_to_tray_var.set(s.get("minimize_to_tray", False))
        self.start_with_windows_var.set(s.get("start_with_windows", False))
        if hasattr(self, 'color_correction_overlay'):
            self.color_correction_overlay.set_correction_type(self.color_correction_type)
            self.color_correction_overlay.set_intensity(self.color_intensity)
            self.color_correction_overlay.set_gain(self.color_gain)

    def get_screen_adaptive_size(self, width_ratio=0.4, height_ratio=0.5, min_width=500, min_height=400):
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        width = max(min_width, int(screen_width * width_ratio))
        height = max(min_height, int(screen_height * height_ratio))
        return width, height

    # def update_auth_display(self):
    #     for widget in self.auth_frame.winfo_children():
    #         widget.destroy()
    #     if self.is_authenticated and self.current_user:
    #         nickname = self.current_user.get('NickName', 'Пользователь')
    #         btn_nick = tb.Button(self.auth_frame, text=nickname, bootstyle="light-outline", width=12,
    #                              command=self.show_user_menu)
    #         btn_nick.pack(side=tk.RIGHT)
    #     else:
    #         btn_login = tb.Button(self.auth_frame, text="🔐 Вход", bootstyle="primary", width=12,
    #                               command=self.login)
    #         btn_login.pack(side=tk.RIGHT, padx=(5, 5))
    #         btn_register = tb.Button(self.auth_frame, text="📝 Регистрация", bootstyle="primary", width=14,
    #                                  command=self.register)
    #         btn_register.pack(side=tk.RIGHT, padx=(0, 5))

    def show_user_menu(self):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="👤 Профиль", command=self.show_profile)
        menu.add_separator()
        menu.add_command(label="🚪 Выйти", command=self.logout)
        try:
            for child in self.auth_frame.winfo_children():
                if isinstance(child, tb.Button) and child.cget('text') == self.current_user.get('NickName', ''):
                    x = child.winfo_rootx()
                    y = child.winfo_rooty() + child.winfo_height()
                    menu.post(x, y)
                    return
            menu.post(self.winfo_pointerx(), self.winfo_pointery())
        except:
            menu.post(self.winfo_pointerx(), self.winfo_pointery())

    def show_profile(self):
        if not self.current_user:
            return
        if hasattr(self, '_profile_win') and self._profile_win is not None and self._profile_win.winfo_exists():
            self._profile_win.lift()
            self._profile_win.focus_force()
            return
        prof_win = tb.Toplevel(self)
        prof_win.title("Профиль пользователя")
        w, h = self.get_screen_adaptive_size(0.35, 0.4, min_width=450, min_height=400)
        prof_win.geometry(f"{w}x{h}")
        prof_win.minsize(450, 400)
        prof_win.resizable(True, True)
        prof_win.transient(self)
        prof_win.grab_set()
        self._profile_win = prof_win

        # центрирование окна
        x = self.winfo_x() + (self.winfo_width() // 2) - (w // 2)
        y = self.winfo_y() + (self.winfo_height() // 2) - (h // 2)
        prof_win.geometry(f"+{x}+{y}")

        main_frame = tb.Frame(prof_win, padding=25)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tb.Label(main_frame, text="Редактирование профиля", font=("Segoe UI", 16, "bold")).pack(pady=(0, 20))

        tb.Label(main_frame, text="Имя пользователя", anchor=tk.W).pack(fill=tk.X, pady=(0, 5))
        nick_var = tk.StringVar(value=self.current_user['NickName'])
        entry_nick = tb.Entry(main_frame, textvariable=nick_var, font=("Segoe UI", 10))
        entry_nick.pack(fill=tk.X, pady=(0, 15))

        tb.Label(main_frame, text="Электронная почта", anchor=tk.W).pack(fill=tk.X, pady=(0, 5))
        lbl_email = tb.Label(main_frame, text=self.current_user['email'], font=("Segoe UI", 10), anchor=tk.W)
        lbl_email.pack(fill=tk.X, pady=(0, 15))

        def change_password():
            pwd_win = tb.Toplevel(prof_win)
            pwd_win.title("Смена пароля")
            pwd_win.geometry("400x370")
            pwd_win.resizable(True, True)
            pwd_win.minsize(400, 370)
            pwd_win.transient(prof_win)
            pwd_win.grab_set()
            frame = tb.Frame(pwd_win, padding=20)
            frame.pack(fill=tk.BOTH, expand=True)
            tb.Label(frame, text="Смена пароля", font=("Segoe UI", 14, "bold")).pack(pady=(0, 15))
            tb.Label(frame, text="Текущий пароль", anchor=tk.W).pack(fill=tk.X)
            old_pass = tb.Entry(frame, show="*")
            old_pass.pack(fill=tk.X, pady=(0, 10))
            tb.Label(frame, text="Новый пароль", anchor=tk.W).pack(fill=tk.X)
            new_pass = tb.Entry(frame, show="*")
            new_pass.pack(fill=tk.X, pady=(0, 10))
            tb.Label(frame, text="Подтверждение", anchor=tk.W).pack(fill=tk.X)
            confirm_pass = tb.Entry(frame, show="*")
            confirm_pass.pack(fill=tk.X, pady=(0, 15))

    def start_model_loading(self):
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))

        model_root = os.path.join(base_dir, "model")
        model_path = os.path.join(model_root, "vosk_russian_model")
        os.makedirs(model_root, exist_ok=True)

        def is_model_valid(path):
            if not os.path.exists(path):
                return False
            am_path = os.path.join(path, "am")
            if not os.path.exists(am_path):
                return False
            final_mdl = os.path.join(am_path, "final.mdl")
            if not os.path.exists(final_mdl) or os.path.getsize(final_mdl) < 1000:
                return False
            return True

        def download_and_extract():
            if not self.is_internet_available():
                self.after(0, lambda: self.status_label_main.config(text="Нет интернета. Модель не скачана."))
                self.after(0, lambda: self.progressbar_main.stop())
                return False

            model_url = "https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip"
            zip_path = os.path.join(model_root, "vosk-model-ru-0.42.zip")
            try:
                if os.path.exists(model_path):
                    shutil.rmtree(model_path)
                if os.path.exists(zip_path):
                    os.remove(zip_path)

                self.after(0, lambda: self.status_label_main.config(text="Скачивание модели (45 МБ)..."))
                self.after(0, lambda: self.progressbar_main.start())

                def report(block, block_size, total):
                    if total > 0:
                        percent = int(block * block_size * 100 / total)
                        self.after(0, lambda: self.status_label_main.config(text=f"Скачивание: {percent}%"))

                urllib.request.urlretrieve(model_url, zip_path, report)

                self.after(0, lambda: self.status_label_main.config(text="Распаковка модели..."))
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(model_root)

                extracted = os.path.join(model_root, "vosk-model-ru-0.42")
                if os.path.exists(extracted) and extracted != model_path:
                    os.rename(extracted, model_path)

                os.remove(zip_path)
                return True
            except Exception as e:
                return False

        def load():
            if not is_model_valid(model_path):
                if not download_and_extract():
                    self.after(0, lambda: self.status_label_main.config(text="Ошибка загрузки модели"))
                    self.after(0, lambda: self.progressbar_main.stop())
                    return
            try:
                self.shared_model = Model(model_path)
                self.model_loaded = True
                self.model_loading = False
                self.after(0, self.enable_switches)
                self.after(0, lambda: self.status_label_main.config(text="Model ready"))
                self.after(0, lambda: self.progressbar_main.stop())
                self.after(0, lambda: self.progressbar_main.config(mode='determinate', value=100))
                self.after(0, lambda: self.voice_cmd.start_listening()) 
            except Exception as e:
                self.model_loaded = False
                self.model_loading = False
                self.after(0, lambda: self.status_label_main.config(text=f"Ошибка модели: {str(e)[:50]}"))
                self.after(0, lambda: self.progressbar_main.stop())

        threading.Thread(target=load, daemon=True).start()

    def enable_switches(self):
        for child in self.content_frame.winfo_children():
            for subchild in child.winfo_children():
                if isinstance(subchild, tb.Checkbutton):
                    parent = subchild.master
                    if parent.winfo_children():
                        text = parent.winfo_children()[0].cget("text")
                        if text in ("Субтитры из звука", "Голосовой ввод текста", "Коррекция цвета для экрана"):
                            subchild.configure(state="normal")

    def disable_switches_until_model_loaded(self):
        for child in self.content_frame.winfo_children():
            for subchild in child.winfo_children():
                if isinstance(subchild, tb.Checkbutton):
                    parent = subchild.master
                    if parent.winfo_children():
                        text = parent.winfo_children()[0].cget("text")
                        if text in ("Субтитры из звука", "Голосовой ввод текста", "Коррекция цвета для экрана"):
                            subchild.configure(state="disabled")

    def create_function_cards(self):
        functions = [
            ("Управление мышью при помощи головы", "Перемещение курсора поворотом головы", self.head_control_var),
            ("Коррекция цвета для экрана", "Адаптация цветов для дальтоников", self.color_correction_var),
            ("Субтитры из звука", "Преобразование речи в текст в реальном времени", self.subtitles_var),
            ("Голосовой ввод текста", "Голос -> текст в активное поле", self.voice_typing_var)
        ]
        for title, desc, var in functions:
            card = tb.Frame(self.content_frame)
            if desc == "Перемещение курсора поворотом головы":
                card.pack(fill=tk.X, pady=(75, 15))
            else:
                card.pack(fill=tk.X, pady=15)
            top_line = tb.Frame(card)
            top_line.pack(fill=tk.X)
            lbl_title = tb.Label(top_line, text=title, font=("Segoe UI", 14, "bold"))
            lbl_title.pack(side=tk.LEFT)
            right_box = tb.Frame(top_line)
            right_box.pack(side=tk.RIGHT)
            btn_settings = tb.Button(right_box, text="⚙️", bootstyle="outline-secondary",
                                     command=lambda t=title: self.open_feature_settings(t))
            btn_settings.pack(side=tk.LEFT, padx=(0, 15))
            switch = tb.Checkbutton(right_box, variable=var, bootstyle="primary-round-toggle",
                                    command=lambda t=title: self.on_switch_toggle(t))
            switch.pack(side=tk.LEFT)
            lbl_desc = tb.Label(card, text=desc, font=("Segoe UI", 10), foreground="gray")
            lbl_desc.pack(anchor=tk.W, pady=(2, 0))

    def on_switch_toggle(self, func_name):
        if func_name == "Субтитры из звука":
            if self.model_loading:
                messagebox.showwarning("Загрузка модели", "Модель ещё загружается.")
                self.subtitles_var.set(False)
                return
            if not self.model_loaded:
                messagebox.showerror("Ошибка", "Модель не загружена.")
                self.subtitles_var.set(False)
                return

            current_time = time.time()
            if current_time - self.last_subtitle_toggle_time < 0.6:
                self.subtitles_var.set(not self.subtitles_var.get())
                return
            self.last_subtitle_toggle_time = current_time

            if self.subtitles_var.get():
                self.start_subtitles()
            else:
                self.stop_subtitles()
        elif func_name == "Голосовой ввод текста":
            if self.model_loading:
                messagebox.showwarning("Загрузка модели", "Модель ещё загружается.")
                self.voice_typing_var.set(False)
                return
            if not self.model_loaded:
                messagebox.showerror("Ошибка", "Модель не загружена.")
                self.voice_typing_var.set(False)
                return
            if self.voice_typing_var.get():
                self.start_voice_typing()
            else:
                self.stop_voice_typing()
        elif func_name == "Коррекция цвета для экрана":
            if self.color_correction_var.get():
                self.start_color_correction()
            else:
                self.stop_color_correction()
        elif func_name == "Управление мышью при помощи головы":
            if self.head_control_var.get():
                self.start_head_tracking()
            else:
                self.stop_head_tracking()

    def start_subtitles(self):
        if self.subtitles_active:
            return
        if self.selected_device_index is None:
            messagebox.showwarning("Нет устройства", "Сначала выберите устройство захвата в настройках (⚙️).")
            self.subtitles_var.set(False)
            self.open_feature_settings("Субтитры из звука")
            return
        
        self.overlay_sub = tk.Toplevel(self)
        self.overlay_sub.title("")
        self.overlay_sub.geometry("800x200+100+100")
        self.overlay_sub.overrideredirect(True)
        self.overlay_sub.attributes("-topmost", True)
        self.overlay_sub.attributes("-alpha", self.subtitle_alpha)
        self.overlay_sub.configure(bg="black")
    
        top_bar = tk.Frame(self.overlay_sub, bg="#333", height=28)
        top_bar.pack(fill=tk.X)
    
        fullscreen_btn = tk.Button(top_bar, text="⛶", font=("Segoe UI", 10), bg="#333", fg="white", relief="flat",
                                   command=self.toggle_fullscreen)
        fullscreen_btn.pack(side=tk.LEFT, padx=5)
    
        drag_label = tk.Label(top_bar, text="     СУБТИТРЫ (перетащите)     ", bg="#333", fg="white", font=("Segoe UI", 9))
        drag_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
    
        close_btn = tk.Button(top_bar, text="✕", font=("Segoe UI", 10), bg="#333", fg="white", relief="flat",
                              command=self.stop_subtitles)
        close_btn.pack(side=tk.RIGHT, padx=5)
    
        drag_label.bind("<Button-1>", self.start_move)
        drag_label.bind("<B1-Motion>", self.on_move)
    
        self.text_widget = tk.Text(self.overlay_sub, wrap=tk.WORD, font=(self.font_family, self.font_size),
                                   bg="black", fg="white", bd=0, highlightthickness=0)
        self.text_widget.tag_configure("center", justify="center")
        self.text_widget.pack(fill=tk.BOTH, expand=True, padx=15, pady=0)
        self.overlay_sub.text_widget = self.text_widget
    
        self.subtitle_history.clear()
        self.partial_text = ""
        self.text_widget.insert(tk.END, "Ожидание аудио...")
        self.text_widget.tag_add("center", "1.0", "end")
    
        self.subtitles_active = True
        self.subtitles_var.set(True) 
        self.overlay_fullscreen = False
        self.overlay_normal_geometry = None
    
        threading.Thread(target=self._run_subtitle_engine, daemon=True).start()

    def _run_subtitle_engine(self):
        try:
            if self.engine is not None:
                try:
                    self.engine.stop()
                except:
                    pass
                
            self.engine = SubtitlesEngine(
                model=self.shared_model,
                callback=self.update_subtitle_text,
                error_callback=lambda msg: self.after(0, lambda: self._on_subtitle_error(msg))
            )
        
            if not self.engine.load_model():
                raise Exception("Не удалось инициаризировать распознаватель")
    
            dev_idx = self.selected_device_index if (self.selected_device_index is not None and self.selected_device_index >= 0) else None
    
            if not self.engine.set_device(dev_idx):
                raise Exception("Не удалось настроить аудиоустройство. Проверьте индекс в настройках.")
        
            if not self.engine.start():
                raise Exception("Не удалось запустить захват звука")
        
        except Exception as e:
            error_message = str(e)
            self.subtitles_var.set(False)
            self.subtitles_active = False
            self.after(0, lambda: self._on_subtitle_error(error_message))

    def stop_subtitles(self):
        """Метод для полного и безопасного выключения субтитров"""
        self.subtitles_active = False
        self.subtitles_var.set(False)
        
        if self.engine:
            try:
                self.engine.stop()
            except Exception as e:
                pass
        if hasattr(self, 'overlay_sub') and self.overlay_sub:
            try:
                if self.overlay_sub.winfo_exists():
                    self.overlay_sub.destroy()
            except Exception as e:
                pass
            self.overlay_sub = None

    def _on_subtitle_error(self, err_msg):
        """Обработчик ошибок, вынесенный на правильный уровень отступов"""
        if self.overlay_sub and self.overlay_sub.winfo_exists():
            self.overlay_sub.destroy()
        self.overlay_sub = None
        self.subtitles_active = False
        self.subtitles_var.set(False)
        messagebox.showerror("Ошибка субтитров", err_msg)

    def update_subtitle_text(self, text, is_partial=False):
        if not self.subtitles_active or not self.overlay_sub:
            return
        try:
            widget = self.overlay_sub.text_widget
            if not widget.winfo_exists():
                return
                
            cleaned = text.strip() if text else ""
            widget.delete(1.0, tk.END)
            
            widget.tag_config("center", justify="center")
            widget.tag_config("fixed", foreground="#ffffff")  
            widget.tag_config("partial", foreground="#aaaaaa") 
            
            if cleaned:
               
                words = cleaned.split()
                formatted_lines = []
                current_line = []
                
                for word in words:
                    current_line.append(word)
                    if len(current_line) >= 11: 
                        formatted_lines.append(" ".join(current_line))
                        current_line = []
                if current_line:
                    formatted_lines.append(" ".join(current_line))
                
               
                widget_height = widget.winfo_height()
                if widget_height <= 10:
                    widget_height = 150 
                
                current_font = tkfont.Font(font=widget['font'])
                line_height = current_font.metrics("linespace") + 2
                
               
                max_visible_lines = max(2, int(widget_height / line_height) - 1)
                
               
                if len(formatted_lines) > max_visible_lines:
                    formatted_lines = formatted_lines[-max_visible_lines:]
                
               
                for i, line in enumerate(formatted_lines):
                    is_last_line = (i == len(formatted_lines) - 1)
                    prefix = "\n" if i > 0 else ""
                    
                    if is_last_line and is_partial:
                        widget.insert(tk.END, prefix + line, ("center", "partial"))
                    else:
                        widget.insert(tk.END, prefix + line, ("center", "fixed"))
            else:
                widget.insert(tk.END, "Ожидание аудио...", "center")
                
        except Exception as e:
            pass

    def _get_display_text(self, include_partial=False):
        history_text = "\n".join(self.subtitle_history[-3:])
        if include_partial and self.partial_text:
            return history_text + ("" if not history_text else "\n") + self.partial_text
        return history_text

    def _update_text_widget(self, text, is_partial):
        widget = self.overlay_sub.text_widget
        widget.delete(1.0, tk.END)
        widget.insert(tk.END, text if text else "Ожидание аудио...")
        widget.tag_add("center", "1.0", "end")
        if is_partial and self.partial_text:
            widget.tag_add("partial", "1.0", "end")
            widget.tag_config("partial", foreground="#aaaaaa")
        else:
            widget.tag_remove("partial", "1.0", "end")

    def toggle_fullscreen(self):
        if not hasattr(self, 'overlay_fullscreen'):
            self.overlay_fullscreen = False
            self.overlay_normal_geometry = None
        if not self.overlay_fullscreen:
            self.overlay_normal_geometry = self.overlay_sub.geometry()
            w = self.overlay_sub.winfo_screenwidth()
            h = self.overlay_sub.winfo_screenheight()
            self.overlay_sub.geometry(f"{w}x{h}+0+0")
            self.overlay_fullscreen = True
        else:
            self.overlay_sub.geometry(self.overlay_normal_geometry)
            self.overlay_fullscreen = False

    def start_move(self, event):
        self._drag_x = event.x_root - self.overlay_sub.winfo_x()
        self._drag_y = event.y_root - self.overlay_sub.winfo_y()

    def on_move(self, event):
        if hasattr(self, 'overlay_fullscreen') and not self.overlay_fullscreen:
            x = event.x_root - self._drag_x
            y = event.y_root - self._drag_y
            self.overlay_sub.geometry(f"+{x}+{y}")

    def show_voice_control_panel(self):
        if hasattr(self, 'voice_win') and self.voice_win is not None and self.voice_win.winfo_exists():
            self.voice_win.lift()
            self.voice_win.focus_force()
            return
        self.voice_win = tb.Toplevel(self)
        self.voice_win.title("Голосовой ввод")
        self.voice_win.geometry("400x230")
        self.voice_win.attributes("-topmost", True)
        container = tb.Frame(self.voice_win, padding=25)
        container.pack(fill=tk.BOTH, expand=True)
        btn_frame = tb.Frame(container)
        btn_frame.pack(pady=10)
        tb.Button(btn_frame, text="▶", bootstyle="success", width=5,
                  command=lambda: setattr(self.voice_engine, 'is_paused', False)).pack(side=tk.LEFT, padx=2)
        tb.Button(btn_frame, text="⏸", bootstyle="warning", width=5,
                  command=lambda: setattr(self.voice_engine, 'is_paused', True)).pack(side=tk.LEFT, padx=2)
        tb.Button(btn_frame, text="⏹", bootstyle="danger", width=5,
                  command=self.stop_voice_typing).pack(side=tk.LEFT, padx=2)
        self.m_progress = tb.Progressbar(container, bootstyle="info", maximum=100, mode='determinate')
        self.m_progress.pack(fill=tk.X, pady=(5, 10))
        if hasattr(self, 'voice_engine') and self.voice_engine:
            self.voice_engine.level_callback = self.update_voice_level
        self.voice_win.protocol("WM_DELETE_WINDOW", lambda: setattr(self, 'voice_win', None))

    def start_voice_typing(self):
        if not self.model_loaded:
            messagebox.showwarning("Модель не загружена", "Подождите загрузки речевой модели.")
            self.voice_typing_var.set(False)
            return
        if not hasattr(self, 'selected_voice_device') or self.selected_voice_device is None:
            self.selected_voice_device = -1
        elif isinstance(self.selected_voice_device, str):
            try:
                self.selected_voice_device = int(self.selected_voice_device)
            except:
                self.selected_voice_device = -1
        self.voice_engine.model = self.shared_model
        self.voice_engine.set_device(self.selected_voice_device)
        if self.voice_engine.start():
            self.voice_active = True
            self.show_voice_control_panel()
        else:
            messagebox.showerror("Ошибка", "Не удалось запустить захват звука. Проверьте настройки микрофона.")
            self.voice_typing_var.set(False)

    def stop_voice_typing(self):
        if self.voice_engine:
            self.voice_engine.stop()
        self.voice_active = False
        if hasattr(self, 'voice_win') and self.voice_win is not None and self.voice_win.winfo_exists():
            self.voice_win.destroy()
            self.voice_win = None
        self.voice_typing_var.set(False)

    def update_voice_level(self, level):
        if hasattr(self, 'm_progress') and self.m_progress.winfo_exists():
            self.m_progress['value'] = level

    def stop_color_correction(self):
        if self.color_correction_overlay:
            self.color_correction_overlay.stop()

    def start_color_correction(self):
        if self.color_correction_overlay:
            self.color_correction_overlay.start()

    def start_head_tracking(self):
        if self.head_tracker is None:
            self.head_tracker = HeadTracker(
                camera_source=self.head_camera_index,
                sensitivity_x=self.head_sensitivity_x,
                sensitivity_y=self.head_sensitivity_y,
                invert_x=self.head_invert_x,
                swap_eyes=self.head_swap_eyes,
                precision_interval_ms=self.head_precision_ms
            )
        self.head_tracker.start()

    def stop_head_tracking(self):
        if self.head_tracker:
            self.head_tracker.stop()

    def open_feature_settings(self, feature_name):
        if feature_name == "Субтитры из звука":
            self.open_subtitle_settings()
        elif feature_name == "Голосовой ввод текста":
            self.open_voice_settings()
        elif feature_name == "Коррекция цвета для экрана":
            self.open_color_correction_settings()
        elif feature_name == "Управление мышью при помощи головы":
            self.open_head_settings()

    def open_head_settings(self):
        if hasattr(self, '_head_win') and self._head_win is not None and self._head_win.winfo_exists():
            self._head_win.lift()
            self._head_win.focus_force()
            return
        win = tb.Toplevel(title="Настройки управления головой")
        w, h = self.get_screen_adaptive_size(0.5, 0.75, min_width=600, min_height=550)
        win.geometry(f"{w}x{h}")
        win.minsize(600, 550)
        win.resizable(True, True)
        self._head_win = win

        container = tb.Frame(win, padding=20)
        container.pack(fill=tk.BOTH, expand=True)

        tb.Label(container, text="Настройки управления", font=("Segoe UI", 14, "bold")).pack(pady=(0, 20))

        current_sx = self.head_sensitivity_x
        current_sy = self.head_sensitivity_y
        current_ms = self.head_precision_ms
        current_inv = self.head_invert_x
        current_swap = self.head_swap_eyes
        current_cam = self.head_camera_index

        tb.Label(container, text="Выберите камеру:", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        graph = FilterGraph()
        device_names = graph.get_input_devices()
        cam_list = [f"{i}: {name}" for i, name in enumerate(device_names)]
        cam_var = tk.StringVar()
        cam_combo = ttk.Combobox(container, textvariable=cam_var, values=cam_list, state="readonly")
        cam_combo.pack(fill=tk.X, pady=(5, 15))
        if cam_list:
            cam_combo.set(cam_list[current_cam] if current_cam < len(cam_list) else cam_list[0])

        tb.Label(container, text="Чувствительность мыши:", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        frame_x = tb.Frame(container)
        frame_x.pack(fill=tk.X, pady=5)
        tb.Label(frame_x, text="По горизонтали (X):", width=20).pack(side=tk.LEFT)
        sx_var = tk.DoubleVar(value=current_sx)
        tb.Scale(frame_x, from_=1.0, to=30.0, variable=sx_var, orient=tk.HORIZONTAL).pack(side=tk.LEFT, fill=tk.X, expand=True)

        frame_y = tb.Frame(container)
        frame_y.pack(fill=tk.X, pady=5)
        tb.Label(frame_y, text="По вертикали (Y):", width=20).pack(side=tk.LEFT)
        sy_var = tk.DoubleVar(value=current_sy)
        tb.Scale(frame_y, from_=1.0, to=30.0, variable=sy_var, orient=tk.HORIZONTAL).pack(side=tk.LEFT, fill=tk.X, expand=True)

        inv_x_var = tk.BooleanVar(value=current_inv)
        tb.Checkbutton(container, text="Отзеркалить движения по горизонтали (Инверсия X)",
                       variable=inv_x_var, bootstyle="primary-round-toggle").pack(anchor=tk.W, pady=15)

        swap_eyes_var = tk.BooleanVar(value=current_swap)
        tb.Checkbutton(container, text="Инверсия кнопок глаз (Левый <-> Правый)",
                       variable=swap_eyes_var, bootstyle="primary-round-toggle").pack(anchor=tk.W, pady=15)

        tb.Label(container, text="Сброс центра (калибровка):", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(10, 0))
        reset_frame = tb.Frame(container)
        reset_frame.pack(fill=tk.X, pady=5)
        tb.Label(reset_frame, text="Кол-во морганий:").pack(side=tk.LEFT)
        blink_count_var = tk.IntVar(value=self.head_reset_blinks)
        tb.Entry(reset_frame, textvariable=blink_count_var, width=5).pack(side=tk.LEFT, padx=5)
        tb.Label(reset_frame, text="За время (сек):").pack(side=tk.LEFT, padx=(15, 0))
        blink_time_var = tk.DoubleVar(value=self.head_reset_time)
        tb.Entry(reset_frame, textvariable=blink_time_var, width=5).pack(side=tk.LEFT, padx=5)

        tb.Label(container, text="Интервал точного перемещения (мс):", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        ms_frame = tb.Frame(container)
        ms_frame.pack(fill=tk.X, pady=5)
        ms_var = tk.IntVar(value=current_ms)
        tb.Entry(ms_frame, textvariable=ms_var, width=10).pack(side=tk.LEFT)
        tb.Label(ms_frame, text=" мс (время перемещения на 1 пиксель)").pack(side=tk.LEFT, padx=10)

        def apply():
            try:
                selected_cam_text = cam_var.get()
                new_cam_idx = int(selected_cam_text.split(":")[0]) if selected_cam_text else 0
                self.head_sensitivity_x = sx_var.get()
                self.head_sensitivity_y = sy_var.get()
                self.head_invert_x = inv_x_var.get()
                self.head_swap_eyes = swap_eyes_var.get()
                self.head_precision_ms = int(ms_var.get())
                self.head_camera_index = new_cam_idx
                self.head_reset_blinks = int(blink_count_var.get())
                self.head_reset_time = float(blink_time_var.get())
                self.settings["head_tracking"].update({
                    "camera_index": self.head_camera_index,
                    "sensitivity_x": self.head_sensitivity_x,
                    "sensitivity_y": self.head_sensitivity_y,
                    "invert_x": self.head_invert_x,
                    "swap_eyes": self.head_swap_eyes,
                    "precision_interval_ms": self.head_precision_ms,
                    "reset_blinks": self.head_reset_blinks,
                    "reset_time": self.head_reset_time
                })
                self.save_settings()
                settings = {
                    'cam': self.head_camera_index,
                    'sx': self.head_sensitivity_x,
                    'sy': self.head_sensitivity_y,
                    'inv_x': self.head_invert_x,
                    'swap': self.head_swap_eyes,
                    'ms': self.head_precision_ms,
                    'reset_blinks': self.head_reset_blinks,
                    'reset_time': self.head_reset_time
                }
                if self.head_tracker:
                    if self.head_tracker.camera_source != new_cam_idx:
                        self.head_tracker.stop()
                        self.head_tracker.camera_source = new_cam_idx
                        self.head_tracker.update_settings(settings)
                        if self.head_control_var.get():
                            self.head_tracker.start()
                    else:
                        self.head_tracker.update_settings(settings)
                win.destroy()
                self._head_win = None
                messagebox.showinfo("Успех", "Настройки головы сохранены")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

        tb.Button(container, text="Применить настройки", bootstyle="success", command=apply).pack(pady=15, fill=tk.X)
        win.protocol("WM_DELETE_WINDOW", lambda: setattr(self, '_head_win', None) or win.destroy())

    def open_subtitle_settings(self):
        if hasattr(self, '_subtitle_win') and self._subtitle_win is not None and self._subtitle_win.winfo_exists():
            self._subtitle_win.lift()
            self._subtitle_win.focus_force()
            return

        win = tb.Toplevel(title="Настройки субтитров")
        w, h = self.get_screen_adaptive_size(0.55, 0.65, min_width=600, min_height=480)
        win.geometry(f"{w}x{h}")
        win.minsize(600, 480)
        win.resizable(True, True)
        self._subtitle_win = win

        container = tb.Frame(win, padding=20)
        container.pack(fill=tk.BOTH, expand=True)

        tb.Label(container, text="Настройка субтитров", font=("Segoe UI", 14, "bold")).pack(pady=15)

        dev_frame = tb.Frame(container)
        dev_frame.pack(fill=tk.X, padx=20, pady=8)
        tb.Label(dev_frame, text="Устройство захвата (loopback):").pack(side=tk.LEFT, padx=(0, 10))
        tmp = SubtitlesEngine(self.shared_model)
        devices = tmp.get_loopback_devices()
        device_names = [f"{idx}: {name}" for idx, name in devices]
        device_combo = ttk.Combobox(dev_frame, values=device_names, state="readonly")
        device_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        if self.selected_device_index is not None:
            for idx, name in devices:
                if idx == self.selected_device_index:
                    device_combo.set(f"{idx}: {name}")
                    break
        if not device_combo.get() and devices:
            device_combo.set(device_names[0] if device_names else "")

        alpha_frame = tb.Frame(container)
        alpha_frame.pack(fill=tk.X, padx=20, pady=8)
        tb.Label(alpha_frame, text="Прозрачность окна:").pack(side=tk.LEFT, padx=(0, 10))
        alpha_slider = tb.Scale(alpha_frame, from_=0.2, to=1.0, value=self.subtitle_alpha, orient=tk.HORIZONTAL, length=200)
        alpha_slider.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
        alpha_label = tb.Label(alpha_frame, text=f"{int(self.subtitle_alpha * 100)}%")
        alpha_label.pack(side=tk.LEFT)

        def update_alpha(val):
            self.subtitle_alpha = float(val)
            alpha_label.config(text=f"{int(self.subtitle_alpha * 100)}%")
            if self.overlay_sub and self.overlay_sub.winfo_exists():
                self.overlay_sub.attributes("-alpha", self.subtitle_alpha)
            self.settings["subtitles"]["alpha"] = self.subtitle_alpha
            self.save_settings()
        alpha_slider.configure(command=update_alpha)

        font_frame = tb.Frame(container)
        font_frame.pack(fill=tk.X, padx=20, pady=8)
        tb.Label(font_frame, text="Шрифт:").pack(side=tk.LEFT, padx=(0, 10))
        font_combo = ttk.Combobox(font_frame, values=["Segoe UI", "Arial", "Times New Roman", "Courier New"], state="readonly")
        font_combo.set(self.font_family)
        font_combo.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        tb.Label(font_frame, text="Размер:").pack(side=tk.LEFT, padx=(10, 5))
        size_slider = tb.Scale(font_frame, from_=10, to=30, value=self.font_size, orient=tk.HORIZONTAL, length=100)
        size_slider.pack(side=tk.LEFT, padx=5)
        size_label = tb.Label(font_frame, text=f"{self.font_size}px")
        size_label.pack(side=tk.LEFT)

        def update_font(*args):
            self.font_family = font_combo.get()
            self.font_size = int(size_slider.get())
            size_label.config(text=f"{self.font_size}px")
            if self.overlay_sub and self.overlay_sub.winfo_exists():
                self.overlay_sub.text_widget.configure(font=(self.font_family, self.font_size))
            self.settings["subtitles"]["font_family"] = self.font_family
            self.settings["subtitles"]["font_size"] = self.font_size
            self.save_settings()
        font_combo.bind("<<ComboboxSelected>>", update_font)
        size_slider.configure(command=lambda v: update_font())

        tb.Separator(container).pack(pady=10, padx=20, fill=tk.X)

        advanced_frame = tb.LabelFrame(container, text="🚀 Продвинутые настройки скорости отклика")
        advanced_frame.pack(fill=tk.X, padx=20, pady=10)

        buffer_frame = tb.Frame(advanced_frame)
        buffer_frame.pack(fill=tk.X, pady=8, padx=10)
        tb.Label(buffer_frame, text="Размер аудио-буфера (кадры):").pack(side=tk.LEFT, padx=(0, 10))
        buffer_combo = ttk.Combobox(buffer_frame, values=["256", "512", "1024", "2048"], state="readonly", width=10)
        buffer_combo.set(str(self.sub_buffer_size))
        buffer_combo.pack(side=tk.LEFT)
        def on_buffer_change(event):
            self.sub_buffer_size = int(buffer_combo.get())
            self.settings["subtitles"]["buffer_size"] = self.sub_buffer_size
            self.save_settings()
        buffer_combo.bind("<<ComboboxSelected>>", on_buffer_change)

        active_tip = [None]

        def show_tip(widget, text_content):
            if active_tip[0] is not None:
                return
            x = widget.winfo_rootx() + 20
            y = widget.winfo_rooty() + widget.winfo_height() + 5
            tip_window = tk.Toplevel(widget)
            tip_window.wm_overrideredirect(True)
            tip_window.wm_geometry(f"+{x}+{y}")
            tip_window.attributes("-topmost", True)
            lbl = tk.Label(tip_window, text=text_content, justify=tk.LEFT,
                           background="#222222", foreground="#ffffff",
                           relief=tk.SOLID, borderwidth=1,
                           font=("Segoe UI", 9), padx=6, pady=4)
            lbl.pack()
            active_tip[0] = tip_window

        def hide_tip(event=None):
            if active_tip[0]:
                active_tip[0].destroy()
                active_tip[0] = None

        q_frame = tb.Frame(advanced_frame)
        q_frame.pack(fill=tk.X, pady=8, padx=10)
        q_help = tb.Label(q_frame, text="❓", font=("Segoe UI", 10, "bold"), bootstyle="info", cursor="hand2")
        q_help.pack(side=tk.LEFT, padx=(0, 8))
        q_text = ("Чем МЕНЬШЕ это значение, тем быстрее фоновый поток забирает\n"
                  "звук из системы и отправляет его. Маленькие значения\n"
                  "делают появление букв мгновенным, но нагружают процессор.")
        q_help.bind("<Enter>", lambda e, w=q_help, t=q_text: show_tip(w, t))
        q_help.bind("<Leave>", hide_tip)
        tb.Label(q_frame, text="Частота опроса очереди (сек):").pack(side=tk.LEFT, padx=(0, 10))
        q_slider = tb.Scale(q_frame, from_=0.01, to=0.30, value=self.sub_queue_timeout, orient=tk.HORIZONTAL, length=180)
        q_slider.pack(side=tk.LEFT, fill=tk.X, expand=True)
        q_label = tb.Label(q_frame, text=f"{self.sub_queue_timeout:.2f} с")
        q_label.pack(side=tk.LEFT)

        def update_queue_timeout(val):
            self.sub_queue_timeout = float(val)
            q_label.config(text=f"{self.sub_queue_timeout:.2f} с")
            self.settings["subtitles"]["queue_timeout"] = self.sub_queue_timeout
            self.save_settings()
        q_slider.configure(command=update_queue_timeout)

        v_frame = tb.Frame(advanced_frame)
        v_frame.pack(fill=tk.X, pady=8, padx=10)
        v_help = tb.Label(v_frame, text="❓", font=("Segoe UI", 10, "bold"), bootstyle="info", cursor="hand2")
        v_help.pack(side=tk.LEFT, padx=(0, 8))
        v_text = ("Время ожидания паузы между предложениями. Как только звук прекращается\n"
                  "на указанное время, приложение зафиксирует фразу, сделает её белой\n"
                  "и перенесет на строку выше. Рекомендуется ставить 0.3 - 0.5 сек.")
        v_help.bind("<Enter>", lambda e, w=v_help, t=v_text: show_tip(w, t))
        v_help.bind("<Leave>", hide_tip)
        tb.Label(v_frame, text="Пауза финализации фразы (сек):").pack(side=tk.LEFT, padx=(0, 10))
        v_slider = tb.Scale(v_frame, from_=0.1, to=1.5, value=self.sub_vosk_timeout, orient=tk.HORIZONTAL, length=180)
        v_slider.pack(side=tk.LEFT, fill=tk.X, expand=True)
        v_label = tb.Label(v_frame, text=f"{self.sub_vosk_timeout:.1f} с")
        v_label.pack(side=tk.LEFT)

        def update_vosk_timeout(val):
            self.sub_vosk_timeout = float(val)
            v_label.config(text=f"{self.sub_vosk_timeout:.1f} с")
            self.settings["subtitles"]["vosk_timeout"] = self.sub_vosk_timeout
            self.save_settings()
        v_slider.configure(command=update_vosk_timeout)

        def save():
            sel = device_combo.get()
            if sel:
                self.selected_device_index = int(sel.split(":")[0])
            self.settings["subtitles"]["device_index"] = self.selected_device_index
            self.save_settings()
            if self.subtitles_active:
                self.stop_subtitles()
                self.start_subtitles()
            hide_tip()
            win.destroy()
            self._subtitle_win = None

        tb.Button(container, text="Сохранить настройки", bootstyle="success", command=save).pack(pady=20, fill=tk.X)
        win.protocol("WM_DELETE_WINDOW", lambda: hide_tip() or setattr(self, '_subtitle_win', None) or win.destroy())

    def open_voice_settings(self):
        if hasattr(self, '_voice_settings_win') and self._voice_settings_win is not None and self._voice_settings_win.winfo_exists():
            self._voice_settings_win.lift()
            self._voice_settings_win.focus_force()
            return
        win = tb.Toplevel(title="Настройки голосового ввода")
        w, h = self.get_screen_adaptive_size(0.4, 0.35, min_width=450, min_height=280)
        win.geometry(f"{w}x{h}")
        win.minsize(450, 280)
        win.resizable(True, True)
        win.transient(self)
        win.grab_set()
        self._voice_settings_win = win

        frame_voice = tb.Frame(win, padding=20)
        frame_voice.pack(fill=tk.BOTH, expand=True)

        tb.Label(frame_voice, text="Выберите микрофон для ввода текста:", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(0, 5))

        devices = []
        seen_names = set()
        try:
            p_temp = pa.PyAudio()
            for i in range(p_temp.get_device_count()):
                try:
                    dev_info = p_temp.get_device_info_by_index(i)
                    if dev_info.get('maxInputChannels', 0) > 0:
                        name = dev_info.get('name', f"Микрофон {i}").strip()
                        if isinstance(name, bytes):
                            name = name.decode('utf-8', errors='ignore')
                        ignore_keywords = ["динамик", "наушник", "speaker", "headphone", "loopback", "output"]
                        should_ignore = any(keyword in name.lower() for keyword in ignore_keywords)
                        if name not in seen_names and not should_ignore:
                            seen_names.add(name)
                            devices.append((i, name))
                except:
                    continue
            p_temp.terminate()
        except Exception as e:
            pass

        device_list = ["-1: Системное устройство (По умолчанию)"] + [f"{i}: {name}" for i, name in devices]
        device_combo = ttk.Combobox(frame_voice, values=device_list, state="readonly")
        device_combo.pack(fill=tk.X, pady=(0, 15))

        current_dev = self.settings.get("voice_input", {}).get("device_index", -1)
        target_value = next((item for item in device_list if item.startswith(f"{current_dev}:")), None)
        if not target_value:
            if current_dev == -1:
                target_value = "-1: Системное устройство (По умолчанию)"
            else:
                target_value = f"{current_dev}: Настроенное устройство записи"
        device_combo.set(target_value)

        def save_voice_config():
            if not win.winfo_exists():
                return
            selected = device_combo.get()
            if selected:
                try:
                    idx = int(selected.split(":")[0])
                    if "voice_input" not in self.settings:
                        self.settings["voice_input"] = {}
                    self.settings["voice_input"]["device_index"] = idx
                    self.selected_voice_device = idx
                    if hasattr(self, 'voice_engine') and self.voice_engine:
                        self.voice_engine.set_device(idx)
                    self.save_settings()
                    messagebox.showinfo("Успех", "Настройки микрофона успешно сохранены.", parent=win)
                    win.destroy()
                    self._voice_settings_win = None
                except Exception as e:
                    messagebox.showerror("Ошибка", f"Не удалось сохранить настройки: {e}", parent=win)
            else:
                win.destroy()
                self._voice_settings_win = None

        def internal_open_replacements():
            if hasattr(self, '_repl_win') and self._repl_win is not None and self._repl_win.winfo_exists():
                self._repl_win.lift()
                self._repl_win.focus_force()
                return
            win_repl = tb.Toplevel(win)
            win_repl.title("Настройка голосовых замен")
            w2, h2 = self.get_screen_adaptive_size(0.5, 0.6, min_width=600, min_height=550)
            win_repl.geometry(f"{w2}x{h2}")
            win_repl.minsize(600, 550)
            win_repl.resizable(True, True)
            win_repl.transient(win)
            win_repl.grab_set()
            self._repl_win = win_repl

            if "voice_replacements" not in self.settings:
                self.settings["voice_replacements"] = {
                    "знак запятая": ",",
                    "знак точка": ".",
                    "знак вопрос": "?",
                    "знак восклицания": "!"
                }
            replacements = self.settings["voice_replacements"]

            frame_repl = tb.Frame(win_repl, padding=15)
            frame_repl.pack(fill=tk.BOTH, expand=True)

            tb.Label(frame_repl, text="Добавить новую замену:", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, pady=(0,10))
            tb.Label(frame_repl, text="Что говорить (голосовая команда):").pack(anchor=tk.W)
            cmd_frame = tb.Frame(frame_repl)
            cmd_frame.pack(fill=tk.X, pady=(2, 10))
            entry_cmd = tb.Entry(cmd_frame)
            entry_cmd.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

            def record_phrase():
                if self.shared_model is None:
                    messagebox.showerror("Ошибка", "Модель Vosk не загружена!")
                    return

                def listen():
                    import pyaudio
                    import json
                    from vosk import KaldiRecognizer 

                    p = pyaudio.PyAudio()
                    try:
                        stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000,
                                        input=True, frames_per_buffer=4000)
                    except Exception as e:
                        self.after(0, lambda: messagebox.showerror("Ошибка", f"Не удалось открыть микрофон:\n{e}"))
                        p.terminate()
                        return

                    rec = KaldiRecognizer(self.shared_model, 16000)
                    self.after(0, lambda: messagebox.showinfo("Запись", "Произнесите команду"))

                    frames = []
                    for _ in range(0, int(16000 / 4000 * 5)):
                        try:
                            data = stream.read(4000, exception_on_overflow=False)
                            frames.append(data)
                        except IOError:
                            continue

                    stream.stop_stream()
                    stream.close()
                    p.terminate()

                    for frame in frames:
                        rec.AcceptWaveform(frame)

                    result_json = rec.Result()
                    text = json.loads(result_json).get("text", "").strip()

                    def update_gui():
                        try:
                            entry_cmd.delete(0, tk.END)
                            entry_cmd.insert(0, text)
                        except Exception:
                            pass

                    self.after(0, update_gui)

                threading.Thread(target=listen, daemon=True).start()

            tb.Button(cmd_frame, text="🎤", width=4, bootstyle="outline-secondary", command=record_phrase).pack(side=tk.RIGHT)

            tb.Label(frame_repl, text="На какой символ или слово заменять:").pack(anchor=tk.W)
            sym_frame = tb.Frame(frame_repl)
            sym_frame.pack(fill=tk.X, pady=(2, 15))
            entry_sym = tb.Entry(sym_frame)
            entry_sym.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
            tb.Button(sym_frame, text="⌨️ Клавиатура", bootstyle="outline-info", command=lambda: os.system("start osk.exe")).pack(side=tk.RIGHT)

            list_container = tb.Frame(frame_repl)
            list_container.pack(fill=tk.BOTH, expand=True, pady=5)
            listbox = tk.Listbox(list_container, font=("Courier New", 10))
            listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scroll = tb.Scrollbar(list_container, orient=tk.VERTICAL, command=listbox.yview)
            scroll.pack(side=tk.RIGHT, fill=tk.Y)
            listbox.configure(yscrollcommand=scroll.set)

            listbox_keys = []

            def refresh():
                listbox.delete(0, tk.END)
                listbox_keys.clear()
                for cmd, sym in replacements.items():
                    listbox_keys.append(cmd)
                    listbox.insert(tk.END, f" 🗣 '{cmd}'  ➔  🎹 '{sym}'")

            def add():
                cmd_text = entry_cmd.get().strip().lower()
                sym_text = entry_sym.get().strip()
                if not cmd_text or not sym_text:
                    messagebox.showwarning("Ошибка", "Заполните оба поля!", parent=win_repl)
                    return
                replacements[cmd_text] = sym_text
                self.settings["voice_replacements"] = replacements
                self.save_settings()
                refresh()
                entry_cmd.delete(0, tk.END)
                entry_sym.delete(0, tk.END)

            def delete():
                sel = listbox.curselection()
                if sel:
                    index = sel[0]
                    cmd_to_del = listbox_keys[index]
                    if cmd_to_del in replacements:
                        del replacements[cmd_to_del]
                        self.settings["voice_replacements"] = replacements
                        self.save_settings()
                        refresh()

            tb.Button(frame_repl, text="Добавить замену", bootstyle="success", command=add).pack(fill=tk.X, pady=3)
            tb.Button(frame_repl, text="Удалить выбранное", bootstyle="danger-outline", command=delete).pack(fill=tk.X, pady=3)
            refresh()
            win_repl.protocol("WM_DELETE_WINDOW", lambda: setattr(self, '_repl_win', None) or win_repl.destroy())

        tb.Button(frame_voice, text="🔣 Настройка голосовых замен и знаков", bootstyle="info-outline", command=internal_open_replacements).pack(fill=tk.X, pady=(0, 20))

        actions_frame = tb.Frame(frame_voice)
        actions_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        tb.Button(actions_frame, text="Сохранить микрофон", bootstyle="success", command=save_voice_config).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        tb.Button(actions_frame, text="Отмена", bootstyle="secondary", command=lambda: (win.destroy(), setattr(self, '_voice_settings_win', None))).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        win.protocol("WM_DELETE_WINDOW", lambda: setattr(self, '_voice_settings_win', None) or win.destroy())

    def open_color_correction_settings(self):
        if hasattr(self, '_color_settings_win') and self._color_settings_win is not None and self._color_settings_win.winfo_exists():
            self._color_settings_win.lift()
            self._color_settings_win.focus_force()
            return
        win = tb.Toplevel(title="Настройки цветокоррекции")
        w, h = self.get_screen_adaptive_size(0.45, 0.4, min_width=550, min_height=350)
        win.geometry(f"{w}x{h}")
        win.minsize(550, 350)
        win.resizable(True, True)
        self._color_settings_win = win

        container = tb.Frame(win, padding=20)
        container.pack(fill=tk.BOTH, expand=True)

        tb.Label(container, text="Коррекция цвета для дальтоников", font=("Segoe UI", 14, "bold")).pack(pady=15)

        type_frame = tb.Frame(container)
        type_frame.pack(fill=tk.X, padx=20, pady=10)
        tb.Label(type_frame, text="Тип коррекции:").pack(side=tk.LEFT, padx=(0, 10))
        temp_type = tk.StringVar(value=self.color_correction_type)
        types = [("Протанопия (красный)", "protanomaly"), ("Дейтеранопия (зелёный)", "deuteranomaly"), ("Тританопия (синий)", "tritanomaly")]
        for text, val in types:
            tb.Radiobutton(type_frame, text=text, variable=temp_type, value=val).pack(anchor=tk.W)

        int_frame = tb.Frame(container)
        int_frame.pack(fill=tk.X, padx=20, pady=10)
        tb.Label(int_frame, text="Интенсивность:").pack(side=tk.LEFT, padx=(0, 10))
        temp_intensity = tk.DoubleVar(value=self.color_intensity)
        int_slider = tb.Scale(int_frame, from_=0.0, to=1.0, variable=temp_intensity, orient=tk.HORIZONTAL, length=200)
        int_slider.pack(side=tk.LEFT, fill=tk.X, expand=True)
        int_label = tb.Label(int_frame, text=f"{int(temp_intensity.get() * 100)}%")
        int_label.pack(side=tk.LEFT)
        def update_int_label(*args):
            int_label.config(text=f"{int(temp_intensity.get() * 100)}%")
        temp_intensity.trace_add('write', update_int_label)

        gain_frame = tb.Frame(container)
        gain_frame.pack(fill=tk.X, padx=20, pady=10)
        tb.Label(gain_frame, text="Усиление цвета:").pack(side=tk.LEFT, padx=(0, 10))
        temp_gain = tk.DoubleVar(value=self.color_gain)
        gain_slider = tb.Scale(gain_frame, from_=0.0, to=1.0, variable=temp_gain, orient=tk.HORIZONTAL, length=200)
        gain_slider.pack(side=tk.LEFT, fill=tk.X, expand=True)
        gain_label = tb.Label(gain_frame, text=f"{int(temp_gain.get() * 100)}%")
        gain_label.pack(side=tk.LEFT)
        def update_gain_label(*args):
            gain_label.config(text=f"{int(temp_gain.get() * 100)}%")
        temp_gain.trace_add('write', update_gain_label)

        btn_frame = tb.Frame(container)
        btn_frame.pack(pady=20)

        def apply_changes():
            self.color_correction_type = temp_type.get()
            self.color_intensity = temp_intensity.get()
            self.color_gain = temp_gain.get()
            self.settings["color_correction"] = {"type": self.color_correction_type, "intensity": self.color_intensity, "gain": self.color_gain}
            self.save_settings()
            self.color_correction_overlay.set_correction_type(self.color_correction_type)
            self.color_correction_overlay.set_intensity(self.color_intensity)
            self.color_correction_overlay.set_gain(self.color_gain)
            if self.color_correction_var.get():
                self.stop_color_correction()
                self.start_color_correction()
            messagebox.showinfo("Успех", "Настройки цветокоррекции сохранены")

        def close_window():
            if self._color_settings_win:
                self._color_settings_win.destroy()
                self._color_settings_win = None

        tb.Button(btn_frame, text="Применить", bootstyle="success", command=apply_changes).pack(side=tk.LEFT, padx=10)
        tb.Button(btn_frame, text="Закрыть", bootstyle="secondary", command=close_window).pack(side=tk.LEFT, padx=10)
        win.protocol("WM_DELETE_WINDOW", lambda: setattr(self, '_color_settings_win', None) or win.destroy())

    def open_program_settings(self):
        if hasattr(self, '_program_win') and self._program_win is not None and self._program_win.winfo_exists():
            self._program_win.lift()
            self._program_win.focus_force()
            return
        win = tb.Toplevel(title="Настройки программы")
        w, h = self.get_screen_adaptive_size(0.4, 0.45, min_width=450, min_height=480)
        win.geometry(f"{w}x{h}")
        win.minsize(450, 480)
        win.resizable(True, True)
        self._program_win = win

        container = tb.Frame(win, padding=20)
        container.pack(fill=tk.BOTH, expand=True)

        tb.Label(container, text="⚙️ Общие настройки", font=("Segoe UI", 14, "bold")).pack(pady=(0, 20))

        themes_dict = {
            "darkly": "Тёмная классика", "flatly": "Светлая классика",
            "superhero": "Супергерой", "cyborg": "Киборг",
            "vapor": "Киберпанк", "solar": "Солнечная"
        }
        rev_themes = {v: k for k, v in themes_dict.items()}
        theme_frame = tb.Frame(container)
        theme_frame.pack(fill=tk.X, pady=10)
        tb.Label(theme_frame, text="Выберите оформление:").pack(anchor=tk.W, pady=5)
        theme_combo = ttk.Combobox(theme_frame, values=list(themes_dict.values()), state="readonly")
        current_tech = self.style.theme.name
        theme_combo.set(themes_dict.get(current_tech, "Тёмная классика"))
        theme_combo.pack(fill=tk.X)

        def on_theme_change(event):
            rus_name = theme_combo.get()
            tech_name = rev_themes.get(rus_name, "darkly")
            self.style.theme_use(tech_name)
            self.settings["app"]["theme"] = tech_name
            self.save_settings()
            self.update()
            if hasattr(self, 'menu_frame'):
                self.refresh_menu_content()
        theme_combo.bind("<<ComboboxSelected>>", on_theme_change)

        tb.Separator(container).pack(pady=15, fill=tk.X)

        def check_autorun():
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
                    winreg.QueryValueEx(key, "AssistiveSuite")
                    return True
            except:
                return False

        def set_autorun(enable):
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS) as key:
                    if enable:
                        if getattr(sys, 'frozen', False):
                            app_path = f'"{sys.executable}"'
                        else:
                            app_path = f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"'
                        winreg.SetValueEx(key, "AssistiveSuite", 0, winreg.REG_SZ, app_path)
                    else:
                        try:
                            winreg.DeleteValue(key, "AssistiveSuite")
                        except FileNotFoundError:
                            pass
            except Exception as e:
                pass

        def set_tray(enable):
            self.settings["minimize_to_tray"] = enable
            self.save_settings()

        autorun_var = tk.BooleanVar(value=check_autorun())
        cb_autorun = tb.Checkbutton(container, text="Запускать при старте Windows",
                                    bootstyle="success-square-toggle",
                                    command=lambda: set_autorun(autorun_var.get()),
                                    variable=autorun_var)
        cb_autorun.pack(anchor=tk.W, pady=5)

        tray_var = tk.BooleanVar(value=self.settings.get("minimize_to_tray", False))
        cb_tray = tb.Checkbutton(container, text="Сворачивать в трей при закрытии",
                                 bootstyle="success-square-toggle",
                                 command=lambda: set_tray(tray_var.get()),
                                 variable=tray_var)
        cb_tray.pack(anchor=tk.W, pady=5)

        tb.Separator(container).pack(pady=15, fill=tk.X)
        tb.Button(container, text="Закрыть", bootstyle="secondary", command=win.destroy).pack(side=tk.BOTTOM, fill=tk.X, pady=10)
        win.protocol("WM_DELETE_WINDOW", lambda: setattr(self, '_program_win', None) or win.destroy())

    def open_instructions_window(self):
        if hasattr(self, '_instructions_win') and self._instructions_win is not None and self._instructions_win.winfo_exists():
            self._instructions_win.lift()
            self._instructions_win.focus_force()
            return
        win = tb.Toplevel(title="Центр помощи")
        w, h = self.get_screen_adaptive_size(0.4, 0.5, 550, 450)
        win.geometry(f"{w}x{h}")
        win.minsize(600, 500)
        win.resizable(True, True)
        self._instructions_win = win

        main_frame = tb.Frame(win, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        tb.Label(main_frame, text="📖 Руководство пользователя", font=("Segoe UI", 16, "bold"), bootstyle="success").pack(pady=(0, 20))
        btn_container = tb.Frame(main_frame)
        btn_container.pack(fill=tk.X, pady=10)
        menu_items = [
            ("Управление головой", "👁️", self.show_eye_instruction),
            ("Цветокоррекция", "🎨", self.show_color_instruction),
            ("Субтитры", "📝", self.show_subtitles_instruction),
            ("Голосовой ввод", "🎤", self.show_voice_instruction),
            ("Запуск по кнопке", "⚡", self.show_script_launcher_instruction),
            ("Комбинации клавиш", "⌨️", self.show_hotkeys_instruction),
            ("Голосовые команды", "🔊", self.show_voice_commands_instruction)
        ]

        for idx, (text, icon, cmd) in enumerate(menu_items):
            if text == "Запуск по кнопке":
                tb.Separator(btn_container).pack(pady=15, fill=tk.X)
            if idx >= 4:
                style = "outline-warning"
            else:
                style = "outline-secondary"
            btn = tb.Button(btn_container, text=f"{icon} {text}", bootstyle=style, command=cmd)
            btn.pack(pady=5, fill=tk.X)

        tb.Button(main_frame, text="Понятно", bootstyle="success", command=win.destroy).pack(side=tk.BOTTOM, pady=10)
        win.protocol("WM_DELETE_WINDOW", lambda: setattr(self, '_instructions_win', None) or win.destroy())

    def create_side_menu(self):
        self.menu_frame = tk.Frame(
            self.main_container,
            width=280,
            bg=self.style.colors.bg,
            bd=0,
            highlightthickness=0,
            padx=0,
            pady=0
        )
        self.menu_frame.place(x=-280, y=0, width=280, relheight=1.0)
        self.menu_frame.pack_propagate(False)

        self.menu_content = tk.Frame(self.menu_frame, bg=self.style.colors.bg)
        self.menu_content.pack(fill=tk.BOTH, expand=True)

        self.accent_canvas = tk.Canvas(self.menu_frame, width=4, bg=self.style.colors.bg, highlightthickness=0)
        self.accent_canvas.place(relx=1.0, x=-4, y=0, width=4, relheight=1.0)
        self.accent_canvas.create_line(2, 0, 2, 10000, fill='#28a745', width=3)

        self.refresh_menu_content()

    def refresh_menu_content(self):
        for widget in self.menu_content.winfo_children():
            widget.destroy()

        bg_color = self.style.colors.bg
        fg_color = self.style.colors.fg
        accent = '#28a745'
        hover_bg = self.style.colors.inputbg
        btn_style = {
            "bg": bg_color, "fg": fg_color,
            "activebackground": hover_bg, "activeforeground": accent,
            "relief": "flat", "bd": 0, "font": ("Segoe UI", 10, "bold"),
            "anchor": "w", "padx": 15
        }

        tk.Label(self.menu_content, text="МЕНЮ", font=("Segoe UI", 16, "bold"),
                 bg=bg_color, fg=accent, bd=0, highlightthickness=0).pack(pady=(40, 30))

        tk.Button(self.menu_content, text="📖 Инструкция", **btn_style,
                  command=self.open_instructions_window).pack(fill="x", pady=5, padx=(0, 10))
        tk.Button(self.menu_content, text="⚙️ Настройки программы", **btn_style,
                  command=self.open_program_settings).pack(fill="x", pady=5, padx=(0, 10))

        tk.Frame(self.menu_content, bg=self.style.colors.border, height=1, bd=0, highlightthickness=0).pack(fill="x", padx=20, pady=20)

        tk.Button(self.menu_content, text="🎤 Голосовые команды", **btn_style,
                  command=self.voice_cmd.show_settings_window).pack(fill="x", pady=5, padx=(0, 10))
        tk.Button(self.menu_content, text="⌨️ Комбинации клавиш", **btn_style,
                  command=self.hotkey_cmd.show_settings_window).pack(fill="x", pady=5, padx=(0, 10))
        tk.Button(self.menu_content, text="⚡ Запуск по кнопке", **btn_style,
                  command=self.script_launcher.show_main_window).pack(fill="x", pady=5, padx=(0, 10))

        if self.script_launcher.buttons:
            tk.Frame(self.menu_content, bg=self.style.colors.border, height=1, bd=0, highlightthickness=0).pack(fill="x", padx=20, pady=10)
            for name in list(self.script_launcher.buttons.keys()):
                btn = tk.Button(self.menu_content, text=f"▶ {name}", **btn_style,
                                command=lambda n=name: self.script_launcher.run_script(n))
                btn.pack(fill="x", pady=5, padx=(0, 10))

        tk.Frame(self.menu_content, bg=self.style.colors.border, height=1, bd=0, highlightthickness=0).pack(fill="x", padx=20, pady=20)
        frame_sw = tk.Frame(self.menu_content, bg=bg_color, bd=0, highlightthickness=0)
        frame_sw.pack(fill="x", padx=(20, 15), pady=5)
        tk.Label(frame_sw, text="Авто-меню", bg=bg_color, fg="gray", font=("Segoe UI", 9), bd=0, highlightthickness=0).pack(side="left")
        tb.Checkbutton(frame_sw, variable=self.menu_on_hover_var, bootstyle="success-round-toggle").pack(side="right")

        btn_close = tk.Button(self.menu_content, text="✕ ЗАКРЫТЬ", **btn_style, command=self.close_menu)
        btn_close.pack(side="bottom", fill="x", pady=30, padx=(0, 10))

    def create_hover_detector(self):
        self.hover_detector = tk.Frame(self.main_container, bg="", width=15)
        self.hover_detector.place(x=0, y=0, width=15, relheight=1.0)
        self.hover_detector.lower()
        self.bind_hover_events()

    def bind_hover_events(self):
        def on_enter_hitbox(e):
            if self.menu_on_hover_var.get() and not self.menu_open:
                self.open_menu()
        self.hover_detector.bind("<Enter>", on_enter_hitbox)

        def is_mouse_over_menu():
            x, y = self.winfo_pointerxy()
            widget = self.winfo_containing(x, y)
            while widget:
                if widget == self.menu_frame:
                    return True
                widget = widget.master
            return False

        def on_mouse_move(e):
            if self.menu_on_hover_var.get() and self.menu_open:
                if not is_mouse_over_menu():
                    self.close_menu()
        self.bind("<Motion>", on_mouse_move)

    def toggle_menu(self):
        if self.menu_open:
            self.close_menu()
        else:
            self.open_menu()

    def open_menu(self):
        if not self.menu_open:
            self.menu_frame.place(x=0, y=0)
            self.menu_frame.lift()
            self.menu_open = True

    def close_menu(self):
        if self.menu_open:
            self.menu_frame.place(x=-280, y=0)
            self.menu_open = False

    def _create_styled_info_window(self, title, icon, subtitle, steps):
        win = tb.Toplevel(title=title)
        w, h = self.get_screen_adaptive_size(0.35, 0.45, min_width=500, min_height=450)
        win.geometry(f"{w}x{h}")
        win.minsize(550, 550)
        win.resizable(True, True)

        container = tb.Frame(win, padding=25)
        container.pack(fill=tk.BOTH, expand=True)

        header_frame = tb.Frame(container)
        header_frame.pack(fill=tk.X, pady=(0, 15))
        tb.Label(header_frame, text=icon, font=("Segoe UI", 24)).pack(side=tk.LEFT, padx=(0, 15))
        tb.Label(header_frame, text=title, font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)

        tb.Label(container, text=subtitle, font=("Segoe UI", 10, "italic"),
                 wraplength=int(w*0.8), justify=tk.LEFT, foreground="gray").pack(anchor=tk.W, pady=(0, 20))

        steps_frame = tb.Frame(container)
        steps_frame.pack(fill=tk.BOTH, expand=True)

        for i, step in enumerate(steps, 1):
            step_frame = tb.Frame(steps_frame)
            step_frame.pack(fill=tk.X, pady=5)
            tb.Label(step_frame, text=f"{i}.", font=("Segoe UI", 10, "bold"),
                     bootstyle="success").pack(side=tk.LEFT, anchor=tk.N, padx=(0, 10))
            tb.Label(step_frame, text=step, font=("Segoe UI", 10),
                     wraplength=int(w*0.7), justify=tk.LEFT).pack(side=tk.LEFT, anchor=tk.W, fill=tk.X, expand=True)

        tb.Button(container, text="Закрыть", bootstyle="outline-success", command=win.destroy).pack(pady=(20, 0))

    def show_voice_instruction(self):
        steps = ["Убедитесь, что микрофон подключен в настройках (⚙️).", "Нажмите кнопку ▶ на панели управления для старта.",
                 "Говорите четко. Текст будет печататься в активное окно.", "Используйте кнопку паузы (⏸), если нужно прерваться.",
                 "Для завершения нажмите кнопку Стоп (⏹)."]
        self._create_styled_info_window("Голосовой ввод", "🎤", "Превращает вашу речь в печатный текст в любом приложении.", steps)

    def show_subtitles_instruction(self):
        steps = ["Выберите устройство в настройках.", "Включите функцию: появится прозрачное окно.",
                 "Окно можно перетаскивать и менять его прозрачность.", "Теперь можно использовать для получения информации в звуковом варианте.",
                 "Текст очищается автоматически каждые несколько секунд."]
        self._create_styled_info_window("Субтитры", "📝", "Отображает системные звуки и речь в виде текста поверх всех окон.", steps)

    def show_color_instruction(self):
        steps = ["Выберите ваш тип цветовой слепоты в настройках.", "Настройте ползунки под себя.",
                 "Фильтр применяется ко всей области экрана мгновенно.", "Если цвета не изменились, попробуйте перезапустить функцию."]
        self._create_styled_info_window("Коррекция цвета", "🎨", "Адаптирует палитру монитора для лучшего различения цветов.", steps)

    def show_eye_instruction(self):
        steps = ["Замрите перед камерой в центре экрана при включении.", "Поворот головы — мышь плавно едет в сторону.",
                 "Левый глаз — клик ЛКМ, Правый глаз — ПКМ.", "Долгое закрытие глаза — зажатие кнопки.",
                 "Моргните обоими глазами 2 раза для быстрого сброса центра."]
        self._create_styled_info_window("Управление головой", "👁️", "Полный контроль мыши без помощи рук при помощи веб-камеры.", steps)

    def show_voice_commands_instruction(self):
        steps = ["Откройте настройки голосовых команд из бокового меню.",
                 "Придумайте слово или фразу (например, 'открой браузер').",
                  "Привяжите к этой фразе системное действие или запуск программы.",
                  "Слушатель команд работает в фоновом режиме, пока запущен ассистент.",
                  "Произнесите команду четко, и система мгновенно выполнит действие."]
        self._create_styled_info_window("Голосовые команды", "🔊", "Управление операционной системой и ассистентом при помощи голосовых триггеров.", steps)

    def show_hotkeys_instruction(self):
        steps = ["Зайдите в раздел 'Комбинации клавиш' в боковом меню.",
                 "Скажите фразу или слово, которое вы хотите привязать к комбинации.",
                 "Нажмите сочетание клавиш на клавиатуре для записи бинда.",
                 "Горячие клавиши работают глобально, даже если окно ассистента свернуто.",
                 "Используйте данную функцию если требуется применить горячие клавиши но возможности сделать это с физ. клавиатуры нету."]
        self._create_styled_info_window("Комбинации клавиш", "⌨️", "Быстрый запуск и переключение инклюзивных функций с клавиатуры.", steps)

    def show_script_launcher_instruction(self):
        steps = ["Откройте 'Запуск по кнопке' и перейдите в настройки создания кнопок.",
                 "Укажите название кнопки.",
                 "Добавьте элементы: это могут быть локальные файлы, программы или сайты.",
                 "Для сайтов можно вводить ссылки в любом формате (например, 'https://youtube.com' или 'google.com').",
                 "Нажмите 'Сохранить кнопку'. Теперь запускать нужные сценарии можно в один клик из меню."]
        self._create_styled_info_window("Запуск по кнопке", "⚡", "Создание кастомных сценариев для мгновенного открытия файлов, приложений и сайтов.", steps)

if __name__ == "__main__":
    app = AssistiveSuite()
    app.mainloop()