# main.py - Модифицированный для работы с GUI через очередь

import telebot
from telebot import types
import json
import os
import datetime
import logging
import time
import threading
from multiprocessing import Queue # Импорт Queue
import sys # Для работы с аргументами при запуске
from logging.handlers import RotatingFileHandler # Для более гибкого логирования

# Импорт конфигурации из config.py
try:
    from config import TOKEN, MAIN_CHAT_ID, CHAT_RULES, BAD_WORDS, ADMIN_USER_IDS, AUTO_MUTE_WARN_COUNT, AUTO_MUTE_DURATION_MINUTES, DATA_FILE, SEND_GUI_CONFIRMATIONS_TO_CHAT
except ImportError:
    print("Ошибка: Не найден файл config.py или в нем отсутствуют необходимые переменные.")
    print("Убедитесь, что config.py находится в той же папке, что и main.py, и содержит все необходимые настройки.")
    sys.exit(1) # Используем sys.exit для завершения процесса при ошибке конфигурации

# --- Настройка логирования ---
LOG_FILE = 'bot_activity.log'
try:
    # Удаляем предыдущие обработчики, если они уже были настроены
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    for handler in logging.getLogger().handlers[:]:
        logging.getLogger().removeHandler(handler)

    # Используем RotatingFileHandler для автоматического управления размером лог-файла
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=2, encoding='utf-8')
    stream_handler = logging.StreamHandler() # Вывод в консоль тоже

    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s - %(name)s - %(levelname)s - %(message)s]',
        handlers=[
            file_handler,
            stream_handler
        ]
    )
    logging.info(f"Логи будут записываться в файл: {os.path.abspath(LOG_FILE)}")
    logger = logging.getLogger(__name__)

except Exception as e:
    print(f"Критическая ошибка при настройке логирования: {e}")
    sys.exit(1)

# --- Инициализация бота ---
bot = telebot.TeleBot(TOKEN)

# --- Загрузка и сохранение данных ---
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Проверяем наличие ключей, если файл пуст или поврежден
            if not isinstance(data, dict) or "warns" not in data or "mutes" not in data:
                raise ValueError("Файл данных поврежден или имеет неверный формат.")
            return data
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Ошибка чтения {DATA_FILE}. Файл поврежден или пуст. Создаю новый. Ошибка: {e}")
            return {"warns": {}, "mutes": {}}
    logger.info(f"Файл данных {DATA_FILE} не найден. Создаю новый.")
    return {"warns": {}, "mutes": {}}

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

bot_data = load_data()

# --- Вспомогательные функции ---
def is_admin(user_id):
    return user_id in ADMIN_USER_IDS

def check_mutes():
    current_time = datetime.datetime.now()
    users_to_unmute = []
    for user_id_str, mute_info in list(bot_data["mutes"].items()): # Используем list() для безопасной итерации
        mute_end_time = datetime.datetime.fromisoformat(mute_info["end_time"])
        if current_time >= mute_end_time:
            users_to_unmute.append(int(user_id_str)) # Преобразуем обратно в int для unban_chat_member
    
    for user_id in users_to_unmute:
        try:
            # Размучиваем пользователя
            bot.restrict_chat_member(MAIN_CHAT_ID, user_id, can_send_messages=True, can_add_web_page_previews=True,
                                     can_send_media_messages=True, can_send_other_messages=True)
            bot_data["mutes"].pop(str(user_id))
            save_data(bot_data)
            logger.info(f"Пользователь {user_id} размучен автоматически.")
            # Отправка сообщения в чат об автоматическом размучивании (это сообщение всегда отправляется)
            bot.send_message(MAIN_CHAT_ID, f"Пользователь <a href='tg://user?id={user_id}'>{user_id}</a> был размучен автоматически.", parse_mode='HTML')
        except Exception as e:
            logger.error(f"Ошибка при автоматическом размучивании пользователя {user_id}: {e}")

# --- ОБРАБОТЧИКИ КОМАНД И СООБЩЕНИЙ (как у вас уже есть) ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я твой бот-модератор. Используй /rules, чтобы ознакомиться с правилами.")
    logger.info(f"[{message.chat.title} (ID: {message.chat.id})] - Пользователь {message.from_user.first_name} (ID: {message.from_user.id}) использовал /start")

@bot.message_handler(commands=['rules'])
def send_rules(message):
    bot.send_message(message.chat.id, CHAT_RULES, parse_mode='HTML')
    logger.info(f"[{message.chat.title} (ID: {message.chat.id})] - Пользователь {message.from_user.first_name} (ID: {message.from_user.id}) использовал /rules")

@bot.message_handler(commands=['warn'])
def warn_user(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "У вас нет прав для использования этой команды.")
        return

    try:
        if message.reply_to_message:
            target_user_id = message.reply_to_message.from_user.id
            target_username = message.reply_to_message.from_user.username
            target_first_name = message.reply_to_message.from_user.first_name

            if str(target_user_id) not in bot_data["warns"]:
                bot_data["warns"][str(target_user_id)] = 0
            
            bot_data["warns"][str(target_user_id)] += 1
            save_data(bot_data)

            warn_count = bot_data["warns"][str(target_user_id)]
            bot.reply_to(message.reply_to_message, 
                         f"<a href='tg://user?id={target_user_id}'>{target_first_name}</a>, вам выдано предупреждение ({warn_count}/{AUTO_MUTE_WARN_COUNT}).", 
                         parse_mode='HTML')
            
            logger.info(f"[{message.chat.title} (ID: {message.chat.id})] - Администратор {message.from_user.id} предупредил {target_user_id} (@{target_username}). Предупреждений: {warn_count}")

            if warn_count >= AUTO_MUTE_WARN_COUNT:
                mute_user_id(target_user_id, AUTO_MUTE_DURATION_MINUTES, "Автоматический мут за превышение лимита предупреждений", message.chat.id)
                bot_data["warns"][str(target_user_id)] = 0 # Сбрасываем счетчик предупреждений после авто-мута
                save_data(bot_data)

        else:
            bot.reply_to(message, "Эта команда должна быть использована в ответ на сообщение пользователя.")
    except Exception as e:
        logger.error(f"Ошибка при выполнении команды /warn: {e}", exc_info=True)
        bot.reply_to(message, "Произошла ошибка при обработке команды /warn.")

def mute_user_id(user_id, duration_minutes, reason, chat_id):
    try:
        current_time = datetime.datetime.now()
        mute_end_time = current_time + datetime.timedelta(minutes=duration_minutes)
        
        bot.restrict_chat_member(chat_id, user_id, 
                                 can_send_messages=False, 
                                 until_date=int(mute_end_time.timestamp()))
        
        bot_data["mutes"][str(user_id)] = {
            "end_time": mute_end_time.isoformat(),
            "reason": reason,
            "admin_id": chat_id # В данном случае это chat_id, если мут из чата
        }
        save_data(bot_data)
        logger.info(f"Пользователь {user_id} замучен на {duration_minutes} минут. Причина: {reason}")
        # Это сообщение отправляется в чат, если мут сделан через GUI и SEND_GUI_CONFIRMATIONS_TO_CHAT = True
        # или если это автоматический мут (тогда вызывается отсюда)
        if SEND_GUI_CONFIRMATIONS_TO_CHAT: # Отправляем только если включено
            bot.send_message(chat_id, f"Пользователь <a href='tg://user?id={user_id}'>{user_id}</a> замучен на {duration_minutes} минут. Причина: {reason}", parse_mode='HTML')
    except Exception as e:
        logger.error(f"Ошибка при мутировании пользователя {user_id}: {e}", exc_info=True)

# Обработчик текстовых сообщений
@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_text(message):
    # Исправленная строка f-string:
    full_name_or_empty = ((message.from_user.first_name or '') + ' ' + (message.from_user.last_name or '')).strip()
    logger.info(f"[{message.chat.title} (ID: {message.chat.id}) (Type: {message.chat.type})] - "
                f"[{full_name_or_empty} " # Используем очищенное полное имя
                f"(ID: {message.from_user.id}) (Username: @{message.from_user.username or ''})]: {message.text}")


    # Проверка на плохие слова
    if message.chat.type in ['group', 'supergroup']:
        for word in BAD_WORDS:
            if word in message.text.lower():
                try:
                    bot.delete_message(message.chat.id, message.message_id)
                    logger.info(f"[{message.chat.title} (ID: {message.chat.id})] - Удалено сообщение от {message.from_user.id} за плохое слово: '{word}'")
                    
                    # Можно добавить предупреждение пользователю
                    bot.send_message(message.chat.id, 
                                     f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>, ваше сообщение удалено за нарушение правил (обнаружено запрещенное слово).",
                                     parse_mode='HTML')
                    break # Удаляем только одно сообщение, если нашли плохое слово

                except telebot.apihelper.ApiTelegramException as e:
                    logger.error(f"Не удалось удалить сообщение: {e}. Возможно, у бота нет прав администратора.")
                except Exception as e:
                    logger.error(f"Неизвестная ошибка при удалении сообщения: {e}")

# --- НОВЫЕ ФУНКЦИИ ДЛЯ ОБРАБОТКИ КОМАНД ИЗ GUI ---

# Функция для безопасного получения ID пользователя из @username или прямого ID
def get_user_id_from_arg(bot_instance, chat_id, arg):
    """
    Пытается получить ID пользователя из аргумента.
    Предпочтительно использовать прямой ID. Поиск по @username без истории сообщений сложен.
    """
    if arg.startswith('@'):
        logger.warning(f"Получен username '{arg}'. Для административных действий (бан/мут) надежнее использовать прямой ID пользователя.")
        # Если вы хотите реализовать поиск по username, это потребует дополнительных запросов
        # или использования кэша пользователей. Для простоты, пока что вернем None.
        return None 
    else:
        try:
            return int(arg)
        except ValueError:
            logger.error(f"Некорректный ID пользователя в аргументе: {arg}")
            return None

def process_gui_command(command_str, bot_instance):
    """Обрабатывает команды, полученные из GUI."""
    logger.info(f"Получена команда из GUI: {command_str}")
    try:
        parts = command_str.split(' ', 3) # Разбиваем на 4 части: команда, цель, длительность, причина
        cmd = parts[0]

        # Специальная команда для отправки произвольного сообщения из GUI
        if cmd == "/send_message_to_main_chat":
            message_text = " ".join(parts[1:]) if len(parts) > 1 else ""
            if message_text:
                bot_instance.send_message(MAIN_CHAT_ID, message_text, parse_mode='HTML')
                logger.info(f"GUI: Отправлено сообщение в чат {MAIN_CHAT_ID}: \"{message_text}\"")
            else:
                logger.warning("GUI: Попытка отправить пустое сообщение в чат.")
            return # Выходим, так как это не команда администрирования пользователя

        # Далее идут команды, требующие user_id
        target_arg = parts[1] if len(parts) > 1 else None
        user_id = get_user_id_from_arg(bot_instance, MAIN_CHAT_ID, target_arg) if target_arg else None
        
        if not user_id:
            logger.error(f"Не удалось получить корректный ID пользователя для команды из GUI: {command_str}")
            return

        if cmd == "/ban_id":
            reason = parts[2] if len(parts) > 2 else "Без причины"
            bot_instance.ban_chat_member(MAIN_CHAT_ID, user_id)
            logger.info(f"GUI: Пользователь {user_id} забанен в чате {MAIN_CHAT_ID}. Причина: {reason}")
            if SEND_GUI_CONFIRMATIONS_TO_CHAT: # <<< НОВОЕ УСЛОВИЕ
                bot_instance.send_message(MAIN_CHAT_ID, f"Пользователь <a href='tg://user?id={user_id}'>{user_id}</a> забанен через GUI. Причина: {reason}", parse_mode='HTML')

        elif cmd == "/mute":
            duration_minutes = 0
            if len(parts) > 2:
                try:
                    duration_int = int(parts[2])
                    if duration_int <= 0: # Мут должен быть хотя бы на 1 минуту, или 0 для бессрочного
                        logger.warning(f"GUI: Длительность мута должна быть положительным числом, получено '{parts[2]}'. Установлено 1 минута.")
                        duration_minutes = 1
                    else:
                        duration_minutes = duration_int
                except ValueError:
                    logger.warning(f"GUI: Некорректная длительность мута '{parts[2]}'. Установлено 60 минут по умолчанию.")
                    duration_minutes = 60 # Значение по умолчанию
            else:
                duration_minutes = 60 # Значение по умолчанию, если длительность не указана

            reason = parts[3] if len(parts) > 3 else "Без причины"
            
            until_date = int(time.time() + duration_minutes * 60) if duration_minutes > 0 else 0
            bot_instance.restrict_chat_member(MAIN_CHAT_ID, user_id, can_send_messages=False, until_date=until_date)
            
            # Сохранение мута в bot_data
            bot_data["mutes"][str(user_id)] = {
                "end_time": (datetime.datetime.now() + datetime.timedelta(minutes=duration_minutes)).isoformat(),
                "reason": reason,
                "admin_id": "GUI" # Указываем, что мут был через GUI
            }
            save_data(bot_data)

            logger.info(f"GUI: Пользователь {user_id} замучен на {duration_minutes} минут. Причина: {reason}")
            if SEND_GUI_CONFIRMATIONS_TO_CHAT: # <<< НОВОЕ УСЛОВИЕ
                bot_instance.send_message(MAIN_CHAT_ID, f"Пользователь <a href='tg://user?id={user_id}'>{user_id}</a> замучен на {duration_minutes} минут через GUI. Причина: {reason}", parse_mode='HTML')

        elif cmd == "/unban_id":
            bot_instance.unban_chat_member(MAIN_CHAT_ID, user_id)
            logger.info(f"GUI: Пользователь {user_id} разбанен в чате {MAIN_CHAT_ID}.")
            if SEND_GUI_CONFIRMATIONS_TO_CHAT: # <<< НОВОЕ УСЛОВИЕ
                bot_instance.send_message(MAIN_CHAT_ID, f"Пользователь <a href='tg://user?id={user_id}'>{user_id}</a> разбанен через GUI.", parse_mode='HTML')
            
        elif cmd == "/unmute":
            bot_instance.restrict_chat_member(MAIN_CHAT_ID, user_id, can_send_messages=True, can_add_web_page_previews=True,
                                              can_send_media_messages=True, can_send_other_messages=True)
            if str(user_id) in bot_data["mutes"]:
                bot_data["mutes"].pop(str(user_id))
                save_data(bot_data)
            logger.info(f"GUI: Пользователь {user_id} размучен в чате {MAIN_CHAT_ID}.")
            if SEND_GUI_CONFIRMATIONS_TO_CHAT: # <<< НОВОЕ УСЛОВИЕ
                bot_instance.send_message(MAIN_CHAT_ID, f"Пользователь <a href='tg://user?id={user_id}'>{user_id}</a> размучен через GUI.", parse_mode='HTML')
        else:
            logger.warning(f"GUI: Неизвестная команда: {command_str}")

    except telebot.apihelper.ApiTelegramException as e:
        logger.error(f"GUI: Ошибка Telegram API при выполнении команды '{command_str}': {e}", exc_info=True)
        # Отправляем сообщение об ошибке только в логи и GUI, не в чат
        # bot_instance.send_message(MAIN_CHAT_ID, f"Ошибка выполнения команды из GUI для Telegram API: {e}", parse_mode='HTML')
    except Exception as e:
        logger.error(f"GUI: Неизвестная ошибка при выполнении команды '{command_str}': {e}", exc_info=True)

# --- Функция, которая слушает команды от GUI ---
def gui_command_listener_thread(command_queue, bot_instance):
    logger.info("GUI command listener thread started.")
    while True:
        try:
            # Получаем команду из очереди с таймаутом, чтобы поток мог завершиться
            command = command_queue.get(timeout=1) 
            if command == "SHUTDOWN":
                logger.info("GUI command listener received SHUTDOWN command. Exiting.")
                break
            process_gui_command(command, bot_instance)
        except Exception as e:
            # Если очередь пуста (таймаут), просто продолжаем
            # Другие ошибки будут залогированы
            pass

# --- Функция, которая запускает весь основной код бота ---
# Эта функция будет вызвана из gui_app.py как отдельный процесс
def run_main_bot_process(command_queue):
    global bot # Убеждаемся, что бот доступен в этом процессе
    
    logger.info("Бот-процесс запущен из GUI.")

    # Запускаем слушателя команд GUI в отдельном ПОТОКЕ
    listener_thread = threading.Thread(target=gui_command_listener_thread, args=(command_queue, bot))
    listener_thread.daemon = True # Поток завершится, когда завершится основной процесс бота
    listener_thread.start()

    # Запускаем проверку мутов в отдельном потоке
    def mute_checker_loop():
        while True:
            try:
                check_mutes()
            except Exception as e:
                logger.error(f"Ошибка в потоке проверки мутов: {e}")
            time.sleep(30 * 60) # Проверяем каждые 30 минут

    mute_thread = threading.Thread(target=mute_checker_loop)
    mute_thread.daemon = True
    mute_thread.start()

    try:
        logger.info("Бот запущен и готов к работе!")
        logger.info("Бот запускается...")
        bot.polling(none_stop=True, interval=2, timeout=20)
    except Exception as e:
        logger.error(f"Произошла критическая ошибка бота: {e}", exc_info=True)
    finally:
        logger.info("Бот остановлен.")
        
# Точка входа для скрипта, если он запускается напрямую (для отладки)
if __name__ == '__main__':
    logger.warning("main.py запущен напрямую. Функции GUI будут недоступны без gui_app.py.")
    # При прямом запуске, очередь не будет использоваться
    # Создаем фиктивную очередь для совместимости, но она не будет принимать команды из GUI
    dummy_queue = Queue() 
    run_main_bot_process(dummy_queue)