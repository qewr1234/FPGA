@echo off
rem Put Vivado on PATH for the caller. No setlocal: the PATH change must survive.
rem Returns errorlevel 0 when "vivado" is runnable afterwards, 1 when it is not.
rem
rem Order: something already on PATH, then %XILINX_VIVADO%, then the usual install
rem roots with the highest version directory first.

where vivado >nul 2>nul
if not errorlevel 1 exit /b 0

if defined XILINX_VIVADO (
    if exist "%XILINX_VIVADO%\settings64.bat" (
        echo Using XILINX_VIVADO=%XILINX_VIVADO%
        call "%XILINX_VIVADO%\settings64.bat"
        where vivado >nul 2>nul
        if not errorlevel 1 exit /b 0
    ) else (
        echo XILINX_VIVADO is set to "%XILINX_VIVADO%" but there is no settings64.bat there.
    )
)

rem Layout the unified installer has used since 2024.x: <root>\<version>\Vivado.
rem C:\Vivado is in this list because that is where an install actually was: the
rem installer's default root can be changed, and only C:\Xilinx was searched, so
rem the script reported Vivado missing on a machine that had it.
for %%R in (
    "C:\Xilinx"
    "D:\Xilinx"
    "E:\Xilinx"
    "C:\Vivado"
    "D:\Vivado"
    "E:\Vivado"
    "C:\tools\Xilinx"
    "C:\AMD"
    "D:\AMD"
    "%ProgramFiles%\Xilinx"
    "%ProgramFiles%\AMD"
) do (
    if exist "%%~R\" (
        for /f "delims=" %%V in ('dir /b /ad /o-n "%%~R" 2^>nul') do (
            if exist "%%~R\%%V\Vivado\settings64.bat" (
                echo Found Vivado %%V in %%~R
                call "%%~R\%%V\Vivado\settings64.bat"
                goto :recheck
            )
        )
    )
)

rem Older layout: <root>\Vivado\<version>.
for %%R in (
    "C:\Xilinx\Vivado"
    "D:\Xilinx\Vivado"
    "E:\Xilinx\Vivado"
    "C:\tools\Xilinx\Vivado"
    "C:\Xilinx\Vitis"
    "D:\Xilinx\Vitis"
    "%ProgramFiles%\Xilinx\Vivado"
    "%ProgramFiles(x86)%\Xilinx\Vivado"
) do (
    if exist "%%~R\" (
        for /f "delims=" %%V in ('dir /b /ad /o-n "%%~R" 2^>nul') do (
            if exist "%%~R\%%V\settings64.bat" (
                echo Found Vivado %%V in %%~R
                call "%%~R\%%V\settings64.bat"
                goto :recheck
            )
        )
    )
)

:recheck
where vivado >nul 2>nul
if errorlevel 1 (
    echo.
    echo Searched PATH, XILINX_VIVADO and the usual roots without finding
    echo settings64.bat. If Vivado is installed somewhere else, point at the
    echo directory that CONTAINS settings64.bat and re-run:
    echo     set XILINX_VIVADO=C:\Vivado\2026.1\Vivado
    echo To find it:  where /r C:\ settings64.bat
    exit /b 1
)
exit /b 0
