import os
import io
import requests
import urllib.parse
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

class MatchGraphics:
    def __init__(self, assets_path="data/assets"):
        self.assets_path = os.path.abspath(assets_path)
        self.logos_path = os.path.join(self.assets_path, "logos")
        self.players_path = os.path.join(self.assets_path, "players")
        
        base_font = "C:/Windows/Fonts/"
        self.fonts = {
            "title": os.path.join(base_font, "bahnschrift.ttf"),
            "impact": os.path.join(base_font, "impact.ttf"),
            "regular": os.path.join(base_font, "segoeui.ttf"),
            "bold": os.path.join(base_font, "segoeuib.ttf")
        }

    def _get_font(self, font_type, size):
        try:
            return ImageFont.truetype(self.fonts.get(font_type, "arial.ttf"), size)
        except:
            return ImageFont.load_default()

    def _normalize_name(self, name):
        n = str(name).upper().strip()
        if "AMED" in n: return "AMEDSPOR"
        if "EROK" in n: return "EROKSPOR"
        if "BESIKTAS" in n: return "BESIKTAS"
        if "KOCAELI" in n: return "KOCAELISPOR"
        mapping = {'İ': 'I', 'Ş': 'S', 'Ğ': 'G', 'Ü': 'U', 'Ö': 'O', 'Ç': 'C'}
        for k, v in mapping.items():
            n = n.replace(k, v)
        return n

    def _get_ai_bg(self, home, away):
        try:
            prompt = f"Professional football match stadium poster for {home} vs {away}, dark cinematic lighting, orange neon, 8k, aerial view"
            url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}?width=1080&height=1080&nologo=true"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                img = Image.open(io.BytesIO(response.content)).convert("RGB")
                return ImageOps.fit(img, (1080, 1080))
        except: pass
        return Image.new("RGB", (1080, 1080), (10, 15, 25))

    def generate_match_summary(self, match_data):
        # 1. BASE
        img = self._get_ai_bg(match_data['home_team'], match_data['away_team'])
        overlay = Image.new("RGBA", (1080, 1080), (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        
        # Darkening overlay
        d.rectangle([0, 0, 1080, 1080], fill=(0, 0, 0, 180))

        # 2. HEADER (SCOREBOARD)
        # -----------------------
        hy = 180
        def draw_logo(name, x, y, size=200):
            norm = self._normalize_name(name)
            paths = [
                os.path.join(self.logos_path, f"{norm}.png"),
                os.path.join(self.logos_path, f"{name.upper()}.png"),
                os.path.join(self.logos_path, f"{name.upper().replace('İ','I')}.png")
            ]
            logo_img = None
            for p in paths:
                if os.path.exists(p):
                    logo_img = Image.open(p).convert("RGBA")
                    break
            
            if logo_img:
                logo_img = ImageOps.fit(logo_img, (size, size))
                overlay.paste(logo_img, (int(x-size/2), int(y-size/2)), logo_img)
            else:
                d.ellipse([x-size/2, y-size/2, x+size/2, y+size/2], outline="white", width=2)
                d.text((x, y), name[:1].upper(), fill="white", font=self._get_font("bold", 60), anchor="mm")

        draw_logo(match_data['home_team'], 200, hy)
        draw_logo(match_data['away_team'], 880, hy)
        
        d.text((540, hy), f"{match_data['home_score']} - {match_data['away_score']}", fill="white", font=self._get_font("impact", 200), anchor="mm")
        
        self._draw_text_box(d, match_data['home_team'].upper(), (200, hy+140), 380, "title", 40)
        self._draw_text_box(d, match_data['away_team'].upper(), (880, hy+140), 380, "title", 40)
        
        # 3. STATS (MIDDLE AREA - FULL WIDTH)
        # -----------------------------------
        sy = 480
        stats = list(match_data.get('stats', {}).items())[:6]
        for i, (label, val) in enumerate(stats):
            y_curr = sy + (i * 60)
            total = (val[0] + val[1]) if (val[0] + val[1]) > 0 else 1
            h_ratio = val[0] / total
            
            # Label
            d.text((540, y_curr - 18), label.upper(), fill="#999999", font=self._get_font("regular", 14), anchor="mm")
            
            # Values
            d.text((250, y_curr), str(val[0]), fill="white", font=self._get_font("bold", 24), anchor="rm")
            d.text((830, y_curr), str(val[1]), fill="white", font=self._get_font("bold", 24), anchor="lm")
            
            # Bars
            bw = 500
            bx = 290
            d.rectangle([bx, y_curr-3, bx+bw, y_curr+3], fill=(255,255,255,20))
            d.rectangle([bx, y_curr-3, bx + (bw * h_ratio), y_curr+3], fill="#00bfff") # Home
            d.rectangle([bx + (bw * h_ratio), y_curr-3, bx + bw, y_curr+3], fill="#f5f5f5") # Away

        # 4. BOTTOM AREA (Split into Goals and MOTM)
        # ------------------------------------------
        by = 880
        
        # MOTM (Left side of bottom)
        motm = match_data.get('motm', {})
        if motm:
            mx, my = 50, by
            d.rounded_rectangle([mx, my, mx+450, my+120], radius=15, fill=(0, 191, 255, 20), outline="#00bfff", width=2)
            d.text((mx+20, my+30), "MAÇIN ADAMI", fill="#00bfff", font=self._get_font("bold", 16), anchor="lm")
            self._draw_text_box(d, motm.get('player','').upper(), (mx+20, my+75), 320, "title", 28, anchor="lm")
            # Rating Circle
            d.ellipse([mx+340, my+10, mx+440, my+110], outline="#00bfff", width=3)
            d.text((mx+390, my+60), str(motm.get('rating', 0)), fill="white", font=self._get_font("impact", 48), anchor="mm")

        # GOALS (Right side of bottom)
        goals = [e for e in match_data.get('events', []) if e['type'] == "goal"][:5]
        if goals:
            gx, gy = 550, by
            d.text((gx, gy-20), "GOLLER", fill="#00bfff", font=self._get_font("bold", 18), anchor="lm")
            for i, goal in enumerate(goals):
                gy_curr = gy + (i * 28)
                icon = "⚽"
                d.text((gx, gy_curr), f"{goal['minute']}' {icon} {goal['player'].upper()}", fill="white", font=self._get_font("bold", 16), anchor="lm")

        # 5. WATERMARK / VERSION
        d.text((1060, 1060), "v3.0 PREMIUM", fill=(255,255,255,40), font=self._get_font("regular", 12), anchor="se")

        # FINAL COMPOSITE
        img.paste(overlay, (0, 0), overlay)
        output = io.BytesIO()
        img.save(output, format="PNG")
        output.seek(0)
        return output

    def _draw_text_box(self, draw, text, pos, max_w, font_type, size, anchor="mm", fill="white"):
        current_size = size
        font = self._get_font(font_type, current_size)
        while current_size > 10:
            bbox = draw.textbbox((0, 0), text, font=font, anchor=anchor)
            w = bbox[2] - bbox[0]
            if w <= max_w: break
            current_size -= 1
            font = self._get_font(font_type, current_size)
        draw.text(pos, text, fill=fill, font=font, anchor=anchor)
