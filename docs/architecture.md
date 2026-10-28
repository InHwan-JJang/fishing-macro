# 구조와 유지보수

## 파일 역할

| 파일 | 역할 |
|---|---|
| `fishing_macro.py` | Win32 입력/포커스/클립보드, 명령 반복, 메인 UI, 예약, 설정·기록 저장, PC 종료 |
| `fishing_history.py` | 결과 텍스트 해석, 세션 기록, 새 메시지 추적, 통계 집계, 한국 시간 |
| `history_window.py` | 히스토리 Treeview, 정렬·필터, 과거 기록 표시 |
| `history_view.py` | 표시 행 생성, 대표값 선택, 숫자·등급 기반 단일 열 정렬 |
| `test_history_view.py` | 행운 마지막 횟수·사용자 분리·표시·정렬·Tkinter 열 테스트 |
| `test_fishing.py` | 파싱·중복 방지·미끼 수량·예약·종료 조건·복사 회귀 테스트 |
| `build.bat` | 가상환경과 PyInstaller를 이용한 Windows EXE 빌드 |
| `make_icon.py` | Pillow로 아이콘 생성 |

런타임은 Python 표준 라이브러리와 Windows DLL을 사용합니다. 빌드에는 PyInstaller,
아이콘 재생성에는 Pillow가 필요합니다. 서버나 OCR을 사용하지 않습니다.

## 실행 흐름

```text
App (Tkinter 메인 스레드, 50ms 폴링)
 ├─ GlobalHotkeys 스레드 → Queue → F9 처리
 ├─ 예약 / 저장 / 종료 타이머
 └─ MacroJob 작업 스레드
     ├─ 시작 시 대화 baseline 수집
     ├─ 낚시 명령 전송
     ├─ copy_chat → 기존 횟수/한도 파서
     │            → Observer → History → HistoryWindow
     ├─ 자동어 수동 해제 / 미끼 사용
     └─ 한도·지정 횟수·사용자 정지·창 닫힘에 따른 종료
```

History는 잠금으로 갱신과 snapshot을 보호합니다. UI는 snapshot으로 기록을 읽고
version 변경을 기준으로 약 1초마다 히스토리 화면을 갱신합니다.
저장은 History.update마다 history_storage.save_csv로 임시 CSV를 쓴 후 fsync와 os.replace로 교체합니다. 실패는 메모리에 유지하고 타이머에서 재시도합니다.

## 대화 파싱

복사 메시지 헤더는 `[발신자] [오전/오후 H:MM] 본문`입니다.
다음 헤더 전까지의 줄을 같은 본문으로 합칩니다.
명령의 멘션 대상은 봇 이름이며 봇 답장의 대상 멘션은 복사 시 `@사용자`로 표시됩니다.

Observer는 명령을 FIFO로 보관하고 봇 응답과 순서대로 연결합니다.
응답별 컨텍스트를 유지하여 낚시 결과 본문과 해당 어종 카드를 같은 이벤트 ID로 갱신합니다.
두 응답 헤더가 먼저 도착해도 기존 응답을 잃지 않으며, 카드 종류(물고기/진주/레이드/가방)가
같은 미완료 응답에 순서대로 연결합니다. 다른 사람의 컨텍스트도 카드 연결이 끝날 때까지 유지합니다.
같은 종류의 카드 자체가 역순으로 도착하거나 명령·카드가 누락되는 경우까지 확정적으로 식별할 수는 없습니다.
반복 복사된 메시지는 prefix/overlap 비교로 제외하고, 마지막 메시지의 추가 본문은 기존 기록에 반영합니다.
겹치는 메시지를 찾을 수 없는 대화 변경은 과거 기록 중복 수집을 피하기 위해 재기준화합니다.
초기 복사 실패 시 첫 성공 복사를 baseline으로 사용하므로 그 사이 결과는 기록에서 빠질 수 있습니다.

기존 `my_replies`, `classify_reply`, `limit_hit` 기반 제어 로직도 유지됩니다.
추가 Observer의 오늘 횟수·한도도 실행 상태에 반영하며 대어·진주·레이드 응답을 분류합니다.

## 기록 형식

필드는 응답에서 확인된 경우에만 존재할 수 있습니다.

| 필드 | 의미 |
|---|---|
| `id`, `user`, `time` | 세션 이벤트 ID, 사용자, 관측 시각(한국 시간 ISO 8601) |
| `kind` | `fish`, `auto`, `pearl`, `raid` |
| `species`, `size`, `grade` | 어종, cm 크기, 등급 |
| `today`, `limit` | 오늘 순번과 한도 |
| `gold`, `multiplier`, `balance` | 획득 골드, 판매 배율 %, 보유 골드 |
| `exp`, `pearls` | 획득 경험치, 진주 증가량 |
| `damage`, `stones`, `bonus` | 레이드 피해, 해신석, 달성 보상 골드 |
| `collection` | 도감 완성 확인 여부 |
| `luck_remaining`, `lucky` | 메시지의 잔여 행운, 적용 판정 |

`time`은 채팅에 적힌 시각을 복원한 값이 아니라 프로그램이 관측한 시각입니다.
크기 원문은 `cm`와 `m`를 지원하고 `size`는 cm로 통일합니다(어비스 37.4m → 3740cm).
진주·해신석은 보유 총량이 아니라 증가량을 사용합니다.
레이드 상단 보상과 하단 카드에 같은 보상이 반복돼도 동일 필드를 갱신하므로 두 번 더하지 않습니다.

## 클립보드 복사: 회귀 방지 핵심

현재 순서는 다음과 같습니다.

1. 기존 텍스트 클립보드와 시퀀스 번호 저장
2. 대화 목록으로 포커스 이동
3. Ctrl+A → Ctrl+C
4. **입력창 포커스 복원**
5. 변경된 시퀀스에서 텍스트가 준비될 때까지 최대 약 3초 확인
6. 기존 텍스트 클립보드 복원

실제 낚시방에서 4번을 5번 뒤로 미루면 대기 중 복사가 완료되지 않고,
포커스 복원 직후에야 클립보드가 바뀌는 현상을 재현했습니다.
단순히 대기 시간을 늘리거나 작업 스레드 메시지를 펌핑하는 것만으로는 해결되지 않았습니다.
최종 버전은 입력창 복원을 먼저 수행하고 대기 중 작업 스레드 메시지 펌핑도 유지합니다.
시퀀스가 바뀌어도 텍스트가 아직 없으면 즉시 실패하지 않고 재확인합니다.

기존 클립보드 보존 범위는 텍스트뿐입니다. 이미지·파일 형식 보존 기능을 추가하지 않았습니다.

## 빌드와 검증

Windows PowerShell에서 프로젝트 루트 기준:

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_fishing test_history_view
.\build.bat nopause
```

`build.bat`는 일반 Python을 찾아 `.venv`를 생성하고 PyInstaller를 설치한 뒤 빌드합니다.
빌드 산출물은 `dist/FishingMacro.exe`이며 루트의 `FishingMacro.exe`로 복사합니다.
실행 중인 같은 이름의 프로세스가 있으면 빌드 스크립트가 중단합니다.

빌드 스크립트와 동일한 패키징 명령:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --noupx --icon fishing.ico --add-data "fishing.ico;." --name FishingMacro fishing_macro.py
```

현재 작업에서 사용한 환경은 Python 3.12.14, PyInstaller 6.22.3입니다.
PyInstaller의 일반적인 Windows 비대상 모듈 경고(`pwd`, `grp`, `posix` 등)와 실제 필수 모듈 누락을 구분합니다.
실행 파일에는 `fishing_history`, `history_window`, `tkinter` 포함을 확인했습니다.
빌드 도구 버전은 저장소에서 고정하지 않았습니다.

## 문제 진단 순서

1. 실행 파일과 소스가 같은 버전인지 확인합니다.
2. 설정 사용자 이름과 복사 대화 발신자 이름을 비교합니다.
3. `diagnostics.log`에서 `focus`, `keys`, `chars`, 클립보드 시퀀스를 확인합니다.
4. 복사는 성공하는데 기록이 없다면 명령·답장·카드 메시지 연결을 확인합니다.
5. 기록 CSV와 화면을 비교하여 수집 문제와 표시 문제를 구분합니다.

자동 실행 설정이 있으므로 EXE 실행 자체가 채팅 명령 전송으로 이어질 수 있습니다.
파서와 UI 테스트는 실제 입력·PC 종료 호출을 모킹하고, 실사용 검증은 명시적으로 범위를 정해 수행합니다.


## 특수 카드와 행운 부여 구분 (2026-10-28 추가)

크기 정규식이 맞지 않아도 `[이름] 속성` 카드 제목을 인식해 응답 연결을 완료합니다.
`9강`은 강화 수치로 기록하고 크기는 생성하지 않습니다. 현재 사용자 정책상 kind는 fish를 유지하여 기존 집계에 포함합니다.
행운 snapshot은 10의 배수이면서 예상 잔여량보다 증가한 문구를 `luck_granted=True`로 표시하고 `lucky=False`로 처리합니다.
이후 감소 및 문구 없는 마지막 소비는 lucky에 포함합니다. 첫 관측이 10의 배수가 아닌 양수이면 소비입니다. 이전 기록 없이 10의 배수부터 관측하면 부여로 간주합니다.

## CSV 저장과 열람 분리

history_storage.py는 CSV 직렬화, CSV/구버전 JSON 타입 검증, 과거 파일 삭제 경로 검증을 담당합니다.
History(path)는 RLock 아래에서 변경 기록을 저장합니다. History.load는 저장 경로 없는 별도 객체를 만듭니다.
App.history는 항상 현재 세션이며 HistoryWindow.history만 열람 대상으로 교체합니다.
불러오기/삭제 중 _dialog_open으로 F9, 자동 시작, 자정 시작과의 경합을 막습니다.
현재 파일 및 history 폴더 밖 파일은 영구 삭제할 수 없습니다.

## 효과 기반 미끼 요청

EFFECTS의 luck/frost/fire별 잔여/부여/소비 상태를 사용자·날짜 단위로 독립 계산합니다.
Observer는 내 응답을 저장한 후 새 부여 판정의 최대 잔여 횟수를 buff_requests에 한 번 넣습니다.
어종명 테이블은 제거했습니다. 행운 보기에는 any_lucky를 사용하며 lucky는 일반 행운만 뜻합니다.
CSV 스키마는 각 효과별 필드를 포함하고 이전 파일의 누락 필드는 그대로 허용합니다.

## 일별 파일 저장 (최신 정책)

App은 DailyHistory를 사용합니다. 실행 파일 옆 fishing-macro-history/YYYY-MM-DD.csv가 정식 파일입니다.
ensure_day가 한국 날짜 변경 시 해당 파일을 로드/생성하고 동일 History 객체의 표시 날짜를 전환합니다.
new_id/update에서도 날짜를 확인하므로 작업 스레드가 UI 타이머보다 먼저 진행해도 올바른 날짜로 기록합니다.
이전 날짜 객체는 메모리에 남아 지연 카드가 도착해도 원래 날짜 파일을 보완합니다.
각 날짜의 변경 기록은 dirty_days에 유지하고 저장 실패 시 재시도합니다.
오늘 일별 파일이 없다면 legacy history CSV를 읽어 해당 날짜 기록을 재번호화하여 저장합니다.
정식 파일이 있으면 원본 세션 파일을 다시 가져오지 않습니다. 잘못된 파일은 오류로 처리하고 덮어쓰지 않습니다.
과거 불러오기는 여전히 별도 열람용 객체를 사용합니다. 앱 종료 버튼은 예약/종료 타이머를 해제하고 close를 호출합니다.

## 강한 입질과 DPI 행 높이

CATCH_MARKERS(낚시 성공/대어 출현/강한 입질)를 두 응답 파서에서 공유합니다.
강한 입질 헤더도 fish 컨텍스트를 생성해야 뒤따르는 에픽 카드가 올바르게 연결됩니다.
HistoryWindow는 전용 History.Treeview 스타일에서 실제 폰트 linespace에 DPI 여백을 더해 행 높이를 설정합니다.
매초 폴링 시 높이를 재확인하여 글꼴 변화에 대응합니다.
_await_reply는 명령 Enter부터 3초 구간 동안 0.7초 후 첫 복사, 이후 0.5초 간격으로 읽으며 복사 비용이 주기에 추가됩니다.

## 구조 기반 포획과 고정 대기 예산

CATCH_MARKERS 목록 제거. parse_details는 포획 카드 또는 today+(gold/exp)로 fish를 판정합니다.
Observer는 종류 미정 낚시 컨텍스트도 카드 종류와 연결할 수 있으며 FIFO 소유자 배정을 유지합니다.
classify_reply는 오늘 횟수 구조나 파싱된 fish/pearl을 사용합니다.
_command는 시작 기준 0.5초/1초 절대 목표 시각으로 입력하여 처리시간을 중복 대기하지 않습니다.
_last_enter는 Enter 키 입력 시작 시각이며 _await_reply의 첫 검사와 만료는 각각 +0.5/+3초입니다.
copy_chat의 선택적 deadline은 클립보드 접근 재시도 및 복사 대기에 전달됩니다.
기존 입력창 포커스를 복사 대기 전에 복원하는 순서는 유지합니다.

## 탭과 누적 수

HistoryWindow의 Notebook은 7개 보기 탭을 제공하고 공통 Treeview를 갱신합니다.
구간별 통계는 동일 HistoryWindow의 mode를 구간별로 전환하여 표시합니다. Notebook의 기존 선택 탭을 다시 클릭해도 mode를 복원합니다.
make_rows는 필터 전에 날짜·사용자·어종별 누적 수를 계산한 복사본을 만듭니다. CSV 원본은 변경하지 않습니다.
어종/구간 합계 행은 실제 그룹 수로 표시하며 모든 기본 정렬은 최신 time/id 순입니다.
도감 탭은 collection 기록만 사용해 이후 일반 포획으로 완성 시각과 크기가 바뀌지 않습니다.
행운 기록에는 소비뿐 아니라 각 효과의 granted도 포함합니다.

## 평균 표시

history_view.average_summaries가 원본 포획 기록을 대상으로 구간/등급/행운 소비 평균을 계산합니다.
COLUMNS에서 average를 제거했고 행별 평균은 더 이상 계산하지 않습니다.
등급 정렬 활성 여부를 HistoryWindow.refresh에서 전달하며 값은 detail 요약에 표시합니다.

기본 sort_column=None 상태의 유효 표시 정렬은 time/내림차순으로 해석하여 시간 ▼를 렌더링합니다.
실제 정렬 데이터는 make_rows의 최신순을 사용하므로 기존 기본 정렬 복귀 동작을 유지합니다.
# 월드 보스 파싱 확장 (1.1.1-dev)

- 사용자 제공 복사 원문 기준으로 `월드 보스 <이름> 조우!`, `즉시 보상: N G`, `N 데미지`, HP 막대/백분율/분수 형식을 인식합니다. 기존 잔향 형식도 유지합니다.
- Observer의 명령 FIFO와 종류별 미완료 응답 연결을 유지하며 월드 보스 카드도 raid 슬롯으로 연결합니다. 헤더/카드 보상은 합산하지 않고 한 기록을 보완합니다.
- CSV 선택 필드: boss_name, raid_type, hp_current, hp_max, hp_percent. 기존 파일에는 없어도 됩니다.
- history_view의 raid_rows/display_raid_row와 HistoryWindow의 열 전환으로 같은 창에서 전용 레이드 표를 표시합니다. 일반 표와 전용 표 전환 시 정렬은 최신 시간순으로 초기화합니다.
- test_world_boss.py: 다른 보스 이름, 친구와의 겹친 응답, 중복 복사, CSV 왕복/구 필드 호환, 잔향, 등급 필터 및 화면 전환 검증.
