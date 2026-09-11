# -*- coding: utf-8 -*-
"""Fase 2 — renomear em massa e excluir para a Lixeira (lógica pura)."""
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


# ── 1. Localizar e substituir ───────────────────────────────────────────────
nomes = ["090001IT - Vazio", "090002AB - Vazio", "090003IT - Cliente X"]
r = ff.preview_rename(nomes, "substituir", de="Vazio", para="Pendente")
check([x[1] for x in r] == ["090001IT - Pendente", "090002AB - Pendente",
                            "090003IT - Cliente X"],
      "substituir troca só onde encontra")
check(all(x[2] is None for x in r), "sem problemas apontados")

r = ff.preview_rename(["ABC", "abc"], "substituir", de="a", para="X",
                      ignorar_caso=True)
check([x[1] for x in r][0] == "XBC", "substituir ignorando maiúsculas")
r = ff.preview_rename(["ABC", "abc"], "substituir", de="a", para="X",
                      ignorar_caso=False)
check([x[1] for x in r] == ["ABC", "Xbc"], "substituir respeitando maiúsculas")

# ── 2. Prefixo e sufixo ─────────────────────────────────────────────────────
r = ff.preview_rename(["Cliente A", "Cliente B"], "afixo", prefixo="OK - ")
check([x[1] for x in r] == ["OK - Cliente A", "OK - Cliente B"],
      "adiciona prefixo")
r = ff.preview_rename(["OK - Cliente A"], "afixo", remover_prefixo="OK - ")
check(r[0][1] == "Cliente A", "remove prefixo")
r = ff.preview_rename(["Arte final"], "afixo", sufixo=" (v2)")
check(r[0][1] == "Arte final (v2)", "adiciona sufixo")
r = ff.preview_rename(["Arte final"], "afixo", remover_sufixo=" final")
check(r[0][1] == "Arte", "remove sufixo")

# ── 3. Renumerar ────────────────────────────────────────────────────────────
r = ff.preview_rename(["b", "a", "c"], "renumerar", formato="{seq:03d}",
                      inicio=1, padrao="{seq} - {nome}")
check([x[1] for x in r] == ["001 - b", "002 - a", "003 - c"],
      "renumera na ordem dada")
r = ff.preview_rename(["x", "y"], "renumerar", formato="{seq:04d}", inicio=10,
                      padrao="Pasta {seq}")
check([x[1] for x in r] == ["Pasta 0010", "Pasta 0011"],
      "renumera com formato e início escolhidos")

# ── 4. Trocar nome do cliente ───────────────────────────────────────────────
r = ff.preview_rename(["090001IT - Vazio"], "cliente", novo="Padaria do Zé")
check(r[0][1] == "090001IT - Padaria do Zé", "troca cliente mantendo o código")
r = ff.preview_rename(["SemCodigo"], "cliente", novo="Fulano")
check(r[0][1] == "SemCodigo - Fulano", "sem código, acrescenta o cliente")

# ── 5. Validações ───────────────────────────────────────────────────────────
# "a"→"b" colide com o "b" que fica parado: quem muda é que é sinalizado
r = ff.preview_rename(["a", "b"], "substituir", de="a", para="b")
check("repetido" in (r[0][2] or ""), f"detecta colisão com item parado ({r[0][2]})")
check(r[1][2] is None, "o item que não muda não é acusado")
# dois renomeados caindo no mesmo nome: ambos sinalizados
r = ff.preview_rename(["001 - A", "001 - B"], "cliente", novo="Zé")
check(all("repetido" in (x[2] or "") for x in r),
      f"dois renomeados colidindo são ambos sinalizados ({[x[2] for x in r]})")
r = ff.preview_rename(["teste"], "afixo", prefixo="in|valido:")
check("inválidos" in (r[0][2] or "") and "|" not in r[0][1],
      f"limpa caracteres proibidos ({r[0][1]!r}, {r[0][2]})")
r = ff.preview_rename(["abc"], "substituir", de="abc", para="")
check(r[0][2] == "nome vazio ou inválido", "recusa nome que ficaria vazio")

# ── 6. Aplicar de verdade ───────────────────────────────────────────────────
tmp = tempfile.mkdtemp(prefix="ff_ren_")
for n in ["090001IT - Vazio", "090002AB - Vazio"]:
    os.makedirs(os.path.join(tmp, n))
pares = ff.preview_rename(sorted(os.listdir(tmp)), "substituir",
                          de="Vazio", para="Pendente")
feitos, erros = ff.aplicar_rename(tmp, pares)
check(feitos == 2 and not erros, f"2 pastas renomeadas ({feitos}, {erros})")
check(sorted(os.listdir(tmp)) == ["090001IT - Pendente", "090002AB - Pendente"],
      "nomes no disco conferem")

# troca circular A→B e B→A
tmp2 = tempfile.mkdtemp(prefix="ff_swap_")
os.makedirs(os.path.join(tmp2, "A"))
os.makedirs(os.path.join(tmp2, "B"))
pares = [("A", "B", None), ("B", "A", None)]
feitos, erros = ff.aplicar_rename(tmp2, pares)
check(feitos == 2 and not erros, f"troca circular funciona ({feitos}, {erros})")
check(sorted(os.listdir(tmp2)) == ["A", "B"], "as duas pastas continuam lá")
check(not [f for f in os.listdir(tmp2) if f.startswith("__ff_tmp_")],
      "nenhum temporário deixado para trás")

# colisão com pasta que NÃO será renomeada → erro claro, sem destruir nada
tmp3 = tempfile.mkdtemp(prefix="ff_col_")
os.makedirs(os.path.join(tmp3, "origem"))
os.makedirs(os.path.join(tmp3, "ocupado"))
feitos, erros = ff.aplicar_rename(tmp3, [("origem", "ocupado", None)])
check(feitos == 0 and erros and "já existe" in erros[0],
      f"colisão avisa em vez de sobrescrever ({erros})")
check(os.path.isdir(os.path.join(tmp3, "origem")), "a pasta original continua")

# ── 7. Lixeira ──────────────────────────────────────────────────────────────
tmp4 = tempfile.mkdtemp(prefix="ff_lix_")
alvo = os.path.join(tmp4, "para excluir")
os.makedirs(alvo)
open(os.path.join(alvo, "arq.txt"), "w").write("x")
n_ok, erros = ff.mandar_para_lixeira([alvo])
check(n_ok == 1 and not erros, f"mandou para a Lixeira ({n_ok}, {erros})")
check(not os.path.exists(alvo), "pasta saiu do lugar original")

n_ok, erros = ff.mandar_para_lixeira([os.path.join(tmp4, "nao existe")])
check(n_ok == 0 and erros, "caminho inexistente vira erro, não exceção")

# ── 8. Tamanho ──────────────────────────────────────────────────────────────
tmp5 = tempfile.mkdtemp(prefix="ff_tam_")
os.makedirs(os.path.join(tmp5, "sub"))
open(os.path.join(tmp5, "a.bin"), "wb").write(b"x" * 1000)
open(os.path.join(tmp5, "sub", "b.bin"), "wb").write(b"y" * 2000)
check(ff.tamanho_de(tmp5) == 3000, "soma o tamanho das subpastas")
check(ff.fmt_tamanho(3000) == "2.9 KB", f"formata ({ff.fmt_tamanho(3000)})")
check(ff.fmt_tamanho(500) == "500 B", "formata bytes")

for d in (tmp, tmp2, tmp3, tmp4, tmp5):
    shutil.rmtree(d, ignore_errors=True)
print(f"\n{ok} verificações passaram. RENOMEAR/EXCLUIR OK")
