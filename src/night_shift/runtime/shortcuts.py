"""Atalhos na área de trabalho do Windows: OFF, ON e Painel.

Cada atalho abre um ``cmd`` que roda o comando e (no OFF/ON) espera uma tecla, para dar
para ler o relatório antes da janela fechar.
"""

import os
from pathlib import Path

# Ícones do shell32.dll do próprio Windows.
ICON_POWER = 27
ICON_PLAY = 137
ICON_WINDOW = 13

SHORTCUTS = [
    ("night-shift OFF", "off", True, ICON_POWER),
    ("night-shift ON", "on", True, ICON_PLAY),
    ("night-shift Painel", "serve --open", False, ICON_WINDOW),
]


def shortcut_arguments(exe: Path, command: str, pause: bool) -> str:
    # cmd /c ""C:\caminho com espaço\night-shift.exe" off & pause"
    return f'/c ""{exe}" {command}{" & pause" if pause else ""}"'


def create_desktop_shortcuts(exe: Path, workdir: Path) -> list[Path]:
    import win32com.client

    shell = win32com.client.Dispatch("WScript.Shell")
    # SpecialFolders respeita a área de trabalho redirecionada pelo OneDrive.
    desktop = Path(shell.SpecialFolders("Desktop"))
    cmd = Path(os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"))
    shell32 = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "shell32.dll"

    created = []
    for name, command, pause, icon in SHORTCUTS:
        path = desktop / f"{name}.lnk"
        link = shell.CreateShortCut(str(path))
        link.TargetPath = str(cmd)
        link.Arguments = shortcut_arguments(exe, command, pause)
        link.WorkingDirectory = str(workdir)
        link.IconLocation = f"{shell32},{icon}"
        link.Description = f"night-shift {command}"
        link.Save()
        created.append(path)
    return created
