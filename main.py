#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import curses
import shutil
import subprocess
import locale
from pathlib import Path
import textwrap


class OperationCancelled(Exception):
    """Пользователь отменил операцию."""

# Файл для сохранения последнего посещенного каталога
CD_FILE = os.path.expanduser("~/.tui_fm_last_dir")

# Включаем поддержку локали для корректного отображения Unicode (в том числе кириллицы)
locale.setlocale(locale.LC_ALL, '')

class FileManager:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.current_dir = os.getcwd()
        self.last_dir = self.current_dir # Запоминаем начальную директорию
        self.cursor_pos = 0
        self.offset = 0
        self.files = []
        self.selected_files = set()
        self.show_hidden = False
        self.height, self.width = stdscr.getmaxyx()
        self.max_items = self.height - 5  # Оставляем место для заголовка, строки статуса и подсказок
        curses.curs_set(0)  # Скрываем курсор
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_RED)   # курсор
        curses.init_pair(2, curses.COLOR_RED, -1)                   # директории
        curses.init_pair(3, curses.COLOR_GREEN, -1)                 # исполняемые
        curses.init_pair(4, curses.COLOR_CYAN, curses.COLOR_BLACK)  # символические ссылки
        curses.init_pair(5, curses.COLOR_YELLOW, -1)  # выделенные файлы

        # Для пометок операций
        curses.init_pair(6, curses.COLOR_GREEN, -1)  # copy
        curses.init_pair(7, curses.COLOR_YELLOW, -1) # move
        curses.init_pair(8, curses.COLOR_RED, -1)    # delete

        # Буфер (clipboard) для copy/move старой функциональности
        self.clipboard = []  # список полных путей
        self.clipboard_action = None

        # Новое: action_map хранит для имени файла действие: 'copy'/'move'/'delete'
        self.action_map = {}  # filename -> action

        self.get_files()

    def get_files(self):
        self.files = []
        try:
            if self.show_hidden:
                self.files.extend(sorted(os.listdir(self.current_dir)))
            else:
                self.files.extend(sorted([f for f in os.listdir(self.current_dir) if not f.startswith('.')]))
        except PermissionError:
            self.show_message("Ошибка доступа к директории")
            self.current_dir = os.path.dirname(self.current_dir)
            self.get_files()

    def draw(self):
        self.stdscr.clear()
        self.height, self.width = self.stdscr.getmaxyx()
        self.max_items = self.height - 5

        # Заголовок + информация о буфере
        clipboard_info = ""
        if self.clipboard:
            clipboard_info = f" | Clipboard: {len(self.clipboard)} item(s) [{self.clipboard_action}]"
        header = f" GFD - {self.current_dir} {clipboard_info} "
        try:
            self.stdscr.addstr(0, 0, header[:self.width-1], curses.A_REVERSE)
        except curses.error:
            pass

        # Список файлов
        line = 2
        for i in range(self.offset, min(len(self.files), self.offset + self.max_items)):
            file_name = self.files[i]
            full_path = os.path.join(self.current_dir, file_name)

            # Приписка метки в виде [C]/[M]/[D]
            tag = ""
            if file_name in self.action_map:
                act = self.action_map[file_name]
                tag = " [C]" if act == 'copy' else (" [M]" if act == 'move' else " [D]")

            display_name = (file_name + tag)[:self.width-1]

            # Определяем базовый цвет по типу файла
            if os.path.isdir(full_path) or file_name == "..":
                file_type_attr = curses.color_pair(2)
            elif os.path.islink(full_path):
                file_type_attr = curses.color_pair(4)
            elif os.access(full_path, os.X_OK):
                file_type_attr = curses.color_pair(3)
            else:
                file_type_attr = curses.A_NORMAL

            # Если для файла назначено действие — цвет соответствующей пометки
            if file_name in self.action_map:
                act = self.action_map[file_name]
                if act == 'copy':
                    file_type_attr = curses.color_pair(6)
                elif act == 'move':
                    file_type_attr = curses.color_pair(7)
                elif act == 'delete':
                    file_type_attr = curses.color_pair(8) | curses.A_BOLD

            # Если курсор на строке — используем курсор-атрибут (он имеет приоритет визуально)
            if i == self.cursor_pos:
                attr = curses.color_pair(1)
            elif file_name in self.selected_files:
                attr = curses.color_pair(5)
            else:
                attr = curses.A_NORMAL

            try:
                # Рисуем: если курсор на строке, рисуем с курсор-атрибутом (и текстом display_name)
                if i == self.cursor_pos or file_name in self.selected_files:
                    self.stdscr.addstr(line, 0, display_name.ljust(self.width-1), attr)
                else:
                    self.stdscr.addstr(line, 0, display_name.ljust(self.width-1), file_type_attr)
            except curses.error:
                pass

            line += 1

        # Подсказки больше не рисуются в строке — они доступны в popup по клавише "?"
        self.stdscr.refresh()

    def show_message(self, message):
        # Показываем сообщение в центре; ждём нажатия клавиши
        y, x = self.height // 2, max(0, self.width // 2 - min(len(message), self.width-1) // 2)
        try:
            # Если сообщение многострочное, рисуем построчно
            lines = str(message).splitlines()
            start_y = max(0, self.height // 2 - len(lines) // 2)
            for idx, ln in enumerate(lines):
                self.stdscr.addstr(start_y + idx, max(0, self.width // 2 - min(len(ln), self.width-1) // 2), ln[:self.width-1], curses.A_BOLD)
            self.stdscr.refresh()
            self.stdscr.get_wch()
        except curses.error:
            pass  # если не удалось нарисовать — игнорируем

    def show_help_popup(
                self,
                help_text="←: Вернуться | →: Войти\Запустить \n c: Отметить для копирования \n m: Отметить для перемещения \n d: Отметить для удаления \n p: Применить метки \n x: Очистить буфер \n .: Показать\Скрыть скрытые файлы \n Space: Выбрать файл \n r: Переименовать \n n: Новый файл\папка \n ?: Помощь \n q: Выход ",
                width_ratio=0.6,
                height_ratio=0.4,
                padding=4
            ):
                # Разбираем текст на строки, учитывая переносы \n
                lines = []
                for part in help_text.split("\n"):
                    wrapped = textwrap.wrap(part, max(10, int(self.width * width_ratio) - 2 * padding))
                    if not wrapped:
                        lines.append("")
                    else:
                        lines.extend(wrapped)
            
                # Размер окна с учётом рамки и отступов
                win_h = len(lines) + 2 * padding
                win_w = min(self.width - 4, max(len(ln) for ln in lines) + 2 * padding)
            
                # Позиция окна — центр экрана
                start_y = max(0, (self.height - win_h) // 2)
                start_x = max(0, (self.width - win_w) // 2)
            
                try:
                    win = curses.newwin(win_h, win_w, start_y, start_x)
                    win.box()
            
                    # Отрисовка текста с отступами
                    for idx, ln in enumerate(lines):
                        try:
                            win.addstr(padding - 1 + idx, padding, ln[:win_w - 2 * padding])
                        except curses.error:
                            pass
            
                    win.refresh()
                    try:
                        win.get_wch()
                    except Exception:
                        pass
            
                    # Возврат в основное окно
                    del win
                    self.stdscr.touchwin()
                    self.stdscr.refresh()
            
                except curses.error:
                    self.show_message(help_text)

    def get_input(self, prompt, default='', none_on_cancel=False):
                            win = self.stdscr
                            try:
                                curses.curs_set(1)  # показать курсор на время ввода
                            except curses.error:
                                pass

                            try:
                                maxy, maxx = win.getmaxyx()
                                y = maxy - 1  # рисуем в последней строке
                                buf = list(default)
                                pos = len(buf)

                                def render():
                                    nonlocal maxy, maxx, y
                                    maxy, maxx = win.getmaxyx()
                                    y = maxy - 1
                                    try:
                                        win.move(y, 0)
                                        win.clrtoeol()
                                        display = prompt + ''.join(buf)
                                        if len(display) > maxx - 1:
                                            start = len(display) - (maxx - 1)
                                            disp = display[start:]
                                            cursor_x = len(disp) - (len(buf) - pos)
                                        else:
                                            disp = display
                                            cursor_x = len(prompt) + pos
                                        win.addstr(y, 0, disp)
                                        cursor_x = max(0, min(maxx - 1, cursor_x))
                                        win.move(y, cursor_x)
                                        win.refresh()
                                    except curses.error:
                                        pass

                                while True:
                                    render()
                                    try:
                                        ch = win.get_wch()
                                    except KeyboardInterrupt:
                                        return None if none_on_cancel else ''
                                    except curses.error:
                                        return ''.join(buf)

                                    if isinstance(ch, str):
                                        if ch == '\n' or ch == '\r':
                                            return ''.join(buf)
                                        if ch == '\x1b':
                                            return None if none_on_cancel else ''
                                        if ch in ('\x03', '\x07'):
                                            return None if none_on_cancel else ''
                                        if ch in ('\x08', '\x7f'):
                                            if pos > 0:
                                                del buf[pos - 1]
                                                pos -= 1
                                            continue
                                        if ord(ch) >= 32:
                                            buf[pos:pos] = [ch]
                                            pos += 1
                                        continue

                                    if ch == curses.KEY_LEFT:
                                        if pos > 0:
                                            pos -= 1
                                    elif ch == curses.KEY_RIGHT:
                                        if pos < len(buf):
                                            pos += 1
                                    elif ch == curses.KEY_BACKSPACE:
                                        if pos > 0:
                                            del buf[pos - 1]
                                            pos -= 1
                                    elif ch == curses.KEY_DC:
                                        if pos < len(buf):
                                            del buf[pos]
                                    elif ch == curses.KEY_HOME:
                                        pos = 0
                                    elif ch == curses.KEY_END:
                                        pos = len(buf)
                                    elif ch == curses.KEY_RESIZE:
                                        maxy, maxx = win.getmaxyx()
                                        y = maxy - 1
                                    else:
                                        pass
                            finally:
                                try:
                                    curses.curs_set(0)  # вернуть прежнее состояние (скрыть)
                                except curses.error:
                                    pass

    def handle_input(self):
        key = self.stdscr.get_wch()

        if key == curses.KEY_UP:
            self.cursor_pos = max(0, self.cursor_pos - 1)
            if self.cursor_pos < self.offset:
                self.offset = max(0, self.offset - 1)

        elif key == curses.KEY_DOWN:
            self.cursor_pos = min(len(self.files) - 1, self.cursor_pos + 1)
            if self.cursor_pos >= self.offset + self.max_items:
                self.offset += 1

        elif key == curses.KEY_LEFT:
            self.navigate_back()

        elif key == curses.KEY_RIGHT:
            self.open_selected_item()

        elif key == "q":
            # Сохраняем текущую директорию для cd on exit, только если она изменилась
            if self.current_dir != self.last_dir:
                try:
                    with open(CD_FILE, 'w') as f:
                        f.write(self.current_dir)
                except Exception:
                    pass
            return False # Выходим из цикла

        elif key == " ":
            if self.cursor_pos < len(self.files):
                fname = self.files[self.cursor_pos]
                if fname in self.selected_files:
                    self.selected_files.remove(fname)
                else:
                    self.selected_files.add(fname)

        elif key == ".":
            self.show_hidden = not self.show_hidden
            self.get_files()

        elif key == "r":
            self.rename_item()

        elif key == "c":
            # Если есть пометки — это пометка "copy" для текущего файла
            self.mark_action('copy')

        elif key == "m":
            self.mark_action('move')

        elif key == "d":
            self.mark_action('delete')

        elif key == "p":
            # Если есть пометки — выполняем batch-операции, иначе — старая paste
            if self.action_map:
                self.execute_marked_actions()
            else:
                self.paste_from_clipboard()

        elif key == "x":
            self.clear_clipboard()

        elif key == "n":
            self.create_new_item()

        elif key == "?":
            self.show_help_popup()

        return True

    def open_selected_item(self):
        if self.cursor_pos < len(self.files):
            selected_file = self.files[self.cursor_pos]
            full_path = os.path.join(self.current_dir, selected_file)

            if os.path.isdir(full_path):
                self.change_directory(full_path)
            else:
                self.open_file(full_path)

    def navigate_back(self):
        parent_dir = os.path.dirname(self.current_dir)
        if parent_dir != self.current_dir:  # Проверяем, что мы не в корневой директории
            self.current_dir = parent_dir
            self.cursor_pos = 0
            self.offset = 0
            self.get_files()

    def change_directory(self, path):
        self.current_dir = os.path.abspath(path)
        self.cursor_pos = 0
        self.offset = 0
        self.get_files()

    def open_file(self, full_path):
        try:
            curses.endwin()
            if sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", full_path])
            elif sys.platform == "darwin":  # macOS
                subprocess.Popen(["open", full_path])
            elif sys.platform.startswith("win"):
                os.startfile(full_path)
            else:
                self.show_message("Неизвестная платформа: не знаю, как открыть файл")
            curses.doupdate()
        except Exception as e:
            self.show_message(f"Ошибка при открытии файла: {e}")

    def rename_item(self):
        if self.cursor_pos < len(self.files) and self.files[self.cursor_pos] != "..":
            old_name = self.files[self.cursor_pos]
            new_name = self.get_input(f"Переименовать {old_name} в: ")
            if new_name:
                try:
                    os.rename(os.path.join(self.current_dir, old_name),
                              os.path.join(self.current_dir, new_name))
                    self.get_files()
                except Exception as e:
                    self.show_message(f"Ошибка переименования: {e}")

    # --- Метки операций (новое) ---

    def mark_action(self, action):
        """Установить/снять метку action ('copy'/'move'/'delete') для файла под курсором."""
        if self.cursor_pos < len(self.files):
            fname = self.files[self.cursor_pos]
            if fname == "..":
                return
            prev = self.action_map.get(fname)
            if prev == action:
                # снять метку
                del self.action_map[fname]
            else:
                self.action_map[fname] = action

    def _unique_dest(self, dest_path):
        """Если dest_path существует, возвращает уникальный путь с суффиксом _copy, _copy1, ..."""
        if not os.path.exists(dest_path):
            return dest_path
        base, ext = os.path.splitext(dest_path)
        count = 1
        new_path = f"{base}_copy{ext}"
        while os.path.exists(new_path):
            new_path = f"{base}_copy{count}{ext}"
            count += 1
        return new_path

    def execute_marked_actions(self):
        """Выполнить все пометки: сначала запросить папки назначения для copy/move, затем применить."""
        # Собираем списки
        to_copy = [f for f, a in self.action_map.items() if a == 'copy']
        to_move = [f for f, a in self.action_map.items() if a == 'move']
        to_delete = [f for f, a in self.action_map.items() if a == 'delete']

        if not (to_copy or to_move or to_delete):
            self.show_message("Нет пометок для выполнения")
            return

        # Запрос папок назначения для copy/move (если есть)
        copy_dest = None
        move_dest = None
        if to_copy:
            copy_dest = self.get_input("Папка назначения для COPY (оставьте пустой, чтобы задавать для каждого): ").strip()
            if copy_dest == "":
                copy_dest = None
        if to_move:
            move_dest = self.get_input("Папка назначения для MOVE (оставьте пустой, чтобы задавать для каждого): ").strip()
            if move_dest == "":
                move_dest = None

        errors = []

        # Выполняем copy
        for fname in to_copy:
            src = os.path.join(self.current_dir, fname)
            if not os.path.exists(src):
                errors.append(f"Copy: исходник не найден: {fname}")
                continue

            # определяем dest
            if copy_dest:
                dest = os.path.join(copy_dest, fname)
            else:
                # спрашиваем для файла
                dest_dir = self.get_input(f"Куда копировать {fname}? (папка): ").strip()
                if not dest_dir:
                    errors.append(f"Copy: пропущено для {fname}")
                    continue
                dest = os.path.join(dest_dir, fname)

            # проверка назначения
            if not os.path.isdir(os.path.dirname(dest)):
                errors.append(f"Copy: папка назначения не существует для {fname}: {os.path.dirname(dest)}")
                continue

            # уникализируем имя
            dest = self._unique_dest(dest)

            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dest)
                else:
                    shutil.copy2(src, dest)
            except Exception as e:
                errors.append(f"Copy {fname}: {e}")

        # Выполняем move
        for fname in to_move:
            src = os.path.join(self.current_dir, fname)
            if not os.path.exists(src):
                errors.append(f"Move: исходник не найден: {fname}")
                continue

            if move_dest:
                dest = os.path.join(move_dest, fname)
            else:
                dest_dir = self.get_input(f"Куда переместить {fname}? (папка): ").strip()
                if not dest_dir:
                    errors.append(f"Move: пропущено для {fname}")
                    continue
                dest = os.path.join(dest_dir, fname)

            if not os.path.isdir(os.path.dirname(dest)):
                errors.append(f"Move: папка назначения не существует для {fname}: {os.path.dirname(dest)}")
                continue

            # защита от перемещения в потомка
            try:
                src_real = os.path.realpath(src)
                dest_real = os.path.realpath(dest)
                if dest_real.startswith(src_real + os.sep) or dest_real == src_real:
                    errors.append(f"Move: нельзя переместить {fname} внутрь него самого")
                    continue
            except Exception:
                pass

            dest = self._unique_dest(dest)

            try:
                shutil.move(src, dest)
            except Exception as e:
                errors.append(f"Move {fname}: {e}")

        # Выполняем delete
        for fname in to_delete:
            target = os.path.join(self.current_dir, fname)
            if not os.path.exists(target):
                errors.append(f"Delete: не найден {fname}")
                continue
            try:
                if os.path.isdir(target):
                    shutil.rmtree(target)
                else:
                    os.remove(target)
            except Exception as e:
                errors.append(f"Delete {fname}: {e}")

        # Очистим метки и обновим список
        self.action_map.clear()
        self.get_files()

        if errors:
            self.show_message("Ошибки:\n" + "\n".join(errors))
        else:
            self.show_message("Операции выполнены успешно")

    # --- Конец меток операций ---

    def copy_to_clipboard(self):
        targets = self._get_targets_fullpaths()
        if not targets:
            self.show_message("Нечего копировать")
            return
        self.clipboard = targets.copy()
        self.clipboard_action = 'copy'
        # можно очистить выделение, чтобы избежать повторного добавления
        self.selected_files.clear()

    def cut_to_clipboard(self):
        targets = self._get_targets_fullpaths()
        if not targets:
            self.show_message("Нечего вырезать")
            return
        self.clipboard = targets.copy()
        self.clipboard_action = 'move'
        self.selected_files.clear()

    def clear_clipboard(self):
        self.clipboard = []
        self.clipboard_action = None

    def _get_targets_fullpaths(self):
        """Возвращает список полных путей для текущей селекции или файла под курсором."""
        targets = []
        if self.selected_files:
            for fname in self.selected_files:
                if fname == "..":
                    continue
                targets.append(os.path.join(self.current_dir, fname))
        else:
            if self.cursor_pos < len(self.files):
                fname = self.files[self.cursor_pos]
                if fname != "..":
                    targets.append(os.path.join(self.current_dir, fname))
        return targets

    def paste_from_clipboard(self):
        if not self.clipboard:
            self.show_message("Буфер пуст")
            return

        # Пытаемся вставить все элементы в self.current_dir
        errors = []
        for src in self.clipboard:
            try:
                if not os.path.exists(src):
                    errors.append(f"Исходник не найден: {src}")
                    continue
                name = os.path.basename(src.rstrip(os.sep))
                dest = os.path.join(self.current_dir, name)

                # Защита: если пытаемся переместить директорию в саму себя (или в его потомка)
                if self.clipboard_action == 'move':
                    src_real = os.path.realpath(src)
                    dest_real = os.path.realpath(dest)
                    if dest_real.startswith(src_real + os.sep) or dest_real == src_real:
                        errors.append(f"Нельзя переместить {name} внутрь него самого")
                        continue

                # Получаем уникальное имя, если нужно
                if os.path.exists(dest):
                    dest = self._unique_dest(dest)

                if os.path.isdir(src):
                    # Копирование/перемещения директорий
                    if self.clipboard_action == 'copy':
                        shutil.copytree(src, dest)
                    else:
                        shutil.move(src, dest)
                else:
                    # Файлы: используем copy2 (копирует метаданные) или move
                    if self.clipboard_action == 'copy':
                        shutil.copy2(src, dest)
                    else:
                        shutil.move(src, dest)

            except Exception as e:
                errors.append(f"{os.path.basename(src)}: {e}")

        # После операции обновляем список
        self.get_files()

        # Если операция была перемещение — очищаем буфер
        if self.clipboard_action == 'move':
            self.clear_clipboard()

        if errors:
            self.show_message("Ошибки:\n" + "\n".join(errors))
        else:
            self.show_message("Операция выполнена")

    def copy_items(self):
        # Старый метод заменён на clipboard-поведение. Оставляем для совместимости:
        self.copy_to_clipboard()

    def move_items(self):
        # Старый метод заменён на clipboard-поведение. Оставляем для совместимости:
        self.cut_to_clipboard()

    def delete_items(self):
        targets = self.selected_files if self.selected_files else {self.files[self.cursor_pos]}
        # Преобразуем в корректный список имён (исключая "..")
        targets = [t for t in targets if t != ".."]
        if not targets:
            self.show_message("Нечего удалять")
            return
        confirm = self.get_input(f"Удалить {', '.join(targets)}? (y/n): ")
        if confirm.lower() == 'y':
            for fname in targets:
                file_to_delete = os.path.join(self.current_dir, fname)
                try:
                    if os.path.isdir(file_to_delete):
                        shutil.rmtree(file_to_delete)
                    else:
                        os.remove(file_to_delete)
                    self.get_files()
                except Exception as e:
                    self.show_message(f"Ошибка удаления {fname}: {e}")
            self.selected_files.clear()

    def create_new_item(self):
        name = self.get_input("Имя нового файла/директории: ")
        if name:
            create_type = self.get_input("Файл (f) или директория (d)? ")
            if create_type.lower() == 'f':
                try:
                    open(os.path.join(self.current_dir, name), 'a').close()
                    self.get_files()
                except Exception as e:
                    self.show_message(f"Ошибка создания файла: {e}")
            elif create_type.lower() == 'd':
                try:
                    os.mkdir(os.path.join(self.current_dir, name))
                    self.get_files()
                except Exception as e:
                    self.show_message(f"Ошибка создания директории: {e}")

    def run(self):
        while True:
            self.draw()
            if not self.handle_input():
                break

def main(stdscr):
    fm = FileManager(stdscr)
    fm.run()

if __name__ == "__main__":
    curses.wrapper(main)

