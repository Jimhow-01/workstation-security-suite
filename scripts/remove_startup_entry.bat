@echo off
set file_path=%AppData%\Microsoft\Windows\Start Menu\Programs\Startup\bitlocker_startup.bat

if exist "%file_path%" (
    del /F /Q "%file_path%"
    echo Executável deletado com sucesso.
) else (
    echo O arquivo não foi encontrado.
)

