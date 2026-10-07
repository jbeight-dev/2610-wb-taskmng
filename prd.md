# PRD — Jira Epic 기반 담당자별 일감 현황

- 작성일: 2026-10-07
- 버전: 1.1 — Python + Streamlit 로컬 실행
- 대상: 사내 Jira를 사용하는 개발 리더 및 일감 운영 담당자
- 산출물: 사용자 컴퓨터에서 실행하는 Streamlit 단일 페이지 대시보드
- 실행 환경: 사내망 또는 VPN에 연결된 Windows / macOS 컴퓨터
- 기술 스택: Python 3.11 이상, Streamlit, requests, pandas
- 문서 상태: 구현 준비용 초안. 아래 기본 정책을 적용하고, 사내 Jira 버전·인증·이슈 구조 확인 후 확정한다.

## 1. 목적

로컬 앱에 설정한 개인 Jira 인증 계정이 담당자로 지정된 Epic의 하위 Task를 조회하여, 진행 중인 일감과 완료된 일감을 구분하고 각 담당자가 어떤 업무를 수행하는지 한 페이지에서 파악한다.

Epic 담당자와 하위 Task 담당자는 서로 다를 수 있다. 조회 대상은 **내가 담당자인 Epic**으로 정하고, 해당 Epic의 하위 Task는 **담당자와 무관하게 조회**한다.

## 2. 배경 및 확인된 사항

- 사내 Jira REST API를 활용한다.
- 사용자가 `/rest/api/2/myself`에서 본인 정보를 조회할 수 있다고 확인했다.
- 이 확인만으로 Python 연동용 인증이 확보되었다고 판단하지 않는다. 브라우저 로그인 쿠키로 조회되었을 가능성이 있으므로 실제 호출 방식 확인이 필요하다.
- Jira 설치 버전, 프로젝트 키, Epic과 Task 연결 필드, 사용자별 API 인증 방식은 아직 확인되지 않았다.
- 문서의 `https://jira.company.com`은 설명용 주소이며 실제 배포 설정으로 대체한다.

## 3. 사용자 문제와 목표

| 현재 문제 | 제공할 기능 |
|---|---|
| 여러 Epic을 열어 하위 Task를 반복 확인해야 한다 | 내가 담당인 Epic의 하위 Task를 통합 조회 |
| 담당자별로 업무가 흩어져 있다 | 담당자별 일감 그룹과 상태별 건수 표시 |
| 진행 중과 완료를 빠르게 비교하기 어렵다 | 진행 중·완료 분류와 상태 필터 제공 |
| 대기 상태를 진행 중으로 오해할 수 있다 | 대기 상태를 별도로 표시 |
| 특정 일감 상세를 확인해야 한다 | Jira 원본 일감으로 연결 |

성공 기준은 Jira에서 확인한 대상 일감과 대시보드의 조회 범위·상태·담당자가 일치하고, 첫 화면에서 담당자별 진행 중 업무를 확인할 수 있는 것이다.

## 4. MVP 범위

### 4.1 포함

1. 설정된 개인 인증 정보로 `/myself`를 호출하여 Jira 계정 확인.
2. 현재 사용자가 담당자인 Epic 전체 조회.
3. 조회한 Epic에 직접 연결된 Task 전체 조회.
4. Task를 진행 중·완료·대기로 분류.
5. 담당자별 요약 및 일감 목록 표시.
6. Epic·담당자·상태 필터 및 수동 새로고침.
7. Jira 원본 일감 링크, 마지막 조회 완료 시각 표시.
8. 담당자 미지정, 빈 결과, 인증 실패, 부분 조회 실패 처리.

### 4.2 제외

- Jira 일감 생성·수정·상태 변경·담당자 변경.
- 내가 담당자가 아닌 Epic을 임의로 포함하는 기능.
- 직접 하위 Task의 Sub-task를 재귀적으로 조회하는 기능.
- Story·Bug 등 Task 이외 유형의 포함. 이후 요구 시 별도 확장한다.
- 스프린트 관리, 일정 계획, 알림, AI 요약, 실적 평가.
- 처리 이력 저장 및 과거 시점의 추세 분석.
- 별도 React 프런트엔드, Spring Boot/FastAPI 서버, 데이터베이스.
- 다중 사용자 서비스, 별도 앱 로그인, 사내 서버 또는 외부 호스팅 배포.

## 5. 조회 및 분류 정책

### 5.1 Epic 선정

- 현재 사용자의 Jira 계정을 기준으로 담당자를 판별한다.
- Epic 유형의 실제 ID를 확인해 설정한다. 화면 표시명이 반드시 `Epic`이라고 가정하지 않는다.
- 기본적으로 현재 사용자 담당 Epic을 상태와 관계없이 조회한다. 완료된 Epic의 하위 완료 Task도 확인할 수 있어야 한다.
- 기본 날짜 제한은 없다. 완료 목록은 현재 상태가 완료인 Task이며, 이번 주 완료 실적을 의미하지 않는다.
- 프로젝트 제한은 기본적으로 적용하지 않는다. 운영 범위가 확정되면 로컬 설정에서 프로젝트 키를 제한할 수 있다.
- 조회 결과는 설정된 개인 인증 계정이 Jira에서 볼 수 있는 범위에 한정한다.

### 5.2 하위 Task 선정

- 선정한 Epic에 실제 Epic 하위 관계로 직접 연결된 Task만 포함한다.
- 일반적인 이슈 링크인 `relates to`, `blocks`는 하위 관계로 해석하지 않는다.
- Task 유형은 사내 Jira의 실제 유형 ID를 설정으로 관리한다.
- Epic 담당자가 나이고 Task 담당자가 다른 사람이어도 포함한다.
- Task 담당자가 나여도 상위 Epic 담당자가 다른 사람이면 제외한다.
- Epic 자체는 Task 건수와 완료율 계산에서 제외한다.
- 동일 Task가 중복 반환되면 Jira issue ID 기준으로 한 번만 집계한다.
- Sub-task는 기본적으로 제외하므로 부모 Task와 이중 집계하지 않는다.

### 5.3 상태 분류

상태 이름의 문자열 비교 대신 Jira 응답의 `fields.status.statusCategory.key`를 사용한다. 사내 워크플로에 대한 실제 응답을 확인한 후 적용한다.

| Jira 상태 카테고리 키 | 화면 분류 | 의미 |
|---|---|---|
| `indeterminate` | 진행 중 | 업무 수행 중인 상태 |
| `done` | 완료 | Jira 워크플로에서 완료 범주인 상태 |
| `new` | 대기 | 아직 시작하지 않은 상태 |
| 누락 또는 미지원 값 | 분류 확인 필요 | 임의로 진행 중·완료에 포함하지 않음 |

- 기본 화면 상태 필터는 `진행 중`이다.
- `완료`, `대기`, `전체` 필터를 제공한다.
- 미완료 전체를 진행 중으로 부르지 않는다. 미완료는 진행 중과 대기의 합이다.
- 취소·반려 등이 `done`에 속하면 완료 범주에 포함하고 원본 상태명을 함께 표시한다. 정상 완료만의 지표는 MVP에 포함하지 않는다.
- 분류 확인 필요 항목은 전체 보기에서 표시하고 별도 건수로 안내한다.

### 5.4 담당자 기준

- 그룹 식별자는 Jira 사용자 고유 식별자를 사용하고 화면에는 표시명을 사용한다.
- 설치 버전에 맞는 `key` 등 식별자를 확인한다. 표시명만으로 그룹을 합치지 않는다.
- 담당자가 없으면 `미지정` 그룹으로 표시한다.
- 조회 대상 Task에 등장하는 담당자를 표시한다. 일감이 없는 팀원을 임의로 추가하지 않는다.
- 완료 Task도 현재 담당자 기준으로 집계한다. 실제 완료 수행자나 상태 변경 수행자를 추정하지 않는다.

## 6. 사용자 흐름

1. 사용자가 가상환경과 로컬 설정을 준비하고 Streamlit을 실행한다.
2. 브라우저에서 로컬 페이지를 열면 Python 앱이 `/myself`로 설정된 개인 Jira 인증 계정을 확인한다.
3. 사용자가 담당자인 Epic을 조회한다.
4. 각 Epic의 직접 하위 Task를 조회한다.
5. Python 앱이 상태를 분류하고 pandas로 담당자별 집계를 수행한다.
6. 화면에 전체 요약과 담당자별 진행 중 목록을 표시한다.
7. 사용자가 완료·대기·전체로 전환하거나 특정 Epic·담당자를 선택한다.
8. 상세 확인이 필요하면 표의 Jira 링크를 눌러 Jira 원본을 연다.
9. 새로고침을 누르면 최신 Jira 상태로 다시 조회한다.

## 7. 단일 페이지 화면 요구사항

### 7.1 상단

- 페이지명: `내 Epic 일감 현황`
- 조회 기준 사용자 표시.
- 마지막 조회 완료 시각 표시.
- `새로고침` 버튼 제공. 요청 중에는 중복 클릭을 막고 조회 중 상태를 표시한다.
- 부분 조회 실패 시 상단 경고 영역 표시.

### 7.2 요약 영역

| 항목 | 집계 기준 |
|---|---|
| 대상 Epic | Epic 필터 적용 후의 Epic 수 |
| 전체 Task | Epic·담당자 필터 적용 후의 고유 Task 수 |
| 진행 중 | 같은 범위에서 진행 중 Task 수 |
| 완료 | 같은 범위에서 완료 Task 수 |
| 대기 | 같은 범위에서 대기 Task 수 |

요약은 Epic·담당자 필터를 반영하되 상태 필터의 영향을 받지 않는다. 진행 중 화면에서도 완료와 대기 건수를 비교할 수 있어야 한다. 분류 확인 필요 항목이 있으면 추가 건수를 표시한다.

### 7.3 필터 영역

- Epic: 전체 또는 특정 Epic 한 개. 선택 목록에 키와 제목을 함께 표시한다.
- 담당자: 전체 또는 특정 담당자 한 명. 미지정도 선택 가능하다.
- 상태: 진행 중 / 완료 / 대기 / 전체.
- 초기값: Epic 전체, 담당자 전체, 진행 중.
- 필터 변경은 이미 조회한 데이터를 기준으로 즉시 반영한다.
- 새로고침 후에도 유효한 선택은 유지한다. 선택 대상이 사라지면 전체로 전환하고 안내한다.

### 7.4 담당자별 업무 영역

각 담당자 그룹은 다음을 표시한다.

- 담당자명.
- 전체·진행 중·완료·대기 건수. Epic 필터는 반영하고 상태 필터와 무관하게 표시한다.
- 현재 상태 필터에 해당하는 일감 표.

| 일감 표 컬럼 | 표시 내용 |
|---|---|
| 일감 | Task 키와 제목, Jira 상세 링크 |
| Epic | 상위 Epic 키와 제목 |
| 상태 | 분류와 Jira 원본 상태명 |
| 우선순위 | Jira 우선순위명, 없으면 `—` |
| 기한 | Jira 기한, 없으면 `—` |
| 최근 변경 | Jira 수정 시각 |

- 진행 중 필터에서 해당 일감이 없는 담당자는 목록에서 숨긴다.
- 담당자 정렬: 진행 중 건수 내림차순, 동률이면 표시명 오름차순. 미지정은 마지막에 표시한다.
- 그룹 내 일감은 최근 변경 시각 내림차순, 동률이면 일감 키 순으로 표시한다.
- 대량 목록은 `st.dataframe`의 스크롤 가능한 표로 표시하되 집계는 전체 조회 결과 기준으로 수행한다.
- 담당자 그룹은 세로 배치한다. 좁은 화면에서는 필터가 겹치지 않아야 하며 표의 가로 스크롤을 허용한다.
- 표에는 클릭 가능한 Jira 링크 컬럼을 제공한다. 제목을 링크로 만드는 것은 필수가 아니다.

## 8. 집계 규칙

```text
전체 Task = 진행 중 + 완료 + 대기 + 분류 확인 필요
담당자별 Task 수의 합 = 전체 Task 수
```

- 상태 필터는 표시 목록만 제한한다.
- Epic·담당자 필터는 목록과 요약의 집계 범위를 제한한다.
- 빈 Epic도 Epic 선택 목록에는 남긴다.
- 부분 조회 결과는 성공적으로 가져온 일감만 집계하며 `일부 조회 결과`로 명시한다. 실패한 Epic의 건수를 0건으로 확정하지 않는다.
- 페이지네이션이 끝나기 전의 결과를 전체 건수로 표시하지 않는다.

## 9. Jira 연동 설계

### 9.1 로컬 실행 구성

브라우저는 로컬 Streamlit 화면에 접속하고, Jira REST API 호출은 같은 컴퓨터의 Python 프로세스가 수행한다. 브라우저에서 Jira를 직접 호출하지 않는다.

| 구성 요소 | 기술 | 역할 |
|---|---|---|
| 실행 환경 | Python 3.11 이상 + venv | 프로젝트별 의존성 관리 |
| UI | Streamlit | 요약, 필터, 담당자별 표, 조회 상태 |
| HTTP | requests | 인증, Jira API 호출, 타임아웃 처리 |
| 데이터 처리 | pandas + Python | 정규화, 필터, 담당자·상태 집계 |
| 설정 | 환경변수 또는 `.streamlit/secrets.toml` | Jira URL, PAT, 이슈 유형 ID |
| 세션 | `st.session_state` | 조회 결과와 필터 선택 유지 |
| 테스트 | pytest | 조회·분류·페이지네이션 핵심 동작 검증 |

- 사용자 개인 PAT를 기본 인증 방식으로 검토하고 사내 Jira 지원 여부를 확인한다.
- 앱의 '나'는 `/myself`로 확인한 인증 계정이다. OS 사용자나 브라우저 SSO 사용자를 자동으로 추정하지 않는다.
- 개인 인증 계정으로 조회하므로 JQL의 `currentUser()`를 사용한다. 서비스 계정 기반 사용자 대리 조회는 MVP에서 제외한다.
- Streamlit은 `127.0.0.1`에 바인딩하여 내 컴퓨터에서 접속한다.
- 사내망/VPN, DNS, 프록시, 사내 인증서 신뢰 설정이 Python 프로세스에서도 동작해야 한다.
- TLS 인증서 검증을 유지하고 사내 CA가 필요하면 CA 파일 경로를 설정한다.
- 별도 REST 서버와 업무 데이터베이스는 두지 않는다.

### 9.2 Epic 조회 예시

```http
POST /rest/api/2/search
Content-Type: application/json
```

```json
{
  "jql": "issuetype = 10000 AND assignee = currentUser() ORDER BY updated DESC",
  "startAt": 0,
  "maxResults": 100,
  "fields": ["summary", "assignee", "status", "updated"]
}
```

`10000`은 예시 유형 ID이며 실제 Epic 유형 ID로 대체한다. `currentUser()`는 로컬 앱에 설정된 Jira 개인 인증 계정을 의미한다. 설정값은 검증하고 화면에서 임의 JQL을 입력하는 기능은 제공하지 않는다.

### 9.3 하위 Task 조회

설치형 Jira Software의 Epic 하위 조회 API를 우선 검증한다.

```http
GET /rest/agile/1.0/epic/{epicIdOrKey}/issue
```

- `startAt`, `maxResults`, `fields`를 지정하고 모든 페이지를 조회한다.
- API가 지원하는 JQL 필터 또는 Python 모듈의 유형 검사로 실제 Task 유형만 선정한다.
- 필요한 필드: `summary`, `issuetype`, `status`, `assignee`, `priority`, `duedate`, `updated`.
- Epic 호출 단위로 상위 Epic 관계를 응답에 부여한다.
- 해당 API가 제공되지 않으면 사내 Jira의 Epic Link 필드 또는 실제 지원되는 parent 관계를 확인해 검색 API로 대체한다.
- Epic Link의 사용자 정의 필드 ID는 고정값을 가정하지 않는다. `/rest/api/2/field`와 실제 Task 응답으로 확인한다.
- Jira Cloud 예시의 parent 검색을 설치형 Jira에 검증 없이 적용하지 않는다.

### 9.4 페이지네이션 및 호출 관리

- Epic 목록과 각 Epic 하위 목록 모두 전체 페이지를 조회한다.
- 다음 시작 위치는 실제 반환된 항목 수만큼 증가시킨다.
- 응답의 전체 건수와 빈 페이지를 함께 확인하고 무한 반복을 방지한다.
- 서버가 요청한 페이지 크기보다 적게 반환해도 목록 누락이 없어야 한다.
- MVP는 Epic별 순차 호출을 기본으로 한다. 성능 측정에서 필요하면 최대 3개 동시 호출로 확장하고 각 작업의 HTTP 세션을 분리한다.
- 기본 읽기 타임아웃은 10초, 전체 수집 제한은 60초를 시작값으로 두고 사내 측정 후 확정한다.
- 네트워크 오류·429·일시적 5xx는 제한된 재시도를 적용한다. 429 응답의 Retry-After가 있으면 준수한다.
- 400·401·403은 무조건 반복 요청하지 않는다.

## 10. Python 모듈 및 내부 데이터 계약

### 10.1 프로젝트 구조

```text
jira-epic-dashboard/
  app.py
  jira_client.py
  dashboard_service.py
  models.py
  settings.py
  requirements.txt
  README.md
  prd.md
  .gitignore
  .streamlit/
    config.toml
    secrets.toml.example
  tests/
    test_dashboard_service.py
    test_jira_client.py
```

실제 `.streamlit/secrets.toml`은 사용자가 로컬에 생성하고 Git에서 제외한다. 이 구조는 향후 구현할 프로젝트의 제안이며 본 PRD 작성 단계에서 코드가 생성되었다는 의미는 아니다.

| 모듈 | 책임 |
|---|---|
| `app.py` | Streamlit 화면, 필터, 새로고침, 오류 및 결과 표시 |
| `settings.py` | 설정 로드·검증. 동일 키는 환경변수 우선, 없으면 secrets 사용 |
| `jira_client.py` | `/myself`, Epic·하위 Task 조회, 페이지네이션, HTTP 오류 처리 |
| `dashboard_service.py` | 조회 조합, Task 유형 선정, 정규화, 집계·필터 |
| `models.py` | 사용자·Epic·Task·조회 결과·경고 데이터 모델 |

### 10.2 Streamlit 실행 및 재실행 정책

- 최초 접속 시 설정을 검증하고 Jira 전체 조회를 1회 수행한다.
- 결과는 `st.session_state`에 저장한다. 필터 변경에 따른 스크립트 재실행은 기존 결과만 다시 집계하고 Jira를 재조회하지 않는다.
- 수동 새로고침은 필터 선택을 유지하며 Jira를 재조회한다.
- 조회 중에는 `st.spinner` 또는 `st.status`로 진행 상황을 표시한다.
- 재실행 과정에서 최초 조회가 실패한 경우에도 무한 자동 요청을 하지 않는다. 다시 조회 버튼으로 재시도한다.
- MVP는 인증 결과와 Jira 데이터에 전역 `st.cache_data` 또는 `st.cache_resource`를 사용하지 않는다.
- 브라우저 새 세션·앱 재시작 시 다시 조회한다. 디스크에 Jira 결과를 저장하지 않는다.
- 새로고침 성공 시 일관된 결과 묶음으로 교체한다. 실패 시 이전 결과와 이전 조회 시각을 유지한다.
- 일부 Epic 실패 결과는 불완전 상태로 제공하고 수집 중인 중간 건수를 최종 통계로 표시하지 않는다.

### 10.3 화면 구성 매핑

| 화면 요소 | Streamlit 구성 |
|---|---|
| 제목·조회 사용자·시각 | `st.title`, `st.caption` |
| 요약 건수 | `st.columns`, `st.metric` |
| Epic·담당자 필터 | `st.selectbox` |
| 상태 필터 | `st.radio` |
| 새로고침 | `st.button` |
| 담당자별 영역 | `st.subheader`, 필요 시 `st.expander` |
| 일감 목록 | `st.dataframe`, `st.column_config.LinkColumn` |
| 오류·경고·빈 결과 | `st.error`, `st.warning`, `st.info` |

### 10.4 내부 조회 결과

`load_dashboard(settings)`가 반환하는 Python 데이터 모델은 아래 구조를 따른다. JSON은 데이터 구조 설명용이며 외부 HTTP API를 제공한다는 뜻이 아니다.

내부 데이터 예시:


```json
{
  "viewer": { "jiraUserId": "user-key-1", "displayName": "조회 사용자" },
  "fetchedAt": "2026-10-07T10:24:00Z",
  "isPartial": false,
  "epics": [
    { "id": "10001", "key": "DP-100", "summary": "카탈로그 개선" }
  ],
  "issues": [
    {
      "id": "10002",
      "key": "DP-101",
      "summary": "권한 등록 UX 개선",
      "epicKey": "DP-100",
      "assignee": { "id": "user-key-2", "displayName": "담당자 A" },
      "statusName": "개발 중",
      "statusCategoryKey": "indeterminate",
      "category": "IN_PROGRESS",
      "priority": "High",
      "dueDate": null,
      "updatedAt": "2026-10-07T09:00:00Z",
      "url": "https://jira.company.com/browse/DP-101"
    }
  ],
  "summary": {
    "epicCount": 1,
    "taskCount": 1,
    "inProgressCount": 1,
    "doneCount": 0,
    "todoCount": 0,
    "unknownCount": 0
  },
  "warnings": []
}
```

- `category`: `IN_PROGRESS`, `DONE`, `TODO`, `UNKNOWN`.
- 담당자 미지정은 `assignee: null`로 반환한다.
- `summary`는 필터 적용 전의 전체 응답 기준이다. Streamlit 앱은 Epic·담당자 선택 시 같은 규칙으로 다시 계산한다.
- `warnings`는 실패 Epic 키, 오류 종류와 사용자 안내를 포함하며 토큰이나 내부 응답 원문은 포함하지 않는다.
- 새로고침 실패 시 기존 성공 결과를 유지하고 이전 조회 시각과 실패 안내를 표시한다.

## 11. 상태 및 오류 처리

| 상황 | 화면 동작 |
|---|---|
| 최초 조회 중 | 로딩 표시. 임의의 0건 통계를 보여주지 않음 |
| 내 담당 Epic 없음 | `담당자로 지정된 Epic이 없습니다` |
| Epic은 있으나 Task 없음 | `해당 Epic에 조회 가능한 Task가 없습니다` |
| 현재 필터 결과 없음 | `선택한 조건에 해당하는 일감이 없습니다` |
| 담당자 미지정 | 미지정 그룹으로 표시 |
| Jira 401 | 인증 실패 안내 및 인증 재설정 필요 표시 |
| Jira 403 | 조회 권한 또는 API 접근 정책 확인 안내 |
| Epic 404 | 삭제·접근 제한 가능성 안내, 부분 결과로 처리 |
| 일부 Epic 조회 실패 | 성공 결과 표시와 실패 Epic 목록 제공 |
| 페이지 수집 도중 실패 | 해당 Epic 결과를 불완전으로 표시하고 전체 결과임을 주장하지 않음 |
| 전체 조회 실패 | 오류 표시와 다시 조회 버튼 제공 |
| 새로고침 실패 | 기존 결과 유지, 이전 결과임을 표시 |
| 미지원 상태 | 분류 확인 필요 건수와 원본 상태 표시 |

Jira가 권한 때문에 검색 결과에서 숨기는 일감은 검출하거나 누락 건수로 추정하지 않는다. `조회 가능한 일감 기준`임을 화면에 짧게 표시한다.

## 12. 비기능 요구사항

- Jira 원본을 읽기 전용으로 사용한다.
- 설정된 개인 Jira 계정을 `/myself`로 확인하고 화면에 표시한다.
- 개인 컴퓨터의 단일 사용자 앱으로 운영하며 외부 접속을 열지 않는다.
- 토큰은 환경변수 또는 로컬 secrets 파일로 관리하고 로그·브라우저 저장소·화면 데이터에 포함하지 않는다.
- 인증 설정을 변경하면 앱을 재시작하고 이전 세션 결과를 재사용하지 않는다.
- 제목·표시명 등 Jira 문자열은 일반 텍스트로 렌더링하고 임의 HTML 실행을 허용하지 않는다.
- Jira 링크는 설정된 Jira 기준 URL과 검증된 일감 키로 구성한다.
- 날짜·시각은 Asia/Seoul 기준으로 표시하고 내부 데이터 시각은 ISO 8601로 관리한다. 기한은 날짜 값 그대로 표시한다.
- 상태는 색뿐 아니라 텍스트로 구별한다.
- 키보드로 필터, 새로고침, 일감 링크를 사용할 수 있어야 한다.
- 개발자 약 5명 규모를 기본 사용 시나리오로 한다.
- 성능 검증 기준 데이터: Epic 20개, Task 1,000개. 초기 조회 10초 이내를 목표로 하되 Jira 응답 시간을 포함해 사내에서 측정한다.
- 조회 지연·실패율·조회 Epic 및 Task 건수를 로컬 로그로 확인할 수 있어야 한다.

## 13. 수용 기준

| ID | 시나리오 | 기대 결과 |
|---|---|---|
| AC-01 | 내가 담당인 Epic 2개, 다른 사람이 담당인 Epic 1개 존재 | 내 담당 Epic 2개만 포함 |
| AC-02 | 내 Epic의 Task 담당자가 A·B·미지정으로 나뉨 | 모두 조회되고 담당자별 그룹으로 표시 |
| AC-03 | 다른 담당자의 Epic 하위 Task를 내가 담당 | 조회 대상에서 제외 |
| AC-04 | Task 카테고리가 진행 중 3·완료 2·대기 1 | 전체 6건, 각 상태 건수 일치 |
| AC-05 | 서로 다른 상태명이 같은 진행 중 카테고리에 속함 | 모두 진행 중으로 분류하고 원본 상태명 표시 |
| AC-06 | Epic 선택 후 담당자 A와 완료 필터 적용 | 선택 Epic·A 담당·완료 Task만 목록 표시, 요약은 해당 Epic·A의 모든 상태 기준 |
| AC-07 | 일감이 여러 API 페이지에 걸쳐 반환됨 | 모든 페이지 수집 후 집계, 누락·중복 없음 |
| AC-08 | 동일 표시명을 가진 사용자 2명 존재 | 고유 식별자로 별도 그룹 유지 |
| AC-09 | 완료된 Epic 하위에 완료 Task 존재 | 날짜 제한 없이 조회 대상에 포함 |
| AC-10 | Task 아래 Sub-task가 존재 | 부모 Task만 포함하고 Sub-task 제외 |
| AC-11 | 내 Epic에 Story·Bug와 Task가 혼재 | 설정한 Task 유형만 포함 |
| AC-12 | 일부 Epic 호출 실패 | 부분 결과임을 표시하고 실패 Epic 안내 |
| AC-13 | 브라우저 /myself는 성공하나 Python 인증은 실패 | 정상 데이터로 위장하지 않고 인증 오류 표시 |
| AC-14 | 개인 PAT로 앱 실행 | `/myself`의 계정이 화면에 표시되고 해당 계정 담당 Epic만 조회 |
| AC-15 | 새로고침 후 담당자·상태가 변경됨 | 목록과 집계가 현재 Jira 값으로 함께 갱신 |
| AC-16 | 필터만 변경하여 Streamlit 재실행 | Jira 호출 없이 기존 결과를 다시 집계 |
| AC-17 | 상태 카테고리가 없거나 알 수 없음 | 분류 확인 필요로 표시, 전체 집계 일치 |
| AC-18 | 표의 Jira 링크 선택 | 사내 Jira 상세 페이지로 이동 |
| AC-19 | 새로고침 선택 | Jira API 재호출 후 데이터와 조회 시각 갱신 |
| AC-20 | 인증 설정 누락 | 누락 항목을 안내하고 Jira 요청을 실행하지 않음 |
| AC-21 | 로컬 실행 명령 수행 | 127.0.0.1:8501에서 단일 페이지 접속 가능 |

## 14. 구현 순서

1. 사내 Jira 버전·인증·Epic 및 Task 유형 ID·Epic 연결 방식 확인.
2. 실제 사용자 인증으로 Epic과 하위 Task 조회를 검증.
3. Python Jira 클라이언트, 페이지네이션, 상태 정규화 및 집계 모듈 구현.
4. Streamlit 단일 페이지의 요약, 필터, 담당자별 목록과 세션 상태 구현.
5. 실제 Jira 결과와 대조하고 수용 기준 및 대량·오류 시나리오 검증.

## 15. 구현 전 확인 항목

| 항목 | 현재 상태 | 확인 방법 |
|---|---|---|
| Jira 종류와 버전 | 미확인 | 관리자 또는 serverInfo 응답으로 확인 |
| 실제 기준 URL과 context path | 미확인 | `/myself` 호출 주소 확인 |
| `/myself` 인증 방식 | 미확인 | 브라우저 쿠키·PAT·기타 방식 구분 |
| Python 연동 인증 | 미확인 | 개인 컴퓨터의 requests로 `/myself` 호출 검증 |
| Epic·Task 유형 ID | 미확인 | Jira 유형 목록 및 실제 일감 응답 확인 |
| Epic 하위 조회 API | 미확인 | 실제 Epic으로 Agile API 호출 검증 |
| Epic Link 또는 parent 관계 | 미확인 | field 목록과 실제 Task 응답 확인 |
| 상태 카테고리 매핑 | 미확인 | 사내 상태별 응답 샘플 확인 |
| 개인 인증 계정 | 미확인 | `/myself` 응답의 계정이 실제 본인인지 확인 |
| 사내망·프록시·CA | 미확인 | Python 프로세스의 DNS·HTTPS 연결 검증 |
| Sub-task·Story·Bug 포함 필요 | 기본 제외 | 실제 사용 중인 업무 유형 확인 후 범위 변경 여부 결정 |

## 16. 공식 참고 문서

다음 문서는 API 설계 참고용이다. 실제 설치 버전에 맞는 API 지원 여부를 검증해야 한다.

- [Jira Data Center — Search REST API](https://developer.atlassian.com/server/jira/platform/rest/v11002/api-group-search)
- [Jira Data Center — Epic REST API](https://developer.atlassian.com/server/jira/platform/rest/v11002/api-group-epic/)
- [Jira REST API 검색 예제](https://developer.atlassian.com/server/jira/platform/jira-rest-api-examples/)
- [Personal Access Token 사용](https://confluence.atlassian.com/enterprise/using-personal-access-tokens-1026032365.html)


## 17. 로컬 설정 및 실행 요구사항

### 17.1 설정 항목

| 설정 | 필수 여부 | 내용 |
|---|---|---|
| `JIRA_BASE_URL` | 필수 | 실제 Jira URL. context path 포함 |
| `JIRA_PAT` | PAT 방식일 때 필수 | 본인 계정의 개인 액세스 토큰 |
| `JIRA_EPIC_TYPE_ID` | 필수 | 실제 Epic 이슈 유형 ID |
| `JIRA_TASK_TYPE_IDS` | 필수 | 포함할 Task 유형 ID. 복수일 때 쉼표 구분 |
| `JIRA_PROJECT_KEYS` | 선택 | 제한할 프로젝트 키. 없으면 전체 |
| `JIRA_CA_BUNDLE` | 선택 | 사내 CA 인증서 파일 경로 |
| `JIRA_CONNECT_TIMEOUT_SECONDS` | 선택 | 기본 5초 |
| `JIRA_READ_TIMEOUT_SECONDS` | 선택 | 기본 10초 |
| `JIRA_COLLECTION_TIMEOUT_SECONDS` | 선택 | 기본 60초, 전체 수집 예산 |

requests의 연결·읽기 타임아웃만으로 전체 수집 제한이 구현되었다고 판단하지 않는다. 페이지·재시도 사이에 남은 전체 예산을 확인하고 초과하면 불완전 결과 또는 실패로 처리한다. PAT 미지원 환경은 실제 지원 인증을 확인한 뒤 Jira 클라이언트에 반영한다.

설정 예시 — `.streamlit/secrets.toml`:

```toml
JIRA_BASE_URL = "https://jira.company.com"
JIRA_PAT = "REPLACE_WITH_YOUR_PAT"
JIRA_EPIC_TYPE_ID = "REPLACE_WITH_EPIC_TYPE_ID"
JIRA_TASK_TYPE_IDS = "REPLACE_WITH_TASK_TYPE_ID"
```

설정 검증 시 샘플 문자열을 실제 값으로 받아들이지 않는다. secrets 파일은 암호화 저장소가 아니므로 로컬 파일 접근 권한으로 보호한다. `.gitignore`에는 실제 secrets 파일과 `.venv/`를 포함한다.

### 17.2 의존성

- 실행 의존성: `streamlit`, `requests`, `pandas`.
- 개발·테스트 의존성: `pytest`.
- 실제 구현 시 설치·검증한 버전을 고정한다. PRD에서는 최신 버전 번호를 추정하지 않는다.
- 환경변수 또는 Streamlit secrets를 사용하므로 `.env` 파일이나 python-dotenv는 필수가 아니다.

### 17.3 실행 예시

Windows PowerShell에서 가상환경 활성화 없이 실행하는 예시:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

macOS / Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

접속 주소: `http://127.0.0.1:8501`. 종료는 실행한 터미널에서 Ctrl+C를 사용한다. 위 명령은 향후 구현 코드가 준비되었을 때의 실행 방법이다.

### 17.4 검증 범위

- 모의 Jira 응답으로 상태 분류, Task 유형 필터, 담당자 미지정·동명 사용자, 중복 제거, 페이지네이션, 부분 실패를 테스트한다.
- 실제 사내 Jira에서 `/myself`와 Epic 1개를 기준으로 결과를 대조한다.
- Streamlit 필터 변경 때 Jira 호출이 증가하지 않고 새로고침 때만 재조회되는지 확인한다.
- 자동 테스트에서 실제 PAT나 Jira 개인정보를 fixture에 저장하지 않는다.
- 데모 데이터는 별도 명시한 경우에만 사용하며 실제 인증 실패를 데모 결과로 감추지 않는다.

## 18. Streamlit 공식 참고 문서

- [Session State](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state)
- [로컬 secrets.toml 설정](https://docs.streamlit.io/develop/api-reference/connections/secrets.toml)
- [서버 설정](https://docs.streamlit.io/develop/api-reference/configuration/config.toml)
- [표 컬럼 설정](https://docs.streamlit.io/develop/api-reference/data/st.column_config)
