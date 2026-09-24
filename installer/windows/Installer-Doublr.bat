@echo off
title Installation de Doublr
echo.
echo   Installation de Doublr (doublage audio par IA)
echo   Cette fenetre va telecharger et installer tout le necessaire.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; iex (irm 'https://raw.githubusercontent.com/coachccai-blip/mp3-audio-translator/main/installer/windows/install.ps1')"
echo.
pause
