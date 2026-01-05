This project has two separate scripts



steamworkshop\_id\_downloader.py

Collects Workshop mod IDs from listing pages.



steamcmd\_downloader.py

Downloads those mods using SteamCMD.



Make sure SteamCMD is downloaded and is in the same folder as the scripts

Make a new account if you are paranoid of using your passwords/cookies



**COOKIES (Optional):**

Some workshop pages are private, NSFW, or requires you to own the game.

The ID scraper works around this by using Steam cookies.

If cookies are missing or invalid, the script will still try without cookies.

Cookies are recommended for private, NSFW, or pages that require ownership of the game.





Log into Steam in your browser

1. Obtain cookies in whatever way you want (Cookie Editor extension makes this easy)
2. Put the cookies onto a file called steam cookie.txt (Supports Netscape and JSON)
3. Place the file next to the scripts



**steamworkshop\_id\_downloader.py:**

1. Run the program



2\. It will ask for a steam workshop url:
Collection

User workshop page

Search results

Favorites



3\. The script will output 0 - output/Game Name - AppID/

Inside the lists folder:

ids.txt (mod IDs)

urls.txt (mod URLs)

ids\_titles.txt (ID + title)



Old runs are archived in:

old runs/YYYY-MM-DD/



**python steamcmd\_downloader.py:**

1. Run the program
2. It will ask for username and password
3. It will ask which game to download for (If you ran steamworkshop\_id\_downloader multiple times with different games)
4. Reads ids.txt
5. Detect already installed mods (If ran previously)
6. Skip mods that are not updated recently
7. Uses Steam ACF files to check install state and last update time
8. Redownload mods that are missing or empty
9. Batch all downloading into one steamCMD run



Mods are stored:

steamcmd/steamapps/workshop/content/AppID/ModID/



If a mod fails or downloads an empty folder, it is written to failed\_ids.txt so the user can retry later





