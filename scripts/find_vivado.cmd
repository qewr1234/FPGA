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
for %%R in (
    "C:\Xilinx"
    "D:\Xilinx"
    "E:\Xilinx"
    "C:\tools\Xilinx"
    "%ProgramFiles%\Xilinx"
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
if errorlevel 1 exit /b 1
exit /b 0
