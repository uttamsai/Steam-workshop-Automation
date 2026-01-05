# Steam-workshop-Automation# Steam Workshop Automation

This project includes tools to scrape Steam Workshop item IDs and download them using SteamCMD.

## Features

- Scrape Steam Workshop pages for mod IDs
- Save mod IDs to organized folders
- Automate downloading mods via SteamCMD
- Handles existing downloads and skips duplicates

## How to Use

1. Run `steamworkshop_id_downloader.py`
2. Enter a Steam Workshop page URL
3. IDs are saved into `0 - output/<Game - AppID>`
4. Run `steamcmd_automation.py` to download with SteamCMD

## Requirements

- Python 3.10 or later
- `requests` library
- SteamCMD installed and visible in PATH
