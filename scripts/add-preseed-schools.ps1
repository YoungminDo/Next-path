# HELLOMYME Career — PRE_SEED add-on: every 4-year school (Windows PowerShell 5.1+)
#
# One line in PowerShell:
#   irm https://raw.githubusercontent.com/YoungminDo/Next-path/main/scripts/add-preseed-schools.ps1 | iex
#
# What it does: installs uv if missing, downloads the API code, finds the official pre-seed
# workbook (HELLOMYME_PreSeed_Career_Data_v1.3.xlsx) in Downloads/Desktop/Documents, builds the
# v1.4 add-on from it (other 4-year schools, people copied from v1.3 of the same major; simulation
# data, docs/10 §PRE_SEED v1.4), asks for the database connection string (hidden input) and
# imports the add-on next to v1.3. v1.3 is not touched. Re-running it is safe (ALREADY_IMPORTED).
# To take the add-on out again: run the v1.3 import with --retire v1.4 (docs/10 §PRE_SEED v1.4).

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$BaseVersion = "v1.3"          # the official workbook the add-on is built from
$DatasetVersion = "v1.4"       # the add-on (imported beside v1.3; nothing is retired)
$AsOf = "2026-10-07"
$Work = Join-Path $HOME "nextpath-import"
New-Item -ItemType Directory -Force -Path $Work | Out-Null

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User") + ";" +
                (Join-Path $HOME ".local\bin")
}

# 1. uv (Python package manager) ------------------------------------------------------------
Step "uv 확인"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Refresh-Path }
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv 설치 중..."
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    Refresh-Path
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv 를 찾을 수 없습니다. PowerShell 창을 새로 열고 다시 실행해 주세요."
}

# 2. API code -------------------------------------------------------------------------------
Step "코드 다운로드"
$CodeZip = Join-Path $Work "next-path.zip"
$CodeDir = Join-Path $Work "code"
if ($env:NEXTPATH_CODE_DIR) {
    $ApiDir = Join-Path (Join-Path $env:NEXTPATH_CODE_DIR "apps") "api"
} else {
    Invoke-WebRequest "https://github.com/YoungminDo/Next-path/archive/refs/heads/main.zip" -OutFile $CodeZip
    if (Test-Path $CodeDir) { Remove-Item -Recurse -Force $CodeDir }
    Expand-Archive $CodeZip -DestinationPath $CodeDir
    $ApiDir = Join-Path (Join-Path (Get-ChildItem $CodeDir -Directory | Select-Object -First 1).FullName "apps") "api"
}
if (-not (Test-Path (Join-Path $ApiDir "pyproject.toml"))) { throw "API 코드를 찾지 못했습니다: $ApiDir" }

# 3. Pre-seed workbook ----------------------------------------------------------------------
Step "Pre-seed 데이터 찾기"
$Roots = @()
if ($env:PRESEED_PATH) { $Roots += $env:PRESEED_PATH }
$Roots += @((Join-Path $HOME "Downloads"), (Join-Path $HOME "Desktop"), (Join-Path $HOME "Documents"),
            [Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("MyDocuments"))
$Roots = $Roots | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique

$Pattern = "HELLOMYME_PreSeed_Career_Data_$BaseVersion*.xlsx"
$Workbook = $null
foreach ($root in $Roots) {
    if ((Test-Path $root -PathType Leaf) -and $root -like "*.xlsx") { $Workbook = Get-Item $root; break }
    $hit = Get-ChildItem $root -Recurse -Depth 3 -Filter $Pattern -ErrorAction SilentlyContinue |
           Where-Object { $_.Name -notlike '~$*' } |
           Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($hit) { $Workbook = $hit; break }
}
if (-not $Workbook) {
    throw ("Pre-seed 파일을 찾지 못했습니다. $Pattern 을 다운로드 폴더에 두고 다시 실행하세요. " +
           "다른 위치라면: `$env:PRESEED_PATH='C:\경로\파일.xlsx'")
}
# Excel keeps the file locked while it is open; work on a copy.
$WorkbookCopy = Join-Path $Work "preseed.xlsx"
Copy-Item $Workbook.FullName $WorkbookCopy -Force
Write-Host "사용할 파일: $($Workbook.FullName)"

# 4. Database connection string -------------------------------------------------------------
Step "데이터베이스 연결"
if (-not $env:HELLOMYME_DATABASE_URL) {
    Write-Host "Render 의 HELLOMYME_DATABASE_URL 과 같은 값을 붙여넣으세요 (입력은 화면에 표시되지 않습니다)."
    $secure = Read-Host "연결 문자열" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $env:HELLOMYME_DATABASE_URL = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim() }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}
if ($env:HELLOMYME_DATABASE_URL -match "\[YOUR-PASSWORD\]") {
    throw "[YOUR-PASSWORD] 를 실제 비밀번호로 바꿔서 붙여넣어 주세요."
}

# 5. Build the add-on, then import it -------------------------------------------------------
Step "v1.4 만들기 (1~2분) 및 import (3~6분)"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$AddOn = Join-Path $Work "preseed-v1.4.xlsx"
Push-Location $ApiDir
try {
    uv sync --no-dev
    if ($LASTEXITCODE -ne 0) { throw "uv sync 실패" }
    $summary = Join-Path $Work "make-report.json"
    uv run --no-dev hellomyme-make-preseed $WorkbookCopy --out $AddOn --version $DatasetVersion --min 30 --max 45 |
        Out-File -Encoding utf8 $summary
    if ($LASTEXITCODE -ne 0) { throw "v1.4 만들기 실패. $summary 를 확인하세요." }
    $s = Get-Content $summary -Raw -Encoding utf8 | ConvertFrom-Json
    Write-Host ("만든 것: 학교 {0}곳 · 학교×전공 {1}칸 · {2}명" -f $s.schools, $s.cells, $s.persons)
    $report = Join-Path $Work "import-report.json"
    uv run --no-dev hellomyme-import-preseed $AddOn --dataset-version $DatasetVersion --as-of $AsOf |
        Out-File -Encoding utf8 $report
    $code = $LASTEXITCODE
} finally {
    Pop-Location
    Remove-Item Env:\HELLOMYME_DATABASE_URL -ErrorAction SilentlyContinue
}

$r = Get-Content $report -Raw -Encoding utf8 | ConvertFrom-Json
Step "결과"
Write-Host ("상태: " + $r.status)
if ($r.imported) {
    Write-Host ("인원 {0} · 학력 {1} · 경력 이벤트 {2} · 거부 {3}" -f $r.imported.persons,
                $r.imported.education_records, $r.imported.work_events, $r.rejected_total)
}
foreach ($x in @($r.retired)) { if ($x) { Write-Host ("이전 버전 정리: {0} {1} (삭제 {2}명)" -f $x.source_system, $x.status, $x.deleted_persons) } }
if ($r.aggregation) { Write-Host ("경력 이동 집계: " + $r.aggregation.transitions) }
Write-Host "전체 리포트: $report"
if ($code -ne 0) { throw "import 실패 (exit $code). 위 리포트를 확인하세요." }
Write-Host "`n완료. https://nextpath.da-sh.io 에서 확인하세요." -ForegroundColor Green
