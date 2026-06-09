@echo off
chcp 65001 > /dev/null
cd /d "%~dp0"
python scripts\resume-amounts.py >> outputs\_resume_log.txt 2>&1
