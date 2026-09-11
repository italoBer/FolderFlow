# -*- coding: utf-8 -*-
"""Etapa A no app: abas iguais, Renomear/Conferir genéricos, excluir grupo,
logo volta ao início, detecção no editor, criar modelo aqui, rolagem."""
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
ff.messagebox.showerror = lambda *a, **k: print("      [showerror]", a)

ok = 0


def check(cond, msg):
    global ok
    if cond:
        ok += 1
        print(f"  OK  {msg}")
    else:
        print(f"FALHOU: {msg}")
        sys.exit(1)


tmp = tempfile.mkdtemp(prefix="ff_eA_")
ff.CONFIG_FILE = os.path.join(tmp, "cfg.json")
ff.INDEX_FILE = os.path.join(tmp, "idx.json")
ff.HISTORY_FILE = os.path.join(tmp, "hist.json")

# grupo de estrutura com pastas reais
base_t = os.path.join(tmp, "Estrutura")
for n in ("vazio 0001", "vazio 0002", "Cliente Pronto", "Padaria Antiga"):
    os.makedirs(os.path.join(base_t, n))
open(os.path.join(base_t, "vazio 0002", "Padaria Central.cdr"), "w").close()
open(os.path.join(base_t, "Cliente Pronto", "arte.pdf"), "w").close()
gt = ff.default_group("template")
gt.update({"name": "Estrutura", "base_path": base_t,
           "template": "Nova Estrutura/\n  sub/\n"})

# marketplace sem pasta por mês (o caso do 'Grupo 2 Testes')
base_m = os.path.join(tmp, "Ecom")
os.makedirs(base_m)
agora = datetime.datetime.now()
mn = f"{agora.month:02d}"
for n in (f"{mn}0001D - Vazio", f"{mn}0002D - carlinhos"):
    os.makedirs(os.path.join(base_m, n, "#ENVIAR"))
gm = ff.default_group("marketplace")
gm.update({"name": "Ecom", "base_path": base_m, "dest_pattern": ""})

cfg = ff.DEFAULT_CONFIG.copy()
cfg.update({"groups": [gt, gm], "onboarding_ok": True, "usa_trello": False,
            "usa_onedrive": False})
ff.save_config(cfg)

app = ff.App()
app.update()


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


# ── todas as abas montam sem erro nos dois tipos ────────────────────────────
for g in app.groups():
    app.show_group(g)
    pump(0.5)
    tabs = app._tabs_grupo
    for nome in tabs._tab_dict:
        tabs.set(nome)
        pump(0.4)
    check(True, f"'{g['name']}': as {len(tabs._tab_dict)} abas abriram")

g_t, g_m = app.groups()

# ── fita de meses do marketplace sem pasta por mês ──────────────────────────
app.show_group(g_m)
pump(0.4)
app._tabs_grupo.set(app.ABA_CRIAR)
pump(1.0)
aba = app._tabs_grupo.tab(app.ABA_CRIAR)
textos = " ".join(str(l.cget("text")) for l in todos(aba, ctk.CTkLabel))
check("contagem pelo código" in textos,
      "fita avisa: 'não tem pasta por mês — contagem pelo código'")
check("12 de 12" not in textos, "não mostra mais o falso '12 de 12 meses'")
links = [b for b in todos(aba, ctk.CTkButton)
         if b.cget("text") == "Detectar organização"]
check(links and links[0].winfo_ismapped(), "link 'Detectar organização' aparece")

# ── Renomear genérico: busca por parte do nome ──────────────────────────────
app.show_group(g_t)
pump(0.4)
app._tabs_grupo.set(app.ABA_REN)
pump(0.5)
aba = app._tabs_grupo.tab(app.ABA_REN)
ents = todos(aba, ctk.CTkEntry)
ents[0].insert(0, "padaria")
[b for b in todos(aba, ctk.CTkButton) if "Localizar" in str(b.cget("text"))][0].invoke()
pump(1.5)
resultados = [b.cget("text") for b in todos(aba, ctk.CTkButton)
              if "Padaria Antiga" in str(b.cget("text"))]
check(resultados, "achou 'Padaria Antiga' buscando 'padaria'")
check(any("Selecionada: Padaria Antiga" in str(l.cget("text"))
          for l in todos(aba, ctk.CTkLabel)),
      "resultado único já vem selecionado")
ents[1].insert(0, "Padaria Nova")
pump(0.3)
b_ren = [b for b in todos(aba, ctk.CTkButton) if "RENOMEAR" in str(b.cget("text"))]
check(b_ren[0].cget("state") == "normal", "botão RENOMEAR habilitado")
b_ren[0].invoke()
pump(0.6)
check(os.path.isdir(os.path.join(base_t, "Padaria Nova")),
      "sem código: troca o nome inteiro ('Padaria Nova')")

# ── Conferir genérico (grupo de estrutura, escopo = pasta) ──────────────────
app._tabs_grupo.set(app.ABA_CONF)
pump(0.5)
aba = app._tabs_grupo.tab(app.ABA_CONF)
b_conf = [b for b in todos(aba, ctk.CTkButton) if "CONFERIR" in str(b.cget("text"))]
check("PASTA" in b_conf[0].cget("text"), "grupo de estrutura: 'CONFERIR PASTA'")
b_conf[0].invoke()
pump(1.5)
check(any(e.get() == "Padaria Central" for e in todos(aba, ctk.CTkEntry)),
      "sugere 'Padaria Central' pelo .cdr da 'vazio 0002'")
b_corr = [b for b in todos(aba, ctk.CTkButton) if "Corrigir todas" in str(b.cget("text"))]
b_corr[0].invoke()
pump(0.8)
check(os.path.isdir(os.path.join(base_t, "0002 - Padaria Central")),
      "corrigiu para '0002 - Padaria Central'")

# ── Criar estrutura do modelo aqui ──────────────────────────────────────────
destino = os.path.join(base_t, "Cliente Pronto")
app._criar_modelo_em(app.groups()[0], destino)
pump(1.5)
check(os.path.isdir(os.path.join(destino, "Nova Estrutura", "sub")),
      "modelo aplicado dentro da pasta escolhida")
for w in app.winfo_children():
    if isinstance(w, ctk.CTkToplevel):
        w.destroy()

# ── clique no logo volta ao início ──────────────────────────────────────────
nome_lbl = [l for l in todos(app, ctk.CTkLabel) if l.cget("text") == ff.APP_NAME][0]
nome_lbl._label.event_generate("<Button-1>") if hasattr(nome_lbl, "_label") \
    else nome_lbl.event_generate("<Button-1>")
pump(0.5)
check(app._crumb.cget("text").endswith("Início"), "clicar em FolderFlow volta ao início")

# ── editor: marketplace novo nasce com {ano}/{mes} e detecta ────────────────
base_d = os.path.join(tmp, "Detecta")
for m in ("07 - JULHO", "08 - AGOSTO", "09 - SETEMBRO"):
    os.makedirs(os.path.join(base_d, "Loja 2026", m + " - LOJA"))
win = app.open_group_editor(None) or [w for w in app.winfo_children()
                                      if isinstance(w, ctk.CTkToplevel)][-1]
pump(0.5)
seg = todos(win, ctk.CTkSegmentedButton)[0]
check("Marketplace" in seg.cget("values"), "rótulo agora é só 'Marketplace'")
seg.set("Marketplace")
seg._command("Marketplace")
pump(0.3)
ents = todos(win, ctk.CTkEntry)
padrao = [e for e in ents if e.get() == "{ano}/{mes}"]
check(padrao, "marketplace novo já nasce com {ano}/{mes}")
b_det = [b for b in todos(win, ctk.CTkButton) if "Detectar" in str(b.cget("text"))]
check(b_det, "botão 'Detectar pelas pastas' existe")
ents[1].delete(0, "end")            # pasta base
ents[1].insert(0, base_d)
b_det[0].invoke()
pump(1.5)
cards = [l.cget("text") for l in todos(win, ctk.CTkLabel)
         if "reconhece" in str(l.cget("text"))]
print("      candidatos:", [c.splitlines()[0] for c in cards])
check(any("Loja {ano}/{mes} - LOJA" in c for c in cards),
      "detectou 'Loja {ano}/{mes} - LOJA'")
win.destroy()
pump(0.2)

# ── excluir grupo: travas e confirmação digitando o nome ────────────────────
check(ff.pasta_protegida("C:\\") is not None, "recusa apagar raiz de disco")
check(ff.pasta_protegida(os.path.expanduser("~")) is not None,
      "recusa apagar a pasta do usuário")
check(ff.pasta_protegida(base_t) is None, "pasta comum pode ser apagada")

dlg = app._delete_group(app.groups()[0])
pump(0.6)
radios = todos(dlg, ctk.CTkRadioButton)
radios[1].invoke()                      # "Remover e apagar a pasta base"
pump(0.8)
b_ok = [b for b in todos(dlg, ctk.CTkButton)
        if "Apagar" in str(b.cget("text"))][0]
check(b_ok.cget("state") == "disabled", "botão bloqueado até digitar o nome")
ent = todos(dlg, ctk.CTkEntry)[0]
ent.insert(0, "Estrutura")
pump(0.3)
check(b_ok.cget("state") == "normal", "digitando o nome do grupo, libera")
b_ok.invoke()
pump(0.8)
check(not os.path.exists(base_t), "pasta base foi para a Lixeira")
check([g["name"] for g in app.groups()] == ["Ecom"], "grupo removido do app")

# remover só do app (padrão) mantém a pasta
dlg = app._delete_group(app.groups()[0])
pump(0.4)
[b for b in todos(dlg, ctk.CTkButton)
 if "Remover do FolderFlow" in str(b.cget("text"))][0].invoke()
pump(0.4)
check(os.path.isdir(base_m) and not app.groups(),
      "'Remover só do FolderFlow' mantém a pasta no disco")

app.destroy()
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{ok} verificações passaram. ETAPA A OK")
