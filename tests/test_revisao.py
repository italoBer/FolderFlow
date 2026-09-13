# -*- coding: utf-8 -*-
"""Correções da revisão geral: Trello sem código duplicado, nome provisório
em todo lugar, watcher que tenta de novo, índice seguro, busca sem acento,
Renomear procurando nos outros grupos, número repetido, dicas visíveis."""
import os
import sys
import json
import time
import shutil
import tempfile
import datetime
import threading

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


tmp = tempfile.mkdtemp(prefix="ff_rev_")

# ── Trello: nunca duplica o código ──────────────────────────────────────────
check(ff.titulo_card("090004AB", "Restaurante") == "090004AB - Restaurante",
      "card sem código recebe o código na frente (como na v1)")
check(ff.titulo_card("090004AB", "090004AB - Restaurante") is None,
      "card que já tem o código não vira '090004AB - 090004AB - …'")
check(ff.titulo_card("A090004AB", "A090001IT - Outro") is None,
      "card com outro código também não é mexido")

# ── nome provisório do grupo vale na criação e no Conferir ──────────────────
base = os.path.join(tmp, "Loja")
g = ff.default_group("marketplace")
g.update({"name": "Loja", "base_path": base, "dest_pattern": "{ano}/{mes}",
          "provisorios": ["Aguardando"]})
os.makedirs(base)
ff.criar_lote(g, "2026", "09 - SETEMBRO", [("IT", 2)], lambda *a, **k: None, False)
dest = ff.mp_destino(g, "2026", "09 - SETEMBRO")
check(sorted(os.listdir(dest)) == ["090001IT - Aguardando", "090002IT - Aguardando"],
      "lote usa o nome provisório do grupo")
open(os.path.join(dest, "090001IT - Aguardando", "Padaria.cdr"), "w").close()
r = ff.conferir_pastas(g, "2026", "09 - SETEMBRO")
check([i["estado"] for i in r["itens"]] == ["nao_renomeada", "vazia"],
      "Conferir reconhece o nome provisório personalizado")

# ── número repetido ─────────────────────────────────────────────────────────
os.makedirs(os.path.join(dest, "090002AB - Mercado"))
r = ff.conferir_pastas(g, "2026", "09 - SETEMBRO")
check(r["duplicados"] == [["090002AB - Mercado", "090002IT - Aguardando"]],
      f"Conferir acha número repetido ({r['duplicados']})")

# ── índice ──────────────────────────────────────────────────────────────────
idx = {"0001": {"path": r"C:\a\0001 - X", "nome": "0001 - X"},
       "0001\x00C:\\B\\0001 - Y": {"path": r"C:\b\0001 - Y", "nome": "0001 - Y"}}
ff.indice_troca(idx, r"C:\b\0001 - Y", r"C:\b\0001 - Z", "G")
check(idx["0001"]["path"] == r"C:\a\0001 - X"
      and any(v["path"] == r"C:\b\0001 - Z" for v in idx.values())
      and not any(v["path"] == r"C:\b\0001 - Y" for v in idx.values()),
      "renomear troca só a pasta certa no índice (sem apagar outra de mesmo código)")
ff.INDEX_FILE = os.path.join(tmp, "idx.json")
ff.save_index({"A": {"path": "x"}})
check(json.load(open(ff.INDEX_FILE, encoding="utf-8")) == {"A": {"path": "x"}}
      and not os.path.exists(ff.INDEX_FILE + ".tmp"), "índice gravado de forma atômica")

# ── Conferir só mexe no card certo ──────────────────────────────────────────
chamadas = []
ff.trello_update_card_name = lambda cid, nome, k, t: chamadas.append((cid, nome))
cfg_tr = {"trello_key": "k", "trello_token": "t", "usa_trello": True}


def roda_trello(cards, cliente="Restaurante Bom Prato"):
    chamadas.clear()
    ff.trello_search_cards = lambda q, b, k, t: cards
    fake = type("F", (), {"config_data": cfg_tr})()
    antes = set(threading.enumerate())
    ff.App._trello_renomeia_card(fake, {"board_id": "B"}, "090004AB", cliente)
    for th in set(threading.enumerate()) - antes:
        th.join(3)
    return list(chamadas)


check(roda_trello([{"id": "1", "name": "Restaurante Bom Prato"}]) ==
      [("1", "090004AB - Restaurante Bom Prato")], "Conferir: card com o nome exato é atualizado")
check(roda_trello([{"id": "1", "name": "090004AB - Restaurante Bom Prato"}]) == [],
      "Conferir: card que já tem código não é mexido (antes duplicava)")
check(roda_trello([{"id": "2", "name": "Restaurante Bom Prato Filial"}]) == [],
      "Conferir: card só parecido não é mexido (antes podia pegar o card errado)")

# ── app ─────────────────────────────────────────────────────────────────────
ff.CONFIG_FILE = os.path.join(tmp, "cfg.json")
ff.HISTORY_FILE = os.path.join(tmp, "hist.json")
bs = os.path.join(tmp, "Shopee")
bm = os.path.join(tmp, "ML")
gs, gml = ff.preset_marketplace_groups({"shopee_base": bs, "ml_base": bm})
agora = datetime.datetime.now()
mes = ff.MESES[agora.month - 1]
d_s = ff.mp_destino(gs, str(agora.year), mes)
d_m = ff.mp_destino(gml, str(agora.year), mes)
os.makedirs(os.path.join(d_s, f"{mes[:2]}0001IT - João da Silva", "#ENVIAR"))
os.makedirs(os.path.join(d_m, f"A{mes[:2]}0005IT - Vazio", "#ENVIAR"))
cfg = ff.DEFAULT_CONFIG.copy()
cfg.update({"groups": [gs, gml], "onboarding_ok": True, "usa_trello": False,
            "usa_onedrive": False, "trello_key": "k", "trello_token": "t"})
ff.save_config(cfg)
app = ff.App()
app.update()
gs, gml = app.groups()


def pump(s=0.3):
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


def espera(cond, s=6):
    fim = time.time() + s
    while time.time() < fim:
        pump(0.1)
        if cond():
            return True
    return False


# índice automático ao abrir
check(espera(lambda: any("João da Silva" in v.get("nome", "")
                         for v in app.index_data.values()), 10),
      "índice é montado sozinho ao abrir o app")

# busca sem acento
app.show_search()
pump(0.4)
app._busca_campo.insert(0, "joao")
app._busca_campo._entry.event_generate("<KeyRelease>")
lb = [w for w in todos(app.container, __import__("tkinter").Listbox)][0]
check(espera(lambda: any("João da Silva" in lb.get(i) for i in range(lb.size())), 3),
      "Buscar: 'joao' acha 'João da Silva'")
app._busca_campo.delete(0, "end")
app._busca_campo._entry.event_generate("<KeyRelease>")
pump(0.2)
check(lb.size() == 0, "Buscar: apagar o texto limpa os resultados")

# dicas visíveis
app.show_group(gs)
pump(0.3)
app._tabs_grupo.set(app.ABA_REN)
pump(0.5)
aba = app._tabs_grupo.tab(app.ABA_REN)
busca_ren = todos(aba, ctk.CTkEntry)[0]
check(busca_ren._placeholder_text_active, "Renomear: a dica do campo de busca aparece")

# Renomear procura nos outros grupos
busca_ren.insert(0, f"A{mes[:2]}0005IT")
[b for b in todos(aba, ctk.CTkButton) if "Localizar" in str(b.cget("text"))][0].invoke()
check(espera(lambda: any("Abrir no grupo Mercado Livre" in str(b.cget("text"))
                         for b in todos(aba, ctk.CTkButton)), 6),
      "Renomear: não achou na Shopee → oferece abrir no Mercado Livre")
[b for b in todos(aba, ctk.CTkButton)
 if "Abrir no grupo Mercado Livre" in str(b.cget("text"))][0].invoke()
pump(0.5)
aba = app._tabs_grupo.tab(app.ABA_REN)
check(app._crumb.cget("text").endswith("Mercado Livre")
      and espera(lambda: any(f"Selecionada: A{mes[:2]}0005IT - Vazio" in str(l.cget("text"))
                             for l in todos(aba, ctk.CTkLabel)), 6),
      "…e lá já aparece a pasta selecionada")

app._tabs_grupo.set(app.ABA_CRIAR)
pump(0.6)
aba = app._tabs_grupo.tab(app.ABA_CRIAR)
tot = [e for e in todos(aba, ctk.CTkEntry) if e.cget("width") == 70][0]
check(tot._placeholder_text_active, "Criar: a dica 'ex: 100' aparece")

# watcher: pasta que chega atrasada é renomeada depois (antes era esquecida)
cards = [{"id": "c9", "name": f"A{mes[:2]}0009IT - Oficina: Filial/Centro"}]
ff.trello_get_list_cards = lambda lista, k, t: cards
gml["list_dev"] = "DEV"
app._watcher_tick()
pump(0.5)
check("c9" in app._watcher_pendentes and "c9" not in app._watcher_processed,
      "watcher: pasta ainda não existe → fica para tentar de novo")
os.makedirs(os.path.join(d_m, f"A{mes[:2]}0009IT - Vazio"))
app._watcher_pendentes["c9"] = (1, 0)          # já passou dos 5 minutos
app._watcher_tick()
pump(0.8)
check(os.path.isdir(os.path.join(d_m, f"A{mes[:2]}0009IT - Oficina FilialCentro")),
      "watcher: renomeia quando a pasta chega, tirando ':' e '/' do nome")
check(any("Oficina FilialCentro" in l for l, _t in app._watcher_lines),
      "watcher: registro chega na tela pela fila (sem mexer na tela pela thread)")

app.destroy()
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{ok} verificações passaram. REVISÃO OK")
