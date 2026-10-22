@echo off
rem Compile la fenetre du studio : target\release\DSDecompStudio.exe (Studio.cmd le lance).
rem Pas de Visual Studio sur ce PC : toolchain Rust gnu + WinLibs (dlltool, as, ld) sur le PATH.
cd /d "%~dp0"
set PATH=%LOCALAPPDATA%\Microsoft\WinGet\Packages\BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe\mingw64\bin;%USERPROFILE%\.cargo\bin;%PATH%
cargo +stable-x86_64-pc-windows-gnu build --release -j 4 || exit /b 1
rem with the gnu toolchain the WebView2 loader is a DLL: it must sit next to the .exe
for /d %%d in (target\release\build\webview2-com-sys-*) do if exist "%%d\out\x64\WebView2Loader.dll" copy /y "%%d\out\x64\WebView2Loader.dll" target\release\ >nul
