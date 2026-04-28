"""
Deterministik Swiss League çizelgeleyici — 36 takım, 8 hafta, çakışma sıfır.
Yaklaşım: Her gün için 18 maçlık "perfect matching" oluştur.
Bütün maçlar 4 torba üzerinden bipartite çiftleri olarak organize edilir.
"""
import random

def build_schedule(n_teams=36, n_rounds=8):
    """
    36 takım, 8 haftalık garantili çizelge.
    Her takım tam 8 kez oynar, hiçbir gün 2 kez oynamaz.
    
    Yaklaşım:
    - 36 takımı A[0..17] ve B[0..17] olarak ikiye böl
    - Her gün: A[i] vs B[sigma(i)] eşleştirmesi (sigma = permütasyon)
    - 8 farklı permütasyon 8 farklı günü oluşturur
    - Her takım tam 1 kez her günde görünür → çakışma imkânsız
    """
    teams = [f"T{i}" for i in range(n_teams)]
    half = n_teams // 2  # 18
    A = teams[:half]
    B = teams[half:]
    
    # 8 farklı permütasyon üret (her biri 18 elemanlı)
    # Başlangıç: kimlik permütasyonu
    # Sonraki: kaydırma (shift)
    schedule = {}
    for r in range(1, n_rounds + 1):
        shift = (r - 1) * 2  # 0, 2, 4, ... 14 kaydırma
        matches = []
        for i in range(half):
            j = (i + shift) % half
            # Ev/Dep dönüşümlü
            if r % 2 == 0:
                matches.append({"home": A[i], "away": B[j]})
            else:
                matches.append({"home": B[j], "away": A[i]})
        schedule[r] = matches
    
    return schedule, teams

def verify_schedule(schedule, teams):
    """Çizelgeyi doğrula."""
    team_counts = {t: 0 for t in teams}
    conflicts = 0
    
    for r, matches in schedule.items():
        day_teams = set()
        for fx in matches:
            h, a = fx["home"], fx["away"]
            team_counts[h] += 1
            team_counts[a] += 1
            if h in day_teams or a in day_teams:
                conflicts += 1
            day_teams.add(h)
            day_teams.add(a)
    
    wrong_counts = [(t, c) for t, c in team_counts.items() if c != 8]
    return conflicts, wrong_counts, team_counts


# Test 1: Basit shift-based
print("=== Test 1: Shift-Based ===")
sched, teams = build_schedule()
conf, wrong, counts = verify_schedule(sched, teams)
print(f"Cakisma: {conf}, Yanlis mac sayisi: {len(wrong)}/{len(teams)}")
for r, m in sched.items():
    print(f"  MD{r}: {len(m)} mac")


# Test 2: 4 torbali (9er) yaklasimi - potlara gore karsilasma
print("\n=== Test 2: 4-Pot Bipartite (9+9) ===")
teams36 = [f"T{i}" for i in range(36)]
pots = [teams36[i*9:(i+1)*9] for i in range(4)]

def build_pot_schedule(pots_list):
    """
    Her gün: pot0 vs pot1 (9 mac) + pot2 vs pot3 (9 mac) = 18 mac
    8 gun x 18 mac = 144 mac
    Her gun her takım tam 1 kez oynuyor
    
    Gun 1-2: pot0 vs pot1, pot2 vs pot3 (farkli permutasyon)
    Gun 3-4: pot0 vs pot2, pot1 vs pot3
    Gun 5-6: pot0 vs pot3, pot1 vs pot2
    Gun 7-8: pot0 vs pot1, pot2 vs pot3 (tekrar - farkli permutasyon)
    """
    # Torba ciftleri: her gun 2 cift vardir
    day_structure = [
        (0,1, 2,3),  # MD1
        (0,1, 2,3),  # MD2 (farkli eslestirme)
        (0,2, 1,3),  # MD3
        (0,2, 1,3),  # MD4
        (0,3, 1,2),  # MD5
        (0,3, 1,2),  # MD6
        (0,1, 2,3),  # MD7 (ucuncu kez - ama farkli permutasyon)
        (0,2, 1,3),  # MD8
    ]
    
    # Her torba ciftinin kacinci kullanilmasi oldugunu takip et
    pair_usage = {}
    
    schedule = {}
    all_teams = [t for pot in pots_list for t in pot]
    
    for day_idx, (p1a, p1b, p2a, p2b) in enumerate(day_structure):
        r = day_idx + 1
        matches = []
        
        # Cift 1: pot[p1a] vs pot[p1b]
        key1 = (min(p1a,p1b), max(p1a,p1b))
        cnt1 = pair_usage.get(key1, 0)
        pair_usage[key1] = cnt1 + 1
        
        pot_a = pots_list[p1a][:]
        pot_b = pots_list[p1b][:]
        random.shuffle(pot_a)
        random.shuffle(pot_b)
        
        for i in range(9):
            shift = cnt1 * 3  # Her kullanim icin farkli offset
            j = (i + shift) % 9
            if cnt1 % 2 == 0:
                matches.append({"home": pot_a[i], "away": pot_b[j]})
            else:
                matches.append({"home": pot_b[j], "away": pot_a[i]})
        
        # Cift 2: pot[p2a] vs pot[p2b]
        key2 = (min(p2a,p2b), max(p2a,p2b))
        cnt2 = pair_usage.get(key2, 0)
        pair_usage[key2] = cnt2 + 1
        
        pot_c = pots_list[p2a][:]
        pot_d = pots_list[p2b][:]
        random.shuffle(pot_c)
        random.shuffle(pot_d)
        
        for i in range(9):
            shift = cnt2 * 3
            j = (i + shift) % 9
            if cnt2 % 2 == 0:
                matches.append({"home": pot_c[i], "away": pot_d[j]})
            else:
                matches.append({"home": pot_d[j], "away": pot_c[i]})
        
        schedule[r] = matches
    
    return schedule, all_teams, pair_usage

for trial in range(10):
    sched2, teams2, usage = build_pot_schedule(pots)
    conf2, wrong2, counts2 = verify_schedule(sched2, teams2)
    if conf2 == 0 and len(wrong2) == 0:
        print(f"Trial {trial+1}: BASARILI! Cakisma: {conf2}, Yanlis: {len(wrong2)}")
        print(f"  Pot cift kullanim: {usage}")
        break
    else:
        print(f"Trial {trial+1}: Cakisma={conf2}, YanlisSayi={len(wrong2)}, ornekler={wrong2[:3]}")
