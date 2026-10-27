# ATLAS PC helper

A web page cannot control a computer. This small Windows program lets **ATLAS Live** do things on
your PC when you ask: open apps, websites and files, search, play and pause music, change the
volume, type text, press shortcuts and manage windows.

## Use it

1. Download `AtlasHelper.exe` from the latest release:
   https://github.com/SHASHWAT-MISHRA-997/Atlas-OS/releases/latest/download/AtlasHelper.exe
2. Open it. The file is not code-signed, so Windows may say "Windows protected your PC": click
   **More info**, then **Run anyway**. A black window opens and shows a 6-digit pairing code.
3. On the same PC, open ATLAS in Chrome or Edge, go to **Live**, tap **PC**, type the code and press
   **Connect**. If the browser asks to let the site reach devices on your network, click **Allow**.
4. Start Live and talk: "Notepad kholo", "YouTube pe Arijit ke gaane chalao", "volume badhao".

Keep the window open while you use it. Close it to stop ATLAS controlling the PC at once.
In the window: **P** + Enter shows a new pairing code, **U** + Enter unpairs every browser,
**Q** + Enter quits.

Without the .exe: install Python 3.9 or newer and run `py atlas_helper.py`.

## What it can and cannot do

| Action | Asks "Allow?" on the PC first |
|---|---|
| Open an app from the Start menu (`open_app`, `list_apps`) | No |
| Open a website, search Google, YouTube, Bing, Maps or Wikipedia | No |
| Media keys: play/pause, next, previous, mute, volume | No |
| Find files by name in your user folders; open documents, pictures, music, videos; open folders | No |
| Save a new note in Documents\ATLAS Notes (never overwrites) | No |
| Lock the PC; read time, battery and free disk space | No |
| Type text into the window in front | **Yes**, the box shows the text and the window |
| Press a shortcut (except harmless ones like Alt+Tab, Win+D, Page Down) | **Yes** |
| Close the window in front | **Yes** |

It never: deletes or overwrites files, runs commands, opens a command prompt, PowerShell, Terminal
or the registry editor, opens programs or scripts as files (.exe, .bat, .ps1 …), presses Win+R or
Win+X, installs anything, changes settings, or shuts down or restarts. It cannot click the mouse.
An "Allow?" box that is not answered in 60 seconds counts as No.

## How it stays safe

- It listens only on `127.0.0.1:47823`, so other computers on your network cannot reach it.
- Only the ATLAS site (`https://atlas-os-sm.netlify.app`) may talk to it, and only to the names
  `127.0.0.1` / `localhost` (this blocks DNS-rebinding pages).
- A browser must pair once with the code shown in the window (one use, 10 minutes, 5 tries). It
  then gets a random token; the helper stores only a hash of it in `%APPDATA%\ATLAS\helper.json`.
- Every action is a fixed, typed command with checked arguments, and is printed in the window.
- Typing, shortcuts and closing windows need a click on a Windows Yes/No box on the PC itself, so
  even a hijacked web page cannot type into your apps without you seeing it.
- File names found with `find_files`, and the results of actions, go to the AI provider you use
  in Live (Google or OpenAI, or your AI Chat provider), like the rest of the conversation.

## Develop

```
python -m unittest -v test_atlas_helper        # no Windows needed (FakePC)
python atlas_helper.py --fake --allow-origin http://localhost:8888   # touches nothing, prints actions
python atlas_helper.py --self-test             # reads this PC's app list and exits
```

CI builds `AtlasHelper.exe` with PyInstaller on Windows and publishes it as a GitHub release
(`pc-helper-v<version>`) after a merge to `main`, when the version in `atlas_helper.py` is new.
