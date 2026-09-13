# -*- coding: utf-8 -*-
"""Etapa B1: releitura automática do disco sem piscar."""
import os
import sys
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


tmp = tempfile.mkdtemp(prefix="ff_eB1_")

# ── provedor sem tela: refresh só troca o que mudou ─────────────────────────
b0 = os.path.join(tmp, "p0")
os.makedirs(os.path.join(b0, "a"))
avisos = []
dp = ff.DiskTreeProvider(b0, on_ready=lambda p: avisos.append(p))
raiz = dp.roots()[0]
check([r.label for r in dp.children(raiz)] == ["a"], "lê a pasta")
dp.refresh()
check(avisos == [], "nada mudou: não avisa a tela (nada é redesenhado)")
os.makedirs(os.path.join(b0, "b"))
dp.refresh()
check(avisos and [r.label for r in dp.children(raiz)] == ["a", "b"],
      "pasta nova aparece no refresh")
dp.children(dp.children(raiz)[0])             # lê 'a'
os.rmdir(os.path.join(b0, "a"))
dp.refresh()
check([r.label for r in dp.children(raiz)] == ["b"], "pasta apagada some")
check(dp._key(os.path.join(b0, "a")) not in dp._cache,
      "cache da pasta apagada é esquecido")

# ── no app ──────────────────────────────────────────────────────────────────
ff.CONFIG_FILE = os.path.join(tmp, "cfg.json")
ff.INDEX_FILE = os.path.join(tmp, "idx.json")
ff.HISTORY_FILE = os.path.join(tmp, "hist.json")
ff.messagebox.askyesno = lambda *a, **k: True
base = os.path.join(tmp, "Base")
for i in range(1, 61):
    os.makedirs(os.path.join(base, f"{i:03d} - cliente"))
g = ff.default_group("template")
g.update({"name": "B1", "base_path": base})
cfg = ff.DEFAULT_CONFIG.copy()
cfg.update({"groups": [g], "onboarding_ok": True, "usa_trello": False})
ff.save_config(cfg)

app = ff.App()
app.geometry("900x520")
app.update()
app.show_group(app.groups()[0])

piscou = [False]


def pump(s=0.3, tree=None):
    end = time.time() + s
    while time.time() < end:
        app.update()
        if tree is not None and any(r.state == "loading" for r in tree.rows()):
            piscou[0] = True
        time.sleep(0.01)


def trees(w, out):
    for c in w.winfo_children():
        if isinstance(c, ff.TreeCanvas):
            out.append(c)
        trees(c, out)
    return out


pump(1.0)
d = trees(app._tabs_grupo.tab(app.ABA_PASTAS), [])[0]
app.focus_force()
pump(0.5, d)
check(len(d.rows()) == 61, f"base aberta com 60 pastas ({len(d.rows())})")

# pasta criada por fora aparece sozinha, sem 'carregando…'
piscou[0] = False
os.makedirs(os.path.join(base, "999 - de fora"))
t0 = time.time()
achou = False
while time.time() - t0 < 7:
    pump(0.1, d)
    if any(r.label == "999 - de fora" for r in d.rows()):
        achou = True
        break
print(f"      apareceu em {time.time() - t0:.1f}s")
check(achou, "pasta criada pelo Explorador aparece sozinha")
check(not piscou[0], "nenhum 'carregando…' piscou na releitura")

# âncora: rola até o meio; item novo no topo não empurra a vista
d.canvas.yview_moveto(0.5)
d._redraw()
pump(0.2)
topo_antes = d._flat[int(d.canvas.canvasy(0) // d.ROW_H)].key
os.makedirs(os.path.join(base, "000 - no topo"))
t0 = time.time()
while time.time() - t0 < 7:
    pump(0.1, d)
    if any(r.label == "000 - no topo" for r in d.rows()):
        break
topo_depois = d._flat[int(d.canvas.canvasy(0) // d.ROW_H)].key
check(topo_antes == topo_depois, "item novo acima não empurrou a vista")

# F2: nada é relido enquanto digita
d.select_key(d.rows()[5].key)
d.begin_edit()
d.entry.delete(0, "end")
d.entry.insert(0, "digitando...")
os.makedirs(os.path.join(base, "555 - durante F2"))
pump(4.5)
check(d._edit_idx >= 0 and d.entry.get() == "digitando...",
      "releitura não apagou o que estava sendo digitado")
check(not any(r.label == "555 - durante F2" for r in d.rows()),
      "linhas não mudaram durante o F2")
d._cancel_edit()
t0 = time.time()
while time.time() - t0 < 7:
    pump(0.1)
    if any(r.label == "555 - durante F2" for r in d.rows()):
        break
check(any(r.label == "555 - durante F2" for r in d.rows()),
      "depois do F2 a pasta aparece")

# OneDrive lento: a tela não trava
prov = d.provider
ler_orig = prov._ler


def ler_lento(p):
    time.sleep(1.5)
    return ler_orig(p)


prov._ler = ler_lento
os.makedirs(os.path.join(base, "777 - lento"))
pior = 0.0
t0 = time.time()
while time.time() - t0 < 7:
    a = time.perf_counter()
    app.update()
    pior = max(pior, time.perf_counter() - a)
    if any(r.label == "777 - lento" for r in d.rows()):
        break
    time.sleep(0.01)
prov._ler = ler_orig
print(f"      maior travada da tela: {pior * 1000:.0f} ms")
check(any(r.label == "777 - lento" for r in d.rows()), "leitura lenta chega")
check(pior < 0.15, "leitura lenta não trava a tela")

# ação do próprio app: nova pasta aparece e já entra em edição
app._tabs_grupo.set(app.ABA_PASTAS)
d.select_key(d.rows()[0].key)
n_antes = len(d.rows())
# chama o mesmo atalho que o Ctrl+N aciona (sem depender de a janela do
# teste estar com o foco do teclado, que falhava de vez em quando na suíte)
d.on_shortcut("new", False)
pump(1.0)
check(len(d.rows()) == n_antes + 1 and d._edit_idx >= 0,
      "Ctrl+N cria a pasta e já abre o F2")
d.entry.delete(0, "end")
d.entry.insert(0, "Renomeada")
d._commit_edit()
pump(1.0)
sel = d.selected_row()
check(sel is not None and sel.label == "Renomeada",
      "renomeada e continua selecionada")

# janela minimizada: vigia parado
app.iconify()
pump(0.3)
os.makedirs(os.path.join(base, "888 - minimizado"))
pump(4.5)
check(not any(r.label == "888 - minimizado" for r in d.rows()),
      "minimizado: não relê")
app.deiconify()
app.focus_force()
t0 = time.time()
while time.time() - t0 < 7:
    pump(0.1)
    if any(r.label == "888 - minimizado" for r in d.rows()):
        break
check(any(r.label == "888 - minimizado" for r in d.rows()),
      "ao voltar, relê")

app.destroy()
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{ok} verificações passaram. ETAPA B1 OK")
