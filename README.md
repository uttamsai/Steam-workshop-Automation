# Steam Workshop Automation

A set of Python tools to **scrape Steam Workshop mod IDs** and **automatically download mods using SteamCMD**.

This project is designed for **batch archiving, offline use, and automation**, with support for large Workshop collections.

---

## Features

- Scrape Steam Workshop listing pages for mod IDs  
- Supports public and cookie-authenticated pages  
- Automatically detects AppID and game name  
- Organizes output by game and AppID  
- Archives previous runs automatically  
- Downloads mods via SteamCMD  
- Skips already installed and up-to-date mods  
- Detects failed or empty downloads  

---

## Project Files

- `steamworkshop id downloader.py`  
  Scrapes Workshop listing pages and generates organized ID lists.

- `steamcmd automation.py`  
  Uses SteamCMD to download Workshop items in bulk from ID lists.

---

## Requirements

### Software
- **Python 3.10+**
- **SteamCMD**
- **Steam account**

### Python Dependencies
Create a file called `requirements.txt` with:

