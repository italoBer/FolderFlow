# -*- coding: utf-8 -*-
"""Etapa C: desfazer, filtro, paleta, atalhos, pendências na home, barra de
status, exportar/importar grupo e o tour guiado."""
import os
import sys
import json
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


class Tecla:
    """Evento falso de Ctrl+tecla (pelo código da tecla, como no Windows)."""
    def __init__(self, letra, shift=False):
        self.keycode = ord(letra) if isinstance(letra, str) else letra
        self.state = 0x0004 | (0x0001 if shift else 0)


tmp = tempfile.mkdtemp(prefix="ff_eC_")

# ── funções de desfazer (sem tela) ──────────────────────────────────────────
d0 = os.path.join(tmp, "d0")
os.makedirs(d0)
for n, t in (("a.txt", "AAA"), ("b.txt", "BBB")):
    with open(os.path.join(d0, n), "w") as f:
        f.write(t)
ff.aplicar_rename(d0, [("a.txt", "b.txt", None), ("b.txt", "a.txt", None)])
ler = lambda n: open(os.path.join(d0, n)).read()
check(ler("a.txt") == "BBB", "troca circular aplicada")
pastas, erro = ff.desfaz_renomes([(os.path.join(d0, "b.txt"), os.path.join(d0, "a.txt")),
                                  (os.path.join(d0, "a.txt"), os.path.join(d0, "b.txt"))])
check(erro is None and ler("a.txt") == "AAA" and ler("b.txt") == "BBB",
      "desfazer a troca circular volta os dois nomes")

dst = os.path.join(tmp, "dst")
os.makedirs(dst)
pares = []
ff.colar_itens([os.path.join(d0, "a.txt")], dst, pares=pares)
check(os.path.isfile(os.path.join(dst, "a.txt")), "colou a cópia")
ff.desfaz_colagem(pares, mover=False)
check(not os.path.exists(os.path.join(dst, "a.txt"))
      and os.path.isfile(os.path.join(d0, "a.txt")),
      "desfazer cópia: a cópia vai para a Lixeira, o original fica")
pares = []
ff.colar_itens([os.path.join(d0, "b.txt")], dst, mover=True, pares=pares)
check(not os.path.exists(os.path.join(d0, "b.txt")), "moveu")
ff.desfaz_colagem(pares, mover=True)
check(os.path.isfile(os.path.join(d0, "b.txt"))
      and not os.path.exists(os.path.join(dst, "b.txt")),
      "desfazer recorte: volta para a pasta de origem")
nova = os.path.join(dst, "Nova pasta")
os.makedirs(os.path.join(nova, "sub"))
_p, erro = ff.desfaz_criacao(nova)
check(erro and os.path.isdir(nova), "não apaga pasta criada que já tem coisa dentro")
shutil.rmtree(os.path.join(nova, "sub"))
_p, erro = ff.desfaz_criacao(nova)
check(erro is None and not os.path.exists(nova), "pasta criada e vazia: desfaz")

# ── sobras de um tour interrompido são limpas ao abrir ──────────────────────
ff.CONFIG_FILE = os.path.join(tmp, "cfg.json")
ff.INDEX_FILE = os.path.join(tmp, "idx.json")
ff.HISTORY_FILE = os.path.join(tmp, "hist.json")
sobra = tempfile.mkdtemp(prefix="FolderFlow tour ")
gt = ff.default_group("template")
gt.update({"name": "Exemplo — sobra", "base_path": sobra, "tour": True,
           "tour_raiz": sobra})

base = os.path.join(tmp, "Base")
for n in ("Cliente 0001", "Cliênte 0002", "Arquivo Morto"):
    os.makedirs(os.path.join(base, n))
with open(os.path.join(base, "Cliente 0001", "arte.pdf"), "wb") as f:
    f.write(b"x" * 1000)
g1 = ff.default_group("template")
g1.update({"name": "Estrutura C", "base_path": base,
           "template": "Nova/\n  sub/\n"})

base_m = os.path.join(tmp, "Loja")
agora = datetime.datetime.now()
gm = ff.preset_marketplace_groups()[0]
gm.update({"name": "Loja C", "base_path": base_m, "dest_pattern": "{ano}/{mes}",
           "board_id": ""})
mes = ff.MESES[agora.month - 1]
dest = ff.mp_destino(gm, str(agora.year), mes)
p = os.path.join(dest, f"{mes[:2]}0001AB - Vazio")
os.makedirs(os.path.join(p, "#ENVIAR"))
open(os.path.join(p, "Padaria Central.cdr"), "w").close()

cfg = ff.DEFAULT_CONFIG.copy()
cfg.update({"groups": [gt, g1, gm], "onboarding_ok": True, "usa_trello": False,
            "usa_onedrive": False})
ff.save_config(cfg)

app = ff.App()
app.geometry("1120x740")
app.update()
check(all(not x.get("tour") for x in app.groups()) and not os.path.exists(sobra),
      "grupo de tour que sobrou é tirado da config e a pasta temporária apagada")


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


def espera(cond, s=6):
    fim = time.time() + s
    while time.time() < fim:
        pump(0.1)
        if cond():
            return True
    return False


g1, gm = app.groups()

# ── pendências no card da home ──────────────────────────────────────────────
app.show_home()
card = None
espera(lambda: app.alvo(f"card_{gm['id']}") is not None, 2)
card = app.alvo(f"card_{gm['id']}")
achou = espera(lambda: "1 para corrigir" in card.pendencias.cget("text"))
print("      card:", repr(card.pendencias.cget("text")))
check(achou, "card do marketplace mostra '1 para corrigir'")
check(app.alvo(f"card_{g1['id']}").pendencias.cget("text") == "",
      "grupo sem pendência não mostra nada")
card.pendencias._label.event_generate("<Button-1>")
pump(1.0)
check(app._tabs_grupo.get() == app.ABA_CONF, "clicar na pendência abre o Conferir")
check(app._tabs_grupo.tab(app.ABA_CONF).winfo_ismapped()
      and not app._tabs_grupo.tab(app.ABA_PASTAS).winfo_ismapped(),
      "a aba Conferir aparece de verdade (não fica em branco)")

# ── paleta (Ctrl+K) ─────────────────────────────────────────────────────────
app.index_data = {"090007IT": {"nome": "090007IT - Padaria Estrela",
                               "path": tmp, "codigo": "090007IT"}}
app._atalho_global(Tecla("K"))
pump(0.4)
pal = app._paleta
check(pal is not None and pal.winfo_exists(), "Ctrl+K abre a paleta")
pal.paleta["digita"]("estrutura c")
pump(0.2)
res = pal.paleta["resultados"]()
check(res and "Ir para: Estrutura C" in res[0], f"acha o grupo ({res[:2]})")
pal.paleta["digita"]("0900 padária")
pump(0.2)
res = pal.paleta["resultados"]()
check(any("090007IT - Padaria Estrela" in r for r in res),
      "acha pasta do índice pelo código + nome, sem ligar para acento")
pal.paleta["digita"]("estrutura c")
pump(0.2)
pal.paleta["executa"]()
pump(0.8)
check(app._crumb.cget("text").endswith("Estrutura C") and app._paleta is None,
      "Enter abre o grupo e fecha a paleta")

# ── atalhos ─────────────────────────────────────────────────────────────────
app._atalho_global(Tecla("3"))
pump(0.5)
check(app._tabs_grupo.get() == list(app._tabs_grupo._tab_dict)[2],
      "Ctrl+3 troca para a 3ª aba")
check(app.bind("<Alt-Left>") and app.bind("<F1>"), "Alt+← e F1 ligados")
w_at = app.open_atalhos()
pump(0.3)
check(any("Ctrl+K" == l.cget("text") for l in todos(w_at, ctk.CTkLabel)),
      "tela de atalhos lista o Ctrl+K")
w_at.destroy()

# ── aba Pastas: barra de status, filtro e desfazer ──────────────────────────
app._atalho_global(Tecla("1"))
pump(1.0)
d = todos(app._tabs_grupo.tab(app.ABA_PASTAS), ff.TreeCanvas)[0]
espera(lambda: len(d.rows()) >= 4, 3)
status = app.alvo("pastas_status")
check(espera(lambda: "3 itens" in status.cget("text"), 2),
      f"sem seleção: quantidade e pasta base ({status.cget('text')!r})")
d._expanded.add(os.path.normcase(os.path.abspath(os.path.join(base, "Cliente 0001"))))
d.reload()
espera(lambda: any(r.label == "arte.pdf" for r in d.rows()), 3)
arte = [r for r in d.rows() if r.label == "arte.pdf"][0]
d.select_key(arte.key)
pump(0.2)
check("1000 B" in status.cget("text") or ff.fmt_tamanho(1000) in status.cget("text"),
      f"arquivo selecionado mostra o tamanho ({status.cget('text')!r})")
pasta1 = [r for r in d.rows() if r.label == "Cliente 0001"][0]
d.select_key(pasta1.key)
check(espera(lambda: ff.fmt_tamanho(1000) in status.cget("text"), 3),
      "pasta selecionada: tamanho calculado em segundo plano")

d.set_filtro("CLIENTE 00")
nomes = [r.label for r in d.rows()]
check("Cliente 0001" in nomes and "Cliênte 0002" in nomes
      and "Arquivo Morto" not in nomes and d.n_encontrados == 2,
      f"filtro sem acento/caixa mostra só os que batem ({nomes})")
check(nomes[0] == "Base", "a pasta de cima continua aparecendo")
d.set_filtro("")
check(any(r.label == "Arquivo Morto" for r in d.rows()), "limpar o filtro restaura")

# F2 + Ctrl+Z
morto = [r for r in d.rows() if r.label == "Arquivo Morto"][0]
d.on_rename(morto, "Arquivo Vivo")
pump(0.6)
check(os.path.isdir(os.path.join(base, "Arquivo Vivo")), "renomeou")
check("Arquivo Morto" in (app.proximo_desfazer() or ""), "desfazer sabe o que fazer")
d._on_ctrl_key(Tecla("Z"))
pump(0.8)
check(os.path.isdir(os.path.join(base, "Arquivo Morto"))
      and not os.path.exists(os.path.join(base, "Arquivo Vivo")),
      "Ctrl+Z volta o nome")
check(espera(lambda: any(r.label == "Arquivo Morto" for r in d.rows()), 3),
      "a árvore mostra o nome antigo de novo")

# Ctrl+N + Ctrl+Z
d.select_key(d.rows()[0].key)
d._on_ctrl_key(Tecla("N"))
pump(0.8)
d._cancel_edit()
check(os.path.isdir(os.path.join(base, "Nova pasta")), "Ctrl+N criou")
d._on_ctrl_key(Tecla("Z"))
pump(0.6)
check(not os.path.exists(os.path.join(base, "Nova pasta")),
      "Ctrl+Z tira a pasta recém-criada")

# ── Modelo: Ctrl+Z ──────────────────────────────────────────────────────────
app._tabs_grupo.set(app.ABA_MODELO)
pump(1.0)
tm = todos(app._tabs_grupo.tab(app.ABA_MODELO), ff.TreeCanvas)[0]
antes = g1["template"]
tm._sel.clear()
tm._on_ctrl_key(Tecla("N"))
pump(0.8)
check(g1["template"] != antes, "nova pasta no modelo")
tm._cancel_edit()
tm._on_ctrl_key(Tecla("Z"))
pump(0.6)
check(g1["template"] == antes, "Ctrl+Z no modelo volta como estava")
tm.set_filtro("sub")
check([r.label for r in tm.rows()] == ["Nova", "sub"],
      "filtro do modelo procura também no que está fechado")
tm.set_filtro("")

# ── exportar / importar ─────────────────────────────────────────────────────
arq = os.path.join(tmp, "grupo.json")
app.exportar_grupo(g1, caminho=arq)
dados = json.load(open(arq, encoding="utf-8"))
check(dados["folderflow_grupo"] == 1 and dados["grupo"]["template"] == g1["template"],
      "exportou o grupo com o modelo")
gi = app.importar_grupo(arq)
pump(0.5)
check(gi["name"] == "Estrutura C (importado)" and gi["id"] != g1["id"]
      and gi in app.groups(), "importar: nome '(importado)' e identidade nova")
dados["grupo"]["base_path"] = r"Z:\nao\existe"
json.dump(dados, open(arq, "w", encoding="utf-8"))
ff.filedialog.askdirectory = lambda **k: ""
gi2 = app.importar_grupo(arq)
check(gi2["base_path"] == "" and gi2["name"] == "Estrutura C (importado 2)",
      "pasta base que não existe neste PC fica em branco")
app.config_data["groups"] = [g1, gm]
app.save()

# ── menu do ⓘ ───────────────────────────────────────────────────────────────
check(app._btn_info.cget("command") is not None, "ⓘ tem ação (menu)")

# ── tour ────────────────────────────────────────────────────────────────────
app.show_home()
pump(0.5)
app.deiconify()
app.lift()
app.focus_force()
tour = app.iniciar_tour()
pump(0.6)
raiz = tour.raiz
check(os.path.isdir(raiz) and sum(1 for x in app.groups() if x.get("tour")) == 2,
      "tour cria os 2 grupos de exemplo na pasta temporária")
titulos, com_moldura = [], 0
for i in range(len(tour._roteiro)):
    pump(0.9)
    check(tour._balao.winfo_ismapped(), f"passo {i + 1}: balão visível")
    titulos.append(tour._lbl_titulo.cget("text"))
    if tour._barras[0].winfo_ismapped():
        com_moldura += 1
    if i == 8:
        conf = app._tabs_grupo.tab(app.ABA_CONF)
        espera(lambda: any("Restaurante Bom Prato" in e.get()
                           for e in todos(conf, ctk.CTkEntry)), 4)
        check(any("Restaurante Bom Prato" in e.get()
                  for e in todos(conf, ctk.CTkEntry)),
              "Conferir rodou sozinho no exemplo e sugeriu o nome pelo .cdr")
    tour.avancar()
print("      passos:", titulos)
print(f"      com moldura: {com_moldura} de {len(titulos)}")
check(len(titulos) == 12 and len(set(titulos)) == 12, "12 passos diferentes")
check(com_moldura == 12, "a moldura verde aparece em todos os passos")
pump(0.5)
check(not tour.ativo and not os.path.exists(raiz)
      and not any(x.get("tour") for x in app.groups()),
      "no fim: grupos de exemplo e pasta temporária apagados")
check(not any(x.get("tour") for x in ff.load_config()["groups"]),
      "config salva sem os grupos de exemplo")
check(app._crumb.cget("text").endswith("Início"), "volta para o início")

# pular no meio também limpa
tour = app.iniciar_tour()
pump(0.5)
raiz = tour.raiz
tour.ir_para(4)
pump(0.6)
tour.terminar()
pump(0.3)
check(not os.path.exists(raiz) and not any(x.get("tour") for x in app.groups()),
      "Pular no meio também apaga tudo")

app.destroy()
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{ok} verificações passaram. ETAPA C OK")
