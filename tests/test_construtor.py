# -*- coding: utf-8 -*-
"""Construtor novo dentro do app: ações da barra, menu de contexto, renome,
persistência do modelo e ida/volta Visual↔Texto."""
import os
import sys
import time
import tempfile

sys.path.insert(0, r"D:\Claude\Teste1")
import folderflow as ff
import customtkinter as ctk

# nada de diálogo modal travando o teste: responde "sim" automaticamente
ff.messagebox.askyesno = lambda *a, **k: True
ff.messagebox.showinfo = lambda *a, **k: None
ff.messagebox.showwarning = lambda *a, **k: None
ff.messagebox.showerror = lambda *a, **k: (_ for _ in ()).throw(
    AssertionError("showerror inesperado: " + str(a)))

ok = 0


def check(cond, msg):
    global ok
    if cond:
        ok += 1
        print(f"  OK  {msg}")
    else:
        print(f"FALHOU: {msg}")
        sys.exit(1)


tmp = tempfile.mkdtemp(prefix="ff_cons_")
ff.CONFIG_FILE = os.path.join(tmp, "cfg.json")
ff.INDEX_FILE = os.path.join(tmp, "idx.json")
base = os.path.join(tmp, "base")
os.makedirs(base)
cfg = ff.DEFAULT_CONFIG.copy()
g = ff.default_group("template")
g.update({"name": "T", "base_path": base})
cfg["groups"] = [g]
ff.save_config(cfg)

app = ff.App()
app.update()
app.show_group(app.groups()[0])


def pump(s=0.25):
    end = time.time() + s
    while time.time() < end:
        app.update()
        time.sleep(0.01)


pump(0.6)
# o grupo abre na aba Pastas; o construtor mora na aba Modelo
app._tabs_grupo.set(app.ABA_MODELO)
pump(0.6)
modelo_tab = app._tabs_grupo.tab(app.ABA_MODELO)


def achar_tree(w):
    for c in w.winfo_children():
        if isinstance(c, ff.TreeCanvas) and isinstance(
                c.provider, ff.TemplateTreeProvider):
            return c
        r = achar_tree(c)
        if r:
            return r
    return None


def achar_tipo(w, tipo, out=None):
    out = [] if out is None else out
    for c in w.winfo_children():
        if isinstance(c, tipo):
            out.append(c)
        achar_tipo(c, tipo, out)
    return out


tree = achar_tree(app)
check(tree is not None, "árvore encontrada na tela do grupo")
grupo = app.groups()[0]

# ── modelo padrão carregado, já expandido ────────────────────────────────────
labels = [r.label for r in tree.rows()]
print("      linhas:", labels)
raizes = [r.label for r in tree.rows() if r.depth == 0]
check(raizes == ["Clientes Loja 1", "Produtos Loja 2"],
      f"raízes corretas ({raizes})")
check("X" in labels and "Y" in labels and "Z" in labels,
      "abre expandido, mostrando X, Y e Z")
check(any(r.badge == "×10" for r in tree.rows()),
      "badge da sequência aparece na árvore")

# ── recolher e expandir uma pasta ────────────────────────────────────────────
n_exp = len(tree.rows())
tree.toggle(1)                       # recolhe "Produtos Loja 2"
pump(0.2)
check(len(tree.rows()) < n_exp, "recolher esconde os filhos")
tree.toggle(1)
pump(0.2)
check(len(tree.rows()) == n_exp, "expandir traz os filhos de volta")

# ── botão único de recolher/expandir ─────────────────────────────────────────
def achar_botoes(w, out):
    for c in w.winfo_children():
        if isinstance(c, ctk.CTkButton):
            out.append(c)
        achar_botoes(c, out)
    return out


btns = achar_botoes(modelo_tab, [])
colapso = achar_tipo(modelo_tab, ff.IconeRecolher)
check(len(colapso) == 1, f"existe UM botão de recolher/expandir ({len(colapso)})")
check(not [b for b in btns if b.cget("text") == "⌫"],
      "botão 'Limpar tudo' foi removido")

antes = tree.all_expanded()
colapso[0].command()
pump(0.3)
check(tree.all_expanded() != antes, "o botão alterna o estado da árvore")
modo1 = colapso[0].recolher
colapso[0].command()
pump(0.3)
check(colapso[0].recolher != modo1,
      "o ícone muda (setas uma para a outra / de costas)")

# ── ações da barra criam dentro do selecionado ───────────────────────────────
tree.set_all_expanded(False)
pump(0.2)
tree.select_key(tree.rows()[0].key)      # "Clientes Loja 1"
pump(0.1)

add_pasta = [b for b in btns if "Pasta" in str(b.cget("text"))]
check(add_pasta, "botão '+ Pasta' existe na barra do topo")
add_pasta[0].invoke()
pump(0.4)
filhos = grupo_nodes = None
# a nova pasta deve estar DENTRO de "Clientes Loja 1"
modelo = ff.parse_template(app.groups()[0]["template"])
check(any(c["name"] == "Nova pasta" for c in modelo[0]["children"]),
      "'+ Pasta' criou dentro do item selecionado")

# sem seleção → cria na raiz
tree._sel.clear()
tree._redraw()
pump(0.1)
add_pasta[0].invoke()
pump(0.4)
modelo = ff.parse_template(app.groups()[0]["template"])
check(any(n["name"] == "Nova pasta" for n in modelo),
      "sem seleção, '+ Pasta' cria na raiz")

# ── renome pela árvore altera o modelo salvo ─────────────────────────────────
tree.select_key(tree.rows()[0].key)
tree.begin_edit()
pump(0.2)
tree.entry.delete(0, "end")
tree.entry.insert(0, "Clientes Renomeado")
tree._commit_edit()
pump(0.5)
check("Clientes Renomeado" in app.groups()[0]["template"],
      "renome na árvore foi salvo no modelo")

# ── menu de contexto monta itens ─────────────────────────────────────────────
itens = tree.on_context(tree.rows()[0], tree.selection())
rotulos = [i[0] for i in itens if i]
print("      menu (pasta):", [r.split()[0] for r in rotulos])
check(any("Renomear" in r for r in rotulos), "menu tem Renomear")
check(any("Duplicar" in r for r in rotulos), "menu tem Duplicar")
check(any("Excluir" in r for r in rotulos), "menu tem Excluir")
check(any("Nova pasta dentro" in r for r in rotulos),
      "menu de pasta oferece criar dentro")
itens_raiz = tree.on_context(None, [])
check(any("raiz" in i[0] for i in itens_raiz if i),
      "clique direito no vazio oferece criar na raiz")

# ── duplicar ─────────────────────────────────────────────────────────────────
n_antes = len(ff.parse_template(app.groups()[0]["template"]))
tree.select_key(tree.rows()[0].key)
tree.on_action(tree.rows()[0], "duplicate")
pump(0.5)
n_depois = len(ff.parse_template(app.groups()[0]["template"]))
check(n_depois == n_antes + 1, f"duplicar acrescenta um item ({n_antes}→{n_depois})")

# ── excluir ──────────────────────────────────────────────────────────────────
tree.select_key(tree.rows()[0].key)
tree.on_action(tree.rows()[0], "delete")
pump(0.5)
check(len(ff.parse_template(app.groups()[0]["template"])) == n_antes,
      "excluir remove o item")

# ── ida e volta Visual ↔ Texto preserva a estrutura ──────────────────────────
modelo_antes = app.groups()[0]["template"]
seg = [b for b in achar_botoes(app, []) if False]   # segmented não é CTkButton


def achar_seg(w):
    for c in w.winfo_children():
        if isinstance(c, ctk.CTkSegmentedButton):
            return c
        r = achar_seg(c)
        if r:
            return r


sb = achar_seg(app)
check(sb is not None, "chave Visual/Texto encontrada")
sb.set("⌨ Texto")
sb._command("⌨ Texto")
pump(0.5)
sb.set("✦ Visual")
sb._command("✦ Visual")
pump(0.6)
tree2 = achar_tree(app)
check(tree2 is not None, "árvore continua após voltar ao Visual")
depois = ff.parse_template(app.groups()[0]["template"])
antes_p = ff.parse_template(modelo_antes)


def resumo(ns):
    return [(n["type"], n["name"], resumo(n["children"])) for n in ns]


check(resumo(depois) == resumo(antes_p),
      "estrutura idêntica depois de ir ao Texto e voltar")

app.destroy()
print(f"\n{ok} verificações passaram. CONSTRUTOR OK")
