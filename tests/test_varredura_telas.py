# -*- coding: utf-8 -*-
"""Varredura de TODAS as telas e diálogos, clicando como o usuário.
Qualquer erro dentro de um clique (que no app real só aparece no console e
deixa o botão "sem fazer nada") é capturado e reprovado aqui."""
import os
import sys
import time
import shutil
import tempfile
import datetime
import traceback

sys.path.insert(0, r"D:\Claude\Teste1")
import folderflow as ff
import customtkinter as ctk

ok = 0
erros = []


def check(cond, msg):
    global ok
    if cond:
        ok += 1
        print(f"  OK  {msg}")
    else:
        print(f"FALHOU: {msg}")
        for e in erros[:5]:
            print(e)
        sys.exit(1)


# nenhum diálogo pode travar o teste: respostas "não/cancelar"
ff.messagebox.askyesno = lambda *a, **k: False
ff.messagebox.showinfo = lambda *a, **k: None
ff.messagebox.showwarning = lambda *a, **k: None
ff.messagebox.showerror = lambda *a, **k: erros.append(f"showerror: {a}")
ff.filedialog.askdirectory = lambda *a, **k: ""
ff.filedialog.askopenfilename = lambda *a, **k: ""
ff.filedialog.asksaveasfilename = lambda *a, **k: ""
ff.check_update = lambda *a, **k: None          # sem internet no teste


def novo_ambiente(prefixo):
    tmp = tempfile.mkdtemp(prefix=prefixo)
    ff.CONFIG_FILE = os.path.join(tmp, "cfg.json")
    ff.INDEX_FILE = os.path.join(tmp, "idx.json")
    ff.HISTORY_FILE = os.path.join(tmp, "hist.json")
    return tmp


def abre_app():
    app = ff.App()
    app.report_callback_exception = lambda et, ev, tb: erros.append(
        "".join(traceback.format_exception(et, ev, tb)))
    app.update()
    return app


def pump(app, s=0.3):
    fim = time.time() + s
    while time.time() < fim:
        app.update()
        time.sleep(0.01)


def todos(w, tipo, out=None):
    out = [] if out is None else out
    for c in w.winfo_children():
        if isinstance(c, tipo):
            out.append(c)
        todos(c, tipo, out)
    return out


def janelas(app):
    return [w for w in app.winfo_children() if isinstance(w, ctk.CTkToplevel)]


def fecha_janelas(app):
    for w in janelas(app):
        try:
            w.destroy()
        except Exception:
            pass
    pump(app, 0.2)


def sem_erros(msg):
    check(not erros, msg + (f"  ({len(erros)} erro(s))" if erros else ""))


# ═══ 1. instalação nova: assistente clicado até o fim ═══════════════════════
tmp1 = novo_ambiente("ff_varre1_")
app = abre_app()
pump(app, 1.0)
wiz = janelas(app)
check(wiz, "instalação nova abre o assistente")
wiz = wiz[0]
for passo in range(4):
    b = [b for b in todos(wiz, ctk.CTkButton)
         if b.cget("text") in ("Continuar", "Concluir")][0]
    b.invoke()
    pump(app, 0.3)
check(not wiz.winfo_exists(), "clicar 'Concluir' fecha o assistente")
check(app.config_data["onboarding_ok"], "assistente marca que foi concluído")
pump(app, 0.8)
sem_erros("assistente sem erros do começo ao fim")
app.destroy()
shutil.rmtree(tmp1, ignore_errors=True)

# ═══ 2. app com grupos: todas as telas ══════════════════════════════════════
tmp = novo_ambiente("ff_varre2_")
base_t = os.path.join(tmp, "Clientes")
for n in ("Cliente 0001", "Cliente 0002"):
    os.makedirs(os.path.join(base_t, n, "Artes"))
open(os.path.join(base_t, "Cliente 0001", "Artes", "logo.cdr"), "w").close()
gt = ff.default_group("template")
gt.update({"name": "Clientes", "base_path": base_t,
           "template": "[2] Cliente {seq:04d}/\n  Artes/\n"})
gs = ff.preset_marketplace_groups({"shopee_base": os.path.join(tmp, "Shopee")})[0]
agora = datetime.datetime.now()
mes = ff.MESES[agora.month - 1]
dest = ff.mp_destino(gs, str(agora.year), mes)
os.makedirs(os.path.join(dest, f"{mes[:2]}0001IT - Vazio", "#ENVIAR"))
open(os.path.join(dest, f"{mes[:2]}0001IT - Vazio", "Padaria.cdr"), "w").close()
cfg = ff.DEFAULT_CONFIG.copy()
cfg.update({"groups": [gt, gs], "onboarding_ok": True, "usa_trello": True,
            "usa_onedrive": True})
ff.save_config(cfg)
app = abre_app()
pump(app, 1.0)
check(not janelas(app), "com grupos: abre direto")

app.show_home()
pump(app, 1.5)
sem_erros("início (cards e pendências)")

for nome, abre in (("Configurações", app.open_settings),
                   ("Ajuda do modelo", app.open_help),
                   ("Sobre", app.open_sobre),
                   ("Watcher", app.open_watcher),
                   ("Atalhos", app.open_atalhos),
                   ("Novo grupo", lambda: app.open_group_editor(None)),
                   ("Editar grupo", lambda: app.open_group_editor(app.groups()[1])),
                   ("Excluir grupo", lambda: app._delete_group(app.groups()[0]))):
    abre()
    pump(app, 0.7)
    check(janelas(app), f"abre: {nome}")
    fecha_janelas(app)
    sem_erros(f"{nome} sem erros")

pal = app.open_paleta()
pump(app, 0.3)
pal.paleta["digita"]("cli")
pump(app, 0.2)
pal.paleta["fecha"]()
sem_erros("paleta Ctrl+K")

app.show_search()
pump(app, 0.4)
app._busca_campo.insert(0, "cliente")
app._busca_campo._entry.event_generate("<KeyRelease>")
pump(app, 0.6)
sem_erros("busca")

app.quick_create(app.groups()[0])            # confirmação responde "não"
pump(app, 0.3)
sem_erros("⚡ criar agora (cancelado)")

for g in app.groups():
    app.show_group(g)
    pump(app, 0.5)
    for aba in list(app._tabs_grupo._tab_dict):
        app._tabs_grupo.set(aba)
        pump(app, 0.6)
        t = app._tabs_grupo.tab(aba)
        # botões de ação de cada aba
        for rotulo in ("CONFERIR", "GERAR RELATÓRIO", "Localizar",
                       "Detectar organização", "Dividir igualmente"):
            for b in todos(t, ctk.CTkButton):
                if rotulo in str(b.cget("text")) and b.cget("state") == "normal":
                    b.invoke()
                    pump(app, 0.8)
        # menus de contexto das árvores (sem abrir o menu nativo)
        for arv in todos(t, ff.TreeCanvas):
            if arv.on_context:
                arv.on_context(None, [])
                linhas = arv.rows()
                if linhas:
                    arv.on_context(linhas[0], [linhas[0]])
        fecha_janelas(app)
        sem_erros(f"{g['name']} › {aba.strip()}")

tour = app.iniciar_tour()
for i in range(len(tour._roteiro)):
    pump(app, 0.5)
    tour.avancar()
pump(app, 0.5)
sem_erros("tour completo")

app._start_watcher()
pump(app, 0.5)
app._stop_watcher()
pump(app, 0.5)
sem_erros("liga/desliga watcher")

app.destroy()
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{ok} verificações passaram. VARREDURA DAS TELAS OK")
