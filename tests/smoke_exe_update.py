# -*- coding: utf-8 -*-
"""Teste de fumaça do .exe, simulando o que acontece num PC da Flag quando a
v1.1.0 se atualiza para a 2.0: o FolderFlow.exe novo aparece na MESMA pasta,
ao lado do folderflow_config.json e do folderflow_index.json da v1.

Roda o dist\\FolderFlow.exe de verdade (não o .py) numa pasta temporária e
confere: abre, continua aberto, migra a config para grupos, não cai no
assistente, mantém as chaves da v1 e lê o índice antigo.

Uso:  python tests\\smoke_exe_update.py   (depois de gerar o .exe)"""
import os
import sys
import json
import time
import shutil
import tempfile
import subprocess

RAIZ = r"D:\Claude\Teste1"
EXE = os.path.join(RAIZ, "dist", "FolderFlow.exe")
ok = 0


def check(cond, msg):
    global ok
    if cond:
        ok += 1
        print(f"  OK  {msg}")
    else:
        print(f"FALHOU: {msg}")
        sys.exit(1)


check(os.path.isfile(EXE), "dist\\FolderFlow.exe existe")
pasta = tempfile.mkdtemp(prefix="ff_smoke_")
shutil.copy2(EXE, os.path.join(pasta, "FolderFlow.exe"))
bases = {k: os.path.join(pasta, "dados", k) for k in ("Shopee", "ML")}
sh_mes = os.path.join(bases["Shopee"], "Shopee 2026", "09 - SETEMBRO - SHOPEE")
os.makedirs(os.path.join(sh_mes, "090001IT - Padaria", "#ENVIAR"))
os.makedirs(os.path.join(bases["ML"], "ML - 2026", "09 - SETEMBRO", "A090001IT - Vazio"))

cfg_v1 = {
    "shopee_base": bases["Shopee"], "ml_base": bases["ML"],
    "pause_onedrive": True, "trello_key": "", "trello_token": "",
    "shopee_board_id": "", "ml_board_id": "",
    "shopee_list_aguardando": "", "ml_list_aguardando": "",
    "shopee_list_dev_id": "", "ml_list_dev_id": "",
    "watcher_interval": 60, "github_repo": "italoBer/FolderFlow",
}
cfg_path = os.path.join(pasta, "folderflow_config.json")
json.dump(cfg_v1, open(cfg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
idx_v1 = {"090001IT": {"path": os.path.join(sh_mes, "090001IT - Padaria"),
                       "nome": "090001IT - Padaria", "plat": "SHOPEE",
                       "cliente": "Padaria"}}
json.dump(idx_v1, open(os.path.join(pasta, "folderflow_index.json"), "w",
                       encoding="utf-8"), ensure_ascii=False, indent=2)

proc = subprocess.Popen([os.path.join(pasta, "FolderFlow.exe")], cwd=pasta)
try:
    migrou = False
    fim = time.time() + 40
    while time.time() < fim:
        try:
            c = json.load(open(cfg_path, encoding="utf-8"))
            if c.get("config_version") == 2 and c.get("onboarding_ok"):
                migrou = True
                break
        except Exception:
            pass
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    check(proc.poll() is None, "o .exe abriu e está rodando")
    check(migrou, "config da v1.1.0 migrada pelo .exe (versão 2, sem assistente)")
    c = json.load(open(cfg_path, encoding="utf-8"))
    nomes = [g["name"] for g in c.get("groups", [])]
    check(nomes == ["Shopee", "Mercado Livre"], f"grupos criados a partir da v1: {nomes}")
    check(c["groups"][0]["base_path"] == bases["Shopee"]
          and c["groups"][1]["prefix"] == "A", "pastas base e prefixo corretos")
    check(all(k in c for k in cfg_v1), "chaves da v1 mantidas (dá para voltar)")
    check(os.path.exists(cfg_path + ".bak"), "backup da config criado antes de gravar")
    time.sleep(8)          # passa da checagem de update (3s) e do índice (4s)
    check(proc.poll() is None, "continua aberto depois de 8s (sem fechar sozinho)")
    # o .exe é de arquivo único: o processo aberto só descompacta e inicia um
    # processo FILHO, que é quem tem a janela
    ps = ("$ids = @(" + str(proc.pid) + ") + @(Get-CimInstance Win32_Process "
          "-Filter 'ParentProcessId=" + str(proc.pid) + "' | "
          "ForEach-Object { $_.ProcessId }); "
          "$ids | ForEach-Object { (Get-Process -Id $_ -ErrorAction "
          "SilentlyContinue).MainWindowTitle } | Where-Object { $_ }")
    titulos = []
    fim = time.time() + 15
    while time.time() < fim and not titulos:
        try:
            titulos = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                     capture_output=True, text=True
                                     ).stdout.split("\n")
            titulos = [t.strip() for t in titulos if t.strip()]
        except Exception:
            titulos = []
        if not titulos:
            time.sleep(1)
    print("      título da janela:", titulos)
    check(any(t.startswith("FolderFlow v2") for t in titulos),
          "janela principal aberta (FolderFlow v2…)")
    novos = [n for n in os.listdir(pasta) if n.endswith(".corrompido")]
    check(not novos, "nenhum arquivo marcado como corrompido")
finally:
    # mata a árvore inteira (pai + filho); só proc.kill() deixava a janela
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                   capture_output=True)
    try:
        proc.wait(10)
    except Exception:
        pass
    time.sleep(1.5)
    shutil.rmtree(pasta, ignore_errors=True)
print(f"\n{ok} verificações passaram. .EXE OK NO CENÁRIO DE ATUALIZAÇÃO DA FLAG")
