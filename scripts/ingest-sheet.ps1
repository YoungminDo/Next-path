# HELLOMYME Career — load the career ingestion workbook (template v2.1) into the deployed database
# (Windows PowerShell 5.1+)
#
# One line in PowerShell:
#   irm https://raw.githubusercontent.com/YoungminDo/Next-path/main/scripts/ingest-sheet.ps1 | iex
#
# What it does: finds the newest HELLOMYME_Career_Ingestion*.xlsx in Downloads/Desktop/Documents,
# asks for the database connection string (hidden input), runs a dry run first and opens the
# report (what would load, what to fix by sheet and row, which names need standardising), and
# only after you type y loads it. Re-running it is safe: unchanged people report "이미 적재됨".
#
# Options (set before running):
#   $env:INGEST_PATH = 'C:\경로\파일.xlsx'          use this workbook
#   $env:INGEST_ACCEPT_UNREVIEWED = '1'           treat pending/blank review_status as reviewed by you
#   $env:INGEST_LEGAL_BASIS = '...'               basis for people without a 12_CONSENT row

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Work = Join-Path $HOME "nextpath-ingest"
New-Item -ItemType Directory -Force -Path $Work | Out-Null

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User") + ";" +
                (Join-Path $HOME ".local\bin")
}

# 1. uv -------------------------------------------------------------------------------------
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

# 3. Workbook -------------------------------------------------------------------------------
Step "수집 엑셀 찾기"
$Pattern = "HELLOMYME_Career_Ingestion*.xlsx"
$Workbook = $null
if ($env:INGEST_PATH) { $Workbook = Get-Item $env:INGEST_PATH }
if (-not $Workbook) {
    $Roots = @((Join-Path $HOME "Downloads"), (Join-Path $HOME "Desktop"), (Join-Path $HOME "Documents"),
               [Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("MyDocuments")) |
             Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique
    $Workbook = $Roots | ForEach-Object {
        Get-ChildItem $_ -Recurse -Depth 3 -Filter $Pattern -ErrorAction SilentlyContinue } |
        Where-Object { $_.Name -notlike '~$*' -and $_.Name -notmatch '_(미리보기|적재결과)' } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
}
if (-not $Workbook) {
    throw ("수집 엑셀을 찾지 못했습니다. $Pattern 이름으로 다운로드 폴더에 두거나 " +
           "`$env:INGEST_PATH='C:\경로\파일.xlsx' 를 지정하고 다시 실행하세요.")
}
$Stem = [IO.Path]::GetFileNameWithoutExtension($Workbook.Name)
$WorkbookCopy = Join-Path $Work "$Stem.xlsx"   # Excel locks open files; work on a copy
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

# 5. Dry run, then load on confirmation -----------------------------------------------------
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$Basis = if ($env:INGEST_LEGAL_BASIS) { $env:INGEST_LEGAL_BASIS } else { "PENDING_LEGAL_REVIEW (staging test load)" }
$Common = @("--legal-basis", $Basis)
if ($env:INGEST_ACCEPT_UNREVIEWED -eq "1") { $Common += "--accept-unreviewed" }

function Show($label, $json) {
    $r = $json | ConvertFrom-Json
    Write-Host $label -ForegroundColor Yellow
    $r.summary.PSObject.Properties | ForEach-Object { Write-Host ("  {0}: {1}" -f $_.Name, $_.Value) }
    Write-Host ("  리포트: " + $r.report)
    Invoke-Item $r.report
}

Push-Location $ApiDir
try {
    Step "설치 및 DB 스키마 확인 (1~3분)"
    uv sync --no-dev
    if ($LASTEXITCODE -ne 0) { throw "uv sync 실패" }
    uv run --no-dev alembic upgrade head   # same migrations the API runs at start; idempotent
    if ($LASTEXITCODE -ne 0) { throw "DB 스키마 업데이트 실패" }

    Step "미리보기 (저장하지 않음)"
    $preview = uv run --no-dev hellomyme-ingest sheet $WorkbookCopy --dry-run @Common | Out-String
    if ($LASTEXITCODE -ne 0) { throw "미리보기 실패:`n$preview" }
    Show "미리보기 결과" $preview

    $answer = Read-Host "`n리포트를 확인했나요? 이대로 적재할까요? (y/N)"
    if ($answer -notmatch '^(y|yes|ㅛ)$') { Write-Host "적재하지 않았습니다."; return }

    Step "적재"
    $result = uv run --no-dev hellomyme-ingest sheet $WorkbookCopy @Common | Out-String
    if ($LASTEXITCODE -ne 0) { throw "적재 실패:`n$result" }
    Show "적재 결과" $result
} finally {
    Pop-Location
    Remove-Item Env:\HELLOMYME_DATABASE_URL -ErrorAction SilentlyContinue
}
Write-Host ("`n완료. 리포트의 '고칠 것' 시트대로 엑셀을 고쳐 다시 실행하면 검수 대기·거부였던 사람이 " +
            "다시 반영돼요. 이미 적재된 사람은 그대로 둡니다.") -ForegroundColor Green
