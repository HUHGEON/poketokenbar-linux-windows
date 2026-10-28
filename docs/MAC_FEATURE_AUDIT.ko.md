# macOS 기능 비교 및 반영 결과 — 2026-10-28

## 비교 기준

GitHub에서 최신 안정 릴리스 [v2.5.6](https://github.com/chattymin/PokeTokenBar/releases/tag/v2.5.6)과 main [`32ebe4c`](https://github.com/chattymin/PokeTokenBar/tree/32ebe4cac2aca1d298d71e7cbc70a507015470f9)를 다시 확인했다. main은 2026-10-27 점검 이후 바뀌지 않았다. 아래는 현재 **Windows Qt 앱과 공통 Python 코어**의 반영 결과다. 기능 이름뿐 아니라 macOS의 상세 화면·개체 규칙·API 정규화·최근 커밋과 실제 구현을 비교했다.

## 현재 반영 상태

| 영역 | 반영 결과 |
| --- | --- |
| 타입 | 한국어 타입 배지, 복합 타입, macOS와 같은 18개 색상 |
| 개체 | 레벨·성별·성격·선택된 특성·숨겨진 특성·개체 선택 |
| 능력치 | 6개 개체값, 레벨·성격을 반영한 능력치 수치와 그래프 |
| 기술 | 현재 배운 기술 최대 4개와 습득 레벨, 전체 기술 목록과 습득 방법 |
| 기술 기준 | macOS와 같은 `black-2-white-2`; 이전 `black-white` 캐시는 필요할 때 갱신 |
| 종 정보 | 가능한 특성 전체, 키(m)·몸무게(kg)·종족값 합계 |
| 개체 없는 수집 단계 | 기본 종족값·종 정보·전체 기술을 표시 |
| 상세 로딩 | 상세 진입 시 요청, 실패 안내·재시도, 오프라인 이전 캐시 및 재요청 간격 |
| 상세 언어 | 언어를 바꾸면 다른 언어의 상세 캐시를 노출하지 않고 재요청 |
| 폼 | 1–5세대 23종 폼의 수집·진화·저장·대표 선택; 기본형 전투 데이터 정책 안내 |
| 도감 탐색 | 검색·희귀도/이로치 필터·정렬, 4×4 페이지, 휠 넘김, 상세에서 뒤로가면 목록 위치 복귀 |
| 상세 바로가기 | 홈·진화 라인·포획 로그·도감 이미지; 홈은 현재 개체를 선택 |
| 상점·가방 | 사탕·민트·이로치 부적·등급별 알, 소모품 일괄 구매/사용, 사탕 성장 미리보기 |
| 사용량 | 14개 도구, 모델별 사용량/비용, 일별 도구별 누적 막대, 주·월·연 돌아보기 |
| 돌아보기 접근성 | 홈에 한국어 텍스트 버튼; 오늘 사용량이 없어도 주·월 이력이 있으면 접근 가능 |
| 트레이 메뉴 | 오늘 요약, 새로고침, 도감·설정 바로가기, 펫 표시/숨김 및 기존 저장/종료 작업 |
| 플로팅 펫 | 대표 포켓몬·애니메이션 품질·드래그·툴팁·열기/숨기기 우클릭 메뉴 |
| 한도 말풍선 | 데몬의 실제 경고/임박 임계값 이벤트를 한 번씩 표시; 오래된 이벤트·알림 끄기 반영 |
| 저장 | 내보내기/가져오기, 자동/수동 스냅샷, 복원·손상 복구 |
| Claude 로그 | 추가된 부분만 읽는 영구 오프셋 캐시; 부분 쓰기 재읽기, 재작성/축소 시 전체 재해석, 누적 비용 재분배 |
| Cursor 인증 | 사용량과 한도 요청이 갱신 JWT/회전 refresh token을 메모리에서 공유. 로그인/루트 변경을 검증하고 IDE SQLite는 수정하지 않음 |

최근 main의 [추가 커밋](https://github.com/chattymin/PokeTokenBar/compare/d82867bb0659604c3737a74b36bc9dcac7db1ac5...32ebe4cac2aca1d298d71e7cbc70a507015470f9) 중 Cursor 인증 공유, Claude 증분 읽기, 홈 돌아보기 버튼 표시는 이 포트에 반영했다. macOS의 OCR CI 픽스처는 macOS 테스트 전용이므로 복사하지 않는다.

## 기존 데이터와 한국어

기존 개체의 레벨·개체값·식별자·진행도는 유지한다. 배운 기술은 새 기준 게임의 레벨업 기술로 갱신한다. 새 UI 문구는 한국어 중심으로 추가했고 다른 기존 UI 언어에서는 영어로 대체한다. 기술·특성 고유 이름은 PokéAPI 번역 캐시와 영어 대체 정책을 사용한다.

실제 설치본에서 꼬렛의 전체 기술 **61개와 한국어 이름 61개**, 가능한 특성 및 상세 UI를 확인했다. Windows Qt 렌더링 검사와 공개 API 확인을 구분하며, offscreen 렌더링을 사용자의 실제 데스크톱 캡처로 표현하지 않는다.

## 플랫폼별 범위

Windows에 대응되는 macOS의 주요 사용자 기능과 최근 공통 코어 개선을 반영했다. macOS의 AppKit/SwiftUI 창 수명, Keychain, 메뉴바 크기, Apple Silicon/Intel 배포물 등은 해당 플랫폼 전용이다. Windows는 기존 트레이·PowerShell 설치·알림 방식으로 제공한다.

GNOME 확장에는 타입·폼·기술·종 정보·수집/상점 제어를 연결했지만, 별도의 돌아보기/차트 화면과 로컬 스냅샷 관리 화면은 Windows Qt/macOS와 범위가 다르다. 이번 푸시는 현재 사용 중인 **Windows 브랜치**를 대상으로 하며 전체 GNOME UI까지 동일하다고 주장하지 않는다.

macOS에도 기술을 수동으로 바꾸거나 기술로 싸우는 배틀 화면은 없다. 전체 기술은 지정 게임 버전에 속한 목록이다. 다른 폼의 타입·능력치·특성·기술은 macOS와 같이 기본형 기준이다. 난수 구현은 플랫폼마다 다르므로 같은 seed의 결과가 완전히 같다고 보장하지 않는다.

## 검증

전체 Python 회귀 검사, 네이티브 Windows Qt 검사, JavaScript 동작/문법 검사와 컴파일 검사를 수행한다. 새 검사는 Claude의 부분 쓰기·재작성·축소·재시작·누적 비용, Cursor의 인증 공유·회전 토큰·계정 격리·로그아웃, 펫 말풍선·메뉴와 트레이/돌아보기 접근을 포함한다. 인증 검사는 합성 SQLite와 주입한 네트워크 응답만 사용한다.

최종 결과: 전체 Python **1,242 통과 / 14 건너뜀**, Windows Qt **92 통과**,
JavaScript 동작 **19 통과**. 마지막 파일 잠금 복구 수정 후 관련 코어 **102 통과**.
컴파일과 `git diff --check`도 통과했다.

## 핵심 소스

- macOS [상세 UI](https://github.com/chattymin/PokeTokenBar/blob/32ebe4cac2aca1d298d71e7cbc70a507015470f9/Sources/PokeTokenBar/UI/CompanionView.swift#L1570)
- macOS [개체·기술·능력치 규칙](https://github.com/chattymin/PokeTokenBar/blob/32ebe4cac2aca1d298d71e7cbc70a507015470f9/Sources/PokeTokenBar/Core/PokemonProfile.swift)
- macOS [펫](https://github.com/chattymin/PokeTokenBar/blob/32ebe4cac2aca1d298d71e7cbc70a507015470f9/Sources/PokeTokenBar/UI/FloatingPetPanel.swift)
- macOS [최근 개선 비교](https://github.com/chattymin/PokeTokenBar/compare/d82867bb0659604c3737a74b36bc9dcac7db1ac5...32ebe4cac2aca1d298d71e7cbc70a507015470f9)
