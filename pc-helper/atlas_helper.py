"""ATLAS PC helper: lets ATLAS Live control this Windows PC by voice, safely.

A web page cannot touch the desktop, so this small program runs on the PC and listens only on
127.0.0.1 (never the network). The ATLAS web app sends it typed actions such as "open_app" or
"media"; there is no shell, no file deletion, no shutdown and no installing.

- Pairing: the program shows a 6-digit code; typing it into ATLAS (Live -> PC) gives that browser a
  random token. Every action needs the token, from the ATLAS site's origin, to 127.0.0.1.
- Allow prompts: actions that type, press keys or close windows open a Windows "Allow?" box on this
  PC first. Nothing happens unless you click Yes. No answer in 60 seconds counts as No.
- Every action is printed in this window. Close the window to stop ATLAS controlling the PC.

Python 3.9+ standard library only. Run: python atlas_helper.py  (or the AtlasHelper.exe build).
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import quote_plus, urlsplit

VERSION = '1.0.0'
PORT = 47823
# Only the ATLAS site itself. Deploy previews are left out on purpose: anyone can open a pull request
# on the public repository and get a preview of their own code on a *--atlas-os-sm.netlify.app address.
# Another address (a local preview) can be added with --allow-origin.
ORIGIN_RE = re.compile(r'^https://atlas-os-sm\.netlify\.app$')
CODE_TTL = 10 * 60
MAX_CODE_TRIES = 5
MAX_BODY = 16 * 1024
CONFIRM_SECONDS = 60
ACTIONS_PER_MINUTE = 40
IS_WINDOWS = sys.platform == 'win32'


class ActionError(Exception):
    """An action that was refused or failed; the message is safe to show and speak."""


# ------------------------------------------------------------------ the PC (Windows)

# Apps that would give a model a way around the typed actions are never opened.
BLOCKED_APP = re.compile(r'powershell|pwsh|command prompt|\bcmd\b|terminal|regedit|registry|windows script|'
                         r'\bwsl\b|ubuntu|\bbash\b|uninstall|\brun\b|python|node\.js|git cmd|developer command|'
                         r'mshta|cscript|wscript|recovery|reset this pc', re.I)

# When Windows cannot list the Start menu, these still open (App Paths finds most of them).
FALLBACK_APPS = {
    'notepad': 'notepad.exe', 'calculator': 'calc.exe', 'paint': 'mspaint.exe', 'file explorer': 'explorer.exe',
    'task manager': 'taskmgr.exe', 'settings': 'ms-settings:', 'google chrome': 'chrome.exe', 'microsoft edge': 'msedge.exe',
    'word': 'winword.exe', 'excel': 'excel.exe', 'powerpoint': 'powerpnt.exe', 'microsoft store': 'ms-windows-store:',
    'camera': 'microsoft.windows.camera:', 'snipping tool': 'ms-screenclip:', 'spotify': 'spotify:', 'whatsapp': 'whatsapp:',
}
APP_ALIASES = {'chrome': 'google chrome', 'edge': 'microsoft edge', 'explorer': 'file explorer', 'files': 'file explorer',
               'calc': 'calculator', 'vs code': 'visual studio code', 'vscode': 'visual studio code', 'store': 'microsoft store'}

MEDIA_KEYS = {'play_pause': 0xB3, 'next': 0xB0, 'previous': 0xB1, 'stop': 0xB2, 'mute': 0xAD, 'volume_down': 0xAE, 'volume_up': 0xAF}

VK = {**{chr(c): c for c in range(0x41, 0x5B)}, **{str(d): 0x30 + d for d in range(10)},
      **{'f' + str(n): 0x6F + n for n in range(1, 13)},
      'ctrl': 0x11, 'alt': 0x12, 'shift': 0x10, 'win': 0x5B, 'enter': 0x0D, 'esc': 0x1B, 'tab': 0x09, 'space': 0x20,
      'backspace': 0x08, 'delete': 0x2E, 'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22, 'up': 0x26,
      'down': 0x28, 'left': 0x25, 'right': 0x27, 'plus': 0xBB, 'minus': 0xBD, 'printscreen': 0x2C}
VK.update({k.lower(): v for k, v in list(VK.items()) if len(k) == 1})
EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2E, 0x5B}
KEY_NAMES = {'control': 'ctrl', 'escape': 'esc', 'return': 'enter', 'windows': 'win', 'super': 'win', 'del': 'delete',
             'pgup': 'pageup', 'pgdn': 'pagedown', 'page_up': 'pageup', 'page_down': 'pagedown', 'arrowup': 'up',
             'arrowdown': 'down', 'arrowleft': 'left', 'arrowright': 'right', '+': 'plus', '-': 'minus'}
# Harmless shortcuts run without an Allow prompt; any other combination asks first.
SAFE_COMBOS = {('alt', 'tab'), ('win', 'd'), ('win',), ('esc',), ('pageup',), ('pagedown',), ('up',), ('down',), ('left',),
               ('right',), ('space',), ('f11',), ('ctrl', 'plus'), ('ctrl', 'minus'), ('ctrl', '0'), ('win', 'up'),
               ('win', 'down'), ('ctrl', 'c'), ('home',), ('end',)}
# The Run box, the power-user menu and the lock-screen menu lead around the typed actions.
BLOCKED_COMBOS = {('win', 'r'), ('win', 'x'), ('ctrl', 'alt', 'delete'), ('ctrl', 'shift', 'esc'), ('win', 'l')}

SAFE_OPEN = {'.txt', '.md', '.pdf', '.rtf', '.csv', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods',
             '.odp', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.heic', '.svg', '.mp3', '.wav', '.m4a', '.flac',
             '.aac', '.ogg', '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.webm', '.epub', '.json', '.log'}
USER_FOLDERS = ('Desktop', 'Documents', 'Downloads', 'Pictures', 'Music', 'Videos')


class WindowsPC:
    """The real computer. Only the typed operations below exist."""

    def __init__(self):
        self._apps: list[tuple[str, str]] | None = None
        self._apps_at = 0.0
        if IS_WINDOWS:
            import ctypes
            from ctypes import wintypes
            self.ctypes = ctypes
            self.user32 = ctypes.WinDLL('user32', use_last_error=True)
            self.kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            self.user32.GetForegroundWindow.restype = wintypes.HWND
            for fn in ('SetForegroundWindow', 'IsWindow', 'IsIconic'):
                getattr(self.user32, fn).argtypes = [wintypes.HWND]
            self.user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

            class KEYBDINPUT(ctypes.Structure):
                _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD),
                            ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]

            class MOUSEINPUT(ctypes.Structure):  # only here so the union has Windows' full size
                _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD),
                            ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]

            class _U(ctypes.Union):
                _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT)]

            class INPUT(ctypes.Structure):
                _fields_ = [('type', wintypes.DWORD), ('u', _U)]
            self.INPUT, self.KEYBDINPUT = INPUT, KEYBDINPUT
            self.user32.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]

    def home(self) -> Path:
        return Path.home()

    # -- apps
    def apps(self) -> list[tuple[str, str]]:
        """(name, launch target) for every app in the Start menu, shells left out."""
        if self._apps is not None and time.time() - self._apps_at < 600:
            return self._apps
        found: list[tuple[str, str]] = []
        if IS_WINDOWS:
            # A fixed command with no user input: Windows' own list of Start menu apps, Store apps included.
            cmd = ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                   '[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress']
            try:
                out = subprocess.run(cmd, capture_output=True, timeout=30, creationflags=0x08000000, check=False).stdout  # noqa: S603
                rows = json.loads(out.decode('utf-8', 'replace') or '[]')
                rows = rows if isinstance(rows, list) else [rows]
                found = [(str(r.get('Name', '')), 'shell:AppsFolder\\' + str(r.get('AppID', ''))) for r in rows if r.get('Name') and r.get('AppID')]
            except (OSError, ValueError, subprocess.SubprocessError):
                found = []
        names = {n.lower() for n, _ in found}
        found += [(n.title(), t) for n, t in FALLBACK_APPS.items() if n not in names and (IS_WINDOWS or not found)]
        self._apps = [(n, t) for n, t in found if not BLOCKED_APP.search(n) and not BLOCKED_APP.search(t)]
        self._apps_at = time.time()
        return self._apps

    def launch(self, target: str) -> None:
        if not IS_WINDOWS:
            raise ActionError('Opening apps works on Windows only.')
        if target.startswith('shell:AppsFolder\\'):
            subprocess.Popen(['explorer.exe', target])  # noqa: S603,S607 - fixed program, AppID from Windows' own list
        else:
            os.startfile(target)  # noqa: S606 - targets come from FALLBACK_APPS or checked paths only

    def open_url(self, url: str) -> None:
        webbrowser.open(url, new=2)

    # -- keyboard
    def press(self, keys: list[str]) -> None:
        if not IS_WINDOWS:
            raise ActionError('Pressing keys works on Windows only.')
        codes = [VK[k] for k in keys]
        ext = lambda c: 1 if c in EXTENDED else 0  # noqa: E731 - KEYEVENTF_EXTENDEDKEY for arrows and similar keys
        self._send([(c, 0, ext(c)) for c in codes] + [(c, 0, ext(c) | 2) for c in reversed(codes)])  # 2 = KEYEVENTF_KEYUP
        time.sleep(0.05)

    def _send(self, events: list[tuple[int, int, int]]) -> None:
        """Key events (virtual key, scan code, flags) through SendInput, as one uninterrupted batch."""
        arr = (self.INPUT * len(events))()
        for i, (vk, scan, flags) in enumerate(events):
            arr[i].type = 1  # INPUT_KEYBOARD
            arr[i].u.ki = self.KEYBDINPUT(vk, scan, flags, 0, 0)
        if self.user32.SendInput(len(events), arr, self.ctypes.sizeof(self.INPUT)) != len(events):
            raise ActionError('Windows blocked the key presses (an admin window may be in front).')

    def type_text(self, text: str) -> None:
        if not IS_WINDOWS:
            raise ActionError('Typing works on Windows only.')
        for ch in text.replace('\r\n', '\n'):
            if ch == '\n':
                self.press(['enter'])
                continue
            units = self._utf16(ch)
            self._send([(0, u, 4) for u in units] + [(0, u, 4 | 2) for u in units])  # 4 = KEYEVENTF_UNICODE
            time.sleep(0.004)

    @staticmethod
    def _utf16(ch: str) -> list[int]:
        b = ch.encode('utf-16-le')
        return [int.from_bytes(b[i:i + 2], 'little') for i in range(0, len(b), 2)]

    def media(self, key: str, steps: int) -> None:
        if not IS_WINDOWS:
            raise ActionError('Media keys work on Windows only.')
        for _ in range(steps):
            self._send([(MEDIA_KEYS[key], 0, 1), (MEDIA_KEYS[key], 0, 3)])
            time.sleep(0.02)

    def lock(self) -> None:
        if not IS_WINDOWS:
            raise ActionError('Locking works on Windows only.')
        self.user32.LockWorkStation()

    def active_window(self) -> str:
        if not IS_WINDOWS:
            return ''
        hwnd = self.user32.GetForegroundWindow()
        buf = self.ctypes.create_unicode_buffer(512)
        self.user32.GetWindowTextW(hwnd, buf, 512)
        return buf.value

    def front(self) -> int:
        """The window in front, as a handle (0 when there is none)."""
        return int(self.user32.GetForegroundWindow() or 0) if IS_WINDOWS else 0

    def bring_front(self, hwnd: int) -> bool:
        """Puts that exact window in front again (the Allow box took the focus) and says whether it is."""
        if not IS_WINDOWS or not hwnd or not self.user32.IsWindow(hwnd):
            return False
        if self.user32.IsIconic(hwnd):
            self.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        for _ in range(15):
            if self.front() == hwnd:
                return True
            self.user32.SetForegroundWindow(hwnd)
            time.sleep(0.1)
        return self.front() == hwnd

    def battery(self) -> dict | None:
        if not IS_WINDOWS:
            return None
        ctypes = self.ctypes

        class Power(ctypes.Structure):
            _fields_ = [('ac', ctypes.c_ubyte), ('flag', ctypes.c_ubyte), ('percent', ctypes.c_ubyte), ('saver', ctypes.c_ubyte),
                        ('life', ctypes.c_ulong), ('full', ctypes.c_ulong)]
        p = Power()
        if not self.kernel32.GetSystemPowerStatus(ctypes.byref(p)) or p.flag & 128 or p.percent == 255:
            return None
        return {'percent': p.percent, 'charging': p.ac == 1}

    def confirm(self, question: str) -> bool:
        """A Windows Yes/No box on top of everything; No is the default and the answer after 60 s."""
        if not IS_WINDOWS:
            return False
        flags = 0x4 | 0x30 | 0x100 | 0x1000 | 0x10000 | 0x40000  # YESNO, WARNING, DEFBUTTON2, SYSTEMMODAL, SETFOREGROUND, TOPMOST
        box = getattr(self.user32, 'MessageBoxTimeoutW', None)
        if box:
            answer = box(None, question, 'ATLAS wants to act on this PC', flags, 0, CONFIRM_SECONDS * 1000)
        else:
            answer = self.user32.MessageBoxW(None, question, 'ATLAS wants to act on this PC', flags)
        # 6 = Yes, 7 = No, 32000 = no answer in time. Shown in the helper window, so it is clear what happened.
        self.last_answer = {6: 'Yes', 7: 'No', 32000: 'no answer in time'}.get(answer, f'box closed ({answer})')
        return answer == 6


class FakePC(WindowsPC):
    """For tests and demos: records what would happen and touches nothing. --fake on the command line."""

    def __init__(self, home: Path, approve: bool = True):
        super().__init__()
        self._home = home
        self.approve = approve
        self.done: list[tuple] = []
        self.asked: list[str] = []

    def home(self) -> Path:
        return self._home

    def apps(self):
        return [('Notepad', 'notepad.exe'), ('Google Chrome', 'chrome.exe'), ('Spotify', 'shell:AppsFolder\\Spotify'),
                ('Visual Studio Code', 'code.exe'), ('Calculator', 'calc.exe')]

    def launch(self, target):
        self.done.append(('launch', target))

    def open_url(self, url):
        self.done.append(('open_url', url))

    def press(self, keys):
        self.done.append(('press', tuple(keys)))

    def type_text(self, text):
        self.done.append(('type_text', text))

    def media(self, key, steps):
        self.done.append(('media', key, steps))

    def lock(self):
        self.done.append(('lock',))

    def active_window(self):
        return 'Untitled - Notepad'

    front_ok = True

    def front(self):
        return 1

    def bring_front(self, hwnd):
        return self.front_ok and hwnd == 1

    def battery(self):
        return {'percent': 80, 'charging': True}

    def confirm(self, question):
        self.asked.append(question)
        return self.approve


# ------------------------------------------------------------------ actions

@dataclass
class Plan:
    summary: str             # shown in the log, and in the Allow box when ask is set
    run: Callable[[], dict]
    ask: bool = False


def _norm(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()


def _str(args: dict, key: str, limit: int, required: bool = True) -> str:
    v = args.get(key, '')
    if not isinstance(v, str):
        raise ActionError(f'"{key}" must be text.')
    v = v.strip()
    if required and not v:
        raise ActionError(f'"{key}" is missing.')
    if len(v) > limit:
        raise ActionError(f'"{key}" is too long (at most {limit} characters).')
    return v


class Actions:
    """Turns a typed request into a Plan, checking every argument. Unknown names are refused."""

    def __init__(self, pc: WindowsPC):
        self.pc = pc

    def plan(self, name: str, args: dict) -> Plan:
        fn = getattr(self, 'do_' + name, None) if re.fullmatch(r'[a-z_]{2,30}', name or '') else None
        if not fn:
            raise ActionError(f'Unknown action "{name}". ATLAS can: ' + ', '.join(self.names()) + '.')
        if not isinstance(args, dict):
            raise ActionError('Arguments must be an object.')
        return fn(args)

    @classmethod
    def names(cls) -> list[str]:
        return sorted(n[3:] for n in dir(cls) if n.startswith('do_'))

    # -- apps and the web
    def find_app(self, wanted: str) -> tuple[str, str]:
        w = _norm(wanted)
        w = APP_ALIASES.get(w, w)
        if BLOCKED_APP.search(wanted) or BLOCKED_APP.search(w):
            raise ActionError('ATLAS does not open command shells, registry or system recovery tools.')
        best, score = None, 0
        for name, target in self.pc.apps():
            n = _norm(name)
            s = 4 if n == w else 3 if n.startswith(w) else 2 if w in n else 1 if all(p in n for p in w.split()) else 0
            if s > score or (s == score and best and len(name) < len(best[0])):
                best, score = (name, target), s
        if not best or not score:
            close = [n for n, _ in self.pc.apps() if any(p in _norm(n) for p in w.split() if len(p) > 2)][:8]
            raise ActionError(f'No app called "{wanted}" was found in the Start menu.' + (' Similar: ' + ', '.join(close) + '.' if close else ''))
        return best

    def do_open_app(self, args):
        name, target = self.find_app(_str(args, 'name', 80))
        return Plan(f'Open {name}', lambda: (self.pc.launch(target), {'message': f'Opened {name}.'})[1])

    def do_list_apps(self, args):
        f = _norm(_str(args, 'filter', 60, required=False))
        apps = sorted({n for n, _ in self.pc.apps() if not f or f in _norm(n)})
        return Plan('List apps', lambda: {'message': f'{len(apps)} apps.', 'apps': apps[:60]})

    def do_open_url(self, args):
        url = _str(args, 'url', 2000)
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.netloc:
            raise ActionError('Only http and https web addresses can be opened.')
        return Plan(f'Open {url}', lambda: (self.pc.open_url(url), {'message': f'Opened {parts.netloc} in the browser.'})[1])

    def do_web_search(self, args):
        q = _str(args, 'query', 300)
        site = _str(args, 'site', 20, required=False).lower() or 'google'
        urls = {'google': 'https://www.google.com/search?q=', 'youtube': 'https://www.youtube.com/results?search_query=',
                'bing': 'https://www.bing.com/search?q=', 'maps': 'https://www.google.com/maps/search/',
                'wikipedia': 'https://en.wikipedia.org/w/index.php?search='}
        if site not in urls:
            raise ActionError('site must be one of: ' + ', '.join(urls) + '.')
        url = urls[site] + quote_plus(q)
        return Plan(f'Search {site} for "{q}"', lambda: (self.pc.open_url(url), {'message': f'Searched {site} for {q}.'})[1])

    # -- files and folders (inside the user's own folders only; nothing is ever deleted or overwritten)
    def _inside_home(self, raw: str) -> Path:
        home = self.pc.home().resolve()
        p = Path(os.path.expandvars(os.path.expanduser(raw)))
        p = (p if p.is_absolute() else home / p).resolve()
        if p != home and home not in p.parents:
            raise ActionError('ATLAS only opens things inside your own user folder.')
        parts = {x.lower() for x in p.relative_to(home).parts}
        if 'appdata' in parts or any(x.startswith('.') for x in parts):
            raise ActionError('ATLAS does not open app data or hidden folders.')
        return p

    def do_open_folder(self, args):
        raw = _str(args, 'folder', 400)
        named = {f.lower(): f for f in USER_FOLDERS}
        p = self.pc.home() / named[raw.lower()] if raw.lower() in named else self.pc.home() if raw.lower() in ('home', 'user') else self._inside_home(raw)
        if not p.is_dir():
            raise ActionError(f'There is no folder "{raw}".')
        return Plan(f'Open folder {p}', lambda: (self.pc.launch(str(p)), {'message': f'Opened {p.name or p}.'})[1])

    def do_open_file(self, args):
        p = self._inside_home(_str(args, 'path', 400))
        if p.suffix.lower() not in SAFE_OPEN:
            raise ActionError('For safety ATLAS opens documents, pictures, music and videos only, never programs or scripts.')
        if not p.is_file():
            raise ActionError(f'There is no file "{p.name}". Use find_files first.')
        return Plan(f'Open file {p}', lambda: (self.pc.launch(str(p)), {'message': f'Opened {p.name}.'})[1])

    def do_find_files(self, args):
        words = _norm(_str(args, 'query', 100)).split()
        if not words:
            raise ActionError('Say part of the file name.')
        home = self.pc.home()

        def run():
            # Level by level across all the folders, so a big Desktop cannot use up the time before
            # Documents is looked at (seen on a real PC).
            hits, seen, deadline = [], 0, time.time() + 4
            queue = deque((top, 0) for top in [home / f for f in USER_FOLDERS] + sorted(home.glob('OneDrive*')) if top.is_dir())
            while queue and len(hits) < 25 and seen <= 40000 and time.time() < deadline:
                folder, depth = queue.popleft()
                try:
                    entries = list(os.scandir(folder))
                except OSError:
                    continue
                for e in entries:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if depth < 4 and not e.name.startswith('.') and e.name.lower() not in ('appdata', 'node_modules', '$recycle.bin'):
                                queue.append((Path(e.path), depth + 1))
                        else:
                            seen += 1
                            if all(w in _norm(e.name) for w in words):
                                hits.append(e.path)
                    except OSError:
                        continue
            return {'message': f'Found {len(hits)} file(s).', 'files': hits[:25]}
        return Plan(f'Find files named "{" ".join(words)}"', run)

    def do_write_note(self, args):
        title = re.sub(r'[^\w\- ]+', '', _str(args, 'title', 80)).strip() or 'Note'
        text = _str(args, 'text', 20000)
        folder = self.pc.home() / 'Documents' / 'ATLAS Notes'

        def run():
            folder.mkdir(parents=True, exist_ok=True)
            p, n = folder / (title + '.txt'), 1
            while p.exists():  # never overwrite
                n += 1
                p = folder / f'{title} ({n}).txt'
            p.write_text(text + '\n', encoding='utf-8')
            return {'message': f'Saved the note "{p.name}" in Documents\\ATLAS Notes.', 'path': str(p)}
        return Plan(f'Save a note "{title}" in Documents\\ATLAS Notes', run)

    # -- keyboard, media and windows
    def do_media(self, args):
        key = _str(args, 'key', 20)
        if key not in MEDIA_KEYS:
            raise ActionError('key must be one of: ' + ', '.join(MEDIA_KEYS) + '.')
        steps = args.get('steps', 1 if not key.startswith('volume') else 5)
        if not isinstance(steps, int) or isinstance(steps, bool) or not 1 <= steps <= 50:
            raise ActionError('steps must be a whole number from 1 to 50.')
        steps = steps if key.startswith('volume') else 1
        return Plan(f'Media key {key}' + (f' x{steps}' if steps > 1 else ''),
                    lambda: (self.pc.media(key, steps), {'message': key.replace('_', ' ').capitalize() + (f' ({steps * 2}%)' if steps > 1 else '') + '.'})[1])

    @staticmethod
    def parse_keys(raw: str) -> tuple[str, ...]:
        keys = []
        for k in re.split(r'\s*\+\s*(?=.)', raw.strip().lower()):
            k = KEY_NAMES.get(k, k)
            if k not in VK:
                raise ActionError(f'Unknown key "{k}".')
            keys.append(k)
        if not 1 <= len(keys) <= 4:
            raise ActionError('Press one to four keys at once, like "ctrl+s".')
        mods = [k for k in keys if k in ('ctrl', 'alt', 'shift', 'win')]
        return tuple(sorted(mods, key=['ctrl', 'alt', 'shift', 'win'].index) + [k for k in keys if k not in mods])

    def _in_approved_window(self, do: Callable[[], None]) -> Callable[[], None]:
        """The Allow box names the window in front now; after Yes, act on exactly that window or not at all.
        (Seen on a real PC: when the box closed, Windows put a different window in front.)"""
        hwnd, title = self.pc.front(), self.pc.active_window() or 'the active window'

        def run():
            if not self.pc.bring_front(hwnd):
                raise ActionError(f'"{title}" is no longer the window in front, so nothing was done. Click it and ask again.')
            do()
        return run

    def do_press_keys(self, args):
        keys = self.parse_keys(_str(args, 'keys', 40))
        if keys in BLOCKED_COMBOS or set(keys) >= {'ctrl', 'alt', 'delete'}:
            raise ActionError('That shortcut opens system tools, so ATLAS does not press it.')
        label = '+'.join(keys)
        ask = keys not in SAFE_COMBOS
        press = (lambda: self.pc.press(list(keys)))
        press = self._in_approved_window(press) if ask else press
        return Plan(f'Press {label} in "{self.pc.active_window() or "the active window"}"',
                    lambda: (press(), {'message': f'Pressed {label}.'})[1], ask=ask)

    def do_type_text(self, args):
        text = _str(args, 'text', 2000)
        shown = text if len(text) <= 400 else text[:400] + '…'
        typing = self._in_approved_window(lambda: self.pc.type_text(text))
        return Plan(f'Type into "{self.pc.active_window() or "the active window"}":\n\n{shown}',
                    lambda: (typing(), {'message': f'Typed {len(text)} characters.'})[1], ask=True)

    def do_window(self, args):
        acts = {'show_desktop': ('win', 'd'), 'switch': ('alt', 'tab'), 'maximize': ('win', 'up'), 'minimize': ('win', 'down'),
                'close': ('alt', 'f4'), 'snap_left': ('win', 'left'), 'snap_right': ('win', 'right'), 'fullscreen': ('f11',)}
        a = _str(args, 'action', 20)
        if a not in acts:
            raise ActionError('action must be one of: ' + ', '.join(acts) + '.')
        title = self.pc.active_window() or 'the active window'
        press = (lambda: self.pc.press(list(acts[a])))
        press = self._in_approved_window(press) if a == 'close' else press
        return Plan(('Close' if a == 'close' else a.replace('_', ' ').capitalize()) + f' "{title}"',
                    lambda: (press(), {'message': a.replace('_', ' ').capitalize() + ' done.'})[1], ask=a == 'close')

    def do_lock_pc(self, args):
        return Plan('Lock the PC', lambda: (self.pc.lock(), {'message': 'Locked the PC.'})[1])

    def do_system_info(self, args):
        def run():
            info = {'time': time.strftime('%A %d %B %Y, %H:%M'), 'computer': socket.gethostname(),
                    'active_window': self.pc.active_window()}
            try:
                du = shutil.disk_usage(self.pc.home().anchor or '/')
                info['disk_free_gb'] = round(du.free / 1e9, 1)
            except OSError:
                pass
            b = self.pc.battery()
            if b:
                info['battery'] = b
            return {'message': 'System info.', **info}
        return Plan('Read the time, battery and free disk space', run)


# ------------------------------------------------------------------ pairing and the local server

@dataclass
class Helper:
    pc: WindowsPC
    config_path: Path
    extra_origins: set = field(default_factory=set)
    say: Callable[[str], None] = print
    code: str = ''
    code_until: float = 0
    tries: int = 0
    recent: list = field(default_factory=list)

    def __post_init__(self):
        self.actions = Actions(self.pc)
        self.lock = threading.Lock()
        self.confirm_lock = threading.Lock()
        try:
            self.config = json.loads(self.config_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.config = {}
        self.config.setdefault('tokens', [])

    def save(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.config, indent=1), encoding='utf-8')
        os.replace(tmp, self.config_path)

    def new_code(self) -> str:
        with self.lock:
            self.code = f'{secrets.randbelow(10 ** 6):06d}'
            self.code_until = time.time() + CODE_TTL
            self.tries = 0
        self.say(f'\n  Pairing code: {self.code[:3]} {self.code[3:]}   (works for 10 minutes, once)\n'
                 '  In ATLAS open Live, tap "PC", and type this code.\n')
        return self.code

    def origin_ok(self, origin: str) -> bool:
        return bool(origin) and (bool(ORIGIN_RE.match(origin)) or origin in self.extra_origins)

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def pair(self, code: str, origin: str) -> dict:
        with self.lock:
            if not self.code or time.time() > self.code_until:
                raise ActionError('The pairing code has expired. Press P and Enter in the ATLAS helper window for a new one.')
            if not hmac.compare_digest(re.sub(r'\D', '', str(code)), self.code):
                self.tries += 1
                if self.tries >= MAX_CODE_TRIES:
                    self.code = ''
                    raise ActionError('Too many wrong codes. Press P and Enter in the ATLAS helper window for a new one.')
                raise ActionError('That code is not right. Check the number in the ATLAS helper window.')
            self.code = ''
            token = secrets.token_urlsafe(32)
            self.config['tokens'].append({'hash': self._hash(token), 'origin': origin, 'since': time.strftime('%Y-%m-%d %H:%M')})
            self.save()
        self.say(f'  Paired with ATLAS at {origin}.')
        return {'token': token, 'computer': socket.gethostname(), 'version': VERSION}

    def token_ok(self, auth: str, origin: str) -> bool:
        token = auth[7:] if auth.startswith('Bearer ') else ''
        h = self._hash(token)
        return bool(token) and any(hmac.compare_digest(t['hash'], h) and t['origin'] == origin for t in self.config['tokens'])

    def unpair(self, auth: str = '', everyone: bool = False):
        with self.lock:
            h = self._hash(auth[7:])
            self.config['tokens'] = [] if everyone else [t for t in self.config['tokens'] if t['hash'] != h]
            self.save()

    def run(self, name: str, args: dict) -> dict:
        now = time.time()
        self.recent = [t for t in self.recent if now - t < 60] + [now]
        if len(self.recent) > ACTIONS_PER_MINUTE:
            raise ActionError('Too many actions in a minute. Wait a little.')
        plan = self.actions.plan(name, args)
        stamp = time.strftime('%H:%M:%S')
        if plan.ask:
            if not self.confirm_lock.acquire(blocking=False):
                raise ActionError('Another Allow box is already open on the PC. Answer that one first.')
            try:
                self.say(f'  [{stamp}] ASKING: {plan.summary}')
                allowed = self.pc.confirm(plan.summary + '\n\nAllow this?')
                self.say(f'  [{stamp}] answer: {getattr(self.pc, "last_answer", "Yes" if allowed else "No")}')
                if not allowed:
                    self.say(f'  [{stamp}] not allowed')
                    return {'ok': False, 'denied': True, 'message': 'Not allowed: the user said No on the PC (or did not answer).'}
            finally:
                self.confirm_lock.release()
        try:
            result = plan.run()
        except ActionError:
            raise
        except Exception as exc:  # the OS refused; say what, never crash the helper
            raise ActionError(f'Windows could not do that: {exc}') from None
        self.say(f'  [{stamp}] {plan.summary.splitlines()[0]} — done')
        return {'ok': True, **result}


def make_handler(helper: Helper):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'ATLAS-helper/' + VERSION
        sys_version = ''

        def log_message(self, *a):  # the helper prints its own short log
            pass

        def _origin(self) -> str:
            return self.headers.get('Origin', '')

        def _checks(self) -> bool:
            # A DNS-rebinding page arrives with its own host name; only the loopback names are served.
            host = self.headers.get('Host', '')
            if host not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
                self._send(421, {'error': 'wrong host'})
                return False
            if not helper.origin_ok(self._origin()):
                self._send(403, {'error': 'Only the ATLAS web app can use this helper.'})
                return False
            return True

        def _send(self, status: int, body: dict):
            data = json.dumps(body).encode()
            self.send_response(status)
            origin = self._origin()
            if helper.origin_ok(origin):
                self.send_header('Access-Control-Allow-Origin', origin)
                self.send_header('Access-Control-Allow-Private-Network', 'true')
                self.send_header('Access-Control-Allow-Local-Network', 'true')
            self.send_header('Vary', 'Origin')
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):  # noqa: N802
            if not self._checks():
                return
            self.send_response(204)
            self.send_header('Access-Control-Allow-Origin', self._origin())
            self.send_header('Access-Control-Allow-Methods', 'GET, POST')
            self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
            self.send_header('Access-Control-Allow-Private-Network', 'true')
            self.send_header('Access-Control-Allow-Local-Network', 'true')
            self.send_header('Access-Control-Max-Age', '600')
            self.send_header('Vary', 'Origin')
            self.send_header('Content-Length', '0')
            self.end_headers()

        def do_GET(self):  # noqa: N802
            if not self._checks():
                return
            if self.path == '/hello':
                self._send(200, {'app': 'atlas-helper', 'version': VERSION, 'windows': IS_WINDOWS,
                                 'paired': helper.token_ok(self.headers.get('Authorization', ''), self._origin())})
                return
            if self.path == '/status':
                if not helper.token_ok(self.headers.get('Authorization', ''), self._origin()):
                    self._send(401, {'error': 'Not paired. Pair again with a new code.'})
                    return
                self._send(200, {'computer': socket.gethostname(), 'version': VERSION, 'windows': IS_WINDOWS, 'actions': Actions.names()})
                return
            self._send(404, {'error': 'not found'})

        def do_POST(self):  # noqa: N802
            if not self._checks():
                return
            if 'application/json' not in self.headers.get('Content-Type', ''):
                self._send(415, {'error': 'JSON only'})
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_BODY:
                self._send(413, {'error': 'too large'})
                return
            try:
                body = json.loads(self.rfile.read(length) or b'{}')
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                self._send(400, {'error': 'bad JSON'})
                return
            auth = self.headers.get('Authorization', '')
            try:
                if self.path == '/pair':
                    self._send(200, helper.pair(body.get('code', ''), self._origin()))
                    return
                if not helper.token_ok(auth, self._origin()):
                    self._send(401, {'error': 'Not paired. Pair again with a new code.'})
                    return
                if self.path == '/action':
                    self._send(200, helper.run(str(body.get('name', '')), body.get('args') or {}))
                elif self.path == '/unpair':
                    helper.unpair(auth)
                    helper.say('  A browser disconnected.')
                    self._send(200, {'ok': True})
                else:
                    self._send(404, {'error': 'not found'})
            except ActionError as exc:
                helper.say(f'  refused: {exc}')
                self._send(200 if self.path == '/action' else 400, {'ok': False, 'error': str(exc), 'message': str(exc)})
    return Handler


def config_file() -> Path:
    base = os.environ.get('APPDATA') if IS_WINDOWS else os.environ.get('XDG_CONFIG_HOME') or str(Path.home() / '.config')
    return Path(base or Path.home()) / 'ATLAS' / 'helper.json'


def serve(helper: Helper, port: int = PORT) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(('127.0.0.1', port), make_handler(helper))
    server.daemon_threads = True
    return server


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='ATLAS PC helper: lets ATLAS Live control this PC, with Allow prompts.')
    ap.add_argument('--port', type=int, default=PORT)
    ap.add_argument('--allow-origin', action='append', default=[], help='another web address allowed to pair (for development)')
    ap.add_argument('--fake', action='store_true', help='touch nothing: print what would happen (tests and demos)')
    ap.add_argument('--fake-deny', action='store_true', help='with --fake: answer No to every Allow box')
    ap.add_argument('--config', help='where paired browsers are remembered')
    ap.add_argument('--no-input', action='store_true', help='do not read commands from this window')
    ap.add_argument('--self-test', action='store_true', help='check this PC can be read, then exit')
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass

    if a.self_test:
        pc = WindowsPC()
        apps = pc.apps()
        print(json.dumps({'version': VERSION, 'windows': IS_WINDOWS, 'apps': len(apps), 'sample': [n for n, _ in apps[:5]],
                          'active_window': pc.active_window(), 'battery': pc.battery()}))
        return 0 if (apps or not IS_WINDOWS) else 1

    pc = FakePC(Path.cwd(), approve=not a.fake_deny) if a.fake else WindowsPC()
    if a.fake:
        def fake_log(kind):
            def wrap(*args):
                print('FAKE ' + kind + ' ' + json.dumps(args), flush=True)
                FakePC.__dict__[kind](pc, *args)
            return wrap
        for kind in ('launch', 'open_url', 'press', 'type_text', 'media', 'lock'):
            setattr(pc, kind, fake_log(kind))
    helper = Helper(pc, Path(a.config) if a.config else config_file(), set(a.allow_origin))
    try:
        server = serve(helper, a.port)
    except OSError:
        print(f'ATLAS helper is already running (port {a.port} is in use). Look for its window.')
        if not a.no_input:
            input('Press Enter to close.')
        return 1
    print(f'ATLAS PC helper {VERSION}' + (' (FAKE: touches nothing)' if a.fake else '') + f' is running on 127.0.0.1:{a.port}.')
    print('  ATLAS Live can now open apps, search, play media and more on this PC.')
    print('  Typing, key presses and closing windows always ask "Allow?" here first.')
    print('  It never deletes files, runs commands, installs or shuts down.')
    print(f'  Paired browsers: {len(helper.config["tokens"])}.  P = new pairing code, U = unpair all, Q = quit.')
    print('  Close this window to stop ATLAS controlling this PC.')
    helper.new_code()
    if not a.fake:
        # Windows takes several seconds to list the Start menu the first time; do it now, not on the first request.
        threading.Thread(target=pc.apps, daemon=True).start()
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        if a.no_input:
            t.join()
        while True:
            cmd = input().strip().lower()
            if cmd == 'p':
                helper.new_code()
            elif cmd == 'u':
                helper.unpair(everyone=True)
                print('  Every browser is unpaired. Pair again with a new code (P).')
            elif cmd == 'q':
                break
    except (KeyboardInterrupt, EOFError):
        pass
    server.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
