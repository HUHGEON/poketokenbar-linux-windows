"""UI strings in en / ko / ja / es / fr / pt / de — ports Localization.swift.

Strings are resolved in the daemon and shipped through state.json, so QML holds
no catalogue of its own. That keeps one source of truth and means changing the
language takes effect on the next poll without reloading the plasmoid.

Only strings the Linux UI actually renders are included; the Swift file also
covers macOS-only surfaces (Keychain, updater, support mail).
"""

from __future__ import annotations

LANGUAGES = ("en", "ko", "ja", "es", "fr", "pt", "de")

# key: (en, ko, ja, es)
STRINGS: dict[str, tuple[str, ...]] = {
    "plan_balance": ("Codex plan & growth", "Codex 요금제·성장 배율", "Codex プランと成長", "Plan Codex y crecimiento", "Forfait Codex et progression", "Plano Codex e crescimento", "Codex-Tarif und Wachstum"),
    "difficulty": ("Difficulty", "난이도", "難易度", "Dificultad", "Difficulté", "Dificuldade", "Schwierigkeit"),
    "difficulty_growth": ("Growth", "성장 난이도", "成長", "Crecimiento", "Croissance", "Crescimento", "Wachstum"),
    "difficulty_shop": ("Shop prices", "상점 가격 난이도", "ショップ価格", "Precios de la tienda", "Prix de la boutique", "Preços da loja", "Shop-Preise"),
    "difficulty_hint": ("10%–200% of the default balance. Lower grows faster and costs less; higher does the opposite.", "기본 밸런스의 10%–200%예요. 낮추면 빨리 자라고 싸지며, 높이면 그 반대예요.", "標準バランスの10%〜200%です。下げると早く育ち安くなり、上げるとその逆です。", "Del 10 % al 200 % del balance predeterminado. Menos crece más rápido y cuesta menos; más hace lo contrario.", "De 10 % à 200 % de l’équilibrage par défaut. Plus bas accélère la croissance et réduit les prix ; plus haut fait l’inverse.", "De 10% a 200% do balanceamento padrão. Menor cresce mais rápido e custa menos; maior faz o contrário.", "10–200 % der Standardbalance. Niedriger wächst schneller und kostet weniger; höher bewirkt das Gegenteil."),
    "save": ("Save", "저장", "保存", "Guardar", "Enregistrer", "Salvar", "Speichern"),
    "plan_auto_hint": ("Detected automatically. Manual selection is unavailable.", "자동 감지한 요금제입니다. 직접 선택할 수 없습니다.", "自動検出されます。手動では選択できません。", "Detección automática. No se puede seleccionar manualmente.", "Détection automatique. Sélection manuelle indisponible.", "Detecção automática. Seleção manual indisponível.", "Automatisch erkannt. Keine manuelle Auswahl möglich."),
    "plan_scale": ("Growth, candy & prices: ×%1 (Plus = 1)", "경험치 통·사탕·가격: ×%1 (Plus 기준)", "成長・アメ・価格：×%1（Plus 基準）", "Crecimiento, caramelos y precios: ×%1 (Plus = 1)", "Progression, bonbons et prix : ×%1 (Plus = 1)", "Crescimento, doces e preços: ×%1 (Plus = 1)", "Wachstum, Bonbons und Preise: ×%1 (Plus = 1)"),
    "plan_checking": ("Checking Codex account…", "Codex 계정 확인 중…", "Codex アカウントを確認中…", "Comprobando cuenta Codex…", "Vérification du compte Codex…", "Verificando conta Codex…", "Codex-Konto wird geprüft…"),
    "plan_unavailable": ("Plan unavailable. Keeping the current scale; new saves use Plus scale.", "요금제를 확인하지 못해 기존 배율을 유지합니다. 새 저장은 Plus 배율로 시작합니다.", "プランを確認できません。現在の倍率を維持し、新規データは Plus 倍率を使います。", "Plan no disponible. Se mantiene la escala actual; las partidas nuevas usan Plus.", "Forfait indisponible. Le coefficient actuel est conservé ; les nouvelles parties utilisent Plus.", "Plano indisponível. Mantém a escala atual; novos jogos usam Plus.", "Tarif nicht verfügbar. Bisheriger Faktor bleibt; neue Spielstände nutzen Plus."),
    "plan_unknown": ("Not detected", "미확인", "未検出", "No detectado", "Non détecté", "Não detectado", "Nicht erkannt"),
    # tabs
    "home": ("Home", "홈", "ホーム", "Inicio",
        'Accueil', 'Início', 'Start',
    ),
    "shop": ("Shop", "상점", "ショップ", "Tienda",
        'Boutique', 'Loja', 'Shop',
    ),
    "bag": ("Bag", "가방", "バッグ", "Bolsa",
        'Sac', 'Mochila', 'Beutel',
    ),
    "collection": ("Collection", "컬렉션", "コレクション", "Colección",
        'Collection', 'Coleção', 'Sammlung',
    ),
    "pokedex": ("Pokédex", "도감", "図鑑", "Pokédex",
        'Pokédex', 'Pokédex', 'Pokédex',
    ),
    "catch_log": ("Catch log", "포획 로그", "捕獲ログ", "Registro",
        'Journal', 'Registro', 'Fangliste',
    ),
    # today
    "todays_tokens": ("Today's tokens", "오늘의 토큰", "本日のトークン", "Tokens de hoy",
        'Jetons du jour', 'Tokens de hoje', 'Tokens heute',
    ),
    "this_week": ("This week", "이번 주", "今週", "Esta semana",
        'Cette semaine', 'Esta semana', 'Diese Woche',
    ),
    "this_month": ("This month", "이번 달", "今月", "Este mes",
        'Ce mois-ci', 'Este mês', 'Dieser Monat',
    ),
    # limits
    "limits_official": ("Limits (official)", "한도(공식)", "上限（公式）", "Límites (oficial)",
        'Limites (officiel)', 'Limites (oficial)', 'Limits (offiziell)',
    ),
    "five_hour_session": ("5-hour session", "5시간 세션", "5時間セッション", "Sesión de 5 horas",
        'Session de 5 heures', 'Sessão de 5 horas', '5-Stunden-Sitzung',
    ),
    "weekly": ("Weekly", "주간", "週間", "Semanal",
        'Hebdomadaire', 'Semanal', 'Wöchentlich',
    ),
    "resetting_now": ("resetting now", "지금 초기화 중", "リセット中", "reiniciando",
        'réinitialisation', 'reiniciando', 'wird zurückgesetzt',
    ),
    "limits_unavailable": (
        "Limits unavailable", "한도를 불러올 수 없음", "上限を取得できません",
        "Límites no disponibles",
        'Limites indisponibles', 'Limites indisponíveis', 'Limits nicht verfügbar',
    ),
    # companion
    "egg": ("Egg", "알", "タマゴ", "Huevo",
        'Œuf', 'Ovo', 'Ei',
    ),
    "final_form": ("Final form", "최종 형태", "最終形態", "Forma final",
        'Forme finale', 'Forma final', 'Endform',
    ),
    "graduation": ("graduation", "졸업", "卒業", "graduación",
        'diplôme', 'formatura', 'Abschluss',
    ),
    "next_evolution": ("next evolution", "다음 진화", "次の進化", "próxima evolución",
        'prochaine évolution', 'próxima evolução', 'nächste Entwicklung',
    ),
    "shiny": ("Shiny", "이로치", "色違い", "Variocolor",
        'Chromatique', 'Brilhante', 'Schillernd',
    ),
    "raising": ("RAISING", "키우는 중", "育成中", "CRIANDO",
        'EN ÉLEVAGE', 'CRIANDO', 'AUFZUCHT',
    ),
    # status messages
    "status_idle": (
        "Keeping quiet today.", "오늘은 조용히 자리를 지켜요.", "今日は静かにしています。",
        "Hoy se mantiene tranquilo.",
        "Il reste tranquille aujourd'hui.", 'Hoje está quietinho.', 'Heute bleibt es ruhig.',
    ),
    "status_working": (
        "Today's work is piling up.", "오늘의 작업 흔적이 쌓이고 있어요.",
        "本日の作業が積み重なっています。", "El trabajo de hoy se va acumulando.",
        "Le travail du jour s'accumule.", 'O trabalho de hoje vai se acumulando.', 'Die Arbeit von heute häuft sich.',
    ),
    "status_focus": (
        "In focus mode now.", "지금은 집중 모드예요.", "今は集中モードです。",
        "Ahora está en modo concentración.",
        'En mode concentration.', 'Agora em modo de foco.', 'Jetzt im Fokusmodus.',
    ),
    "status_sleep": ("Sleeping now.", "지금은 자고 있어요.", "今は眠っています。", "Ahora está durmiendo.",
        'Il dort en ce moment.', 'Está dormindo agora.', 'Es schläft gerade.',
    ),
    "status_tired": (
        "Careful — the limit is close.", "조심해요 — 한도가 가까워요.", "注意 — 上限が近いです。",
        "Cuidado — el límite está cerca.",
        'Attention — la limite approche.', 'Cuidado — o limite está perto.', 'Vorsicht — das Limit ist nah.',
    ),
    "status_egg": ("An egg is warming up.", "알이 따뜻해지고 있어요.", "タマゴが温まっています。", "Un huevo se está calentando.",
        'Un œuf se réchauffe.', 'Um ovo está esquentando.', 'Ein Ei wird warm.',
    ),
    "status_grew": ("It grew!", "성장했어요!", "成長しました！", "¡Ha crecido!",
        'Il a grandi !', 'Cresceu!', 'Es ist gewachsen!',
    ),
    # shop / bag
    "spendable_tokens": (
        "Spendable tokens", "쓸 수 있는 토큰", "使えるトークン",
        "Tokens disponibles", "Tokens disponibles", "Tokens disponíveis",
        "Verfügbare Tokens",
    ),
    "spend_hint": (
        "Spend the tokens you've used on items.", "사용한 토큰으로 아이템을 살 수 있어요.",
        "使ったトークンでアイテムを買えます。", "Gasta los tokens que has usado en objetos.",
        'Dépensez les jetons déjà utilisés en objets.', 'Gaste em itens os tokens que já usou.', 'Gib die verbrauchten Tokens für Items aus.',
    ),
    "buy": ("Buy", "구매", "購入", "Comprar",
        'Acheter', 'Comprar', 'Kaufen',
    ),
    "owned": ("Owned", "보유 중", "所持中", "En posesión",
        'En possession', 'Em posse', 'Im Besitz',
    ),
    "use": ("Use", "사용", "つかう", "Usar",
        'Utiliser', 'Usar', 'Benutzen',
    ),
    "active": ("Active", "적용 중", "適用中", "Activo",
        'Actif', 'Ativo', 'Aktiv',
    ),
    "bag_empty": ("Your bag is empty.", "가방이 비어 있어요.", "バッグは空です。", "Tu bolsa está vacía.",
        'Votre sac est vide.', 'Sua mochila está vazia.', 'Dein Beutel ist leer.',
    ),
    "price": ("Price", "가격", "価格", "Precio",
        'Prix', 'Preço', 'Preis',
    ),
    "not_enough_tokens": ("Not enough tokens", "토큰이 부족해요", "トークンが足りません", "Tokens insuficientes",
        'Jetons insuffisants', 'Tokens insuficientes', 'Nicht genug Tokens',
    ),
    # dex
    "no_pokemon_yet": (
        "No Pokémon caught yet!", "아직 잡은 포켓몬이 없어요!", "まだ捕まえたポケモンがいません！",
        "¡Aún no has capturado ninguno!",
        'Aucun Pokémon capturé !', 'Nenhum Pokémon capturado ainda!', 'Noch kein Pokémon gefangen!',
    ),
    "legendary": ("Legendary", "전설", "伝説", "Legendario",
        'Légendaire', 'Lendário', 'Legendär',
    ),
    "rare": ("Rare", "희귀", "レア", "Raro",
        'Rare', 'Raro', 'Selten',
    ),
    "uncommon": ("Uncommon", "고급", "アンコモン", "Poco común",
        'Peu commun', 'Incomum', 'Ungewöhnlich',
    ),
    "common": ("Common", "일반", "コモン", "Común",
        'Commun', 'Comum', 'Häufig',
    ),
    # misc
    "refresh": ("Refresh", "새로고침", "更新", "Actualizar",
        'Actualiser', 'Atualizar', 'Aktualisieren',
    ),
    "stale_warning": (
        "Data is stale — is poketokend running?", "데이터가 오래됐어요 — poketokend 실행 중인가요?",
        "データが古いです — poketokend は動作中ですか？",
        "Datos obsoletos — ¿poketokend está en marcha?",
        'Données obsolètes — poketokend tourne-t-il ?', 'Dados desatualizados — o poketokend está em execução?', 'Daten veraltet — läuft poketokend?',
    ),
    "at_this_rate": ("at this rate, full at %1", "이 속도면 %1 에 도달", "このペースだと %1 に到達", "a este ritmo, lleno a las %1",
        'à ce rythme, plein à %1', 'neste ritmo, cheio às %1', 'in diesem Tempo voll um %1',
    ),
    # settings
    #
    # One row per switch. They used to borrow whichever label came closest —
    # three switches read "Limits (official)" and two read "Raising" — which
    # made the settings list a column of duplicates, and the desktop pet a
    # switch nobody could find.
    "setting_tokens_in_panel": ("Tokens in the panel", "패널에 토큰 표시", "パネルにトークン表示", "Tokens en el panel",
        'Jetons dans le panneau', 'Tokens no painel', 'Tokens in der Leiste',
    ),
    "setting_cost_in_panel": ("Cost in the panel", "패널에 비용 표시", "パネルに費用表示", "Coste en el panel",
        'Coût dans le panneau', 'Custo no painel', 'Kosten in der Leiste',
    ),
    "setting_limits_in_panel": ("Limits in the panel", "패널에 한도 표시", "パネルに上限表示", "Límites en el panel",
        'Limites dans le panneau', 'Limites no painel', 'Limits in der Leiste',
    ),
    "setting_limit_notifications": ("Notify on limit warnings", "한도 경고 알림", "上限の警告を通知", "Avisar de los límites",
        'Alerter sur les limites', 'Avisar sobre os limites', 'Bei Limit-Warnungen benachrichtigen',
    ),
    "setting_companion_notifications": ("Notify on companion events", "포켓몬 소식 알림", "ポケモンの出来事を通知", "Avisar del compañero",
        'Alerter sur le compagnon', 'Avisar sobre o companheiro', 'Bei Begleiter-Ereignissen benachrichtigen',
    ),
    "setting_status_checks": ("Check provider status", "서비스 상태 확인", "サービス状態を確認", "Comprobar estado del servicio",
        'Vérifier l\'état des services', 'Verificar o estado dos serviços', 'Dienststatus prüfen',
    ),
    "setting_desktop_pet": ("Desktop pet", "바탕화면에 포켓몬 띄우기", "デスクトップに表示", "Mascota en el escritorio",
        'Mascotte sur le bureau', 'Mascote na área de trabalho', 'Begleiter auf dem Desktop',
    ),
    "setting_pet_bubbles": ("Pet speech bubbles", "포켓몬 말풍선", "ふきだしで知らせる", "Bocadillos de la mascota",
        'Bulles de la mascotte', 'Balões de fala do mascote', 'Sprechblasen des Begleiters',
    ),
    # companion and limit notifications
    "notif_hatch_title": ("🥚 Hatched!", "🥚 부화!", "🥚 孵化！", "🥚 ¡Eclosionó!",
        "🥚 Éclosion !", "🥚 Chocou!", "🥚 Geschlüpft!",
    ),
    "notif_hatch_body": ("%1 hatched from the egg!", "알에서 %1이(가) 나왔어요!", "タマゴから %1 が生まれました！", "¡%1 salió del huevo!",
        "%1 est sorti de l'œuf !", "%1 saiu do ovo!", "%1 ist aus dem Ei geschlüpft!",
    ),
    "notif_shiny_hatch_title": ("✨ Shiny Pokémon!", "✨ 이로치 포켓몬!", "✨ 色違いポケモン！", "✨ ¡Pokémon variocolor!",
        "✨ Pokémon chromatique !", "✨ Pokémon shiny!", "✨ Schillerndes Pokémon!",
    ),
    "notif_shiny_hatch_body": ("A shiny %1 hatched! (1 in 64)", "이로치 %1이(가) 태어났어요! (1/64)", "色違いの %1 が生まれました！(1/64)", "¡Nació un %1 variocolor! (1 entre 64)",
        "Un %1 chromatique est né ! (1 sur 64)", "Nasceu um %1 shiny! (1 em 64)", "Ein schillerndes %1 ist geschlüpft! (1/64)",
    ),
    "notif_evolve_title": ("✨ Evolved!", "✨ 진화!", "✨ 進化！", "✨ ¡Evolucionó!",
        "✨ Évolution !", "✨ Evoluiu!", "✨ Entwicklung!",
    ),
    "notif_evolve_body": ("Evolved into %1!", "%1(으)로 진화했어요!", "%1 に進化しました！", "¡Evolucionó a %1!",
        "A évolué en %1 !", "Evoluiu para %1!", "Hat sich zu %1 entwickelt!",
    ),
    "notif_ditto_title": ("🎭 Huh? It's Ditto!", "🎭 어라? 메타몽!", "🎭 あれ？メタモン！", "🎭 ¿Eh? ¡Es Ditto!",
        "🎭 Hein ? C'est Métamorph !", "🎭 Ué? É um Ditto!", "🎭 Huch? Ditto!",
    ),
    "notif_ditto_body": ("You thought it was %1 — it was Ditto all along!", "%1인 줄 알았는데 — 사실은 메타몽이었어요!", "%1 だと思ってた… 実はメタモンでした！", "Pensabas que era %1 — ¡en realidad era Ditto!",
        "Tu croyais que c'était %1 — c'était Métamorph depuis le début !", "Você achava que era %1 — era um Ditto o tempo todo!", "Du dachtest, es wäre %1 – dabei war es die ganze Zeit Ditto!",
    ),
    "notif_shiny_ditto_title": ("🎭✨ Huh? A shiny Ditto!", "🎭✨ 어라? 이로치 메타몽!", "🎭✨ あれ？色違いメタモン！", "🎭✨ ¿Eh? ¡Un Ditto variocolor!",
        "🎭✨ Hein ? Un Métamorph chromatique !", "🎭✨ Ué? Um Ditto shiny!", "🎭✨ Huch? Ein schillerndes Ditto!",
    ),
    "notif_shiny_ditto_body": ("You thought it was %1 — it was a shiny Ditto! (1 in 64)", "%1인 줄 알았는데 — 이로치 메타몽이었어요! (1/64)", "%1 だと思ってた… 色違いのメタモンでした！(1/64)", "Pensabas que era %1 — ¡era un Ditto variocolor! (1 entre 64)",
        "Tu croyais que c'était %1 — c'était un Métamorph chromatique ! (1 sur 64)", "Você achava que era %1 — era um Ditto shiny! (1 em 64)", "Du dachtest, es wäre %1 – dabei war es ein schillerndes Ditto! (1/64)",
    ),
    "notif_graduate_title": ("🎓 Graduated!", "🎓 졸업!", "🎓 卒業！", "🎓 ¡Graduado!",
        "🎓 Diplômé !", "🎓 Formatura!", "🎓 Abschied!",
    ),
    "notif_graduate_body": ("%1 — saved to your Pokédex! A new egg has arrived.", "%1 — 도감에 보존! 새 알이 도착했어요.", "%1 — 図鑑に保存！新しいタマゴが届きました。", "%1 — ¡guardado en tu Pokédex! Ha llegado un nuevo huevo.",
        "%1 — conservé dans ton Pokédex ! Un nouvel œuf est arrivé.", "%1 — guardado na sua Pokédex! Chegou um novo ovo.", "%1 – in deinem Pokédex gespeichert! Ein neues Ei ist da.",
    ),
    "notif_limit_warning": ("Limit warning", "한도 경고", "上限警告", "Aviso de límite",
        "Alerte de limite", "Aviso de limite", "Limit-Warnung",
    ),
    "notif_limit_critical": ("Limit imminent", "한도 임박", "上限切迫", "Límite inminente",
        "Limite imminente", "Limite iminente", "Limit fast erreicht",
    ),
    "notif_limit_body": ("%1 at %2", "%1 한도 %2 사용", "%1 上限 %2 使用", "%1 al %2",
        "%1 à %2", "%1 em %2", "%1: %2 verbraucht",
    ),
    # companion status
    "status_evolved": ("Evolved into %1!", "%1(으)로 진화했어요!", "%1 に進化しました！", "¡Evolucionó a %1!",
        "A évolué en %1 !", "Evoluiu para %1!", "Hat sich zu %1 entwickelt!",
    ),
    # shop and bag
    "owned_count": ("Owned ×%1", "보유 ×%1", "所持 ×%1", "En posesión ×%1",
        "Possédés ×%1", "Você tem ×%1", "Im Beutel ×%1",
    ),
    "item_rare_candy": ("Rare Candy", "이상한 사탕", "ふしぎなアメ", "Caramelo Raro",
        "Super Bonbon", "Doce Raro", "Sonderbonbon",
    ),
    "item_mint": ("Mint", "민트", "ミント", "Menta",
        "Menthe", "Menta", "Minze",
    ),
    "item_shiny_charm": ("Shiny Charm", "이로치 부적", "ひかるおまもり", "Amuleto Iris",
        "Charme Chroma", "Amuleto Shiny", "Schillerpin",
    ),
    "item_rare_candy_desc": ("Raises your Pokémon's EXP by %1.", "현재 포켓몬의 경험치를 %1 올려줘요.", "ポケモンの経験値を%1上げます。", "Aumenta la experiencia de tu Pokémon en %1.",
        "Augmente l'EXP de ton Pokémon de %1.", "Aumenta a experiência do seu Pokémon em %1.", "Gibt deinem aktuellen Pokémon %1 EP.",
    ),
    "item_mint_desc": ("Randomly changes your Pokémon's nature.", "현재 포켓몬의 성격을 랜덤으로 바꿔줘요.", "ポケモンのせいかくをランダムに変えます。", "Cambia aleatoriamente la naturaleza de tu Pokémon.",
        "Change aléatoirement la nature de ton Pokémon.", "Muda a natureza do seu Pokémon aleatoriamente.", "Ändert das Wesen deines aktuellen Pokémon zufällig.",
    ),
    "item_shiny_charm_desc": ("While owned, raises the chance of hatching a shiny.", "보유하면 이로치 포켓몬이 태어날 확률이 올라가요.", "持っていると色違いが生まれる確率が上がります。", "Mientras lo tengas, aumenta la probabilidad de que nazca un Pokémon variocolor.",
        "Tant que tu le possèdes, augmente les chances qu'un Pokémon chromatique éclose.", "Enquanto estiver na sua bolsa, aumenta a chance de nascer um Pokémon shiny.", "Erhöht im Beutel die Chance, dass ein schillerndes Pokémon schlüpft.",
    ),
    "item_rare_candy_effect": ("+%1 XP", "+%1 XP", "+%1 XP", "+%1 XP",
        "+%1 XP", "+%1 XP", "+%1 EP",
    ),
    "item_mint_effect": ("Random nature", "성격 랜덤 변경", "せいかくランダム変更", "Naturaleza aleatoria",
        "Nature aléatoire", "Natureza aleatória", "Zufälliges Wesen",
    ),
    "item_shiny_charm_effect": ("Shiny rate ↑ · active", "이로치 확률 ↑ · 적용 중", "色違い率↑ · 適用中", "Prob. variocolor ↑ · activo",
        "Taux chromatique ↑ · actif", "Chance shiny ↑ · ativo", "Schillerchance ↑ · aktiv",
    ),
    "egg_common": ("Pokémon Egg", "포켓몬 알", "ポケモンのタマゴ", "Huevo Pokémon",
        "Œuf Pokémon", "Ovo Pokémon", "Pokémon-Ei",
    ),
    "egg_uncommon": ("Uncommon Egg", "고급 알", "アンコモンのタマゴ", "Huevo poco común",
        "Œuf peu commun", "Ovo incomum", "Ungewöhnliches Ei",
    ),
    "egg_rare": ("Rare Egg", "희귀 알", "レアのタマゴ", "Huevo raro",
        "Œuf rare", "Ovo raro", "Seltenes Ei",
    ),
    "egg_desc_fresh": ("Send off your current Pokémon and start fresh with a new egg.", "지금 포켓몬을 놓아주고 새 알로 다시 시작해요.", "いまのポケモンを手放して新しいタマゴからやり直します。", "Suelta a tu Pokémon actual y empieza de nuevo con un huevo nuevo.",
        "Laisse partir ton Pokémon actuel et repars de zéro avec un nouvel œuf.", "Solte seu Pokémon atual e recomece com um ovo novo.", "Verabschiede dein aktuelles Pokémon und starte mit einem neuen Ei.",
    ),
    "egg_desc_guaranteed": ("Send off your current Pokémon for an egg guaranteed to hatch %1 or better.", "지금 포켓몬을 놓아주고 %1 이상이 확정으로 나오는 알을 받아요.", "いまのポケモンを手放して %1 以上が確定で孵るタマゴをもらいます。", "Suelta a tu Pokémon actual y consigue un huevo garantizado de %1 o superior.",
        "Laisse partir ton Pokémon actuel pour un œuf garanti %1 ou mieux.", "Solte seu Pokémon atual e ganhe um ovo que garante %1 ou melhor.", "Verabschiede dein aktuelles Pokémon und erhalte ein Ei, aus dem garantiert ein Pokémon der Seltenheitsstufe %1 oder höher schlüpft.",
    ),
    "egg_guarantee": ("%1 or better", "%1 이상 확정", "%1 以上確定", "%1 o superior garantizado",
        "%1 ou mieux garanti", "%1 ou melhor garantido", "Garantiert %1 oder besser",
    ),
    # settings
    "settings": ("Settings", "설정", "設定", "Ajustes",
        "Réglages", "Ajustes", "Einstellungen",
    ),
    "general": ("General", "일반", "一般", "General",
        "Général", "Geral", "Allgemein",
    ),
    "notifications": ("Notifications", "알림", "通知", "Notificaciones",
        "Notifications", "Notificações", "Benachrichtigungen",
    ),
    "setting_refresh_interval": ("Refresh interval", "새로고침 간격", "更新間隔", "Intervalo de actualización",
        "Intervalle d'actualisation", "Intervalo de atualização", "Aktualisierungsintervall",
    ),
    "setting_warn_threshold": ("Warning", "경고", "警告", "Aviso",
        "Avertissement", "Aviso", "Warnung",
    ),
    "setting_crit_threshold": ("Critical", "임박", "切迫", "Crítico",
        "Critique", "Crítico", "Kritisch",
    ),
    "setting_pet_size": ("Size", "크기", "サイズ", "Tamaño",
        "Taille", "Tamanho", "Größe",
    ),
    "setting_animation": ("Animation", "애니메이션", "アニメーション", "Animación",
        "Animation", "Animação", "Animation",
    ),
    "quality_saver": ("Power saver", "배터리 절약", "バッテリー優先", "Ahorro de batería",
        "Économie d'énergie", "Economia de bateria", "Energiesparmodus",
    ),
    "quality_balanced": ("Balanced", "기본", "標準", "Equilibrado",
        "Équilibré", "Equilibrado", "Ausgewogen",
    ),
    "quality_smooth": ("Smooth", "부드럽게", "滑らか", "Fluido",
        "Fluide", "Fluido", "Flüssig",
    ),
    "setting_limit_display": ("Limit display", "한도 표시 방식", "上限の表示", "Visualización del límite",
        "Affichage de la limite", "Exibição do limite", "Limit-Anzeige",
    ),
    "limits_both": ("Both", "둘 다", "両方", "Ambos",
        "Les deux", "Ambos", "Beide",
    ),
    "setting_language": ("Language", "언어", "言語", "Idioma",
        "Langue", "Idioma", "Sprache",
    ),
    "scan_folders": ("Scan folders", "스캔 폴더", "スキャンフォルダ", "Carpetas de escaneo",
        "Dossiers analysés", "Pastas de varredura", "Scan-Ordner",
    ),
    "setting_scan_roots": ("Additional scan folders", "추가 스캔 폴더", "追加スキャンフォルダ", "Carpetas de escaneo adicionales",
        "Dossiers d'analyse supplémentaires", "Pastas extras para escanear", "Zusätzliche Scan-Ordner",
    ),
    "setting_scan_roots_hint": ("Only for this provider's logs outside the built-in locations. Comma/newline separated, * wildcards. Do not point at another provider's folder.", "선택한 프로바이더의 로그가 기본 위치 밖에 있을 때만. 콤마·줄바꿈 구분, * 와일드카드. 다른 프로바이더 폴더를 넣지 마세요.", "選択したプロバイダーのログが既定の場所にないときだけ。カンマ・改行区切り、*ワイルドカード。別プロバイダーのフォルダは指定しないでください。", "Solo para los registros de este proveedor fuera de las ubicaciones integradas. Separados por coma o salto de línea; comodines *. No indiques la carpeta de otro proveedor.",
        "Uniquement pour les journaux de ce fournisseur en dehors des emplacements intégrés. Séparés par des virgules ou des retours à la ligne ; caractères génériques *. N'indique pas le dossier d'un autre fournisseur.", "Só para os logs deste provedor fora dos locais padrão. Separados por vírgula ou quebra de linha; curingas *. Não aponte para a pasta de outro provedor.", "Nur für Protokolle dieses Anbieters außerhalb der Standardpfade. Durch Kommas oder Zeilenumbrüche getrennt, * als Platzhalter. Wähle keinen Ordner eines anderen Anbieters.",
    ),
    "setting_scan_roots_matches": ("Scans %1 extra folder(s) now", "지금 %1개 추가 폴더를 스캔함", "現在%1個の追加フォルダをスキャン", "Escanea %1 carpeta(s) extra ahora",
        "Analyse %1 dossier(s) supplémentaire(s) maintenant", "Escaneando %1 pasta(s) extra agora", "Zusätzlich gescannte Ordner: %1",
    ),
    "transfer": ("Backup & Transfer", "백업 & 이전", "バックアップと移行", "Copia de seguridad y transferencia",
        "Sauvegarde et transfert", "Backup e transferência", "Sicherung & Übertragung",
    ),
    "export_save": ("Export save", "세이브 내보내기", "セーブを書き出す", "Exportar partida",
        "Exporter la sauvegarde", "Exportar save", "Spielstand exportieren",
    ),
    "import_save": ("Import save", "세이브 불러오기", "セーブを読み込む", "Importar partida",
        "Importer une sauvegarde", "Importar save", "Spielstand importieren",
    ),
    # small words
    "scanning": ("scanning\u2026", "\uac80\uc0c9 \uc911\u2026", "\u30b9\u30ad\u30e3\u30f3\u4e2d\u2026", "escaneando\u2026",
        "analyse\u2026", "verificando\u2026", "wird gescannt \u2026",
    ),
    "on": ("On", "켬", "オン", "Sí",
        "Oui", "Sim", "An",
    ),
    "off": ("Off", "끔", "オフ", "No",
        "Non", "Não", "Aus",
    ),
    "just_now": ("just now", "방금", "たった今", "ahora mismo",
        "à l'instant", "agora mesmo", "gerade eben",
    ),
    "minutes_ago": ("%1 min ago", "%1분 전", "%1分前", "hace %1 min",
        "il y a %1 min", "há %1 min", "vor %1 Min.",
    ),
    "updated": ("Updated", "갱신", "更新", "Actualizado",
        "Mis à jour", "Atualizado", "Aktualisiert",
    ),
    "open": ("Open", "열기", "開く", "Abrir", "Ouvrir", "Abrir", "Öffnen"),
    "quit": ("Quit", "종료", "終了", "Salir", "Quitter", "Sair", "Beenden"),
    "setting_scan_folders": (
        "Extra scan folders", "추가 스캔 폴더", "追加スキャンフォルダ",
        "Carpetas adicionales", "Dossiers supplémentaires", "Pastas adicionais",
        "Zusätzliche Ordner",
    ),
    "scan_folders_hint": (
        "comma or newline separated, * allowed", "쉼표나 줄바꿈으로 구분, * 사용 가능",
        "カンマか改行で区切り、* 使用可", "separadas por comas o saltos de línea, * permitido",
        "séparés par des virgules ou des retours à la ligne, * autorisé",
        "separadas por vírgula ou quebra de linha, * permitido",
        "durch Komma oder Zeilenumbruch getrennt, * erlaubt",
    ),
    "waiting_for_daemon": (
        "Waiting for poketokend…", "poketokend 기다리는 중…", "poketokend を待っています…",
        "Esperando a poketokend…", "En attente de poketokend…",
        "Aguardando o poketokend…", "Warte auf poketokend…",
    ),
    "cannot_read_state": (
        "Cannot read state file", "상태 파일을 읽을 수 없음", "状態ファイルを読めません",
        "No se puede leer el archivo de estado", "Impossible de lire le fichier d'état",
        "Não foi possível ler o arquivo de estado", "Statusdatei nicht lesbar",
    ),
    "updated_just_now": (
        "Updated just now", "방금 갱신", "たった今更新", "Actualizado ahora mismo",
        "Mis à jour à l'instant", "Atualizado agora mesmo", "Gerade aktualisiert",
    ),
    "updated_minutes_ago": (
        "Updated %1 min ago", "%1분 전 갱신", "%1分前に更新", "Actualizado hace %1 min",
        "Mis à jour il y a %1 min", "Atualizado há %1 min", "Vor %1 Min. aktualisiert",
    ),
    "species_count": (
        "%1 species", "%1종", "%1種", "%1 especies", "%1 espèces", "%1 espécies",
        "%1 Spezies",
    ),
    "catches_total": (
        "%1 total", "총 %1마리", "全%1匹", "%1 en total", "%1 au total",
        "%1 no total", "%1 insgesamt",
    ),
    "token_breakdown": (
        "in %1 · out %2 · cache w %3 · r %4",
        "입력 %1 · 출력 %2 · 캐시 쓰기 %3 · 읽기 %4",
        "入力 %1 · 出力 %2 · キャッシュ書込 %3 · 読込 %4",
        "entrada %1 · salida %2 · caché esc. %3 · lec. %4",
        "entrée %1 · sortie %2 · cache écr. %3 · lec. %4",
        "entrada %1 · saída %2 · cache esc. %3 · leit. %4",
        "Eingabe %1 · Ausgabe %2 · Cache-Schr. %3 · Les. %4",
    ),
    "plan": ("Plan", "플랜", "プラン", "Plan", "Forfait", "Plano", "Tarif"),
    "account": ("Account", "계정", "アカウント", "Cuenta", "Compte", "Conta", "Konto"),
    "setting_launch_at_login": (
        "Launch at login", "로그인 시 자동 시작", "ログイン時に自動起動",
        "Iniciar al arrancar sesión", "Lancer à l'ouverture de session",
        "Abrir ao iniciar sessão", "Bei der Anmeldung starten",
    ),
    "setting_limit_percent": (
        "Limit display", "한도 표시 방식", "上限の表示", "Visualización del límite",
        "Affichage de la limite", "Exibição do limite", "Limit-Anzeige",
    ),
    "percent_remaining": (
        "%1 left", "%1 남음", "残り%1", "%1 restante", "%1 restant", "%1 restante",
        "%1 übrig",
    ),
    "unit_day": ("%1d", "%1일", "%1日", "%1 d", "%1 j", "%1 d", "%1 T"),
    "unit_hour": ("%1h", "%1시간", "%1時間", "%1 h", "%1 h", "%1 h", "%1 Std."),
    "unit_minute": ("%1m", "%1분", "%1分", "%1 min", "%1 min", "%1 min", "%1 Min."),
    "unit_second": ("%1s", "%1초", "%1秒", "%1 s", "%1 s", "%1 s", "%1 Sek."),
    "nature_hardy": ("Hardy", "노력", "がんばりや", "Fuerte", "Hardi", "Esforçada", "Robust"),
    "nature_lonely": ("Lonely", "외로움", "さみしがり", "Huraña", "Solo", "Carente", "Solo"),
    "nature_brave": ("Brave", "용감", "ゆうかん", "Audaz", "Brave", "Corajosa", "Mutig"),
    "nature_adamant": ("Adamant", "고집", "いじっぱり", "Firme", "Rigide", "Teimosa", "Hart"),
    "nature_naughty": ("Naughty", "개구쟁이", "やんちゃ", "Pícara", "Mauvais", "Levada", "Frech"),
    "nature_bold": ("Bold", "대담", "ずぶとい", "Osada", "Assuré", "Ousada", "Kühn"),
    "nature_docile": ("Docile", "온순", "すなお", "Dócil", "Docile", "Dócil", "Sanft"),
    "nature_relaxed": ("Relaxed", "무사태평", "のんき", "Plácida", "Relax", "Descontraída", "Locker"),
    "nature_impish": ("Impish", "장난꾸러기", "わんぱく", "Agitada", "Malin", "Travessa", "Pfiffig"),
    "nature_lax": ("Lax", "촐랑", "のうてんき", "Floja", "Lâche", "Despreocupada", "Lasch"),
    "nature_timid": ("Timid", "겁쟁이", "おくびょう", "Miedosa", "Timide", "Medrosa", "Scheu"),
    "nature_hasty": ("Hasty", "성급", "せっかち", "Activa", "Pressé", "Apressada", "Hastig"),
    "nature_serious": ("Serious", "성실", "まじめ", "Seria", "Sérieux", "Séria", "Ernst"),
    "nature_jolly": ("Jolly", "명랑", "ようき", "Alegre", "Jovial", "Alegre", "Froh"),
    "nature_naive": ("Naive", "천진난만", "むじゃき", "Ingenua", "Naïf", "Ingênua", "Naiv"),
    "nature_modest": ("Modest", "조심", "ひかえめ", "Modesta", "Modeste", "Modesta", "Mäßig"),
    "nature_mild": ("Mild", "의젓", "おっとり", "Afable", "Doux", "Meiga", "Mild"),
    "nature_quiet": ("Quiet", "냉정", "れいせい", "Mansa", "Discret", "Discreta", "Ruhig"),
    "nature_bashful": ("Bashful", "수줍음", "てれや", "Tímida", "Pudique", "Tímida", "Zaghaft"),
    "nature_rash": ("Rash", "덜렁", "うっかりや", "Alocada", "Foufou", "Impulsiva", "Hitzig"),
    "nature_calm": ("Calm", "차분", "おだやか", "Serena", "Calme", "Calma", "Still"),
    "nature_gentle": ("Gentle", "얌전", "おとなしい", "Amable", "Gentil", "Gentil", "Zart"),
    "nature_sassy": ("Sassy", "건방", "なまいき", "Grosera", "Malpoli", "Atrevida", "Forsch"),
    "nature_careful": ("Careful", "신중", "しんちょう", "Cauta", "Prudent", "Cautelosa", "Sacht"),
    "nature_quirky": ("Quirky", "변덕", "きまぐれ", "Rara", "Bizarre", "Excêntrica", "Kauzig"),
    "update": ("Update", "업데이트", "アップデート", "Actualizar", "Mise à jour",
               "Atualizar", "Aktualisieren"),
    "update_available": (
        "A new version is available", "새 버전이 있어요", "新しいバージョンがあります",
        "Hay una versión nueva", "Une nouvelle version est disponible",
        "Há uma versão nova", "Eine neue Version ist verfügbar",
    ),
    "update_current": (
        "Up to date (%1)", "최신 버전이에요 (%1)", "最新です（%1）",
        "Está actualizado (%1)", "À jour (%1)", "Está atualizado (%1)",
        "Aktuell (%1)",
    ),
    "update_now": ("Update now", "지금 업데이트", "今すぐ更新", "Actualizar ahora",
                   "Mettre à jour", "Atualizar agora", "Jetzt aktualisieren"),
    "update_restart": (
        "Restart to finish", "다시 시작하면 적용돼요", "再起動で反映されます",
        "Reinicia para terminar", "Redémarre pour terminer",
        "Reinicie para concluir", "Zum Abschluss neu starten",
    ),
    "restart": ("Restart", "다시 시작", "再起動", "Reiniciar", "Redémarrer",
                "Reiniciar", "Neu starten"),
    "update_unsupported": (
        "Installed from a checkout — update it with git",
        "체크아웃에서 실행 중 — git으로 업데이트하세요",
        "チェックアウトから実行中 — git で更新してください",
        "Ejecutando desde un checkout: actualiza con git",
        "Lancé depuis un checkout — mets-le à jour avec git",
        "Rodando de um checkout — atualize com git",
        "Läuft aus einem Checkout — mit git aktualisieren",
    ),
    "weekly_model": (
        "Weekly %1", "주간 %1", "週間 %1", "Semanal %1", "Hebdo %1", "Semanal %1",
        "%1 – wöchentlich",
    ),
    "claude_current_block": (
        "Claude current 5h block", "Claude 현재 5h 블록", "Claude 現在の5hブロック",
        "Bloque actual de 5h de Claude", "Bloc 5 h actuel de Claude",
        "Bloco atual de 5h do Claude", "Aktueller 5-Stunden-Block von Claude",
    ),
    "reset": ("reset", "리셋", "リセット", "reinicio", "réinit.", "reinício", "Reset"),
    "plan_label": (
        "Plan %1", "플랜 %1", "プラン %1", "Plan %1", "Forfait %1", "Plano %1", "Tarif %1",
    ),
    "account_label": (
        "Account %1", "계정 %1", "アカウント %1", "Cuenta %1", "Compte %1", "Conta %1",
        "Konto %1",
    ),
    "forecast_reach": (
        "At current rate, limit hit at %1", "현재 속도면 %1 한도 도달",
        "現在のペースで %1 に上限到達", "Al ritmo actual, límite alcanzado a las %1",
        "À ce rythme, limite atteinte à %1", "No ritmo atual, limite atingido às %1",
        "Bei diesem Tempo erreichst du das Limit um %1",
    ),
    "spendable_tokens_hint": (
        "Spend the tokens you have used on items.",
        "사용한 토큰으로 아이템을 살 수 있어요.",
        "使ったトークンでアイテムを買えます。",
        "Gasta los tokens que has usado en objetos.",
        "Dépense les jetons déjà utilisés en objets.",
        "Gaste os tokens já usados em itens.",
        "Gib die verbrauchten Tokens für Gegenstände aus.",
    ),
    "insufficient_tokens": (
        "Not enough tokens", "토큰이 부족해요", "トークンが足りません",
        "No hay tokens suficientes", "Jetons insuffisants", "Tokens insuficientes",
        "Nicht genug Tokens",
    ),
    "owned_now": ("Owned", "보유 중", "所持中", "En posesión", "Possédé", "Em posse", "Im Besitz"),
    "graduation_remaining": (
        "%1 to graduation", "졸업까지 %1", "卒業まで %1", "%1 para graduarse",
        "%1 avant la remise de diplôme", "%1 para a formatura", "%1 bis zum Abschluss",
    ),
    "evolution_remaining": (
        "%1 to next evolution", "다음 진화까지 %1", "次の進化まで %1",
        "%1 para la próxima evolución", "%1 avant la prochaine évolution",
        "%1 para a próxima evolução", "%1 bis zur nächsten Entwicklung",
    ),
    "back": ("Back", "뒤로", "戻る", "Atrás", "Retour", "Voltar", "Zurück"),
    "show_in_panel": (
        "Show in the panel", "메뉴바에 표시", "メニューバーに表示", "Mostrar en el panel",
        "Afficher dans le panneau", "Mostrar no painel", "In der Leiste anzeigen",
    ),
    "panel_all_off_hint": (
        "With all of these off only the character is shown",
        "전부 끄면 캐릭터만 표시됩니다",
        "すべてオフにするとキャラクターのみ表示されます",
        "Con todo desactivado solo se muestra el personaje",
        "Tout désactivé, seul le personnage est affiché",
        "Com tudo desligado só o personagem aparece",
        "Wenn alles aus ist, wird nur die Figur angezeigt",
    ),
    "floating_pet": (
        "Floating pet", "플로팅 펫", "フローティングペット", "Mascota flotante",
        "Compagnon flottant", "Mascote flutuante", "Schwebender Begleiter",
    ),
    "floating_pet_hint": (
        "The Pokemon floats above your screen — drag it to move it",
        "포켓몬이 화면 위에 떠 있어요 — 드래그로 위치를 옮길 수 있어요",
        "ポケモンが画面上に浮かびます — ドラッグで移動できます",
        "El Pokemon flota sobre la pantalla: arrástralo para moverlo",
        "Le Pokemon flotte sur l'écran — glisse-le pour le déplacer",
        "O Pokemon flutua sobre a tela — arraste para mover",
        "Das Pokemon schwebt über dem Bildschirm — zum Bewegen ziehen",
    ),
    "size": ("Size", "크기", "サイズ", "Tamaño", "Taille", "Tamanho", "Größe"),
    "warn_at": ("Warning", "경고", "警告", "Aviso", "Alerte", "Aviso", "Warnung"),
    "crit_at": ("Critical", "임박", "危険", "Crítico", "Critique", "Crítico", "Kritisch"),
    "animation_hint": (
        "Smoother uses more battery", "부드러울수록 배터리를 더 씁니다",
        "なめらかにするほどバッテリーを消費します",
        "Cuanto más suave, más batería", "Plus c'est fluide, plus ça consomme",
        "Quanto mais suave, mais bateria", "Flüssiger verbraucht mehr Akku",
    ),
    "status_checks_hint": (
        "Shows Claude/OpenAI outages in the popup (not a notification)",
        "Claude·OpenAI 장애를 팝오버에 표시 (알림 아님)",
        "Claude・OpenAI の障害をポップオーバーに表示（通知ではありません）",
        "Muestra incidencias de Claude/OpenAI en el panel (sin notificar)",
        "Affiche les pannes Claude/OpenAI dans le panneau (sans notification)",
        "Mostra falhas do Claude/OpenAI no painel (sem notificação)",
        "Zeigt Claude/OpenAI-Störungen im Panel (keine Benachrichtigung)",
    ),
    "usage": ("Used", "사용량", "使用量", "Usado", "Utilisé", "Usado", "Verbraucht"),
    "remaining": ("Remaining", "남은 양", "残量", "Restante", "Restant", "Restante", "Verbleibend"),
    "representative": (
        "Representative Pokemon", "대표 포켓몬", "代表ポケモン", "Pokemon representativo",
        "Pokemon representatif", "Pokemon representativo", "Repräsentatives Pokemon",
    ),
    "follow_current": (
        "Follow the current Pokemon", "현재 포켓몬 따라가기", "現在のポケモンに従う",
        "Seguir al Pokemon actual", "Suivre le Pokemon actuel",
        "Seguir o Pokemon atual", "Dem aktuellen Pokemon folgen",
    ),
    "weekly_scoped": (
        "Weekly (scoped)", "주간 (모델별)", "週間（モデル別）", "Semanal (por modelo)",
        "Hebdo (par modèle)", "Semanal (por modelo)", "Wöchentlich (pro Modell)",
    ),
    "active_block": (
        "current 5h block", "현재 5h 블록", "現在の5h ブロック", "bloque actual de 5 h",
        "bloc de 5 h en cours", "bloco atual de 5 h", "aktueller 5-Std.-Block",
    ),
    "resets_in": (
        "resets in %1", "리셋 %1", "%1 後にリセット", "se reinicia en %1",
        "réinitialisation dans %1", "reinicia em %1", "Reset in %1",
    ),
    "no_limit_before_reset": (
        "will not reach the limit before it resets",
        "현재 속도로는 리셋 전 한도 도달 없음",
        "現在のペースではリセット前に上限に達しません",
        "a este ritmo no se alcanzará el límite antes del reinicio",
        "à ce rythme, la limite ne sera pas atteinte avant la réinitialisation",
        "neste ritmo o limite não será atingido antes do reinício",
        "erreicht das Limit vor dem Reset nicht",
    ),
}

_INDEX = {code: i for i, code in enumerate(LANGUAGES)}


def t(key: str, language: str = "en") -> str:
    """Resolve one string, falling back to English then to the key itself.

    Returning the key rather than an empty string makes a missing translation
    visible in the UI instead of silently blanking a label.
    """
    row = STRINGS.get(key)
    if row is None:
        return key
    index = _INDEX.get(language, 0)
    # A row shorter than LANGUAGES means a translation was left off. Fall back
    # to English rather than raising: a missing string must not take the whole
    # popover down with it. `test_every_row_covers_every_language` is what
    # actually stops that reaching a release.
    if index >= len(row):
        return row[0]
    return row[index] or row[0]


def catalogue(language: str = "en") -> dict[str, str]:
    """Every string resolved for one language, for shipping in state.json."""
    return {key: t(key, language) for key in STRINGS}


def system_default(preferred: str | None = None) -> str:
    """The language to start in — ports AppLanguage.systemDefault.

    A fresh install defaulting to English left a Korean user reading English
    until they found the setting, which most people will not go looking for.
    Matched on the first two letters, as upstream does: "ko_KR.UTF-8",
    "ko-KR" and "ko" all mean the same thing.

    The environment is consulted in POSIX order, then Windows' own UI language.
    `locale.getdefaultlocale` is deliberately not used: it is deprecated, and on
    Windows it reports the *format* locale, which someone can set to Korean
    dates while running an English interface — or the reverse.
    """
    candidates = []
    if preferred:
        candidates.append(preferred)
    else:
        import os

        for name in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
            value = (os.environ.get(name) or "").strip()
            if value and value not in ("C", "POSIX"):
                candidates.append(value)
        candidates.append(_windows_ui_language() or "")

    for candidate in candidates:
        code = candidate.replace("-", "_").split("_")[0].split(".")[0].lower()
        if code in LANGUAGES:
            return code
    return "en"


def _windows_ui_language() -> str | None:
    """The Windows *interface* language, or None anywhere else.

    Wrapped in its own function so the import cost and the failure are both
    contained: this is called once, at first run, and a machine without the DLL
    should get English rather than a traceback.
    """
    try:
        import ctypes

        lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()  # type: ignore[attr-defined]
        import locale

        return locale.windows_locale.get(lcid)
    except Exception:
        return None


# Each language written in itself. Someone who has landed on the wrong one has
# to recognise theirs, and "ko" in a list of two-letter codes is not something
# to recognise — which is what the language dropdown actually showed.
LANGUAGE_NAMES = {
    "en": "English",
    "ko": "한국어",
    "ja": "日本語",
    "es": "Español",
    "fr": "Français",
    "pt": "Português",
    "de": "Deutsch",
}


LANGUAGE_NAMES = {
    "en": "English",
    "ko": "한국어",
    "ja": "日本語",
    "es": "Español",
    "fr": "Français",
    "pt": "Português",
    "de": "Deutsch",
}
