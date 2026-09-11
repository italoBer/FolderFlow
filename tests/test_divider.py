# -*- coding: utf-8 -*-
"""Divisor arrastável: ghost no arraste, layout só ao soltar, proporção salva,
limites, duplo clique e restauração.

Nota: eventos sintéticos do Tk saem com timestamp 0, então dois <Button-1>
seguidos viram um duplo clique. Por isso passamos `time=` crescente quando
queremos cliques distintos — e omitimos quando queremos testar o duplo clique.
"""
import os
import sys
import time as _time
import tempfile
import tkinter as tk

sys.path.insert(0, r"D:\Claude\Teste1")
import folderflow as ff

tmp = tempfile.mkdtemp(prefix="ff_div_")
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

_clock = [10000]


def tick(step=2000):
    _clock[0] += step
    return _clock[0]


def pump(sec=0.3):
    end = _time.time() + sec
    while _time.time() < end:
        app.update()
        _time.sleep(0.01)


def find_div(w):
    for c in w.winfo_children():
        try:
            if (c.__class__ is tk.Frame and c.cget("cursor") == "sb_h_double_arrow"
                    and c.winfo_width() <= 20 and c.winfo_height() > 100
                    and c.winfo_children()):
                return c
        except Exception:
            pass
        r = find_div(c)
        if r:
            return r
    return None


def ghosts_in(_body_w=None):
    """A linha-guia é um Toplevel próprio (para o Windows repintar sozinho
    e não deixar rastro sobre os painéis)."""
    out = []
    for c in app.winfo_children():
        if isinstance(c, tk.Toplevel):
            try:
                if c.cget("bg") == ff.ACCENT:
                    out.append(c)
            except Exception:
                pass
    return out


def ghost_local_x(gh, body_w):
    return gh.winfo_rootx() - body_w.winfo_rootx()


def warp_to(body_w, local_x, y=200):
    """Move o ponteiro e devolve o x local REALMENTE alcançado.
    (a janela tem borda invisível no Win11, então o warp não é exato —
    o teste compara contra o ponteiro real, não contra o alvo pedido)"""
    app.event_generate("<Motion>", warp=True,
                       x=body_w.winfo_rootx() - app.winfo_rootx() + local_x,
                       y=y)
    app.update()
    return body_w.winfo_pointerx() - body_w.winfo_rootx()


def drag_to(div_w, body_w, local_x):
    """press → move → release, com timestamps distintos."""
    div_w.event_generate("<Button-1>", x=7, y=200, time=tick())
    pump(0.12)
    n1 = len(ghosts_in(body_w))
    warp_to(body_w, local_x)
    div_w.event_generate("<B1-Motion>", x=7, y=200, time=tick(50))
    pump(0.12)
    gg = ghosts_in(body_w)
    print(f"    [drag→{local_x}] ghost após press={n1} "
          f"x_durante={ghost_local_x(gg[0], body_w) if gg else '—'}")
    div_w.event_generate("<ButtonRelease-1>", x=7, y=200, time=tick(50))
    pump(0.3)


pump(0.6)
div = find_div(app)
assert div is not None, "divisor não encontrado"
body = div.master
w = body.winfo_width()
print(f"divisor achado — x={div.winfo_x()}  corpo={w}px")

col0 = body.grid_columnconfigure(0)["weight"]
print(f"peso inicial da esquerda: {col0}")

# ── press cria a linha-guia ──
div.event_generate("<Button-1>", x=7, y=200, time=tick())
pump(0.15)
gs = ghosts_in(body)
assert len(gs) == 1, f"linha-guia deveria existir (achei {len(gs)})"
print("press: linha-guia criada  OK")

# ── arraste: ghost segue o mouse e os painéis NÃO são recalculados ──
alvo = int(w * 0.35)
real = warp_to(body, alvo)
div.event_generate("<B1-Motion>", x=7, y=200, time=tick(50))
pump(0.15)
gx = ghost_local_x(gs[0], body)
print(f"ghost seguiu o mouse: ghost_x={gx}  ponteiro_x={real}")
assert abs(gx - real) <= 2, (gx, real)
assert body.grid_columnconfigure(0)["weight"] == col0, \
    "painéis recalculados durante o arraste (deveria ser só ao soltar)"
print("durante o arraste: painéis intactos (sem re-layout por pixel)  OK")

# ── release aplica e salva ──
div.event_generate("<ButtonRelease-1>", x=7, y=200, time=tick(50))
pump(0.35)
assert not ghosts_in(body), "linha-guia deveria sumir ao soltar"
print(f"pesos ao soltar: esquerda={body.grid_columnconfigure(0)['weight']} "
      f"direita={body.grid_columnconfigure(2)['weight']}")
r = app.config_data.get("split_ratio")   # gravação em disco é debounced
print("proporção aplicada:", r)
assert r and 0.33 <= r <= 0.37, r

# a gravação é adiada (500ms) para o soltar não engasgar no disco
pump(0.9)
assert ff.load_config().get("split_ratio") == r, "não persistiu em disco"
print("persistiu em disco após o debounce  OK")

# ── limite mínimo ──
drag_to(div, body, 5)
r = app.config_data.get("split_ratio")   # gravação em disco é debounced
print("arrastando ao extremo esquerdo →", r)
assert 0.31 <= r <= 0.33, f"clamp mínimo falhou: {r}"

# ── limite máximo ──
drag_to(div, body, w - 5)
r = app.config_data.get("split_ratio")   # gravação em disco é debounced
print("arrastando ao extremo direito  →", r)
assert 0.73 <= r <= 0.75, f"clamp máximo falhou: {r}"

# ── duplo clique reseta (dois press sem `time` = duplo clique para o Tk) ──
div.event_generate("<Button-1>", x=7, y=200)
div.event_generate("<Button-1>", x=7, y=200)
pump(0.2)
div.event_generate("<ButtonRelease-1>", x=7, y=200)
pump(0.35)
r = app.config_data.get("split_ratio")   # gravação em disco é debounced
print("duplo clique →", r)
assert abs(r - 0.52) < 0.01, f"reset falhou: {r}"
assert not ghosts_in(body), "duplo clique deixou linha-guia órfã"

# ── proporção é restaurada ao reabrir a tela ──
drag_to(div, body, int(w * 0.42))
r = app.config_data.get("split_ratio")   # gravação em disco é debounced
app.show_group(app.groups()[0])
pump(0.6)
body2 = find_div(app).master
aplicada = body2.grid_columnconfigure(0)["weight"] / 1000
print(f"reabrindo a tela: salva={r} aplicada={aplicada}")
assert abs(aplicada - r) < 0.02, (aplicada, r)

app.destroy()
print("\nDIVISOR OK — arraste leve, aplica ao soltar, salva, limita e restaura")
