# -*- coding: utf-8 -*-
"""Fase 1 — correções de base: config atômica, OneDrive, criar_lote rápido."""
import os
import sys
import json
import time
import shutil
import tempfile

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


tmp = tempfile.mkdtemp(prefix="ff_f1_")
ff.CONFIG_FILE = os.path.join(tmp, "cfg.json")

# ── 1. Gravação atômica + backup ─────────────────────────────────────────────
cfg = ff.DEFAULT_CONFIG.copy()
g = ff.default_group("template")
g.update({"name": "Grupo Importante", "base_path": tmp})
cfg["groups"] = [g]
ff.save_config(cfg)
check(os.path.exists(ff.CONFIG_FILE), "config gravada")
check(not os.path.exists(ff.CONFIG_FILE + ".tmp"), "temporário não sobra")

cfg["groups"][0]["name"] = "Grupo v2"
ff.save_config(cfg)
check(os.path.exists(ff.CONFIG_FILE + ".bak"), "backup criado na 2ª gravação")
bak = json.load(open(ff.CONFIG_FILE + ".bak", encoding="utf-8"))
check(bak["groups"][0]["name"] == "Grupo Importante",
      "backup guarda a versão anterior")

# ── 2. Config corrompida → recupera do backup, não zera os grupos ────────────
open(ff.CONFIG_FILE, "w", encoding="utf-8").write('{"groups": [{"nam')  # truncado
c = ff.load_config()
check(len(c["groups"]) == 1 and c["groups"][0]["name"] == "Grupo Importante",
      "config corrompida recuperada do backup (grupos preservados)")
check(ff.CONFIG_LOAD_WARNING, "avisa o usuário sobre a recuperação")
print("      aviso:", ff.CONFIG_LOAD_WARNING[0].splitlines()[0])

# ── 3. Corrompida SEM backup → preserva o arquivo para perícia ──────────────
tmp2 = tempfile.mkdtemp(prefix="ff_f1b_")
ff.CONFIG_FILE = os.path.join(tmp2, "cfg.json")
open(ff.CONFIG_FILE, "w", encoding="utf-8").write("lixo{{{")
c = ff.load_config()
check(c["groups"] == [], "sem backup, começa limpo")
check(os.path.exists(ff.CONFIG_FILE + ".corrompido"),
      "arquivo ilegível é preservado, não sobrescrito")
check(ff.CONFIG_LOAD_WARNING, "avisa que não havia backup")

# ── 4. Detecção de OneDrive ─────────────────────────────────────────────────
roots = ff.onedrive_roots()
print("      raízes OneDrive detectadas:", roots)
check(isinstance(roots, list), "onedrive_roots devolve lista")
if roots:
    dentro = os.path.join(roots[0], "Documentos", "Teste")
    check(ff.path_no_onedrive(dentro) == roots[0],
          "pasta dentro do OneDrive é detectada")
    check(ff.path_no_onedrive(roots[0]) == roots[0],
          "a própria raiz conta como OneDrive")
check(ff.path_no_onedrive(tmp) is None,
      f"pasta fora do OneDrive não é detectada ({tmp})")
check(ff.path_no_onedrive("") is None, "caminho vazio não quebra")
check(ff.path_no_onedrive(r"D:\Claude\Teste1") is None,
      "D:\\Claude\\Teste1 corretamente fora do OneDrive")
# não confundir prefixo parecido: "OneDriveXPTO" não está dentro de "OneDrive"
if roots:
    check(ff.path_no_onedrive(roots[0] + "XPTO") is None,
          "prefixo parecido não conta como dentro (OneDriveXPTO)")

# ── 5. criar_lote: rápido e correto ─────────────────────────────────────────
base = os.path.join(tmp, "mp")
os.makedirs(base)
grp = ff.preset_marketplace_groups()[0]
grp["base_path"] = base

n = ff.criar_lote(grp, "2026", "09 - SETEMBRO", [("IT", 3), ("AB", 2)],
                  lambda m, **k: None, pause_od=False)
destino = os.path.join(base, "Shopee 2026", "09 - SETEMBRO - SHOPEE")
check(n == 5, "5 pastas criadas")
check(os.path.isdir(os.path.join(destino, "090001IT - Vazio", "#ENVIAR")),
      "estrutura correta (código + #ENVIAR)")
check(os.path.isdir(os.path.join(destino, "090005AB - Vazio")),
      "numeração contínua entre responsáveis")

n2 = ff.criar_lote(grp, "2026", "09 - SETEMBRO", [("IT", 2)],
                   lambda m, **k: None, pause_od=False)
check(os.path.isdir(os.path.join(destino, "090007IT - Vazio")),
      "segunda rodada continua do 0006")

# não duplica quando a pasta já foi renomeada
os.rename(os.path.join(destino, "090001IT - Vazio"),
          os.path.join(destino, "090001IT - Cliente Teste"))
antes = len(os.listdir(destino))
ff.criar_lote(grp, "2026", "09 - SETEMBRO", [("IT", 1)],
              lambda m, **k: None, pause_od=False)
check(len(os.listdir(destino)) == antes + 1,
      "renomeada não é recriada nem duplicada")

# desempenho: 300 pastas num destino que já tem muitas
base2 = os.path.join(tmp, "perf")
os.makedirs(base2)
grp2 = ff.preset_marketplace_groups()[0]
grp2["base_path"] = base2
ff.criar_lote(grp2, "2026", "09 - SETEMBRO", [("XX", 300)],
              lambda m, **k: None, pause_od=False)
t0 = time.time()
ff.criar_lote(grp2, "2026", "09 - SETEMBRO", [("YY", 300)],
              lambda m, **k: None, pause_od=False)
dt = time.time() - t0
print(f"      300 pastas sobre 300 existentes: {dt:.2f}s")
check(dt < 8.0, f"criação de lote grande é rápida ({dt:.2f}s)")

d2 = os.path.join(base2, "Shopee 2026", "09 - SETEMBRO - SHOPEE")
check(len(os.listdir(d2)) == 600, "600 pastas no total, sem duplicata")

# ── 6. abrir_no_explorer: escape de caminho ─────────────────────────────────
import inspect
src = inspect.getsource(ff.abrir_no_explorer)
check("replace(\"'\", \"''\")" in src, "caminho é escapado para o PowerShell")
check("-NoProfile" in src, "PowerShell roda sem perfil (mais rápido/previsível)")

shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(tmp2, ignore_errors=True)
print(f"\n{ok} verificações passaram. FASE 1 (base) OK")
