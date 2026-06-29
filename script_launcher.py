import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import ttkbootstrap as tb
import webbrowser
import os
import re
import subprocess

class ScriptLauncherManager:
    def __init__(self, parent):
        self.parent = parent
        self.buttons = parent.settings.get("script_buttons", {})
        self._main_win = None
        self._settings_win = None

    def run_script(self, name):
        items = self.buttons.get(name, [])
        if not items:
            return
        for path in items:
            path = path.strip()
            
            url_pattern = re.compile(r'^(https?://)?([a-zA-Z0-9а-яА-ЯёЁ\-]+\.)+[a-zA-Zа-яА-Я]{2,}(\/.*)?$')
            
            if url_pattern.match(path):
                if not (path.startswith("http://") or path.startswith("https://")):
                    path = "https://" + path
                webbrowser.open(path)
            else:
                try:
                    os.startfile(path)
                except Exception as e:
                    try:
                        subprocess.Popen([path], shell=True)
                    except Exception as err:
                        pass

    def show_main_window(self):
        if self._main_win is not None and self._main_win.winfo_exists():
            self._main_win.lift()
            self._main_win.focus_force()
            return
        win = tb.Toplevel(self.parent)
        win.title("Запуск по кнопке")
        win.geometry("500x400")
        win.resizable(False, False)
        self._main_win = win

        def on_close():
            self._main_win = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", on_close)

        frame = tb.Frame(win, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        tb.Label(frame, text="Список созданных кнопок:", font=("Segoe UI", 11, "bold")).pack(anchor=tk.W)

        listbox = tk.Listbox(frame)
        listbox.pack(fill=tk.BOTH, expand=True, pady=5)

        def refresh_list():
            listbox.delete(0, tk.END)
            for name in self.buttons.keys():
                listbox.insert(tk.END, name)

        refresh_list()

        def run_selected():
            sel = listbox.curselection()
            if sel:
                name = listbox.get(sel[0])
                self.run_script(name)

        def edit_settings():
            win.destroy()
            self._main_win = None
            self.show_settings_window()

        btn_run = tb.Button(frame, text="Запустить выбранное", bootstyle="success", command=run_selected)
        btn_run.pack(fill=tk.X, pady=2)

        btn_edit = tb.Button(frame, text="Настроить кнопки", bootstyle="info", command=edit_settings)
        btn_edit.pack(fill=tk.X, pady=2)

        tb.Button(frame, text="Закрыть", bootstyle="secondary", command=win.destroy).pack(fill=tk.X, pady=2)

    def show_settings_window(self):
        if self._settings_win is not None and self._settings_win.winfo_exists():
            self._settings_win.lift()
            self._settings_win.focus_force()
            return
        win = tb.Toplevel(self.parent)
        win.title("Настройка кнопок запуска")
        win.geometry("700x600")
        win.resizable(False, False)
        self._settings_win = win

        def on_close():
            self._settings_win = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", on_close)

        main_frame = tb.Frame(win, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        left_frame = tb.Frame(main_frame, width=250)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0,10))
        left_frame.pack_propagate(False)
        tb.Label(left_frame, text="Существующие кнопки:", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        existing_listbox = tk.Listbox(left_frame)
        existing_listbox.pack(fill=tk.BOTH, expand=True, pady=5)
        scroll = tb.Scrollbar(existing_listbox, orient=tk.VERTICAL)
        existing_listbox.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        def refresh_existing():
            existing_listbox.delete(0, tk.END)
            for name in self.buttons.keys():
                existing_listbox.insert(tk.END, name)
        refresh_existing()

        right_frame = tb.Frame(main_frame)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        tb.Label(right_frame, text="Название кнопки:").pack(anchor=tk.W)
        name_entry = tb.Entry(right_frame)
        name_entry.pack(fill=tk.X, pady=2)

        tb.Label(right_frame, text="Элементы (программы/сайты):").pack(anchor=tk.W, pady=(10,0))
        items_frame = tb.Frame(right_frame)
        items_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        items_listbox = tk.Listbox(items_frame)
        items_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        items_scroll = tb.Scrollbar(items_frame, orient=tk.VERTICAL, command=items_listbox.yview)
        items_listbox.configure(yscrollcommand=items_scroll.set)
        items_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        add_frame = tb.Frame(right_frame)
        add_frame.pack(fill=tk.X, pady=5)
        item_entry = tb.Entry(add_frame)
        item_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))

        def browse():
            path = filedialog.askopenfilename()
            if path:
                item_entry.delete(0, tk.END)
                item_entry.insert(0, path)
        tb.Button(add_frame, text="Обзор", command=browse).pack(side=tk.RIGHT)

        def add_item():
            path = item_entry.get().strip()
            if not path:
                messagebox.showwarning("Ошибка", "Введите путь или URL")
                return
            items_listbox.insert(tk.END, path)
            item_entry.delete(0, tk.END)

        tb.Button(right_frame, text="➕ Добавить элемент", bootstyle="info", command=add_item).pack(fill=tk.X, pady=2)

        def remove_item():
            sel = items_listbox.curselection()
            if sel:
                items_listbox.delete(sel[0])
        tb.Button(right_frame, text="❌ Удалить выбранный элемент", bootstyle="danger", command=remove_item).pack(fill=tk.X, pady=2)

        def load_selected():
            sel = existing_listbox.curselection()
            if sel:
                name = existing_listbox.get(sel[0])
                name_entry.delete(0, tk.END)
                name_entry.insert(0, name)
                items_listbox.delete(0, tk.END)
                for item in self.buttons.get(name, []):
                    items_listbox.insert(tk.END, item)

        def save():
            name = name_entry.get().strip()
            if not name:
                messagebox.showwarning("Ошибка", "Введите название кнопки")
                return
            items = list(items_listbox.get(0, tk.END))
            if not items:
                messagebox.showwarning("Ошибка", "Добавьте хотя бы один элемент")
                return
            self.buttons[name] = items
            self.parent.settings["script_buttons"] = self.buttons
            self.parent.save_settings()

            self.parent.send_settings_to_server() 

            refresh_existing()
            name_entry.delete(0, tk.END)
            items_listbox.delete(0, tk.END)
            
            self.parent.menu_open = False
            if hasattr(self.parent, 'btn_show_menu') and self.parent.btn_show_menu:
                self.parent.btn_show_menu.config(text=">")
            
            if hasattr(self.parent, 'menu_frame') and self.parent.menu_frame:
                try: self.parent.menu_frame.destroy()
                except: pass
                self.parent.menu_frame = None

            if hasattr(self.parent, 'hover_detector') and self.parent.hover_detector:
                try: self.parent.hover_detector.destroy()
                except: pass
                self.parent.hover_detector = None
                
            self.parent.create_side_menu()
            if hasattr(self.parent, 'create_hover_detector'):
                self.parent.create_hover_detector()
            if hasattr(self.parent, 'bind_hover_events'):
                self.parent.bind_hover_events()
                
            win.focus_force()
            messagebox.showinfo("Успех", f'Кнопка "{name}" сохранена')

        def delete_selected():
            sel = existing_listbox.curselection()
            if sel:
                name = existing_listbox.get(sel[0])
                if messagebox.askyesno("Удалить", f'Удалить кнопку "{name}"?'):
                    del self.buttons[name]
                    self.parent.settings["script_buttons"] = self.buttons
                    self.parent.save_settings()

                    self.parent.send_settings_to_server() 

                    refresh_existing()
                    
                    self.parent.menu_open = False
                    if hasattr(self.parent, 'btn_show_menu') and self.parent.btn_show_menu:
                        self.parent.btn_show_menu.config(text=">")
                    
                    if hasattr(self.parent, 'menu_frame') and self.parent.menu_frame:
                        try: self.parent.menu_frame.destroy()
                        except: pass
                        self.parent.menu_frame = None

                    if hasattr(self.parent, 'hover_detector') and self.parent.hover_detector:
                        try: self.parent.hover_detector.destroy()
                        except: pass
                        self.parent.hover_detector = None

                    self.parent.create_side_menu()
                    if hasattr(self.parent, 'create_hover_detector'):
                        self.parent.create_hover_detector()
                    if hasattr(self.parent, 'bind_hover_events'):
                        self.parent.bind_hover_events()
                        
                    name_entry.delete(0, tk.END)
                    items_listbox.delete(0, tk.END)
                    win.focus_force()

        btn_frame = tb.Frame(right_frame)
        btn_frame.pack(fill=tk.X, pady=10)
        tb.Button(btn_frame, text="Загрузить сценарий", bootstyle="secondary", command=load_selected).pack(side=tk.LEFT, padx=2)
        tb.Button(btn_frame, text="Сохранить сценарий", bootstyle="success", command=save).pack(side=tk.LEFT, padx=2)
        tb.Button(btn_frame, text="Удалить сценарий", bootstyle="danger", command=delete_selected).pack(side=tk.LEFT, padx=2)

        refresh_existing()