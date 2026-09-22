@echo off
setlocal
pushd "%~dp0"
python -c "from pathlib import Path; import subprocess,sys; subprocess.Popen([str(Path(sys.executable).with_name('pythonw.exe')),str(Path.cwd()/'lab.py')],cwd=Path.cwd())"
if errorlevel 1 pause
popd
