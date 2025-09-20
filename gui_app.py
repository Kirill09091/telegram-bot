import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk
import threading
import time
import subprocess
import os
import re
from multiprocessing import Queue 
import psutil 
import datetime 
from PIL import Image, ImageTk 
import sys # <-- Эта строка очень важна для корректной работы иконки в скомпилированном exe

LOG_FILE = 'bot_activity.log' # Имя файла логов, должно совпадать с main.py
MAIN_PY_PATH = 'main.py' # Путь к файлу main.py
ICON_FILENAME = 'bot_logo.png' # Имя PNG файла иконки. Замените на свое, если нужно.

class App:
    def __init__(self, master):
        self.master = master
        master.title("Управление Telegram Ботом")
        master.geometry("800x700") 
        master.configure(bg='black') # Темная тема

        # --- Добавление иконки окна ---
        # Правильный путь для PyInstaller
        if getattr(sys, 'frozen', False):
            # Если приложение заморожено (скомпилировано PyInstaller)
            base_path = sys._MEIPASS
        else:
            # Если запускается как обычный скрипт Python
            base_path = os.path.abspath(".")
        
        icon_path_full = os.path.join(base_path, ICON_FILENAME)

        if os.path.exists(icon_path_full):
            try:
                # Открываем изображение для иконки
                icon_image = Image.open(icon_path_full)
                # Tkinter PhotoImage для иконки окна
                self.tk_icon = ImageTk.PhotoImage(icon_image)
                # Устанавливаем иконку окна
                self.master.iconphoto(True, self.tk_icon) 
            except Exception as e:
                messagebox.showwarning("Ошибка загрузки иконки", f"Не удалось загрузить иконку {icon_path_full}: {e}")
        else:
            messagebox.showwarning("Иконка не найдена", f"Файл иконки '{ICON_FILENAME}' не найден. Для отображения иконки окна, поместите его в ту же папку, что и gui_app.py, или убедитесь, что он включен в сборку PyInstaller.")


        # Переменные для хранения процесса бота и очереди команд
        self.bot_process = None
        self.log_tail_thread = None
        self.running_log_tail = True
        self.command_queue = Queue() # Очередь для отправки команд в процесс бота

        # Стилизация для кнопок (черный фон, синие кнопки)
        style = ttk.Style()
        style.theme_use('clam') # Используем тему 'clam' для лучшей настройки
        
        # Общие настройки для кнопок
        style.configure('TButton',
                        background='#007bff', # Синий цвет
                        foreground='white',
                        font=('Helvetica', 10, 'bold'),
                        padding=10,
                        bd=0) # Убираем стандартную границу
        style.map('TButton',
                  background=[('active', '#0056b3')], # Темнее при наведении
                  foreground=[('disabled', '#cccccc')]) # Серый текст для неактивных кнопок

        # Настройки для текстовых полей и меток
        style.configure('TLabel', background='black', foreground='white')
        style.configure('TEntry', fieldbackground='#333333', foreground='white', insertbackground='white')

        # --- Рамка для управления ботом ---
        self.control_frame = tk.Frame(master, bg='black', bd=0)
        self.control_frame.pack(pady=10)

        self.start_button = ttk.Button(self.control_frame, text="Запустить Бота", command=self.start_bot)
        self.start_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")

        self.stop_button = ttk.Button(self.control_frame, text="Остановить Бота", command=self.stop_bot, state=tk.DISABLED)
        self.stop_button.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        # --- Рамка для команд администрирования ---
        self.admin_frame = tk.LabelFrame(master, text="Администрирование", bg='black', fg='white', bd=2, relief="groove", font=('Helvetica', 10, 'bold'))
        self.admin_frame.pack(pady=10, padx=10, fill="x")

        # Настраиваем расширение колонки для поля ввода
        self.admin_frame.grid_columnconfigure(1, weight=1) 

        tk.Label(self.admin_frame, text="ID пользователя (число):", bg='black', fg='white').grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.user_id_entry = tk.Entry(self.admin_frame, width=25, bg='#333333', fg='white', insertbackground='white', bd=1, relief="solid")
        self.user_id_entry.grid(row=0, column=1, padx=5, pady=2, sticky="ew")

        # Новая кнопка "Вставить ID"
        self.paste_id_button = ttk.Button(self.admin_frame, text="Вставить ID", command=self.paste_user_id_from_clipboard)
        self.paste_id_button.grid(row=0, column=2, padx=5, pady=2, sticky="ew")

        # Кнопки администрирования
        self.ban_button = ttk.Button(self.admin_frame, text="Забанить", command=self.ban_user)
        self.ban_button.grid(row=1, column=0, padx=5, pady=5, sticky="ew")

        self.mute_button = ttk.Button(self.admin_frame, text="Замутить", command=self.mute_user)
        self.mute_button.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        self.unban_button = ttk.Button(self.admin_frame, text="Разбанить", command=self.unban_user)
        self.unban_button.grid(row=2, column=0, padx=5, pady=5, sticky="ew")

        self.unmute_button = ttk.Button(self.admin_frame, text="Размутить", command=self.unmute_user)
        self.unmute_button.grid(row=2, column=1, padx=5, pady=5, sticky="ew")

        # Поле для ввода длительности мута и причины
        tk.Label(self.admin_frame, text="Длительность мута (мин, 0=бессрочно):", bg='black', fg='white').grid(row=3, column=0, padx=5, pady=2, sticky="w")
        self.mute_duration_entry = tk.Entry(self.admin_frame, width=10, bg='#333333', fg='white', insertbackground='white', bd=1, relief="solid")
        self.mute_duration_entry.insert(0, "60") # Значение по умолчанию
        self.mute_duration_entry.grid(row=3, column=1, padx=5, pady=2, sticky="ew")

        tk.Label(self.admin_frame, text="Причина:", bg='black', fg='white').grid(row=4, column=0, padx=5, pady=2, sticky="w")
        self.reason_entry = tk.Entry(self.admin_frame, width=30, bg='#333333', fg='white', insertbackground='white', bd=1, relief="solid")
        self.reason_entry.grid(row=4, column=1, padx=5, pady=2, sticky="ew")

        # --- Рамка для логов ---
        self.log_frame = tk.LabelFrame(master, text="Логи Бота", bg='black', fg='white', bd=2, relief="groove", font=('Helvetica', 10, 'bold'))
        self.log_frame.pack(pady=10, padx=10, fill="both", expand=True)

        self.log_text_widget = scrolledtext.ScrolledText(self.log_frame, wrap=tk.WORD, bg='#1a1a1a', fg='white', font=('Consolas', 9), insertbackground='white')
        self.log_text_widget.pack(padx=5, pady=5, fill="both", expand=True)
        self.log_text_widget.config(state=tk.DISABLED) # Только для чтения

        # --- Кнопки управления логами ---
        self.log_control_frame = tk.Frame(master, bg='black', bd=0)
        self.log_control_frame.pack(pady=5, fill="x")

        # Кнопка для копирования выделенного текста
        self.copy_selected_button = ttk.Button(self.log_control_frame, text="Копировать выделенное", command=self.copy_selected_logs)
        self.copy_selected_button.pack(side=tk.LEFT, padx=5, pady=5)

        # Кнопка для копирования всего лога
        self.copy_logs_button = ttk.Button(self.log_control_frame, text="Копировать весь лог", command=self.copy_full_logs)
        self.copy_logs_button.pack(side=tk.LEFT, padx=5, pady=5)

        # Обработка закрытия окна
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def start_bot(self):
        if self.bot_process is None or not self.bot_process.is_alive():
            try:
                self.log_text_widget.config(state=tk.NORMAL)
                self.log_text_widget.insert(tk.END, "[GUI]: Запуск бота...\n")
                self.log_text_widget.config(state=tk.DISABLED)
                self.log_text_widget.see(tk.END)

                # Запускаем main.py как отдельный процесс, передавая ему очередь команд
                self.bot_process = subprocess.Popen(['python', MAIN_PY_PATH], 
                                                    stdout=subprocess.PIPE, 
                                                    stderr=subprocess.PIPE,
                                                    text=True,  # Декодирует stdout/stderr как текст
                                                    bufsize=1,  # Буферизация построчно
                                                    universal_newlines=True # Также для текста
                                                    )
                
                # Запускаем поток для чтения логов из файла
                self.running_log_tail = True
                self.log_tail_thread = threading.Thread(target=self.tail_log_file)
                self.log_tail_thread.daemon = True # Поток завершится с основным приложением
                self.log_tail_thread.start()

                self.start_button.config(state=tk.DISABLED)
                self.stop_button.config(state=tk.NORMAL)
                self.set_admin_buttons_state(tk.NORMAL)
                self.paste_id_button.config(state=tk.NORMAL) # Включаем кнопку вставки
                self.copy_selected_button.config(state=tk.NORMAL) # Включаем кнопку копирования выделенного
                self.copy_logs_button.config(state=tk.NORMAL) # Включаем кнопку копирования всего лога

                messagebox.showinfo("Статус", "Бот запущен!")

            except Exception as e:
                messagebox.showerror("Ошибка запуска", f"Не удалось запустить бота: {e}")
                self.log_text_widget.config(state=tk.NORMAL)
                self.log_text_widget.insert(tk.END, f"[GUI Error]: Failed to start bot: {e}\n")
                self.log_text_widget.config(state=tk.DISABLED)
                self.log_text_widget.see(tk.END)
        else:
            messagebox.showinfo("Статус", "Бот уже запущен.")

    def stop_bot(self):
        if self.bot_process and self.bot_process.poll() is None: # Проверяем, что процесс еще запущен
            try:
                self.log_text_widget.config(state=tk.NORMAL)
                self.log_text_widget.insert(tk.END, "[GUI]: Попытка остановить бота...\n")
                self.log_text_widget.config(state=tk.DISABLED)
                self.log_text_widget.see(tk.END)

                # Отправляем команду SHUTDOWN через очередь, чтобы бот завершился корректно
                if self.command_queue:
                    self.command_queue.put("SHUTDOWN")
                    # Даем боту немного времени на завершение
                    time.sleep(1) 

                # Если процесс все еще жив, принудительно завершаем
                if self.bot_process.poll() is None:
                    # Убить процесс и его потомков
                    parent = psutil.Process(self.bot_process.pid)
                    for child in parent.children(recursive=True):
                        child.terminate()
                    parent.terminate()
                    gone, alive = psutil.wait_procs([parent] + parent.children(recursive=True), timeout=5)
                    for p in alive:
                        p.kill() # Убиваем, если не завершились
                    # Добавляем лог через стандартный print, т.к. логгер main.py уже может быть выключен
                    print(f"Бот-процесс {self.bot_process.pid} и его потомки принудительно завершены.")


                self.running_log_tail = False # Останавливаем поток чтения логов
                if self.log_tail_thread and self.log_tail_thread.is_alive():
                    self.log_tail_thread.join(timeout=2) # Ждем завершения потока

                self.bot_process = None
                self.start_button.config(state=tk.NORMAL)
                self.stop_button.config(state=tk.DISABLED)
                self.set_admin_buttons_state(tk.DISABLED)
                self.paste_id_button.config(state=tk.DISABLED) # Отключаем кнопку вставки
                self.copy_selected_button.config(state=tk.DISABLED) # Отключаем кнопку копирования выделенного
                self.copy_logs_button.config(state=tk.DISABLED) # Отключаем кнопку копирования всего лога


                messagebox.showinfo("Статус", "Бот остановлен.")
                self.log_text_widget.config(state=tk.NORMAL)
                self.log_text_widget.insert(tk.END, "[GUI]: Бот успешно остановлен.\n")
                self.log_text_widget.config(state=tk.DISABLED)
                self.log_text_widget.see(tk.END)

            except Exception as e:
                messagebox.showerror("Ошибка остановки", f"Не удалось остановить бота: {e}")
                self.log_text_widget.config(state=tk.NORMAL)
                self.log_text_widget.insert(tk.END, f"[GUI Error]: Failed to stop bot: {e}\n")
                self.log_text_widget.config(state=tk.DISABLED)
                self.log_text_widget.see(tk.END)
        else:
            messagebox.showinfo("Статус", "Бот не запущен.")
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self.set_admin_buttons_state(tk.DISABLED)
            self.paste_id_button.config(state=tk.DISABLED) # Отключаем кнопку вставки
            self.copy_selected_button.config(state=tk.DISABLED) # Отключаем кнопку копирования выделенного
            self.copy_logs_button.config(state=tk.DISABLED) # Отключаем кнопку копирования всего лога


    def tail_log_file(self):
        try:
            # Ждем, пока файл будет создан, если его нет
            while not os.path.exists(LOG_FILE) and self.running_log_tail:
                time.sleep(0.1)

            with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
                # Перемещаемся в конец файла
                f.seek(0, os.SEEK_END)
                while self.running_log_tail:
                    line = f.readline()
                    if not line:
                        time.sleep(0.1) # Ждем новых строк
                        continue
                    # Удаляем цветовые коды ANSI, если они есть (например, от colorlog)
                    clean_line = re.sub(r'\x1b\[[0-9;]*m', '', line)
                    self.master.after(0, self.update_log_widget, clean_line) # Обновляем GUI в основном потоке
        except Exception as e:
            self.master.after(0, self.update_log_widget, f"[GUI Log Error]: {e}\n")

    def update_log_widget(self, message):
        self.log_text_widget.config(state=tk.NORMAL)
        self.log_text_widget.insert(tk.END, message)
        self.log_text_widget.see(tk.END)
        self.log_text_widget.config(state=tk.DISABLED)

    def on_closing(self):
        # Спрашиваем пользователя, действительно ли он хочет выйти
        if messagebox.askokcancel("Выход", "Вы уверены, что хотите выйти? Бот будет остановлен."):
            # Сначала сохраняем логи
            self.save_logs_to_file()
            # Затем останавливаем бота
            self.stop_bot() 
            # И закрываем приложение
            self.master.destroy()

    def save_logs_to_file(self):
        try:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            log_filename = f"logs_{timestamp}.txt"
            
            self.log_text_widget.config(state=tk.NORMAL) # Временно включаем для чтения
            logs_content = self.log_text_widget.get(1.0, tk.END)
            self.log_text_widget.config(state=tk.DISABLED) # Возвращаем в состояние "только для чтения"

            with open(log_filename, 'w', encoding='utf-8') as f:
                f.write(logs_content)
            
            messagebox.showinfo("Сохранение логов", f"Логи сохранены в файл: {log_filename}")
        except Exception as e:
            messagebox.showerror("Ошибка сохранения логов", f"Не удалось сохранить логи: {e}")

    def set_admin_buttons_state(self, state):
        self.ban_button.config(state=state)
        self.mute_button.config(state=state)
        self.unban_button.config(state=state)
        self.unmute_button.config(state=state)
        self.user_id_entry.config(state=state)
        self.mute_duration_entry.config(state=state)
        self.reason_entry.config(state=state)

    def paste_user_id_from_clipboard(self):
        try:
            clipboard_content = self.master.clipboard_get()
            # Простая валидация: убедимся, что это число
            if clipboard_content.strip().isdigit():
                self.user_id_entry.delete(0, tk.END)
                self.user_id_entry.insert(0, clipboard_content.strip())
            else:
                messagebox.showwarning("Вставка ID", "Содержимое буфера обмена не является числовым ID.")
        except tk.TclError:
            messagebox.showwarning("Вставка ID", "Буфер обмена пуст или содержит некорректные данные.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Произошла ошибка при вставке: {e}")

    def send_telegram_command(self, command_type):
        user_input = self.user_id_entry.get().strip()
        duration_input = self.mute_duration_entry.get().strip()
        reason_input = self.reason_entry.get().strip()

        if not user_input:
            messagebox.showwarning("Предупреждение", "Пожалуйста, введите ID пользователя.")
            return

        user_id_arg = user_input # Предполагаем, что это всегда ID
        full_command = ""
        title = ""

        if command_type == "ban":
            full_command = f"/ban_id {user_id_arg} {reason_input}"
            title = "Бан пользователя"
        elif command_type == "mute":
            # Валидация длительности мута
            try:
                duration_minutes = int(duration_input)
                if duration_minutes < 0:
                    messagebox.showwarning("Предупреждение", "Длительность мута не может быть отрицательной. Установлено 0 (бессрочно).")
                    duration_minutes = 0
            except ValueError:
                messagebox.showwarning("Предупреждение", "Некорректная длительность мута. Установлено 60 минут.")
                duration_minutes = 60 # Значение по умолчанию
            full_command = f"/mute {user_id_arg} {duration_minutes} {reason_input}"
            title = "Мут пользователя"
        elif command_type == "unban":
            full_command = f"/unban_id {user_id_arg}"
            title = "Разбан пользователя"
        elif command_type == "unmute":
            full_command = f"/unmute {user_id_arg}"
            title = "Размут пользователя"
        else:
            messagebox.showerror("Ошибка", "Неизвестная команда.")
            return

        # Отправка команды в очередь, которую слушает основной процесс бота
        if self.command_queue:
            self.command_queue.put(full_command)
            messagebox.showinfo(title, f"Команда '{full_command}' отправлена боту.")
            self.log_text_widget.config(state=tk.NORMAL)
            self.log_text_widget.insert(tk.END, f"[GUI Action]: Command sent to bot: {full_command}\n")
            self.log_text_widget.see(tk.END)
            self.log_text_widget.config(state=tk.DISABLED)
        else:
            messagebox.showerror("Ошибка", "Бот не запущен или канал связи недоступен.")
            self.log_text_widget.config(state=tk.NORMAL)
            self.log_text_widget.insert(tk.END, "[GUI Error]: Bot not running or command queue not available.\n")
            self.log_text_widget.see(tk.END)
            self.log_text_widget.config(state=tk.DISABLED)

    def ban_user(self):
        self.send_telegram_command("ban")

    def mute_user(self):
        self.send_telegram_command("mute")

    def unban_user(self):
        self.send_telegram_command("unban")

    def unmute_user(self):
        self.send_telegram_command("unmute")

    def copy_selected_logs(self):
        try:
            self.log_text_widget.config(state=tk.NORMAL)
            selected_text = self.log_text_widget.get(tk.SEL_FIRST, tk.SEL_LAST)
            self.master.clipboard_clear()
            self.master.clipboard_append(selected_text)
            self.master.update()
            if selected_text:
                messagebox.showinfo("Копирование", "Выделенный текст скопирован в буфер обмена!")
            else:
                messagebox.showwarning("Копирование", "Нет выделенного текста для копирования.")
        except tk.TclError:
            messagebox.showwarning("Копирование", "Нет выделенного текста для копирования.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Произошла ошибка при копировании: {e}")
        finally:
            self.log_text_widget.config(state=tk.DISABLED)

    def copy_full_logs(self):
        self.log_text_widget.config(state=tk.NORMAL)
        logs = self.log_text_widget.get(1.0, tk.END)
        self.master.clipboard_clear()
        self.master.clipboard_append(logs)
        self.master.update()
        messagebox.showinfo("Копирование", "Весь лог скопирован в буфер обмена!")
        self.log_text_widget.config(state=tk.DISABLED)

if __name__ == '__main__':
    root = tk.Tk()
    app = App(root)
    root.mainloop()