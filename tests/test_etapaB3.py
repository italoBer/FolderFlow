# -*- coding: utf-8 -*-
"""Etapa B3/B4: revisão antes de 'Corrigir todas' e cards do relatório
como filtro."""
import os
import sys
import time
import shutil
import tempfile
import datetime

sys.path.insert(0, r"D:\Claude\Teste1")
import folderflow as ff
import customtkinter as ctk

ff.messagebox.askyesno = lambda *a, **k: True
ff.messagebox.showinfo = lambda *a, **k: None
ff.messagebox.showwarning = lambda *a, **k: None

ok = 0


def check(cond, msg):
    global ok
    if cond:
        ok += 1
        print(f"  OK  {msg}")
    else:
        print(f"FALHOU: {msg}")
        sys.exit(1)


tmp = tempfile.mkdtemp(prefix="ff_eB3_")
ff.CONFIG_FILE = os.path.join(tmp, "cfg.json")
ff.INDEX_FILE = os.path.join(tmp, "idx.json")
ff.HISTORY_FILE = os.path.join(tmp, "hist.json")
base = os.path.join(tmp, "base")
os.makedirs(base)
g = ff.preset_marketplace_groups()[0]
g["base_path"] = base
cfg = ff.DEFAULT_CONFIG.copy()
cfg.update({"groups": [g], "onboarding_ok": True, "usa_trello": False,
            "usa_onedrive": False})
ff.save_config(cfg)
agora = datetime.datetime.now()
ano, mes = str(agora.year), ff.MESES[agora.month - 1]
destino = ff.mp_destino(g, ano, mes)
mn = mes[:2]


def pasta(nome, arquivos=(), enviar=()):
    p = os.path.join(destino, nome)
    os.makedirs(os.path.join(p, "#ENVIAR"), exist_ok=True)
    for a in arquivos:
        open(os.path.join(p, a), "w").close()
    for a in enviar:
        open(os.path.join(p, "#ENVIAR", a), "w").close()


pasta(f"{mn}0001IT - Padaria", enviar=("arte.pdf",))
pasta(f"{mn}0002IT - Vazio")
pasta(f"{mn}0003IT - Vazio")
pasta(f"{mn}0004AB - Vazio", arquivos=("Restaurante Bom Prato.cdr",))
pasta(f"{mn}0005AB - Vazio", arquivos=("Oficina do João.cdr",))

app = ff.App()
app.update()
app.show_group(app.groups()[0])


def pump(s=0.3):
    end = time.time() + s
    while time.time() < end:
        app.update()
        time.sleep(0.01)


def todos(w, tipo, out=None):
    out = [] if out is None else out
    for c in w.winfo_children():
        if isinstance(c, tipo):
            out.append(c)
        todos(c, tipo, out)
    return out


pump(0.6)
app._tabs_grupo.set(app.ABA_CONF)
pump(0.5)
aba = app._tabs_grupo.tab(app.ABA_CONF)
[b for b in todos(aba, ctk.CTkButton) if "CONFERIR" in str(b.cget("text"))][0].invoke()
pump(1.5)
b_corr = [b for b in todos(aba, ctk.CTkButton)
          if "Corrigir todas" in str(b.cget("text"))][0]
b_corr.invoke()
pump(0.6)
rev = [w for w in app.winfo_children() if isinstance(w, ctk.CTkToplevel)][-1]
b_ap = [b for b in todos(rev, ctk.CTkButton) if "Aplicar" in str(b.cget("text"))][0]
check("Aplicar 2 correções" in b_ap.cget("text"), "revisão: 2 correções")
textos = [l.cget("text") for l in todos(rev, ctk.CTkLabel)]
check(any(f"{mn}0004AB - Vazio" == t for t in textos)
      and any(t == f"→  {mn}0004AB - Restaurante Bom Prato" for t in textos),
      "mostra 'antes → depois'")
todos(rev, ctk.CTkCheckBox)[1].toggle()          # tira a 2ª
pump(0.2)
check("Aplicar 1 correção" in b_ap.cget("text"), "desmarcar atualiza o botão")
ent = todos(rev, ctk.CTkEntry)[0]
ent.delete(0, "end")
ent.insert(0, "Restaurante Novo")
pump(0.2)
check(any(l.cget("text") == f"→  {mn}0004AB - Restaurante Novo"
          for l in todos(rev, ctk.CTkLabel)), "editar o nome atualiza a prévia")
b_ap.invoke()
pump(0.8)
nomes = os.listdir(destino)
check(f"{mn}0004AB - Restaurante Novo" in nomes, "aplicou com o nome editado")
check(f"{mn}0005AB - Vazio" in nomes, "a desmarcada ficou como estava")
check("(1)" in b_corr.cget("text"), f"sobra 1 pendente ({b_corr.cget('text')})")

# nada para corrigir: o botão explica
shutil.rmtree(os.path.join(destino, f"{mn}0005AB - Vazio"))
[b for b in todos(aba, ctk.CTkButton) if "CONFERIR" in str(b.cget("text"))][0].invoke()
pump(1.5)
check(b_corr.cget("text") == "✔ Nada para corrigir", "botão diz 'Nada para corrigir'")
check(any("Nada para corrigir neste mês" in str(l.cget("text"))
          for l in todos(aba, ctk.CTkLabel)), "e explica o motivo")

# ── relatório: cards como filtro ────────────────────────────────────────────
app._tabs_grupo.set(app.ABA_REL)
pump(0.5)
aba = app._tabs_grupo.tab(app.ABA_REL)
[b for b in todos(aba, ctk.CTkButton) if "RELATÓRIO" in str(b.cget("text"))][0].invoke()
pump(1.5)
tabela = todos(aba, ctk.CTkScrollableFrame)[0]
n_linhas = lambda: len(tabela.winfo_children()) - 1
check(n_linhas() == 4, f"4 pastas na tabela ({n_linhas()})")
cards = {l.cget("text"): l for l in todos(aba, ctk.CTkLabel)
         if l.cget("text") in ("total", "vazias", "entregues")}
# o clique está no rótulo interno do CTkLabel
cards["vazias"]._label.event_generate("<Button-1>")
pump(0.4)
check(n_linhas() == 2, f"clicar em 'vazias' mostra só as 2 vazias ({n_linhas()})")
moldura = cards["vazias"].master
check(moldura.cget("border_color") == ff.ACCENT, "card ativo destacado")
cards["vazias"]._label.event_generate("<Button-1>")
pump(0.4)
check(n_linhas() == 4, "clicar de novo mostra tudo")
cards["entregues"]._label.event_generate("<Button-1>")
pump(0.3)
cards["total"]._label.event_generate("<Button-1>")
pump(0.3)
check(n_linhas() == 4, "clicar em 'total' mostra tudo")

app.destroy()
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{ok} verificações passaram. ETAPA B3/B4 OK")
