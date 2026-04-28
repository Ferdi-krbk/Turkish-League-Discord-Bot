"""
Media/Press Generator for Turkish Super League Bot
FULL TRIBUNE EDITION: Aggressive, Street-style, and Cinematic Visual Prompts.
"""

import random
import urllib.parse
from typing import Dict, List, Any

# --- STREET STYLE HEADLINES (TRIBÜN AĞZI) ---
HEADLINE_TEMPLATES_WIN = [
    "{team} resital sundu, rakibi sahadan sildi!",
    "{team} acımadı! Resmen sahadan süpürdü!",
    "{team} taraftarının önünde rakibi perişan etti!",
    "{team} fırtınası esti! Kimse durduramıyor!",
    "{team} rakibine nefes aldırmadı!",
    "{team} gücünü gösterdi, herkes sussun!",
    "{team} rakibini sikti attı!",
    "{team} şölen yaptı, şehir ayakta!",
]

HEADLINE_TEMPLATES_LOSS = [
    "{team} çöktü! Bu ruhsuzluk ne?",
    "{team} taraftarını kahretti!",
    "{team} için kabus gecesi!",
    "{team} sahada yoktu resmen rezalet!",
    "{team} ne yapacağını şaşırdı, dağıldı!",
    "{team} için hesap vaktidir!",
    "{team} perişan oldu, isyan sesleri yükseliyor!",
    "{team} formanın ağırlığını unuttu!",
]

HEADLINE_TEMPLATES_DRAW = [
    "{team} fırsat tepti!",
    "{team} bir ileri bir geri, yerinde sayıyor!",
    "{team} taraftarı bu puanla yetinmez!",
    "{team} düğümü çözemedi!",
    "{team} iki yakasını bir araya getiremedi!",
    "{team} için kayıp puanlar can yakacak!",
]

HEADLINE_TEMPLATES_DERBY = [
    "Şehir boyandı! Derbide {team} fırtınası!",
    "Derbi krallık ilanı: {team} ezdi geçti!",
    "Dünya sustu, {team} konuştu!",
    "{team} derbi canavarı olduğunu bir kez daha kanıtladı!",
    "Derbi ateşi! {team} rakibinin hayallerini yıktı!",
]

# --- AGGRESSIVE MANAGER QUOTES ---
MANAGER_WIN_QUOTES = [
    "Biz bu ligin en iyisiyiz. Sahada bunu bir kez daha kanıtladık.",
    "Kalitemizi herkes gördü. Bizimle aşık atamazlar.",
    "Rakibi analiz ettik ve paramparça ettik. Planımız tıkır tıkır işledi.",
    "Bu forma için savaşan, kazanan çocuklarıma teşekkürler.",
    "Herkes sussun artık, konuşma sırası bizde.",
]

MANAGER_LOSS_QUOTES = [
    "Bu skorun sorumlusu biziz ama hakem kararları da ortada.",
    "Bazı oyuncularımın bu formanın değerini anlaması lazım.",
    "Bize komplo kuruluyor ama yıkılmayacağız.",
    "Taraftarımızdan özür diliyoruz ama bu iş burada bitmedi.",
    "Sahada istediklerimizi yapamadık, bazı kararları sorgulayacağız.",
]

MANAGER_DRAW_QUOTES = [
    "Puan puandır ama biz daha fazlasını haketmiştik.",
    "Zorlu bir mücadeleydi, oyunun hakkı beraberlikti belki de.",
    "Hala liderlik inancımız tam, bu puan bizi yolumuzdan çeviremez.",
]

# --- FAN REACTIONS (Sokak/Tribün) ---
FAN_WIN_REACTIONS = [
    "O sene bu sene! Şampiyon geliyoooor! 🏆🔥",
    "İşte bu be! Sahayı dar ettik adamlara!",
    "Hoca tam bir dahi, taktik akıyor!",
    "Semt ayakta! Herkes evine, biz zirveye!",
    "Bu futbolu özlemiştik, helal olsun!",
]

FAN_LOSS_REACTIONS = [
    "Hoca istifa! Bu nasıl futbol kardeşim?",
    "Yazıklar olsun o formaya! Terletin bari!",
    "Yönetim uyuma, taraftarını çıldırtma!",
    "Bizim paramızla bu topu mu oynuyorsunuz?",
    "Hafta sonumuzu zehir ettiniz, bravo!",
]

FAN_DRAW_REACTIONS = [
    "En azından kaybetmedik ama bu futbol şampiyonluğa yetmez.",
    "Korkak futbol puan getirmez!",
    "Daha agresif olmalıyız, çok yumuşak kalıyoruz.",
]

class MediaGenerator:
    def __init__(self):
        pass

    def generate_press_headlines(self, match_result: Dict[str, Any]) -> List[str]:
        """Generate 3 press headlines based on match result"""
        headlines = []
        home_team = match_result["home_team"]
        away_team = match_result["away_team"]
        home_score = match_result["home_score"]
        away_score = match_result["away_score"]
        importance = match_result.get("importance", "Normal")

        # Derby headlines
        if importance == "Derby":
            if home_score > away_score:
                headlines.append(random.choice(HEADLINE_TEMPLATES_DERBY).format(team=home_team))
            elif away_score > home_score:
                headlines.append(random.choice(HEADLINE_TEMPLATES_DERBY).format(team=away_team))
            else:
                headlines.append(f"Kördüğüm! Derbide Yeniçeriler Yenişemedi: {home_team} {home_score}-{away_score} {away_team}")
            
            headlines.append(self._generate_headline(home_team, away_team, home_score, away_score))
            headlines.append(self._generate_headline(home_team, away_team, home_score, away_score))
        else:
            headlines.append(self._generate_headline(home_team, away_team, home_score, away_score))
            headlines.append(self._generate_headline(home_team, away_team, home_score, away_score))
            headlines.append(self._generate_headline(home_team, away_team, home_score, away_score))

        return headlines[:3]

    def _generate_headline(self, home_team: str, away_team: str,
                           home_score: int, away_score: int) -> str:
        if home_score > away_score:
            template = random.choice(HEADLINE_TEMPLATES_WIN)
            return template.format(team=home_team)
        elif away_score > home_score:
            template = random.choice(HEADLINE_TEMPLATES_WIN)
            return template.format(team=away_team)
        else:
            template = random.choice(HEADLINE_TEMPLATES_DRAW)
            return template.format(team=home_team if random.random() > 0.5 else away_team)

    def generate_manager_comments(self, match_result: Dict[str, Any]) -> Dict[str, str]:
        home_score = match_result["home_score"]
        away_score = match_result["away_score"]
        comments = {}

        if home_score > away_score:
            comments["home"] = random.choice(MANAGER_WIN_QUOTES)
        elif home_score < away_score:
            comments["home"] = random.choice(MANAGER_LOSS_QUOTES)
        else:
            comments["home"] = random.choice(MANAGER_DRAW_QUOTES)

        if away_score > home_score:
            comments["away"] = random.choice(MANAGER_WIN_QUOTES)
        elif away_score < home_score:
            comments["away"] = random.choice(MANAGER_LOSS_QUOTES)
        else:
            comments["away"] = random.choice(MANAGER_DRAW_QUOTES)

        return comments

    def generate_fan_reactions(self, match_result: Dict[str, Any]) -> Dict[str, List[str]]:
        home_score = match_result["home_score"]
        away_score = match_result["away_score"]
        reactions = {"home": [], "away": []}

        if home_score > away_score:
            reactions["home"] = random.sample(FAN_WIN_REACTIONS, 3)
        elif home_score < away_score:
            reactions["home"] = random.sample(FAN_LOSS_REACTIONS, 3)
        else:
            reactions["home"] = random.sample(FAN_DRAW_REACTIONS, 3)

        if away_score > home_score:
            reactions["away"] = random.sample(FAN_WIN_REACTIONS, 3)
        elif away_score < home_score:
            reactions["away"] = random.sample(FAN_LOSS_REACTIONS, 3)
        else:
            reactions["away"] = random.sample(FAN_DRAW_REACTIONS, 3)

        return reactions

    #Highlight Image Prompts (Pollinations.ai)
    def generate_highlight_prompts(self, match_result: Dict[str, Any]) -> List[Dict[str, str]]:
        """Identifies top 3 cinematic moments and builds visual prompts for them."""
        events = match_result.get("events", [])
        goals = match_result.get("goals", [])
        home_team = match_result.get("home_team", "Takım A")
        away_team = match_result.get("away_team", "Takım B")
        weather = match_result.get("weather", "Clear").lower()
        
        candidates = []
        for g in goals:
            candidates.append({
                "type": "goal",
                "minute": g["minute"],
                "desc": f"{g['player']} scoring a goal for {g['team']}",
                "importance": 10
            })
            
        for e in events:
            if e["type"] == "red_card":
                candidates.append({
                    "type": "red_card",
                    "minute": e["minute"],
                    "desc": "Referee showing a red card in a heated match",
                    "importance": 9
                })
            elif e["type"] == "penalty_saved":
                candidates.append({
                    "type": "save",
                    "minute": e["minute"],
                    "desc": "Goalkeeper making an incredible penalty save",
                    "importance": 8
                })

        candidates.append({
            "type": "celebration",
            "minute": 90,
            "desc": f"Passionate fans in the stadium stands celebrating",
            "importance": 5
        })
        
        candidates.sort(key=lambda x: x["importance"], reverse=True)
        top_moments = candidates[:3]
        
        highlights = []
        for m in top_moments:
            # Construct a cinematic prompt
            weather_desc = "rainy night" if "rain" in weather else "clear night" if "clear" in weather else "cloudy day"
            
            # SANITIZATION: Remove special chars that break Discord URLs
            clean_desc = m['desc'].replace("(", "").replace(")", "").replace("[", "").replace("]", "")
            # Better prompt for Turkish Lig atmosphere
            base_prompt = f"Hyper-realistic sports photography, {clean_desc}, wearing official Turkish league fragmented kits, intense match atmosphere in a crowded stadium, stadium floodlights, smoke and flares in background, 8k resolution, cinematic lighting, dramatic angle"
            
            # Use image.pollinations.ai with 'flux' (more stable model)
            encoded_prompt = urllib.parse.quote(base_prompt)
            # Add seed and model=flux for the highest quality free generation
            image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&model=flux&seed={random.randint(1,99999)}&nologo=true"
            
            highlights.append({
                "minute": m["minute"],
                "type": m["type"],
                "image_url": image_url,
                "caption": f"**DAKİKA {m['minute']}:** {m['desc']}"
            })
            
        return highlights
