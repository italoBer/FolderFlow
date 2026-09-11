# -*- coding: utf-8 -*-
"""Abre o app real e navega por todas as telas, sem tocar na config do projeto."""
import os
import sys
import tempfile

sys.path.insert(0, r"D:\Claude\Teste1")
import folderflow as ff

tmp = tempfile.mkdtemp(prefix="ff2_ui_")
ff.CONFIG_FILE = os.path.join(tmp, "cfg.json")
ff.INDEX_FILE  = os.path.join(tmp, "idx.json")

# config com 1 grupo template + preset marketplace
base = os.path.join(tmp, "base")
os.makedirs(base)
cfg = ff.DEFAULT_CONFIG.copy()
tg = ff.default_group("template")
tg.update({"name": "Meu projeto", "color": "#a8e05f", "base_path": base})
cfg["groups"] = [tg] + ff.preset_marketplace_groups()
ff.save_config(cfg)

app = ff.App()
app.update()
print("home ok — grupos:", [g["name"] for g in app.groups()])

app.show_group(app.groups()[0]); app.update()
print("vista template ok")

app.show_group(app.groups()[1]); app.update()
print("vista marketplace (Shopee) ok")

app.show_group(app.groups()[2]); app.update()
print("vista marketplace (ML) ok")

app.show_search(); app.update()
print("busca ok")

for opener, nome in [(app.open_help, "ajuda"), (app.open_sobre, "sobre"),
                     (app.open_watcher, "watcher"), (app.open_settings, "config"),
                     (lambda: app.open_group_editor(None), "editor novo"),
                     (lambda: app.open_group_editor(app.groups()[1]), "editor mp")]:
    opener()
    app.update()
    for w in list(app.winfo_children()):
        if isinstance(w, ff.ctk.CTkToplevel):
            w.grab_release()
            w.destroy()
    app.update()
    print(f"janela {nome} ok")

# home vazia (sem grupos)
app.config_data["groups"] = []
app.show_home(); app.update()
print("home vazia ok")

# preset a partir da home vazia
app._add_preset(); app.update()
print("preset adicionado:", [g["name"] for g in app.groups()])

app.destroy()
print("\nUI OK — todas as telas abriram sem erro")
