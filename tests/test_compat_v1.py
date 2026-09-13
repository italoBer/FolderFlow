# -*- coding: utf-8 -*-
"""CERTIFICAÇÃO: a 2.0 faz o mesmo que a v1.1.0 que está em produção na Flag.

A versão antiga é tirada do próprio git (tag v1.1.0) e as duas rodam lado a
lado, nas mesmas pastas, e os resultados são comparados:
  1. a config da v1 é lida e migrada sem perder nada (e a v1 ainda lê depois)
  2. os caminhos dos 12 meses são idênticos (Shopee e Mercado Livre)
  3. criar lote: mesmas pastas, mesma numeração, mesmo '#ENVIAR', mesmos pulos
  4. renomear: mesmo nome final e as mesmas chamadas ao Trello
  5. watcher: renomeia as mesmas pastas a partir dos cards
  6. índice: a 2.0 lê o índice da v1, e a v1 lê o da 2.0
  7. atualização: a v1.1.0 instalada vai oferecer a 2.0.0
  8. OneDrive: a opção de pausar vem ligada, como na v1
  9. janela cabe em notebook 1366x768 com escala de 125%
"""
import os
import sys
import json
import time
import types
import shutil
import tempfile
import importlib.util
import subprocess

RAIZ = r"D:\Claude\Teste1"
sys.path.insert(0, RAIZ)
import folderflow as ff
import customtkinter as ctk

ok = 0


def check(cond, msg):
    global ok
    if cond:
        ok += 1
        print(f"  OK  {msg}")
    else:
        print(f"FALHOU: {msg}")
        sys.exit(1)


tmp = tempfile.mkdtemp(prefix="ff_compat_")

# ── a versão de produção, direto do git ─────────────────────────────────────
src_old = subprocess.run(["git", "-C", RAIZ, "show", "v1.1.0:folderflow.py"],
                         capture_output=True).stdout
check(b'APP_VERSION = "1.1.0"' in src_old, "v1.1.0 extraída do git (tag de produção)")
p_old = os.path.join(tmp, "ff_v110.py")
open(p_old, "wb").write(src_old)
spec = importlib.util.spec_from_file_location("ff_v110", p_old)
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)


def arvore(raiz):
    out = []
    for r, ds, fs in os.walk(raiz):
        rel = os.path.relpath(r, raiz)
        out += [os.path.normcase(os.path.join(rel, d)) + os.sep for d in ds]
        out += [os.path.normcase(os.path.join(rel, f)) for f in fs]
    return sorted(out)


def nada(*a, **k):
    return None


# ═══ 1. config da v1 ═══════════════════════════════════════════════════════
dA, dB = os.path.join(tmp, "A"), os.path.join(tmp, "B")    # A = v1, B = 2.0
for d in (dA, dB):
    os.makedirs(os.path.join(d, "Shopee"))
    os.makedirs(os.path.join(d, "ML"))


def cfg_v1(raiz):
    return {
        "shopee_base": os.path.join(raiz, "Shopee"),
        "ml_base": os.path.join(raiz, "ML"),
        "pause_onedrive": True,
        "trello_key": "KEY123", "trello_token": "TOK456",
        "shopee_board_id": "BOARD_S", "ml_board_id": "BOARD_M",
        "shopee_list_aguardando": "AGUARD_S", "ml_list_aguardando": "AGUARD_M",
        "shopee_list_dev_id": "DEV_S", "ml_list_dev_id": "DEV_M",
        "watcher_interval": 45, "github_repo": "italoBer/FolderFlow",
    }


cfg_dir = os.path.join(tmp, "cfg")
os.makedirs(cfg_dir)
ff.CONFIG_FILE = old.CONFIG_FILE = os.path.join(cfg_dir, "folderflow_config.json")
ff.INDEX_FILE = old.INDEX_FILE = os.path.join(cfg_dir, "folderflow_index.json")
ff.HISTORY_FILE = os.path.join(cfg_dir, "folderflow_history.json")
json.dump(cfg_v1(dB), open(ff.CONFIG_FILE, "w", encoding="utf-8"), indent=2)

novo = ff.load_config()
gs, gm = novo["groups"]
check((gs["name"], gm["name"]) == ("Shopee", "Mercado Livre"),
      "config v1 vira os grupos Shopee e Mercado Livre")
check(gs["base_path"] == cfg_v1(dB)["shopee_base"]
      and gm["base_path"] == cfg_v1(dB)["ml_base"], "pastas base preservadas")
check((gs["board_id"], gs["list_aguardando"], gs["list_dev"]) ==
      ("BOARD_S", "AGUARD_S", "DEV_S")
      and (gm["board_id"], gm["list_aguardando"], gm["list_dev"]) ==
      ("BOARD_M", "AGUARD_M", "DEV_M"), "Trello: boards e listas preservados")
check((gs["prefix"], gm["prefix"]) == ("", "A"), "prefixo 'A' do Mercado Livre")
check(novo["trello_key"] == "KEY123" and novo["watcher_interval"] == 45
      and novo["pause_onedrive"] is True, "chave, intervalo e pausa preservados")
salvo = json.load(open(ff.CONFIG_FILE, encoding="utf-8"))
check(all(k in salvo for k in cfg_v1(dB)),
      "o arquivo mantém as chaves da v1 (dá para voltar à 1.1.0)")
volta = old.load_config()
check(volta["shopee_base"] == cfg_v1(dB)["shopee_base"]
      and old.trello_configurado(volta), "a v1.1.0 ainda lê a config migrada")

# ═══ 2. caminhos dos 12 meses ═══════════════════════════════════════════════
cA = cfg_v1(dA)
gsA = ff.preset_marketplace_groups(cA)[0]
gmA = ff.preset_marketplace_groups(cA)[1]
iguais = 0
for ano in ("2025", "2026", "2027"):
    for mes in ff.MESES:
        for plat, grp in (("shopee", gsA), ("ml", gmA)):
            _b, dest_old, pref_old = old._paths(plat, ano, mes, cA)
            if (os.path.normcase(dest_old) == os.path.normcase(ff.mp_destino(grp, ano, mes))
                    and pref_old == grp["prefix"]):
                iguais += 1
check(iguais == 72, f"caminho e prefixo idênticos nos 72 casos (3 anos × 12 meses × 2) ({iguais})")

# ═══ 3. criar lote lado a lado ═══════════════════════════════════════════════
gsB, gmB = ff.preset_marketplace_groups(cfg_v1(dB))


def semeia(raiz):
    sh = os.path.join(raiz, "Shopee", "Shopee 2026", "09 - SETEMBRO - SHOPEE")
    # "090013it" (iniciais minúsculas) não entra na contagem do maior número,
    # mas o código existe: as duas versões têm de PULAR o 090013IT
    for n in ("090001IT - Cliente A", "090002IT - Vazio", "090007AB - Loja",
              "12345 - Sistema antigo", "090012IT - Já renomeada",
              "090013it - Iniciais minúsculas"):
        os.makedirs(os.path.join(sh, n, "#ENVIAR"))
    open(os.path.join(sh, "planilha.xlsx"), "w").close()
    ml = os.path.join(raiz, "ML", "ML - 2026", "09 - SETEMBRO")
    os.makedirs(os.path.join(ml, "A090003IT - Vazio", "#ENVIAR"))


semeia(dA)
semeia(dB)
logs_old, logs_new = [], []
cenarios = [
    ("shopee", gsA, gsB, "2026", "09 - SETEMBRO", [("IT", 3), ("AB", 2)]),
    ("shopee", gsA, gsB, "2026", "09 - SETEMBRO", [("IB", 4)]),       # continua
    ("ml", gmA, gmB, "2026", "09 - SETEMBRO", [("IT", 2), ("MK", 1)]),
    ("shopee", gsA, gsB, "2026", "03 - MARÇO", [("IT", 2)]),          # mês novo, com Ç
    ("ml", gmA, gmB, "2027", "01 - JANEIRO", [("AB", 3)]),            # ano novo
]
for plat, _ga, grp_b, ano, mes, itens in cenarios:
    n_old = old.criar_lote(plat, ano, mes, itens, cA,
                           lambda m, **k: logs_old.append(m), False)
    n_new = ff.criar_lote(grp_b, ano, mes, itens,
                          lambda m, **k: logs_new.append(m), False)
    check(n_old == n_new, f"{plat} {mes[:2]}/{ano} {itens}: mesma quantidade ({n_old})")
    check(arvore(dA) == arvore(dB), f"{plat} {mes[:2]}/{ano}: pastas idênticas às da v1.1.0")
pulos_old = [m for m in logs_old if "pulando" in m]
pulos_new = [m for m in logs_new if "pulando" in m]
check(pulos_old == pulos_new and pulos_old,
      f"pula o mesmo código já existente ({pulos_old[0].strip()})")
sh = os.path.join(dB, "Shopee", "Shopee 2026", "09 - SETEMBRO - SHOPEE")
print("      exemplo:", sorted(n for n in os.listdir(sh) if n.startswith("09001"))[:6])
check(os.path.isdir(os.path.join(dB, "Shopee", "Shopee 2026", "03 - MARÇO - SHOPEE",
                                 "030001IT - Vazio", "#ENVIAR")),
      "mês com acento (MARÇO) igual ao da v1")

# ═══ 6. índice (antes da tela, para a tela abrir com ele) ═══════════════════
idx_old = old.build_index(cA["shopee_base"], cA["ml_base"])
old.save_index(idx_old)
lido = ff.load_index()
check(lido == idx_old and "090001IT" in lido, "a 2.0 lê o índice gravado pela v1.1.0")
ff.save_index(ff.build_index([gsB, gmB]))
lido_v1 = old.load_index()
check("090001IT" in lido_v1 and "A090003IT" in lido_v1,
      "a v1.1.0 lê o índice gravado pela 2.0")
check(not any("#ENVIAR" in k for k in lido_v1), "índice sem as pastas #ENVIAR")

# ═══ app da 2.0 com a config da v1 (primeira abertura depois do update) ═════
json.dump(cfg_v1(dB), open(ff.CONFIG_FILE, "w", encoding="utf-8"), indent=2)
ff.messagebox.askyesno = lambda *a, **k: True
ff.messagebox.showinfo = nada
ff.messagebox.showwarning = nada
chamadas = []
card_cliente = {"id": "C1", "name": "Padaria do Zé", "idList": "LX"}
ff.trello_search_cards = lambda q, b, k, t: (chamadas.append(("busca", q, b)),
                                             [card_cliente])[1]
ff.trello_update_card_name = lambda cid, nome, k, t: chamadas.append(("nome", cid, nome))
ff.trello_move_card = lambda cid, lista, k, t: chamadas.append(("mover", cid, lista))

app = ff.App()
app.update()


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


pump(0.8)
check(not [w for w in app.winfo_children() if isinstance(w, ctk.CTkToplevel)],
      "PCs da Flag: abre direto, sem assistente de primeira abertura")
cfg_app = ff.load_config()
check(cfg_app["onboarding_ok"] and cfg_app["usa_trello"] is True
      and cfg_app["usa_onedrive"] is True,
      "Trello e OneDrive continuam ligados para quem já usava")
check(app._watcher_chip.winfo_ismapped(), "botão do watcher aparece no topo")

# ═══ 8. pausa do OneDrive ligada por padrão ═══════════════════════════════
g_shopee = app.groups()[0]
app.show_group(g_shopee)
pump(0.4)
app._tabs_grupo.set(app.ABA_CRIAR)
pump(0.8)
aba = app._tabs_grupo.tab(app.ABA_CRIAR)
sw = [s for s in todos(aba, ctk.CTkSwitch) if "Pausar OneDrive" in s.cget("text")]
check(sw and sw[0].get() == 1,
      "'Pausar OneDrive durante criação' aparece ligado, como na v1.1.0")

# ═══ 4. renomear: mesmo nome e mesmas chamadas ao Trello ═══════════════════
alvo_A = os.path.join(dA, "Shopee", "Shopee 2026", "09 - SETEMBRO - SHOPEE",
                      "090002IT - Vazio")
nome_v1 = os.path.basename(old.renomear_pasta(alvo_A, "Padaria do Zé"))
titulo_v1 = f"{'090002IT'} - {card_cliente['name']}"     # fórmula da v1.1.0

app._tabs_grupo.set(app.ABA_REN)
pump(0.5)
aba = app._tabs_grupo.tab(app.ABA_REN)
ents = todos(aba, ctk.CTkEntry)
ents[0].insert(0, "090002IT")
[b for b in todos(aba, ctk.CTkButton) if "Localizar" in str(b.cget("text"))][0].invoke()
fim = time.time() + 6
while time.time() < fim and not any("Selecionada" in str(l.cget("text"))
                                    for l in todos(aba, ctk.CTkLabel)):
    pump(0.1)
check(any("Selecionada: 090002IT - Vazio" in str(l.cget("text"))
          for l in todos(aba, ctk.CTkLabel)), "localiza a pasta pelo código")
ents[1].insert(0, "Padaria do Zé")
fim = time.time() + 5
while time.time() < fim and not any(str(l.cget("text")).startswith("Card:")
                                    for l in todos(aba, ctk.CTkLabel)):
    pump(0.1)
check(("busca", "Padaria do Zé", "BOARD_S") in chamadas,
      "procura o card pelo nome do cliente no board da Shopee (igual à v1)")
[b for b in todos(aba, ctk.CTkButton) if "RENOMEAR" in str(b.cget("text"))][0].invoke()
fim = time.time() + 5
while time.time() < fim and not any(c[0] == "mover" for c in chamadas):
    pump(0.1)
sh_B = os.path.join(dB, "Shopee", "Shopee 2026", "09 - SETEMBRO - SHOPEE")
check(os.path.isdir(os.path.join(sh_B, nome_v1)),
      f"nome final idêntico ao da v1.1.0 ('{nome_v1}')")
check(("nome", "C1", titulo_v1) in chamadas,
      f"card renomeado com a mesma fórmula da v1 ('{titulo_v1}')")
check(("mover", "C1", "AGUARD_S") in chamadas,
      "card movido para a lista Aguardando da Shopee (igual à v1)")

# ═══ 5. watcher lado a lado ═════════════════════════════════════════════════
for raiz in (dA, dB):
    sh_r = os.path.join(raiz, "Shopee", "Shopee 2026", "09 - SETEMBRO - SHOPEE")
    ml_r = os.path.join(raiz, "ML", "ML - 2026", "09 - SETEMBRO")
    for n in ("090020IT - Vazio", "090021AB - Vazio"):
        os.makedirs(os.path.join(sh_r, n, "#ENVIAR"))
    os.makedirs(os.path.join(ml_r, "A090022IT - Vazio", "#ENVIAR"))

cards = {
    "DEV_S": [{"id": "s1", "name": "090020IT - Restaurante Sabor"},
              {"id": "s2", "name": "090001IT - Cliente A"},       # já renomeada
              {"id": "s3", "name": "Card ainda sem código"},
              {"id": "s4", "name": "090021AB - Mercado Bom"}],
    "DEV_M": [{"id": "m1", "name": "A090022IT - Oficina do João"}],
}
old.trello_get_list_cards = lambda lista, k, t: cards[lista]
ff.trello_get_list_cards = lambda lista, k, t: cards[lista]
fake = types.SimpleNamespace(
    config_data=cA, _watcher_processed=set(), index_data={},
    _watcher_log_append=lambda m, tag="info": None)
old.App._watcher_tick(fake)
app._watcher_tick()
pump(0.8)
check(arvore(dA) == arvore(dB), "watcher: renomeia exatamente as mesmas pastas que a v1.1.0")
check(os.path.isdir(os.path.join(dB, "ML", "ML - 2026", "09 - SETEMBRO",
                                 "A090022IT - Oficina do João")),
      "watcher: Mercado Livre (prefixo A) também")
check(any("Restaurante Sabor" in v.get("nome", "") for v in app.index_data.values()),
      "watcher: pasta renomeada entra no índice")

# ═══ 7. atualização automática ══════════════════════════════════════════════
perguntou = []


class Resposta:
    def __init__(self, dados):
        self.dados = json.dumps(dados).encode()

    def read(self):
        return self.dados

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


release = {"tag_name": "v2.0.0", "assets": [
    {"name": "FolderFlow.exe",
     "browser_download_url": "https://github.com/italoBer/FolderFlow/releases/download/v2.0.0/FolderFlow.exe"}]}
old.urllib.request.urlopen = lambda req, timeout=0: Resposta(release)
old.messagebox.askyesno = lambda titulo, msg: (perguntou.append(msg), False)[1]
raiz_falsa = types.SimpleNamespace(after=lambda ms, fn: fn())
old.check_update(cA, raiz_falsa)
check(perguntou and "2.0.0" in perguntou[0],
      "a v1.1.0 instalada na Flag vai oferecer a atualização para a 2.0.0")
check(ff._ver_tuple(ff.APP_VERSION) > ff._ver_tuple("1.1.0"), "2.0.0 é mais nova que 1.1.0")
perguntou.clear()
ff.urllib.request.urlopen = lambda req, timeout=0: Resposta(release)
ff.messagebox.askyesno = lambda titulo, msg: (perguntou.append(msg), False)[1]
ff.check_update({"github_repo": "italoBer/FolderFlow"}, raiz_falsa)
check(not perguntou, "depois de atualizada, a 2.0 não pede para atualizar de novo")
release["tag_name"] = "v1.1.0"
ff.check_update({"github_repo": "italoBer/FolderFlow"}, raiz_falsa)
check(not perguntou, "e nunca volta para a 1.1.0 (sem downgrade)")

# ═══ 9. janela cabe na tela ══════════════════════════════════════════════════
w, h, mw, mh = ff.tamanho_janela(1366, 768, 1.25)
check(w * 1.25 <= 1366 and h * 1.25 + 90 <= 768 + 1 and mw <= w and mh <= h,
      f"notebook 1366x768 a 125%: janela {w}x{h} cabe inteira")
check(ff.tamanho_janela(1920, 1080, 1.0)[:2] == (1120, 740), "monitor Full HD: tamanho normal")
# aplica também o mínimo daquela tela (senão o mínimo desta máquina,
# 960x640, seguraria a janela maior e o teste não mediria a altura real)
app.minsize(mw, mh)
app.geometry(f"{w}x{h}")
app.update()
check(abs(app.winfo_height() - round(h * ff.ctk.ScalingTracker.get_window_scaling(app)))
      <= 2, f"janela realmente com a altura do notebook ({app.winfo_height()}px)")
app.show_group(app.groups()[0])
pump(0.3)
app._tabs_grupo.set(app.ABA_CRIAR)
pump(1.0)
aba = app._tabs_grupo.tab(app.ABA_CRIAR)
btn = [b for b in todos(aba, ctk.CTkButton) if "CRIAR PASTAS" in str(b.cget("text"))][0]
base_y = app.winfo_rooty() + app.winfo_height()
fundo_btn = btn.winfo_rooty() + btn.winfo_height()
print(f"      botão termina em {fundo_btn - app.winfo_rooty()}px de {app.winfo_height()}px")
check(btn.winfo_ismapped() and fundo_btn <= base_y,
      "na janela pequena o botão CRIAR PASTAS continua visível")

app.destroy()
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{ok} verificações passaram. COMPATÍVEL COM A v1.1.0 DE PRODUÇÃO")
