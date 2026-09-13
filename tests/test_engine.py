# -*- coding: utf-8 -*-
"""Testes do motor de templates + migração do FolderFlow v2 (sem UI)."""
import os
import sys
import json
import shutil
import tempfile

sys.path.insert(0, r"D:\Claude\Teste1")
import folderflow as ff

ok_count = 0

def check(cond, msg):
    global ok_count
    if cond:
        ok_count += 1
        print(f"  OK  {msg}")
    else:
        print(f"FALHOU: {msg}")
        sys.exit(1)

tmp = tempfile.mkdtemp(prefix="ff2_test_")
print("dir de teste:", tmp)

# ── 1. Exemplo exato do usuário ────────────────────────────────────────────────
TPL = """
# comentário
Clientes Loja 1/
Produtos Loja 2/
  X/
  Y/
    [200] Pasta {seq:04d}/
      teste/
      infos.txt = Informações do item {seq:04d}
  Z/
"""
nodes = ff.parse_template(TPL)
check(len(nodes) == 2, "parse: 2 pastas raiz")
check(nodes[1]["children"][1]["name"] == "Y", "parse: Y dentro de Produtos Loja 2")
rep = nodes[1]["children"][1]["children"][0]
check(rep["repeat"] == "200" and rep["name"] == "Pasta {seq:04d}", "parse: nó de repetição")
check(ff.collect_variables(nodes) == [], "variáveis: seq não conta")

st = ff.execute_template(nodes, tmp, {}, dry=True)
check(st["folders"] == 2 + 3 + 200 + 200 and st["files"] == 200,
      f"dry-run: {st['folders']} pastas / {st['files']} arquivos")

st = ff.execute_template(nodes, tmp, {}, dry=False)
p = os.path.join(tmp, "Produtos Loja 2", "Y", "Pasta 0042")
check(os.path.isdir(os.path.join(p, "teste")), "execução: Pasta 0042/teste existe")
info = open(os.path.join(p, "infos.txt"), encoding="utf-8").read()
check(info == "Informações do item 0042", "execução: conteúdo do infos.txt com {seq}")

# ── 2. Idempotência + continuação de numeração ────────────────────────────────
st2 = ff.execute_template(nodes, tmp, {}, dry=True, continue_seq=True)
check(st2["folders"] == 200 + 200 and st2["files"] == 200,
      "continuação: 2ª rodada cria 0201-0400 (não duplica)")
st3 = ff.execute_template(nodes, tmp, {}, dry=True, continue_seq=False)
check(st3["folders"] == 0 and st3["skipped"] > 0,
      "sem continuação: tudo já existe, nada a criar")

# ── 3. Variáveis do usuário + repetição por variável ─────────────────────────
TPL2 = """
{cliente}/
  [{qtd}] Item {seq:03d}/
  resumo.txt = Cliente {cliente} em {ano}
"""
n2 = ff.parse_template(TPL2)
check(ff.collect_variables(n2) == ["cliente", "qtd", "ano"], "variáveis detectadas em ordem")
d2 = os.path.join(tmp, "var")
os.makedirs(d2)
r2 = ff.execute_template(n2, d2, {"cliente": "ACME", "qtd": "5", "ano": "2026"})
check(os.path.isdir(os.path.join(d2, "ACME", "Item 003")), "variáveis: repetição {qtd}=5")
check(open(os.path.join(d2, "ACME", "resumo.txt"), encoding="utf-8").read()
      == "Cliente ACME em 2026", "variáveis: conteúdo renderizado")

# ── 4. Erros amigáveis ────────────────────────────────────────────────────────
for bad, motivo in [
    ("  \n", "modelo vazio"),
    ("a.txt\n  dentro/", "filho de arquivo"),
    ("pasta|inv/", "caractere inválido"),
    ("[x] p/", "repetição inválida"),
]:
    try:
        n = ff.parse_template(bad)
        ff.execute_template(n, tmp, {}, dry=True)
        check(False, f"deveria falhar: {motivo}")
    except ff.TemplateError as e:
        check(True, f"erro amigável ({motivo}): {e}")

try:
    ff.execute_template(ff.parse_template("{nome}/"), tmp, {}, dry=True)
    check(False, "variável sem valor deveria falhar")
except ff.TemplateError as e:
    check("nome" in str(e), f"variável sem valor: {e}")

# ── 5. Marketplace: criar_lote fiel ao v1 ────────────────────────────────────
mp_base = os.path.join(tmp, "shopee_base")
os.makedirs(mp_base)
g = ff.preset_marketplace_groups()[0]
g["base_path"] = mp_base
logs = []
n = ff.criar_lote(g, "2026", "09 - SETEMBRO", [("IT", 3), ("AB", 2)],
                  lambda m, **k: logs.append(m), pause_od=False)
destino = os.path.join(mp_base, "Shopee 2026", "09 - SETEMBRO - SHOPEE")
check(n == 5, "marketplace: 5 pastas criadas")
check(os.path.isdir(os.path.join(destino, "090001IT - Vazio", "#ENVIAR")),
      "marketplace: 090001IT - Vazio/#ENVIAR")
check(os.path.isdir(os.path.join(destino, "090005AB - Vazio")),
      "marketplace: numeração contínua entre responsáveis")
n2 = ff.criar_lote(g, "2026", "09 - SETEMBRO", [("IT", 1)],
                   lambda m, **k: None, pause_od=False)
check(os.path.isdir(os.path.join(destino, "090006IT - Vazio")),
      "marketplace: continua do 0006")

# ML com prefixo A
ml_base = os.path.join(tmp, "ml_base")
os.makedirs(ml_base)
gml = ff.preset_marketplace_groups()[1]
gml["base_path"] = ml_base
ff.criar_lote(gml, "2026", "09 - SETEMBRO", [("IT", 1)], lambda m, **k: None, False)
check(os.path.isdir(os.path.join(ml_base, "ML - 2026", "09 - SETEMBRO",
                                 "A090001IT - Vazio")),
      "marketplace ML: prefixo A e destino ML - 2026/09 - SETEMBRO")

# ── 6. Relatório ──────────────────────────────────────────────────────────────
os.rename(os.path.join(destino, "090001IT - Vazio"),
          os.path.join(destino, "090001IT - Cliente Teste"))
open(os.path.join(destino, "090001IT - Cliente Teste", "#ENVIAR", "arte.pdf"),
     "w").close()
r = ff.conferir_pastas(g, "2026", "09 - SETEMBRO")
estados = [it["estado"] for it in r["itens"]]
check(len(estados) == 6 and estados.count("ok") == 1
      and estados.count("vazia") == 5,
      f"relatório: {len(estados)} pastas, entregue={estados.count('ok')}")
check(r["por_pessoa"]["IT"]["total"] == 4 and r["por_pessoa"]["AB"]["total"] == 2,
      "relatório: contagem por responsável")

# ── 7. Migração v1 → v2 ──────────────────────────────────────────────────────
cfg_v1 = {
    "shopee_base": r"C:\OneDrive\SHOPEE", "ml_base": r"C:\OneDrive\ML",
    "pause_onedrive": True, "trello_key": "K", "trello_token": "T",
    "shopee_board_id": "SB", "ml_board_id": "MB",
    "shopee_list_aguardando": "SLA", "ml_list_aguardando": "MLA",
    "shopee_list_dev_id": "SLD", "ml_list_dev_id": "MLD",
    "watcher_interval": 60, "github_repo": "italoBer/FolderFlow",
}
cfg2, migrated = ff.migrate_config(dict(cfg_v1))
check(migrated and len(cfg2["groups"]) == 2, "migração: 2 grupos criados")
sh, ml = cfg2["groups"]
check(sh["name"] == "Shopee" and sh["base_path"] == cfg_v1["shopee_base"]
      and sh["board_id"] == "SB" and sh["list_aguardando"] == "SLA"
      and sh["list_dev"] == "SLD" and sh["prefix"] == "",
      "migração: grupo Shopee completo")
check(ml["prefix"] == "A" and ml["dest_pattern"] == "ML - {ano}/{mes}"
      and ml["list_dev"] == "MLD", "migração: grupo ML completo")
check(cfg2["trello_key"] == "K" and cfg2["shopee_base"] == cfg_v1["shopee_base"],
      "migração: chaves antigas preservadas (rollback possível)")
cfg3, migrated2 = ff.migrate_config(cfg2)
check(not migrated2 and len(cfg3["groups"]) == 2, "migração: idempotente")
cfg_fresh, _ = ff.migrate_config(dict(ff.DEFAULT_CONFIG))
check(cfg_fresh["groups"] == [], "instalação nova: sem grupos fantasma")

# ── 8. Índice/busca ──────────────────────────────────────────────────────────
idx = ff.build_index([g, gml])
check("090001IT" in idx and idx["090001IT"]["cliente"] == "Cliente Teste",
      "índice: pasta renomeada indexada")
check("A090001IT" in idx and idx["A090001IT"]["plat"] == "MERCADO LIVRE",
      "índice: grupo ML rotulado")
achados = ff.buscar_pastas(mp_base, "090001IT")
check(achados and os.path.basename(achados[0]) == "090001IT - Cliente Teste",
      "busca por código")
check(not any("#ENVIAR" in k for k in idx), "índice não guarda as pastas #ENVIAR")

shutil.rmtree(tmp)
print(f"\n{ok_count} verificações passaram. TUDO OK")
