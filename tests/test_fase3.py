# -*- coding: utf-8 -*-
"""Fase 3 no app: aba Conferir, correção, histórico, distribuição,
relatório em tabela, assistente e ocultação de Trello/OneDrive."""
import os
import sys
import time
import shutil
import tempfile

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


tmp = tempfile.mkdtemp(prefix="ff_f3_")
ff.CONFIG_FILE = os.path.join(tmp, "cfg.json")
ff.INDEX_FILE = os.path.join(tmp, "idx.json")
ff.HISTORY_FILE = os.path.join(tmp, "hist.json")

base = os.path.join(tmp, "base")
os.makedirs(base)
cfg = ff.DEFAULT_CONFIG.copy()
g = ff.preset_marketplace_groups()[0]
g["base_path"] = base
cfg["groups"] = [g]
cfg["onboarding_ok"] = True          # pula o assistente neste teste
cfg["usa_trello"] = True
cfg["usa_onedrive"] = True
ff.save_config(cfg)

agora = __import__("datetime").datetime.now()
ano, mes = str(agora.year), ff.MESES[agora.month - 1]
destino = ff.mp_destino(g, ano, mes)
os.makedirs(destino)


def pasta(nome, arquivos=(), enviar=()):
    p = os.path.join(destino, nome)
    os.makedirs(p, exist_ok=True)
    os.makedirs(os.path.join(p, "#ENVIAR"), exist_ok=True)
    for a in arquivos:
        open(os.path.join(p, a), "w").close()
    for a in enviar:
        open(os.path.join(p, "#ENVIAR", a), "w").close()


mn = mes[:2]
pasta(f"{mn}0001IT - Padaria do Zé", enviar=("arte.pdf",))
pasta(f"{mn}0002IT - Vazio")
pasta(f"{mn}0003AB - Vazio", arquivos=("Restaurante Bom Prato.cdr",))
pasta(f"{mn}0004AB - Vazio", arquivos=("Oficina do João.cdr",))

app = ff.App()
app.update()
app.show_group(app.groups()[0])


def pump(s=0.3):
    end = time.time() + s
    while time.time() < end:
        app.update()
        time.sleep(0.01)


pump(0.8)


def todos(w, tipo, out=None):
    out = [] if out is None else out
    for c in w.winfo_children():
        if isinstance(c, tipo):
            out.append(c)
        todos(c, tipo, out)
    return out


# ── as abas do marketplace ──────────────────────────────────────────────────
tabview = app._tabs_grupo
abas = [a.strip() for a in tabview._tab_dict.keys()]
print("      abas:", abas)
check(abas == ["Pastas", "Criar", "Renomear", "Conferir", "Relatório"],
      "marketplace: Pastas · Criar · Renomear · Conferir · Relatório")
tabview.set(app.ABA_CRIAR)
pump(0.8)

# ── fita de meses ───────────────────────────────────────────────────────────
btns = todos(app, ctk.CTkButton)
chips = [b for b in btns if b.cget("text") in [m[:2] for m in ff.MESES]]
check(len(chips) >= 12, f"fita com os 12 meses ({len(chips)})")
atual = [b for b in chips if b.cget("text_color") == ff.ACCENT]
check(atual, "mês atual destacado na fita")
existentes = [b for b in chips if b.cget("fg_color") == ff.BG_INPUT]
check(len(chips) - len(atual) - len(existentes) > 0,
      "meses inexistentes ficam apagados")

# ── distribuir total ────────────────────────────────────────────────────────
b_div = [b for b in btns if "Dividir" in str(b.cget("text"))]
check(b_div, "botão de dividir total existe")

entries = todos(app, ctk.CTkEntry)
resp_e = [e for e in entries if e.cget("width") == 150]
check(resp_e, "campo de responsável encontrado")
resp_e[0].insert(0, "IT")
# adiciona uma segunda pessoa
b_add = [b for b in btns if "Adicionar pessoa" in str(b.cget("text"))]
b_add[0].invoke()
pump(0.3)
entries = todos(app, ctk.CTkEntry)
resp_e = [e for e in entries if e.cget("width") == 150]
resp_e[1].insert(0, "AB")
pump(0.2)
total_e = [e for e in entries if e.cget("width") == 70]
check(total_e, "campo de total existe")
total_e[0].insert(0, "7")
b_div[0].invoke()
pump(0.4)
qtds = [e.get() for e in todos(app, ctk.CTkEntry) if e.cget("width") == 80]
print("      quantidades após dividir 7 entre 2:", qtds)
check(sorted(qtds[:2]) == ["3", "4"], f"7 dividido em 4 e 3 ({qtds[:2]})")

# ── conferência ─────────────────────────────────────────────────────────────
tabview.set("  Conferir  ")
pump(0.5)
b_conf = [b for b in todos(app, ctk.CTkButton)
          if "CONFERIR" in str(b.cget("text"))]
check(b_conf, "botão CONFERIR existe")
b_conf[0].invoke()
pump(1.5)

labels = [l.cget("text") for l in todos(app, ctk.CTkLabel)]
check(any("Restaurante Bom Prato" in str(l) for l in labels)
      or any("Restaurante Bom Prato" in e.get()
             for e in todos(app, ctk.CTkEntry)),
      "sugestão do .cdr aparece na tela")
b_corr = [b for b in todos(app, ctk.CTkButton)
          if "Corrigir todas" in str(b.cget("text"))]
check(b_corr and b_corr[0].cget("state") == "normal",
      "botão 'Corrigir todas' habilitado com 2 pendências")
check("(2)" in str(b_corr[0].cget("text")),
      f"mostra quantas pendências ({b_corr[0].cget('text')})")

# corrige todas: abre a revisão, depois aplica
b_corr[0].invoke()
pump(0.6)
rev = [w for w in app.winfo_children() if isinstance(w, ctk.CTkToplevel)][-1]
b_ap = [b for b in todos(rev, ctk.CTkButton) if "Aplicar" in str(b.cget("text"))]
check(b_ap and "Aplicar 2 correções" in b_ap[0].cget("text"),
      f"revisão lista as 2 antes de aplicar ({b_ap[0].cget('text')})")
check(os.path.isdir(os.path.join(destino, f"{mn}0003AB - Vazio")),
      "nada é renomeado antes de aplicar")
b_ap[0].invoke()
pump(1.5)
nomes_disco = os.listdir(destino)
print("      pastas após corrigir:", nomes_disco)
check(any("Restaurante Bom Prato" in n for n in nomes_disco),
      "pasta renomeada no disco com o nome do .cdr")
check(any("Oficina do João" in n for n in nomes_disco),
      "a segunda também foi corrigida")
check(not any(n.endswith("- Vazio") and n.startswith(f"{mn}0003")
              for n in nomes_disco), "não sobrou como 'Vazio'")

# ── relatório em tabela ─────────────────────────────────────────────────────
tabview.set("  Relatório  ")
pump(0.5)
b_rel = [b for b in todos(app, ctk.CTkButton)
         if "RELATÓRIO" in str(b.cget("text"))]
b_rel[0].invoke()
pump(1.5)
b_csv = [b for b in todos(app, ctk.CTkButton)
         if "CSV" in str(b.cget("text"))]
check(b_csv and b_csv[0].cget("state") == "normal",
      "exportar CSV fica disponível após gerar")
cabecalhos = [b for b in todos(app, ctk.CTkButton)
              if str(b.cget("text")).startswith(("CÓDIGO", "CLIENTE", "RESP"))]
check(len(cabecalhos) >= 3, f"tabela com colunas clicáveis ({len(cabecalhos)})")

app.destroy()

# ── histórico foi registrado pela criação? (simula) ─────────────────────────
ff.registrar_lote(g["name"], ano, mes, [("IT", 4), ("AB", 3)])
s = ff.sugestoes_de_pessoas(g["name"])
check([p for p, _q, _n in s] == ["IT", "AB"], "histórico sugere as pessoas")

# ── assistente e ocultação ──────────────────────────────────────────────────
tmp2 = tempfile.mkdtemp(prefix="ff_f3b_")
ff.CONFIG_FILE = os.path.join(tmp2, "cfg.json")
ff.INDEX_FILE = os.path.join(tmp2, "idx.json")
app2 = ff.App()
app2.update()
pump = lambda s=0.3: [app2.update() or time.sleep(0.01)
                      for _ in range(int(s / 0.01))]
pump(0.9)
tops = [w for w in app2.winfo_children() if isinstance(w, ctk.CTkToplevel)]
check(tops, "assistente abre na primeira execução")
wiz = tops[0]
lbls = [l.cget("text") for l in todos(wiz, ctk.CTkLabel)]
check(any("OneDrive" in str(l) for l in lbls), "1º passo pergunta do OneDrive")

# responde "não uso Trello" e conclui
app2._finaliza(wiz, {"onedrive": False, "trello": False,
                     "modelo": None, "base": ""})
pump(0.5)
check(app2.config_data["onboarding_ok"], "assistente marca que já rodou")
check(app2.usa("trello") is False, "app sabe que não usa Trello")
check(app2.usa("onedrive") is False, "app sabe que não usa OneDrive")
check(not app2._watcher_chip.winfo_ismapped(),
      "chip do watcher some para quem não usa Trello")
check(ff.group_trello_ok(app2.config_data, {"board_id": "X"}) is False,
      "integração Trello fica desligada por completo")
app2.destroy()

# ── bug #6: prefixo do grupo no regex ───────────────────────────────────────
gml = ff.preset_marketplace_groups()[1]        # prefixo "A"
r = ff.codigo_re_do_grupo(gml)
check(r.match("A090001IT - Cliente"), "regex do ML aceita prefixo A")
gx = dict(gml, prefix="ZZ")
check(ff.codigo_re_do_grupo(gx).match("ZZ090001IT - Cliente"),
      "prefixo personalizado agora é reconhecido (antes ficava invisível)")

shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(tmp2, ignore_errors=True)
print(f"\n{ok} verificações passaram. FASE 3 OK")
