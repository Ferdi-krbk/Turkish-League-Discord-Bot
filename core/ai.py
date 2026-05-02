import json
import asyncio
import re
import ast
import random
import aiohttp
import os
from typing import Dict, Any, Optional, List
from google import genai
from google.genai import types
import config

class AIManager:
    """
    Central manager for AI model calls with multi-tier fallback (cascade),
    retries, and advanced JSON healing capability.
    """

    def __init__(self):
        self.api_key = getattr(config, 'GEMINI_API_KEY', "")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

        self.groq_key = os.getenv("GROQ_API_KEY", "") or getattr(config, "GROQ_API_KEY", "")
        self.groq_model = getattr(config, "GROQ_MODEL", "llama-3.3-70b-versatile")
        self.groq_models = getattr(config, "GROQ_MODELS", ["llama-3.3-70b-versatile", "llama3-70b-8192"])
        
        # New: Elite Local Fallback Toggle
        self.prefer_local = getattr(config, "PREFER_LOCAL_FALLBACK", True)

        self.or_key = getattr(config, 'OPENROUTER_API_KEY', "")
        self.or_models_long = getattr(config, 'OPENROUTER_MODELS', None)
        if not isinstance(self.or_models_long, list) or not self.or_models_long:
            self.or_models_long = [getattr(config, 'OPENROUTER_MODEL', "openrouter/free")]

        self.or_models_fast = getattr(config, 'OPENROUTER_MODELS_FAST', None)
        if not isinstance(self.or_models_fast, list) or not self.or_models_fast:
            self.or_models_fast = ["openrouter/free"]

    @staticmethod
    def _est_tokens_from_text(s: str) -> int:
        if not s:
            return 0
        return int(len(s) / 4)

    @staticmethod
    def _shrink_between_markers(text: str, start: str, end: str, keep_head: int, keep_tail: int) -> str:
        if not text:
            return text
        out = text
        idx = 0
        while True:
            s = out.find(start, idx)
            if s == -1:
                break
            e = out.find(end, s + len(start))
            if e == -1:
                break
            block = out[s:e + len(end)]
            if len(block) > keep_head + keep_tail + 200:
                head = block[:keep_head]
                tail = block[-keep_tail:]
                block2 = head + "\n...[TRIMMED_FOR_GROQ]...\n" + tail
                out = out[:s] + block2 + out[e + len(end):]
                idx = s + len(block2)
            else:
                idx = e + len(end)
        return out

    def _shrink_prompt_for_groq(self, prompt: str, system: str) -> tuple[str, str]:
        p = prompt or ""
        s = system or ""
        p = self._shrink_between_markers(p, "[BAŞLANGIÇ_EV_SAHİBİ]", "[BİTİŞ_EV_SAHİBİ]", keep_head=1400, keep_tail=900)
        p = self._shrink_between_markers(p, "[BAŞLANGIÇ_DEPLASMAN]", "[BİTİŞ_DEPLASMAN]", keep_head=1400, keep_tail=900)
        max_est = getattr(config, "GROQ_MAX_REQUEST_TOKENS_EST", 6000)
        max_chars = max_est * 4
        total = len(p) + len(s)
        if total > max_chars:
            keep_prompt = max(3000, max_chars - len(s))
            if len(p) > keep_prompt:
                p = "[TRIMMED_FOR_GROQ_ABSOLUTE_CAP]\n" + p[-keep_prompt:]
        return p, s

    def _hard_cap_for_groq(self, prompt: str, system: str) -> tuple[str, str]:
        p = prompt or ""
        s = system or ""
        p = self._shrink_between_markers(p, "[BAŞLANGIÇ_EV_SAHİBİ]", "[BİTİŞ_EV_SAHİBİ]", keep_head=700, keep_tail=500)
        p = self._shrink_between_markers(p, "[BAŞLANGIÇ_DEPLASMAN]", "[BİTİŞ_DEPLASMAN]", keep_head=700, keep_tail=500)
        p = self._shrink_between_markers(p, "=== GÜNCEL KADROLAR", "Sen profesyonel", keep_head=800, keep_tail=300)
        max_est = getattr(config, "GROQ_MAX_REQUEST_TOKENS_EST", 5500)
        max_chars = max_est * 4
        if len(s) > 2400:
            s = s[:2400] + "\n...[TRIMMED_SYSTEM_FOR_GROQ]..."
        keep_prompt = max(2400, max_chars - len(s))
        if len(p) > keep_prompt:
            p = "[HARD_TRIMMED_FOR_GROQ]\n" + p[-keep_prompt:]
        return p, s

    async def _query_groq(
        self,
        prompt: str,
        system: str,
        temp: float,
        max_tokens: int,
        timeout: int = 30,
        is_json: bool = False,
    ) -> Optional[str]:
        if not self.groq_key:
            return None
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_key}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "model": self.groq_model,
            "messages": [
                {"role": "system", "content": system or ""},
                {"role": "user", "content": prompt or ""},
            ],
            "temperature": temp,
            "max_tokens": max_tokens,
        }
        if is_json:
            # Groq REQUIREMENT: Must contain the word 'json' in some form to use json_object
            # ENHANCEMENT: Use a strict English instruction for better Llama 3 compliance
            json_instruction = "Return ONLY valid JSON. Do not include any explanations, markdown, or text outside the JSON object."
            if "json" not in (system or "").lower():
                system = ((system + "\n\n") if system else "") + json_instruction
            else:
                system = system + "\n\n" + json_instruction
            payload["response_format"] = {"type": "json_object"}
            
        try:
            async with aiohttp.ClientSession() as session:
                max_est = getattr(config, "GROQ_MAX_REQUEST_TOKENS_EST", 5600)
                # Recalculate EST with possible JSON instruction
                est = self._est_tokens_from_text((system or "") + (prompt or ""))
                active_prompt, active_system = prompt, system
                if est > max_est:
                    print(f"DEBUG: [{label}] [Groq] İstek çok büyük ({est} token), budanıyor...")
                    active_prompt, active_system = self._shrink_prompt_for_groq(prompt, system)
                
                payload["messages"] = [
                    {"role": "system", "content": active_system or ""},
                    {"role": "user", "content": active_prompt or ""},
                ]
                for g_model in self.groq_models:
                    payload["model"] = g_model
                    for attempt in range(2):
                        try:
                            async with session.post(url, headers=headers, json=payload, timeout=timeout) as resp:
                                if resp.status == 200:
                                    data = await resp.json()
                                    return data["choices"][0]["message"]["content"]
                                elif resp.status == 429: # Rate limit
                                    if attempt == 0: await asyncio.sleep(2); continue
                                    else: break
                                elif resp.status == 400:
                                    err_text = await resp.text()
                                    # Fallback: If JSON validation fails, try regular text mode
                                    if "json_validate_failed" in err_text and "response_format" in payload:
                                        print(f"DEBUG: [Groq] JSON Validation failed for {g_model}. Retrying in text mode...")
                                        del payload["response_format"]
                                        # Force a different temperature for the retry to increase chances of success
                                        payload["temperature"] = 0.2
                                        continue 
                                    print(f"DEBUG: [Groq] HTTP 400 Hatasi: {err_text[:200]}")
                                    break
                                else:
                                    err_text = await resp.text()
                                    print(f"DEBUG: [Groq] HTTP {resp.status} Hatasi: {err_text[:200]}")
                                    if resp.status in [413, 403]: # Too Large or Forbidden
                                        return None
                                    break
                        except asyncio.TimeoutError:
                            print(f"DEBUG: [Groq] {g_model} zaman aşımına uğradı.")
                            continue
                        except Exception as e:
                            print(f"DEBUG: [Groq] {g_model} İstek Hatasi ({type(e).__name__}): {e}")
                            break
        except Exception as e:
            print(f"DEBUG: [Groq] Genel Hata: {e}")
        return None

    @staticmethod
    def _is_retryable_gemini_error(err: str) -> bool:
        if not err: return False
        err_u = err.upper()
        return any(x in err_u for x in ["503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "OVERLOADED", "TOO MANY REQUESTS", "RATE LIMIT"])

    def clean_json(self, text: str) -> str:
        """Markdown bloklarını ve JSON dışı metinleri temizleyerek saf JSON döndürür."""
        if not text: return ""
        text = text.strip()
        
        # 1. Kod bloğu ayıklama (```json ... ``` veya ``` ... ```)
        match = re.search(r"```(?:json|python|text)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if match:
            text = match.group(1).strip()
            
        # 2. JSON Başlangıç ve Bitişini Bul (Daha Esnek)
        start_obj = text.find('{')
        start_list = text.find('[')
        
        if start_obj == -1 and start_list == -1:
            return text.strip()
            
        if start_obj == -1: start = start_list
        elif start_list == -1: start = start_obj
        else: start = min(start_obj, start_list)
        
        end_obj = text.rfind('}')
        end_list = text.rfind(']')
        end = max(end_obj, end_list)
        
        if start != -1 and end != -1 and end > start:
            inner = text[start:end+1]
            # Extra cleanup for pythonic leftovers in text mode
            inner = inner.replace('TRUE', 'true').replace('FALSE', 'false').replace('NULL', 'null')
            return inner
            
        return text.strip()

    def repair_json(self, s: str) -> str:
        """Kırpılmış veya eksik JSON bloklarını tamir eder."""
        s = s.strip()
        if not s: return ""
        
        # Eğer tırnakla bitiyorsa ama virgül/parantez yoksa, kapatmayı dene
        if s.endswith('"') and not s.endswith(('}"', ']"')):
            # Bu durum genelde bir stringin içinde kesildiğini gösterir
            pass

        # Balans kontrolü ile eksik parantezleri kapat
        stack = []
        in_string = False
        escape = False
        
        processed_s = ""
        for char in s:
            if char == '"' and not escape:
                in_string = not in_string
            
            if not in_string:
                if char == '{': stack.append('}')
                elif char == '[': stack.append(']')
                elif char == '}':
                    if stack and stack[-1] == '}': stack.pop()
                elif char == ']':
                    if stack and stack[-1] == ']': stack.pop()
            
            escape = (char == '\\' and not escape)
            processed_s += char
            
        if in_string:
            processed_s += '"' # Tırnağı kapat
            
        if stack:
            processed_s += ''.join(reversed(stack))
            
        return processed_s

    async def _simulate_local_algorithmic(self, prompt: str, label: str = "LOCALSIM") -> Dict[str, Any]:
        """Hyper-Realistic Local Engine (Tactical)"""
        print(f"DEBUG: [{label}] Yerel Motor Devreye Giriyor...")

        # 1. Veri Ayıklama (Gelişmiş Regex)
        try:
            teams = re.findall(r"(?i)(?:MAÇ:|EV SAHİBİ:)\s*(.*?)\s+(?:vs|DEPLASMAN:)\s*(.*?)(?:\n|\||$)", prompt)
            home_team = teams[0][0].strip() if teams else "Ev Sahibi"
            away_team = teams[0][1].strip() if teams else "Deplasman"

            gpr_a, gpr_b = 50.0, 50.0
            g_match = re.search(r"GPR(?:[^\d]*(\d+\.?\d*)[^\d]*(\d+\.?\d*))?", prompt)
            if g_match and g_match.group(1):
                gpr_a = float(g_match.group(1))
                gpr_b = float(g_match.group(2))

            def get_players(text):
                players = []
                for line in text.split('\n'):
                    if '|' in line:
                        parts = line.split('|')
                        name = parts[0].replace('•', '').strip()
                        name = re.sub(r'^\d+[\.\)]\s*', '', name)
                        pos = parts[1].strip().upper() if len(parts) > 1 else "CM"
                        if name and len(name) > 2:
                            players.append({"name": name, "pos": pos})
                return players

            s_a = re.findall(r"\[BAŞLANGIÇ_EV_SAHİBİ\](.*?)\[BİTİŞ_EV_SAHİBİ\]", prompt, re.DOTALL)
            s_b = re.findall(r"\[BAŞLANGIÇ_DEPLASMAN\](.*?)\[BİTİŞ_DEPLASMAN\]", prompt, re.DOTALL)
            
            if not s_a:
                s_a = re.findall(r"SQUAD\s+A:.*?\n(.*?)(?=\n\n|\nSQUAD\s+B|$)", prompt, re.DOTALL)
                s_b = re.findall(r"SQUAD\s+B:.*?\n(.*?)(?=\n\n|\nImportance|$)", prompt, re.DOTALL)

            p_a_all = get_players(s_a[0]) if s_a else []
            p_b_all = get_players(s_b[0]) if s_b else []
            
            if not p_a_all and not p_b_all:
                all_p = get_players(prompt)
                if len(all_p) >= 11:
                    p_a_all = all_p[:len(all_p)//2]
                    p_b_all = all_p[len(all_p)//2:]

            if not p_a_all: p_a_all = [{"name": f"{home_team} Oyuncusu", "pos": "ST"}]
            if not p_b_all: p_b_all = [{"name": f"{away_team} Oyuncusu", "pos": "ST"}]
            
            active_a, bench_a = p_a_all[:11], p_a_all[11:]
            active_b, bench_b = p_b_all[:11], p_b_all[11:]

            # --- SENARYO FARKINDALIĞI (Scenario-Awareness) ---
            match_flow = re.search(r"(?i)MA\w\wN AKI\w SENARYOSU.*?: (.*?)(?:\n|$)", prompt)
            match_flow = match_flow.group(1).strip() if match_flow else ""
            
            luck_scenario = re.search(r"(?i)(?:ZEL KOUL|ANS FAKT|KO\wUL).*?: (.*?)(?:\n|$)", prompt)
            luck_scenario = luck_scenario.group(1).strip() if luck_scenario else ""
            
            chaos_lvl = re.search(r"KAOS SEVİYESİ: (\d+)", prompt)
            chaos_val = int(chaos_lvl.group(1)) if chaos_lvl else 5

            modifiers = {
                "force_late": any(x in match_flow.upper() or x in luck_scenario.upper() for x in ["SON DAKİKA", "90+", "YIKIMI", "ADALET", "ŞOKU"]),
                "early_blitz": "ERKEN BLITZ" in match_flow.upper(),
                "chaos_boost": chaos_val > 7 or "GOL YAĞMURU" in match_flow.upper(),
                "defensive_nerf": "STOPERLER" in luck_scenario.upper() and "HATA" in luck_scenario.upper(),
                "physical_game": any(x in match_flow.upper() for x in ["KEMİK SESLERİ", "SERT", "GERGİN"]),
                "goalkeeper_show": "KALECİLERİN DÜELLOSU" in match_flow.upper()
            }
            if match_flow: print(f"DEBUG: [{label}] Tespit Edilen Senaryo: {match_flow}")
            if luck_scenario: print(f"DEBUG: [{label}] Tespit Edilen Şans: {luck_scenario}")

        except Exception as e:
            print(f"DEBUG: LocalSim Data Extraction Error: {e}")
            home_team, away_team = "Ev Sahibi", "Deplasman"
            gpr_a, gpr_b = 50.0, 50.0
            active_a, active_b = [{"name": "Ev Sahibi Oyuncusu", "pos": "ST"}], [{"name": "Deplasman Oyuncusu", "pos": "ST"}]
            bench_a, bench_b = [], []
            modifiers = {"force_late": False, "early_blitz": False, "chaos_boost": False, "defensive_nerf": False, "physical_game": False, "goalkeeper_show": False}

        # 2. Atmosfer ve Simülasyon Değişkenleri
        atmospheres = [
            {"name": "Normal", "weights": [15, 35, 20, 15, 10], "desc": "Sakin bir atmosferde maç başlıyor."},
            {"name": "Gergin", "weights": [12, 30, 25, 25, 18], "desc": "Hava çok gergin, tribünler her pozisyonda ayakta!"},
            {"name": "Derbi Havası", "weights": [18, 40, 15, 15, 12], "desc": "Tam bir derbi atmosferi! Tempo çok yüksek."},
            {"name": "Kaotik", "weights": [10, 25, 30, 20, 30], "desc": "Saha içi tam bir kaos, kontrol her an kaybolabilir!"}
        ]
        
        # Senaryoya göre atmosfer seçimi
        if modifiers["physical_game"]: atm = atmospheres[1] # Gergin
        elif modifiers["chaos_boost"]: atm = atmospheres[3] # Kaotik
        else: atm = random.choice(atmospheres)
        
        print(f"DEBUG: [{label}] Atmosfer Modu: {atm['name']}")

        red_cards_a, red_cards_b = 0, 0
        events, goals_data = [], []
        
        # 2. Gelişmiş Matematiksel Denge (GPR Gap Discipline)
        gap = gpr_a - gpr_b
        r_gap = abs(gap)
        ratio = gpr_a / max(gpr_b, 1.0)
        
        # xG Hesaplaması (Daha muhafazakar bir model)
        base_xg_ratio = 1.15 if modifiers["chaos_boost"] else 1.0
        # Kuvvetli takıma logaritmik avantaj sağla
        base_xg_h = 1.2 * (ratio ** 1.8) * random.uniform(0.85, 1.15) * base_xg_ratio
        base_xg_a = 1.2 / (ratio ** 1.8) * random.uniform(0.85, 1.15) * base_xg_ratio
        
        # Gol Hesaplama (Daha dengeli bir Poisson benzeri dağılım)
        target_h = sum(1 for _ in range(6) if random.random() < (base_xg_h / 6))
        target_a = sum(1 for _ in range(6) if random.random() < (base_xg_a / 6))
        
        # GPR Farkına Göre Score Cap (YENİ: Skandal Skor Engelleme)
        if r_gap < 12:
            target_h = min(target_h, 3 + random.randint(0, 1))
            target_a = min(target_a, 3 + random.randint(0, 1))
        elif r_gap < 20: 
            target_h = min(target_h, 5)
            target_a = min(target_a, 5)

        if modifiers["defensive_nerf"]:
            if random.random() < 0.5: target_a = min(6, target_a + 1)
            else: target_h = min(6, target_h + 1)

        # 3. Şablonlar ve Atmosfer
        templates = {
            "goal": [
                "⚽ **GOOOL!** {player} ceza sahası dışından mermi gibi vurdu, ağlar sarsılıyor!",
                "⚽ **GOOOL!** {player} kaleciyle karşı karşıya soğukkanlı bir bitiriş yaptı!",
                "⚽ **GOOOL!** Kornerden gelen topa {player} harika yükseldi ve kafayı vurdu!",
                "⚽ **GOOOL!** {player} rakiplerini ipe dizdi ve enfes bir plase bıraktı!",
                "⚽ **GOOOL!** Dönen topu {player} tamamladı, stadyum yıkılıyor!",
                "🎯 **GOOOL!** {player} penaltı noktasında hata yapmadı ve ağları havalandırdı!",
                "🚀 **GOOOL!** İnanılmaz bir frikik golü! {player} topu 90'a astı!"
            ],
            "red_card": [
                "🟥 **KIRMIZI KART!** {player} rakibine yaptığı sert müdahale sonrası ihraç edildi!",
                "🟥 **KIRMIZI KART!** {player} ikinci sarıdan oyun dışı! Saha karıştı!"
            ],
            "injury": ["🚑 **SAKATLIK!** {player} acı içinde yerde kaldı.", "🤕 {player} oyuna devam edemiyor!"],
            "sub": "🔄 **DEĞİŞİKLİK!** {p_out} kenara gelirken, {p_in} oyuna dahil oluyor.",
            "chaos": [
                "🔥 **GERGİNLİK!** Saha içinde oyuncular birbirine girdi!",
                "🧨 **TARAFTAR BASKISI!** Tribünlerde meşaleler yakıldı!",
                "👔 **HOCA KIZGIN!** Kenarda hakeme itiraz eden teknik direktöre sarı kart!",
                "🪧 **İTİRAZ!** {player} hakemin kararını kabul etmiyor!"
            ],
            "shot": ["🥅 {player} kaleyi yokladı ama dışarıda!", "🧤 {player} vurdu, kaleci çeldi!", "💥 Direkten döndü! {player} çerçeveyi bulamadı!"],
            "card": ["🟨 {player} sarı kart gördü.", "🟨 Hakem {player}'ı uyardı ve sarı kartını çıkardı."],
            "foul": ["💢 {player} rakibini indirdi.", "💢 Faul! {player} sert bir müdahale yaptı."],
            "var_check": "🖥️ **VAR KONTROLÜ!** Hakem golü incelemek üzere ekrana gidiyor...",
            "var_cancel": "❌ **GOL İPTAL!** Pozisyonun geçersiz olduğu belirlendi!",
            "var_confirm": "✅ **GOL GEÇERLİ!** Hakem santrayı gösteriyor!"
        }

        def pick_weighted_player(active_list, etype):
            if not active_list: return {"name": "Bilinmeyen", "pos": "CM"}
            st_pos, mid_pos, def_pos = ["ST", "FW", "LW", "RW", "CF", "FOR"], ["CAM", "CM", "LM", "RM", "CDM", "OS"], ["CB", "LB", "RB", "LWB", "RWB", "DF"]
            weights = []
            for p in active_list:
                pos = p.get("pos", "CM").upper()
                w = 10
                if etype in ["goal", "shot"]:
                    if any(x in pos for x in st_pos): w = 80
                    elif any(x in pos for x in mid_pos): w = 30
                    elif any(x in pos for x in def_pos): w = 5
                    elif "GK" in pos or "KL" in pos: w = 0.5
                elif etype in ["card", "foul"]:
                    if any(x in pos for x in def_pos): w = 60
                    elif any(x in pos for x in mid_pos): w = 40
                    elif any(x in pos for x in st_pos): w = 20
                weights.append(w)
            return random.choices(active_list, weights=weights)[0]

        # 4. Ana Döngü
        curr_h, curr_a = 0, 0
        used_min = set()
        event_count = random.randint(8, 11)
        
        def add_ev(m, type, team, player_name, desc):
            events.append({"minute": m, "type": type, "team": team, "player": player_name, "description": desc})

        for _ in range(event_count):
            m = random.randint(1, 90)
            while m in used_min: m = random.randint(1, 90)
            used_min.add(m)
            
            is_h = random.random() < (gpr_a / (gpr_a + gpr_b))
            team, active, bench = (home_team, active_a, bench_a) if is_h else (away_team, active_b, bench_b)
            
            etype = random.choices(["goal", "shot", "foul", "card", "chaos"], weights=atm["weights"])[0]
            
            if etype == "goal":
                if ((is_h and curr_h < target_h) or (not is_h and curr_a < target_a)):
                    if random.random() < 0.1:
                        add_ev(m, "var", team, "Hakem", templates["var_check"])
                        if random.random() < 0.4:
                            add_ev(m+1, "var", team, "Hakem", templates["var_cancel"])
                            continue
                    p_obj = pick_weighted_player(active, "goal")
                    add_ev(m, "goal", team, p_obj["name"], random.choice(templates["goal"]).format(player=p_obj["name"]))
                    goals_data.append({"minute": m, "player": p_obj["name"], "team": team, "type": "normal"})
                    if is_h: curr_h += 1
                    else: curr_a += 1
                else: etype = "shot"
            
            if etype != "goal":
                p_obj = pick_weighted_player(active, etype)
                add_ev(m, etype, team, p_obj["name"], random.choice(templates.get(etype, templates["shot"])).format(player=p_obj["name"]))

        # Skor Tamamlama
        while curr_h < target_h:
            m = random.randint(1, 90); p = pick_weighted_player(active_a, "goal")
            add_ev(m, "goal", home_team, p["name"], random.choice(templates["goal"]).format(player=p["name"]))
            goals_data.append({"minute": m, "player": p["name"], "team": home_team, "type": "normal"}); curr_h += 1
        while curr_a < target_a:
            m = random.randint(1, 90); p = pick_weighted_player(active_b, "goal")
            add_ev(m, "goal", away_team, p["name"], random.choice(templates["goal"]).format(player=p["name"]))
            goals_data.append({"minute": m, "player": p["name"], "team": away_team, "type": "normal"}); curr_a += 1

        events.sort(key=lambda x: x["minute"])
        goals_data.sort(key=lambda x: x["minute"])

        # 🧠 İstatistiksel Tutarlılık (Logical Coherence)
        def clamp(n, minn, maxn): return max(minn, min(n, maxn))
        pos_h = int(max(30, min(70, 50 + clamp((gpr_a - gpr_b) / 3, -15, 15) + random.randint(-4, 4))))
        
        # İsabetli Şut >= Gol Olmak Zorundadır
        sot_h = target_h + random.randint(1, 6)
        sot_a = target_a + random.randint(1, 6)
        
        # Toplam Şut >= İsabetli Şut
        sh_h = sot_h + random.randint(2, 12)
        sh_a = sot_a + random.randint(2, 12)
        
        # Pas İsabeti GPR'a göre ölçeklenir
        pass_h = int(max(65, min(94, 75 + (gpr_a - 70) * 0.5 + random.randint(-2, 2))))
        pass_a = int(max(65, min(94, 75 + (gpr_b - 70) * 0.5 + random.randint(-2, 2))))
        
        # xG Tutarlılığı (Pozisyon kalitesine dayalı)
        xg_h = round((target_h * 0.6) + (sot_h * 0.15) + (sh_h * 0.05) + random.uniform(0.1, 0.4), 2)
        xg_a = round((target_a * 0.6) + (sot_a * 0.15) + (sh_a * 0.05) + random.uniform(0.1, 0.4), 2)

        return {
            "home_score": target_h, "away_score": target_a,
            "goals": goals_data, "events": events,
            "possession_home": pos_h, "possession_away": 100 - pos_h,
            "shots_home": sh_h, "shots_away": sh_a,
            "shots_on_target_home": sot_h, "shots_on_target_away": sot_a,
            "pass_accuracy_home": pass_h, "pass_accuracy_away": pass_a,
            "fouls_home": random.randint(6, 18), "fouls_away": random.randint(6, 18),
            "corners_home": random.randint(2, 10), "corners_away": random.randint(2, 10),
            "offsides_home": random.randint(0, 5), "offsides_away": random.randint(0, 5),
            "xg_home": xg_h, "xg_away": xg_a,
            "motm": {
                "player": pick_weighted_player(active_a if target_h >= target_a else active_b, "goal")["name"],
                "rating": round(random.uniform(8.2, 9.8), 1)
            },
            "match_narrative": f"Atmosfer: {atm['name']} | " + random.choice([
                "Mevki disiplininin ve taktiksel varyasyonların ön planda olduğu bir 90 dakikayı geride bıraktık.",
                "Yıldız oyuncuların bireysel yetenekleriyle maçı kopardığı, heyecan dozajı yüksek bir mücadeleydi.",
                "Orta saha mücadelesinin ve fiziksel temasın maçın kaderini belirlediği bir karşılaşma izledik."
            ])
        }

    def shrink_tactics(self, text: str) -> str:
        if not text: return ""
        patterns = [
            r"(?i)I\.\s+STRATEJİK VİZYON.*?(?=II\.\s+ANA YAPI|III\.\s+HÜCUM PLANI|$)",
            r"(?i)III\.\s+HÜCUM PLANI.*?(?=IV\.\s+SAVUNMA YAPISI|$)",
            r"(?i)IV\.\s+SAVUNMA YAPISI.*?(?=V\.\s+GEÇİŞ OYUNU|$)",
            r"(?i)V\.\s+GEÇİŞ OYUNU.*?(?=VI\.\s+KRİTİK DÜZELTMELER|$)",
            r"(?i)VI\.\s+KRİTİK DÜZELTMELER.*?(?=$)",
            r"(?i)🚀\s+GÜNCEL KADRO DURUMU.*?(?=\n\n|$)",
            r"(?i)🔄\s+STRATEJİK DEĞİŞİKLİK PLANI.*?(?=$)",
            r"(?i)📉\s+BEKLENEN SONUÇLAR.*?(?=$)",
            r"(?i)YZ \(YAPAY ZEKA\) CHEATLARI.*?(?=$)"
        ]
        shrunk = text
        for pattern in patterns:
            shrunk = re.sub(pattern, "\n[DETAYLI ANALİZ TASARRUF İÇİN BUDANDI]\n", shrunk, flags=re.DOTALL)
        return shrunk

    def safe_load(self, content: str) -> Optional[Any]:
        if not content: return None
        try:
            content = '\n'.join([line.strip() for line in content.split('\n')])
            content = re.sub(r'(\d+)\s*\+\s*(\d+)', lambda m: str(int(m.group(1)) + int(m.group(2))), content)
        except: pass
        try: return json.loads(content)
        except:
            try: return json.loads(self.repair_json(content))
            except:
                try:
                    pythonic = content.replace('null', 'None').replace('true', 'True').replace('false', 'False')
                    repaired = self.repair_json(pythonic)
                    repaired = '\n'.join([l.strip() for l in repaired.split('\n')])
                    val = ast.literal_eval(repaired)
                    # If it's a tuple/list, we probably wanted a dict (AI quirk)
                    if isinstance(val, (list, tuple)) and len(val) > 0 and isinstance(val[0], dict):
                        return val[0]
                    return val if isinstance(val, dict) else None
                except: return None

    async def _query_openrouter(self, prompt: str, system: str, temp: float, max_tokens: int, timeout: int = 60, is_json: bool = False, json_retry: bool = False) -> Optional[str]:
        if not self.or_key or "sk-or-v1-..." in self.or_key: return None
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.or_key}", "Content-Type": "application/json"}
        try:
            async with aiohttp.ClientSession() as session:
                for model in self.or_models_long:
                    sys_msg = system or ""
                    if is_json:
                        sys_msg = ((sys_msg + "\n\n") if sys_msg else "") + "SADECE geçerli JSON döndür. Markdown, açıklama, önsöz, son söz YAZMA."
                        if json_retry: sys_msg += " JSON'ı tek parça ve eksiksiz ver. Ek anahtar ekleme."
                    payload = {"model": model, "messages": [{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}], "temperature": temp, "max_tokens": max_tokens}
                    if is_json: payload["response_format"] = {"type": "json_object"}
                    async with session.post(url, headers=headers, json=payload, timeout=timeout) as resp:
                        if resp.status == 200:
                            try:
                                raw = await resp.text()
                                data = json.loads(raw)
                                return data["choices"][0]["message"]["content"]
                            except: continue
                        if resp.status == 429: await asyncio.sleep(0.5); continue
                        continue
                return None
        except: return None

    async def generate_content_cascade(self, prompt: str, system_instruction: str = "", temperature: float = 0.7, max_tokens: int = 8000, is_json: bool = True, label: str = "GLOBAL", attempts: int = None, timeout: int = 45, provider: str = "auto", prompt_fallback: str = None, system_fallback: str = None) -> Any:
        gemini_id = getattr(config, 'GEMINI_MODEL', "gemini-3.1-flash-lite-preview")
        max_attempts = attempts if attempts is not None else getattr(config, "AI_MAX_ATTEMPTS", 4)
        provider = (provider or "auto").lower().strip()
        
        # If specific provider requested, skip other tiers
        if provider in ("openrouter", "openrouter_fast", "groq", "groq_fast"):
            max_attempts = 0
        elif not self.client:
            print(f"DEBUG: [{label}] Gemini Client bulunamadı, Tier 1 atlanıyor.")
            max_attempts = 0
        
        # Tier 1: Gemini
        for attempt in range(max_attempts):
            try:
                print(f"DEBUG: [{label}] AI Tier 1 (Gemini) - Deneme {attempt + 1}/{max_attempts}...")
                response = await asyncio.wait_for(asyncio.to_thread(self.client.models.generate_content, model=gemini_id, contents=f"{system_instruction}\n\n{prompt}", config=types.GenerateContentConfig(temperature=temperature, max_output_tokens=max_tokens, safety_settings=[types.SafetySetting(category=c, threshold='BLOCK_NONE') for c in ['HARM_CATEGORY_HATE_SPEECH', 'HARM_CATEGORY_HARASSMENT', 'HARM_CATEGORY_SEXUALLY_EXPLICIT', 'HARM_CATEGORY_DANGEROUS_CONTENT']])), timeout=timeout)
                if response and response.text:
                    text = response.text
                    if is_json:
                        content = self.clean_json(text)
                        result = self.safe_load(content)
                        if result: return result
                    else: return text
                if attempt < max_attempts - 1: await asyncio.sleep(1); continue
                else: break
            except Exception as e:
                print(f"DEBUG: [{label}] Tier 1 Hata (Deneme {attempt+1}/{max_attempts}): {e}")
                if attempt < max_attempts - 1: await asyncio.sleep(1); continue
                else: break

        if provider == "gemini":
            print(f"DEBUG: [{label}] Sadece Gemini istendi ve başarısız oldu.")
            return None

        if provider.startswith("groq") or provider == "auto":
            # Tier 2: Groq
            print(f"DEBUG: [{label}] Tier 2 (Groq) devreye giriyor...")
            shrunk_p = self.shrink_tactics(prompt_fallback or prompt)
            shrunk_s = self.shrink_tactics(system_fallback or system_instruction)
            groq_out_cap = getattr(config, "GROQ_MAX_OUTPUT_TOKENS", 1200)
            
            groq_text = await self._query_groq(
                prompt=shrunk_p, 
                system=shrunk_s, 
                temp=temperature, 
                max_tokens=min(max_tokens, groq_out_cap), 
                timeout=min(timeout, 30), 
                is_json=is_json
            )
            
            if groq_text:
                if is_json:
                    content = self.clean_json(groq_text)
                    parsed = self.safe_load(content)
                    if parsed is not None: return parsed
                else:
                    return groq_text
            
            print(f"DEBUG: [{label}] Tier 2 (Groq) başarısız oldu.")
            
            # If specifically groq was requested OR openrouter fallback is disabled, go to local
            if provider.startswith("groq") or not getattr(config, "USE_OPENROUTER_FALLBACK", False):
                if self.prefer_local:
                    print(f"DEBUG: [{label}] [Groq Sonrası] Yerel Motor Devreye Giriyor...")
                    local_res = await self._simulate_local_algorithmic(prompt, label)
                    if local_res: return local_res
                return None

        # Tier 3: OpenRouter
        print(f"DEBUG: [{label}] Tier 3 (OpenRouter) devreye giriyor...")
        shrunk_p_or = self.shrink_tactics(prompt_fallback or prompt)
        shrunk_s_or = self.shrink_tactics(system_fallback or system_instruction)
        or_models_prev = self.or_models_long
        if provider in ("openrouter_fast", "openrouter-short", "openrouter_small"): self.or_models_long = self.or_models_fast
        or_text = await self._query_openrouter(shrunk_p_or, shrunk_s_or, temperature, max_tokens, timeout=timeout, is_json=is_json)
        self.or_models_long = or_models_prev
        if or_text:
            if is_json:
                content = self.clean_json(or_text)
                parsed = self.safe_load(content)
                if parsed is not None: return parsed
                or_text_2 = await self._query_openrouter(prompt_fallback or prompt, system_fallback or system_instruction, min(temperature, 0.2), max_tokens, timeout=timeout, is_json=True, json_retry=True)
                if or_text_2:
                    content2 = self.clean_json(or_text_2)
                    return self.safe_load(content2)
            else: return or_text
        
        # Tier 4 (Son Kale): Yerel Algoritmik Motor
        # SADECE maç simülasyonu ve JSON gerektiren işler için devreye girer.
        if self.prefer_local and is_json:
            # Soru sorma veya panorama gibi metin bazlı işlerde yerel motor dictionary döndürmemeli.
            is_match_task = any(x in label.upper() for x in ["MATCH", "SIM", "LIG", "TAKTİK"])
            if is_match_task:
                local_res = await self._simulate_local_algorithmic(prompt, label)
                if local_res: return local_res
        
        return None

ai_manager = AIManager()
async def generate_content(prompt, system="", temp=0.7, tokens=8000, is_json=True, label="AI", attempts=None, timeout=60, provider="auto", prompt_fallback=None, system_fallback=None):
    return await ai_manager.generate_content_cascade(prompt=prompt, system_instruction=system, temperature=temp, max_tokens=tokens, is_json=is_json, label=label, attempts=attempts, timeout=timeout, provider=provider, prompt_fallback=prompt_fallback, system_fallback=system_fallback)
