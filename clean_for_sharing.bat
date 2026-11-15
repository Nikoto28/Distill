@echo off
rem clean_for_sharing.bat - strips this folder down to what is needed to build Distill, so it can be zipped and shared
rem without your saved logins, settings, downloaded tools or installed games going with it.
rem
rem   clean_for_sharing.bat              list what will go, ask, then delete
rem   clean_for_sharing.bat /dry         only list it, delete nothing
rem   clean_for_sharing.bat /y           delete without asking
rem   clean_for_sharing.bat /keepvenv    leave .venv-build alone, so the next build does not reinstall everything
rem
rem Deleted for good, not sent to the Recycle Bin. Run it on a COPY of your folder, not the one you use every day.
setlocal EnableExtensions
cd /d "%~dp0"

if not exist "Distill.spec" goto :notsource
if not exist "distill\constants.py" goto :notsource

set "YES="
set "DRY="
set "KEEPVENV="
:args
if "%~1"=="" goto :argsdone
if /i "%~1"=="/y" set "YES=1"
if /i "%~1"=="/dry" set "DRY=1"
if /i "%~1"=="/keepvenv" set "KEEPVENV=1"
shift
goto :args
:argsdone

rem Folders the app or the build creates beside the source. tools holds downloaded programs, recomps holds installed games,
rem covers and state.json (your SteamGridDB key and GitHub token), game_media holds downloaded screenshots and media,
rem icon_cache holds pictures found online, Watch is the watched drop folder, keys holds your key files, distill_torrents
rem holds torrent copies.
set "DIRLIST=tools recomps game_media icon_cache Watch keys distill_torrents pkg_logs dist build .pytest_cache .ruff_cache"

set "FILELIST=distill_*.json distill_*.txt distill_*.db distill_*.db-wal distill_*.db-shm ps3_names.json selftest.txt *.part distill\local_keys.py"

set /a found=0
echo.
echo This folder: %CD%
echo.
echo Will be deleted:
for %%P in (%DIRLIST%) do (
    if exist "%%P\" (
        echo   folder  %%P
        set /a found+=1
    )
)
if not defined KEEPVENV (
    for /d %%P in (.venv*) do (
        echo   folder  %%P
        set /a found+=1
    )
)
for %%P in (%FILELIST%) do (
    if exist "%%P" (
        echo   file    %%P
        set /a found+=1
    )
)
for /f "delims=" %%P in ('dir /s /b /ad "distill\__pycach*" "tests\__pycach*" 2^>nul') do (
    echo   folder  %%P
    set /a found+=1
)

if %found%==0 (
    echo   nothing - this folder is already clean.
    goto :end
)

echo.
echo Kept: the source, tests, assets, README, build files and the bundled recomp list.
if defined DRY (
    echo Dry run - nothing was deleted.
    goto :end
)

if not defined YES (
    echo.
    echo This permanently removes saved logins, settings, tools and installed recomps from THIS folder.
    choice /c YN /n /m "Delete all of that now? [Y/N] "
    if errorlevel 2 (
        echo Cancelled - nothing was deleted.
        goto :end
    )
)

for %%P in (%DIRLIST%) do (
    if exist "%%P\" rd /s /q "%%P"
)
if not defined KEEPVENV (
    for /d %%P in (.venv*) do rd /s /q "%%P"
)
for %%P in (%FILELIST%) do (
    if exist "%%P" del /f /q "%%P"
)
for /f "delims=" %%P in ('dir /s /b /ad "distill\__pycach*" "tests\__pycach*" 2^>nul') do (
    rd /s /q "%%P"
)

echo.
echo Done. This folder is safe to zip and share.
goto :end

:notsource
echo This does not look like the Distill source folder - Distill.spec and distill\constants.py were not found next to this file.
echo Nothing was deleted.
exit /b 1

:end
endlocal
