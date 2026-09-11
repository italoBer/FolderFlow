# -*- coding: utf-8 -*-
"""Etapa A — detecção da organização ano/mês, fita sem mês, conferência
genérica e nomes provisórios."""
import os
import sys
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


def arvore(base, caminhos):
    for c in caminhos:
        os.makedirs(os.path.join(base, *c.split("/")), exist_ok=True)


def melhor(base):
    c = ff.detectar_padrao_mes(base)
    return c[0] if c else None


NOMES = ff.MES_NOMES
raiz = tempfile.mkdtemp(prefix="ff_det_")

# 1. Shopee {ano}/{mes} - SHOPEE com 2 anos
b = os.path.join(raiz, "c1")
arvore(b, [f"Shopee 2026/{m:02d} - {NOMES[m-1]} - SHOPEE" for m in range(4, 10)]
       + ["Shopee 2025/12 - DEZEMBRO - SHOPEE"])
for m in range(4, 10):   # pastas de cliente dentro dos meses (ruído)
    arvore(b, [f"Shopee 2026/{m:02d} - {NOMES[m-1]} - SHOPEE/0{m}0001IT - Vazio"])
c = melhor(b)
print("      1:", c and (c["pattern"], c["meses"], c["anos"]))
check(c and c["pattern"] == "Shopee {ano}/{mes} - SHOPEE", "Shopee {ano}/{mes} - SHOPEE")
check(c["meses"] == 7 and c["anos"] == ["2025", "2026"], "7 meses em 2 anos")

# 2. ML - {ano}/{mes}
b = os.path.join(raiz, "c2")
arvore(b, ["ML - 2026/09 - SETEMBRO", "ML - 2026/08 - AGOSTO"])
c = melhor(b)
check(c and c["pattern"] == "ML - {ano}/{mes}", f"ML - {{ano}}/{{mes}} ({c and c['pattern']})")

# 3. {ano}/{mes}
b = os.path.join(raiz, "c3")
arvore(b, ["2026/09 - SETEMBRO", "2026/10 - OUTUBRO", "2025/01 - JANEIRO"])
c = melhor(b)
check(c and c["pattern"] == "{ano}/{mes}", f"{{ano}}/{{mes}} ({c and c['pattern']})")

# 4. {ano}/{mes_nome} sem acento
b = os.path.join(raiz, "c4")
arvore(b, ["2026/SETEMBRO", "2026/MARCO", "2026/ABRIL"])
c = melhor(b)
check(c and c["pattern"] == "{ano}/{mes_nome}", f"{{ano}}/{{mes_nome}} ({c and c['pattern']})")
check(c["estilo"]["acento"] is False, "aprendeu que escreve MARCO sem cedilha")
g = {"base_path": b, "dest_pattern": c["pattern"], "mes_estilo": c["estilo"]}
check(ff.mp_destino(g, "2026", "03 - MARÇO").endswith(os.path.join("2026", "MARCO")),
      "gera MARCO (não cria MARÇO duplicado)")

# 4b. Title case
b = os.path.join(raiz, "c4b")
arvore(b, ["2026/Setembro", "2026/Outubro", "2026/Março"])
c = melhor(b)
g = {"base_path": b, "dest_pattern": c["pattern"], "mes_estilo": c["estilo"]}
check(ff.mp_destino(g, "2026", "09 - SETEMBRO").endswith(os.path.join("2026", "Setembro")),
      f"respeita 'Setembro' em caixa de título ({c['estilo']})")

# 5. {ano}/{mes_num}
b = os.path.join(raiz, "c5")
arvore(b, ["2026/09", "2026/10", "2026/11"])
c = melhor(b)
check(c and c["pattern"] == "{ano}/{mes_num}", f"{{ano}}/{{mes_num}} ({c and c['pattern']})")

# 6. base com ano no nome → sugere a pasta pai
b = os.path.join(raiz, "c6", "Shopee 2026")
arvore(b, ["09 - SETEMBRO - SHOPEE", "08 - AGOSTO - SHOPEE", "07 - JULHO - SHOPEE"])
cs = ff.detectar_padrao_mes(b)
sug = [x for x in cs if x["base_diferente"]]
check(sug and sug[0]["pattern"] == "Shopee {ano}/{mes} - SHOPEE",
      "base 'Shopee 2026' → sugere usar a pasta de cima com {ano}")
check(os.path.normcase(sug[0]["base"]) == os.path.normcase(os.path.dirname(b)),
      "e aponta para a pasta pai")

# 7. {ano}-{mes_num}
b = os.path.join(raiz, "c7")
arvore(b, ["2026-09", "2026-10", "2025-12"])
c = melhor(b)
check(c and c["pattern"] == "{ano}-{mes_num}", f"{{ano}}-{{mes_num}} ({c and c['pattern']})")

# 8. ruído: 3000 pastas de cliente + Loja 1/2/13 → nada
b = os.path.join(raiz, "c8")
arvore(b, [f"{i:04d}R - Vazio" for i in range(3000)] + ["Loja 1", "Loja 2", "Loja 13"])
chamadas = [0]
orig = os.scandir


def espiao(p="."):
    chamadas[0] += 1
    return orig(p)


ff.os.scandir = espiao
cs = ff.detectar_padrao_mes(b)
ff.os.scandir = orig
check(cs == [], f"ruído não gera candidato ({[x['pattern'] for x in cs]})")
check(chamadas[0] < 5, f"não abre as pastas de cliente ({chamadas[0]} leituras)")

# ── ida e volta dos presets ─────────────────────────────────────────────────
for p, _rot in ff.PRESETS_PADRAO:
    if not p:
        continue
    pp = ff.preset_para_grupo(p, "Loja")
    b = os.path.join(raiz, "rt_" + str(abs(hash(pp))))
    g = {"base_path": b, "dest_pattern": pp, "name": "Loja"}
    for m in ("07 - JULHO", "08 - AGOSTO", "09 - SETEMBRO"):
        os.makedirs(ff.mp_destino(g, "2026", m), exist_ok=True)
    c = melhor(b)
    g2 = dict(g, dest_pattern=c["pattern"], mes_estilo=c["estilo"]) if c else None
    iguais = c and all(
        os.path.normcase(ff.mp_destino(g, "2026", m)) ==
        os.path.normcase(ff.mp_destino(g2, "2026", m))
        for m in ff.MESES)
    check(iguais, f"preset '{pp}' é reconhecido de volta ({c and c['pattern']})")

# ── fita: grupo sem pasta por mês conta pelo código ─────────────────────────
b = os.path.join(raiz, "semmes")
arvore(b, ["090001D - Vazio", "090002D - carlinhos", "100001T - Vazio",
           "100002T - Vazio", "100003Y - Vazio"])
g = {"base_path": b, "dest_pattern": "", "prefix": "", "kind": "marketplace"}
me = ff.meses_existentes(g, "2026")
check(me["09 - SETEMBRO"]["pastas"] == 2 and me["10 - OUTUBRO"]["pastas"] == 3,
      "sem pasta por mês: conta pelo código (09→2, 10→3)")
check(not me["01 - JANEIRO"]["existe"], "janeiro não existe (antes dava 12 de 12)")
check(me["09 - SETEMBRO"]["por_codigo"], "marca que a contagem é pelo código")

# conferência também filtra pelo código do mês
r = ff.conferir_pastas(g, "2026", "10 - OUTUBRO")
check(len(r["itens"]) == 3, f"conferência de outubro só vê as 3 de outubro ({len(r['itens'])})")

# ── conferência genérica (grupo de estrutura) + nomes provisórios ───────────
b = os.path.join(raiz, "generico")
arvore(b, ["vazio 0001", "vazio 0002", "Cliente Pronto", "Cliente Sem Nada"])
open(os.path.join(b, "vazio 0002", "Padaria Central.cdr"), "w").close()
open(os.path.join(b, "Cliente Pronto", "arte.pdf"), "w").close()
r = ff.conferir_pasta(b, usa_enviar=False)
est = {i["nome"]: i["estado"] for i in r["itens"]}
print("      genérico:", est)
check(est["vazio 0001"] == "vazia", "'vazio 0001' reconhecido como provisório vazio")
check(est["vazio 0002"] == "nao_renomeada", "provisório com arquivo = não renomeada")
check(est["Cliente Pronto"] == "ok" and est["Cliente Sem Nada"] == "sem_arquivo",
      "definitivas: com e sem entrega")
it = [i for i in r["itens"] if i["nome"] == "vazio 0002"][0]
check(it["sugestao"] == "Padaria Central", "sugestão pelo .cdr funciona no genérico")
check(ff.nome_corrigido(it, "Padaria Central") == "0002 - Padaria Central",
      f"nome corrigido mantém o número ({ff.nome_corrigido(it, 'Padaria Central')})")
it_cod = {"tem_codigo": True, "codigo": "090005AB", "nome": "090005AB - Vazio"}
check(ff.nome_corrigido(it_cod, "Bom Prato") == "090005AB - Bom Prato",
      "com código: CÓDIGO - Cliente")

# ── compatibilidade: os presets antigos continuam iguais ───────────────────
sh = ff.preset_marketplace_groups()[0]
sh["base_path"] = r"C:\X"
check(ff.mp_destino(sh, "2026", "09 - SETEMBRO") ==
      os.path.join(r"C:\X", "Shopee 2026", "09 - SETEMBRO - SHOPEE"),
      "caminho da Shopee idêntico ao de antes")

shutil.rmtree(raiz, ignore_errors=True)
print(f"\n{ok} verificações passaram. DETECÇÃO OK")
