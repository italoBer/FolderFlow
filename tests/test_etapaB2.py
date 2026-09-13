# -*- coding: utf-8 -*-
"""Etapa B2: motor de colar + Ctrl+C/X/V na aba Pastas.
A parte da tela usa a área de transferência do PC: só com FF_CLIP=1."""
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


tmp = tempfile.mkdtemp(prefix="ff_eB2_")
src = os.path.join(tmp, "src")
dst = os.path.join(tmp, "dst")
os.makedirs(os.path.join(src, "Pasta A", "sub"))
os.makedirs(dst)
open(os.path.join(src, "arte.cdr"), "w").close()
open(os.path.join(src, "Pasta A", "sub", "x.txt"), "w").close()
open(os.path.join(dst, "arte.cdr"), "w").close()

prog = []
novos, erros = ff.colar_itens([os.path.join(src, "arte.cdr"),
                               os.path.join(src, "Pasta A")], dst,
                              avisa=prog.append)
check(sorted(os.listdir(dst)) == ["Pasta A", "arte (2).cdr", "arte.cdr"],
      "conflito vira 'arte (2).cdr'; pasta copiada")
check(os.path.isfile(os.path.join(dst, "Pasta A", "sub", "x.txt")),
      "copia a pasta com o conteúdo")
check(prog == [(1, 2, "arte.cdr"), (2, 2, "Pasta A")], "avisa o progresso")
ff.colar_itens([os.path.join(src, "Pasta A")], dst)
check(os.path.isdir(os.path.join(dst, "Pasta A (2)")), "pasta repetida: '(2)'")
ff.colar_itens([os.path.join(src, "arte.cdr")], dst)
check(os.path.isfile(os.path.join(dst, "arte (3).cdr")), "terceira: '(3)'")

novos, erros = ff.colar_itens([os.path.join(src, "Pasta A")],
                              os.path.join(src, "Pasta A", "sub"))
check(not novos and erros and "dentro dela mesma" in erros[0],
      "recusa colar uma pasta dentro dela mesma")

novos, erros = ff.colar_itens([os.path.join(src, "arte.cdr")], src, mover=True)
check(novos == [os.path.join(src, "arte.cdr")] and not erros
      and os.listdir(src).count("arte.cdr") == 1,
      "recortar e colar no mesmo lugar: não faz nada")

novos, erros = ff.colar_itens([os.path.join(src, "arte.cdr")], dst, mover=True)
check(not os.path.exists(os.path.join(src, "arte.cdr"))
      and os.path.isfile(os.path.join(dst, "arte (4).cdr")),
      "recortar: move para o destino")
novos, erros = ff.colar_itens([os.path.join(src, "sumiu.txt")], dst)
check(erros and "não existe" in erros[0], "origem que sumiu vira aviso")

# ── na tela (usa a área de transferência) ───────────────────────────────────
if os.environ.get("FF_CLIP") != "1":
    print("      (parte da tela pulada — defina FF_CLIP=1)")
else:
    ff.CONFIG_FILE = os.path.join(tmp, "cfg.json")
    ff.INDEX_FILE = os.path.join(tmp, "idx.json")
    ff.HISTORY_FILE = os.path.join(tmp, "hist.json")
    base = os.path.join(tmp, "Base")
    for n in ("Mes 1", "Mes 2"):
        os.makedirs(os.path.join(base, n))
    open(os.path.join(base, "Mes 1", "logo.png"), "w").close()
    g = ff.default_group("template")
    g.update({"name": "B2", "base_path": base})
    cfg = ff.DEFAULT_CONFIG.copy()
    cfg.update({"groups": [g], "onboarding_ok": True, "usa_trello": False})
    ff.save_config(cfg)
    app = ff.App()
    app.update()
    app.show_group(app.groups()[0])

    def pump(s=0.3):
        end = time.time() + s
        while time.time() < end:
            app.update()
            time.sleep(0.01)

    def trees(w, out):
        for c in w.winfo_children():
            if isinstance(c, ff.TreeCanvas):
                out.append(c)
            trees(c, out)
        return out

    def chave(p):
        return os.path.normcase(os.path.abspath(p))

    def ctrl(tecla):
        d.on_shortcut and d._on_ctrl_key(type("E", (), {
            "keycode": ord(tecla), "state": 0x0004})())

    pump(1.0)
    d = trees(app._tabs_grupo.tab(app.ABA_PASTAS), [])[0]
    d._expanded.add(chave(os.path.join(base, "Mes 1")))
    d.reload()
    pump(0.8)
    d.select_key(chave(os.path.join(base, "Mes 1", "logo.png")))
    ctrl("C")
    lidos, rec = ff.clipboard_ler_arquivos()
    check(lidos and os.path.basename(lidos[0]) == "logo.png" and not rec,
          "Ctrl+C põe o arquivo na área de transferência do Windows")
    d.select_key(chave(os.path.join(base, "Mes 2")))
    ctrl("V")
    pump(1.5)
    check(os.path.isfile(os.path.join(base, "Mes 2", "logo.png")),
          "Ctrl+V cola na pasta selecionada")
    sel = d.selected_row()
    check(sel is not None and sel.label == "logo.png"
          and os.path.dirname(sel.payload).endswith("Mes 2"),
          "o item colado aparece e fica selecionado")

    d.select_key(chave(os.path.join(base, "Mes 1", "logo.png")))
    ctrl("X")
    pump(0.2)
    check(chave(os.path.join(base, "Mes 1", "logo.png")) in d.recortados,
          "Ctrl+X deixa o item apagado")
    d.select_key(chave(os.path.join(base, "Mes 2")))
    ctrl("V")
    pump(1.5)
    check(not os.path.exists(os.path.join(base, "Mes 1", "logo.png"))
          and os.path.isfile(os.path.join(base, "Mes 2", "logo (2).png")),
          "recortar + colar move (conflito vira 'logo (2).png')")
    check(not d.recortados and not ff.clipboard_ler_arquivos()[0],
          "depois de mover, o recorte some (como no Explorador)")

    # ── no Modelo: copiar um nó para dentro de outra pasta ─────────────────
    app.groups()[0]["template"] = "Cliente/\n  arte.pdf\nArquivo Morto/\n"
    app.show_group(app.groups()[0])
    pump(0.5)
    app._tabs_grupo.set(app.ABA_MODELO)
    pump(0.8)
    d = trees(app._tabs_grupo.tab(app.ABA_MODELO), [])[0]
    por_nome = lambda n: [r for r in d.rows() if r.label == n][0]
    d.select_key(por_nome("Cliente").key)
    ctrl("C")
    check("Cliente/" in app.clipboard_get(), "o trecho vai como texto do modelo")
    d.select_key(por_nome("Arquivo Morto").key)
    ctrl("V")
    pump(0.5)
    morto = por_nome("Arquivo Morto").payload
    check([c["name"] for c in morto["children"]] == ["Cliente"]
          and morto["children"][0]["children"][0]["name"] == "arte.pdf",
          "Ctrl+V cola a pasta com o conteúdo dentro da selecionada")
    d.select_key(por_nome("Arquivo Morto").key)
    ctrl("X")
    pump(0.3)
    check(not any(r.label == "Arquivo Morto" for r in d.rows()),
          "Ctrl+X tira o nó do modelo")
    d._sel.clear()
    ctrl("V")
    pump(0.3)
    check(any(r.label == "Arquivo Morto" for r in d.rows()),
          "e Ctrl+V devolve na raiz")
    app.destroy()

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{ok} verificações passaram. ETAPA B2 OK")
