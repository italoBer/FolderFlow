# -*- coding: utf-8 -*-
"""Ida e volta da área de transferência com o Windows (PowerShell).
USA A SUA ÁREA DE TRANSFERÊNCIA — só roda com FF_CLIP=1."""
import os
import sys
import shutil
import tempfile
import subprocess
import tkinter as tk

if os.environ.get("FF_CLIP") != "1":
    print("pulado (defina FF_CLIP=1 para rodar — usa a área de transferência)")
    sys.exit(0)

sys.path.insert(0, r"D:\Claude\Teste1")
import folderflow as ff

ok = 0


def check(cond, msg):
    global ok
    if cond:
        ok += 1
        print(f"  OK  {msg}")
    else:
        print(f"FALHOU: {msg}")
        sys.exit(1)


def ps(cmd):
    r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command",
                        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + cmd],
                       capture_output=True, text=True, encoding="utf-8")
    return r.stdout.strip()


tmp = tempfile.mkdtemp(prefix="ff_clip_")
a = os.path.join(tmp, "Ação São João.cdr")
b = os.path.join(tmp, "pasta com espaço")
open(a, "w").close()
os.makedirs(b)
longo = os.path.join(tmp, *(["subpasta_bem_comprida_" + "x" * 20] * 4))
os.makedirs(longo)
c = os.path.join(longo, "arquivo.pdf")
open(c, "w").close()

root = tk.Tk()
root.withdraw()
hwnd = root.winfo_id()

# FolderFlow → Windows
check(ff.clipboard_escrever_arquivos([a, b, c], hwnd=hwnd), "escreveu")
lista = ps("Add-Type -AssemblyName System.Windows.Forms;"
           "[System.Windows.Forms.Clipboard]::GetFileDropList()").splitlines()
print("      o Windows leu:", [os.path.basename(x) for x in lista])
check(sorted(map(os.path.normcase, lista)) ==
      sorted(map(os.path.normcase, [a, b, c])),
      "o Windows lê os 3 caminhos (acentos e caminho longo)")
lidos, rec = ff.clipboard_ler_arquivos()
check(len(lidos) == 3 and rec is False, "lê de volta como 'copiar'")

ff.clipboard_escrever_arquivos([a], recortar=True, hwnd=hwnd)
lidos, rec = ff.clipboard_ler_arquivos()
check(lidos == [a] and rec is True, "'recortar' marcado")

# Windows → FolderFlow (como o Explorador faz)
ps(f"Set-Clipboard -Path '{b}'")
lidos, rec = ff.clipboard_ler_arquivos()
check([os.path.normcase(x) for x in lidos] == [os.path.normcase(b)],
      "lê o que o Windows copiou")
# recortar do Explorador: DropEffect = 2
ps("Add-Type -AssemblyName System.Windows.Forms;"
   "$d=New-Object System.Windows.Forms.DataObject;"
   "$f=New-Object System.Collections.Specialized.StringCollection;"
   f"[void]$f.Add('{a}');$d.SetFileDropList($f);"
   "$m=New-Object IO.MemoryStream(,[byte[]](2,0,0,0));"
   "$d.SetData('Preferred DropEffect',$m);"
   "[System.Windows.Forms.Clipboard]::SetDataObject($d,$true)")
lidos, rec = ff.clipboard_ler_arquivos()
check(lidos and rec is True, "'Recortar' do Explorador é reconhecido")

ff.clipboard_limpar()
root.destroy()
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{ok} verificações passaram. CLIPBOARD OK")
