# -*- coding: utf-8 -*-
"""Fase 3 — conferência de pastas, sugestão de cliente, distribuição,
histórico e meses existentes."""
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


tmp = tempfile.mkdtemp(prefix="ff_conf_")
ff.HISTORY_FILE = os.path.join(tmp, "hist.json")

base = os.path.join(tmp, "base")
os.makedirs(base)
g = ff.preset_marketplace_groups()[0]
g["base_path"] = base
destino = ff.mp_destino(g, "2026", "09 - SETEMBRO")
os.makedirs(destino)


def pasta(nome, arquivos=(), enviar=()):
    p = os.path.join(destino, nome)
    os.makedirs(p, exist_ok=True)
    os.makedirs(os.path.join(p, "#ENVIAR"), exist_ok=True)
    for a in arquivos:
        open(os.path.join(p, a), "w").close()
    for a in enviar:
        open(os.path.join(p, "#ENVIAR", a), "w").close()
    return p


# os quatro estados
pasta("090001IT - Padaria do Zé", enviar=("arte.pdf",))          # ok
pasta("090002IT - Mercearia Silva")                              # sem arquivo
pasta("090003AB - Vazio")                                        # vazia
pasta("090004AB - Vazio", arquivos=("Restaurante Bom Prato.cdr",
                                    "previa.jpg"))               # OneDrive falhou
pasta("090005IT - Vazio", arquivos=("090005IT_lanchonete_da_ana_FINAL_v2.cdr",))

r = ff.conferir_pastas(g, "2026", "09 - SETEMBRO")
estados = {i["codigo"]: i["estado"] for i in r["itens"]}
print("      estados:", estados)
check(estados["090001IT"] == "ok", "pasta entregue = ok")
check(estados["090002IT"] == "sem_arquivo", "com cliente e sem arte = sem_arquivo")
check(estados["090003AB"] == "vazia", "sem nada dentro = vazia de verdade")
check(estados["090004AB"] == "nao_renomeada",
      "'Vazio' COM arquivos = OneDrive não renomeou")
check(estados["090005IT"] == "nao_renomeada", "idem para a outra")

# ── sugestão de nome vinda do .cdr ──────────────────────────────────────────
sug = {i["codigo"]: i["sugestao"] for i in r["itens"] if i["sugestao"]}
print("      sugestões:", sug)
check(sug.get("090004AB") == "Restaurante Bom Prato",
      f"pegou o nome do .cdr ({sug.get('090004AB')!r})")
check(sug.get("090005IT") == "Lanchonete da Ana",
      f"limpou código, 'FINAL' e 'v2', com 'da' minúsculo "
      f"({sug.get('090005IT')!r})")

# prioriza .cdr sobre .jpg
p = pasta("090006AB - Vazio", arquivos=("zzz_foto.jpg", "Oficina do João.cdr"))
n, fonte = ff.sugerir_cliente(p, "090006AB")
check(n == "Oficina do João", f"prefere o .cdr ({n!r} de {fonte!r})")

# nome que vira lixo não é sugerido
p = pasta("090007AB - Vazio", arquivos=("final v2.cdr",))
n, _ = ff.sugerir_cliente(p, "090007AB")
check(n == "", f"não sugere nome que sobra vazio ({n!r})")

# ── resumo por pessoa ───────────────────────────────────────────────────────
r = ff.conferir_pastas(g, "2026", "09 - SETEMBRO")
pp = r["por_pessoa"]
print("      por pessoa:", {k: dict(v) for k, v in pp.items()})
check(pp["IT"]["total"] == 3, "3 pastas do IT")
check(pp["IT"]["ok"] == 1 and pp["IT"]["sem_arquivo"] == 1
      and pp["IT"]["nao_renomeada"] == 1, "IT: 1 ok, 1 sem arte, 1 não renomeada")
check(pp["AB"]["vazia"] == 1, f"AB deixou 1 realmente vazia ({pp['AB']['vazia']})")
check(pp["AB"]["nao_renomeada"] == 3,
      "AB tem 3 com arquivo que o OneDrive não renomeou")
# uma delas tem arquivo mas nome impossível de aproveitar: continua listada,
# só que sem sugestão — o usuário digita na mão
sem_sug = [i for i in r["itens"]
           if i["estado"] == "nao_renomeada" and not i["sugestao"]]
check(len(sem_sug) == 1 and sem_sug[0]["codigo"] == "090007AB",
      "pasta sem sugestão aproveitável ainda aparece para correção manual")
check(sem_sug[0]["n_arquivos"] >= 1, "e informa que tem arquivo dentro")

# ── distribuir total ────────────────────────────────────────────────────────
d = ff.distribuir_total(100, ["IT", "AB", "CD"])
check(sorted(d.values()) == [33, 33, 34], f"100 entre 3 = 34/33/33 ({d})")
check(sum(d.values()) == 100, "a soma bate com o total")
d = ff.distribuir_total(9, ["A", "B", "C"])
check(list(d.values()) == [3, 3, 3], "divisão exata")
d = ff.distribuir_total(2, ["A", "B", "C"])
check(sorted(d.values()) == [0, 1, 1], f"total menor que a equipe ({d})")
check(ff.distribuir_total(0, ["A"]) == {"A": 0}, "total zero não quebra")
check(ff.distribuir_total(10, []) == {}, "sem pessoas não quebra")

# ── histórico ───────────────────────────────────────────────────────────────
ff.registrar_lote("Shopee", "2026", "08 - AGOSTO", [("IT", 20), ("AB", 10)])
ff.registrar_lote("Shopee", "2026", "09 - SETEMBRO", [("IT", 30), ("CD", 5)])
ff.registrar_lote("Outro", "2026", "09 - SETEMBRO", [("ZZ", 99)])
h = ff.load_history()
check(len(h) == 3, "3 lotes registrados")

s = ff.sugestoes_de_pessoas("Shopee")
nomes = [p for p, _q, _n in s]
print("      sugestões de pessoas:", s)
check(nomes[0] == "IT", "IT é o mais frequente e vem primeiro")
check("ZZ" not in nomes, "não mistura pessoas de outro grupo")
qtd_it = dict((p, q) for p, q, _n in s)["IT"]
check(qtd_it in (20, 30), f"quantidade típica do IT ({qtd_it})")

u = ff.ultimo_lote("Shopee")
check(u["mes"] == "09 - SETEMBRO", "último lote do grupo é o mais recente")
check(ff.ultimo_lote("Inexistente") is None, "grupo sem histórico devolve None")

# ── meses existentes ────────────────────────────────────────────────────────
me = ff.meses_existentes(g, "2026")
check(me["09 - SETEMBRO"]["existe"], "setembro existe")
check(me["09 - SETEMBRO"]["pastas"] == 7, f"conta as pastas ({me['09 - SETEMBRO']['pastas']})")
check(not me["01 - JANEIRO"]["existe"], "janeiro não existe")
check(len(me) == 12, "os 12 meses são avaliados")

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{ok} verificações passaram. CONFERÊNCIA/HISTÓRICO OK")
