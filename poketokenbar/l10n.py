"""UI strings in en / ko / ja / es / fr / pt / de — ports Localization.swift.

Strings are resolved in the daemon and shipped through state.json, so QML holds
no catalogue of its own. That keeps one source of truth and means changing the
language takes effect on the next poll without reloading the plasmoid.

Only strings the Linux UI actually renders are included; the Swift file also
covers macOS-only surfaces (Keychain, updater, support mail).
"""

from __future__ import annotations

import re

LANGUAGES = ("en", "ko", "ja", "es", "fr", "pt", "de")

# key: (en, ko, ja, es)
STRINGS: dict[str, tuple[str, ...]] = {
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
    "limits_offline": (
        "Limits: no network connection", "한도: 네트워크에 연결할 수 없음",
        "上限: ネットワークに接続できません", "Límites: sin conexión de red",
        'Limites : pas de connexion réseau', 'Limites: sem conexão de rede',
        'Limits: keine Netzwerkverbindung',
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
    "spendable_tokens": ("Spendable tokens", "사용 가능한 토큰", "使用可能なトークン", "Tokens disponibles",
        'Jetons disponibles', 'Tokens disponíveis', 'Verfügbare Tokens',
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
    "growth_boost": ("%1× growth", "%1× 성장", "成長 %1倍", "Crecimiento ×%1",
        "Croissance ×%1", "Crescimento ×%1", "%1× Wachstum",
    ),
    "dex_released": ("Released", "놓아줌", "逃がした", "Liberado",
        "Relâché", "Solto", "Freigelassen",
    ),
    # Limits shown are the last good ones; refreshing them is failing (ce65fde).
    "stale_limits": ("Stale", "갱신 지연", "更新遅延", "Desactualizado",
        "Périmé", "Desatualizado", "Nicht aktuell",
    ),
    # The wall-clock time a limit resets at, when it is not today (f2fe5ac):
    # %1 weekday, %2 day of the month, %3 24-hour time.
    "reset_clock_far": ("%1 %2, %3", "%2일 (%1) %3", "%2日(%1) %3", "%1 %2, %3",
        "%1 %2, %3", "%1 %2, %3", "%1 %2., %3",
    ),
    "weekday_mon": ("Mon", "월", "月", "lun", "lun.", "seg", "Mo."),
    "weekday_tue": ("Tue", "화", "火", "mar", "mar.", "ter", "Di."),
    "weekday_wed": ("Wed", "수", "水", "mié", "mer.", "qua", "Mi."),
    "weekday_thu": ("Thu", "목", "木", "jue", "jeu.", "qui", "Do."),
    "weekday_fri": ("Fri", "금", "金", "vie", "ven.", "sex", "Fr."),
    "weekday_sat": ("Sat", "토", "土", "sáb", "sam.", "sáb", "Sa."),
    "weekday_sun": ("Sun", "일", "日", "dom", "dim.", "dom", "So."),
    # This month's day-by-day bars (upstream 0912c68).
    "daily_trend": ("Daily this month", "이번 달 일별", "今月の日別", "Diario de este mes",
        "Par jour ce mois-ci", "Diário deste mês", "Täglich",
    ),
    "peak_day": ("Peak", "최다", "最多", "Máx.", "Max.", "Máx.", "Max."),
    # A cost total where nothing could be priced (upstream 69ff39b).
    "cost_unavailable": ("Unavailable", "계산 불가", "計算不可", "No disponible",
        "Indisponible", "Indisponível", "Nicht verfügbar",
    ),
    # Popup layout, as upstream's (PopoverView, SettingsView)
    "stage_of": ("Stage %1 / %2", "진화 단계 %1 / %2", "進化段階 %1 / %2", "Etapa %1 / %2", "Stade %1 / %2", "Estágio %1 / %2", "Entwicklungsstufe %1 / %2"),
    "egg_incubating": ("🥚 Incubating", "🥚 부화 준비 중", "🥚 孵化の準備中", "🥚 Incubando", "🥚 En incubation", "🥚 Incubando", "🥚 Wird ausgebrütet"),
    "egg_imminent": ("About to hatch!", "곧 부화해요!", "もうすぐ孵化！", "¡Está a punto de eclosionar!", "Sur le point d'éclore !", "Está quase chocando!", "Schlüpft gleich!"),
    "egg_to_hatch": ("%1 to hatch", "부화까지 %1", "孵化まで %1", "%1 para eclosionar", "%1 avant l'éclosion", "%1 para chocar", "%1 bis zum Schlüpfen"),
    "to_next_evolution": ("%1 to next evolution", "다음 진화까지 %1", "次の進化まで %1", "%1 para la siguiente evolución", "%1 avant la prochaine évolution", "%1 para a próxima evolução", "%1 bis zur nächsten Entwicklung"),
    "to_graduation": ("%1 to graduation", "졸업까지 %1", "卒業まで %1", "%1 para graduarse", "%1 avant le diplôme", "%1 para se formar", "%1 bis zum Abschied"),
    "percent_left": ("%1 left", "%1 남음", "残り%1", "%1 restante", "%1 restant", "%1 restante", "%1 übrig"),
    "limit_value_used": ("Used", "사용량", "使用量", "Usado", "Utilisé", "Usado", "Verbraucht"),
    "limit_value_remaining": ("Remaining", "남은 양", "残量", "Restante", "Restant", "Restante", "Verbleibend"),
    "setting_limit_value": ("Limit display", "한도 표시 방식", "上限の表示", "Visualización del límite", "Affichage de la limite", "Exibição do limite", "Limit-Anzeige"),
    "plan_label": ("Plan %1", "플랜 %1", "プラン %1", "Plan %1", "Forfait %1", "Plano %1", "Tarif %1"),
    "account_label": ("Account %1", "계정 %1", "アカウント %1", "Cuenta %1", "Compte %1", "Conta %1", "Konto %1"),
    "species_total": ("%1 species", "%1종", "%1種", "%1 especies", "%1 espèces", "%1 espécies", "%1 Spezies"),
    "catch_total": ("%1 total", "총 %1마리", "全%1匹", "%1 en total", "%1 au total", "%1 no total", "%1 insgesamt"),
    "buy_confirm": ("Buy %1?", "%1 구매할까요?", "%1 を購入しますか？", "¿Comprar %1?", "Acheter %1 ?", "Comprar %1?", "%1 kaufen?"),
    "owned_already": ("Owned", "보유 중", "所持済み", "En posesión", "Possédé", "Já tem", "Im Beutel"),
    "refresh_now": ("Refresh now", "지금 새로고침", "今すぐ更新", "Actualizar ahora", "Actualiser maintenant", "Atualizar agora", "Jetzt aktualisieren"),
    "section_panel": ("Show in panel", "패널에 표시", "パネルに表示", "Mostrar en el panel", "Afficher dans le panneau", "Mostrar no painel", "In der Leiste anzeigen"),
    "all_off_hint": ("All off shows only the character", "전부 끄면 캐릭터만 표시됩니다", "すべてオフにするとキャラクターのみ表示", "Si desactivas todo, solo se mostrará el personaje", "Tout désactiver n'affiche que le personnage", "Se desativar tudo, só o personagem aparece", "Wenn du alles ausschaltest, wird nur das Pokémon angezeigt"),
    "setting_panel_limit_windows": ("Limits in panel", "패널에 표시할 한도", "パネルに表示する上限", "Límites en el panel", "Limites dans le panneau", "Limites no painel", "Limits in der Leiste"),
    "section_pet": ("Floating Pet", "플로팅 펫", "フローティングペット", "Mascota flotante", "Compagnon flottant", "Mascote flutuante", "Schwebendes Pokémon"),
    "pet_hint": ("Your Pokémon floats over the screen — drag to reposition", "포켓몬이 화면 위에 떠 있어요 — 드래그로 위치를 옮길 수 있어요", "ポケモンが画面の上に浮かびます — ドラッグで移動できます", "Tu Pokémon flota sobre la pantalla — arrástralo para moverlo", "Ton Pokémon flotte au-dessus de l'écran — fais-le glisser pour le déplacer", "Seu Pokémon flutua sobre a tela — arraste para reposicionar", "Dein Pokémon schwebt über dem Bildschirm – zieh es an die gewünschte Stelle"),
    "animation_hint": ("Smoother uses more battery", "부드러울수록 배터리를 더 씁니다", "滑らかにするとバッテリー消費が増えます", "Más fluido consume más batería", "Plus fluide consomme plus de batterie", "Mais fluido consome mais bateria", "Flüssigere Animationen verbrauchen mehr Batterie"),
    "status_checks_hint": ("Show Claude / OpenAI incidents in the popup (not a notification)", "Claude·OpenAI 장애를 팝업에 표시 (알림 아님)", "Claude・OpenAIの障害をポップアップに表示（通知ではない）", "Muestra incidentes de Claude/OpenAI en la ventana (no es una notificación)", "Affiche les incidents Claude / OpenAI dans la fenêtre (pas une notification)", "Mostra incidentes do Claude/OpenAI no painel (não é uma notificação)", "Störungen bei Claude / OpenAI im Popup anzeigen (keine Benachrichtigung)"),
    "section_transfer": ("Backup & Transfer", "백업 & 이전", "バックアップと移行", "Copia de seguridad y transferencia", "Sauvegarde et transfert", "Backup e transferência", "Sicherung & Übertragung"),
    "export_hint": ("Saves your Pokédex, lifetime tokens, Bag, and current Pokémon as one file", "도감·누적 토큰·가방·현재 포켓몬을 파일 하나로 저장해요", "図鑑・累計トークン・バッグ・現在のポケモンを1つのファイルに保存します", "Guarda tu Pokédex, tokens acumulados, Bolsa y Pokémon actual en un solo archivo", "Enregistre ton Pokédex, tes tokens cumulés, ton Sac et ton Pokémon actuel dans un seul fichier", "Salva sua Pokédex, tokens acumulados, Bolsa e Pokémon atual em um único arquivo", "Speichert deinen Pokédex, alle bisherigen Tokens, den Beutel und dein aktuelles Pokémon in einer Datei"),
    "import_hint": ("Continue here with a file exported from another computer", "다른 컴퓨터에서 내보낸 파일로 여기서 이어서 키워요", "他のコンピューターから書き出したファイルでここから続けます", "Continúa aquí con un archivo exportado desde otro ordenador", "Continue ici avec un fichier exporté depuis un autre ordinateur", "Continue por aqui com um arquivo exportado de outro computador", "Mach hier mit einer auf einem anderen Computer exportierten Datei weiter"),
    "section_advanced": ("Advanced", "고급", "詳細", "Avanzado", "Avancé", "Avançado", "Erweitert"),
    "duration_days_hours": ("%1 days, %2 hr", "%1일 %2시간", "%1日 %2時間", "%1 días, %2 h", "%1 j, %2 h", "%1 dias, %2 h", "%1 Tage, %2 Std."),
    "duration_hours_minutes": ("%1 hr, %2 min", "%1시간 %2분", "%1時間 %2分", "%1 h, %2 min", "%1 h %2 min", "%1 h, %2 min", "%1 Std., %2 Min."),
    "duration_minutes": ("%1 min", "%1분", "%1分", "%1 min", "%1 min", "%1 min", "%1 Min."),
    "minutes_unit": ("%1 min", "%1분", "%1分", "%1 min", "%1 min", "%1 min", "%1 Min."),
    # Pokédex detail page (upstream b6bf676)
    "detail_back": ("Back", "뒤로", "戻る", "Atrás", "Retour", "Voltar", "Zurück"),
    "retry": ("Retry", "다시 시도", "再試行", "Reintentar", "Réessayer", "Tentar novamente", "Erneut versuchen"),
    "loading_pokemon_details": ("Loading Pokémon details…", "포켓몬 정보를 불러오는 중…", "ポケモン情報を読み込み中…", "Cargando detalles del Pokémon…", "Chargement des détails du Pokémon…", "Carregando detalhes do Pokémon…", "Pokémon-Details werden geladen…"),
    "pokemon_details_unavailable": ("Pokémon details could not be loaded.", "포켓몬 정보를 불러오지 못했어요.", "ポケモン情報を読み込めませんでした。", "No se pudieron cargar los detalles.", "Impossible de charger les détails.", "Não foi possível carregar os detalhes.", "Pokémon-Details konnten nicht geladen werden."),
    "pokemon_individual": ("Individual", "개체", "個体", "Ejemplar", "Individu", "Indivíduo", "Individuum"),
    "level": ("Level", "레벨", "レベル", "Nivel", "Niveau", "Nível", "Level"),
    "gender": ("Gender", "성별", "性別", "Sexo", "Sexe", "Gênero", "Geschlecht"),
    "nature": ("Nature", "성격", "性格", "Naturaleza", "Nature", "Natureza", "Wesen"),
    "ability": ("Ability", "특성", "特性", "Habilidad", "Talent", "Habilidade", "Fähigkeit"),
    "hidden_ability": ("Hidden Ability", "숨겨진 특성", "隠れ特性", "Habilidad oculta", "Talent caché", "Habilidade oculta", "Versteckte Fähigkeit"),
    "hidden": ("Hidden", "숨김", "隠れ", "Oculta", "Caché", "Oculta", "Versteckt"),
    "known_moves": ("Known moves", "배운 기술", "覚えている技", "Movimientos conocidos", "Capacités connues", "Golpes conhecidos", "Erlernte Attacken"),
    "no_level_moves": ("No level-up moves learned at this level.", "현재 레벨에서 배운 기술이 없어요.", "現在のレベルで覚えた技はありません。", "No hay movimientos aprendidos a este nivel.", "Aucune capacité apprise à ce niveau.", "Nenhum golpe aprendido neste nível.", "Auf diesem Level wurden keine Attacken erlernt."),
    "actual_stats": ("Actual stats", "실제 능력치", "実能力値", "Estadísticas reales", "Stats réelles", "Atributos reais", "Tatsächliche Werte"),
    "base_stats": ("Base stats", "기본 능력치", "種族値", "Estadísticas base", "Stats de base", "Atributos base", "Basiswerte"),
    "species_data": ("Species data", "종 정보", "種情報", "Datos de especie", "Données de l’espèce", "Dados da espécie", "Speziesdaten"),
    "height": ("Height", "키", "高さ", "Altura", "Taille", "Altura", "Größe"),
    "weight": ("Weight", "몸무게", "重さ", "Peso", "Poids", "Peso", "Gewicht"),
    "base_stat_total": ("Base total", "합계", "合計", "Total base", "Total de base", "Total base", "Basiswertsumme"),
    "possible_abilities": ("Possible abilities", "가능한 특성", "可能な特性", "Habilidades posibles", "Talents possibles", "Habilidades possíveis", "Mögliche Fähigkeiten"),
    "complete_move_list": ("Complete move list · %1", "전체 기술 목록 %1개", "全技リスト・%1", "Lista completa · %1", "Liste complète · %1", "Lista completa · %1", "Vollständige Attackenliste · %1"),
    "gender_male": ("Male", "수컷", "オス", "Macho", "Mâle", "Macho", "Männlich"),
    "gender_female": ("Female", "암컷", "メス", "Hembra", "Femelle", "Fêmea", "Weiblich"),
    "gender_genderless": ("Genderless", "무성", "性別不明", "Sin género", "Asexué", "Sem gênero", "Geschlechtslos"),
    "stat_hp": ("HP", "HP", "HP", "HP", "HP", "HP", "HP"),
    "stat_attack": ("Attack", "공격", "こうげき", "Ataque", "Attaque", "Ataque", "Angriff"),
    "stat_defense": ("Defense", "방어", "ぼうぎょ", "Defensa", "Défense", "Defesa", "Vert."),
    "stat_special_attack": ("Sp. Atk", "특공", "とくこう", "At. Esp.", "Atq. Spé.", "Atq. Esp.", "Sp.-Ang."),
    "stat_special_defense": ("Sp. Def", "특방", "とくぼう", "Def. Esp.", "Déf. Spé.", "Def. Esp.", "Sp.-Vert."),
    "stat_speed": ("Speed", "스피드", "すばやさ", "Velocidad", "Vitesse", "Velocidade", "Initiative"),
    "move_method_start": ("Start", "시작", "基本", "Inicio", "Départ", "Inicial", "Start"),
    "move_method_egg": ("Egg", "교배", "タマゴ", "Huevo", "Œuf", "Ovo", "Ei"),
    "move_method_tutor": ("Tutor", "가르침", "教え", "Tutor", "Maître", "Tutor", "Tutor"),
    "pin_to_panel": ("Pin to panel", "패널에 고정", "パネルに固定", "Fijar en el panel", "Épingler au panneau", "Fixar no painel", "An die Leiste heften"),
    "dex_detail_hint": ("Tap a Pokémon to see its details and pin it to the panel.", "포켓몬을 누르면 상세 정보를 보고 패널에 고정할 수 있어요.", "ポケモンをタップすると詳細を表示し、パネルに固定できます。", "Toca un Pokémon para ver sus detalles y fijarlo en el panel.", "Touchez un Pokémon pour voir ses détails et l'épingler au panneau.", "Toque em um Pokémon para ver os detalhes e fixá-lo no painel.", "Tippe ein Pokémon an, um Details zu sehen und es an die Leiste zu heften."),
    "egg_shop_locked_hint": (
        "Available once your current egg hatches.",
        "지금 품고 있는 알이 부화하면 살 수 있어요.",
        "いま抱えているタマゴが孵ると購入できます。",
        "Disponible cuando eclosione tu huevo actual.",
        "Disponible une fois ton œuf actuel éclos.",
        "Disponível quando seu ovo atual chocar.",
        "Verfügbar, sobald dein aktuelles Ei geschlüpft ist.",
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
    # The shortcut on a quantity stepper: jump to everything the wallet covers.
    "quantity_max": ("Max", "최대", "最大", "Máx.",
        "Max", "Máx.", "Max",
    ),
    "price": ("Price", "가격", "価格", "Precio",
        'Prix', 'Preço', 'Preis',
    ),
    # Pace against a limit window (upstream 68deb09, 2eec9af). Deliberately not
    # called a "recommended" amount: it is the line where an even burn would
    # sit, not advice to use less, and there is no reason to fill a window.
    # Where an even burn would sit right now. Short, because it shares a line
    # with the tier name and the delta; upstream has the room for a sentence in
    # a tooltip, a panel popup does not.
    "pace_hint": ("Pace %1", "페이스 %1", "ペース %1", "Ritmo %1",
        "Rythme %1", "Ritmo %1", "Tempo %1",
    ),
    "pace_way_under": ("Well under pace", "여유 많음", "かなり余裕", "Muy por debajo del ritmo",
        "Bien sous le rythme", "Bem abaixo do ritmo", "Deutlich unter Tempo",
    ),
    "pace_under": ("Under pace", "여유", "余裕あり", "Por debajo del ritmo",
        "Sous le rythme", "Abaixo do ritmo", "Unter Tempo",
    ),
    "pace_on_pace": ("On pace", "페이스대로", "ペース通り", "Al ritmo",
        "Dans le rythme", "No ritmo", "Im Tempo",
    ),
    "pace_slightly_over": ("Slightly fast", "조금 빠름", "やや速い", "Algo rápido",
        "Un peu rapide", "Um pouco rápido", "Etwas schnell",
    ),
    "pace_over": ("Fast", "빠름", "速い", "Rápido",
        "Rapide", "Rápido", "Schnell",
    ),
    "pace_way_over": ("Very fast", "매우 빠름", "とても速い", "Muy rápido",
        "Très rapide", "Muito rápido", "Sehr schnell",
    ),
    # Said as an amount used, never as a position: in remaining mode the fill is
    # drawn shorter than the mark, and "ahead of the line" then reads backwards.
    "pace_delta_over": ("%1 pts more used", "페이스보다 %1%p 더 씀", "ペースより%1pt多く使用",
        "%1 pts más de uso", "%1 pts de plus utilisés", "%1 p.p. a mais de uso",
        "%1 Pkt. mehr verbraucht",
    ),
    "pace_delta_under": ("%1 pts less used", "페이스보다 %1%p 덜 씀", "ペースより%1pt少なく使用",
        "%1 pts menos de uso", "%1 pts de moins utilisés", "%1 p.p. a menos de uso",
        "%1 Pkt. weniger verbraucht",
    ),
    "not_enough_tokens": ("Not enough tokens", "토큰이 부족해요", "トークンが足りません", "Tokens insuficientes",
        'Jetons insuffisants', 'Tokens insuficientes', 'Nicht genug Tokens',
    ),
    # dex
    # The appearance picker on a Pokédex page: a species collected both ways
    # has two of them, and one used to hide the other (upstream 4bfae97).
    # Searching, sorting and filtering the Pokédex and the catch log
    # (upstream ae7bd9d).
    "dex_search_placeholder": ("Search name or #…", "이름 또는 #번호 검색…", "名前または#番号で検索…",
        "Buscar por nombre o #…", "Rechercher par nom ou #…", "Buscar por nome ou #…",
        "Nach Name oder # suchen…",
    ),
    "sort_title": ("Sort", "정렬", "並び替え", "Ordenar", "Trier", "Ordenar", "Sortieren"),
    "sort_number_asc": ("Number ↑", "번호 ↑", "図鑑番号 ↑", "Nº ↑", "N° ↑", "Nº ↑", "Nummer ↑"),
    "sort_number_desc": ("Number ↓", "번호 ↓", "図鑑番号 ↓", "Nº ↓", "N° ↓", "Nº ↓", "Nummer ↓"),
    "sort_name_asc": ("Name A–Z", "이름 가나다", "名前 A-Z", "Nombre A–Z", "Nom A–Z", "Nome A–Z",
        "Name A–Z",
    ),
    "sort_rarity_desc": ("Rarity ↓", "희귀도 순", "希少度順", "Rareza ↓", "Rareté ↓", "Raridade ↓",
        "Seltenheit ↓",
    ),
    "sort_date_desc": ("Most recent", "최근 순", "最近捕獲", "Más recientes", "Plus récents",
        "Mais recentes", "Neueste zuerst",
    ),
    "sort_date_asc": ("Oldest first", "오래된 순", "古い順", "Más antiguos", "Plus anciens",
        "Mais antigos", "Älteste zuerst",
    ),
    "filter_shiny_only": ("Shiny only", "이로치만", "色違いのみ", "Solo variocolor",
        "Chromatique uniquement", "Apenas Shiny", "Nur schillernde",
    ),
    "no_search_results": ("No Pokémon found", "검색 결과가 없어요", "見つかりませんでした",
        "No se encontraron Pokémon", "Aucun Pokémon trouvé", "Nenhum Pokémon encontrado",
        "Keine Pokémon gefunden",
    ),
    "clear_filters": ("Reset filters", "필터 초기화", "フィルターを解除", "Restablecer filtros",
        "Réinitialiser les filtres", "Redefinir filtros", "Filter zurücksetzen",
    ),
    "dex_normal_label": ("Normal", "일반", "通常", "Normal", "Normal", "Normal", "Normal"),
    "dex_appearance": ("Appearance", "모습", "姿", "Aspecto", "Apparence", "Aparência", "Aussehen"),
    "dex_appearance_preview": (
        "Collected appearance · species reference",
        "수집한 모습 · 종 정보",
        "収集した姿・種情報",
        "Aspecto coleccionado · datos de especie",
        "Apparence collectionnée · données de l'espèce",
        "Aparência coletada · dados da espécie",
        "Gesammeltes Aussehen · Speziesdaten",
    ),
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
    "notif_hatch_body": ("%1 hatched from the egg!", "알에서 %1{s} 나왔어요!", "タマゴから %1 が生まれました！", "¡%1 salió del huevo!",
        "%1 est sorti de l'œuf !", "%1 saiu do ovo!", "%1 ist aus dem Ei geschlüpft!",
    ),
    "notif_shiny_hatch_title": ("✨ Shiny Pokémon!", "✨ 이로치 포켓몬!", "✨ 色違いポケモン！", "✨ ¡Pokémon variocolor!",
        "✨ Pokémon chromatique !", "✨ Pokémon shiny!", "✨ Schillerndes Pokémon!",
    ),
    "notif_shiny_hatch_body": ("A shiny %1 hatched! (1 in %2)", "이로치 %1{s} 태어났어요! (1/%2)", "色違いの %1 が生まれました！(1/%2)", "¡Nació un %1 variocolor! (1 entre %2)",
        "Un %1 chromatique est né ! (1 sur %2)", "Nasceu um %1 shiny! (1 em %2)", "Ein schillerndes %1 ist geschlüpft! (1/%2)",
    ),
    "notif_evolve_title": ("✨ Evolved!", "✨ 진화!", "✨ 進化！", "✨ ¡Evolucionó!",
        "✨ Évolution !", "✨ Evoluiu!", "✨ Entwicklung!",
    ),
    "notif_evolve_body": ("Evolved into %1!", "%1{d} 진화했어요!", "%1 に進化しました！", "¡Evolucionó a %1!",
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
    "notif_shiny_ditto_body": ("You thought it was %1 — it was a shiny Ditto!", "%1인 줄 알았는데 — 이로치 메타몽이었어요!", "%1 だと思ってた… 色違いのメタモンでした！", "Pensabas que era %1 — ¡era un Ditto variocolor!",
        "Tu croyais que c'était %1 — c'était un Métamorph chromatique !", "Você achava que era %1 — era um Ditto shiny!", "Du dachtest, es wäre %1 – dabei war es ein schillerndes Ditto!",
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
    "status_evolved": ("Evolved into %1!", "%1{d} 진화했어요!", "%1 に進化しました！", "¡Evolucionó a %1!",
        "A évolué en %1 !", "Evoluiu para %1!", "Hat sich zu %1 entwickelt!",
    ),
    # shop and bag
    # A bare quantity mark. The same in every language, and one place to change
    # if a language ever needs a different one.
    "times_count": ("×%1", "×%1", "×%1", "×%1",
        "×%1", "×%1", "×%1",
    ),
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
    # Rare Candy batch preview — what using this many at once would do.
    "candy_graduates": ("Expected to graduate.", "이 포켓몬은 졸업할 것으로 예상돼요.",
        "卒業する見込みです。", "Se espera que se gradúe.",
        "Devrait terminer sa croissance.", "Deve se formar.",
        "Schließt voraussichtlich sein Training ab.",
    ),
    "candy_carryover_xp": (
        "Expected after evolution: %1 XP carried over.",
        "예상 진화 후 이월 경험치: %1 XP.",
        "進化後の予想繰越経験値：%1 XP。",
        "Tras evolucionar: %1 XP de remanente previsto.",
        "Après évolution : %1 XP de report prévu.",
        "Após evoluir: previsão de %1 XP restantes.",
        "Nach der Entwicklung: voraussichtlich %1 EP übertragen.",
    ),
    "candy_discarded_xp": (
        "On graduation, %1 leftover XP will be discarded.",
        "졸업 시 남는 %1 XP는 사라져요.",
        "卒業時、余った%1 XPは失われます。",
        "Al graduarse, se perderán %1 XP sobrantes.",
        "À la fin de la croissance, les %1 XP restants seront perdus.",
        "Ao se formar, %1 XP restantes serão descartados.",
        "Beim Trainingsabschluss verfallen %1 überschüssige EP.",
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
    # What a release actually costs. The description above says a Pokémon is
    # sent off, which reads as losing it from the Pokédex too — it is not, and
    # the same species can hatch again at the same odds (upstream c951492).
    "egg_release_note": (
        "A released Pokémon stays in your Pokédex and can hatch again at the same odds — only the growth progress is lost.",
        "놓아준 포켓몬도 도감에 남고, 같은 확률로 다시 만날 수 있어요. 키운 진행도만 사라져요.",
        "手放したポケモンも図鑑に残り、同じ確率でまた出会えます。失われるのは育てた進み具合だけです。",
        "El Pokémon liberado permanece en la Pokédex y puede volver a salir con la misma probabilidad; solo se pierde el progreso de crianza.",
        "Un Pokémon relâché reste dans le Pokédex et peut réapparaître avec la même probabilité ; seule la progression est perdue.",
        "O Pokémon solto continua na Pokédex e pode voltar a aparecer com a mesma chance; só o progresso de criação se perde.",
        "Ein freigelassenes Pokémon bleibt im Pokédex und kann mit gleicher Wahrscheinlichkeit wieder schlüpfen; nur der Aufzuchtfortschritt geht verloren.",
    ),
    # The second confirmation an egg needs when the companion it would discard
    # is shiny or legendary (upstream b4ff5de). A rare one is not guarded: they
    # are common enough that the extra tap becomes reroll fatigue.
    "fresh_egg_shiny_warning": (
        "⚠️ This one is shiny! Really send it off?",
        "⚠️ 이로치 포켓몬이에요! 정말 놓아줄까요?",
        "⚠️ 色違いです！本当に手放しますか？",
        "⚠️ ¡Este es variocolor! ¿Seguro que quieres soltarlo?",
        "⚠️ Celui-ci est chromatique ! Vraiment le laisser partir ?",
        "⚠️ Esse é shiny! Quer mesmo soltar?",
        "⚠️ Dieses Pokémon ist schillernd! Wirklich verabschieden?",
    ),
    "fresh_egg_legendary_warning": (
        "⚠️ This is a Legendary Pokémon! Really send it off?",
        "⚠️ 전설 포켓몬이에요! 정말 놓아줄까요?",
        "⚠️ 伝説のポケモンです！本当に手放しますか？",
        "⚠️ ¡Es un Pokémon legendario! ¿Seguro que quieres soltarlo?",
        "⚠️ C'est un Pokémon légendaire ! Vraiment le laisser partir ?",
        "⚠️ Esse é um Pokémon lendário! Quer mesmo soltar?",
        "⚠️ Dieses Pokémon ist legendär! Wirklich verabschieden?",
    ),
    "fresh_egg_discard_shiny": ("Send shiny off", "이로치 놓아주기", "手放す", "Soltar variocolor",
        "Laisser partir le chromatique", "Soltar o shiny", "Schillerndes Pokémon verabschieden",
    ),
    "fresh_egg_discard_valuable": ("Send off", "놓아주기", "手放す", "Soltar",
        "Laisser partir", "Soltar", "Verabschieden",
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
    "difficulty_section": ("Difficulty", "난이도", "難易度", "Dificultad",
        "Difficulté", "Dificuldade", "Schwierigkeit",
    ),
    "difficulty_growth": ("Growth", "성장", "成長", "Crecimiento",
        "Croissance", "Crescimento", "Wachstum",
    ),
    "difficulty_shop": ("Shop prices", "상점 가격", "ショップ価格", "Precios de la tienda",
        "Prix de la boutique", "Preços da loja", "Shop-Preise",
    ),
    "difficulty_hint": (
        "Percentages of the default balance — lower grows faster and costs less, higher does the opposite",
        "기본값 100% 기준이에요 — 낮추면 빨리 자라고 싸지고, 높이면 그 반대예요",
        "標準バランスに対する割合です — 下げると早く育ち安くなり、上げるとその逆になります",
        "Porcentajes del balance predeterminado: si los bajas, crece más rápido y cuesta menos; si los subes, al revés",
        "Pourcentages de l'équilibrage par défaut — plus bas, la croissance est plus rapide et les prix baissent ; plus haut, l'inverse",
        "Porcentagens do balanceamento padrão — reduzir faz crescer mais rápido e custar menos; aumentar faz o contrário",
        "Prozentwerte der Standardbalance — niedriger wächst schneller und kostet weniger, höher bewirkt das Gegenteil",
    ),
    "setting_animation": ("Animation", "애니메이션", "アニメーション", "Animación",
        "Animation", "Animação", "Animation",
    ),
    # Not a rate but the absence of one: the sprite holds its first frame and
    # stops asking for redraws.
    "quality_off": ("Off", "끄기", "オフ", "Desactivada",
        "Désactivée", "Desativada", "Aus",
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
    # Importing overwrites a Pokédex, so the popup asks first and says exactly
    # what it is about to replace, and with what.
    "import_confirm": ("Replace this save?", "현재 세이브를 덮어쓸까요?", "現在のセーブを上書きしますか？", "¿Reemplazar esta partida?",
        "Remplacer cette sauvegarde ?", "Substituir este save?", "Diesen Spielstand ersetzen?",
    ),
    "import_file_detail": ("File: %1 · Pokédex %2 · %3 tokens", "파일: %1 · 도감 %2 · %3 토큰", "ファイル: %1 · 図鑑 %2 · %3 トークン", "Archivo: %1 · Pokédex %2 · %3 tokens",
        "Fichier : %1 · Pokédex %2 · %3 jetons", "Arquivo: %1 · Pokédex %2 · %3 tokens", "Datei: %1 · Pokédex %2 · %3 Tokens",
    ),
    "import_current_detail": ("Now: Pokédex %1 · %2 tokens", "현재: 도감 %1 · %2 토큰", "現在: 図鑑 %1 · %2 トークン", "Ahora: Pokédex %1 · %2 tokens",
        "Actuel : Pokédex %1 · %2 jetons", "Agora: Pokédex %1 · %2 tokens", "Jetzt: Pokédex %1 · %2 Tokens",
    ),
    "import_goes_backwards": ("This file holds less progress than your current save.", "이 파일은 현재 세이브보다 진행이 적습니다.", "このファイルは現在のセーブより進行が少ないです。", "Este archivo tiene menos progreso que tu partida actual.",
        "Ce fichier contient moins de progression que votre sauvegarde actuelle.", "Este arquivo tem menos progresso que o save atual.", "Diese Datei enthält weniger Fortschritt als dein aktueller Spielstand.",
    ),
    "import_no_file": ("Nothing to import: no export at %1", "불러올 파일이 없습니다: %1 없음", "読み込むファイルがありません: %1 がありません", "Nada que importar: no hay exportación en %1",
        "Rien à importer : aucun export dans %1", "Nada para importar: nenhum export em %1", "Nichts zu importieren: kein Export unter %1",
    ),
    "import_unreadable": ("Not a PokeTokenBar save file", "PokeTokenBar 세이브 파일이 아닙니다", "PokeTokenBar のセーブファイルではありません", "No es un archivo de partida de PokeTokenBar",
        "Ce n'est pas une sauvegarde PokeTokenBar", "Não é um arquivo de save do PokeTokenBar", "Keine PokeTokenBar-Speicherdatei",
    ),
    "undo_import": ("Undo import", "불러오기 되돌리기", "読み込みを元に戻す", "Deshacer importación",
        "Annuler l'import", "Desfazer importação", "Import rückgängig",
    ),
    "undo_confirm": ("Restore the save from before the import?", "불러오기 이전 세이브로 되돌릴까요?", "読み込み前のセーブに戻しますか？", "¿Restaurar la partida anterior a la importación?",
        "Restaurer la sauvegarde d'avant l'import ?", "Restaurar o save anterior à importação?", "Den Spielstand von vor dem Import wiederherstellen?",
    ),
    "undo_file_detail": ("Backup: %1 · Pokédex %2 · %3 tokens", "백업: %1 · 도감 %2 · %3 토큰", "バックアップ: %1 · 図鑑 %2 · %3 トークン", "Copia: %1 · Pokédex %2 · %3 tokens",
        "Sauvegarde : %1 · Pokédex %2 · %3 jetons", "Backup: %1 · Pokédex %2 · %3 tokens", "Sicherung: %1 · Pokédex %2 · %3 Tokens",
    ),
    "restore": ("Restore", "되돌리기", "元に戻す", "Restaurar",
        "Restaurer", "Restaurar", "Wiederherstellen",
    ),
    "replace": ("Replace", "덮어쓰기", "上書き", "Reemplazar",
        "Remplacer", "Substituir", "Ersetzen",
    ),
    "cancel": ("Cancel", "취소", "キャンセル", "Cancelar",
        "Annuler", "Cancelar", "Abbrechen",
    ),
    # Notifications the daemon sends back after a transfer.
    "save_exported": ("Save exported to %1", "%1{d} 세이브를 내보냈습니다", "%1 にセーブを書き出しました", "Partida exportada a %1",
        "Sauvegarde exportée vers %1", "Save exportado para %1", "Spielstand nach %1 exportiert",
    ),
    "save_imported": ("Save imported; the previous one was backed up", "세이브를 불러왔습니다. 이전 세이브는 백업했습니다", "セーブを読み込みました。以前のセーブはバックアップ済みです", "Partida importada; la anterior se respaldó",
        "Sauvegarde importée ; la précédente a été sauvegardée", "Save importado; o anterior foi salvo em backup", "Spielstand importiert; der vorherige wurde gesichert",
    ),
    "save_restored": ("Import undone; the previous save is back", "불러오기를 되돌려 이전 세이브로 복구했습니다", "読み込みを元に戻し、以前のセーブを復元しました", "Importación deshecha; se restauró la partida anterior",
        "Import annulé ; la sauvegarde précédente est restaurée", "Importação desfeita; o save anterior voltou", "Import rückgängig gemacht; der vorherige Spielstand ist zurück",
    ),
    # Notifications the daemon sends back after a shop action. Built here for
    # the same reason the transfer ones are: the daemon used to answer a
    # purchase with an English literal, which is the one toast a Korean UI
    # could still surface in the wrong language.
    "shop_bought": ("Bought %1", "%1 구매 완료", "%1 を購入しました", "Compraste %1",
        "%1 acheté", "%1 comprado", "%1 gekauft",
    ),
    "shop_used": ("Used %1", "%1 사용 완료", "%1 を使いました", "Usaste %1",
        "%1 utilisé", "%1 usado", "%1 benutzt",
    ),
    "shop_used_body": ("%1 gained.", "%1 획득했어요.", "%1 を獲得しました。", "Ganó %1.",
        "%1 gagnés.", "%1 ganho.", "%1 erhalten.",
    ),
    "shop_nature_now": ("Nature is now %1", "성격이 %1{d} 바뀌었어요", "性格が %1 になりました",
        "Su naturaleza ahora es %1",
        "Sa nature est maintenant %1", "A natureza agora é %1", "Das Wesen ist jetzt %1",
    ),
    # Pinning a species to the panel, and letting it go again.
    "pinned": ("PINNED", "고정됨", "固定中", "FIJADO",
        "ÉPINGLÉ", "FIXADO", "ANGEHEFTET",
    ),
    "pinned_to_panel": ("On the panel", "패널에 고정됨", "パネルに固定中",
        "Fijado en el panel",
        "Épinglé au panneau", "Fixado no painel", "An der Leiste",
    ),
    "unpin": ("Release", "고정 해제", "解除", "Soltar",
        "Détacher", "Soltar", "Lösen",
    ),
    "panel_pinned": ("%1 is pinned to the panel", "패널을 %1{d} 고정했어요",
        "パネルを %1 に固定しました", "%1 está fijado en el panel",
        "%1 est épinglé au panneau", "%1 está fixado no painel",
        "%1 ist an der Leiste angeheftet",
    ),
    "panel_unpinned": ("The panel follows your companion again",
        "패널이 다시 파트너를 따라가요", "パネルが再びパートナーを表示します",
        "El panel vuelve a seguir a tu compañero",
        "Le panneau suit de nouveau votre compagnon",
        "O painel volta a seguir seu companheiro",
        "Die Leiste folgt wieder deinem Begleiter",
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
}

_INDEX = {code: i for i, code in enumerate(LANGUAGES)}

# Nature names, in the same language order as STRINGS. The official
# main-series names, except Portuguese: there is no Portuguese release, so
# upstream chose its own 25 distinct names, matching the feminine "natureza".
# Kept out of STRINGS so the catalogue shipped in state.json stays the UI's
# own words; the daemon resolves these where it builds the payload.
NATURE_NAMES: dict[str, tuple[str, ...]] = {
    "hardy": ("Hardy", "노력", "がんばりや", "Fuerte", "Hardi", "Esforçada", "Robust"),
    "lonely": ("Lonely", "외로움", "さみしがり", "Huraña", "Solo", "Carente", "Solo"),
    "brave": ("Brave", "용감", "ゆうかん", "Audaz", "Brave", "Corajosa", "Mutig"),
    "adamant": ("Adamant", "고집", "いじっぱり", "Firme", "Rigide", "Teimosa", "Hart"),
    "naughty": ("Naughty", "개구쟁이", "やんちゃ", "Pícara", "Mauvais", "Levada", "Frech"),
    "bold": ("Bold", "대담", "ずぶとい", "Osada", "Assuré", "Ousada", "Kühn"),
    "docile": ("Docile", "온순", "すなお", "Dócil", "Docile", "Dócil", "Sanft"),
    "relaxed": ("Relaxed", "무사태평", "のんき", "Plácida", "Relax", "Descontraída", "Locker"),
    "impish": ("Impish", "장난꾸러기", "わんぱく", "Agitada", "Malin", "Travessa", "Pfiffig"),
    "lax": ("Lax", "촐랑", "のうてんき", "Floja", "Lâche", "Despreocupada", "Lasch"),
    "timid": ("Timid", "겁쟁이", "おくびょう", "Miedosa", "Timide", "Medrosa", "Scheu"),
    "hasty": ("Hasty", "성급", "せっかち", "Activa", "Pressé", "Apressada", "Hastig"),
    "serious": ("Serious", "성실", "まじめ", "Seria", "Sérieux", "Séria", "Ernst"),
    "jolly": ("Jolly", "명랑", "ようき", "Alegre", "Jovial", "Alegre", "Froh"),
    "naive": ("Naive", "천진난만", "むじゃき", "Ingenua", "Naïf", "Ingênua", "Naiv"),
    "modest": ("Modest", "조심", "ひかえめ", "Modesta", "Modeste", "Modesta", "Mäßig"),
    "mild": ("Mild", "의젓", "おっとり", "Afable", "Doux", "Meiga", "Mild"),
    "quiet": ("Quiet", "냉정", "れいせい", "Mansa", "Discret", "Discreta", "Ruhig"),
    "bashful": ("Bashful", "수줍음", "てれや", "Tímida", "Pudique", "Tímida", "Zaghaft"),
    "rash": ("Rash", "덜렁", "うっかりや", "Alocada", "Foufou", "Impulsiva", "Hitzig"),
    "calm": ("Calm", "차분", "おだやか", "Serena", "Calme", "Calma", "Still"),
    "gentle": ("Gentle", "얌전", "おとなしい", "Amable", "Gentil", "Gentil", "Zart"),
    "sassy": ("Sassy", "건방", "なまいき", "Grosera", "Malpoli", "Atrevida", "Forsch"),
    "careful": ("Careful", "신중", "しんちょう", "Cauta", "Prudent", "Cautelosa", "Sacht"),
    "quirky": ("Quirky", "변덕", "きまぐれ", "Rara", "Bizarre", "Excêntrica", "Kauzig"),
}

# PokéAPI language codes to try for each UI language, most preferred first.
# Japanese names are kana under ja-Hrkt; Brazilian Portuguese is pt-BR.
API_CODES: dict[str, tuple[str, ...]] = {
    "ja": ("ja-hrkt", "ja"),
    "pt": ("pt-br", "pt"),
}


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


# Korean particles, chosen from the word they follow. A name that arrives at
# runtime cannot be baked into the translation, which is why the Korean copy
# used to write both forms ("%1이(가)"). Ports upstream's KoreanParticle
# (746d838); the arithmetic is a few lines, so no dependency is needed.
#
# In a string, `%1{s}` means "substitute %1, then the subject particle that fits
# it": 이/가 for {s}, 을/를 for {o}, 으로/로 for {d}.
_PARTICLES = {
    "s": ("가", "이", "이(가)"),
    "o": ("를", "을", "을(를)"),
    "d": ("로", "으로", "(으)로"),
}
_HANGUL = range(0xAC00, 0xD7A4)
_RIEUL = 8
_PARTICLE_MARKER = re.compile(r"%(\d)\{([sod])\}")


def korean_particle(word: str, kind: str) -> str:
    """The particle that fits this word, or both forms when it cannot be told.

    The coda of the last syllable decides it. A word that does not end in a
    Hangul syllable — a file path, a dex number placeholder, Unown's "[A]" —
    keeps the combined form: writing both is better than writing the wrong one.
    """
    no_coda, with_coda, either = _PARTICLES[kind]
    if not word or ord(word[-1]) not in _HANGUL:
        return either
    coda = (ord(word[-1]) - 0xAC00) % 28
    if coda == 0:
        return no_coda
    # ㄹ takes 로, not 으로 (서울로, 알로).
    if kind == "d" and coda == _RIEUL:
        return no_coda
    return with_coda


def fill(key: str, language: str = "en", *values: str) -> str:
    """Resolve a string and substitute %1, %2 … , Korean particles included.

    Every substitution of a runtime name goes through here rather than through
    `t(...).replace("%1", name)`, because that is the call that knows the word
    the particle has to agree with.
    """
    text = t(key, language)

    def particle(match: re.Match) -> str:
        index = int(match.group(1)) - 1
        word = values[index] if 0 <= index < len(values) else ""
        return f"%{match.group(1)}{korean_particle(word, match.group(2))}"

    text = _PARTICLE_MARKER.sub(particle, text)
    for position, value in enumerate(values, start=1):
        text = text.replace(f"%{position}", value)
    return text


def nature_name(nature: str | None, language: str = "en") -> str:
    """A nature's name in the UI language. An unknown slug is shown as is."""
    if not nature:
        return ""
    row = NATURE_NAMES.get(nature)
    if row is None:
        return nature
    index = _INDEX.get(language, 0)
    return row[index] if index < len(row) and row[index] else row[0]


def _api_code(raw: str) -> str:
    return (raw or "").strip().lower().replace("_", "-")


def api_codes(language: str) -> tuple[str, ...]:
    return API_CODES.get(language, (_api_code(language),))


def resolve_name(names: dict[str, str], language: str) -> str | None:
    """Pick one PokéAPI name for the UI language, falling back to English.

    Ports upstream's PokemonNameLocalization.resolve (2fab082). Codes are
    compared case-insensitively: PokéAPI writes ja-Hrkt and pt-BR, and exact
    matching is how Portuguese kept falling back to English.
    """
    normalized: dict[str, str] = {}
    for key in sorted(names):
        value = (names[key] or "").strip()
        if value:
            normalized[_api_code(key)] = value
    for code in (*api_codes(language), "en"):
        if code in normalized:
            return normalized[code]
    return None


def names_from_api(entries) -> dict[str, str]:
    """{language code: name} from a PokéAPI `names` array."""
    out: dict[str, str] = {}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        code = _api_code(((entry.get("language") or {}).get("name")) or "")
        name = (entry.get("name") or "").strip()
        if code and name:
            out[code] = name
    return out


# Short weekday names, Monday first, per language, and how each language writes
# a month, day and weekday together. Upstream asks the OS locale for this
# ("MdE"); the daemon has no locale data to ask, so the seven are written out.
_WEEKDAYS = {
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
    "ko": ("월", "화", "수", "목", "금", "토", "일"),
    "ja": ("月", "火", "水", "木", "金", "土", "日"),
    "es": ("lun", "mar", "mié", "jue", "vie", "sáb", "dom"),
    "fr": ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."),
    "pt": ("seg", "ter", "qua", "qui", "sex", "sáb", "dom"),
    "de": ("Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So."),
}
_DAY_STAMP = {
    "en": "{w}, {m}/{d}",
    "ko": "{m}. {d}. ({w})",
    "ja": "{m}/{d}({w})",
    "es": "{w}, {d}/{m}",
    "fr": "{w} {d:02d}/{m:02d}",
    "pt": "{w}, {d:02d}/{m:02d}",
    "de": "{w}, {d}.{m}.",
}


def day_stamp(day: str, language: str = "en") -> str:
    """"Wed, 9/17" for a yyyy-mm-dd day, in the language's own order."""
    from datetime import date as _date

    try:
        parsed = _date.fromisoformat(day)
    except ValueError:
        return day
    code = language if language in _WEEKDAYS else "en"
    return _DAY_STAMP[code].format(
        w=_WEEKDAYS[code][parsed.weekday()], m=parsed.month, d=parsed.day)


def catalogue(language: str = "en") -> dict[str, str]:
    """Every string resolved for one language, for shipping in state.json."""
    return {key: t(key, language) for key in STRINGS}
