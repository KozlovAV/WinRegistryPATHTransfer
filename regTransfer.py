# -*- coding: utf-8 -*-
import sqlite3
import json
import sys
from pprint import pprint
from asciimatics.widgets import Frame, ListBox, Layout, Divider, Text, \
    Button, TextBox, Widget, MultiColumnListBox, FileBrowser, PopUpDialog
from asciimatics.scene import Scene
from asciimatics.screen import Screen
from asciimatics.exceptions import ResizeScreenError, NextScene, StopApplication

from winregistry import WinRegistry as Reg


class RegistryModel(object):
    def __init__(self):
        # Create a database in RAM
        self._db = sqlite3.connect(':memory:')
        # self._db.row_factory = sqlite3.Row

        # Create the basic contact table.
        self._db.cursor().execute('''
            CREATE TABLE registry(
                id INTEGER PRIMARY KEY,
                branch TEXT,
                value TEXT,
                data TEXT,
                selected TEXT,
                inwindows TEXT,
                win_data)
        ''')
        self._db.commit()

        # Current contact when editing.
        self.current_id = None

    def load_from_file(self, file_name):
        self._db.cursor().execute('''DELETE FROM registry''')
        self._db.commit()

        with open(file_name, encoding='utf8') as json_file:
            data = json.load(json_file)
            self._HKCU = data['HKCU']
            self._HKLM = data['HKLM']
            self._load_from_windows()
            self._populate_values()

    def _load_from_windows(self):
        reg = Reg()
        path = r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
        self._reg_hklm = reg.read_key(path)['values']
        path = r"HKCU\Environment"
        self._reg_hkcu = reg.read_key(path)['values']

    def _populate_values(self):
        res = []
        for id, elem in enumerate(self._HKCU):
            value = elem['value']
            data = elem['data']
            (inwindows, win_data) = self._find_inwindows_registry(value, data, self._reg_hkcu)
            res.append((id, 'HKCU', value, data, ' ', inwindows, win_data))

        for id, elem in enumerate(self._HKLM, start=len(res)):
            value = elem['value']
            data = elem['data']
            (inwindows, win_data) = self._find_inwindows_registry(value, data, self._reg_hklm)
            res.append((id, 'HKLM', value, data, ' ', inwindows, win_data))

        for row in res:
            self._db.cursor().execute('''
            INSERT INTO registry(id, branch, value, data, selected, inwindows, win_data )
            VALUES(:id, :branch, :value, :data, :selected, :inwindows, :win_data )''',
                                      row)
        self._db.commit()

    def _find_inwindows_registry(self, value, data, values):
        res = [x for x in values if x['value'] == value]
        inwindows = ''
        win_data = ''
        if res:
            win_data = res[0]['data']
            inwindows = '*' if win_data == data else 'M'

        return (inwindows, win_data)

    def dump_table(self):
        pprint(list(self._db.cursor().execute(
            "SELECT * from registry").fetchall()))

    def get_summary(self):
        a = self._db.cursor().execute("SELECT id, selected, inwindows, branch, value, data from registry").fetchall()
        res = [(x2, x1) for (x1, *x2) in a]
        return res

    def select(self, id):
        self._db.cursor().execute(
            "UPDATE registry SET selected = CASE WHEN selected = ' ' THEN '*' ELSE ' ' END WHERE id=:id", (str(id)))
        self._db.commit()

    def select_all(self):
        self._db.cursor().execute("UPDATE registry SET selected = '*' ")
        self._db.commit()

    def unselect_all(self):
        self._db.cursor().execute("UPDATE registry SET selected = ' ' ")
        self._db.commit()

    def update_registry(self):
        a = self._db.cursor().execute("SELECT branch, value, data from registry WHERE selected='*'").fetchall()
        reg = Reg()
        success = []
        errors = []
        for (key, value, data) in a:
            _key = ''
            if key == 'HKCU':
                _key = r"HKCU\Environment"
            elif key == 'HKLM':
                _key = r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment"

            try:
                reg.write_value(_key, value, data, 'REG_SZ')
            except WindowsError:
                errors.append(value)
            else:
                success.append(value)

                path = reg.read_value(_key, 'PATH')['data']
                # print(path)
                _path = ';' + path + ';'
                _path = _path.replace(';%' + value + '%;', ';')
                _path = _path + f';%{value}%;'
                path = _path[1:-1:]
                path = path.replace(';;', ';')
                path = path.replace(';;', ';')
                try:
                    reg.write_value(_key, 'PATH', path, 'REG_SZ')
                except WindowsError:
                    errors.append(f'PATH for {value}')

        return (success, errors)


class FileChooseView(Frame):
    def __init__(self, screen, model):
        super(FileChooseView, self).__init__(screen,
                                             height=screen.height,
                                             width=screen.width,
                                             can_scroll=False,
                                             title='Config file'
                                             )

        self._model = model
        layout = Layout([1], fill_frame=True)
        self.add_layout(layout)

        self._fileChoose = FileBrowser(
            Widget.FILL_FRAME,
            root='.',
            on_select=self._ok)
        layout.add_widget(self._fileChoose)

        layout2 = Layout([1, 1, 1, 1])
        self.add_layout(layout2)
        layout2.add_widget(Button("OK", self._ok), 0)
        layout2.add_widget(Button("Cancel", self._cancel), 3)

        self.fix()

    def _ok(self):
        self._model.filename = self._fileChoose.value
        self._model.load_from_file(self._model.filename)
        raise NextScene("Main")

    @staticmethod
    def _cancel():
        raise NextScene("Main")


class ListView(Frame):
    def __init__(self, screen, model):
        super(ListView, self).__init__(screen,
                                       height=screen.height,
                                       width=screen.width,
                                       can_scroll=False,
                                       on_load=self._reload_list,
                                       title='Windows PATH variable transfer '
                                       )
        self._model = model

        self.current_id = 0

        layout = Layout([1], fill_frame=True)
        self.add_layout(layout)

        self._list_view = MultiColumnListBox(
            Widget.FILL_FRAME,
            columns=['<3', '<5', '<10', '<20%', '<100%'],
            options=self._model.get_summary(),
            titles=['S', 'Wind', 'branch', 'value', 'data'],
            name="key values",
            add_scroll_bar=True,
            on_change=self._on_pick,
            on_select=self._select
        )
        layout.add_widget(self._list_view)

        layout2 = Layout([1, 1, 1, 1, 1])
        self.add_layout(layout2)

        layout2.add_widget(Button('Load config', self._load_configfile), 0)
        layout2.add_widget(Button('Select all', self._select_all), 1)
        layout2.add_widget(Button('Update registry', self._update_registry), 2)
        layout2.add_widget(Button('Unselect all', self._unselect_all), 3)
        layout2.add_widget(Button("Quit", self._quit), 4)

        self.fix()

    def _load_configfile(self):
        raise NextScene("SelectConfig")

    def _reload_list(self, new_value=None):
        self._list_view.options = self._model.get_summary()
        self._list_view.value = new_value

    def _select(self):
        self._model.select(self.current_id)
        self._reload_list(new_value=self.current_id)

    def _select_all(self):
        self._model.select_all()
        self._reload_list(new_value=self.current_id)

    def _unselect_all(self):
        self._model.unselect_all()
        self._reload_list(new_value=self.current_id)

    def _on_pick(self):
        self.current_id = self._list_view.value

    def _update_registry(self):
        (success, errors) = self._model.update_registry()

        err_str = ''
        if errors:
            err_str = f'\nERRORS ({len(errors)}) are:\n' + '\n'.join(errors)

        self.scene.add_effect(
            PopUpDialog(self.screen, f'{len(success)} records updated' + err_str, ["OK"])
        )

        self._model.load_from_file(self._model.filename)
        self._reload_list()

    @staticmethod
    def _quit():
        raise StopApplication("User pressed quit")


def demo(screen, scene):
    scenes = [
        Scene([ListView(screen, model)], -1, name="Main"),
        Scene([FileChooseView(screen, model)], -1, name="SelectConfig"),
    ]

    screen.play(scenes, stop_on_resize=True, start_scene=scene, allow_int=True)


model = RegistryModel()
last_scene = None
while True:
    try:
        Screen.wrapper(demo, catch_interrupt=False, arguments=[last_scene])
        sys.exit(0)
    except ResizeScreenError as e:
        last_scene = e.scene
