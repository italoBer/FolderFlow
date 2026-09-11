# -*- coding: utf-8 -*-
"""TreeCanvas isolado: virtualização, hover, expandir/recolher, seleção,
renome, menu de contexto e desempenho com muitos nós."""
import os
import sys
import time
import tempfile

sys.path.insert(0, r"D:\Claude\Teste1")
import folderflow as ff
import customtkinter as ctk
import tkinter as tk

ok = 0


def check(cond, msg):
    global ok
    if cond:
        ok += 1
        print(f"  OK  {msg}")
    else:
        print(f"FALHOU: {msg}")
        sys.exit(1)


ctk.set_appearance_mode("dark")
win = ctk.CTk(fg_color=ff.BG_MAIN)
win.geometry("900x600")

# modelo: 20 raízes × 20 filhos × 12 netos = 5.020 nós
raizes = []
for a in range(20):
    filhos = []
    for b in range(20):
        f = ff.new_node("folder", f"Pasta {a}-{b}")
        f["children"] = [ff.new_node("file", f"arq{c}.txt") for c in range(12)]
        filhos.append(f)
    r = ff.new_node("folder", f"Raiz {a}")
    r["children"] = filhos
    raizes.append(r)

tree = ff.TreeCanvas(win, multi=True)
tree.pack(fill="both", expand=True)
prov = ff.TemplateTreeProvider(raizes)
tree.set_provider(prov)
win.update()


def pump(sec=0.2):
    end = time.time() + sec
    while time.time() < end:
        win.update()
        time.sleep(0.01)


pump(0.4)

# ── 1. Virtualização ────────────────────────────────────────────────────────
check(len(tree.rows()) == 20, "20 raízes visíveis (filhos recolhidos)")
itens_iniciais = len(tree.canvas.find_all())
print(f"      itens de canvas desenhados: {itens_iniciais}")
check(itens_iniciais < 300, "desenha poucos itens, não a árvore toda")

t0 = time.time()
tree.set_all_expanded(True)
pump(0.3)
dt_exp = time.time() - t0
total = len(tree.rows())
print(f"      expandir tudo: {total} linhas em {dt_exp:.2f}s")
check(total == 5220, f"5.220 nós na lista (20 + 400 + 4800) ({total})")
desenhados = len(tree.canvas.find_all())
print(f"      itens desenhados com 5.020 linhas: {desenhados}")
check(desenhados < 400,
      f"virtualização: só o visível é desenhado ({desenhados} itens)")
check(dt_exp < 6.0, f"expandir 5.020 nós é rápido ({dt_exp:.2f}s)")

# ── 2. Rolagem ──────────────────────────────────────────────────────────────
t0 = time.time()
for _ in range(40):
    tree.canvas.yview_scroll(3, "units")
    tree._redraw()
    win.update()
dt_scroll = time.time() - t0
print(f"      40 rolagens: {dt_scroll:.2f}s ({dt_scroll/40*1000:.1f}ms cada)")
check(dt_scroll / 40 < 0.05, "rolagem fluida (<50ms por passo)")

tree.canvas.yview_moveto(0)
tree._redraw()
pump(0.2)

# ── 3. Hover ────────────────────────────────────────────────────────────────
class Ev:
    def __init__(self, x=0, y=0):
        self.x, self.y, self.state = x, y, 0
        self.x_root = self.y_root = 0


tree._on_motion(Ev(50, tree.ROW_H * 3 + 5))
check(tree._hover == 3, f"hover na linha 3 (deu {tree._hover})")
t0 = time.time()
for i in range(200):
    tree._on_motion(Ev(50, tree.ROW_H * (i % 20) + 5))
dt_hover = time.time() - t0
print(f"      200 movimentos de mouse: {dt_hover*1000:.0f}ms "
      f"({dt_hover/200*1000:.2f}ms cada)")
check(dt_hover / 200 < 0.01, "hover é barato (<10ms por movimento)")

# mesma linha não redesenha (saída antecipada)
tree._on_motion(Ev(50, tree.ROW_H * 5 + 5))
h1 = tree._hover
tree._on_motion(Ev(60, tree.ROW_H * 5 + 8))
check(tree._hover == h1, "mover dentro da mesma linha não muda o hover")
tree._on_motion(Ev(50, -100))
check(tree._hover == -1, "sair da árvore limpa o hover")

# ── 4. Recolher/expandir instantâneo ────────────────────────────────────────
tree.set_all_expanded(False)
pump(0.2)
check(len(tree.rows()) == 20, "recolher tudo volta a 20 linhas")
t0 = time.time()
tree.toggle(0)
pump(0.1)
dt_tog = time.time() - t0
check(len(tree.rows()) == 40, "expandir a raiz 0 revela 20 filhos")
check(dt_tog < 0.4, f"expandir uma pasta é instantâneo ({dt_tog*1000:.0f}ms)")
tree.toggle(0)
pump(0.1)
check(len(tree.rows()) == 20, "recolher volta ao estado anterior")

# ── 5. Seleção ──────────────────────────────────────────────────────────────
sels = []
tree.on_select = lambda rows: sels.append(len(rows))
tree.select_key(tree.rows()[2].key)
check(tree.selected_row().label == "Raiz 2", "seleção por chave")
check(sels and sels[-1] == 1, "callback de seleção disparou")

ev = Ev(60, tree.ROW_H * 4 + 5)
tree._on_click(ev)
check(tree.selected_row().label == "Raiz 4", "clique seleciona a linha certa")

ev2 = Ev(60, tree.ROW_H * 6 + 5)
ev2.state = 0x0004          # Ctrl
tree._on_click(ev2)
check(len(tree.selection()) == 2, "Ctrl+clique soma à seleção")

# ── 6. Renome no lugar ──────────────────────────────────────────────────────
renomeados = []


def _ren(row, novo):
    row.payload["name"] = novo
    renomeados.append((row.label, novo))
    tree.reload()


tree.on_rename = _ren
tree.select_key(tree.rows()[1].key)
tree.begin_edit()
pump(0.15)
check(tree.entry.winfo_ismapped(), "campo de edição aparece")
tree.entry.delete(0, "end")
tree.entry.insert(0, "Raiz Renomeada")
tree._commit_edit()
pump(0.2)
check(renomeados and renomeados[-1][1] == "Raiz Renomeada", "renome aplicado")
check(not tree.entry.winfo_ismapped(), "campo some depois de confirmar")
check(tree.rows()[1].label == "Raiz Renomeada", "árvore reflete o novo nome")

# cancelar com Escape não altera
tree.begin_edit(1)
pump(0.1)
tree.entry.delete(0, "end")
tree.entry.insert(0, "NAO DEVE VALER")
tree._cancel_edit()
pump(0.1)
check(tree.rows()[1].label == "Raiz Renomeada", "Escape cancela o renome")

# ── 7. Estado de expansão sobrevive ao reload ───────────────────────────────
tree.toggle(0)
pump(0.1)
antes = len(tree.rows())
tree.reload()
pump(0.1)
check(len(tree.rows()) == antes, "reload preserva o que estava expandido")

# ── 8. Menu de contexto ─────────────────────────────────────────────────────
chamou = []
tree.on_context = lambda row, sel: (chamou.append(row.label if row else None)
                                    or [("Teste", lambda: None, True)])
evr = Ev(60, tree.ROW_H * 2 + 5)
evr.x_root, evr.y_root = 5000, 5000     # fora da tela: não abre visualmente
try:
    tree._on_right(evr)
except Exception:
    pass
check(chamou, "menu de contexto consultou o dono da árvore")

# ── 9. Badge de sequência ───────────────────────────────────────────────────
raizes[0]["repeat"] = "200"
raizes[0]["name"] = "Lote {seq:04d}"
tree.reload()
pump(0.1)
r0 = tree.rows()[0]
check(r0.badge == "×200", f"badge de repetição ({r0.badge})")
check("{seq" not in r0.label, f"token de numeração escondido do usuário ({r0.label})")

# ── 10. Provider de disco ───────────────────────────────────────────────────
tmp = tempfile.mkdtemp(prefix="ff_tree_")
for i in range(5):
    os.makedirs(os.path.join(tmp, f"pasta {i}"))
for i in range(3):
    open(os.path.join(tmp, f"arq {i}.txt"), "w").close()
dp = ff.DiskTreeProvider(tmp)
tree.set_provider(dp)
pump(0.3)
check(len(tree.rows()) == 1, "raiz única quando há base definida")
tree.toggle(0)
pump(0.2)
labels = [r.label for r in tree.rows()[1:]]
check(len(labels) == 8, f"5 pastas + 3 arquivos ({len(labels)})")
check(labels[:5] == [f"pasta {i}" for i in range(5)],
      "pastas vêm antes dos arquivos, em ordem")
check(tree.rows()[1].expandable and not tree.rows()[6].expandable,
      "pasta expande, arquivo não")

win.destroy()
import shutil
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{ok} verificações passaram. TREECANVAS OK")
