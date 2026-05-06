"""
Transfer Command Cog for Turkish Super League Bot
FULL MASTERPIECE EDITION: Dynamic personalities, Board advice, Rivalry tax, and Player Sale System.
100% Local Logic for negotiations.
"""

import discord
from discord.ext import commands
import json
import os
import random
import re
from typing import Dict, Optional, List, Any
import asyncio
import aiosqlite
import aiohttp
from datetime import datetime
from bs4 import BeautifulSoup
from core import database
import config
from core import ai
import unicodedata

class TransferCog(commands.Cog):
    """Cog for AI-powered transfer commands"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pending_transfers: Dict[int, Dict] = {}
        self.pending_sales: Dict[int, Dict] = {}
        self.refusal_cache: Dict[str, float] = {} # Key: "user_id:player_name", Value: expiry_timestamp

    def _add_split_fields(self, embed, name, value, inline=False):
        """Splits values > 1024 chars into multiple fields to avoid Discord API errors"""
        if not value: return
        value = str(value)
        if len(value) <= 1024:
            embed.add_field(name=name, value=value, inline=inline)
            return

        chunks = []
        val_to_split = value
        while len(val_to_split) > 1000:
            split_idx = val_to_split.rfind('\n', 0, 1000)
            if split_idx == -1: split_idx = val_to_split.rfind(' ', 0, 1000)
            if split_idx == -1: split_idx = 1000
            chunks.append(val_to_split[:split_idx].strip())
            val_to_split = val_to_split[split_idx:].strip()
        if val_to_split: chunks.append(val_to_split)

        for i, chunk in enumerate(chunks):
            field_name = name if i == 0 else f"{name} (Devam {i})"
            embed.add_field(name=field_name, value=chunk, inline=inline)

    def _turkish_lower(self, s: str) -> str:
        """Turkish-aware lowercase conversion"""
        return s.replace('İ', 'i').replace('I', 'ı').lower()

    def _turkish_upper(self, s: str) -> str:
        """Turkish-aware uppercase conversion"""
        return s.replace('i', 'İ').replace('ı', 'I').upper()

    def _check_refusal(self, user_id: int, player_name: str) -> bool:
        """Checks if a player has recently refused this user (24h cooldown)"""
        key = f"{user_id}:{self._clean_player_name(player_name)}"
        expiry = self.refusal_cache.get(key, 0)
        if datetime.now().timestamp() < expiry:
            return True
        return False

    def _set_refusal(self, user_id: int, player_name: str, hours: int = 24):
        """Sets a refusal cooldown for a player/user pair"""
        key = f"{user_id}:{self._clean_player_name(player_name)}"
        self.refusal_cache[key] = datetime.now().timestamp() + (hours * 3600)

    def _clean_player_name(self, name: str) -> str:
        """Karakterleri normalize eder, aksanları siler ve Türkçeye uyumlu temizlik yapar (v4)"""
        if not name: return ""
        
        # 1. Parantez içindeki notları temizle
        name = re.sub(r'\(.*?\)', '', name).strip()
        
        # 2. Unicode Normalizasyonu (NFKD: Aksanları harften ayırır)
        # Örn: 'é' -> 'e' + '´'
        nfkd_form = unicodedata.normalize('NFKD', name)
        
        # 3. Sadece 'Mark' (Mn: Non-spacing mark) olmayan karakterleri tut (Aksanları sil)
        name = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
        
        # 4. Küçük harfe çevir ve özel durumları düzelt (ı -> i gibi)
        name = name.lower().replace('ı', 'i')
        
        return name.strip()

    def _get_form_emoji(self, rating: Any) -> str:
        """Returns emoji representation of player form"""
        try:
            r = int(rating)
        except:
            r = 0
            
        if r >= 2: return "🔥"
        if r == 1: return "↑"
        if r == -1: return "↓"
        if r <= -2: return "❄️"
        return "→"

    def _parse_money(self, text: str) -> int:
        """Parses money strings like '6M', '500k', '1.5m' to integer. Auto-detects millions for small numbers."""
        text = text.lower().replace(",", ".").replace(" ", "")
        if "m" in text or "milyon" in text:
            text = text.replace("milyon", "").replace("m", "").replace("€", "")
            try: return int(float(text) * 1_000_000)
            except: return 0
        elif "k" in text or "bin" in text or "b" in text:
            text = text.replace("bin", "").replace("k", "").replace("b", "").replace("€", "")
            try: return int(float(text) * 1_000)
            except: return 0
        text = text.replace("€", "")
        try:
            val = float(text)
            if val < 1000: # Smart detection: Assume millions if user types "30" instead of "30M"
                return int(val * 1_000_000)
            return int(val)
        except: return 0

    def _format_value(self, value: Any) -> str:
        """Formats integer to readable money string"""
        try:
            v = int(float(value))
        except:
            return "0 "
            
        if v >= 1_000_000: return f"{v/1_000_000:.1f}M "
        if v >= 1_000: return f"{v/1_000:.0f}K "
        return f"{v} "

    def _normalize_scout_data(self, data: Dict) -> Dict:
        """Ensures all critical keys exist in the scout data dict to prevent KeyError."""
        if not data: data = {}
        # Market Value Synonyms
        mv = data.get('market_value_eur') or data.get('market_value') or data.get('value_eur') or data.get('value') or 0
        try: 
            mv = int(float(str(mv).replace("", "").replace(",", "").strip()))
        except: 
            mv = 5000000 # Default fallback
        
        # Salary: use AI value or estimate from market value (realistic football economics)
        raw_salary = data.get('current_salary_eur') or data.get('salary') or 0
        try:
            raw_salary = int(float(str(raw_salary).replace(",", "").strip()))
        except:
            raw_salary = 0
        
        if raw_salary == 0 and mv > 0:
            # Estimate salary as % of MV (weekly wage * 52 weeks, roughly)
            # Elite (100M+): ~7%, High (50-100M): ~9%, Mid (10-50M): ~11%, Low: ~14%
            if mv >= 100_000_000:
                raw_salary = int(mv * 0.07)
            elif mv >= 50_000_000:
                raw_salary = int(mv * 0.09)
            elif mv >= 10_000_000:
                raw_salary = int(mv * 0.11)
            else:
                raw_salary = int(mv * 0.14)
            
        return {
            "player_name": data.get('player_name') or data.get('name') or "Bilinmeyen Oyuncu",
            "age": data.get('age') or 25,
            "nationality": data.get('nationality') or "Bilinmiyor",
            "market_value_eur": mv,
            "current_team": data.get('current_team') or data.get('team') or "Bilinmiyor",
            "position": str(data.get('position') or data.get('pos') or "ST").upper(),
            "overall": data.get('overall') or data.get('ovr') or 75,
            "personality_type": data.get('personality_type') or "Profesyonel",
            "current_salary_eur": raw_salary,
            "loyalty_level": data.get('loyalty_level') or "Orta",
            "interested_clubs": data.get('interested_clubs') or ["Bilinmiyor"],
            "scout_comment": data.get('scout_comment') or "Hzl ve teknik bir oyuncu.",
            "source": data.get('source', 'AI Research')
        }

    def _parse_tactic_value(self, value_str: str) -> int:
        """Parses value strings from tactics files like '7 M €', '800 Bin €'"""
        return database.parse_market_value(value_str)

    async def _find_team(self, name: str) -> Optional[Dict]:
        return await database.search_team(name)

    async def _query_ai(self, messages: List[Dict], system_instruction: str = "", label: str = "TRANSFER", provider: str = "groq") -> Any:
        # Fallback mechanism: If using Groq/OpenRouter, use English prompt for better reasoning
        user_content = messages[-1]['content']
        system_fallback = system_instruction
        prompt_fallback = user_content

        # Scouting için İngilizce prompt oluştur (Reasoning için daha iyi)
        if "scouting raporu hazırla" in user_content.lower():
            p_name_match = re.search(r"'(.*?)'", user_content)
            p_name = p_name_match.group(1) if p_name_match else "this player"
            system_fallback = "You are a professional football scout. Provide detailed scouting data in English, but the final JSON MUST contain the exact requested keys. Keep 'scout_comment' descriptive."
            prompt_fallback = f"Prepare a detailed scouting report for '{p_name}' as of April 1, 2026. The player is currently 25 years old if data is missing. Return ONLY JSON: {{'player_name': '...', 'age': 25, 'nationality': '...', 'market_value_eur': 15000000, 'current_team': '...', 'position': '...', 'overall': 75, 'current_salary_eur': 2000000, 'interested_clubs': ['...'], 'personality_type': 'Professional', 'loyalty_level': 'Medium', 'scout_comment': 'A quick and technical player...', 'stats': '...'}}"

        return await ai.generate_content(
            prompt=user_content,
            system_instruction=system_instruction,
            is_json=True,
            label=label,
            provider=provider,
            prompt_fallback=prompt_fallback,
            system_fallback=system_fallback
        )

    async def _get_player_photo(self, player_name: str) -> Optional[str]:
        """Attempts to find a real player photo URL from various sources."""
        import urllib.parse
        import random
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        q = urllib.parse.quote(player_name)
        
        async with aiohttp.ClientSession(headers=headers) as session:
            # Source 1: Besoccer
            try:
                async with session.get(f"https://www.besoccer.com/search?q={q}", timeout=5) as resp:
                    if resp.status == 200:
                        soup = BeautifulSoup(await resp.text(), 'html.parser')
                        player_link = soup.find('a', href=re.compile(r'/player/'))
                        if player_link:
                            async with session.get("https://www.besoccer.com" + player_link['href'], timeout=5) as p_resp:
                                if p_resp.status == 200:
                                    p_soup = BeautifulSoup(await p_resp.text(), 'html.parser')
                                    img = p_soup.find('img', {'class': 'main-img'}) or p_soup.find('meta', {'property': 'og:image'})
                                    if img:
                                        src = img.get('src') or img.get('content')
                                        if src and not src.startswith('http'): src = "https://www.besoccer.com" + src
                                        return src
            except: pass

            # Source 2: Wikipedia (Fastest fallback)
            try:
                wp_url = f"https://tr.wikipedia.org/wiki/{q.replace('%20', '_')}"
                async with session.get(wp_url, timeout=4) as resp:
                    if resp.status == 200:
                        soup = BeautifulSoup(await resp.text(), 'html.parser')
                        infobox = soup.find('table', {'class': 'infobox'})
                        if infobox:
                            img = infobox.find('img')
                            if img and img.get('src'):
                                return "https:" + img.get('src')
            except: pass

            # Source 3: DuckDuckGo (Desperate fallback)
            try:
                ddg_url = f"https://duckduckgo.com/html/?q={q}+footballer+profile+photo"
                async with session.get(ddg_url, timeout=5) as resp:
                    if resp.status == 200:
                        soup = BeautifulSoup(await resp.text(), 'html.parser')
                        img = soup.find('img', {'class': 'tile--img__img'})
                        if img and img.get('src'):
                            return "https:" + img.get('src')
            except: pass

        return None

    async def _research_player(self, player_name: str) -> Optional[Dict]:
        # Check cache first
        cached = await database.get_scout_cache(player_name)
        if cached: return cached
        
        # English prompt (Groq/OR understand much better in English)
        en_system = "You are a professional football scout. Return ONLY valid JSON with the exact keys requested."
        en_prompt = f"""Prepare a scouting report for '{player_name}' as of April 1, 2026.
CRITICAL OVR SCALE (BAREM):
- Market Value >= 100M EUR: 91 - 96 OVR
- Market Value 70M - 100M EUR: 88 - 90 OVR
- Market Value 45M - 70M EUR: 84 - 87 OVR
- Market Value 25M - 45M EUR: 79 - 83 OVR
- Market Value 10M - 25M EUR: 74 - 78 OVR
- Other: 65 - 73 OVR

Return ONLY a JSON object: {{"player_name": "...", "age": 25, "nationality": "...", "market_value_eur": 25000000, "current_team": "...", "position": "ST", "overall": 82, "personality_type": "Professional", "current_salary_eur": 3000000, "loyalty_level": "Medium", "interested_clubs": ["Club1"], "scout_comment": "Summary..."}}"""        
        
        # provider='auto' but with local engine DISABLED (prefer_local bypass via English prompt path)
        res_dict = await ai.generate_content(
            prompt=en_prompt,
            system=en_system,
            is_json=True,
            label=f"Scout: {player_name}",
            provider="gemini",
            prompt_fallback=en_prompt,
            system_fallback=en_system
        )
        if not res_dict: return None
        
        info = self._normalize_scout_data(res_dict)
        await database.save_scout_cache(player_name, info)
        return info

    async def _fetch_url_content(self, url: str) -> Optional[str]:
        """Fetches the content of a URL and extracts the main text."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=10) as response:
                    if response.status != 200:
                        return None
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    for script in soup(["script", "style"]):
                        script.decompose()
                    text = soup.get_text()
                    lines = (line.strip() for line in text.splitlines())
                    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                    return "\n".join(chunk for chunk in chunks if chunk)
        except Exception as e:
            print(f"DEBUG: URL fetch error: {e}")
            return None

    async def _research_player_from_url(self, url: str) -> Optional[Dict]:
        """Scrapes player data from a Transfermarkt URL and uses AI to parse it."""
        url = (url or "").strip().rstrip(" \t\r\n,.;)>]}")
        # Check cache first
        cached = await database.get_scout_cache(url)
        if cached: return cached
        
        content = await self._fetch_url_content(url)
        
        # --- DETECT TRANSFERMARKT SCRAPER PROTECTION ---
        # If TM redirects us to the "Ansgar Bothe" dummy profile or similar security check
        is_blocked = not content or "Ansgar Bothe" in content or "Forbidden" in content or "Access Denied" in content
        
        if is_blocked:
            print(f"DEBUG: Transfermarkt blocked scrape for {url}. Falling back to name-based AI research.")
            # Extract name from URL if possible
            fallback_name = None
            try:
                parts = url.split("/")
                for i, part in enumerate(parts):
                    if part == "profil" and i > 0:
                        fallback_name = parts[i-1].replace("-", " ").strip().title()
                        break
            except: pass
            
            if fallback_name:
                return await self._research_player(fallback_name)
            return None

        content = content[:8000]
        
        # Use English prompt for Groq fallback compatibility
        en_system = "You are a professional football scout. Extract player data from this Transfermarkt page and return ONLY valid JSON."
        en_prompt = f"""Extract player info from this Transfermarkt page content. Return ONLY a JSON object:
{{"player_name": "Full Name", "age": 25, "nationality": "Country", "market_value_eur": 25000000, "current_team": "Team", "position": "ST", "overall": 82, "personality_type": "Professional", "current_salary_eur": 3000000, "loyalty_level": "Medium", "interested_clubs": ["Club1"], "stats": "Apps: X, Goals: Y, Assists: Z", "scout_comment": "Detailed analysis..."}}

Page content:
{content}
"""
        res_dict = await ai.generate_content(
            prompt=en_prompt,
            system=en_system,
            is_json=True,
            label="URL Scout Analysis",
            provider="gemini",
            prompt_fallback=en_prompt,
            system_fallback=en_system
        )
        info = self._normalize_scout_data(res_dict)
        if info:
            await database.save_scout_cache(url, info)
        return info

    async def _get_local_player_data(self, player_name: str, team_name: str) -> Optional[Dict]:
        """Reads player data (age, pos, value) from tactics/[team_name].txt"""
        tactic_path = os.path.join(database.BASE_PATH, "data", "tactics", f"{team_name}.txt")
        if not os.path.exists(tactic_path):
            return None
        
        search_name = self._turkish_lower(player_name)
        
        try:
            with open(tactic_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
                for line in lines:
                    line_lower = self._turkish_lower(line)
                    if search_name in line_lower and "|" in line:
                        # Split by pipe and clean parts
                        parts = [p.strip() for p in line.split("|")]
                        
                        # Check for 4-part (Name | Pos | Age | Value) or 3-part (Pos: Name | Age | Value)
                        if len(parts) >= 4:
                            p_full_name = self._clean_player_name(parts[0])
                            p_pos = parts[1].upper()
                            p_age_idx, p_val_idx = 2, 3
                        elif len(parts) == 3:
                            # Handle "Pos: Name | Age | Value"
                            sub_parts = parts[0].split(":")
                            p_full_name = self._clean_player_name(sub_parts[-1])
                            p_pos = sub_parts[0].strip().upper() if len(sub_parts) > 1 else "ST"
                            p_age_idx, p_val_idx = 1, 2
                        else:
                            continue

                        # Case-insensitive name check on cleaned name
                        if search_name in self._turkish_lower(p_full_name):
                            try:
                                # Extract age (first number found)
                                age_match = re.search(r'\d+', parts[p_age_idx])
                                p_age = int(age_match.group()) if age_match else 25
                                p_val = parts[p_val_idx]
                            except:
                                continue

                            return self._normalize_scout_data({
                                "player_name": p_full_name,
                                "position": p_pos,
                                "age": p_age,
                                "market_value_eur": self._parse_tactic_value(p_val),
                                "current_team": team_name,
                                "nationality": "Türkiye",
                                "overall": 75,
                                "personality_type": random.choice(["Profesyonel", "Paracı", "Sadık"]),
                                "current_salary_eur": 0,
                                "loyalty_level": random.choice(["Yüksek", "Orta", "Düşük"]),
                                "interested_clubs": random.sample(["Lyon", "Sevilla", "Lille", "Brighton", "Ajax"], 2),
                                "scout_comment": "Taktik dosyasından alınan güncel veri."
                            })
        except Exception as e:
            print(f"DEBUG: Taktik okuma hatası: {e}")
        return None

    async def _remove_player_from_tactic_file(self, team_name: str, player_name: str) -> bool:
        """Removes a player's roster line from the tactical text file."""
        tactic_path = os.path.join(database.BASE_PATH, "data", "tactics", f"{team_name}.txt")
        if not os.path.exists(tactic_path):
            return False
            
        search_name = self._turkish_lower(player_name)
        new_lines = []
        removed = False
        
        try:
            with open(tactic_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            for line in lines:
                line_lower = self._turkish_lower(line)
                # Check for player name in a roster line (containing |)
                if "|" in line:
                    parts = [p.strip() for p in line.split("|")]
                    if parts and search_name in self._turkish_lower(parts[0]):
                        removed = True
                        print(f"DEBUG: Removing {player_name} from {team_name}.txt")
                        continue
                new_lines.append(line)
            
            if removed:
                with open(tactic_path, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
                return True
        except Exception as e:
            print(f"DEBUG Error: _remove_player_from_tactic_file failed: {e}")
            
        return False


    async def _calculate_dynamic_price(self, base_val: int, age: int, team_name: str) -> int:
        """Applies age and team form multipliers to the base price"""
        # Age Multiplier (±30%)
        age_mult = 1.0
        if age <= 21: age_mult = 1.30    # Young Wonderkid
        elif age <= 28: age_mult = 1.15  # Early Prime
        elif age <= 31: age_mult = 1.0   # Mature
        elif age <= 34: age_mult = 0.8   # Older
        else: age_mult = 0.65           # Veteran
        
        # Form Multiplier (±20%)
        form_mult = 1.0
        streak = await database.get_team_form_streak(team_name)
        if streak:
            streak = streak.upper()
            wins = streak.count('W')
            losses = streak.count('L')
            form_mult += (wins * 0.04)   # +4% per win
            form_mult -= (losses * 0.04) # -4% per loss
            form_mult = max(0.8, min(1.2, form_mult))
            
        return int(base_val * age_mult * form_mult)

    # ===============================================
    #  MASTERPIECE NEGOTIATION ENGINES (LOCAL)
    # ===============================================

    async def _negotiate_offer(self, pending: Dict, offer: int, buying_team_name: str) -> Dict:
        # --- Role Check (Optional but good for realism) ---
        user_team = await database.get_user_team(pending.get("user_id", 0))
        user_role = user_team.get("user_role", "ba\u015fkan") if user_team else "ba\u015fkan"
        
        # --- Club Logic ---
        market_val = pending.get("market_value_eur", 5000000)
        from_team = pending.get("current_team", "")
        is_free_agent = pending.get("is_free_agent", False)
        last_counter = pending.get("last_club_counter", 0)
        
        # Initial Asking Price (Market Val + 30% premium)
        # --- INITIAL PRICE CALCULATION (Including Taxes) ---
        initial_asking = int(market_val * 1.45)
        
        # Apply and PERSIST taxes to initial_asking if it's the first time
        if "base_asking_with_tax" not in pending:
            taxed_price = initial_asking
            # Rivalry Tax (GS-FB-BJK-TS)
            big_4 = ["Galatasaray", "Fenerbahçe", "Beşiktaş", "Trabzonspor"]
            is_rivalry = (from_team in big_4) and (buying_team_name in big_4)
            if is_rivalry:
                taxed_price = int(taxed_price * 1.25)
            
            # --- TURKEY TAX (Tiered OVR) ---
            p_ovr = pending.get("overall", 0)
            if p_ovr >= 80:
                taxed_price = int(taxed_price * 1.45)
            elif p_ovr >= 75:
                taxed_price = int(taxed_price * 1.30)
            
            pending["base_asking_with_tax"] = taxed_price
        
        # Use the persistent taxed price or the last counter-offer
        asking = pending.get("last_club_counter", pending["base_asking_with_tax"] if not is_free_agent else market_val)
        
        # --- STUBBORNNESS TIERING (REALISM FIX) ---
        # Larger players are much harder to bargain with
        if is_free_agent:
            drop_rate = 0.985 # Players are stubborn about their signing bonus
            floor_pct = 0.95  # 5% below MV max
        elif market_val >= 50000000: # Elite (50M+)
            drop_rate = 0.982       # %1.8 drop only
            floor_pct = 1.05        # Can't buy below 105% of market value
        elif market_val >= 15000000: # Mid (15M-50M)
            drop_rate = 0.965       # %3.5 drop
            floor_pct = 0.98        # Can't buy below 98% of market value
        else: # Normal (<15M)
            drop_rate = 0.94        # %6 drop (Original)
            floor_pct = 0.90        # Can't buy below 90% of market value

        # Accept condition (Allow 2% wiggle room instead of 5%)
        # Checked BEFORE patience reduction to allow accepting final offers
        if offer >= asking * 0.98:
            if is_free_agent:
                accept_msgs = [
                    "İstediğim imza parası bu. Projeniz ilgimi çekiyor!",
                    "Bu rakam beklentilerimi karşılıyor. İmza atmaya yakınız.",
                    "Menajerim teklifi onayladı, artık maaşı konuşabiliriz."
                ]
            else:
                accept_msgs = [
                    "İstediğimiz noktaya ulaştık. El sıkışalım!",
                    "Rakamlar kulübümüzün beklentilerini karşılıyor. Hayırlı olsun.",
                    "Zorlu bir pazarlıktı ama teklifiniz bizi ikna etti. Onaylıyoruz.",
                    "Bu oyuncuyu bu fiyata bırakmak canımı yaksa da vizyonunuz için kabul ediyoruz.",
                    "Resmi evrakları hazırlatıyorum, hayırlı olsun."
                ]
            return {"status": "Accepted", "msg": random.choice(accept_msgs)}

        # Patience Logic (Max 4 turns - Decreases every turn)
        patience = pending.get("patience", 4)
        
        # If this is the first turn, ensure it starts at 4
        if "p_turns" not in pending:
            pending["p_turns"] = 0
            patience = 4
        
        pending["p_turns"] += 1
        patience -= 1 # Base reduction for every turn
            
        # Extra penalty for the same or lower offer
        if offer <= pending.get("highest_user_offer", 0): 
            patience -= 1 
        
        # Extreme Low-balling (Offer < 50% of market value)
        if offer < market_val * 0.50:
            patience -= 1 # Total -2 with base
            
        pending["patience"] = patience
        if patience <= 0:
            return {"status": "Rejected", "msg": "Sabrımızı zorladınız. Bu görüşmeler bizim için bitmiştir!"}
            
        # Calculate new counter offer (with Stubbornness Chance)
        # Reduced stubbornness chance (35% instead of 60%) for better UX
        is_stubborn = random.random() < 0.35 or (offer < market_val * 0.75) 
        
        role_note = " Say\u0131n Ba\u015fkan," if user_role == "ba\u015fkan" else " Hocam,"
        
        if is_free_agent and last_counter > 0:
            new_ask = last_counter
            stubborn_msg = [
                f"Söylediğim gibi, kulüpsüz bir oyuncu olarak {self._format_value(new_ask)} imza parası bekliyorum.",
                f"Kariyerim için bu imza parası şart: {self._format_value(new_ask)}.",
                f"Menajerim {self._format_value(new_ask)} altına kesinlikle izin vermiyor."
            ]
            return {"status": "Counter", "msg": random.choice(stubborn_msg), "val": new_ask}
        
        if is_stubborn and last_counter > 0:
            new_ask = last_counter
            stubborn_msg = [
                f"Bu oyuncu için son fiyatımız {self._format_value(new_ask)}. Daha aşağı inmiyoruz.",
                f"Yönetim kurulumuz {self._format_value(new_ask)} altına kesinlikle izin vermiyor. Kararımız nettir.",
                f"Pazarlık payımız tükendi.{role_note} {self._format_value(new_ask)} son rakamımızdır.",
                f"Daha fazla indirim yapmamız kulüp menfaatlerine aykırı. {self._format_value(new_ask)} bekliyoruz."
            ]
            return {"status": "Counter", "msg": random.choice(stubborn_msg), "val": new_ask}
        
        # Standard drop logic (if not stubborn)
        new_ask = max(int(asking * drop_rate), int(market_val * floor_pct))
        
        # --- SMART ACCEPTANCE FIX ---
        # If the user offers more than what we were going to ask anyway, ACCEPT IT!
        if offer >= new_ask:
            if is_free_agent:
                accept_msgs = [
                    "İstediğim rakamın bile üzerindesiniz. Projeniz ilgimi çekiyor!",
                    "Bu cömert teklif beklentilerimi fazlasıyla karşılıyor. İmza atmaya yakınız.",
                    "Menajerim teklifi çok beğendi, artık maaşı konuşabiliriz."
                ]
            else:
                accept_msgs = [
                    "Beklentilerimizin de üzerinde bir teklif. El sıkışalım!",
                    "Rakamlar kulübümüzün hedeflerini fazlasıyla karşılıyor. Hayırlı olsun.",
                    "Pazarlığı burada bitirebiliriz, teklifiniz bizi ikna etti. Onaylıyoruz.",
                    "Resmi evrakları hazırlatıyorum, hayırlı olsun."
                ]
            return {"status": "Accepted", "msg": random.choice(accept_msgs)}

        # If the drop is too small (e.g. at the floor), stay final
        if new_ask == last_counter:
            best_offer_msg = f"Bu bizim son ve en iyi teklifimizdir:{role_note} {self._format_value(new_ask)}." if not is_free_agent else f"İmza parası için son sözüm: {self._format_value(new_ask)}."
            return {"status": "Counter", "msg": best_offer_msg, "val": new_ask}

        if is_free_agent:
            counter_msgs = [
                f"Pazarlık yapmayı sevmem ama teklifini {self._format_value(new_ask)} seviyesine çekersen el sıkışabiliriz.",
                f"İstediğim imza parası {self._format_value(new_ask)}. Bu benim değerim.",
                f"Ciddiyseniz {self._format_value(new_ask)} getirin, yarın antrenmana çıkayım."
            ]
        else:
            counter_msgs = [
                f"Fiyatı {self._format_value(new_ask)} noktasına çektik.{role_note} Altını beklemeyin.",
                f"İstediğimiz rakam bu değil. {self._format_value(new_ask)} verirseniz masadan kalkmayız.",
                f"Pazarlık payımız çok kısıtlı. Son sözümüz {self._format_value(new_ask)}.",
                f"Bu oyuncunun kalitesini biliyorsunuz. {self._format_value(new_ask)}'den aşağısı olmaz.",
                f"Ölücü tekliflerle vaktimizi çalmayın. Ciddiyseniz {self._format_value(new_ask)} getirin.",
                f"Yönetim kurulu bu fiyattan aşağısına izin vermiyor: {self._format_value(new_ask)}."
            ]
        return {"status": "Counter", "msg": random.choice(counter_msgs), "val": new_ask}

    async def _negotiate_loan(self, pending: Dict, offer: int, buying_team_name: str) -> Dict:
        """Kiralama pazarlığı için özel mantık (Yaş ve Rol duyarlı)"""
        market_val = pending.get("market_value_eur", 5000000)
        from_team = pending.get("current_team", "")
        age = pending.get("age", 25)
        ovr = pending.get("overall", 75)
        
        # 1. KULÜP STRATEJİSİ (Zorluk Seviyeleri)
        # Genç Yetenek (<21): Gelişimi için verilebilir ama "oynatma sözü" ister.
        # Yaşlı (>32): Maaştan kurtulmak için hemen verilir.
        # Prime (22-31): Sadece yedekse veya çok iyi teklifse verilir.
        
        is_young = age < 21
        is_veteran = age > 35
        is_star = ovr >= 84
        
        # --- PRESTİJ VE GÜÇ DENGESİ KONTROLÜ ---
        # Eğer oyuncu gideceği takım için "fazla iyiyse" reddeder.
        buying_team = await database.search_team(buying_team_name)
        buying_ovr = buying_team['overall'] if buying_team else 70
        
        if ovr > buying_ovr + 6 and not is_veteran:
            return {
                "status": "Rejected", 
                "msg": f"Oyuncu, {buying_team_name} projesini kariyeri için yetersiz buluyor. Daha iddialı bir takıma gitmek istiyor."
            }
        
        # Kiralama Bedeli Beklentisi (Normalde Piyasa Değerinin %5-15'i arasıdır)
        base_loan_ask = int(market_val * 0.10)
        
        if is_young:
            base_loan_ask = int(market_val * 0.05) # Gençler daha ucuz kiralanır
            loan_msg_pool = [
                f"Gelişimi için {self._format_value(base_loan_ask)} karşılığında kiralayabiliriz ama mutlaka süre almalı.",
                f"Gelecek vadeden bir isim. {self._format_value(base_loan_ask)} ve düzenli oynatma garantisiyle kabul ederiz."
            ]
        elif is_veteran:
            base_loan_ask = int(market_val * 0.03) # Yaşlılar çok ucuza kiralanır
            loan_msg_pool = [
                f"Tecrübesiyle size çok şey katar. {self._format_value(base_loan_ask)} ödeyin, maaş yükünden kurtulalım.",
                f"Kadromuzda yer bulması zor. {self._format_value(base_loan_ask)} gibi sembolik bir bedele evet deriz."
            ]
        elif is_star:
            return {"status": "Rejected", "msg": "Bu oyuncu takımımızın yıldızı, kiralık vermeyi kesinlikle düşünmüyoruz!"}
        else:
            base_loan_ask = int(market_val * 0.15)
            loan_msg_pool = [
                f"Kiralık vermek için {self._format_value(base_loan_ask)} bekliyoruz. Daha aşağısı kurtarmaz.",
                f"Normalde satmayı düşünürüz ama {self._format_value(base_loan_ask)} getirirseniz bir sezonluk kiralayabiliriz."
            ]

        # Pazarlık Mantığı
        if offer >= base_loan_ask * 0.90:
            # Maaş Paylaşımı Teklifi
            salary_share = 100
            if is_young: salary_share = 50 # Gençlerin maaşının yarısını ana kulüp ödeyebilir
            elif is_veteran: salary_share = 100 # Yaşlılarınkini tamamen alan öder
            
            pending['salary_share'] = salary_share
            return {
                "status": "Accepted", 
                "msg": f"{random.choice(loan_msg_pool)} Ayrıca oyuncu maaşının %{salary_share}'ini sizin ödemenizi bekliyoruz."
            }
        else:
            new_ask = int(base_loan_ask * 0.95)
            pending['last_club_counter'] = new_ask
            return {
                "status": "Counter", 
                "msg": f"Teklifiniz çok düşük. {self._format_value(new_ask)} kiralama bedeli bekliyoruz.",
                "val": new_ask
            }

    async def _negotiate_salary(self, pending: Dict, offer: int, team_name: str) -> Dict:
        # --- Player Logic ---
        curr_sal = pending.get("current_salary_eur", 1000000)
        pers = pending.get("personality_type", "Profesyonel")
        age = pending.get("age", 25)
        is_free_agent = pending.get("is_free_agent", False)
        market_val = pending.get("market_value_eur", 5000000)
        
        # --- FREE AGENT SALARY RULE (MV / 2) ---
        if is_free_agent:
            target_min = int(market_val / 2)
        else:
            target_min = int(curr_sal * 1.32)  # Default Jump (+15% of 1.15 is ~1.32)
            if "Paracı" in pers: target_min = int(curr_sal * 1.55) # Paracı Jump (+15% of 1.35 is ~1.55)
            if age >= 32: target_min = int(curr_sal * 1.38) # Veteran Jump (+15% of 1.20 is ~1.38)
        
        # Prestige Discount
        team_data = await self._find_team(team_name)
        if team_data and team_data.get("overall", 70) >= 80: target_min = int(target_min * 0.92)
        
        # Asking is target_min + 25% wiggle room starting point
        asking = pending.get("last_p_counter", int(target_min * 1.25))
        
        # Accept condition (Allow 2% wiggle room instead of 4%)
        if offer >= asking * 0.98:
            accept_pools = [
                "\u015eartlar benim i\u00e7in harika. Yar\u0131n kampa kat\u0131l\u0131yorum!",
                "Bu kadar tutkulu bir kul\u00fcbe hay\u0131r diyemezdim. \u0130mzalar\u0131 atal\u0131m.",
                "De\u011ferimi bildi\u011finiz i\u00e7in te\u015fekk\u00fcrler. Formas\u0131n\u0131 giymek i\u00e7in sab\u0131rs\u0131zlan\u0131yorum.",
                "Menajerimle g\u00f6r\u00fc\u015ft\u00fcm, her \u015fey yolunda. Yeni maceram ba\u015fl\u0131yor!",
                "Bu maa\u015f ve sundu\u011funuz proje beni ikna etti. Kabul ediyorum."
            ]
            return {"status": "Accepted", "msg": random.choice(accept_pools)}

        # --- PLAYER PATIENCE LOGIC (Max 4 turns) ---
        p_patience = pending.get("p_patience", 4)
        if "p_salary_turns" not in pending:
            pending["p_salary_turns"] = 0
            p_patience = 4
        
        pending["p_salary_turns"] += 1
        p_patience -= 1 # Every turn
        
        # Salary Low-ball (Offer < 60% of player's asking)
        if offer < asking * 0.60:
            p_patience -= 1
            
        pending["p_patience"] = p_patience
        if p_patience <= 0:
            return {"status": "Rejected", "msg": "Benimle dalga ge\u00e7iyorsunuz san\u0131r\u0131m. Ba\u015fka kul\u00fcplerle g\u00f6r\u00fc\u015fece\u011fim!"}
        
        # Salary Sticking Chance (Stubbornness)
        # Reduced stubbornness chance (35% instead of 60%) for better UX
        is_stubborn_p = random.random() < 0.35 or (offer < asking * 0.80)
        
        if is_stubborn_p and pending.get("last_p_counter", 0) > 0:
            new_ask = asking
            stubborn_p_msgs = [
                f"Kariyerim i\u00e7in bu miktar\u0131n alt\u0131n\u0131 d\u00fc\u015f\u00fcnm\u00fcyorum: {self._format_value(new_ask)}.",
                f"Menajerimle konu\u015ftum, {self._format_value(new_ask)} son karar\u0131m\u0131zd\u0131r.",
                f"Ba\u015fka kul\u00fcplerin verdi\u011fi rakamlar belli. {self._format_value(new_ask)} alt\u0131na imza atmam."
            ]
            return {"status": "Counter", "msg": random.choice(stubborn_p_msgs), "val": new_ask}
            
        new_ask = max(int(asking * 0.95), target_min)
        
        # Karakter Bazlı Karşı Teklifler
        if is_free_agent:
            msg = f"Boştaki bir oyuncu olarak beklentim {self._format_value(new_ask)}. Bu benim için adil."
        elif "Paracı" in pers:
            p_msgs = [
                f"Kariyerime mi oynamamı istiyorsunuz yoksa futbol mu? Teklifimi biliyorsunuz: {self._format_value(new_ask)}.",
                f"Masadaki rakam ciddiyetten uzak. {self._format_value(new_ask)}'den aşağı inmem.",
                f"Başka kulüplerden daha iyi teklifler var. Beklentim {self._format_value(new_ask)}."
            ]
            msg = random.choice(p_msgs)
        elif "Sadık" in pers or "Profesyonel" in pers:
            s_msgs = [
                f"Projeniz beni heyecanlandırıyor ama ailemi ve geleceğimi de düşünmeliyim. {self._format_value(new_ask)} uygun olur.",
                f"Sunduğunuz şartları biraz daha iyileştirirseniz ({self._format_value(new_ask)} gibi), kalpten imzayı atarım.",
                f"Kariyerim için doğru bir adım olduğuna emin olmak istiyorum. İsteğim: {self._format_value(new_ask)}."
            ]
            msg = random.choice(s_msgs)
        else:
            msg = f"Kişisel beklentilerim bu teklifin biraz üzerinde. {self._format_value(new_ask)} orta yol olabilir."

        return {"status": "Counter", "msg": msg, "val": new_ask}

    # ===============================================
    #  ERROR HANDLING
    # ===============================================
    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Friendly error handler for the cog"""
        try:
            if isinstance(error, commands.MissingRequiredArgument):
                if ctx.command.name == "ara":
                    return await ctx.send("🔍 **Başkan, hangi oyuncuyu arıyorsun?**\n👉 `!ara [Oyuncu Adı]` yazarak scout ekibine talimat verebilirsin.")
                if ctx.command.name == "oyuncusat":
                    return await ctx.send("💰 **Hangi oyuncuyu satmak istiyorsun başkan?**\n👉 `!oyuncusat [Oyuncu Adı]` yazman yeterli.")
                if ctx.command.name == "teklif":
                    return await ctx.send("🤝 **Teklif miktarını girmeyi unuttun başkan!**\n👉 `!teklif [Miktar] (Örn: 5M)`")
                if ctx.command.name == "maas":
                    return await ctx.send("💶 **Oyuncuya ne kadar maaş önereceksin?**\n👉 `!maas [Miktar] (Örn: 2M)`")
        except Exception as e:
            print(f"DEBUG: Error while sending error response in TransferCog: {e}")
        
        # Diğer hatalar için logla ama çökme
        print(f"DEBUG: Command error: {error}")

    # ===============================================
    #  COMMANDS
    # ===============================================

    @commands.command(name="ara", aliases=["scout", "transferbilgi"])
    async def ara_command(self, ctx: commands.Context, *, name: str):
        # Normalize user input (Discord often leaves trailing punctuation after URLs)
        name = (name or "").strip()
        name = name.rstrip(" \t\r\n,.;)>]}")

        # --- RED KONTROLÜ ---
        if self._check_refusal(ctx.author.id, name):
            return await ctx.send(f"❌ **{name}** veya kulübü şu an sizinle görüşmek istemiyor. (24 saatlik bekleme süresi)")

        msg = await ctx.send(f"🔍 **{name}** araştırılıyor...")
        
        info = None
        
        # 0. ÖNCELİK: Veri Tabanı (BÜYÜK TUTARLILIK GÜNCELLEMESİ)
        # Eğer oyuncu zaten ligde/DB'de varsa direkt oradaki veriyi kullanalım.
        db_player = await database.search_player(name)
        if db_player:
            print(f"DEBUG: {name} veri tabanında bulundu ({db_player['name']}).")
            info = {
                "player_name": db_player['name'],
                "current_team": db_player['team'],
                "position": db_player['position'],
                "overall": db_player['overall'],
                "age": db_player['age'],
                "market_value_eur": db_player.get('market_value', 50000000),
                "pace": db_player['pace'],
                "shooting": db_player['shooting'],
                "passing": db_player['passing'],
                "defending": db_player['defending'],
                "source": "Yerel Veri Tabanı"
            }

        # 1. URL Check (Eğer DB'de bulunamadıysa)
        if not info and name.startswith("http"):
            info = await self._research_player_from_url(name)
            if not info:
                # URL Scrape failed, try extracting name from URL for fallback search
                try:
                    parts = name.split("/")
                    fallback_name = None
                    for i, part in enumerate(parts):
                        if part == "profil" and i > 0:
                            fallback_name = parts[i-1].replace("-", " ").strip().rstrip(",.;)>]}")
                            break
                    
                    if fallback_name:
                        print(f"DEBUG: URL Research failed for {name}, trying fallback search: {fallback_name}")
                        info = await self._research_player(fallback_name)
                    else:
                        print(f"DEBUG: URL format not recognized, skipping fallback for: {name}")
                except Exception as e:
                    print(f"DEBUG: URL Fallback error: {e}")
        
        # 2. Önce kullanıcının kendi takımına bak (Lokal Dosya) - Sadece isimle aratılıyorsa
        if not info and not name.startswith("http"):
            user_team = await database.get_user_team(ctx.author.id)
            if user_team:
                info = await self._get_local_player_data(name, user_team['name'])
                if info:
                    info['market_value_eur'] = await self._calculate_dynamic_price(
                        info['market_value_eur'], info['age'], user_team['name']
                    )
        
        # 3. Hala bulunamadıysa AI Araştırması Yap (Fallback)
        if not info:
            res = await self._research_player(name)
            # AI tamamen başarısız olsa bile en azından ismi ve temel verileri koruyalım
            if not res:
                # Eğer girdi bir URL ise içinden ismi ayıklamaya çalışalım
                display_name = name
                if name.startswith("http"):
                    parts = name.split("/")
                    for i, part in enumerate(parts):
                        if part == "profil" and i > 0:
                            display_name = parts[i-1].replace("-", " ").title()
                            break
                
                # Akıllı Default Veri (75 OVR, 15M Value)
                res = {
                    'player_name': display_name, 
                    'age': 25,
                    'market_value_eur': 15000000,
                    'overall': 75,
                    'position': 'ST',
                    'current_team': 'Serbest',
                    'nationality': 'Bilinmiyor',
                    'source': 'AI Failure Fallback (Smart Default)'
                }
            
            info = self._normalize_scout_data(res)
            
        await msg.delete()
        if not info: return await ctx.send("❌ Oyuncu bilgisi bulunamadı.")

        # --- REYTING TUTARLILIK KONTROLÜ (FORCE EVALUATION) ---
        # Eğer oyuncu DB'den gelmediyse, Piyasa Değerinden OVR hesaplayalım (Tutarlılık için)
        if info.get("source") != "Yerel Veri Tabanı":
            mv = info.get("market_value_eur", 0)
            # Eğer AI 80 demiş ama 80M değer varsa, bizim formül 90+ diyecek.
            info["overall"] = self._estimate_ovr_from_value(mv)
            info["source"] = f"{info.get('source', 'AI Research')} + Bot Appraisal"
        
        # --- PLAYER WILLINGNESS CHECK (OVR based refusal) ---
        try:
            p_ovr = int(info.get('overall', 0))
        except:
            p_ovr = 75
            
        refuse_chance = 0
        if p_ovr >= 85: refuse_chance = 0.50
        elif p_ovr >= 80: refuse_chance = 0.20
        elif p_ovr >= 75: refuse_chance = 0.10
        
        if random.random() < refuse_chance:
            refusal_msgs = [
                f"❌ **SCOUT RAPORU:** {info['player_name']} Türkiye Ligi'nde oynamaya hiç sıcak bakmıyor.",
                f"❌ **MENAJER NOTU:** \"Oyuncumun kariyer hedefleri arasında şu an Türkiye bulunmuyor.\"",
                f"❌ **BİLGİ:** {info['player_name']} daha rekabetçi bir ligde kalmak istediğini iletti.",
                f"❌ **RED:** Oyuncu tarafı görüşmeyi reddetti. Türkiye'ye gelmeyi bir seçenek olarak görmüyorlar.",
                f"❌ **OLUMSUZ:** {info['player_name']} için yapılan yoklamada 'kesinlikle hayır' yanıtı alındı."
            ]
            return await ctx.send(random.choice(refusal_msgs))
        
        # Tahmini İstenen Bedel (Asking Price) Hesapla
        is_free = "kulüpsüz" in info.get('current_team', '').lower()
        
        if is_free:
            # KULÜPSÜZ KURALI: İmza parası = Piyasa Değeri, Maaş = Piyasa Değeri / 2
            asking_price = info.get('market_value_eur', 0)
            info['is_free_agent'] = True
            info['expected_bonus'] = info.get('market_value_eur', 0)
            info['expected_salary'] = int(info.get('market_value_eur', 0) / 2)
        else:
            asking_price = info.get('asking_price_eur', int(info.get('market_value_eur', 5000000) * 1.3))
            
            # --- TURKEY TAX (Tiered OVR) ---
            p_ovr = info.get('overall', 0)
            if p_ovr >= 80:
                asking_price = int(asking_price * 1.45)
                info['ovr_tax_note'] = "Elite"
            elif p_ovr >= 75:
                asking_price = int(asking_price * 1.10)
                info['ovr_tax_note'] = "Kademeli"
        
        self.pending_transfers[ctx.author.id] = info
        
        # Determine Color Based on OVR
        try:
            ovr = int(info['overall'])
        except:
            ovr = 75
            
        embed_color = discord.Color.blue()
        if ovr >= 85: embed_color = discord.Color.gold()
        elif ovr >= 80: embed_color = discord.Color.from_rgb(192, 192, 192) # Silver
        elif ovr >= 75: embed_color = discord.Color.dark_blue()
        
        embed = discord.Embed(
            title=f"👤 SCOUT RAPORU: {info.get('player_name', 'Bilinmeyen Oyuncu')} ({info.get('age', 25)} Yaş)",
            description=f"💬 *\"{info.get('scout_comment', 'Hızlı ve teknik bir oyuncu.')}\"*",
            color=embed_color
        )
        embed.set_author(name=f"Kaynak: {info.get('source', 'Yapay Zeka')}")
        
        embed.add_field(name="🌍 Milliyet", value=info.get('nationality', 'Bilinmiyor'), inline=True)
        embed.add_field(name="🏟️ Takım", value=info.get('current_team', 'Bilinmiyor'), inline=True)
        embed.add_field(name="📍 Mevki / Güç", value=f"{info.get('position', 'ST')} | ⭐ **{info.get('overall', 75)} OVR**", inline=True)
        
        embed.add_field(name="💰 Piyasa Değeri", value=f"**{self._format_value(info.get('market_value_eur', 0))}**", inline=True)
        
        price_label = "🏷️ İmza Parası" if is_free else "🏷️ Beklenen Bedel"
        note_suffix = " ⚠️ *(Serbest)*" if is_free else (f" ⚠️ *({info.get('ovr_tax_note', '')} Vergisi)*" if info.get('ovr_tax_note') else "")
        embed.add_field(name=price_label, value=f"**{self._format_value(asking_price)}**{note_suffix}", inline=True)
        
        embed.add_field(name="💶 Güncel Maaş", value=self._format_value(info.get('current_salary_eur', 0)), inline=True)
        
        embed.add_field(name="📊 İstatistikler", value=info.get('stats', 'Yeni sezonda başlıyor...'), inline=True)
        embed.add_field(name="🕵️ Karakter", value=info.get('personality_type', 'Profesyonel'), inline=True)
        embed.add_field(name="🤝 Aidiyet / Form", value=f"{info.get('loyalty_level', 'Orta')} | {self._get_form_emoji(info.get('form_rating', 0))}", inline=True)
        
        interested = info.get('interested_clubs', ['Bilinmiyor'])
        if isinstance(interested, list): interested_str = ", ".join(interested)
        else: interested_str = str(interested)
        self._add_split_fields(embed=embed, name="🔥 İlgi Gösterenler", value=interested_str, inline=False)
        
        negotiate_label = "🤝 İmza Teklifi Yap" if is_free else "🤝 Pazarlık Yap"
        embed.set_footer(text=f"👉 {negotiate_label}: !teklif {info.get('player_name', 'Oyuncu')} [Miktar]")
        
        # Fetch Player Photo
        photo_url = await self._get_player_photo(info.get('player_name', ''))
        if photo_url:
            embed.set_image(url=photo_url)
        else:
            # Fallback icon if no photo found
            embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/3211/3211029.png")
        
        await ctx.send(embed=embed)

    async def _research_squad_ai(self, team_name: str) -> List[str]:
        """Uses AI cascade to list the 2025/26 squad with Hybrid Reality Filtering."""
        from core import ai
        
        # 2026 STATIC REALITY FILTERS (Manual overrides for AI hallucinations)
        CLUB_FILTERS = {
            "Sporting": {
                "exclude": ["Viktor Gyökeres", "Gyökeres", "Paulinho", "Adan", "Coates"],
                "must_include": ["Luis Suárez", "Fotis Ioannidis", "Vagiannidis", "Kochorashvili"]
            },
            "Napoli": {
                "exclude": ["Kim Min-jae", "Min-jae Kim", "Zielinski", "Osimhen", "Ndombele", "Elmas", "Lozano", "Ostigard"],
                "must_include": ["Romelu Lukaku", "Scott McTominay", "Billy Gilmour", "Alessandro Buongiorno"]
            },
            "Real Madrid": {
                "exclude": ["Toni Kroos", "Karim Benzema", "Eden Hazard", "Isco"],
                "must_include": ["Kylian Mbappe", "Endrick", "Arda Guler"]
            },
            "Barcelona": {
                "exclude": ["Lionel Messi", "Sergio Busquets", "Jordi Alba", "Ilkay Gundogan"],
                "must_include": ["Lamine Yamal", "Dani Olmo", "Pau Cubarsi"]
            },
            "Arsenal": {
                "exclude": [],
                "must_include": ["Viktor Gyökeres", "Riccardo Calafiori", "Mikel Merino"]
            },
            "Manchester City": {
                "exclude": ["Ederson", "Kevin De Bruyne", "De Bruyne", "Ilkay Gundogan", "Gundogan"],
                "must_include": ["Phil Foden", "Erling Haaland", "Rodri", "Savinho"]
            }
        }
        
        # Select active filter
        active_f = next((v for k, v in CLUB_FILTERS.items() if k.lower() in team_name.lower()), {"exclude": [], "must_include": []})
        must_include_str = ", ".join(active_f["must_include"]) if active_f["must_include"] else "Current stars"
        exclude_str = ", ".join(active_f["exclude"]) if active_f["exclude"] else "None"

        # Force a slightly higher number to account for cleaning
        prompt = f"""You are an elite football scout. It is April 2026.
List the 2025/2026 First-Team Squad for '{team_name}'.

STRICT 2026 RULES:
1. EXCLUDE: {exclude_str} (These players are NOT at the club in 2026).
2. MUST INCLUDE: {must_include_str} (These are confirmed/current stars in 2026).
3. CONTEXT: Gyökeres moved to Arsenal in 2025. Mbappe is at Real Madrid. 
4. COUNT: Exactly 22 UNIQUE names (11 starters + 11 bench).
5. OUTPUT: Return ONLY a JSON array of strings."""

        system = f"Return ONLY valid JSON list of 22 names for {team_name}. April 2026 context is mandatory."
        
        res = await ai.generate_content(
            prompt=prompt,
            system=system,
            is_json=True,
            label=f"Squad Research: {team_name}",
            tokens=1200,
            provider="gemini"
        )
        
        raw_list = []
        if res and isinstance(res, list):
            raw_list = res
        elif res and isinstance(res, dict):
            for v in res.values():
                if isinstance(v, list):
                    raw_list = v
                    break
        
        if raw_list:
            # Apply Manual Filter and Cleaning
            cleaned = []
            lower_excludes = [x.lower() for x in active_f["exclude"]]
            for name in raw_list:
                n_str = str(name).strip()
                if not n_str or len(n_str) < 3: continue
                if any(bad in n_str.lower() for bad in lower_excludes):
                    continue
                cleaned.append(n_str)
            
            # Combine logic: Must include items + AI produced items
            final_set = list(dict.fromkeys(active_f["must_include"] + cleaned))
            return final_set[:22] # Guarantee exactly matchday squad size if possible
            
        return []

    async def _fetch_wikipedia_squad(self, team_name: str) -> List[str]:
        """Fetches the current squad from Wikipedia using Search API + Parse API."""
        import urllib.parse
        import re
        
        # Full browser headers to evade anti-bot filters
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'en-US,en;q=0.9,tr;q=0.8',
            'Origin': 'https://en.wikipedia.org',
            'Referer': 'https://en.wikipedia.org/'
        }
        
        async def try_wiki(lang: str, team_raw: str):
            base_url = f"https://{lang}.wikipedia.org/w/api.php"
            try:
                # ENHANCED SEARCH: Try multiple variants to find the real club page
                search_variants = [f"{team_raw} FC", f"{team_raw} F.C.", team_raw]
                if lang == "tr":
                    search_variants = [f"{team_raw} SK", f"{team_raw} FK", team_raw]
                
                async with aiohttp.ClientSession(headers=headers) as session:
                    page_title = None
                    for variant in search_variants:
                        search_url = f"{base_url}?action=query&list=search&srsearch={urllib.parse.quote(variant)}&format=json"
                        async with session.get(search_url, timeout=5) as resp:
                            if resp.status != 200: continue
                            s_data = await resp.json()
                            results = s_data.get('query', {}).get('search', [])
                            if results:
                                # Ensure it's likely a club page, not a city/person
                                title = results[0].get('title', '')
                                if any(x in title.lower() for x in ["fc", "football", "squad", "club", "f.c.", "sk", "fk", "takım"]):
                                    page_title = title
                                    break
                                elif not page_title: # Fallback to first ever result if no keywords
                                    page_title = title
                    
                    if not page_title: return []
                    
                    # 2. Get sections and find BEST match
                    sections_url = f"{base_url}?action=parse&page={urllib.parse.quote(page_title)}&prop=sections&format=json"
                    async with session.get(sections_url, timeout=7) as sec_resp:
                        if sec_resp.status != 200: return []
                        sec_data = await sec_resp.json()
                        sections = sec_data.get('parse', {}).get('sections', [])
                        
                        best_s_idx = None
                        max_priority = -1
                        
                        # Priority map for section names
                        priorities = {
                            "current squad": 10, "first-team squad": 10, "güncel kadro": 10,
                            "squad": 7, "players": 5, "kadro": 5, "team": 3
                        }
                            
                        for s in sections:
                            line = s.get('line', '').lower()
                            # Skip noise sections
                            if any(bad in line for bad in ["youth", "history", "under-", "altyap", "rezerv", "loan out"]):
                                continue
                            
                            for kw, prio in priorities.items():
                                if kw in line and prio > max_priority:
                                    max_priority = prio
                                    best_s_idx = s.get('index')
                        
                        if not best_s_idx: return []
                        
                        # 3. Parse section and extract names
                        parse_url = f"{base_url}?action=parse&page={urllib.parse.quote(page_title)}&prop=text&section={best_s_idx}&format=json"
                        async with session.get(parse_url, timeout=10) as p_resp:
                            if p_resp.status != 200: return []
                            p_data = await p_resp.json()
                            html = p_data.get('parse', {}).get('text', {}).get('*', '')
                            
                            # Regex for vcard spans or table links
                            players = re.findall(r'<span class="vcard">.*?<a .*?>(.*?)</a>', html)
                            if not players or len(players) < 5:
                                players = re.findall(r'<td><a .*?title=\"(.*?)\"', html)
                            
                            cleaned = []
                            for p in players:
                                p = re.sub(r' \(.*?\)', '', p).replace(" (page does not exist)", "").strip()
                                if len(p) > 3 and not any(x in p.lower() for x in ["f.c.", "club", "squad", "edit", "help", "coach", "manager"]):
                                    cleaned.append(p)
                            return list(dict.fromkeys(cleaned))
            except: pass
            return []

        # Try English first, then Turkish
        names = await try_wiki("en", team_name)
        if len(names) < 11:
            names = await try_wiki("tr", team_name)
        
        return names[:45]

    async def _research_squad_web(self, team_name: str) -> List[Dict]:
        """Scrapes Transfermarkt 2025/26 squad data (Top 22 by Market Value)."""
        import urllib.parse
        from core import ai, database
        
        print(f"DEBUG: [TM_RESEARCH] {team_name} için 2025/26 kadro araştırması (En Değerli 22) başlıyor...")
        
        # 1. AI Research with explicit Transfermarkt 25/26 instruction
        prompt = f"""Search Transfermarkt for '{team_name}' 2025/2026 season squad (saison_id=2025).
List the TOP 22 players by MARKET VALUE.
STRICT 2026 CONTEXT:
- Real Madrid has Mbappe.
- Arsenal has Gyokeres.
- Man City has Donnarumma, Reijnders, Semenyo (EXCLUDE De Bruyne/Ederson/Gundogan).
- Sporting has Luis Suarez and Ioannidis (EXCLUDE Gyokeres).

Return ONLY a JSON list of objects:
[
  {{"name": "...", "pos": "...", "market_value_eur": 120000000}},
  ...
]"""

        system = f"You are a Transfermarkt scraper bot. Return ONLY valid JSON for {team_name} 25/26 squad. April 2026 timeline."
        
        res = await ai.generate_content(
            prompt=prompt,
            system=system,
            is_json=True,
            label=f"TM Research: {team_name}",
            tokens=1500,
            provider="gemini"
        )
        
        if res and isinstance(res, list):
            processed = []
            for p in res:
                mv = p.get("market_value_eur", 0)
                processed.append({
                    "name": p.get("name", "Unknown"),
                    "position": p.get("pos", "ST"),
                    "market_value_eur": mv,
                    "overall": database.estimate_player_ovr(mv)
                })
            # Sort by value just in case
            processed.sort(key=lambda x: x['market_value_eur'], reverse=True)
            return processed[:22]
            
        return []

        # 3. Scrapers Fallback (Tier 2/3)
        
        # 0. Name Mapping for better search accuracy
        name_map = {
            "Petrocub": "FC Petrocub Hincesti",
            "Rapid Wien": "SK Rapid Wien",
            "Legia Warsaw": "Legia Warszawa",
            "Larne": "Larne FC",
            "Vitória SC": "Vitoria Guimaraes",
            "Beşiktaş": "Besiktas",
            "Galatasaray": "Galatasaray",
            "Fenerbahçe": "Fenerbahce",
            "Trabzonspor": "Trabzonspor",
        }
        search_name = name_map.get(team_name, team_name)
        
        # ============================================================
        # TIER 2: TheSportsDB (Fallback)
        # ============================================================
        try:
            name_map = {
                "Petrocub": "FC Petrocub Hincesti",
                "Rapid Wien": "SK Rapid Wien",
                "Legia Warsaw": "Legia Warszawa",
                "Larne": "Larne FC",
                "Vitória SC": "Vitoria Guimaraes",
                "Beşiktaş": "Besiktas",
                "Galatasaray": "Galatasaray",
                "Fenerbahçe": "Fenerbahce",
                "Trabzonspor": "Trabzonspor",
            }
            search_name = name_map.get(team_name, team_name)
            tsdb_search = f"https://www.thesportsdb.com/api/v1/json/3/searchteams.php?t={urllib.parse.quote(search_name)}"
            async with aiohttp.ClientSession() as session:
                async with session.get(tsdb_search, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        teams = data.get("teams") or []
                        
                        # Sadece futbol takımı olanları filtrele
                        team_id = None
                        for t in teams:
                            if t.get("strSport", "").lower() in ("soccer", "football"):
                                team_id = t.get("idTeam")
                                print(f"DEBUG: [TheSportsDB] {team_name} → ID={team_id} ({t.get('strLeague')})")
                                break
                        
                        if team_id:
                            squad_url = f"https://www.thesportsdb.com/api/v1/json/3/lookup_all_players.php?id={team_id}"
                            async with session.get(squad_url, timeout=15) as s_resp:
                                if s_resp.status == 200:
                                    s_data = await s_resp.json(content_type=None)
                                    players = s_data.get("player") or []
                                    
                                    # Sadece aktif oyuncuları al (koçları hariç tut)
                                    names = []
                                    coaching_positions = {"assistant coach", "manager", "coach", "goalkeeper coach", "coaching"}
                                    for p in players:
                                        status = p.get("strStatus", "").lower()
                                        pos = p.get("strPosition", "").lower()
                                        name = p.get("strPlayer", "").strip()
                                        # Koç/yönetici değilse ve aktifse ekle
                                        if name and status != "coaching" and pos not in coaching_positions:
                                            names.append(name)
                                    
                                    if len(names) >= 11:
                                        print(f"DEBUG: [TheSportsDB] {team_name} kadrosu bulundu: {len(names)} oyuncu")
                                        return names[:40]
        except Exception as e:
            print(f"DEBUG: [TheSportsDB] {team_name} için hata: {e}")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        
        # 1. Transfermarkt Search (Generalized)
        try:
            # Simple query to avoid matching agencies with names like "Squad Management"
            search_query = team_name
            tm_query = urllib.parse.quote(search_query)
            tm_search_url = f"https://www.transfermarkt.com.tr/schnellsuche/ergebnis/schnellsuche?query={tm_query}"
            
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(tm_search_url, timeout=15) as resp:
                    if resp.status == 200:
                        soup = BeautifulSoup(await resp.text(), 'html.parser')
                        links = soup.select('td.hauptlink a')
                        team_link = None
                        blacklist_keywords = ["u19", "u21", "u20", "u23", "futuro", "youth", "altyap", "altyapi", "b takm", "b takimi"]
                        
                        for link in links:
                            link_text = link.text.strip().lower()
                            link_href = link['href']
                            
                            if 'verein' in link_href:
                                # Skip if any blacklist keyword is in the link text
                                if any(kw in link_text for kw in blacklist_keywords):
                                    print(f"DEBUG: Skipping youth/reserve team: {link_text}")
                                    continue
                                    
                                team_link = link
                                print(f"DEBUG: Found main team candidate: {link_text}")
                                break
                                
                        if team_link:
                            # Extract team ID and real slug from the link found
                            # Example link: /fc-petrocub-hincesti/startseite/verein/46643
                            parts = team_link['href'].split('/')
                            team_id = parts[-1]
                            real_slug = parts[1]
                            squad_url = f"https://www.transfermarkt.com.tr/{real_slug}/kader/verein/{team_id}/plus/1"
                            async with session.get(squad_url, timeout=15) as s_resp:
                                if s_resp.status == 200:
                                    html_text = await s_resp.text()
                                    # Detection for redirect to Ansgar Bothe or security pages
                                    if "Ansgar Bothe" in html_text or "Forbidden" in html_text:
                                        print(f"DEBUG: Transfermarkt squad scrape blocked for {team_name}. Fallback to AI.")
                                        return []
                                        
                                    s_soup = BeautifulSoup(html_text, 'html.parser')
                                    rows = s_soup.select('table.items > tbody > tr')
                                    names = []
                                    for row in rows:
                                        name_a = row.select_one('td.hauptlink a')
                                        if name_a and name_a.text.strip():
                                            names.append(name_a.text.strip())
                                    if names: return names[:40]
        except: pass

        # 2. Wikipedia (Fallback)
        try:
            import wikipedia
            # More specific query for Wikipedia to find the "Current Squad" section
            query = f"{team_name} football club current squad 2024"
            search_results = wikipedia.search(query)
            if search_results:
                page = wikipedia.page(search_results[0])
                soup = BeautifulSoup(page.html(), 'html.parser')
                # Try multiple selector variations for squads
                players = [a.text for a in soup.select('table.football-squad .vcard .fn a')]
                if not players:
                    players = [a.text for a in soup.select('table.toccolours .vcard .fn a')]
                if players: return players[:40]
        except: pass
        
        return []

    async def _appraise_squad_ai(self, team_name: str, names: List[str]) -> List[Dict]:
        """Uses AI cascade to calculate OVR/stats for a list of names. Tiered approach."""
        from core import ai
        
        # Reality Check 2026: Instruct AI to filter out old/retired players
        prompt = f"""You are a professional football analyst. It is APRIL 2026.
Verify and appraise these players for '{team_name}':
{", ".join(names[:45])}

CRITICAL REALITY CHECK RULES (2026):
1. DELETE EXPIRED DATA: Manually check each name. If they left club in 2024/25, EXCLUDE.
2. INCLUDE NEW STARS: Prioritize 2025/26 signings.
3. OVR BAREM (120M = 90 Scale):
   - >= 120M: 90-95 | 80-120M: 86-89 | 50-80M: 83-85 | 30-50M: 80-82 | 15-30M: 75-79 | 5-15M: 70-74 | < 5M: 62-69.
4. OUTPUT: Return ONLY a JSON list of objects (Exactly 20-22 UNIQUE entities).
[
  {{"name": "Player Name", "position": "GK", "overall": 85, "age": 28, "market_value_eur": 50000000}},
  ...
]"""

        system = "Return ONLY valid JSON array. Be extremely strict about 2026 team status and the 120M=90 OVR scale."
        response = await ai.generate_content(prompt=prompt, system=system, is_json=True, provider="gemini")

        # Handle response format (list or dict containing list)
        players_list = []
        if isinstance(response, list):
            players_list = response
        elif isinstance(response, dict):
            for key, val in response.items():
                if isinstance(val, list):
                    players_list = val
                    break
        
        # --- NORMALIZATION (Force Original Barem) ---
        from core import database
        for p in players_list:
             mv = p.get('market_value_eur', 0)
             if mv > 0:
                 p['overall'] = database.estimate_player_ovr(mv)
        
        # --- EMERGENCY ELITE FALLBACK ---
        # Eğer AI tamamen patlarsa (Empty list), maçı kurtarmak için "Elite Emergency Squad" üretelim
        if not players_list:
            print(f"DEBUG: [Transfer] AI squad appraisal failed for {team_name}. Using Emergency Fallback.")
            # Takım ismine göre elitlik derecesini belirle (MatchCog._get_smart_ovr benzeri mantık)
            tn = team_name.lower()
            base_ovr = 75
            if any(x in tn for x in ["real madrid", "manchester city", "bayern", "liverpool", "psg", "inter", "barcelona"]):
                base_ovr = 95
            elif any(x in tn for x in ["atletico", "juventus", "milan", "dortmund", "leverkusen", "arsenal"]):
                base_ovr = 90
            
            # 15 rastgele kaliteli oyuncu üret
            for i in range(15):
                pos = random.choice(["GK", "CB", "LB", "RB", "CM", "CAM", "RW", "LW", "ST"])
                p_ovr = base_ovr + random.randint(-4, 4)
                players_list.append({
                    "name": f"{team_name} Star {i+1}",
                    "pos": pos,
                    "market_value_eur": p_ovr * 1_000_000, # Dummy MV for OVR calc
                    "age": random.randint(20, 30),
                    "ovr": p_ovr
                })

        # --- UNIFIED RATING EVALUATION ---
        # AI'dan gelen piyasa değerine göre OVR'yi BİZ hesaplıyoruz (Tutarlılık için)
        for p in players_list:
            # Eğer 'ovr' zaten varsa (Emergency'de olduğu gibi) dokunma, yoksa MV'den hesapla
            if 'ovr' not in p or not p['ovr']:
                mv = p.get('market_value_eur', 0)
                p['ovr'] = self._estimate_ovr_from_value(mv)
            
        return players_list

    def _estimate_ovr_from_value(self, value_eur: int) -> int:
        """Piyasa değerinden mantıklı bir OVR tahmini yürütür (Artık database.py üzerinden merkezi yönetilir)"""
        return database.estimate_player_ovr(value_eur)


    @commands.command(name="kadro", aliases=["squad", "takimim", "kadrom"])
    async def kadro_command(self, ctx: commands.Context, *, team_name: str = None):
        """Taktik dosyasındaki veya aranan takımın kadrosunu listeler"""
        
        # 1. Takım İsmi Belirleme & Canonical Çözüm
        team_data = None
        if not team_name:
            user_team = await database.get_user_team(ctx.author.id)
            if not user_team:
                return await ctx.send("❌ **Takımın bulunamadı!**\n👉 `!takimsec [Takım]`")
            team_data = user_team
        else:
            team_data = await database.search_team(team_name)
            
        if not team_data:
            # Create a virtual team object to allow research
            team_data = {
                "name": team_name.title(),
                "overall": 0,
                "league": "Dünya Klası"
            }
            
        target_team = team_data['name']
        db_overall = team_data.get('overall', 0)

        # Normalizasyon Yardımcısı
        def normalize_name(n):
            if not n: return ""
            return n.lower().replace("ı", "i").replace("ç", "c").replace("ş", "s").replace("ğ", "g").replace("ü", "u").replace("ö", "o").strip()

        # 2. ÖNCELİK 1: LOKAL TAKTİK DOSYASI
        tactic_dir = os.path.join(database.BASE_PATH, "data", "tactics")
        target_file = None
        norm_target = normalize_name(target_team)
        
        # Milli Takım Filtresi
        national_teams = ["spain", "turkey", "france", "germany", "italy", "england", "portugal", "netherlands", "brazil", "argentina"]

        tactic_found = False
        if os.path.exists(tactic_dir):
            for f in os.listdir(tactic_dir):
                if f.endswith(".txt"):
                    f_name_lower = normalize_name(f.replace(".txt", ""))
                    if f_name_lower == norm_target:
                        if f_name_lower in national_teams:
                            continue 
                        target_file = f
                        tactic_found = True
                        break
        
        final_players = []

        if target_file:
            tactic_path = os.path.join(tactic_dir, target_file)
            try:
                # Önce DB'den var mı bak
                db_players = await database.get_players_by_team(target_team)
                if db_players and len(db_players) >= 5: # 5+ bile olsa DB'den çekelim
                    for p in db_players:
                        final_players.append({
                            "name": p['name'],
                            "pos": p.get('position', '??').upper(),
                            "ovr": p.get('overall', 70),
                            "form": self._get_form_emoji(p.get('form_rating', 0))
                        })
                    return await self._send_squad_embed(ctx, team_data, final_players, f"Veritabanı (Taktik: {target_file})")

                # DB boş ise Dosyadan Oku ve AI Appraisal Başlat
                msg = await ctx.send(f"📋 **{target_team}** taktik dosyası bulundu. AI Analiz Motoru (2026) başlatılıyor...")
                found_names = []
                with open(tactic_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if "|" in line:
                            parts = [p.strip() for p in line.split("|")]
                            if len(parts) >= 1:
                                p_name = self._clean_player_name(parts[0])
                                if p_name and len(p_name) > 1:
                                    found_names.append(p_name)
                        elif "(" in line and ")" in line:
                            # Fuzzy name extraction for tactic-only files (e.g. (NAME - NAME))
                            content = re.search(r'\((.*?)\)', line)
                            if content:
                                names_raw = content.group(1).split("-")
                                for n in names_raw:
                                    p_name = self._clean_player_name(n.strip())
                                    if p_name and len(p_name) > 1:
                                        found_names.append(p_name)
                
                if found_names:
                    squad_data = await self._appraise_squad_ai(target_team, found_names)
                    if squad_data:
                        await database.save_research_players(target_team, squad_data)
                        
                        for p in squad_data:
                            final_players.append({
                                "name": p['name'],
                                "pos": (p.get('pos') or p.get('position', '??')).upper(),
                                "ovr": p.get('ovr') or p.get('overall', 70),
                                "form": "→"
                            })
                        await msg.delete()
                        # Güncel team_data'yı tekrar al (AI Appraisal sonrası DB değişmiş olabilir)
                        new_team_data = await database.search_team(target_team)
                        if new_team_data: team_data = new_team_data
                        
                        return await self._send_squad_embed(ctx, team_data, final_players, f"AI Analiz (Taktik: {target_file})")

            except Exception as e:
                print(f"DEBUG Error: Tactic path/appraisal error: {e}")

        # 3. ÖNCELİK 2: VERİTABANI (Dosya yoksa ama DB'de varsa)
        db_players = await database.get_players_by_team(target_team)
        if db_players and len(db_players) >= 5:
            for p in db_players:
                final_players.append({
                    "name": p['name'],
                    "pos": p.get('position', '??').upper(),
                    "ovr": p.get('overall', 70),
                    "form": self._get_form_emoji(p.get('form_rating', 0))
                })
            return await self._send_squad_embed(ctx, team_data, final_players, "Veritabanı")

        # 4. ÖNCELİK 3: İNTERNET ARAŞTIRMASI (Fallback)
        if tactic_found:
            msg = await ctx.send(f"⚠️ **{target_team}** taktik dosyası yetersiz veya formatı farklı. İnternet araştırması başlatılıyor...")
        else:
            msg = await ctx.send(f"🔍 **{target_team}** için yerel dosya bulunamadı. İnternet araştırması başlatılıyor...")
        squad_data = await self._research_squad_web(target_team)
        if squad_data:
            await database.save_research_players(target_team, squad_data)
            
            for p in squad_data:
                final_players.append({
                    "name": p['name'],
                    "pos": (p.get('pos') or p.get('position', '??')).upper(),
                    "ovr": p.get('ovr') or p.get('overall', 70),
                    "form": "→"
                })
            await msg.delete()
            # Güncel team_data'yı tekrar al
            new_team_data = await database.search_team(target_team)
            if new_team_data: team_data = new_team_data
            
            return await self._send_squad_embed(ctx, team_data, final_players, "AI İnternet Araştırması (2026)")
        
        await msg.edit(content="❌ Kadro analizi başarısız oldu.")

    async def _send_squad_embed(self, ctx, team_data, players, source):
        """Kadro listesini profesyonel ve estetik bir teknik direktör paneliyle gönderir"""
        team_name = team_data.get('name', 'Bilinmeyen Takım') if team_data else "Bilinmeyen Takım"
        # OVR'ye göre sırala (Genel liste için)
        try:
            players = sorted(players, key=lambda x: int(x['ovr']), reverse=True)
        except:
            players = sorted(players, key=lambda x: x.get('ovr', 0), reverse=True)
        
        # Mevki Gruplandırma Mantığı
        categories = {
            "🧤 KALECİLER": ["GK", "KL"],
            "🛡️ SAVUNMA": ["CB", "LB", "RB", "LWB", "RWB", "DF"],
            "🧠 ORTA SAHA": ["DM", "CM", "AM", "LM", "RM", "OS", "CDM", "CAM"],
            "🔥 HÜCUM": ["ST", "CF", "LW", "RW", "FV"]
        }
        
        grouped = {cat: [] for cat in categories}
        others = []
        
        for p in players:
            pos = p['pos'].strip().upper()
            found = False
            for cat, pos_list in categories.items():
                if pos in pos_list:
                    grouped[cat].append(p)
                    found = True
                    break
            if not found:
                others.append(p)

        def get_ovr_emoji(ovr_val):
            try:
                o = int(ovr_val)
            except:
                o = 75
            if o >= 85: return "🟢" # Elite
            if o >= 80: return "🟡" # Great
            if o >= 75: return "⚪" # Good
            return "🔘" # Average
            
        # --- KADRO REYTING ORTALAMASI HESAPLA (AĞIRLIKLI TOP 18) ---
        try:
            ovr_list = []
            for p in players:
                try: ovr_list.append(int(p['ovr']))
                except: ovr_list.append(70)
            
            sorted_ovr = sorted(ovr_list, reverse=True)
            top_11 = sorted_ovr[:11]
            bench_7 = sorted_ovr[11:18]
            
            avg_11 = sum(top_11) / 11 if top_11 else 0
            avg_bench = sum(bench_7) / 7 if bench_7 else avg_11
            
            # 75% for starters, 25% for depth
            weighted_ovr = (avg_11 * 0.75) + (avg_bench * 0.25)
            avg_str = f"{weighted_ovr:.1f}"
        except:
            avg_str = "??"

        # --- REYTING GÖRÜNTÜLEME (Veritabanı Senk) ---
        db_overall = team_data.get('overall', 0)
        # Eğer hesaplanan ortalama ile DB arasında fark varsa (Yeni oyuncu vs), hesaplananı baz alabiliriz
        # Ama !reyting_hesapla sonrası DB'deki değer 'Resmi' kabul edilir.
        final_ovr_str = f"{db_overall:.1f}" if db_overall else avg_str

        embed = discord.Embed(
            title=f"🏟️ {team_name.upper()} | TEKNİK HEYET PANELİ",
            description=f"📍 **Analiz Kaynağı:** `{source}`\n📊 **Genel Takım Reytingi:** `⭐ {final_ovr_str}`\n━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.dark_grey()
        )
        
        # Her kategoriyi bir alana (field) ekle
        for cat, p_list in grouped.items():
            if p_list:
                cat_text = ""
                for p in p_list:
                    emoji = get_ovr_emoji(p['ovr'])
                    cat_text += f"{emoji} `{p['ovr']}` **{p['name']}** ({p['pos']}) {p['form']}\n"
                
                self._add_split_fields(embed=embed, name=cat, value=cat_text, inline=False)
        
        if others:
            other_text = ""
            for p in others:
                emoji = get_ovr_emoji(p['ovr'])
                other_text += f"{emoji} `{p['ovr']}` **{p['name']}** ({p['pos']}) {p['form']}\n"
            
            self._add_split_fields(embed=embed, name="❓ DİĞER", value=other_text, inline=False)
            
        embed.set_footer(text=f"📋 Toplam {len(players)} Oyuncu | 🟢 85+ | 🟡 80+ | ⚪ 75+")
        # Takım logosu (Thumbnail) - Eğer veritabanında varsa veya icon bulabilirsek
        embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/3211/3211029.png")
        
        await ctx.send(embed=embed)


    @commands.command(name="pd_guncelle", aliases=["pdg", "pd_sync", "market_sync"])
    @commands.has_permissions(administrator=True)
    async def pd_guncelle_command(self, ctx: commands.Context, *, team_name: str = None):
        """TXT dosyasındaki piyasa değerlerini (PD) veritabanına işler ve reytingleri günceller."""
        # 1. Takım Çözümleme
        team_data = None
        if not team_name:
            user_team = await database.get_user_team(ctx.author.id)
            if not user_team:
                return await ctx.send("❌ **Takımın bulunamadı!**\n👉 `!takimsec [Takım]`")
            team_data = user_team
        else:
            team_data = await database.search_team(team_name)
            
        if not team_data:
             return await ctx.send(f"❌ **{team_name}** bulunamadı.")

        target_team = team_data['name']
        
        msg = await ctx.send(f"🔄 **{target_team}** PD senkronizasyonu başlatılıyor...")
        updated, skipped = await self._sync_pd_from_txt(target_team)
        
        if updated == -1:
            return await msg.edit(content=f"❌ **{target_team}** için taktik dosyası bulunamadı.")

        await msg.edit(content=f"✅ **{target_team}** PD Güncellemesi Tamamlandı!\n"
                               f"📈 **Güncellenen Oyuncu:** `{updated}`\n"
                               f"⚠️ **Bulunamayan Oyuncu:** `{skipped}`\n"
                               f"💡 _Not: Reytingler yeni piyasa değerlerine göre otomatik senkronize edildi._")

    @commands.command(name="pd_guncelle_hepsi", aliases=["pdg_hepsi", "pd_sync_all"])
    @commands.has_permissions(administrator=True)
    async def pd_guncelle_hepsi_command(self, ctx: commands.Context):
        """TUM LIG takımlarının PD'lerini TXT dosyalarından senkronize eder."""
        msg = await ctx.send("⌛ **Tüm lig PD'leri senkronize ediliyor... Bu işlem biraz sürebilir.**")
        
        teams = await database.get_all_teams("Super Lig")
        if not teams:
            return await msg.edit(content="❌ **Hata:** Lig takımları bulunamadı.")
            
        total_updated = 0
        total_skipped = 0
        team_count = 0
        
        for team in teams:
            updated, skipped = await self._sync_pd_from_txt(team['name'])
            if updated != -1:
                total_updated += updated
                total_skipped += skipped
                team_count += 1
                
        await msg.edit(content=f"✅ **Lig Genel PD Senkronizasyonu Tamamlandı!**\n"
                               f"🏟️ **İşlenen Takım:** `{team_count}`\n"
                               f"📈 **Toplam Güncellenen Oyuncu:** `{total_updated}`\n"
                               f"💡 _Tüm lig reytingleri yeni bareme göre hizalandı._")

    async def _sync_pd_from_txt(self, target_team: str) -> Tuple[int, int]:
        """Bir takımın TXT dosyasındaki PD verilerini DB'ye işler. (Internal Helper)"""
        # 1. TXT Dosyasını Bul
        tactic_dir = os.path.join(database.BASE_PATH, "data", "tactics")
        target_file = None
        
        def normalize_name(n):
            if not n: return ""
            return n.lower().replace("ı", "i").replace("ç", "c").replace("ş", "s").replace("ğ", "g").replace("ü", "u").replace("ö", "o").strip()

        norm_target = normalize_name(target_team)
        if os.path.exists(tactic_dir):
            for f in os.listdir(tactic_dir):
                if f.endswith(".txt"):
                    if normalize_name(f.replace(".txt", "")) == norm_target:
                        target_file = f
                        break
        
        if not target_file:
            return -1, 0

        # 2. Dosyayı Oku ve Global Senkronizasyon Yap
        tactic_path = os.path.join(tactic_dir, target_file)
        sync_count = 0

        try:
            async with database.get_db() as db:
                db.row_factory = aiosqlite.Row
                
                # --- SOURCE OF TRUTH: ESKİ KADROYU SİL/BOŞALT ---
                # Takımdaki her oyuncuyu boşa çıkarıyoruz ki dosyadakiyle çakışmasın.
                await db.execute("UPDATE players SET team = NULL WHERE LOWER(team) = LOWER(?)", (target_team,))
                
                # TÜM LİGİ HAFIZAYA ÇEK (Global Eşleşme Garantisi)
                async with db.execute("SELECT id, name, team FROM players") as cursor:
                    all_players = await cursor.fetchall()
                
                # Global Harita (Normalize İsim -> Player Dict)
                global_map = {self._clean_player_name(p['name']): p for p in all_players}
                
                with open(tactic_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if "|" not in line: continue
                        
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) < 2: continue
                        
                        # PARSE LOGIC (Ultra-Smart)
                        raw_name = parts[0]
                        if ":" in raw_name: raw_name = raw_name.split(":", 1)[1].strip()
                        p_name_norm = self._clean_player_name(raw_name)
                        
                        # Temel Veriler (Varsayılanlar)
                        pos = parts[1] if len(parts) >= 2 else "Bilinmiyor"
                        age_str = parts[2] if len(parts) >= 3 else "25"
                        age_match = re.search(r'\d+', age_str)
                        age = int(age_match.group()) if age_match else 25
                        
                        # Değer Ayıkla (Daha Esnek)
                        pd_str = ""
                        if len(parts) >= 4: pd_str = parts[3]
                        elif len(parts) >= 3: pd_str = parts[2]
                        
                        mv_val = database.parse_market_value(pd_str)

                        if not p_name_norm: continue

                        # Karar Verme Mekanizması
                        if p_name_norm in global_map:
                            p_db = global_map[p_name_norm]
                            # Oyuncuyu bulduk, takımını target_team yap ve değerini güncelle
                            await db.execute(
                                "UPDATE players SET team = ?, market_value = ?, position = ?, age = ? WHERE id = ?",
                                (target_team, mv_val, pos, age, p_db['id'])
                            )
                            sync_count += 1
                        else:
                            # 3. Oyuncu Yok mu? (Create)
                            ovr_basis = database.estimate_player_ovr(mv_val)
                            nat = parts[4] if len(parts) >= 5 else "Bilinmiyor"
                            await db.execute(
                                "INSERT INTO players (name, team, position, age, nationality, market_value, overall, goals, assists) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)",
                                (raw_name, target_team, pos, age, nat, mv_val, ovr_basis)
                            )
                            sync_count += 1
                            
                await db.commit()

            # Reytingleri yeniden hesapla
            await database.calculate_team_overall(target_team)
            return sync_count, 0
        except Exception as e:
            print(f"DEBUG PD Sync Error for {target_team}: {e}")
            return 0, 0


    @commands.command(name="butce", aliases=["bütçe", "kasa", "para"])
    async def butce_command(self, ctx: commands.Context, *, team_name: str = None):
        """Kendi bütçeni veya (yetkiliysen) bir takımın bütçesini gör"""
        if team_name and ctx.author.guild_permissions.administrator:
            # Yetkililer başka takımların bütçesini görebilir
            team_data = await database.search_team(team_name)
            if not team_data:
                return await ctx.send(f"❌ **{team_name}** bulunamadı.")
        else:
            # Diğerleri sadece kendi takımlarının bütçesini görebilir
            team_data = await database.get_user_team(ctx.author.id)
            if not team_data:
                return await ctx.send("❌ **Henüz bir takımı yönetmiyorsun!**\n👉 `!takimsec [Takım]`")
        
        budget = team_data.get('budget', 0)
        embed = discord.Embed(
            title="💰 KULÜP FİNANS PANELİ",
            description=f"🏟️ **Kulüp:** `{team_data['name'].upper()}`\n━━━━━━━━━━━━━━━━━━━━",
            color=discord.Color.gold()
        )
        embed.add_field(name="💼 Mevcut Kasa", value=f"### 💵 {self._format_value(budget)}", inline=False)
        embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/3135/3135706.png")
        embed.set_footer(text="💡 Primler ve giderler otomatik olarak bu bakiyeden düşülür.")
        await ctx.send(embed=embed)

    @commands.command(name="butce_ayarla", aliases=["setbudget", "bütçe_ayarla", "parayükle"])
    @commands.has_permissions(administrator=True)
    async def butce_ayarla_command(self, ctx: commands.Context, team_name: str, amount_str: str):
        """Bir takımın bütçesini direkt olarak ayarlar (Admin)"""
        team_data = await database.search_team(team_name)
        if not team_data:
            return await ctx.send(f"❌ **{team_name}** bulunamadı.")
        
        amount = self._parse_money(amount_str)
        await database.set_team_budget(team_data['name'], amount)
        
        await ctx.send(f"✅ **Bütçe Güncellendi!**\n🏟️ **Takım:** {team_data['name']}\n💰 **Yeni Bütçe:** {self._format_value(amount)}")

    @commands.command(name="paragonder", aliases=["paragönder", "gönder", "transfer_para"])
    async def paragonder_command(self, ctx: commands.Context, hedef_takim_adi: str, miktar_str: str):
        """Kendi bütçenden başka bir takıma para gönderir"""
        # 1. Gönderen takımı bul
        user_team = await database.get_user_team(ctx.author.id)
        if not user_team:
            return await ctx.send("❌ **Henüz bir takımı yönetmiyorsun!**\n👉 `!takimsec [Takım Adı]`")
        
        from_team_name = user_team['name']
        
        # 2. Miktarı işle
        amount = self._parse_money(miktar_str)
        if amount <= 0:
            return await ctx.send("❌ **Geçersiz miktar!** Lütfen pozitif bir değer girin (Örn: 5M).")
        
        # 3. Hedef takımı bul (Aramayı genişletelim)
        target_team_data = await database.search_team(hedef_takim_adi)
        if not target_team_data:
            return await ctx.send(f"❌ **Hedef takım ({hedef_takim_adi}) bulunamadı.**")
        
        to_team_name = target_team_data['name']
        
        if from_team_name == to_team_name:
            return await ctx.send("❌ **Kendi kendine para gönderemezsin!**")

        # 4. Transferi gerçekleştir
        success, message = await database.transfer_team_budget(from_team_name, to_team_name, amount)
        
        if success:
            embed = discord.Embed(
                title="💸 KULÜPLER ARASI EFT/TRANSFER",
                description="✅ Finans birimi işlemi onayladı.",
                color=discord.Color.green()
            )
            embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/3135/3135768.png")
            embed.add_field(name="📤 Gönderen", value=f"`{from_team_name}`", inline=True)
            embed.add_field(name="📥 Alıcı", value=f"`{to_team_name}`", inline=True)
            embed.add_field(name="💰 Miktar", value=f"### {self._format_value(amount)}", inline=False)
            embed.add_field(name="💼 Yeni Bakiye", value=self._format_value(user_team['budget'] - amount), inline=False)
            embed.set_footer(text=f"Tarih: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"❌ **Transfer Başarısız!**\n{message}")


    @commands.command(name="teklif")
    async def teklif_command(self, ctx: commands.Context, *, content: str):
        pending = self.pending_transfers.get(ctx.author.id)
        if not pending: return await ctx.send("❌ Önce oyuncu araştırmalısın! `!ara [İsim]`")
        
        offer = self._parse_money(content.split()[-1])
        user_team = await database.get_user_team(ctx.author.id)
        if not user_team:
            return await ctx.send("❌ **Henüz bir takımı yönetmiyorsun!**\n👉 `!takimsec [Takım Adı]` komutuyla bir kulübün başına geçmelisin.")
        
        team_name = user_team['name']
        res = await self._negotiate_offer(pending, offer, team_name)
        
        if res['status'] == "Accepted":
            pending['club_agreed'] = True
            pending['agreed_price'] = offer
            advices = ["Yönetim bu hamle için yeşil ışık yaktı.", "Taraftar bu ismi havaalanında bekliyor!", "Bütçe planlaması için harika bir rakam."]
            
            embed = discord.Embed(
                title="🤝 KULÜPLE ANLAŞMA SAĞLANDI!",
                description=f"🗣️ **{pending['current_team']}:** \"{res['msg']}\"",
                color=discord.Color.green()
            )
            embed.add_field(name="💰 Anlaşılan Bedel", value=f"**{self._format_value(offer)}**", inline=True)
            embed.add_field(name="📰 Son Dakika", value=f"_{random.choice(advices)}_", inline=False)
            embed.set_footer(text=f"👉 Sonraki Adım: !maas {pending['player_name']} [Miktar]")
            await ctx.send(embed=embed)
            
        elif res['status'] == "Counter":
            pending['last_club_counter'] = res['val']
            pending['highest_user_offer'] = max(offer, pending.get('highest_user_offer', 0))
            
            embed = discord.Embed(
                title="⚖️ KARŞI TEKLİF GELDİ!",
                description=f"🗣️ **{pending['current_team']}:** \"{res['msg']}\"",
                color=discord.Color.orange()
            )
            embed.add_field(name="📉 Talep Edilen", value=f"**{self._format_value(res['val'])}**", inline=True)
            embed.add_field(name="📤 Sizin Teklifiniz", value=self._format_value(offer), inline=True)
            embed.set_footer(text=f"👉 Cevap Ver: !teklif {pending['player_name']} [Miktar] veya !kabulet")
            await ctx.send(embed=embed)
            
        else:
            embed = discord.Embed(
                title="❌ MASADAN KALKILDI!",
                description=f"🗣️ **{pending['current_team']}:** \"{res['msg']}\"",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            self._set_refusal(ctx.author.id, pending['player_name'])
            self.pending_transfers.pop(ctx.author.id, None)

    @commands.command(name="maas")
    async def maas_command(self, ctx: commands.Context, *, content: str):
        pending = self.pending_transfers.get(ctx.author.id)
        if not pending or not pending.get('club_agreed'): return await ctx.send("❌ Önce kulüple anlaşmalısın!")
        
        offer = self._parse_money(content.split()[-1])
        user_team = await database.get_user_team(ctx.author.id)
        if not user_team:
            return await ctx.send("❌ **Henüz bir takımı yönetmiyorsun!**")
        
        res = await self._negotiate_salary(pending, offer, user_team['name'])
        
        if res['status'] == "Accepted":
            pending['player_agreed'] = True
            pending['final_salary'] = offer
            
            embed = discord.Embed(
                title="✅ OYUNCU TEKLİFİ KABUL ETTİ!",
                description=f"🗣️ **{pending['player_name']}:** \"{res['msg']}\"",
                color=discord.Color.green()
            )
            embed.add_field(name="💶 Anlaşılan Maaş", value=f"**{self._format_value(offer)}** / Yıl", inline=True)
            embed.set_footer(text=f"🚀 Transferi Bitir: !onayla {pending['player_name']}")
            await ctx.send(embed=embed)
            
        elif res['status'] == "Counter":
            pending['last_p_counter'] = res['val']
            
            embed = discord.Embed(
                title="⚖️ OYUNCUDAN KARŞI TEKLİF!",
                description=f"🗣️ **{pending['player_name']}:** \"{res['msg']}\"",
                color=discord.Color.purple()
            )
            embed.add_field(name="📉 İstediği Maaş", value=f"**{self._format_value(res['val'])}**", inline=True)
            embed.add_field(name="📤 Sizin Teklifiniz", value=self._format_value(offer), inline=True)
            embed.set_footer(text=f"👉 Yeni Teklif: !maas {pending['player_name']} [Miktar] veya !kabulet")
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title="❌ OYUNCU MASADAN KALKTI!",
                description=f"🗣️ **{pending['player_name']}:** \"{res['msg']}\"",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            self._set_refusal(ctx.author.id, pending['player_name'])
            self.pending_transfers.pop(ctx.author.id, None)

    @commands.command(name="kirala", aliases=["kiralik", "loan"])
    async def kirala_command(self, ctx: commands.Context, *, content: str):
        """Bir oyuncuyu kiralamak için teklif verir (Yaş ve rol duyarlı)"""
        pending = self.pending_transfers.get(ctx.author.id)
        if not pending: return await ctx.send("❌ Önce oyuncu araştırmalısın! `!ara [İsim]`")
        
        offer = self._parse_money(content.split()[-1])
        user_team = await database.get_user_team(ctx.author.id)
        if not user_team:
            return await ctx.send("❌ **Henüz bir takımı yönetmiyorsun!**")
        
        pending['is_loan_offer'] = True
        res = await self._negotiate_loan(pending, offer, user_team['name'])
        
        if res['status'] == "Accepted":
            pending['club_agreed'] = True
            pending['agreed_price'] = offer
            pending['transfer_type'] = 'Loan'
            
            embed = discord.Embed(
                title="🤝 KİRALAMA ANLAŞMASI (KULÜP)",
                description=f"🗣️ **{pending['current_team']}:** \"{res['msg']}\"",
                color=discord.Color.blue()
            )
            embed.add_field(name="💰 Kiralama Bedeli", value=f"**{self._format_value(offer)}**", inline=True)
            embed.set_footer(text=f"👉 Sonraki Adım: !maas {pending['player_name']} [Miktar]")
            await ctx.send(embed=embed)
            
        elif res['status'] == "Counter":
            pending['last_club_counter'] = res['val']
            embed = discord.Embed(
                title="⚖️ KİRALAMA KARŞI TEKLİFİ",
                description=f"🗣️ **{pending['current_team']}:** \"{res['msg']}\"",
                color=discord.Color.orange()
            )
            embed.add_field(name="📉 Talep Edilen", value=f"**{self._format_value(res['val'])}**", inline=True)
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"❌ **{pending['current_team']}:** \"{res['msg']}\"")
            self.pending_transfers.pop(ctx.author.id, None)

    @commands.command(name="onayla")
    async def onayla_command(self, ctx: commands.Context, *, name: str = None):
        pending = self.pending_transfers.get(ctx.author.id)
        if not pending or not pending.get('player_agreed'): return await ctx.send("❌ Anlaşma süreci tamamlanmadı.")
        
        user_team = await database.get_user_team(ctx.author.id)
        if not user_team: 
            return await ctx.send("❌ Sahip olduğun bir kulüp yok!")
        
        # Bütçe kontrolü (Final çek)
        if user_team['budget'] < pending['agreed_price']:
            return await ctx.send(f"❌ **YETERSIZ BÜTÇE!** Kasanızda {self._format_value(user_team['budget'])} var, gereken: {self._format_value(pending['agreed_price'])}")

        t_type = pending.get('transfer_type', 'Transfer')
        await database.record_transfer(
            pending['player_name'], 
            pending['current_team'], 
            user_team['name'], 
            pending['agreed_price'], 
            3, 
            player_details=pending,
            transfer_type=t_type
        )
        
        title = "✍️ TRANSFER RESMİLEŞTİ!" if t_type == 'Transfer' else "🤝 KİRALAMA RESMİLEŞTİ!"
        color = discord.Color.gold() if t_type == 'Transfer' else discord.Color.blue()
        
        embed = discord.Embed(
            title=title,
            description=f"🚀 **Hayırlı olsun başkan! {pending['player_name']} artık senin emrinde.**",
            color=color
        )
        embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/3135/3135768.png") # Signature icon
        
        embed.add_field(name="👤 Oyuncu", value=pending['player_name'], inline=True)
        embed.add_field(name="🏟️ Yeni Takım", value=user_team['name'], inline=True)
        
        price_label = "💰 Bonservis" if t_type == 'Transfer' else "💰 Kiralama Bedeli"
        embed.add_field(name=price_label, value=self._format_value(pending['agreed_price']), inline=True)
        embed.add_field(name="💶 Yıllık Maaş", value=self._format_value(pending['final_salary']), inline=True)
        
        if t_type == 'Loan':
            embed.add_field(name="📅 Süre", value="Sezon Sonu", inline=True)
            embed.add_field(name="🏠 Asıl Kulüp", value=pending['current_team'], inline=True)
        
        # 📈 TAKIM REYTINGINI GÜNCELLE
        new_ovr = await database.calculate_team_overall(user_team['name'])
        embed.add_field(name="📈 Takım Reyting Ortalaması", value=f"### {new_ovr}", inline=False)
        embed.set_footer(text=f"💡 İşlem sonrası kadro gücünüz (En İyi 18) yeniden hesaplandı.")

        await ctx.send(embed=embed)
        self.pending_transfers.pop(ctx.author.id)

    @commands.command(name="kabulet", aliases=["kabul", "teklif_kabul"])
    async def kabulet_command(self, ctx: commands.Context):
        """Karşı tarafın (Kulüp veya Oyuncu) son teklifini kabul eder"""
        pending = self.pending_transfers.get(ctx.author.id)
        if not pending:
            return await ctx.send("❌ **Aktif bir görüşme bulunamadı!** Önce `!ara` ile bir oyuncu bulmalısın.")

        # 1. KULÜP TEKLİFİ KABULÜ
        if not pending.get('club_agreed'):
            if pending.get('last_club_counter', 0) > 0:
                price = pending['last_club_counter']
                pending['agreed_price'] = price
                pending['club_agreed'] = True
                
                embed = discord.Embed(
                    title="✅ KULÜBÜN TEKLİFİNİ KABUL ETTİNİZ!",
                    description=f"🗣️ **{pending['current_team']}:** \"Harika, kağıtları hazırlıyoruz.\"",
                    color=discord.Color.green()
                )
                embed.add_field(name="💰 Anlaşılan Bedel", value=f"**{self._format_value(price)}**", inline=True)
                embed.set_footer(text=f"👉 Sonraki Adım: !maas {pending['player_name']} [Miktar]")
                return await ctx.send(embed=embed)
            else:
                # Eğer henüz teklif yapılmadıysa başlangıç bedelini kabul etmeyi denebilir
                # Ama genellikle !teklif ile başlanır. Yine de kolaylık olsun:
                scout_price = int(pending['market_value_eur'] * 1.3) # Default logic
                if "base_asking_with_tax" in pending: scout_price = pending["base_asking_with_tax"]
                
                pending['agreed_price'] = scout_price
                pending['club_agreed'] = True
                return await ctx.send(f"✅ **Kulübün başlangıç talebi olan {self._format_value(scout_price)} kabul edildi.**\n👉 **Şimdi oyuncuyla görüş:** `!maas [Miktar]`")

        # 2. OYUNCU MAAŞ TEKLİFİ KABULÜ
        if pending.get('club_agreed') and not pending.get('player_agreed'):
            if pending.get('last_p_counter', 0) > 0:
                salary = pending['last_p_counter']
                pending['final_salary'] = salary
                pending['player_agreed'] = True
                
                embed = discord.Embed(
                    title="✍️ OYUNCUNUN MAAŞ TALEBİNİ KABUL ETTİNİZ!",
                    description=f"🗣️ **{pending['player_name']}:** \"Şartlar benim için uygun, imzaya hazırım!\"",
                    color=discord.Color.green()
                )
                embed.add_field(name="💶 Anlaşılan Maaş", value=f"**{self._format_value(salary)}**", inline=True)
                embed.set_footer(text="🚀 Sonraki Adım: !onayla")
                return await ctx.send(embed=embed)
            else:
                return await ctx.send("❌ **Oyuncu henüz bir maaş talebinde bulunmadı.** Önce `!maas [Miktar]` ile bir teklif yapmalısın.")

        await ctx.send("❌ **Şu an kabul edilecek yeni bir karşı teklif yok.**")

    # ===============================================
    #  OYUNCU SATIŞ SİSTEMİ (LOCAL)
    # ===============================================

    @commands.command(name="oyuncusat", aliases=["sat"])
    async def oyuncusat_command(self, ctx: commands.Context, *, player_name: str):
        # --- RED KONTROLÜ ---
        if self._check_refusal(ctx.author.id, player_name):
            return await ctx.send(f"❌ **{player_name}** şu an kulüpten ayrılmak istemiyor. (24 saatlik bekleme süresi)")

        user_team = await database.get_user_team(ctx.author.id)
        if not user_team: 
            return await ctx.send("❌ **Sana ait bir takım yok!**\n👉 `!takimsec [Takım]` komutuyla bir kulübü devralabilirsin.")
        
        team_name = user_team['name']
        
        # 1. Önce taktik dosyasından (Lokal) Veri Al
        raw_target = await self._get_local_player_data(player_name, team_name)
        target = self._normalize_scout_data(raw_target)
        
        # 2. Dosyada yoksa DB'den (yedeklerden) bak
        if not target or target.get('player_name') == "Bilinmeyen Oyuncu":
            players = await database.get_players_by_team(team_name)
            p_data = next((p for p in players if player_name.lower() in p['name'].lower()), None)
            if p_data:
                target = self._normalize_scout_data({
                    "player_name": p_data['name'],
                    "age": p_data['age'],
                    "market_value_eur": p_data['market_value'],
                    "current_team": team_name,
                    "overall": p_data.get('overall', 75),
                    "position": p_data.get('position', 'ST')
                })
        
        if not target or target.get('player_name') == "Bilinmeyen Oyuncu": 
            return await ctx.send("❌ Bu oyuncu senin kadrende veya taktik dosyasında bulunmuyor.")
        
        # Dinamik Fiyat Hesapla
        final_value = await self._calculate_dynamic_price(
            target.get('market_value_eur', 5000000), 
            target.get('age', 25), 
            team_name
        )
        
        buyer = random.choice(["Brentford", "Lyon", "Sevilla", "Lille", "Monaco", "Brighton", "Everton", "Lazio", "Aston Villa", "Napoli"])
        # --- ÖLCÜCÜ ALICI MANTIĞI (%20 Altı, Genç/Prime ise %10 Altı) ---
        try:
            player_age = int(target.get('age', 25))
        except:
            player_age = 25
            
        is_valuable = player_age < 23 or (24 <= player_age <= 29)
        
        discount = 0.9 if is_valuable else 0.8
        offer = int(final_value * discount)
        
        self.pending_sales[ctx.author.id] = {
            'p_name': target.get('player_name', 'Bilinmeyen Oyuncu'), 
            'buyer': buyer, 
            'offer': offer, 
            'initial_offer': offer, # Cap kontrolü için
            'market': final_value,
            'age': player_age, # Artık yaş bilgisini tutuyoruz
            'patience': 5 # --- SABIR LİMİTİ ---
        }
        
        # Fiyat Bilgilendirme (Breakdown)
        bonus_val = final_value - target.get('market_value_eur', 0)
        breakdown = f"({self._format_value(target.get('market_value_eur', 0))} Baz + {self._format_value(bonus_val)} Form/Yaş)"
        
        embed = discord.Embed(
            title="💶 OYUNCU SATIŞ TALEBİ",
            description=f"📰 **{buyer}**, oyuncunuz **{target.get('player_name', 'Bilinmeyen Oyuncu')}** için masada!",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/3135/3135706.png") # Cash icon
        
        embed.add_field(name="👤 Oyuncu", value=f"{target['player_name']} ({target['age']} Yaş)", inline=True)
        embed.add_field(name="🏟️ Piyasa Değeri", value=self._format_value(target['market_value_eur']), inline=True)
        embed.add_field(name="📈 Dinamik Değer", value=f"**{self._format_value(final_value)}**", inline=True)
        
        embed.add_field(name="📥 Gelen Teklif", value=f"⭐ **{self._format_value(offer)}**", inline=False)
        
        embed.set_footer(text="👉 Kabul et: !satisonayla | Pazarlık Et: !fiyatiste [Miktar]")
        await ctx.send(embed=embed)

    @commands.command(name="fiyatiste")
    async def fiyatiste_command(self, ctx: commands.Context, miktar: str):
        sale = self.pending_sales.get(ctx.author.id)
        if not sale: return await ctx.send("❌ Aktif bir satış görüşmen bulunmuyor.")
        
        asked = self._parse_money(miktar)
        initial = sale['initial_offer']

        # --- ABSÜRT FİYAT KONTROLÜ (%70 ve üzeri fazlalık) ---
        if asked > initial * 1.7:
            angry_msgs = [
                f"❌ **{sale['buyer']}:** \"Lan sen bizi enayi mi sandın? {self._format_value(asked)} nedir? Yürü git başka kapıya!\"",
                f"❌ **{sale['buyer']}:** \"Dalga mı geçiyorsun başkan? Bu paraya kulübü satın alırız. Görüşmeler bitmiştir!\"",
                f"❌ **{sale['buyer']}:** \"Şaka mı yapıyorsun? Bu terbiyesizlikten sonra masadan kalkıyoruz!\"",
                f"❌ **{sale['buyer']}:** \"Sen ne diyorsun dayı? {self._format_value(asked)} ne? Defol git işine, biz yokuz!\""
            ]
            self.pending_sales.pop(ctx.author.id)
            return await ctx.send(random.choice(angry_msgs))
        
        # --- YAŞA GÖRE KAPASİTE (%25 vs %10) ---
        age = sale.get('age', 25)
        cap_pct = 0.25 if age < 25 else 0.10
        max_limit = int(initial * (1 + cap_pct))

        # --- SABIR KONTROLÜ ---
        sale['patience'] -= 1
        if sale['patience'] <= 0:
            await ctx.send(f"❌ **{sale['buyer']}:** \"Sabrımızı zorladınız başkan. Başka kapıya, masadan kalkıyoruz!\"")
            return self.pending_sales.pop(ctx.author.id)

        # Alıcının yeni teklifi (Daha yumuşak bir pazarlık için 2.1 böleni)
        calc_offer = int((sale['offer'] + asked) / 2.1)
        
        # --- TABAN KONTROLÜ (Teklifin çakılmasını engelle) ---
        # Yeni teklif öncekinden çok düşük olamaz (Kaza ile düşük girme koruması)
        new_offer = max(calc_offer, int(sale['offer'] * 0.95))
        
        # --- KESİN LİMİT ---
        if new_offer > max_limit:
            new_offer = max_limit
            limit_text = "%25" if age < 25 else "%10"
            msg = f"🔄 **{sale['buyer']}:** \"İlk teklifimizin üzerine en fazla {limit_text} çıkabiliriz. Son rakamımız **{self._format_value(new_offer)}**. (Kalan Sabır: {sale['patience']})\""
        elif new_offer <= sale['offer']:
             # Eğer formül gereği artış olmadıysa (User çok yüksek istedi ama formül düşük kaldı), sembolik +%1 artış yap
             new_offer = int(sale['offer'] * 1.01)
             msg = f"🔄 **{sale['buyer']}:** \"Biraz daha ikna olduk. Teklifimizi **{self._format_value(new_offer)}** noktasına çektik. (Kalan Sabır: {sale['patience']})\""
        else:
            msg = f"🔄 **{sale['buyer']}:** \"Teklifimizi **{self._format_value(new_offer)}** noktasına güncelledik. (Kalan Sabır: {sale['patience']})\""

        sale['offer'] = new_offer
        await ctx.send(f"{msg}\n👉 `!satisonayla` veya `!fiyatiste` ")

    @commands.command(name="satisonayla")
    async def satisonayla_command(self, ctx: commands.Context):
        sale = self.pending_sales.pop(ctx.author.id, None)
        if not sale: return await ctx.send("❌ Onaylanacak bir satış yok.")
        
        user_team = await database.get_user_team(ctx.author.id)
        if not user_team: return await ctx.send("❌ Takımın yok!")

        # --- DB KONTROLÜ (Oyuncu hala takımıda mı?) ---
        p_db = await database.get_player(sale['p_name'], user_team['name'])
        if not p_db:
             # Taktik dosyasında da olabilir ama DB'de başka takımdaysa satamaz
             actual_p = await database.get_player(sale['p_name'])
             if actual_p and actual_p['team'] != user_team['name']:
                 return await ctx.send(f"❌ **HATA:** {sale['p_name']} zaten başka bir takıma ({actual_p['team']}) transfer olmuş!")

        # --- %20 OYUNCU REDDİ (Gitmiyorum Şansı - Balance Update) ---
        if random.random() < 0.20:
            refusal_msgs = [
                f"❌ **{sale['p_name']}:** \"Başkanım ben burada mutluyum, hiçbir yere gitmiyorum!\"",
                f"❌ **{sale['p_name']}:** \"Kulübe olan bağlılığım paradan önce gelir. Bu transferi reddediyorum.\"",
                f"❌ **{sale['p_name']}:** \"Taraftarı ve bu formayı bırakmaya niyetim yok. Gitmiyorum!\"",
                f"❌ **{sale['p_name']}:** \"Ben gitmicem! Kariyerime burada devam etmek istiyorum.\"",
                f"❌ **{sale['p_name']}:** \"Ailem ve ben burayı çok sevdik. Başka bir kulübe sıcak bakmıyorum.\""
            ]
            self.pending_sales.pop(ctx.author.id, None)
            self._set_refusal(ctx.author.id, sale['p_name'])
            return await ctx.send(random.choice(refusal_msgs))
        
        success = await database.record_transfer(sale['p_name'], user_team['name'], sale['buyer'], sale['offer'], 3)
        
        if not success:
            return await ctx.send(f"❌ **TRANSFER İPTAL EDİLDİ!** {sale['p_name']} şu an kadronuzda görünmüyor. Başka bir kulübe gitmiş olabilir.")

        # --- TAKTİK DOSYASINDAN SİL (Otomatik Senk) ---
        await self._remove_player_from_tactic_file(user_team['name'], sale['p_name'])
        
        await ctx.send(f"✅ **GÜLE GÜLE!** {sale['p_name']}, {sale['buyer']} kulübüne satıldı. Kasa doldu! 💰")

async def setup(bot):
    await bot.add_cog(TransferCog(bot))
