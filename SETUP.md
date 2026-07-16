# 설정 가이드 (완전 자동화 · GitHub Actions + GitHub Pages)

이 폴더의 파일들을 그대로 새 GitHub 저장소에 올리면, 매일 평일 오전 10시(KST)에 자동으로
10개 기관 인사/부고를 수집해서 고정된 웹페이지 주소로 확인할 수 있습니다.

## 1. Gemini(구글 AI) API 키 발급

1. https://aistudio.google.com 접속 (개인 구글 계정으로 로그인 — 카카오 계정 말고 개인 계정 추천)
2. 좌측 메뉴에서 "Get API key" 클릭
3. "Create API key" 클릭 → 새 프로젝트 선택 또는 생성
4. 발급된 키를 복사해둡니다 (나중에 GitHub Secret으로 등록)

무료 크레딧으로 충분히 사용 가능하지만, 사용량이 많아지면 비용이 발생할 수 있습니다 (하루 몇백 원 수준).

## 2. GitHub 저장소 생성

1. https://github.com 접속 후 로그인 (계정이 없다면 먼저 가입)
2. 우측 상단 "+" → "New repository" 클릭
3. 저장소 이름 입력 (예: gov-news-crawler), "Public"으로 설정 (Public이어야 무료로 Pages 사용 가능)
4. "Create repository" 클릭

## 3. 파일 업로드

1. 방금 만든 저장소 페이지에서 "Add file" → "Upload files" 클릭
2. 이 폴더 안의 모든 파일과 폴더(.github 폴더 포함, crawler-personnel.py, index.html, .gitignore)를
   통째로 끌어다 놓습니다 (브라우저가 폴더 구조를 그대로 인식합니다)
3. 하단에 커밋 메시지 입력 후 "Commit changes" 클릭

주의: `.github` 폴더처럼 이름이 점(.)으로 시작하는 폴더는 파일 탐색기에서 숨김 처리되어
안 보일 수 있습니다. Mac Finder에서는 `Cmd + Shift + .` 를 누르면 숨김 파일이 보입니다.

## 4. Secret 키 등록

1. 저장소 페이지에서 "Settings" 클릭
2. 좌측 메뉴에서 "Secrets and variables" → "Actions" 클릭
3. "New repository secret" 버튼을 3번 눌러 아래 3개를 각각 등록합니다.

| Name | Value |
|---|---|
| GEMINI_API_KEY | (1단계에서 발급받은 키) |
| NAVER_CLIENT_ID | c5jf3L6Qa4isMlEbyh85 |
| NAVER_CLIENT_SECRET | jp_ntNwaXf |

## 5. GitHub Pages 활성화

1. "Settings" → 좌측 메뉴 "Pages" 클릭
2. "Build and deployment" → Source를 "Deploy from a branch"로 설정
3. Branch를 "main", 폴더를 "/ (root)"로 선택 후 저장
4. 잠시 후 상단에 공개 URL이 표시됩니다 (예: `https://계정명.github.io/gov-news-crawler/`)
   — 이 URL이 고정 주소이며, 앞으로 계속 이 주소로 확인하시면 됩니다.

## 6. 첫 실행 테스트

1. 저장소 페이지에서 "Actions" 탭 클릭
2. 좌측에서 "Daily personnel crawler" 클릭
3. 우측의 "Run workflow" 버튼 클릭 → 다시 "Run workflow" 클릭해서 수동 실행
4. 1~2분 후 초록 체크가 뜨면 성공. 초록 체크가 안 뜨고 빨간 X가 뜨면 로그를 열어서
   에러 메시지를 확인하고 저에게 붙여넣어 주시면 같이 해결해드릴게요.
5. 성공하면 위 4번의 Pages URL에 접속해서 오늘자 결과가 뜨는지 확인합니다.

이후로는 평일 오전 10시(KST)에 자동으로 실행되며, 사람이 따로 할 일은 없습니다.
