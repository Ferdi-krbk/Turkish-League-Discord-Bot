import os
import urllib.request
import asyncio
import time

class LogoManager:
    def __init__(self, base_path="data/assets"):
        self.logos_path = os.path.join(base_path, "logos")
        self.players_path = os.path.join(base_path, "players")
        os.makedirs(self.logos_path, exist_ok=True)
        os.makedirs(self.players_path, exist_ok=True)
        
        # Mapping for GitHub Repo (Turkey folder)
        self.GITHUB_MAP = {
            "GALATASARAY": "Galatasaray",
            "FENERBAHÇE": "Fenerbahce",
            "FENERBAHCE": "Fenerbahce",
            "BEŞİKTAŞ": "Besiktas JK",
            "BESIKTAS": "Besiktas JK",
            "TRABZONSPOR": "Trabzonspor",
            "BAŞAKŞEHİR": "Basaksehir FK",
            "BASAKSEHIR": "Basaksehir FK",
            "KASIMPAŞA": "Kasimpasa",
            "KAYSERİSPOR": "Kayserispor",
            "KONYASPOR": "Konyaspor",
            "ANTALYASPOR": "Antalyaspor",
            "ALANYASPOR": "Alanyaspor",
            "GAZİANTEP FK": "Gaziantep FK",
            "SAMSUNSPOR": "Samsunspor",
            "GÖZTEPE": "Goztepe",
            "KOCAELİSPOR": "Kocaelispor",
            "KOCAELISPOR": "Kocaelispor",
            "EYÜPSPOR": "Eyüpspor",
            "SAKARYASPOR": "Sakaryaspor",
            "AMEDSPOR": "Amedspor",
            "ERZURUMSPOR": "Erzurumspor",
            "EROKSPOR": "Erokspor"
        }

    def _sync_download(self, url, dest_path):
        try:
            # Escape spaces in URL
            url = url.replace(" ", "%20")
            opener = urllib.request.build_opener()
            opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
            with opener.open(url, timeout=10) as response:
                content = response.read()
                if len(content) > 500:
                    with open(dest_path, "wb") as f:
                        f.write(content)
                    return dest_path
        except: pass
        return None

    async def get_team_logo(self, team_name):
        clean_name = team_name.strip().upper()
        # Map some common variations
        if "AMED" in clean_name: clean_name = "AMEDSPOR"
        if "EROK" in clean_name: clean_name = "EROKSPOR"
        
        file_path = os.path.join(self.logos_path, f"{clean_name}.png")
        
        if os.path.exists(file_path) and os.path.getsize(file_path) > 1000:
            return file_path
            
        # Try GitHub Fallback
        git_name = self.GITHUB_MAP.get(clean_name)
        if git_name:
            # New Path: Türkiye - Süper Lig
            url = f"https://raw.githubusercontent.com/luukhopman/football-logos/master/logos/T%C3%BCrkiye%20-%20S%C3%BCper%20Lig/{git_name}.png"
            res = await asyncio.to_thread(self._sync_download, url, file_path)
            if res: return res
            
        return None

    async def get_league_logo(self):
        file_path = os.path.join(self.logos_path, "SUPER_LIG.png")
        if os.path.exists(file_path) and os.path.getsize(file_path) > 1000: return file_path
        url = "https://raw.githubusercontent.com/luukhopman/football-logos/master/logos/Turkey/Super-Lig.png"
        return await asyncio.to_thread(self._sync_download, url, file_path)

    async def download_bulk_logos(self):
        print("Starting GITHUB logo rescue...")
        for name in self.GITHUB_MAP.keys():
            print(f"Fetching {name}...")
            await self.get_team_logo(name)
        await self.get_league_logo()
        print("Bulk download complete.")
