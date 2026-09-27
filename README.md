<div align="center">

# PokeTokenBar for GNOME

**당신의 AI 코딩 토큰을 포켓몬으로 — GNOME 패널과 Windows 트레이에서.**

[![GNOME Shell](https://img.shields.io/badge/GNOME%20Shell-45%2B-4a86cf?logo=gnome&logoColor=white)](https://gnome.org)
[![Windows](https://img.shields.io/badge/Windows-10%2B-0078d4?logo=windows&logoColor=white)](#windows)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776ab?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-3fb950)](LICENSE)

**한국어** · [English](README.en.md)

**[chattymin](https://github.com/chattymin) 님의 [PokeTokenBar](https://github.com/chattymin/PokeTokenBar)를 GNOME으로 옮긴 비공식 포트이며,**
**[rubensanchezrivero](https://github.com/rubensanchezrivero) 님의 [poketokenbar-plasma](https://github.com/rubensanchezrivero/poketokenbar-plasma) 데몬 위에 올렸습니다.**

</div>

이미 태우고 있는 AI 코딩 토큰이 GNOME 패널 속에서 자라나는 **포켓몬 companion**이 됩니다.
토큰을 쓰면 알이 부화하고, 실제 진화 계보를 따라 진화하고, 도감에 졸업하고, 다시 새 알이
시작됩니다. companion 아래에는 정확한 사용량 트래커가 있습니다 — 오늘의 사용량과 비용, 공식
5시간·주간 한도를 로컬 로그에서 직접 읽습니다.

> 사용량은 로컬 파일에서 직접 읽습니다(`totalTokens` = input + output + cache, 로컬 날짜).
> 외부 사용량 CLI도, 계정도, 숫자를 위한 네트워크도 필요 없습니다. 비공식·비상업 포켓몬 팬
> 프로젝트입니다 — [라이선스 & 면책](#라이선스--면책) 참고.

## 지금 상태

기능은 다 들어갔고 CI도 초록이지만, **아직 실제 GNOME 데스크탑에서 돌려보지 않았습니다.**

| | |
|---|---|
| 사용량 데몬 (프로바이더 12개) | ✅ 완료 |
| GNOME Shell 확장 | ✅ 작성 완료 |
| Qt 트레이 앱 (Windows·그 외 리눅스) | ✅ 작성 완료 |
| 테스트 | ✅ Python 1108개 + JavaScript 38개, CI 초록 |
| 클린 체크아웃에서 설치 검증 | ✅ CI에서 |
| **실제 Windows에서 데몬 동작 검증** | ✅ **CI의 windows-latest 러너에서** |
| 실제 GNOME 데스크탑에서 검증 | ❌ **아직** |

마지막 줄이 정직한 부분입니다. 확장이 읽는 모든 필드는 실제 데몬 payload와 기계적으로 대조되고,
JavaScript는 푸시마다 파싱되며, 프레임 레이트 계산은 node로 실행해 검증합니다. 그래서 필드 이름이
틀리거나 문법이 깨진 채로 배포될 수는 없습니다. 다만 **액터가 실제로 그려지는지**는 여기서 확인할
방법이 없습니다. GNOME을 쓰신다면 그게 바로 이슈로 남겨주실 만한 내용입니다.

## 지원 도구

원본의 12개 소스를 전부 읽습니다.

| 도구 | 읽는 위치 |
|---|---|
| **Claude Code** | `~/.claude/projects/**.jsonl` |
| **Codex** | `~/.codex/sessions/**.jsonl` |
| **Gemini CLI** | `~/.gemini/tmp/**` |
| **Antigravity** | `~/.gemini/antigravity*/conversations/*.db` |
| **OpenCode** | `~/.local/share/opencode` |
| **Hermes Agent** | `~/.hermes/state.db` |
| **Cursor** | `~/.config/Cursor/User/globalStorage/state.vscdb` |
| **Grok CLI** | `~/.grok/sessions/**/updates.jsonl` |
| **Copilot CLI** | `~/.copilot/session-store.db` |
| **Kiro CLI** | `~/.local/share/kiro-cli`, `~/.kiro/sessions` |
| **Pi Agent** | `~/.pi/agent/sessions` |
| **omp** (oh-my-pi) | `~/.omp/agent/sessions` |

Claude 계정은 공식 5시간·주간 한도까지 읽습니다.

12개 중 10개는 macOS와 완전히 같은 dotfile 경로를 씁니다. 나머지 둘 — **Cursor**와 **Kiro**의
SQLite 저장소 — 만 위치가 실제로 다르고, 그 리눅스 경로는 원본 테스트가 아니라 플랫폼 관례를
따랐습니다. 둘 중 하나가 사용량을 못 잡으면 `CURSOR_DATA_DIR`·`KIRO_CLI_HOME`으로 덮어쓸 수
있고, 실제로 파일이 어디 있었는지 알려주시면 반영하겠습니다.

## 기능

- 🥚 **평소처럼 코딩하세요.** 12개 도구에서 태우는 토큰이 알을 품습니다.
- 🐣 **부화.** [PokéAPI](https://pokeapi.co/)의 1~5세대 진화 계보에서 공식 capture rate 가중으로
  태어납니다. 25종 성격 중 하나가 정해지고, 아주 드물게 **✨ 이로치**가 나옵니다.
- ⚡ **진화 → 🎓 졸업.** 실제 진화 트리를 따라 자라고, 최종 진화 후 **도감**에 영구 보존됩니다.
- 📈 **개체마다 다른 능력치.** 부화할 때 개체값(IV)이 정해지고, 성별·특성·레벨(5→100)·배운 기술이
  따라옵니다. 도감에서 포켓몬을 누르면 실제 능력치, 종 정보, 전체 기술 목록이 담긴 상세 페이지가
  열립니다.
- 🔁 **다시 만난 계열은 2× 성장.** 한 번 졸업시킨 계열이 다시 부화하면 두 배 빨리 자랍니다.
- 🍬 **한도를 채우면 이상한 사탕.** **가방**에서 써서 지금 포켓몬을 키웁니다. 한 번에 여러 개를
  쓸 수 있고, 쓰기 전에 진화·졸업 여부와 남는 경험치를 미리 보여줍니다. 졸업에 필요한 것보다
  많이 쓰이지 않으니 남은 사탕은 가방에 그대로 있습니다. 한도 창이 리셋되면 다시 받을 수 있습니다.
- 🛒 **상점.** 쓴 토큰이 곧 재화 — 이상한 사탕, 민트, 이로치 부적, 3등급의 알. 소모품은 수량을
  정해 한 번에 살 수 있고, 구매 전에 합계 가격을 보여줍니다. 알을 사서 떠나보낸 포켓몬도 도감에
  「놓아줌」으로 남고 같은 확률로 다시 만날 수 있습니다 — 사라지는 건 키운 진행도뿐입니다.
  이로치나 전설을 놓아주는 알은 한 번 더 확인합니다. 알 단계에서는 알을 살 수 없습니다.
- 🎛 **난이도.** 성장 속도와 상점 가격을 각각 10%~200%로 조절합니다. 바꿔도 지금까지 쌓인 진행
  비율은 그대로 유지됩니다.
- 📌 **대표 포켓몬.** 도감 상세 페이지의 **패널에 고정** 버튼으로 그 종을 패널과 데스크탑 펫에
  고정합니다. 진화하거나 졸업해도 고정은 그대로입니다 — 사용자가 고른 종이니까요. 고정된 칸에는
  「고정됨」 배지가 붙고, 상세 페이지나 Home의 **고정 해제** 버튼으로 풉니다. Home은 고정과 무관하게
  계속 키우는 개체를 보여줍니다.
- 🐾 **데스크탑 펫.** 창 위에 떠 있고, 드래그로 옮기고, 호버하면 오늘 사용량이 뜹니다. 384px까지.
- 📊 **공식 한도.** 5시간·주간 사용률, 리셋 카운트다운과 실제 리셋 시각, 소진 예측. 막대에는
  창을 균등하게 썼다면 지금쯤 와 있을 위치를 눈금으로 표시하고, 그보다 얼마나 앞서는지에 따라
  막대·퍼센트·패널 숫자를 6단계로 물들입니다 — 같은 71%도 창 초반이면 빠른 것이고 끝 무렵이면
  느린 것이니까요. 갱신이 실패해 이전 값을 보여주는 중이면 「갱신 지연」으로 표시하고, 네트워크가
  다시 연결되면 바로 갱신합니다.
- 💵 **비용.** 도구가 스스로 기록해 둔 비용을 가장 먼저 씁니다 — Claude Code는 세션 파일에 모델별
  실제 비용을 남기므로, 단가표에 없는 모델이나 1M 컨텍스트 변형까지 정확히 계산됩니다. 그런 기록이
  없으면 모델 단가표로 추정하고, 단가표에 없는 모델을 비슷한 모델 값으로 짐작하지는 않으므로
  아무것도 계산할 수 없는 날만 「계산 불가」로 표시됩니다.
- 📅 **이번 달 일별 추이.** 1일부터 오늘까지 하루 한 막대, 최다 사용일과 호버한 날의 사용량.
- 🧮 **모델별 내역.** 세션 로그 하나에 모델이 여럿이면 실제 답한 모델 기준으로 나눠 보여줍니다.
- 📁 **추가 스캔 폴더.** 기본 경로 밖의 로그를 프로바이더별로 지정.
- 🎚 **애니메이션 품질.** 끄기 / 절약 / 기본 / 부드럽게. 프레임 하나가 재합성 비용이라 실제
  전력 설정입니다. **끄기**는 첫 프레임에서 멈춰 타이머를 아예 걸지 않습니다. 시스템이 절전
  프로파일이면 절약 이하로 자동 제한됩니다.
- 🌐 **7개 언어.** 한국어·영어·일본어·스페인어·프랑스어·포르투갈어·독일어. 포켓몬 이름까지.

## 구조

```
                         ┌──→  state.json      ──→  GNOME Shell 확장
poketokend (Python)  ────┤                          Qt 트레이 앱 (Windows·기타 리눅스)
                         └←──  커맨드 스풀 디렉터리 ←──  Plasma 위젯
```

D-Bus가 아니라 그냥 파일입니다. 데몬은 UI를 전혀 모릅니다 — 애초에 두 번째 프론트엔드가
가능했던 이유이고, 세 번째가 쉬웠던 이유입니다. 실제 경로는 플랫폼을 따릅니다
(리눅스는 XDG, Windows는 `%APPDATA%`, macOS는 Application Support).

## 설치

### Linux (GNOME)

준비물: GNOME Shell 45+, Python 3.12+, 알림용 `libnotify`(선택), 파싱 가속용
`python-orjson`(선택).

```bash
git clone https://github.com/HUHGEON/poketokenbar-gnome.git
cd poketokenbar-gnome
./install.sh
systemctl --user enable --now poketokend
```

그다음 확장을 켭니다.

```bash
gnome-extensions enable poketokenbar@huhgeon.github.io
```

**셸을 다시 띄워야 목록에 나타납니다.** Xorg는 `Alt`+`F2` → `r`, Wayland는 로그아웃 후
다시 로그인. 확장을 켜는 것 자체가 실행이고, 별도로 띄우는 프로그램은 없습니다 — 다만
숫자를 만드는 건 데몬이라 `poketokend`가 돌고 있어야 합니다.

### Linux (그 외 데스크탑)

XFCE·Cinnamon·타일링 컴포지터 등 확장할 패널도 plasmoid도 없는 환경에서는, Windows와
같은 Qt 트레이 앱이 유일하게 동작하는 선택지입니다. `install.sh`가 데스크탑을 못 알아보면
자동으로 이것을 깝니다.

```bash
POKETOKENBAR_UI=qt ./install.sh
```

### Windows

준비물: Windows 10+, Python 3.12+.

```powershell
git clone https://github.com/HUHGEON/poketokenbar-gnome.git
cd poketokenbar-gnome
powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1
```

패널이 없으니 알림 영역(트레이)에 포켓몬이 삽니다. 클릭하면 같은 탭들이 열리고, 데몬과
트레이 앱 둘 다 로그인 시 자동 시작합니다. 전부 사용자 프로필 안에만 설치되고 관리자
권한이 필요 없습니다.

| | 위치 |
|---|---|
| 설정·상태·세이브 | `%APPDATA%\poketokenbar\` |
| 캐시 | `%LOCALAPPDATA%\poketokenbar\` |
| 프로그램 | `%LOCALAPPDATA%\PokeTokenBar\` |

제거는 `packaging\windows\uninstall.ps1` — 세이브는 일부러 남겨둡니다.

## Plasma 포트와 달라진 점

Plasma 포트를 포크해서 세 방향으로 갈라졌습니다.

**프로바이더 10개 추가.** Plasma 포트는 Claude Code와 Codex만 읽습니다 — 작성자가 나머지는
검증할 데이터가 없었기 때문입니다. 그런데 원본 Swift 테스트 스위트가 대부분의 스키마와 샘플
레코드를 들고 있어서, 파서를 테스트 케이스와 함께 옮겼습니다. 그 도구를 쓰지 않아도 검증됩니다.

**공용 코어의 결함 3건 수정.**

- Codex가 주·월 합계를 **0으로 보고**하고 있었습니다. 일별 집계를 복제해 놓고 기간 집계는 아예
  만들지 않아서, Claude만 되고 Codex는 조용히 0이었습니다.
- 토큰 파싱이 `int`만 받아서, 손상된 `1e30`이 클램프가 아니라 **0이 되어 하루치를 지웠습니다.**
- 프로바이더 레지스트리가 캐시 없는 인스턴스를 만들어 두고 아무도 안 썼고, 데몬은 프로바이더
  두 개를 손으로 나열하고 있었습니다.

**Plasma 포트에 없던 기능:** 프로바이더별 추가 스캔 폴더, 모델별 내역, 프랑스어·포르투갈어·독일어,
대표 포켓몬 고정, 애니메이션 품질.

## 개발

```bash
python -m pytest -q      # 네트워크 없음, 12개 도구 하나도 설치 안 해도 됨
node --test tests/js/    # 확장 코드를 실제로 실행하는 테스트
```

테스트가 곧 명세입니다. 파서 규칙이 임의로 보이는 곳은, 그 테스트가 어떤 원본 케이스가 그것을
고정했고 없으면 무엇이 깨지는지 적어두었습니다.

무엇이 검증되고 무엇이 안 되는지는 [docs/TESTING.md](docs/TESTING.md)에 정리했습니다 — 그 검사들이
실제로 잡아낸 결함 목록까지 포함해서, "값을 한다"는 주장이 주장으로 끝나지 않게 했습니다.

## 크레딧

- [chattymin/PokeTokenBar](https://github.com/chattymin/PokeTokenBar) — 원본 macOS 앱이자
  여기 있는 모든 파싱 규칙의 출처.
- [rubensanchezrivero/poketokenbar-plasma](https://github.com/rubensanchezrivero/poketokenbar-plasma)
  — Python 데몬과, 이 포트가 올라탄 UI 비종속 파일 프로토콜.

## 라이선스 & 면책

**MIT** — [LICENSE](LICENSE) 참고. MIT는 이 프로젝트의 **자체 소스 코드에만** 적용되며, 앱을 통해
접근하는 제3자의 상표·아트워크·데이터에 대한 권리는 부여하지 않습니다.

PokeTokenBar for GNOME은 **비공식·비상업 팬 프로젝트**입니다. **Nintendo, Game Freak,
Creatures Inc., The Pokémon Company와 제휴·보증·후원·승인 관계가 없습니다.** "포켓몬(Pokémon)"과
관련 명칭·캐릭터·이미지는 각 권리자의 상표 및 저작물이며, 본 프로젝트는 어떤 포켓몬 지식재산에
대해서도 소유권이나 권리를 주장하지 않습니다.

- **이 저장소와 모든 릴리스에는 포켓몬 에셋이 포함되지 않습니다.** 종 데이터와 스프라이트는 공개
  [PokéAPI](https://pokeapi.co)에서 **런타임에** 받아 사용자 기기에 로컬 캐시되며, PokéAPI를 통해
  제공되는 스프라이트 이미지의 권리는 각 권리자에게 있습니다.
- 본 앱은 **개인적·비상업적 용도로만** 무료 제공됩니다.
- 권리자께서 본 프로젝트에 대해 우려가 있으시면 이슈를 열거나 메인테이너에게 연락 주시면 신속히
  대응하겠습니다.

*본 프로젝트는 어떠한 보증도 없이 "있는 그대로" 제공됩니다. 본 고지는 법률 자문이 아닙니다.*
