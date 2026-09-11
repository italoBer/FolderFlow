# -*- coding: utf-8 -*-
"""Fase 2 no app: painel Disco, ações, marcação de existentes e índice."""
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


tmp = tempfile.mkdtemp(prefix="ff_f2_")
ff.CONFIG_FILE = os.path.join(tmp, "cfg.json")
ff.INDEX_FILE = os.path.join(tmp, "idx.json")
base = os.path.join(tmp, "base")
os.makedirs(base)
# conteúdo real no disco
for n in ["Clientes Loja 1", "Zeta"]:
    os.makedirs(os.path.join(base, n))
open(os.path.join(base, "nota.txt"), "w").close()

cfg = ff.DEFAULT_CONFIG.copy()
g = ff.default_group("template")
g.update({"name": "T", "base_path": base})
cfg["groups"] = [g]
ff.save_config(cfg)

app = ff.App()
app.update()
app.show_group(app.groups()[0])


def pump(s=0.3):
    end = time.time() + s
    while time.time() < end:
        app.update()
        time.sleep(0.01)


pump(0.7)


def achar(w, tipo, cond=None):
    for c in w.winfo_children():
        if isinstance(c, tipo) and (cond is None or cond(c)):
            return c
        r = achar(c, tipo, cond)
        if r:
            return r
    return None


def achar_todos(w, tipo, out=None):
    out = [] if out is None else out
    for c in w.winfo_children():
        if isinstance(c, tipo):
            out.append(c)
        achar_todos(c, tipo, out)
    return out


# ── abas iguais para todo grupo ──────────────────────────────────────────────
tabs = app._tabs_grupo
nomes_abas = list(tabs._tab_dict.keys())
print("      abas:", [n.strip() for n in nomes_abas])
check([n.strip() for n in nomes_abas] ==
      ["Pastas", "Modelo", "Renomear", "Conferir", "Relatório"],
      "grupo de estrutura: Pastas · Modelo · Renomear · Conferir · Relatório")
check(tabs.get() == app.ABA_PASTAS, "abre na aba Pastas")

# ── aba Pastas lista o conteúdo real ─────────────────────────────────────────
pump(1.2)          # leitura do disco é em segundo plano
pastas_tab = tabs.tab(app.ABA_PASTAS)
disco = [t for t in achar_todos(pastas_tab, ff.TreeCanvas)
         if isinstance(t.provider, ff.DiskTreeProvider)][0]
labels = [r.label for r in disco.rows()]
print("      disco:", labels)
check(os.path.basename(base) in labels[0], "raiz é a pasta base")
check("Clientes Loja 1" in labels and "Zeta" in labels and "nota.txt" in labels,
      "lista pastas E arquivos reais")
check(labels.index("Clientes Loja 1") < labels.index("nota.txt"),
      "pastas aparecem antes dos arquivos")

# ── criar pasta pelo painel ─────────────────────────────────────────────────
disco.select_key(disco.rows()[0].key)
pump(0.2)
btns = achar_todos(pastas_tab, ctk.CTkButton)
b_nova = [b for b in btns if b.cget("text") == "📁 Nova pasta"]
check(b_nova, "botão de nova pasta existe na aba Pastas")
b_nova[0].invoke()
pump(1.2)
check(os.path.isdir(os.path.join(base, "Nova pasta")),
      "criou a pasta de verdade no disco")
disco._cancel_edit()

# ── renomear individual ─────────────────────────────────────────────────────
alvo = [r for r in disco.rows() if r.label == "Nova pasta"]
check(alvo, "a nova pasta apareceu na árvore")
disco.on_rename(alvo[0], "Pasta Renomeada")
pump(0.8)
check(os.path.isdir(os.path.join(base, "Pasta Renomeada")),
      "renome individual funcionou no disco")

# ── excluir vai para a Lixeira ──────────────────────────────────────────────
alvo = [r for r in disco.rows() if r.label == "Pasta Renomeada"]
disco.select_key(alvo[0].key)
pump(0.2)
b_del = [b for b in btns if b.cget("text") == "🗑"]
b_del[0].invoke()
pump(1.2)
check(not os.path.exists(os.path.join(base, "Pasta Renomeada")),
      "excluir removeu do lugar (foi para a Lixeira)")

# ── menu de contexto do disco ───────────────────────────────────────────────
zeta = [r for r in disco.rows() if r.label == "Zeta"][0]
disco.select_key(zeta.key)
itens = disco.on_context(zeta, disco.selection())
rot = [i[0] for i in itens if i]
check(any("Explorador" in r for r in rot), "menu tem abrir no Explorador")
check(any("conteúdo desta pasta" in r for r in rot),
      "com uma pasta: 'Renomear o conteúdo desta pasta'")
check(any("Lixeira" in r for r in rot), "menu tem mandar para a Lixeira")
check(any("pasta base" in r for r in rot), "menu tem definir como pasta base")
check(any("modelo aqui" in r for r in rot),
      "grupo de estrutura: 'Criar estrutura do modelo aqui'")

# ── renomear em massa com UMA pasta = o que está dentro dela ────────────────
for n in ("vazio 0001", "vazio 0002", "Cliente X"):
    os.makedirs(os.path.join(base, "Zeta", n))
b_massa = [b for b in btns if "Em massa" in str(b.cget("text"))]
b_massa[0].invoke()
pump(0.6)
dlg = [w for w in app.winfo_children()
       if isinstance(w, ctk.CTkToplevel) and w.title() == "Renomear em massa"]
check(dlg, "diálogo de renome em massa abre")
textos = [l.cget("text") for l in achar_todos(dlg[0], ctk.CTkLabel)]
check(any("dentro de" in t and "Zeta" in t and "3 itens" in t for t in textos),
      "renomeia o CONTEÚDO da pasta selecionada (3 itens)")
prevtxt = achar(dlg[0], ff.tk.Text).get("1.0", "end")
check("vazio 0001" in prevtxt and "Cliente X" in prevtxt,
      "prévia lista os itens de dentro")
# 'Só os provisórios' desmarca o que não é 'Vazio'
b_prov = [b for b in achar_todos(dlg[0], ctk.CTkButton)
          if b.cget("text") == "Só os provisórios"]
b_prov[0].invoke()
pump(0.3)
prevtxt = achar(dlg[0], ff.tk.Text).get("1.0", "end")
linha_x = [l for l in prevtxt.splitlines() if "Cliente X" in l][0]
check(linha_x.startswith("☐"), "'Só os provisórios' desmarca 'Cliente X'")
dlg[0].destroy()
pump(0.2)

# ── marcação de "já existe" na prévia (aba Modelo) ──────────────────────────
tabs.set(app.ABA_MODELO)
pump(1.5)
prev = achar(tabs.tab(app.ABA_MODELO), ff.tk.Text,
             lambda t: "guide" in t.tag_names())
check(prev is not None, "painel de prévia encontrado")
check("Clientes Loja 1" in prev.get("1.0", "end"), "prévia mostra o modelo")
marcadas = prev.tag_ranges("existe")
print(f"      linhas marcadas como existentes: {len(marcadas)//2}")
check(len(marcadas) > 0,
      "'Clientes Loja 1' (que existe no disco) foi marcada com ✓")
segs = achar_todos(tabs.tab(app.ABA_MODELO), ctk.CTkSegmentedButton)
check(not [x for x in segs if "Disco" in (x.cget("values") or [])],
      "o alternador Prévia|Disco saiu do Modelo")

app.destroy()

# ── índice agora enxerga pastas genéricas (bug #7) ──────────────────────────
idx = ff.build_index([g])
nomes = {v["nome"] for v in idx.values()}
check("Zeta" in nomes, "pasta sem ' - ' no nome agora é indexada")
check("Clientes Loja 1" in nomes, "pasta comum indexada")

# códigos repetidos em lugares diferentes não se sobrescrevem
b2 = os.path.join(tmp, "base2")
os.makedirs(os.path.join(b2, "Zeta"))
g2 = ff.default_group("template")
g2.update({"name": "T2", "base_path": b2})
idx2 = ff.build_index([g, g2])
zetas = [v for v in idx2.values() if v["nome"] == "Zeta"]
check(len(zetas) == 2, f"duas pastas 'Zeta' coexistem no índice ({len(zetas)})")

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{ok} verificações passaram. FASE 2 OK")
