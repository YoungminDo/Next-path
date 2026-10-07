# HELLOMYME Career — PRE_SEED import into the deployed database (Windows PowerShell 5.1+)
#
# One line in PowerShell:
#   irm https://raw.githubusercontent.com/YoungminDo/Next-path/main/scripts/import-preseed.ps1 | iex
#
# What it does: installs uv if missing, downloads the API code, finds the pre-seed package in
# Downloads/Desktop/Documents (zip or already extracted, including the nested project package),
# extracts it, asks for the database connection string (hidden input), and runs the idempotent
# importer. Re-running it is safe: an already imported package is reported as ALREADY_IMPORTED.

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$DatasetVersion = "v1.2"
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

# 3. Pre-seed package -----------------------------------------------------------------------
Step "Pre-seed 데이터 찾기"
$Required = @("institutions.csv", "majors.csv", "roles.csv", "organizations.csv", "persons.csv",
              "educations.csv", "work_events.csv", "work_event_sources.csv")
function Test-CsvDir($dir) {
    foreach ($f in $Required) { if (-not (Test-Path (Join-Path $dir $f))) { return $false } }
    return $true
}

$Roots = @()
if ($env:PRESEED_PATH) { $Roots += $env:PRESEED_PATH }
$Roots += @((Join-Path $HOME "Downloads"), (Join-Path $HOME "Desktop"), (Join-Path $HOME "Documents"),
            [Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("MyDocuments"))
$Roots = $Roots | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique

$CsvDir = $null
$Extract = Join-Path $Work "preseed"

# a) already extracted folder
foreach ($root in $Roots) {
    if ((Test-Path $root -PathType Container) -and (Test-CsvDir $root)) { $CsvDir = $root; break }
    $hit = Get-ChildItem $root -Recurse -Depth 3 -Filter "work_event_sources.csv" -ErrorAction SilentlyContinue |
           Where-Object { $_.DirectoryName -notlike "$Work*" -and (Test-CsvDir $_.DirectoryName) } |
           Select-Object -First 1
    if ($hit) { $CsvDir = $hit.DirectoryName; break }
}

# b) zip: HELLOMYME_PreSeed_CSV_v1.2*.zip, or the project package that contains it
if (-not $CsvDir) {
    $zips = foreach ($root in $Roots) {
        if (Test-Path $root -PathType Leaf) { Get-Item $root }
        else { Get-ChildItem $root -Recurse -Depth 2 -Filter "*.zip" -ErrorAction SilentlyContinue }
    }
    $csvZip = $zips | Where-Object { $_.Name -like "*PreSeed_CSV_$DatasetVersion*" } |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $csvZip) {
        $pkg = $zips | Where-Object { $_.Name -like "*HELLOMYME_Project_Package*" } |
               Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($pkg) {
            Write-Host "프로젝트 패키지 압축 해제: $($pkg.Name)"
            $pkgDir = Join-Path $Work "package"
            if (Test-Path $pkgDir) { Remove-Item -Recurse -Force $pkgDir }
            Expand-Archive $pkg.FullName -DestinationPath $pkgDir
            $csvZip = Get-ChildItem $pkgDir -Recurse -Filter "*PreSeed_CSV_$DatasetVersion*.zip" | Select-Object -First 1
        }
    }
    if ($csvZip) {
        Write-Host "CSV 압축 해제: $($csvZip.Name)"
        if (Test-Path $Extract) { Remove-Item -Recurse -Force $Extract }
        Expand-Archive $csvZip.FullName -DestinationPath $Extract
        $hit = Get-ChildItem $Extract -Recurse -Filter "work_event_sources.csv" | Select-Object -First 1
        if ($hit -and (Test-CsvDir $hit.DirectoryName)) { $CsvDir = $hit.DirectoryName }
    }
}
if (-not $CsvDir) {
    throw ("Pre-seed 파일을 찾지 못했습니다. HELLOMYME_PreSeed_CSV_$DatasetVersion.zip 또는 " +
           "HELLOMYME_Project_Package 압축 파일을 다운로드 폴더에 두고 다시 실행하세요. " +
           "다른 위치라면: `$env:PRESEED_PATH='C:\경로'")
}
Write-Host "사용할 폴더: $CsvDir"

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

# 5. Import ---------------------------------------------------------------------------------
Step "설치 및 import (1~3분)"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
Push-Location $ApiDir
try {
    uv sync --no-dev
    if ($LASTEXITCODE -ne 0) { throw "uv sync 실패" }
    $report = Join-Path $Work "import-report.json"
    uv run --no-dev hellomyme-import-preseed $CsvDir --dataset-version $DatasetVersion --as-of $AsOf |
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
if ($r.aggregation) { Write-Host ("경력 이동 집계: " + $r.aggregation.transitions) }
Write-Host "전체 리포트: $report"
if ($code -ne 0) { throw "import 실패 (exit $code). 위 리포트를 확인하세요." }
Write-Host "`n완료. https://nextpath.da-sh.io 에서 확인하세요." -ForegroundColor Green
