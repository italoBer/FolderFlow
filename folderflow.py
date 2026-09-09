# -*- coding: utf-8 -*-
"""FolderFlow 2 — criador e organizador de estruturas de pastas.

Genérico: qualquer pessoa define "grupos" com modelos de estrutura
(pastas, subpastas, arquivos, repetição em lote com numeração).
Preset "Marketplace" mantém o fluxo Shopee/Mercado Livre + Trello
usado pela Flag Brasil (migração automática da config v1).
"""
import os
import re
import sys
import json
import shutil
import time
import uuid
import string
import datetime
import threading
import subprocess
import urllib.request
import urllib.parse
import tkinter as tk
from tkinter import messagebox, filedialog

try:
    import customtkinter as ctk
except ImportError:
    root = tk.Tk(); root.withdraw()
    messagebox.showerror(
        "FolderFlow — dependência faltando",
        "A biblioteca 'customtkinter' não está instalada.\n\n"
        "Abra o terminal e rode:\n    pip install customtkinter")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════════
# VERSÃO E ARQUIVOS DE SUPORTE
# ═══════════════════════════════════════════════════════════════════════════════
APP_NAME    = "FolderFlow"
APP_VERSION = "2.0.0"

if getattr(sys, "frozen", False):
    _DIR = os.path.dirname(sys.executable)
else:
    _DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(_DIR, "folderflow_config.json")
INDEX_FILE  = os.path.join(_DIR, "folderflow_index.json")

MESES = [
    "01 - JANEIRO", "02 - FEVEREIRO", "03 - MARÇO",
    "04 - ABRIL",   "05 - MAIO",      "06 - JUNHO",
    "07 - JULHO",   "08 - AGOSTO",    "09 - SETEMBRO",
    "10 - OUTUBRO", "11 - NOVEMBRO",  "12 - DEZEMBRO",
]

FOLDER_CODE_RE = re.compile(r'^(A?\d{6}[A-Z]+) - (.+)$')

GROUP_COLORS = ["#f5c518", "#a8e05f", "#4f8fff", "#ff6b35",
                "#b98cff", "#00ccdd", "#ff5577", "#22dd77"]

DEFAULT_TEMPLATE = """\
# Modelo da estrutura — edite à vontade (clique em ? para ver a sintaxe)
# Termina com /  = pasta   |   sem /  = arquivo   |   [N] repete N vezes
Clientes Loja 1/
Produtos Loja 2/
  X/
  Y/
    [10] Pasta {seq:04d}/
      teste/
      infos.txt = Informações do item {seq:04d}
  Z/
"""

READY_TEMPLATES = {
    "Lojas / Produtos": DEFAULT_TEMPLATE,
    "Projeto Web": """\
{projeto}/
  src/
    css/
    js/
    img/
  docs/
  README.md = # {projeto}\\nCriado em {data}
""",
    "Fotografia — Ensaio": """\
{cliente} - {data}/
  RAW/
  Selecionadas/
  Editadas/
  Entregues/
  anotacoes.txt = Cliente: {cliente}\\nEnsaio em {data}
""",
    "Arquivos Fiscais": """\
Fiscal {ano}/
  [12] {seq:02d} - Mês/
    Entradas/
    Saídas/
    Notas/
""",
    "Clientes numerados": """\
Clientes/
  [{qtd}] Cliente {seq:03d}/
    Documentos/
    Contratos/
    infos.txt = Cliente {seq:03d}
""",
}

DEFAULT_CONFIG = {
    "config_version":  2,
    "groups":          [],
    "trello_key":      "",
    "trello_token":    "",
    "pause_onedrive":  True,
    "watcher_interval": 60,
    "github_repo":     "italoBer/FolderFlow",
}


def template_counts(text):
    """(pastas, arquivos) estimados de um modelo; repetição variável conta 1×.
    None se o modelo tiver erro de sintaxe."""
    try:
        nodes = parse_template(text or "")
    except TemplateError:
        return None
    counts = [0, 0]

    def walk(ns, mult):
        for n in ns:
            m = mult
            rep = n.get("repeat")
            if rep and rep.isdigit():
                m *= int(rep)
            counts[0 if n["type"] == "folder" else 1] += m
            walk(n["children"], m)
    walk(nodes, 1)
    return counts


def default_group(kind="template"):
    return {
        "id":              uuid.uuid4().hex[:8],
        "name":            "",
        "color":           GROUP_COLORS[0],
        "kind":            kind,          # "template" | "marketplace"
        "base_path":       "",
        "template":        DEFAULT_TEMPLATE,
        "dest_pattern":    "",            # marketplace: subpasta destino
        "prefix":          "",            # marketplace: prefixo do código
        "board_id":        "",
        "list_aguardando": "",
        "list_dev":        "",
    }


def preset_marketplace_groups(cfg_v1=None):
    """Grupos do preset Shopee/ML (reaproveita config v1 quando existir)."""
    c = cfg_v1 or {}
    shopee = default_group("marketplace")
    shopee.update({
        "name": "Shopee", "color": "#ff6b35",
        "base_path":       c.get("shopee_base", ""),
        "dest_pattern":    "Shopee {ano}/{mes} - SHOPEE",
        "prefix":          "",
        "board_id":        c.get("shopee_board_id", ""),
        "list_aguardando": c.get("shopee_list_aguardando", ""),
        "list_dev":        c.get("shopee_list_dev_id", ""),
    })
    ml = default_group("marketplace")
    ml.update({
        "name": "Mercado Livre", "color": "#4f8fff",
        "base_path":       c.get("ml_base", ""),
        "dest_pattern":    "ML - {ano}/{mes}",
        "prefix":          "A",
        "board_id":        c.get("ml_board_id", ""),
        "list_aguardando": c.get("ml_list_aguardando", ""),
        "list_dev":        c.get("ml_list_dev_id", ""),
    })
    return [shopee, ml]


def migrate_config(cfg):
    """Config v1 (Shopee/ML fixos) → v2 (grupos). Chaves antigas são mantidas
    no arquivo para permitir voltar à versão 1.1.0 sem perder nada."""
    if cfg.get("config_version", 1) >= 2 and "groups" in cfg:
        return cfg, False
    if not cfg.get("groups"):
        if cfg.get("shopee_base") or cfg.get("ml_base") or cfg.get("trello_key"):
            cfg["groups"] = preset_marketplace_groups(cfg)
        else:
            cfg["groups"] = []
    cfg["config_version"] = 2
    return cfg, True


def load_config():
    cfg = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = {**DEFAULT_CONFIG, **json.load(f)}
        except Exception:
            pass
    cfg, migrated = migrate_config(cfg)
    if migrated and os.path.exists(CONFIG_FILE):
        save_config(cfg)
    return cfg


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# ONEDRIVE
# ═══════════════════════════════════════════════════════════════════════════════
def _onedrive_exe():
    return os.path.join(os.environ.get("LOCALAPPDATA", ""),
                        "Microsoft", "OneDrive", "OneDrive.exe")


def pause_onedrive():
    exe = _onedrive_exe()
    if os.path.exists(exe):
        subprocess.run([exe, "/shutdown"], capture_output=True)
        time.sleep(1.5)


def resume_onedrive():
    exe = _onedrive_exe()
    if os.path.exists(exe):
        subprocess.Popen([exe])


# ═══════════════════════════════════════════════════════════════════════════════
# MOTOR DE TEMPLATES (DSL de estrutura de pastas)
# ═══════════════════════════════════════════════════════════════════════════════
class TemplateError(Exception):
    pass


class _Fmt(string.Formatter):
    def get_value(self, key, args, kwargs):
        if isinstance(key, str):
            if key not in kwargs:
                raise TemplateError(f"Variável {{{key}}} sem valor definido.")
            return kwargs[key]
        return super().get_value(key, args, kwargs)

    def format_field(self, value, spec):
        if spec and spec[-1] in "dxXob" and isinstance(value, str):
            try:
                value = int(value)
            except ValueError:
                raise TemplateError(
                    f"Valor '{value}' não é número, mas o formato ':{spec}' exige número.")
        return super().format_field(value, spec)


_FMT = _Fmt()


def fmt(text, variables):
    try:
        return _FMT.vformat(text, (), variables)
    except TemplateError:
        raise
    except (ValueError, IndexError) as e:
        raise TemplateError(f"Formato inválido em '{text}': {e}")


_REPEAT_RE = re.compile(r'^\[\s*(\d+|\{[A-Za-z_]\w*\})\s*\]\s*(.+)$')
_VAR_RE    = re.compile(r'\{([A-Za-z_]\w*)(?::[^{}]*)?\}')
_SEQ_RE    = re.compile(r'\{seq(?::[^}]*)?\}')
_BAD_CHARS = re.compile(r'[<>:"|?*\\/]')


def parse_template(text):
    """Converte o texto do modelo em árvore de nós.
    Nó: {type, name, content, repeat, children, line}"""
    root = {"type": "folder", "name": "", "children": [], "line": 0}
    stack = [(-1, root)]
    for ln, raw in enumerate(text.splitlines(), 1):
        line = raw.replace("\t", "  ").rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        body = line.strip()

        repeat = None
        m = _REPEAT_RE.match(body)
        if m:
            repeat, body = m.group(1), m.group(2).strip()
        elif body.startswith("["):
            raise TemplateError(
                f"Linha {ln}: repetição inválida — use [N] Nome/ ou "
                "[{variavel}] Nome/ (ex.: [200] Pasta {seq:04d}/).")

        while stack and stack[-1][0] >= indent:
            stack.pop()
        if not stack:
            raise TemplateError(f"Linha {ln}: indentação inválida.")
        parent = stack[-1][1]
        if parent["type"] == "file":
            raise TemplateError(
                f"Linha {ln}: um arquivo não pode conter itens dentro dele.")

        if body.lower().startswith("copiar:"):
            rest = body[7:].strip()
            if " -> " in rest:
                src, dest = rest.split(" -> ", 1)
            else:
                src, dest = rest, ""
            src = src.strip().strip('"')
            dest = dest.strip()
            if not src:
                raise TemplateError(
                    f"Linha {ln}: 'copiar:' precisa do caminho do arquivo.")
            node = {"type": "copy", "name": dest or os.path.basename(src),
                    "content": None, "src": src, "repeat": repeat,
                    "children": [], "line": ln}
        elif body.endswith("/"):
            name = body[:-1].strip()
            if not name:
                raise TemplateError(f"Linha {ln}: pasta sem nome.")
            node = {"type": "folder", "name": name, "content": None,
                    "repeat": repeat, "children": [], "line": ln}
        else:
            if " = " in body:
                name, content = body.split(" = ", 1)
                name, content = name.strip(), content.strip()
                if (len(content) >= 2 and content[0] == content[-1]
                        and content[0] in "\"'"):
                    content = content[1:-1]
            else:
                name, content = body, ""
            if not name:
                raise TemplateError(f"Linha {ln}: arquivo sem nome.")
            node = {"type": "file", "name": name, "content": content,
                    "repeat": repeat, "children": [], "line": ln}

        # valida caracteres proibidos nas partes literais do nome
        literal = _VAR_RE.sub("", node["name"])
        bad = _BAD_CHARS.search(literal)
        if bad:
            raise TemplateError(
                f"Linha {ln}: caractere inválido '{bad.group(0)}' no nome.")

        parent["children"].append(node)
        stack.append((indent, node))

    if not root["children"]:
        raise TemplateError("O modelo está vazio — adicione pelo menos uma linha.")
    return root["children"]


def collect_variables(nodes):
    """Variáveis usadas no modelo, na ordem em que aparecem ({seq} não conta)."""
    found = []

    def _walk(ns):
        for n in ns:
            sources = [n["name"], n.get("content") or "", n.get("src") or ""]
            if n.get("repeat"):
                sources.append(n["repeat"])
            for s in sources:
                for m in _VAR_RE.finditer(s):
                    v = m.group(1)
                    if v != "seq" and v not in found:
                        found.append(v)
            _walk(n["children"])

    _walk(nodes)
    return found


def builtin_vars():
    now = datetime.datetime.now()
    return {
        "ano":     str(now.year),
        "mes_num": f"{now.month:02d}",
        "mes":     MESES[now.month - 1],
        "data":    now.strftime("%d-%m-%Y"),
    }


def _seq_start(dest, raw_name, variables):
    """Maior {seq} já existente no destino para esse padrão de nome + 1."""
    sentinel = "\x00"
    rendered = fmt(_SEQ_RE.sub(sentinel, raw_name), variables)
    pat = re.compile(
        "^" + re.escape(rendered).replace(re.escape(sentinel), r"(\d+)") + "$",
        re.IGNORECASE)
    maior = 0
    if os.path.isdir(dest):
        for entry in os.listdir(dest):
            m = pat.match(entry)
            if m:
                try:
                    maior = max(maior, int(m.group(1)))
                except ValueError:
                    pass
    return maior + 1


def _resolve_repeat(repeat, variables):
    if repeat.startswith("{"):
        val = fmt(repeat, variables)
    else:
        val = repeat
    try:
        n = int(str(val).strip())
        assert 1 <= n <= 100000
        return n
    except Exception:
        raise TemplateError(f"Repetição inválida: [{repeat}] → '{val}' "
                            "(precisa ser um número entre 1 e 100000).")


def execute_template(nodes, dest, variables, *, dry=False,
                     continue_seq=True, preview_limit=300):
    """Cria (ou simula, com dry=True) a estrutura no destino.
    Retorna {folders, files, skipped, preview[]}"""
    stats = {"folders": 0, "files": 0, "skipped": 0, "preview": []}

    def _preview_add(rel, is_folder):
        if len(stats["preview"]) < preview_limit:
            stats["preview"].append(rel + ("/" if is_folder else ""))
        elif len(stats["preview"]) == preview_limit:
            stats["preview"].append("… (lista resumida)")

    def _clean_name(node, vars_):
        name = fmt(node["name"], vars_).strip()
        if not name or _BAD_CHARS.search(name) or name in (".", ".."):
            raise TemplateError(
                f"Linha {node['line']}: nome resultante inválido: '{name}'")
        return name

    def _make(node, base, vars_, rel):
        name = _clean_name(node, vars_)
        path = os.path.join(base, name)
        rpath = os.path.join(rel, name) if rel else name
        if node["type"] == "folder":
            if os.path.isdir(path):
                stats["skipped"] += 1
            else:
                stats["folders"] += 1
                _preview_add(rpath, True)
                if not dry:
                    os.makedirs(path, exist_ok=True)
            _exec(node["children"], path, vars_, rpath)
        elif node["type"] == "copy":
            src = fmt(node.get("src") or "", vars_).strip()
            if not os.path.isfile(src):
                raise TemplateError(
                    f"Anexo não encontrado: {src}\n"
                    f"(linha {node['line']} — escolha o arquivo de novo)")
            if os.path.exists(path):
                stats["skipped"] += 1
            else:
                stats["files"] += 1
                _preview_add(rpath, False)
                if not dry:
                    os.makedirs(base, exist_ok=True)
                    shutil.copyfile(src, path)
        else:
            if os.path.exists(path):
                stats["skipped"] += 1
            else:
                stats["files"] += 1
                _preview_add(rpath, False)
                if not dry:
                    os.makedirs(base, exist_ok=True)
                    content = fmt(node.get("content") or "", vars_)
                    content = content.replace("\\n", "\n")
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(content)

    def _exec(nodes_, base, vars_, rel=""):
        for node in nodes_:
            if node.get("repeat"):
                count = _resolve_repeat(node["repeat"], vars_)
                uses_seq = bool(_SEQ_RE.search(node["name"]))
                start = 1
                if uses_seq and continue_seq:
                    start = _seq_start(base, node["name"], vars_)
                for i in range(count):
                    _make(node, base, {**vars_, "seq": start + i}, rel)
            else:
                _make(node, base, vars_, rel)

    _exec(nodes, dest, dict(variables))
    return stats


# ═══════════════════════════════════════════════════════════════════════════════
# LÓGICA MARKETPLACE (fluxo Shopee/ML legado — preservado)
# ═══════════════════════════════════════════════════════════════════════════════
def maior_numero_no_mes(pasta_mes, prefixo, mes_num):
    maior = 0
    if not os.path.exists(pasta_mes):
        return 0
    pat = re.compile(r'^' + re.escape(mes_num) + r'(\d+)[A-Z]+$')
    for nome in os.listdir(pasta_mes):
        if not os.path.isdir(os.path.join(pasta_mes, nome)):
            continue
        cod = nome.split(" - ")[0]
        if prefixo and cod.startswith(prefixo):
            cod = cod[len(prefixo):]
        m = pat.match(cod)
        if m:
            try:
                maior = max(maior, int(m.group(1)))
            except ValueError:
                pass
    return maior


def mp_destino(group, ano, mes):
    sub = fmt(group.get("dest_pattern") or "", {
        "ano": ano, "mes": mes, "mes_num": mes[:2]})
    return os.path.join(group["base_path"], sub) if sub else group["base_path"]


def criar_lote(group, ano, mes, itens, log_fn, pause_od):
    base    = group["base_path"]
    destino = mp_destino(group, ano, mes)
    prefixo = group.get("prefix", "")
    if not os.path.exists(base):
        log_fn(f"ERRO: Caminho base não encontrado:\n{base}", erro=True)
        return 0
    mes_num = mes[:2]
    if pause_od:
        log_fn("Pausando OneDrive...")
        pause_onedrive()
    total = 0
    try:
        os.makedirs(destino, exist_ok=True)
        log_fn("Verificando numeração do mês...")
        num = maior_numero_no_mes(destino, prefixo, mes_num)
        log_fn(f"Último número no mês: {num if num else 'nenhum — começando do 0001'}")
        for responsavel, qtd in itens:
            log_fn(f"── {responsavel}: {qtd} pasta(s)")
            for _ in range(qtd):
                num += 1
                codigo     = f"{prefixo}{mes_num}{num:04d}{responsavel}"
                nome_pasta = f"{codigo} - Vazio"
                path_pasta = os.path.join(destino, nome_pasta)
                ja_existe = any(
                    f.split(" - ")[0].upper() == codigo.upper()
                    for f in os.listdir(destino)
                    if os.path.isdir(os.path.join(destino, f)))
                if not ja_existe:
                    os.makedirs(path_pasta)
                    os.makedirs(os.path.join(path_pasta, "#ENVIAR"))
                    log_fn(f"  Criado: {nome_pasta}")
                    total += 1
                else:
                    log_fn(f"  Já existe, pulando: {codigo}", aviso=True)
        return total
    finally:
        if pause_od:
            log_fn("Retomando OneDrive...")
            resume_onedrive()


def buscar_pasta_por_codigo(bases, codigo):
    codigo = codigo.strip().upper()
    for base in bases:
        if not base or not os.path.exists(base):
            continue
        for root, dirs, _ in os.walk(base):
            for d in dirs:
                if d.split(" - ")[0].upper() == codigo:
                    return os.path.join(root, d), d
    return None, None


def renomear_pasta(path_atual, nome_cliente):
    dir_pai    = os.path.dirname(path_atual)
    codigo     = os.path.basename(path_atual).split(" - ")[0]
    novo_path  = os.path.join(dir_pai, f"{codigo} - {nome_cliente.strip()}")
    os.rename(path_atual, novo_path)
    return novo_path


def gerar_relatorio(group, ano, mes):
    destino = mp_destino(group, ano, mes)
    prefixo = group.get("prefix", "")
    resultado = {
        "destino": destino, "total": 0, "vazio": 0,
        "com_cliente": 0, "com_arquivo": 0, "sem_arquivo": 0,
        "por_pessoa": {}, "lista": [],
    }
    if not os.path.exists(destino):
        return resultado
    for nome in sorted(os.listdir(destino)):
        if not os.path.isdir(os.path.join(destino, nome)):
            continue
        partes = nome.split(" - ", 1)
        if len(partes) < 2:
            continue
        codigo, cliente = partes[0], partes[1]
        cod_s = codigo[len(prefixo):] if prefixo and codigo.startswith(prefixo) else codigo
        iniciais = ""
        for ch in reversed(cod_s):
            if ch.isalpha():
                iniciais = ch + iniciais
            else:
                break
        is_vazio    = cliente.strip().upper() == "VAZIO"
        path_enviar = os.path.join(destino, nome, "#ENVIAR")
        tem_arquivo = (os.path.exists(path_enviar) and
                       any(os.path.isfile(os.path.join(path_enviar, f))
                           for f in os.listdir(path_enviar)))
        resultado["total"] += 1
        resultado["vazio" if is_vazio else "com_cliente"] += 1
        resultado["com_arquivo" if tem_arquivo else "sem_arquivo"] += 1
        if iniciais:
            resultado["por_pessoa"][iniciais] = resultado["por_pessoa"].get(iniciais, 0) + 1
        resultado["lista"].append({
            "codigo": codigo, "cliente": cliente,
            "vazio": is_vazio, "tem_arquivo": tem_arquivo,
        })
    return resultado


# ═══════════════════════════════════════════════════════════════════════════════
# ÍNDICE LOCAL (busca instantânea em todos os grupos)
# ═══════════════════════════════════════════════════════════════════════════════
def build_index(groups, progress_fn=None):
    index = {}
    for g in groups:
        base = g.get("base_path", "")
        if not base or not os.path.exists(base):
            continue
        label = g["name"].upper()
        for root, dirs, _ in os.walk(base):
            for d in dirs:
                if " - " not in d:
                    continue
                codigo  = d.split(" - ")[0].upper()
                cliente = d.split(" - ", 1)[1]
                index[codigo] = {
                    "path":    os.path.join(root, d),
                    "nome":    d,
                    "plat":    label,
                    "cliente": cliente,
                }
                if progress_fn:
                    progress_fn(d)
    return index


def load_index():
    if os.path.exists(INDEX_FILE):
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_index(index):
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# TRELLO API
# ═══════════════════════════════════════════════════════════════════════════════
def _trello_get(endpoint, key, token, params=None):
    qs  = urllib.parse.urlencode({"key": key, "token": token, **(params or {})})
    url = f"https://api.trello.com/1{endpoint}?{qs}"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _trello_put(endpoint, key, token, fields):
    data = urllib.parse.urlencode({"key": key, "token": token, **fields}).encode("utf-8")
    url  = f"https://api.trello.com/1{endpoint}"
    req  = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def trello_get_boards(key, token):
    return _trello_get("/members/me/boards", key, token, {"fields": "name,id"})


def trello_get_list_cards(list_id, key, token):
    return _trello_get(f"/lists/{list_id}/cards", key, token,
                       {"fields": "name,id,idList,desc"})


def trello_get_list_name(list_id, key, token):
    r = _trello_get(f"/lists/{list_id}", key, token, {"fields": "name"})
    return r.get("name", "")


def trello_search_cards(query, board_id, key, token):
    r = _trello_get("/search", key, token, {
        "query": query, "idBoards": board_id,
        "modelTypes": "cards", "cards_limit": 10,
        "card_fields": "name,id,idList,idBoard,desc",
    })
    return r.get("cards", [])


def trello_update_card_name(card_id, new_name, key, token):
    return _trello_put(f"/cards/{card_id}", key, token, {"name": new_name})


def trello_move_card(card_id, list_id, key, token):
    return _trello_put(f"/cards/{card_id}", key, token, {"idList": list_id})


def trello_keys_ok(cfg):
    return bool(cfg.get("trello_key") and cfg.get("trello_token"))


def group_trello_ok(cfg, group):
    return trello_keys_ok(cfg) and bool(group.get("board_id"))


# ═══════════════════════════════════════════════════════════════════════════════
# AUTO-UPDATE via GitHub Releases
# ═══════════════════════════════════════════════════════════════════════════════
def _ver_tuple(v):
    """'2.0.0' → (2, 0, 0). Versão que não dá pra ler vira (0,) — nunca é 'mais nova'."""
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:3]) if nums else (0,)


def check_update(cfg, root):
    repo = cfg.get("github_repo", "").strip().strip("/")
    if not repo or "/" not in repo:
        return
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases/latest",
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": APP_NAME})
        with urllib.request.urlopen(req, timeout=8) as r:
            rel = json.loads(r.read())
        latest = rel.get("tag_name", "").lstrip("vV").strip()
        # só oferece se a release for realmente MAIS NOVA (nunca downgrade)
        if not latest or _ver_tuple(latest) <= _ver_tuple(APP_VERSION):
            return
        exe_url = None
        for a in rel.get("assets", []):
            if a.get("name", "").lower().endswith(".exe"):
                exe_url = a.get("browser_download_url")
                break

        def _perguntar():
            if messagebox.askyesno(
                    "Atualização disponível",
                    f"Nova versão {latest} disponível!\n"
                    f"(Você está na {APP_VERSION})\n\n"
                    f"Atualizar agora? O programa reinicia sozinho."):
                threading.Thread(target=_aplicar_update,
                                 args=(exe_url, repo, root), daemon=True).start()
        root.after(0, _perguntar)
    except Exception:
        pass   # sem internet ou repo errado — falha silenciosa


def _aplicar_update(exe_url, repo, root):
    try:
        if getattr(sys, "frozen", False):
            if not exe_url:
                root.after(0, lambda: messagebox.showwarning(
                    "Atualização",
                    "A nova versão ainda não tem o .exe publicado.\n"
                    "Tente novamente mais tarde."))
                return
            exe_atual = sys.executable
            exe_novo  = exe_atual + ".new"
            with urllib.request.urlopen(exe_url, timeout=120) as r, \
                 open(exe_novo, "wb") as f:
                f.write(r.read())
            bat = os.path.join(os.path.dirname(exe_atual), "_folderflow_update.bat")
            with open(bat, "w") as f:
                f.write(
                    "@echo off\n"
                    ":loop\n"
                    "timeout /t 1 /nobreak >nul\n"
                    f'del "{exe_atual}" 2>nul\n'
                    f'if exist "{exe_atual}" goto loop\n'
                    f'move "{exe_novo}" "{exe_atual}" >nul\n'
                    f'start "" "{exe_atual}"\n'
                    'del "%~f0"\n')
            subprocess.Popen(["cmd", "/c", bat],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            root.after(0, root.destroy)
        else:
            url_py = f"https://raw.githubusercontent.com/{repo}/main/folderflow.py"
            with urllib.request.urlopen(url_py, timeout=30) as r:
                conteudo = r.read()
            caminho = os.path.abspath(__file__)
            tmp = caminho + ".tmp"
            with open(tmp, "wb") as f:
                f.write(conteudo)
            os.replace(tmp, caminho)
            root.after(0, lambda: messagebox.showinfo(
                "Atualizado!",
                "Programa atualizado com sucesso!\n\n"
                "Feche e abra novamente para usar a nova versão."))
    except Exception as e:
        root.after(0, lambda e=e: messagebox.showerror("Erro na atualização", str(e)))


# ═══════════════════════════════════════════════════════════════════════════════
# PALETA
# ═══════════════════════════════════════════════════════════════════════════════
# Zinc dark theme (padrão Vercel/Linear/VS Code)
BG_MAIN  = "#09090b"   # fundo principal
BG_CARD  = "#121215"   # painéis / containers
BG_PANEL = "#121215"
BG_NODE  = "#18181b"   # blocos de nó do construtor
BG_INPUT = "#1f1f23"
BG_HOVER = "#27272a"
BORDER   = "#27272a"   # bordas e divisores (1px)
BORDER_S = "#27272a"
ACCENT   = "#84cc16"   # lime — usado com moderação (ações e badges)
ACCENT_H = "#a3e635"
ACCENT_DK   = "#3f6212"   # lime-800 — seleção com texto claro legível
ACCENT_DK_H = "#4d7c0f"
SEQ_BG   = "#232a1b"   # lime a 10% sobre o nó (badge de sequência)
SEQ_BD   = "#2e3c1a"   # lime a 20% (borda do badge)
SEQ_FG   = "#a3e635"
YELLOW   = "#f5c518"
BLUE     = "#4f8fff"
RED      = "#ff4455"
GREEN    = "#22c55e"
CYAN     = "#00ccdd"
FG_MAIN  = "#fafafa"   # texto primário
FG_DIM   = "#52525b"
FG_LABEL = "#a1a1aa"   # texto secundário / muted
DARK_TXT = "#101014"

MONO = ("Consolas", 11)


def F(size=13, bold=False):
    return ctk.CTkFont(family="Segoe UI", size=size,
                       weight="bold" if bold else "normal")


def darker(hex_color, factor=0.8):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % (int(r*factor), int(g*factor), int(b*factor))


def make_textbox(parent, height=140):
    tb = ctk.CTkTextbox(parent, height=height, fg_color=BG_CARD,
                        text_color=CYAN, corner_radius=12,
                        border_width=1, border_color=BORDER,
                        font=ctk.CTkFont(family="Consolas", size=12))
    for tag, cor in (("ok", GREEN), ("aviso", YELLOW), ("erro", RED),
                     ("dim", FG_LABEL), ("titulo", YELLOW), ("pessoa", CYAN),
                     ("normal", FG_MAIN)):
        try:
            tb.tag_config(tag, foreground=cor)
        except Exception:
            try:
                tb._textbox.tag_config(tag, foreground=cor)
            except Exception:
                pass
    tb.configure(state="disabled")
    return tb


def tb_write(tb, msg, tag="dim", timestamp=True):
    tb.configure(state="normal")
    prefix = f"[{datetime.datetime.now():%H:%M:%S}] " if timestamp else ""
    tb.insert("end", f"{prefix}{msg}\n", tag)
    tb.see("end")
    tb.configure(state="disabled")


def tb_clear(tb):
    tb.configure(state="normal")
    tb.delete("1.0", "end")
    tb.configure(state="disabled")


def serialize_template(nodes):
    """Árvore de nós → texto do modelo (inverso de parse_template)."""
    lines = []

    def walk(ns, depth):
        for n in ns:
            ind = "  " * depth
            rep = f"[{n['repeat']}] " if n.get("repeat") else ""
            if n["type"] == "folder":
                lines.append(f"{ind}{rep}{n['name']}/")
            elif n["type"] == "copy":
                src = n.get("src", "")
                sufixo = ("" if n["name"] == os.path.basename(src)
                          else f" -> {n['name']}")
                lines.append(f"{ind}{rep}copiar: {src}{sufixo}")
            else:
                c = n.get("content") or ""
                lines.append(f"{ind}{rep}{n['name']}" + (f" = {c}" if c else ""))
            walk(n["children"], depth + 1)

    walk(nodes, 0)
    return "\n".join(lines) + ("\n" if lines else "")


def new_node(tipo="folder", name="Nova pasta", repeat=None, content=None):
    return {"type": tipo, "name": name, "content": content,
            "repeat": repeat, "children": [], "line": 0}


# formatos de numeração amigáveis (rótulo → token {seq})
SEQ_FORMATS = [
    ("0001, 0002…", "{seq:04d}"),
    ("001, 002…",   "{seq:03d}"),
    ("01, 02…",     "{seq:02d}"),
    ("1, 2…",       "{seq}"),
]


class Tooltip:
    """Dica flutuante discreta ao passar o mouse."""
    def __init__(self, widget, text, delay=450):
        self.widget, self.text, self.delay = widget, text, delay
        self.tip = None
        self._id = None
        try:
            widget.bind("<Enter>", self._schedule, add="+")
            widget.bind("<Leave>", self._hide, add="+")
            widget.bind("<Button-1>", self._hide, add="+")
        except NotImplementedError:
            pass   # alguns widgets ctk não expõem bind — sem tooltip neles

    def _schedule(self, _e=None):
        self._cancel()
        self._id = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._id:
            try:
                self.widget.after_cancel(self._id)
            except Exception:
                pass
            self._id = None

    def _show(self):
        if self.tip:
            return
        try:
            x = self.widget.winfo_rootx() + 8
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            self.tip = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.attributes("-topmost", True)
            tw.configure(bg=BORDER_S)
            tk.Label(tw, text=self.text, bg=BG_PANEL, fg="#c9cfdd",
                     font=("Segoe UI", 9), justify="left", padx=8, pady=5,
                     wraplength=280).pack(padx=1, pady=1)
            tw.wm_geometry(f"+{x}+{y}")
        except Exception:
            self.tip = None

    def _hide(self, _e=None):
        self._cancel()
        if self.tip:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None


def make_switch(parent, **kw):
    """CTkSwitch 6.0 não posiciona o knob conforme a variable inicial —
    força a sincronização visual logo após criar."""
    sw = ctk.CTkSwitch(parent, **kw)
    var = kw.get("variable")
    try:
        if var is not None:
            (sw.select if var.get() else sw.deselect)()
    except Exception:
        pass
    return sw


def abrir_no_explorer(path, mesma_janela=True):
    # filedialog devolve caminhos com "/" — o Explorer exige "\" (senão abre Documentos)
    path = os.path.normpath(path)
    if mesma_janela:
        ps = (
            f'$path = "{path}";'
            f'$shell = New-Object -ComObject Shell.Application;'
            f'$wins = @($shell.Windows());'
            f'if ($wins.Count -gt 0) {{ $wins[0].Navigate($path) }}'
            f'else {{ explorer $path }}')
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
            creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        subprocess.Popen(["explorer", path])


# ═══════════════════════════════════════════════════════════════════════════════
# APP
# ═══════════════════════════════════════════════════════════════════════════════
class App(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=BG_MAIN)
        self.config_data = load_config()
        self.index_data  = load_index()

        self.watcher_active     = False
        self._watcher_processed = set()
        self._watcher_lines     = []
        self._watcher_tb        = None

        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("1120x740")
        self.minsize(960, 640)

        self.after(3000, lambda: threading.Thread(
            target=check_update, args=(self.config_data, self), daemon=True
        ).start())

        self._build_header()
        self.container = ctk.CTkFrame(self, fg_color=BG_MAIN, corner_radius=0)
        self.container.pack(fill="both", expand=True)
        self.show_home()

    # ── helpers ──────────────────────────────────────────────────────────────
    def _clear(self):
        for w in self.container.winfo_children():
            w.destroy()

    def groups(self):
        return self.config_data.get("groups", [])

    def save(self):
        save_config(self.config_data)

    # ── Header ───────────────────────────────────────────────────────────────
    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=58)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        left = ctk.CTkFrame(hdr, fg_color="transparent")
        left.pack(side="left", padx=18)
        # logo
        ctk.CTkLabel(left, text="🗂", width=32, height=32, fg_color=ACCENT_DK,
                     corner_radius=8, font=F(14)).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(left, text=APP_NAME, text_color=FG_MAIN,
                     font=F(15, True)).pack(side="left")
        # breadcrumb de rota
        self._crumb = ctk.CTkLabel(left, text="/  Início", text_color=FG_LABEL,
                                   font=F(12))
        self._crumb.pack(side="left", padx=(10, 0))

        right = ctk.CTkFrame(hdr, fg_color="transparent")
        right.pack(side="right", padx=12)

        self._nav_btns = {}

        def hbtn(text, cmd, width=40, nav_key=None):
            b = ctk.CTkButton(right, text=text, width=width, height=32,
                              fg_color="transparent", hover_color=BG_HOVER,
                              text_color=FG_LABEL, font=F(12, True),
                              corner_radius=16, border_width=0,
                              border_color=BORDER, command=cmd)
            if nav_key:
                self._nav_btns[nav_key] = b
            return b

        hbtn("ⓘ", self.open_sobre).pack(side="right", padx=2)
        hbtn("⚙", self.open_settings).pack(side="right", padx=2)
        self._watcher_chip = hbtn("○ watcher", self.open_watcher, width=90)
        self._watcher_chip.pack(side="right", padx=2)
        hbtn("⌕  Buscar", self.show_search, width=92,
             nav_key="buscar").pack(side="right", padx=3)
        hbtn("⌂  Início", self.show_home, width=86,
             nav_key="inicio").pack(side="right", padx=3)

    def _set_route(self, nav_key, crumb):
        self._crumb.configure(text=f"/  {crumb}")
        for k, b in self._nav_btns.items():
            if k == nav_key:
                b.configure(fg_color="#232327", text_color=FG_MAIN,
                            border_width=1)
            else:
                b.configure(fg_color="transparent", text_color=FG_LABEL,
                            border_width=0)

    def _update_watcher_chip(self):
        if self.watcher_active:
            self._watcher_chip.configure(text="● watcher", text_color=GREEN)
        else:
            self._watcher_chip.configure(text="○ watcher", text_color=FG_DIM)

    # ═════════════════════════════════════════════════════════════════════════
    # HOME — grade de grupos
    # ═════════════════════════════════════════════════════════════════════════
    def show_home(self):
        self._clear()
        self._set_route("inicio", "Início")
        wrap = ctk.CTkFrame(self.container, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=24, pady=16)

        tit = ctk.CTkFrame(wrap, fg_color="transparent")
        tit.pack(fill="x")
        ctk.CTkLabel(tit, text="Meus grupos", text_color=FG_MAIN,
                     font=F(24, True)).pack(anchor="w")
        ctk.CTkLabel(tit, text="Organize e crie estruturas de pastas por grupo",
                     text_color=FG_LABEL, font=F(12)).pack(anchor="w")

        if not self.groups():
            self._home_empty(wrap)
            return

        # barra de ações: filtro + ordenação + novo grupo
        bar = ctk.CTkFrame(wrap, fg_color="transparent")
        bar.pack(fill="x", pady=(12, 8))

        filtro_var = tk.StringVar()
        busca = ctk.CTkEntry(bar, textvariable=filtro_var, width=240, height=34,
                             placeholder_text="Filtrar grupos…   (Ctrl+K)",
                             fg_color=BG_NODE, border_color=BORDER,
                             text_color=FG_MAIN, corner_radius=10, font=F(12))
        busca.pack(side="left")

        sort_var = tk.StringVar(
            value=self.config_data.get("home_sort", "Mais recentes"))
        ctk.CTkOptionMenu(bar, variable=sort_var,
                          values=["Mais recentes", "A–Z"], width=140, height=34,
                          fg_color=BG_NODE, button_color=BG_HOVER,
                          text_color=FG_LABEL, font=F(12), corner_radius=10,
                          dropdown_fg_color=BG_CARD,
                          command=lambda _v: _render()).pack(side="left",
                                                             padx=(8, 0))

        ctk.CTkButton(bar, text="＋  Novo grupo", height=36, corner_radius=10,
                      fg_color=ACCENT, hover_color=ACCENT_H, text_color=DARK_TXT,
                      font=F(12, True),
                      command=lambda: self.open_group_editor(None)
                      ).pack(side="right")

        grid = ctk.CTkScrollableFrame(wrap, fg_color="transparent")
        grid.pack(fill="both", expand=True)
        grid.grid_columnconfigure((0, 1, 2), weight=1, uniform="col")

        def _render(*_a):
            for w in grid.winfo_children():
                w.destroy()
            gs = list(self.groups())
            if sort_var.get() == "A–Z":
                gs.sort(key=lambda x: (x.get("name") or "").lower())
            else:
                gs = list(reversed(gs))
            termo = filtro_var.get().strip().lower()
            if termo:
                gs = [x for x in gs if termo in (x.get("name") or "").lower()]
            if self.config_data.get("home_sort") != sort_var.get():
                self.config_data["home_sort"] = sort_var.get()
                self.save()
            if not gs:
                ctk.CTkLabel(grid, text="Nenhum grupo com esse nome.",
                             text_color=FG_DIM, font=F(12)).grid(
                    row=0, column=0, columnspan=3, pady=32)
            for i, g in enumerate(gs):
                self._group_card(grid, g).grid(
                    row=i // 3, column=i % 3, sticky="nsew", padx=7, pady=7)

        filtro_var.trace_add("write", _render)
        self.bind_all("<Control-k>",
                      lambda e: busca.focus_set()
                      if busca.winfo_exists() else None)
        _render()

    def _home_empty(self, wrap):
        box = ctk.CTkFrame(wrap, fg_color=BG_CARD, corner_radius=20)
        box.pack(fill="both", expand=True, pady=10)
        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(inner, text="🗂", font=F(40)).pack(pady=(0, 6))
        ctk.CTkLabel(inner, text="Nenhum grupo ainda",
                     text_color=FG_MAIN, font=F(18, True)).pack()
        ctk.CTkLabel(inner,
                     text="Um grupo junta uma pasta base + um modelo de estrutura.\n"
                          "Crie um do zero ou use o preset de marketplace.",
                     text_color=FG_LABEL, font=F(12), justify="center"
                     ).pack(pady=(4, 16))
        ctk.CTkButton(inner, text="＋  Criar meu primeiro grupo", height=42,
                      corner_radius=21, fg_color=ACCENT, hover_color=ACCENT_H,
                      text_color=DARK_TXT, font=F(13, True),
                      command=lambda: self.open_group_editor(None)).pack(pady=3)
        ctk.CTkButton(inner, text="🛒  Preset Marketplace (Shopee + ML + Trello)",
                      height=38, corner_radius=19, fg_color=BG_INPUT,
                      hover_color=BG_HOVER, text_color=FG_MAIN, font=F(12),
                      command=self._add_preset).pack(pady=3)

    def _add_preset(self):
        self.config_data["groups"].extend(preset_marketplace_groups())
        self.save()
        self.show_home()

    def _delete_group(self, g, parent=None):
        if not messagebox.askyesno(
                "Excluir grupo",
                f"Excluir o grupo '{g['name']}'?\n\n"
                "As pastas no disco NÃO serão apagadas — só a configuração "
                "do grupo no app.", parent=parent or self):
            return False
        self.config_data["groups"].remove(g)
        self.save()
        self.show_home()
        return True

    def _group_card(self, parent, g):
        cor = g.get("color", ACCENT)
        card = ctk.CTkFrame(parent, fg_color=BG_NODE, corner_radius=12,
                            border_width=1, border_color=BORDER, height=152)
        card.grid_propagate(False)
        card.pack_propagate(False)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=14, pady=12)

        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text="●", text_color=cor, font=F(13, True)
                     ).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(top, text=g["name"] or "(sem nome)", text_color=FG_MAIN,
                     font=F(15, True), anchor="w").pack(side="left")

        def abtn(text, cmd, color=FG_DIM):
            return ctk.CTkButton(top, text=text, width=28, height=24,
                                 fg_color="transparent", hover_color=BG_HOVER,
                                 text_color=color, corner_radius=8, font=F(12),
                                 command=cmd)
        btn_del  = abtn("🗑", lambda: self._delete_group(g), RED)
        btn_del.pack(side="right")
        btn_edit = abtn("✎", lambda: self.open_group_editor(g))
        btn_edit.pack(side="right", padx=(0, 2))

        info = ("MARKETPLACE + TRELLO" if g["kind"] == "marketplace"
                else "ESTRUTURA")
        if g["kind"] == "template":
            c = template_counts(g.get("template"))
            info = ("⚠ modelo com erro" if c is None
                    else f"📁 {c[0]} pastas · 📄 {c[1]} arquivos")
        ctk.CTkLabel(inner, text=f"  {info}  ", text_color=cor,
                     fg_color="#1f1f23", corner_radius=8, font=F(10, True),
                     height=22).pack(anchor="w", pady=(6, 0))

        base = g.get("base_path") or "pasta base não definida"
        if len(base) > 40:
            base = "…" + base[-39:]
        ok = bool(g.get("base_path")) and os.path.exists(g["base_path"])
        ctk.CTkLabel(inner, text=("📁 " if ok else "⚠ ") + base,
                     text_color=FG_DIM, font=F(10), anchor="w"
                     ).pack(fill="x", pady=(4, 0))

        # rodapé com ações claras
        foot = ctk.CTkFrame(inner, fg_color="transparent")
        foot.pack(fill="x", side="bottom")
        ctk.CTkButton(foot, text="✎ Editar modelo", height=28, corner_radius=8,
                      fg_color="transparent", border_width=1,
                      border_color=BORDER, hover_color=BG_HOVER,
                      text_color=FG_LABEL, font=F(11),
                      command=lambda: self.show_group(g)
                      ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(foot, text="⚡ Criar agora", height=28, corner_radius=8,
                      fg_color=SEQ_BG, border_width=1, border_color=SEQ_BD,
                      hover_color=SEQ_BD, text_color=SEQ_FG, font=F(11, True),
                      command=lambda: self.quick_create(g)
                      ).pack(side="left", fill="x", expand=True, padx=(4, 0))

        def _open(_e=None):
            self.show_group(g)

        def _hover(on):
            try:
                card.configure(border_color=cor if on else BORDER)
            except Exception:
                pass
        clickables = [card, inner, top] + [
            w for w in (*inner.winfo_children(), *top.winfo_children())
            if w not in (btn_edit, btn_del, top, foot)]
        for w in clickables:
            w.bind("<Button-1>", _open)
        for w in (card, inner, top, foot):
            w.bind("<Enter>", lambda e: _hover(True))
            w.bind("<Leave>", lambda e: _hover(False))
        return card

    def quick_create(self, g):
        """⚡ do card: cria a estrutura direto da home (se não faltar nada)."""
        if g["kind"] != "template":
            self.show_group(g)
            return
        base = g.get("base_path", "")
        if not base or not os.path.isdir(base):
            messagebox.showinfo(
                "Pasta base", "Defina a pasta base do grupo primeiro (✎).")
            return
        try:
            nodes = parse_template(g.get("template") or "")
            wanted = collect_variables(nodes)
            builtin = builtin_vars()
            if any(v not in builtin for v in wanted):
                self.show_group(g)   # tem variável para preencher — abre a tela
                return
            vars_ = {k: builtin[k] for k in wanted}
            st = execute_template(nodes, base, vars_, dry=True)
        except TemplateError as e:
            messagebox.showerror("Modelo", str(e))
            return
        if st["folders"] + st["files"] == 0:
            messagebox.showinfo("Nada a criar",
                                "Tudo do modelo já existe no destino.")
            return
        if not messagebox.askyesno(
                "⚡ Criar agora",
                f"Grupo: {g['name']}\nDestino: {base}\n\n"
                f"Criar {st['folders']} pasta(s) e {st['files']} arquivo(s)?\n"
                f"({st['skipped']} itens já existem e serão pulados)"):
            return
        pause = self.config_data.get("pause_onedrive", True)

        def task():
            try:
                if pause:
                    pause_onedrive()
                r = execute_template(nodes, base, vars_, dry=False)
                self.after(0, lambda: messagebox.showinfo(
                    "Concluído",
                    f"✓ {r['folders']} pasta(s) e {r['files']} arquivo(s) "
                    f"criados em:\n{base}"))
            except Exception as e:
                self.after(0, lambda e=e: messagebox.showerror("Erro", str(e)))
            finally:
                if pause:
                    resume_onedrive()
        threading.Thread(target=task, daemon=True).start()

    # ═════════════════════════════════════════════════════════════════════════
    # VISTA DE GRUPO
    # ═════════════════════════════════════════════════════════════════════════
    def _group_header(self, wrap, g):
        top = ctk.CTkFrame(wrap, fg_color="transparent")
        top.pack(fill="x", pady=(0, 10))
        ctk.CTkButton(top, text="←", width=38, height=34, corner_radius=10,
                      fg_color=BG_INPUT, hover_color=BG_HOVER, text_color=FG_MAIN,
                      font=F(15, True), command=self.show_home).pack(side="left")
        ctk.CTkLabel(top, text="  ●", text_color=g.get("color", ACCENT),
                     font=F(16, True)).pack(side="left")
        ctk.CTkLabel(top, text=f" {g['name']}", text_color=FG_MAIN,
                     font=F(20, True)).pack(side="left")

        ctk.CTkButton(top, text="✎ Editar", width=80, height=32, corner_radius=10,
                      fg_color=BG_INPUT, hover_color=BG_HOVER, text_color=FG_LABEL,
                      font=F(12), command=lambda: self.open_group_editor(g)
                      ).pack(side="right", padx=(6, 0))
        if g.get("base_path"):
            ctk.CTkButton(top, text="📂 Abrir base", width=100, height=32,
                          corner_radius=10, fg_color=BG_INPUT if False else BG_INPUT,
                          hover_color=BG_HOVER, text_color=FG_LABEL, font=F(12),
                          command=lambda: abrir_no_explorer(g["base_path"], False)
                          ).pack(side="right")

    def show_group(self, g):
        self._clear()
        self._set_route("inicio", g["name"] or "Grupo")
        wrap = ctk.CTkFrame(self.container, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=26, pady=16)
        self._group_header(wrap, g)

        if not g.get("base_path"):
            ctk.CTkLabel(wrap, text="⚠  Defina a pasta base deste grupo em ✎ Editar "
                                    "antes de criar estruturas.",
                         text_color=YELLOW, font=F(12)).pack(anchor="w", pady=(0, 8))

        if g["kind"] == "marketplace":
            self._build_marketplace_view(wrap, g)
        else:
            self._build_template_view(wrap, g)

    # ── Grupo tipo "template" ────────────────────────────────────────────────
    def _build_template_view(self, wrap, g):
        body = ctk.CTkFrame(wrap, fg_color="transparent")
        body.pack(fill="both", expand=True)

        left = ctk.CTkFrame(body, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right = ctk.CTkFrame(body, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))

        mode = [g.get("editor_mode", "visual")]
        try:
            state_nodes = parse_template(g.get("template") or DEFAULT_TEMPLATE)
        except TemplateError:
            state_nodes = []
            mode[0] = "text"

        # ═══ ESQUERDA — cabeçalho: modo + modelos prontos + ajuda ═══
        top_bar = ctk.CTkFrame(left, fg_color="transparent")
        top_bar.pack(fill="x")

        seg = ctk.CTkSegmentedButton(
            top_bar, values=["✦ Visual", "⌨ Texto"],
            height=28, corner_radius=8,
            fg_color=BG_INPUT, selected_color=ACCENT_DK,
            selected_hover_color=ACCENT_DK_H, unselected_color=BG_INPUT,
            unselected_hover_color=BG_HOVER, text_color=FG_MAIN,
            font=F(11, True), command=lambda v: _set_mode(v))
        seg.pack(side="left")
        Tooltip(seg, "Visual: monte a estrutura com botões, sem sintaxe.\n"
                     "Texto: modo avançado, digitação rápida.")

        vis_tools = ctk.CTkFrame(top_bar, fg_color="transparent")

        def vtool(text, cmd, tip):
            b = ctk.CTkButton(vis_tools, text=text, width=28, height=28,
                              corner_radius=8, fg_color="transparent",
                              hover_color=BG_HOVER, text_color=FG_DIM,
                              font=F(12), command=cmd)
            b.pack(side="left", padx=1)
            Tooltip(b, tip)

        def _set_all_collapsed(val):
            def walk(ns):
                for n in ns:
                    if n["children"]:
                        n["_collapsed"] = val
                        walk(n["children"])
            walk(state_nodes)
            _sync_visual()

        def _limpar_tudo():
            if not state_nodes:
                return
            if messagebox.askyesno(
                    "Limpar tudo",
                    "Remover TODOS os itens do modelo?\n"
                    "(nada é apagado do disco — só o modelo)"):
                state_nodes.clear()
                _sync_visual()
                _schedule_refresh()

        vtool("⌃", lambda: _set_all_collapsed(False), "Expandir tudo")
        vtool("⌄", lambda: _set_all_collapsed(True), "Recolher tudo")
        vtool("⌫", _limpar_tudo, "Limpar tudo (com confirmação)")

        ctk.CTkButton(top_bar, text="?", width=28, height=28, corner_radius=14,
                      fg_color="transparent", border_width=1, border_color=BORDER_S,
                      hover_color=BG_HOVER, text_color=FG_LABEL,
                      font=F(11, True), command=self.open_help).pack(side="right")
        modelo_menu = ctk.CTkOptionMenu(
            top_bar, values=list(READY_TEMPLATES), width=150, height=28,
            fg_color=BG_INPUT, button_color=BG_HOVER, button_hover_color=BORDER,
            text_color=FG_LABEL, font=F(11), dropdown_fg_color=BG_CARD,
            corner_radius=8, command=lambda name: _aplicar_modelo(name))
        modelo_menu.set("Modelos prontos")
        modelo_menu.pack(side="right", padx=(0, 8))

        # ═══ ESQUERDA — CONSTRUTOR VISUAL ═══
        vis_container = ctk.CTkFrame(left, fg_color=BG_PANEL, corner_radius=12,
                                     border_width=1, border_color=BORDER_S)

        vis_scroll = ctk.CTkScrollableFrame(vis_container, fg_color="transparent")
        vis_scroll.pack(fill="both", expand=True, padx=8, pady=8)

        _row_vars = []   # segura StringVars das linhas (evita garbage collection)
        _holder = [None]  # frame que contém as linhas atuais (troca atômica)
        _bp = [None]      # parent onde as linhas estão sendo construídas

        def _make_add_row():
            addf = ctk.CTkFrame(_bp[0], fg_color="transparent")
            addf.pack(fill="x", pady=(8, 4))

            def root_btn(text, width, cmd, tip):
                b = ctk.CTkButton(addf, text=text, width=width, height=28,
                                  corner_radius=14, fg_color="transparent",
                                  border_width=1, border_color=BORDER_S,
                                  hover_color=BG_HOVER, text_color=FG_LABEL,
                                  font=F(11), command=cmd)
                b.pack(side="left", padx=(8, 8))
                Tooltip(b, tip)

            root_btn("＋ 📁 Pasta", 110,
                     lambda: _add_node(state_nodes, "folder"),
                     "Adiciona uma pasta no nível raiz")
            root_btn("＋ 📄 Arquivo", 120,
                     lambda: _add_node(state_nodes, "file"),
                     "Adiciona um arquivo no nível raiz")
            root_btn("＋ 🔁 Sequência", 140,
                     lambda: _seq_popover(add_to=state_nodes),
                     "Cria várias pastas numeradas de uma vez\n"
                     "(ex.: Pasta 0001 … Pasta 0200)")
            root_btn("＋ 📎 Anexo", 110,
                     lambda: _add_copy(state_nodes),
                     "Copia um arquivo real (ex.: PDF gabarito)\n"
                     "para dentro do que for criado")

        def _sync_visual():
            # anti-flicker: constrói tudo num frame invisível e troca de uma vez,
            # preservando a posição do scroll
            try:
                ypos = vis_scroll._parent_canvas.yview()[0]
            except Exception:
                ypos = 0.0
            _row_vars.clear()
            old = _holder[0]
            newf = ctk.CTkFrame(vis_scroll, fg_color="transparent")
            _bp[0] = newf

            def add_rows(ns, depth, hidden):
                for n in ns:
                    outer = _make_row(n, ns, depth)
                    if hidden:
                        outer.pack_forget()
                    add_rows(n["children"], depth + 1,
                             hidden or bool(n.get("_collapsed")))
            add_rows(state_nodes, 0, False)
            if not state_nodes:
                ctk.CTkLabel(newf,
                             text="Estrutura vazia — use os botões abaixo\n"
                                  "para adicionar pastas e arquivos.",
                             text_color=FG_DIM, font=F(12), justify="center"
                             ).pack(pady=24)
            _make_add_row()

            if old is not None:
                old.destroy()
            newf.pack(fill="x")
            _holder[0] = newf

            def _restore():
                try:
                    vis_scroll._parent_canvas.yview_moveto(ypos)
                except Exception:
                    pass
            self.after(10, _restore)

        def _make_row(n, parent_list, depth):
            outer = ctk.CTkFrame(_bp[0], fg_color="transparent", height=40)
            outer.pack(fill="x", pady=2)
            outer.pack_propagate(False)

            # linhas-guia verticais (estilo IDE) conectando pai → filhos
            for _d in range(depth):
                tk.Frame(outer, width=1, bg=BORDER
                         ).pack(side="left", fill="y", padx=(12, 9))

            # bloco do nó: container discreto com borda e cantos arredondados
            row = ctk.CTkFrame(outer, fg_color=BG_NODE, corner_radius=8,
                               border_width=1, border_color=BORDER_S)
            row.pack(side="left", fill="both", expand=True, pady=1)

            is_folder = n["type"] == "folder"

            # seta de recolher/expandir (só pastas com conteúdo)
            chev = None
            if n["children"]:
                chev = ctk.CTkButton(
                    row, text="▸" if n.get("_collapsed") else "▾", width=20,
                    height=24, corner_radius=6, fg_color="transparent",
                    hover_color=BG_HOVER, text_color=FG_DIM, font=F(10),
                    command=lambda n=n: _toggle_anim(n))
                chev.pack(side="left", padx=(6, 0))
            else:
                ctk.CTkLabel(row, text="", width=20).pack(side="left",
                                                          padx=(6, 0))

            icon = {"folder": "📁", "file": "📄", "copy": "📎"}[n["type"]]
            extra = f"  ({len(n['children'])})" if n.get("_collapsed") else ""
            icon_lbl = ctk.CTkLabel(
                row, text=icon + extra, font=F(12),
                text_color=FG_DIM if n.get("_collapsed") else FG_MAIN)
            icon_lbl.pack(side="left", padx=(2, 4))
            if n["type"] == "copy":
                Tooltip(icon_lbl, "Anexo — será copiado de:\n" + n.get("src", "?"))

            # badge de sequência (clicável para editar)
            if n.get("repeat"):
                bt = ctk.CTkButton(row, text=f"🔁 ×{n['repeat']}", width=54,
                                   height=22, corner_radius=11,
                                   fg_color=SEQ_BG, border_width=1,
                                   border_color=SEQ_BD, text_color=SEQ_FG,
                                   hover_color=SEQ_BD, font=F(10, True),
                                   command=lambda: _seq_popover(node=n))
                bt.pack(side="left", padx=(0, 6))
                Tooltip(bt, "Repetição: clique para mudar a quantidade\n"
                            "ou o formato da numeração")

            token_m = _SEQ_RE.search(n["name"]) if n.get("repeat") else None
            token = token_m.group(0) if token_m else ""
            shown = _SEQ_RE.sub("", n["name"]).strip() if token else n["name"]
            sv = tk.StringVar(value=shown)
            _row_vars.append(sv)

            def _on_name(*_a, sv=sv, n=n, token=token):
                base = sv.get()
                n["name"] = (base.rstrip() + (" " + token if token else "")).strip() or base
                _schedule_refresh()
            sv.trace_add("write", _on_name)
            entry = ctk.CTkEntry(row, textvariable=sv, height=26,
                                 fg_color=BG_NODE, border_color=BG_NODE,
                                 text_color=FG_MAIN, font=F(12))
            entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

            # ações da linha: invisíveis até o mouse passar por cima (hover)
            reveal = []

            def rbtn(text, cmd, tip, color=FG_LABEL, sempre=False):
                b = ctk.CTkButton(row, text=text, width=28, height=26,
                                  corner_radius=8, fg_color="transparent",
                                  hover_color=BG_HOVER,
                                  text_color=color if sempre else BG_NODE,
                                  font=F(11), command=cmd)
                b.pack(side="right", padx=1)
                Tooltip(b, tip)
                if not sempre:
                    reveal.append((b, color))
                return b

            rbtn("🗑", lambda: _del_node(n, parent_list),
                 "Excluir este item do modelo", RED)
            if is_folder:
                rbtn("🔁", lambda: _seq_popover(node=n),
                     "Multiplicar: transforma em sequência numerada")
                rbtn("📎", lambda: _add_copy(n["children"]),
                     "Anexar um arquivo real (ex.: PDF gabarito)\n"
                     "que será copiado para dentro desta pasta")
                rbtn("＋📄", lambda: _add_node(n["children"], "file"),
                     "Adicionar arquivo de texto dentro desta pasta")
                rbtn("＋📁", lambda: _add_node(n["children"], "folder"),
                     "Adicionar subpasta dentro desta pasta")
            elif n["type"] == "copy":
                rbtn("📂", lambda: _change_copy_src(n),
                     "Trocar o arquivo de origem\nAtual: " + n.get("src", "?"))
            else:
                rbtn("✎", lambda: _content_popover(n),
                     "Editar o conteúdo (texto) do arquivo")

            def _reveal(on):
                for b, col in reveal:
                    try:
                        b.configure(text_color=col if on else BG_NODE)
                    except Exception:
                        pass

            def _still_inside():
                try:
                    w = outer.winfo_containing(*outer.winfo_pointerxy())
                    while w is not None:
                        if w is outer:
                            return True
                        w = w.master
                except Exception:
                    pass
                return False

            def _on_leave(_e=None):
                outer.after(90,
                            lambda: None if _still_inside() else _reveal(False))

            for w in (outer, row, entry, *row.winfo_children()):
                try:
                    w.bind("<Enter>", lambda _e: _reveal(True), add="+")
                    w.bind("<Leave>", _on_leave, add="+")
                except Exception:
                    pass

            n["_row"], n["_chev"], n["_icon"] = outer, chev, icon_lbl
            return outer

        # ── recolher/expandir instantâneo (esconde/mostra, sem reconstruir) ──
        def _visible_desc_rows(n):
            """Linhas descendentes que devem estar visíveis (respeita
            sub-pastas recolhidas)."""
            out = []

            def walk(ns):
                for c in ns:
                    r = c.get("_row")
                    if r is not None and r.winfo_exists():
                        out.append(r)
                    if c["children"] and not c.get("_collapsed"):
                        walk(c["children"])
            walk(n["children"])
            return out

        def _refresh_row_head(n):
            icon = {"folder": "📁", "file": "📄", "copy": "📎"}[n["type"]]
            extra = f"  ({len(n['children'])})" if n.get("_collapsed") else ""
            try:
                n["_icon"].configure(
                    text=icon + extra,
                    text_color=FG_DIM if n.get("_collapsed") else FG_MAIN)
                if n.get("_chev") is not None:
                    n["_chev"].configure(
                        text="▸" if n.get("_collapsed") else "▾")
            except Exception:
                pass

        def _toggle_anim(n):
            if not n.get("_collapsed"):
                rows = _visible_desc_rows(n)
                n["_collapsed"] = True
                _refresh_row_head(n)
                for r in rows:
                    try:
                        r.pack_forget()
                    except Exception:
                        pass
            else:
                n["_collapsed"] = False
                _refresh_row_head(n)
                anchor = n.get("_row")
                for r in _visible_desc_rows(n):
                    try:
                        r.pack(fill="x", pady=2, after=anchor)
                        anchor = r
                    except Exception:
                        pass

        def _add_node(target_list, tipo):
            nome = "Nova pasta" if tipo == "folder" else "arquivo.txt"
            target_list.append(new_node(tipo, nome))
            _sync_visual()
            _schedule_refresh()

        def _add_copy(target_list):
            p = filedialog.askopenfilename(
                parent=self, title="Escolher arquivo para anexar")
            if not p:
                return
            p = os.path.normpath(p)
            node = new_node("copy", os.path.basename(p))
            node["src"] = p
            target_list.append(node)
            _sync_visual()
            _schedule_refresh()

        def _change_copy_src(n):
            p = filedialog.askopenfilename(
                parent=self, title="Escolher arquivo de origem")
            if not p:
                return
            p = os.path.normpath(p)
            velho = os.path.basename(n.get("src", ""))
            n["src"] = p
            if n["name"] == velho:
                n["name"] = os.path.basename(p)
            _sync_visual()
            _schedule_refresh()

        def _del_node(n, parent_list):
            if n["children"] and not messagebox.askyesno(
                    "Excluir",
                    f"'{n['name']}' tem itens dentro. Excluir mesmo assim?\n"
                    "(só sai do modelo — nada é apagado do disco)"):
                return
            parent_list.remove(n)
            _sync_visual()
            _schedule_refresh()

        def _popover(titulo, altura=250):
            win = ctk.CTkToplevel(self, fg_color=BG_MAIN)
            win.title(titulo)
            x = max(self.winfo_pointerx() - 170, 40)
            y = max(self.winfo_pointery() + 12, 40)
            win.geometry(f"360x{altura}+{x}+{y}")
            win.resizable(False, False)
            win.grab_set()
            box = ctk.CTkFrame(win, fg_color="transparent")
            box.pack(fill="both", expand=True, padx=16, pady=16)
            ctk.CTkLabel(box, text=titulo, text_color=FG_MAIN, font=F(15, True)
                         ).pack(anchor="w", pady=(0, 8))
            return win, box

        def _pop_campo(box, rotulo, valor):
            ctk.CTkLabel(box, text=rotulo, text_color=FG_LABEL, font=F(11, True)
                         ).pack(anchor="w", pady=(8, 2))
            sv = tk.StringVar(value=valor)
            ctk.CTkEntry(box, textvariable=sv, height=32, fg_color=BG_INPUT,
                         border_color=BORDER_S, text_color=FG_MAIN, font=F(12)
                         ).pack(fill="x")
            return sv

        def _seq_popover(node=None, add_to=None):
            win, box = _popover("Criar sequência" if node is None
                                else "Editar sequência", altura=316)
            base_atual = "Pasta"
            qtd_atual  = "10"
            fmt_atual  = SEQ_FORMATS[0][0]
            if node is not None:
                base_atual = _SEQ_RE.sub("", node["name"]).strip() or node["name"]
                qtd_atual  = node.get("repeat") or "10"
                m = _SEQ_RE.search(node["name"])
                if m:
                    for rotulo, tok in SEQ_FORMATS:
                        if tok == m.group(0):
                            fmt_atual = rotulo
                            break

            base_var = _pop_campo(box, "NOME BASE", base_atual)
            qtd_var  = _pop_campo(box, "QUANTIDADE DE CÓPIAS", qtd_atual)
            ctk.CTkLabel(box, text="FORMATO DA NUMERAÇÃO", text_color=FG_LABEL,
                         font=F(11, True)).pack(anchor="w", pady=(8, 2))
            fmt_var = tk.StringVar(value=fmt_atual)
            ctk.CTkOptionMenu(box, variable=fmt_var,
                              values=[r for r, _ in SEQ_FORMATS], height=32,
                              fg_color=BG_INPUT, button_color=BG_HOVER,
                              text_color=FG_MAIN, font=F(12),
                              dropdown_fg_color=BG_CARD).pack(fill="x")

            def ok():
                base = base_var.get().strip()
                if not base:
                    messagebox.showerror("Sequência", "Dê um nome base.",
                                         parent=win)
                    return
                q = qtd_var.get().strip()
                if not (q.isdigit() and 1 <= int(q) <= 100000):
                    messagebox.showerror(
                        "Sequência",
                        "Quantidade precisa ser um número entre 1 e 100000.",
                        parent=win)
                    return
                token = dict(SEQ_FORMATS)[fmt_var.get()]
                if node is None:
                    add_to.append(new_node("folder", f"{base} {token}", repeat=q))
                else:
                    node["repeat"] = q
                    node["name"]   = f"{base} {token}"
                win.destroy()
                _sync_visual()
                _schedule_refresh()

            btns = ctk.CTkFrame(box, fg_color="transparent")
            btns.pack(fill="x", pady=(16, 0))
            ctk.CTkButton(btns, text="OK", height=32, width=110, corner_radius=8,
                          fg_color=ACCENT, hover_color=ACCENT_H,
                          text_color=DARK_TXT, font=F(12, True), command=ok
                          ).pack(side="right")
            if node is not None and node.get("repeat"):
                def remover():
                    node["repeat"] = None
                    node["name"]   = _SEQ_RE.sub("", node["name"]).strip()
                    win.destroy()
                    _sync_visual()
                    _schedule_refresh()
                ctk.CTkButton(btns, text="Remover repetição", height=32,
                              corner_radius=8, fg_color="transparent",
                              border_width=1, border_color=BORDER_S,
                              hover_color=BG_HOVER, text_color=FG_LABEL,
                              font=F(11), command=remover).pack(side="left")

        def _content_popover(n):
            win, box = _popover(f"Conteúdo de {n['name']}", altura=380)
            # botão e dica ancorados embaixo ANTES do textbox, para nunca
            # serem empurrados para fora da janela
            btn_ok = ctk.CTkButton(box, text="💾  Salvar", height=36, width=130,
                                   corner_radius=8, fg_color=ACCENT,
                                   hover_color=ACCENT_H, text_color=DARK_TXT,
                                   font=F(12, True))
            btn_ok.pack(side="bottom", anchor="e", pady=(8, 0))
            ctk.CTkLabel(box, text="Dica: pode usar variáveis como {seq} e {data}.",
                         text_color=FG_DIM, font=F(10)
                         ).pack(side="bottom", anchor="w", pady=(4, 0))
            tb = ctk.CTkTextbox(box, fg_color=BG_INPUT, text_color=FG_MAIN,
                                corner_radius=8, border_width=1,
                                border_color=BORDER_S,
                                font=ctk.CTkFont(family="Consolas", size=12))
            tb.pack(fill="both", expand=True)
            tb.insert("1.0", (n.get("content") or "").replace("\\n", "\n"))
            tb.focus_set()

            def ok():
                n["content"] = tb.get("1.0", "end-1c").strip().replace("\n", "\\n")
                win.destroy()
                _schedule_refresh()
            btn_ok.configure(command=ok)

        # ═══ ESQUERDA — MODO TEXTO (avançado) ═══
        text_container = ctk.CTkFrame(left, fg_color="transparent")

        pill_bar = ctk.CTkFrame(text_container, fg_color="transparent")
        pill_bar.pack(fill="x", pady=(0, 8))

        def pill(text, snippet, tip):
            def _ins():
                editor.insert("insert", snippet)
                editor.focus_set()
                _schedule_refresh()
            b = ctk.CTkButton(pill_bar, text=text, height=28, corner_radius=14,
                              fg_color="transparent", border_width=1,
                              border_color=BORDER_S, hover_color=BG_HOVER,
                              text_color=FG_LABEL, font=F(11), command=_ins)
            b.pack(side="left", padx=(0, 8))
            Tooltip(b, tip)

        pill("＋ Pasta", "Nova pasta/\n", "Insere uma pasta (termina com /)")
        pill("＋ Arquivo", "arquivo.txt = conteúdo\n",
             "Insere um arquivo (opcional: = conteúdo)")
        pill("＋ Sequência", "[10] Item {seq:03d}/\n",
             "Insere uma repetição: [N] repete N vezes,\n{seq:03d} vira 001, 002…")
        pill("＋ Variável", "{minha_variavel}",
             "Qualquer {nome} vira um campo preenchível")

        editor = ctk.CTkTextbox(text_container, fg_color=BG_PANEL,
                                text_color=FG_MAIN, corner_radius=12,
                                border_width=1, border_color=BORDER_S,
                                font=ctk.CTkFont(family="Consolas", size=12),
                                undo=True)
        editor.pack(fill="both", expand=True)
        editor.insert("1.0", g.get("template") or DEFAULT_TEMPLATE)

        # ═══ ESQUERDA — status, variáveis, opções ═══
        status_lbl = ctk.CTkLabel(left, text="", text_color=FG_DIM, font=F(11),
                                  anchor="w", wraplength=480, justify="left")

        vars_frame = ctk.CTkFrame(left, fg_color="transparent")
        var_entries = {}
        builtin = builtin_vars()

        opt_row = ctk.CTkFrame(left, fg_color="transparent")

        pause_var = tk.BooleanVar(value=self.config_data.get("pause_onedrive", True))
        sw1 = make_switch(opt_row, text="Pausar OneDrive", variable=pause_var,
                          progress_color=ACCENT, text_color=FG_LABEL, font=F(11))
        sw1.pack(side="left", padx=(0, 16))
        Tooltip(sw1, "Fecha o OneDrive durante a criação e reabre no fim.\n"
                     "Evita travamentos ao criar muitas pastas.")
        seq_var = tk.BooleanVar(value=True)
        sw2 = make_switch(opt_row, text="Continuar numeração", variable=seq_var,
                          command=lambda: _schedule_refresh(),
                          progress_color=ACCENT, text_color=FG_LABEL, font=F(11))
        sw2.pack(side="left")
        Tooltip(sw2, "Sequências continuam da maior numeração que já\n"
                     "existe na pasta (ex.: se há 0200, cria 0201 em diante).")

        # ordem de empacotamento fixa do rodapé esquerdo
        status_lbl.pack(fill="x", side="bottom", pady=(4, 0))
        opt_row.pack(fill="x", side="bottom", pady=(8, 0))
        vars_frame.pack_forget()

        # ═══ DIREITA — painel de pré-visualização ═══
        tree_box = ctk.CTkFrame(right, fg_color=BG_PANEL, corner_radius=12,
                                border_width=1, border_color=BORDER_S)
        tree_box.pack(fill="both", expand=True)

        head = ctk.CTkFrame(tree_box, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(12, 4))
        count_lbl = ctk.CTkLabel(head, text="", text_color=FG_LABEL, font=F(11))
        count_lbl.pack(side="left")
        btn_criar = ctk.CTkButton(head, text="✚  Criar estrutura", height=32,
                                  width=150, corner_radius=8, fg_color=ACCENT,
                                  hover_color=ACCENT_H, text_color=DARK_TXT,
                                  font=F(12, True))
        btn_criar.pack(side="right")
        Tooltip(btn_criar, "Cria no disco tudo o que está na pré-visualização")

        prev_wrap = ctk.CTkFrame(tree_box, fg_color="transparent")
        prev_wrap.pack(fill="both", expand=True, padx=16, pady=(4, 12))
        prev = tk.Text(prev_wrap, bg=BG_PANEL, fg=FG_MAIN, bd=0,
                       highlightthickness=0, wrap="none", cursor="arrow",
                       font=("Segoe UI", 10), spacing1=3, spacing3=3,
                       state="disabled")
        prev_sb = ctk.CTkScrollbar(prev_wrap, command=prev.yview)
        prev_sb.pack(side="right", fill="y")
        prev.pack(side="left", fill="both", expand=True)
        prev.configure(yscrollcommand=prev_sb.set)
        prev.tag_configure("guide", foreground="#2e2e33", font=("Consolas", 10))
        prev.tag_configure("folder", foreground=FG_MAIN)
        prev.tag_configure("file", foreground=FG_LABEL)
        prev.tag_configure("dim", foreground=FG_DIM)
        prev.tag_configure("hoverline", background="#1d1d20")

        def _prev_hover(e=None):
            prev.tag_remove("hoverline", "1.0", "end")
            if e is not None:
                line = prev.index(f"@{e.x},{e.y}").split(".")[0]
                if prev.get(f"{line}.0", f"{line}.end").strip():
                    prev.tag_add("hoverline", f"{line}.0", f"{line}.end+1c")

        prev.bind("<Motion>", _prev_hover)
        prev.bind("<Leave>", lambda e: _prev_hover(None))

        log_lbl = ctk.CTkLabel(right, text="", text_color=FG_DIM, font=F(11),
                               anchor="w", wraplength=480, justify="left")
        log_lbl.pack(fill="x", pady=(4, 0))

        # ═══ LÓGICA ═══
        MAX_INST = 3

        def _aplicar_modelo(name):
            modelo_menu.set("Modelos prontos")
            if name not in READY_TEMPLATES:
                return
            if not messagebox.askyesno(
                    "Modelo pronto",
                    f"Substituir a estrutura atual pelo modelo '{name}'?"):
                return
            editor.delete("1.0", "end")
            editor.insert("1.0", READY_TEMPLATES[name])
            state_nodes[:] = parse_template(READY_TEMPLATES[name])
            _sync_visual()
            _refresh()

        def _set_mode(value):
            m = "visual" if value.startswith("✦") else "text"
            if m == mode[0]:
                return
            if m == "text":
                txt = serialize_template(state_nodes)
                editor.delete("1.0", "end")
                editor.insert("1.0", txt or DEFAULT_TEMPLATE)
                vis_container.pack_forget()
                vis_tools.pack_forget()
                text_container.pack(fill="both", expand=True, pady=(8, 0))
            else:
                try:
                    nodes = parse_template(editor.get("1.0", "end-1c"))
                except TemplateError as e:
                    messagebox.showerror(
                        "Modo visual",
                        "Corrija o modelo antes de trocar para o visual:\n\n"
                        + str(e))
                    seg.set("⌨ Texto")
                    return
                state_nodes[:] = nodes
                _sync_visual()
                text_container.pack_forget()
                vis_tools.pack(side="left", padx=(8, 0))
                vis_container.pack(fill="both", expand=True, pady=(8, 0))
            mode[0] = m
            g["editor_mode"] = m
            self.save()
            _refresh()

        def _rebuild_vars(nodes):
            wanted = collect_variables(nodes)
            if list(var_entries.keys()) == wanted:
                return
            old = {k: v.get() for k, v in var_entries.items()}
            for w in vars_frame.winfo_children():
                w.destroy()
            var_entries.clear()
            if wanted:
                vars_frame.pack(fill="x", side="bottom", pady=(8, 0))
            else:
                vars_frame.pack_forget()
            row = None
            for i, name in enumerate(wanted):
                if i % 2 == 0:
                    row = ctk.CTkFrame(vars_frame, fg_color="transparent")
                    row.pack(fill="x", pady=2)
                cell = ctk.CTkFrame(row, fg_color="transparent")
                cell.pack(side="left", padx=(0, 16))
                ctk.CTkLabel(cell, text="{" + name + "}", text_color=ACCENT,
                             font=F(11, True)).pack(side="left", padx=(0, 6))
                sv = tk.StringVar(value=old.get(name, builtin.get(name, "")))
                sv.trace_add("write", lambda *_: _schedule_refresh())
                var_entries[name] = sv
                if name == "mes":
                    ctk.CTkOptionMenu(cell, variable=sv, values=MESES, width=160,
                                      height=28, fg_color=BG_INPUT,
                                      button_color=BG_HOVER, text_color=FG_MAIN,
                                      font=F(11), dropdown_fg_color=BG_CARD
                                      ).pack(side="left")
                else:
                    ctk.CTkEntry(cell, textvariable=sv, width=110, height=28,
                                 fg_color=BG_INPUT, border_color=BORDER_S,
                                 text_color=FG_MAIN, font=F(11)).pack(side="left")

        def _render_name(node, vars_):
            try:
                return fmt(node["name"], vars_).strip() or node["name"]
            except TemplateError:
                return node["name"]

        def _fill_tree(nodes, vars_):
            base = g.get("base_path", "")
            base_ok = bool(base) and os.path.isdir(base)
            try:
                ypos = prev.yview()[0]
            except Exception:
                ypos = 0.0
            prev.configure(state="normal")
            prev.delete("1.0", "end")

            def emit(depth, texto, tag):
                if depth:
                    prev.insert("end", "│  " * depth, ("guide",))
                prev.insert("end", texto + "\n", (tag,))

            def add(ns, vars2, dest, depth):
                for n in ns:
                    icon = {"folder": "📁 ", "file": "📄 ",
                            "copy": "📎 "}[n["type"]]
                    tag = "folder" if n["type"] == "folder" else "file"
                    rep = n.get("repeat")
                    if rep:
                        try:
                            count = _resolve_repeat(rep, vars2)
                        except TemplateError:
                            count = None
                        start = 1
                        if (count and seq_var.get() and base_ok and dest
                                and _SEQ_RE.search(n["name"])):
                            try:
                                start = _seq_start(dest, n["name"], vars2)
                            except TemplateError:
                                start = 1
                        shown = min(count or 1, MAX_INST)
                        for i in range(shown):
                            v3 = {**vars2, "seq": start + i}
                            name = _render_name(n, v3)
                            emit(depth, icon + name, tag)
                            add(n["children"], v3,
                                os.path.join(dest, name) if dest else "",
                                depth + 1)
                        if count is None:
                            emit(depth, f"🔁 ×[{rep}]  (defina a quantidade)",
                                 "dim")
                        elif count > shown:
                            last = _render_name(
                                n, {**vars2, "seq": start + count - 1})
                            emit(depth, f"🔁 … mais {count - shown}, até {last}",
                                 "dim")
                    else:
                        name = _render_name(n, vars2)
                        emit(depth, icon + name, tag)
                        add(n["children"], vars2,
                            os.path.join(dest, name) if dest else "", depth + 1)

            add(nodes, dict(vars_), base if base_ok else "", 0)
            prev.configure(state="disabled")
            try:
                prev.yview_moveto(ypos)
            except Exception:
                pass

        def _get_nodes():
            """Nós canônicos do modo atual (texto sempre é a fonte salva)."""
            if mode[0] == "visual":
                text = serialize_template(state_nodes)
            else:
                text = editor.get("1.0", "end-1c")
            nodes = parse_template(text)
            return nodes, text

        def _refresh():
            try:
                nodes, text = _get_nodes()
            except TemplateError as e:
                status_lbl.configure(text="✗ " + str(e), text_color=RED)
                count_lbl.configure(text="")
                return
            status_lbl.configure(text="✓ modelo válido", text_color=GREEN)
            if text != g.get("template"):
                g["template"] = text
                self.save()
            _rebuild_vars(nodes)
            vars_ = {k: sv.get().strip() for k, sv in var_entries.items()}
            _fill_tree(nodes, vars_)
            faltam = [k for k, v in vars_.items() if not v]
            if faltam:
                count_lbl.configure(
                    text="preencha: " + ", ".join("{" + f + "}" for f in faltam),
                    text_color=YELLOW)
                return
            base = g.get("base_path", "")
            base_ok = bool(base) and os.path.isdir(base)
            dest = base if base_ok else os.path.join(_DIR, "__ff_preview__")
            try:
                st = execute_template(nodes, dest, vars_, dry=True,
                                      continue_seq=seq_var.get() and base_ok)
                txt = f"📁 {st['folders']} pastas · 📄 {st['files']} arquivos"
                if st["skipped"]:
                    txt += f" · {st['skipped']} já existem"
                count_lbl.configure(text=txt, text_color=FG_LABEL)
            except TemplateError as e:
                count_lbl.configure(text=str(e), text_color=YELLOW)

        def criar():
            _refresh()
            base = g.get("base_path", "")
            if not base or not os.path.isdir(base):
                messagebox.showerror(
                    "Pasta base",
                    "A pasta base do grupo não existe.\nConfigure em ✎ Editar.")
                return
            try:
                nodes, _ = _get_nodes()
                vars_ = {k: sv.get().strip() for k, sv in var_entries.items()}
                faltam = [k for k, v in vars_.items() if not v]
                if faltam:
                    raise TemplateError("Preencha as variáveis: " +
                                        ", ".join(faltam))
                st = execute_template(nodes, base, vars_, dry=True,
                                      continue_seq=seq_var.get())
            except TemplateError as e:
                messagebox.showerror("Modelo", str(e))
                return
            if st["folders"] + st["files"] == 0:
                messagebox.showinfo("Nada a criar",
                                    "Tudo do modelo já existe no destino.")
                return
            if not messagebox.askyesno(
                    "Confirmar criação",
                    f"Destino: {base}\n\n"
                    f"Criar {st['folders']} pasta(s) e {st['files']} arquivo(s)?\n"
                    f"({st['skipped']} itens já existem e serão pulados)"):
                return
            btn_criar.configure(state="disabled", text="Criando...")

            def task():
                try:
                    if pause_var.get():
                        log_lbl.configure(text="Pausando OneDrive...",
                                          text_color=FG_DIM)
                        pause_onedrive()
                    r = execute_template(nodes, base, vars_, dry=False,
                                         continue_seq=seq_var.get())
                    txt = (f"✓ Criado: {r['folders']} pasta(s), "
                           f"{r['files']} arquivo(s).")
                    if r["skipped"]:
                        txt += f" Pulados: {r['skipped']}."
                    log_lbl.configure(text=txt, text_color=GREEN)
                except Exception as e:
                    log_lbl.configure(text=f"✗ ERRO: {e}", text_color=RED)
                finally:
                    if pause_var.get():
                        resume_onedrive()
                    btn_criar.configure(state="normal",
                                        text="✚  Criar estrutura")
                    self.after(0, _schedule_refresh)

            threading.Thread(target=task, daemon=True).start()

        btn_criar.configure(command=criar)

        _t = [None]

        def _schedule_refresh(_e=None):
            if _t[0]:
                self.after_cancel(_t[0])
            _t[0] = self.after(250, _refresh)

        editor.bind("<KeyRelease>", _schedule_refresh)

        # estado inicial
        if mode[0] == "visual":
            seg.set("✦ Visual")
            _sync_visual()
            vis_tools.pack(side="left", padx=(8, 0))
            vis_container.pack(fill="both", expand=True, pady=(8, 0))
        else:
            seg.set("⌨ Texto")
            text_container.pack(fill="both", expand=True, pady=(8, 0))
        _refresh()

    # ── Grupo tipo "marketplace" ─────────────────────────────────────────────
    def _build_marketplace_view(self, wrap, g):
        cor = g.get("color", ACCENT)
        tabs = ctk.CTkTabview(wrap, fg_color=BG_CARD, corner_radius=14,
                              segmented_button_fg_color=BG_INPUT,
                              segmented_button_selected_color=darker(cor, 0.45),
                              segmented_button_selected_hover_color=darker(cor, 0.35),
                              segmented_button_unselected_color=BG_INPUT,
                              segmented_button_unselected_hover_color=BG_HOVER,
                              text_color=FG_MAIN)
        tabs.pack(fill="both", expand=True)
        tab_criar = tabs.add("  Criar  ")
        tab_ren   = tabs.add("  Renomear  ")
        tab_rel   = tabs.add("  Relatório  ")
        self._mp_tab_criar(tab_criar, g, cor)
        self._mp_tab_renomear(tab_ren, g, cor)
        self._mp_tab_relatorio(tab_rel, g, cor)

    def _ano_mes_row(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(4, 10))
        ano_var = tk.StringVar(value=str(datetime.datetime.now().year))
        mes_var = tk.StringVar(value=MESES[datetime.datetime.now().month - 1])
        ctk.CTkLabel(row, text="ANO", text_color=FG_LABEL, font=F(11, True)
                     ).pack(side="left", padx=(0, 6))
        ctk.CTkOptionMenu(row, variable=ano_var, width=90,
                          values=[str(y) for y in range(2024, 2032)],
                          fg_color=BG_INPUT, button_color=BG_HOVER,
                          text_color=FG_MAIN, font=F(12),
                          dropdown_fg_color=BG_CARD).pack(side="left", padx=(0, 16))
        ctk.CTkLabel(row, text="MÊS", text_color=FG_LABEL, font=F(11, True)
                     ).pack(side="left", padx=(0, 6))
        ctk.CTkOptionMenu(row, variable=mes_var, width=180, values=MESES,
                          fg_color=BG_INPUT, button_color=BG_HOVER,
                          text_color=FG_MAIN, font=F(12),
                          dropdown_fg_color=BG_CARD).pack(side="left")
        return ano_var, mes_var

    def _mp_tab_criar(self, tab, g, cor):
        wrap = ctk.CTkFrame(tab, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=10, pady=4)

        ano_var, mes_var = self._ano_mes_row(wrap)

        hdr = ctk.CTkFrame(wrap, fg_color="transparent")
        hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="RESPONSÁVEL (iniciais)", text_color=FG_LABEL,
                     font=F(11, True), width=160, anchor="w").pack(side="left")
        ctk.CTkLabel(hdr, text="QUANTIDADE", text_color=FG_LABEL,
                     font=F(11, True), anchor="w").pack(side="left")

        linhas = ctk.CTkFrame(wrap, fg_color="transparent")
        linhas.pack(fill="x")
        pessoas = []

        def add_linha(resp="", qtd="1"):
            row = ctk.CTkFrame(linhas, fg_color="transparent")
            row.pack(fill="x", pady=3)
            rv, qv = tk.StringVar(value=resp), tk.StringVar(value=qtd)
            e1 = ctk.CTkEntry(row, textvariable=rv, width=150, fg_color=BG_INPUT,
                              border_color=BG_HOVER, text_color=FG_MAIN, font=F(12))
            e1.pack(side="left", padx=(0, 10))
            ctk.CTkEntry(row, textvariable=qv, width=80, fg_color=BG_INPUT,
                         border_color=BG_HOVER, text_color=FG_MAIN, font=F(12)
                         ).pack(side="left", padx=(0, 10))
            item = {"resp": rv, "qtd": qv, "frame": row}

            def remover(i=item):
                if len(pessoas) > 1:
                    i["frame"].destroy()
                    pessoas.remove(i)
            ctk.CTkButton(row, text="✕", width=30, height=28, corner_radius=8,
                          fg_color="transparent", hover_color=BG_HOVER,
                          text_color=RED, font=F(12, True), command=remover
                          ).pack(side="left")
            pessoas.append(item)
            e1.focus_set()

        add_linha()
        ctk.CTkButton(wrap, text="＋ Adicionar pessoa", height=30, corner_radius=10,
                      fg_color="transparent", hover_color=BG_HOVER,
                      text_color=ACCENT, font=F(12), command=add_linha
                      ).pack(anchor="w", pady=(4, 6))

        pause_var = tk.BooleanVar(value=self.config_data.get("pause_onedrive", True))
        make_switch(wrap, text="Pausar OneDrive durante criação", variable=pause_var,
                      progress_color=ACCENT, text_color=FG_LABEL, font=F(12)
                      ).pack(anchor="w", pady=(0, 8))

        out = make_textbox(wrap, height=130)

        def log_fn(msg, erro=False, aviso=False, ok=False):
            tag = "erro" if erro else "aviso" if aviso else "ok" if ok else "dim"
            tb_write(out, msg, tag)

        def iniciar():
            itens, erros = [], []
            for i, p in enumerate(pessoas, 1):
                resp  = p["resp"].get().strip().upper()
                qtd_s = p["qtd"].get().strip()
                if not resp:
                    erros.append(f"Linha {i}: responsável não preenchido.")
                    continue
                try:
                    qtd = int(qtd_s)
                    assert qtd > 0
                except Exception:
                    erros.append(f"Linha {i} ({resp}): quantidade inválida.")
                    continue
                itens.append((resp, qtd))
            if erros:
                messagebox.showerror("Corrija os campos", "\n".join(erros))
                return
            if not itens:
                messagebox.showerror("Sem dados", "Preencha pelo menos uma linha.")
                return
            total  = sum(q for _, q in itens)
            resumo = "\n".join(f"  {r}: {q} pasta(s)" for r, q in itens)
            if not messagebox.askyesno(
                    "Confirmar criação",
                    f"Grupo: {g['name']}\nMês: {mes_var.get()} / {ano_var.get()}\n\n"
                    f"{resumo}\n\nTotal: {total} pasta(s). Confirma?"):
                return
            btn.configure(state="disabled", text="Criando...")

            def task():
                try:
                    n = criar_lote(g, ano_var.get(), mes_var.get(), itens,
                                   log_fn, pause_var.get())
                    log_fn(f"{n} pasta(s) criada(s) com sucesso!", ok=True)
                except Exception as e:
                    log_fn(f"ERRO: {e}", erro=True)
                finally:
                    btn.configure(state="normal", text="✚  CRIAR PASTAS")
            threading.Thread(target=task, daemon=True).start()

        btn = ctk.CTkButton(wrap, text="✚  CRIAR PASTAS", height=42, corner_radius=21,
                            fg_color=ACCENT, hover_color=ACCENT_H,
                            text_color=DARK_TXT, font=F(13, True), command=iniciar)
        btn.pack(fill="x", pady=(0, 8))
        out.pack(fill="both", expand=True)

    def _mp_tab_renomear(self, tab, g, cor):
        wrap = ctk.CTkFrame(tab, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=10, pady=4)
        cfg = self.config_data

        ctk.CTkLabel(wrap, text="CÓDIGO DA PASTA", text_color=FG_LABEL,
                     font=F(11, True)).pack(anchor="w", pady=(2, 3))
        cod_row = ctk.CTkFrame(wrap, fg_color="transparent")
        cod_row.pack(fill="x")
        cod_var = tk.StringVar()
        ctk.CTkEntry(cod_row, textvariable=cod_var, width=170, fg_color=BG_INPUT,
                     border_color=BG_HOVER, text_color=FG_MAIN, font=F(12)
                     ).pack(side="left", padx=(0, 8))
        btn_loc = ctk.CTkButton(cod_row, text="🔍 Localizar", width=110, height=32,
                                corner_radius=10, fg_color=BG_INPUT,
                                hover_color=BG_HOVER, text_color=FG_MAIN, font=F(12))
        btn_loc.pack(side="left")
        lbl_loc = ctk.CTkLabel(wrap, text="", text_color=FG_DIM, font=F(12),
                               wraplength=560, justify="left")
        lbl_loc.pack(anchor="w", pady=(6, 8))

        ctk.CTkLabel(wrap, text="NOME DO CLIENTE", text_color=FG_LABEL,
                     font=F(11, True)).pack(anchor="w", pady=(0, 3))
        nome_var = tk.StringVar()
        ctk.CTkEntry(wrap, textvariable=nome_var, width=320, fg_color=BG_INPUT,
                     border_color=BG_HOVER, text_color=FG_MAIN, font=F(12)
                     ).pack(anchor="w", pady=(0, 8))

        trello_ok = group_trello_ok(cfg, g)
        usar_trello = tk.BooleanVar(value=trello_ok)
        mover_var   = tk.BooleanVar(value=trello_ok)
        sw1 = make_switch(wrap, text="Atualizar card no Trello",
                            variable=usar_trello, progress_color=ACCENT,
                            text_color=FG_LABEL, font=F(12))
        sw1.pack(anchor="w")
        sw2 = make_switch(wrap, text="Mover para Aguardando Aprovação",
                            variable=mover_var, progress_color=ACCENT,
                            text_color=FG_LABEL, font=F(12))
        sw2.pack(anchor="w", pady=(4, 0))
        if not trello_ok:
            sw1.configure(state="disabled")
            sw2.configure(state="disabled")
            ctk.CTkLabel(wrap, text="Configure a API do Trello (⚙) e o Board ID "
                                    "do grupo (✎) para ativar.",
                         text_color=FG_DIM, font=F(11)).pack(anchor="w")

        card_lbl = ctk.CTkLabel(wrap, text="", text_color=FG_DIM, font=F(12),
                                justify="left")
        card_lbl.pack(anchor="w", pady=(6, 0))

        btn_ren = ctk.CTkButton(wrap, text="✏  RENOMEAR", height=42, corner_radius=21,
                                fg_color=ACCENT, hover_color=ACCENT_H,
                                text_color=DARK_TXT, font=F(13, True),
                                state="disabled")
        btn_ren.pack(fill="x", pady=(12, 0))
        lbl_status = ctk.CTkLabel(wrap, text="", font=F(12), wraplength=560,
                                  justify="left")
        lbl_status.pack(anchor="w", pady=(8, 0))

        path_found = [None]
        cards_found = [[]]
        card_sel = [None]

        def localizar():
            codigo = cod_var.get().strip().upper()
            if not codigo:
                messagebox.showwarning("Atenção", "Digite o código da pasta.")
                return
            lbl_loc.configure(text="Buscando pasta...", text_color=FG_DIM)
            btn_loc.configure(state="disabled")
            btn_ren.configure(state="disabled")
            path_found[0] = None
            card_lbl.configure(text="")
            card_sel[0] = None

            def task():
                path, nome = None, None
                info = self.index_data.get(codigo)
                if info and os.path.exists(info["path"]):
                    path, nome = info["path"], info["nome"]
                else:
                    path, nome = buscar_pasta_por_codigo([g["base_path"]], codigo)
                if path:
                    path_found[0] = path
                    lbl_loc.configure(text=f"Encontrada: {nome}", text_color=GREEN)
                    btn_ren.configure(state="normal")
                else:
                    lbl_loc.configure(text=f"Pasta '{codigo}' não encontrada.",
                                      text_color=RED)
                btn_loc.configure(state="normal")
            threading.Thread(target=task, daemon=True).start()

        def buscar_card_async(nome_cliente):
            if not usar_trello.get() or not group_trello_ok(cfg, g):
                return
            card_lbl.configure(text="buscando card...", text_color=FG_DIM)
            cards_found[0] = []
            card_sel[0] = None

            def task():
                try:
                    cards = trello_search_cards(nome_cliente, g["board_id"],
                                                cfg["trello_key"], cfg["trello_token"])
                    cards_found[0] = cards
                    if len(cards) == 1:
                        card_sel[0] = cards[0]
                        card_lbl.configure(text=f"Card: {cards[0]['name']}",
                                           text_color=GREEN)
                    elif len(cards) > 1:
                        card_lbl.configure(
                            text=f"{len(cards)} cards encontrados — clique para selecionar",
                            text_color=YELLOW)
                        card_lbl.bind("<Button-1>", lambda e: _selecionar_card())
                    else:
                        card_lbl.configure(text="Nenhum card encontrado.",
                                           text_color=YELLOW)
                except Exception as ex:
                    card_lbl.configure(text=f"Erro Trello: {ex}", text_color=RED)
            threading.Thread(target=task, daemon=True).start()

        def _selecionar_card():
            cards = cards_found[0]
            if not cards:
                return
            list_names = {}
            try:
                for c in cards:
                    lid = c.get("idList", "")
                    if lid and lid not in list_names:
                        list_names[lid] = trello_get_list_name(
                            lid, cfg["trello_key"], cfg["trello_token"])
            except Exception:
                pass
            chosen = dialog_selecionar_card(self, cards, list_names)
            if chosen:
                card_sel[0] = chosen
                card_lbl.configure(text=f"Card: {chosen['name']}", text_color=GREEN)

        nome_var.trace_add("write", lambda *_: (
            buscar_card_async(nome_var.get().strip())
            if usar_trello.get() and len(nome_var.get().strip()) >= 3 else None))

        def renomear():
            nome = nome_var.get().strip()
            if not nome:
                messagebox.showwarning("Atenção", "Digite o nome do cliente.")
                return
            if not path_found[0]:
                messagebox.showerror("Erro", "Localize a pasta primeiro.")
                return
            nome_atual = os.path.basename(path_found[0])
            codigo_pasta = nome_atual.split(" - ")[0]
            if not messagebox.askyesno(
                    "Confirmar",
                    f"Renomear:\n  {nome_atual}\npara:\n  {codigo_pasta} - {nome}"
                    "\n\nConfirma?"):
                return
            btn_ren.configure(state="disabled", text="Processando...")

            def task():
                erros = []
                try:
                    novo_path = renomear_pasta(path_found[0], nome)
                    path_found[0] = novo_path
                    lbl_loc.configure(text=f"Pasta: {os.path.basename(novo_path)}",
                                      text_color=GREEN)
                    k = os.path.basename(novo_path).split(" - ")[0].upper()
                    self.index_data[k] = {
                        "path": novo_path, "nome": os.path.basename(novo_path),
                        "cliente": nome, "plat": g["name"].upper(),
                    }
                    save_index(self.index_data)
                except Exception as e:
                    erros.append(f"Pasta: {e}")

                if usar_trello.get() and group_trello_ok(cfg, g):
                    card = card_sel[0]
                    if card:
                        try:
                            novo_titulo = f"{codigo_pasta} - {card['name']}"
                            trello_update_card_name(card["id"], novo_titulo,
                                                    cfg["trello_key"],
                                                    cfg["trello_token"])
                            card_lbl.configure(text=f"Trello atualizado: {novo_titulo}",
                                               text_color=GREEN)
                        except Exception as e:
                            erros.append(f"Trello (título): {e}")
                        if mover_var.get():
                            if g.get("list_aguardando"):
                                try:
                                    trello_move_card(card["id"], g["list_aguardando"],
                                                     cfg["trello_key"],
                                                     cfg["trello_token"])
                                except Exception as e:
                                    erros.append(f"Trello (mover): {e}")
                            else:
                                erros.append("ID da lista Aguardando não configurado.")
                    else:
                        erros.append("Card do Trello não identificado — atualize manualmente.")

                if erros:
                    lbl_status.configure(text="⚠ " + " | ".join(erros),
                                         text_color=YELLOW)
                else:
                    lbl_status.configure(text="Concluído com sucesso!",
                                         text_color=GREEN)
                btn_ren.configure(state="normal", text="✏  RENOMEAR")
            threading.Thread(target=task, daemon=True).start()

        btn_loc.configure(command=localizar)
        btn_ren.configure(command=renomear)

    def _mp_tab_relatorio(self, tab, g, cor):
        wrap = ctk.CTkFrame(tab, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=10, pady=4)

        ano_var, mes_var = self._ano_mes_row(wrap)

        btn = ctk.CTkButton(wrap, text="📊  GERAR RELATÓRIO", height=40,
                            corner_radius=20, fg_color=ACCENT,
                            hover_color=ACCENT_H, text_color=DARK_TXT,
                            font=F(13, True))
        btn.pack(fill="x", pady=(0, 8))

        out = make_textbox(wrap, height=300)
        out.pack(fill="both", expand=True)

        def escrever(txt, tag="normal"):
            tb_write(out, txt, tag, timestamp=False)

        def gerar():
            tb_clear(out)
            btn.configure(state="disabled", text="Gerando...")

            def task():
                try:
                    r = gerar_relatorio(g, ano_var.get(), mes_var.get())
                    escrever(f"RELATÓRIO — {g['name'].upper()}  |  "
                             f"{mes_var.get()} / {ano_var.get()}", "titulo")
                    escrever("─" * 50, "dim")
                    if r["total"] == 0:
                        escrever(f"Nenhuma pasta encontrada em:\n{r['destino']}",
                                 "aviso")
                        return
                    escrever(f"Total de pastas:     {r['total']}", "ok")
                    escrever(f"Com nome de cliente: {r['com_cliente']}")
                    escrever(f"Ainda como 'Vazio':  {r['vazio']}",
                             "aviso" if r["vazio"] else "ok")
                    escrever(f"Com arquivo #ENVIAR: {r['com_arquivo']}", "ok")
                    escrever(f"Sem arquivo #ENVIAR: {r['sem_arquivo']}",
                             "aviso" if r["sem_arquivo"] else "ok")
                    escrever("─" * 50, "dim")
                    escrever("POR RESPONSÁVEL:", "titulo")
                    for pessoa, qtd in sorted(r["por_pessoa"].items()):
                        escrever(f"  {pessoa:<6} → {qtd} pasta(s)", "pessoa")
                    sem_arq = [p for p in r["lista"]
                               if not p["tem_arquivo"] and not p["vazio"]]
                    if sem_arq:
                        escrever("─" * 50, "dim")
                        escrever("⚠  Com cliente mas sem arquivo em #ENVIAR:", "aviso")
                        for p in sem_arq:
                            escrever(f"  {p['codigo']} - {p['cliente']}", "aviso")
                finally:
                    btn.configure(state="normal", text="📊  GERAR RELATÓRIO")
            threading.Thread(target=task, daemon=True).start()

        btn.configure(command=gerar)

    # ═════════════════════════════════════════════════════════════════════════
    # BUSCA GLOBAL
    # ═════════════════════════════════════════════════════════════════════════
    def show_search(self):
        self._clear()
        self._set_route("buscar", "Buscar")
        wrap = ctk.CTkFrame(self.container, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=26, pady=16)

        top = ctk.CTkFrame(wrap, fg_color="transparent")
        top.pack(fill="x", pady=(0, 8))
        ctk.CTkButton(top, text="←", width=38, height=34, corner_radius=10,
                      fg_color=BG_INPUT, hover_color=BG_HOVER, text_color=FG_MAIN,
                      font=F(15, True), command=self.show_home).pack(side="left")
        ctk.CTkLabel(top, text="  Buscar pastas", text_color=FG_MAIN,
                     font=F(20, True)).pack(side="left")

        idx_var = tk.StringVar(value=(
            f"Índice local: {len(self.index_data)} pastas indexadas"
            if self.index_data else
            "Índice não gerado. Clique em 'Atualizar índice'."))
        btn_idx = ctk.CTkButton(top, text="🔄 Atualizar índice", width=140,
                                height=32, corner_radius=10, fg_color=BG_INPUT,
                                hover_color=BG_HOVER, text_color=FG_MAIN, font=F(12))
        btn_idx.pack(side="right")
        ctk.CTkLabel(wrap, textvariable=idx_var, text_color=FG_DIM, font=F(11)
                     ).pack(anchor="w", pady=(0, 6))

        busca_var = tk.StringVar()
        ent = ctk.CTkEntry(wrap, textvariable=busca_var, height=40,
                           placeholder_text="Código ou nome do cliente...",
                           fg_color=BG_INPUT, border_color=BG_HOVER,
                           text_color=FG_MAIN, corner_radius=12, font=F(13))
        ent.pack(fill="x", pady=(0, 8))
        ent.focus_set()

        res_frame = ctk.CTkFrame(wrap, fg_color=BG_CARD, corner_radius=12)
        res_frame.pack(fill="both", expand=True)
        sb = tk.Scrollbar(res_frame)
        sb.pack(side="right", fill="y", pady=8)
        listbox = tk.Listbox(res_frame, bg=BG_CARD, fg=FG_MAIN, font=MONO,
                             selectbackground=ACCENT, selectforeground=DARK_TXT,
                             relief="flat", bd=0, highlightthickness=0,
                             yscrollcommand=sb.set, activestyle="none")
        listbox.pack(fill="both", expand=True, padx=10, pady=8)
        sb.config(command=listbox.yview)

        resultados_paths = []
        count_var = tk.StringVar()

        bottom = ctk.CTkFrame(wrap, fg_color="transparent")
        bottom.pack(fill="x", pady=(6, 0))
        mesma_janela = tk.BooleanVar(value=True)
        make_switch(bottom, text="Abrir na mesma janela do Explorador",
                      variable=mesma_janela, progress_color=ACCENT,
                      text_color=FG_LABEL, font=F(12)).pack(side="left")
        ctk.CTkLabel(bottom, textvariable=count_var, text_color=FG_DIM,
                     font=F(11)).pack(side="right")

        def _buscar(*_):
            termo = busca_var.get().strip().upper()
            listbox.delete(0, "end")
            resultados_paths.clear()
            count_var.set("")
            if not termo:
                return
            if not self.index_data:
                listbox.insert("end", "  Índice vazio. Clique em 'Atualizar índice'.")
                return
            for cod, info in self.index_data.items():
                if termo in cod or termo in info.get("cliente", "").upper():
                    listbox.insert("end", f"  [{info['plat']}]  {info['nome']}")
                    resultados_paths.append(info["path"])
            if not resultados_paths:
                listbox.insert("end", "  Nenhum resultado encontrado.")
            else:
                count_var.set(f"{len(resultados_paths)} resultado(s)")

        _after = [None]

        def _live(*_):
            if _after[0]:
                self.after_cancel(_after[0])
            if len(busca_var.get().strip()) >= 2:
                _after[0] = self.after(300, _buscar)
        busca_var.trace_add("write", _live)

        def _abrir(event=None):
            sel = listbox.curselection()
            if not sel or sel[0] >= len(resultados_paths):
                return
            path = resultados_paths[sel[0]]
            if not os.path.exists(path):
                messagebox.showwarning(
                    "Pasta não encontrada",
                    f"O caminho não existe mais:\n{path}\n\nAtualize o índice.")
                return
            abrir_no_explorer(path, mesma_janela.get())
        listbox.bind("<Double-Button-1>", _abrir)

        def _atualizar_indice():
            btn_idx.configure(state="disabled", text="Indexando...")
            idx_var.set("Indexando pastas... aguarde.")

            def task():
                try:
                    idx = build_index(
                        self.groups(),
                        progress_fn=lambda d: idx_var.set(f"Indexando: {d[:40]}..."))
                    save_index(idx)
                    self.index_data = idx
                    idx_var.set(f"Índice atualizado: {len(idx)} pastas indexadas.")
                except Exception as e:
                    idx_var.set(f"ERRO ao indexar: {e}")
                finally:
                    btn_idx.configure(state="normal", text="🔄 Atualizar índice")
            threading.Thread(target=task, daemon=True).start()
        btn_idx.configure(command=_atualizar_indice)

    # ═════════════════════════════════════════════════════════════════════════
    # EDITOR DE GRUPO
    # ═════════════════════════════════════════════════════════════════════════
    def open_group_editor(self, g):
        novo = g is None
        data = default_group() if novo else g

        win = ctk.CTkToplevel(self, fg_color=BG_MAIN)
        win.title("Novo grupo" if novo else f"Editar — {data['name']}")
        win.geometry("560x600")
        win.grab_set()

        sc = ctk.CTkScrollableFrame(win, fg_color="transparent")
        sc.pack(fill="both", expand=True, padx=18, pady=14)

        ctk.CTkLabel(sc, text="Novo grupo" if novo else "Editar grupo",
                     text_color=FG_MAIN, font=F(20, True)).pack(anchor="w",
                                                                pady=(0, 10))

        def campo(rotulo, valor="", browse=False):
            ctk.CTkLabel(sc, text=rotulo, text_color=FG_LABEL, font=F(11, True)
                         ).pack(anchor="w", pady=(8, 2))
            row = ctk.CTkFrame(sc, fg_color="transparent")
            row.pack(fill="x")
            sv = tk.StringVar(value=valor)
            ctk.CTkEntry(row, textvariable=sv, fg_color=BG_INPUT,
                         border_color=BG_HOVER, text_color=FG_MAIN, font=F(12),
                         height=34).pack(side="left", fill="x", expand=True)
            if browse:
                def _browse(v=sv):
                    p = filedialog.askdirectory(parent=win)
                    if p:
                        v.set(os.path.normpath(p))
                ctk.CTkButton(row, text="…", width=40, height=34, corner_radius=10,
                              fg_color=BG_INPUT, hover_color=BG_HOVER,
                              text_color=FG_MAIN, command=_browse
                              ).pack(side="left", padx=(6, 0))
            return sv

        nome_var = campo("NOME DO GRUPO", data["name"])

        # tipo (somente na criação)
        kind_var = tk.StringVar(value=data["kind"])
        if novo:
            ctk.CTkLabel(sc, text="TIPO", text_color=FG_LABEL, font=F(11, True)
                         ).pack(anchor="w", pady=(10, 2))
            seg = ctk.CTkSegmentedButton(
                sc, values=["Estrutura personalizada", "Marketplace (Shopee/ML)"],
                fg_color=BG_INPUT, selected_color=ACCENT_DK,
                selected_hover_color=ACCENT_DK_H, unselected_color=BG_INPUT,
                unselected_hover_color=BG_HOVER, text_color=FG_MAIN, font=F(12),
                command=lambda v: kind_var.set(
                    "template" if v.startswith("Estrutura") else "marketplace"))
            seg.set("Estrutura personalizada" if data["kind"] == "template"
                    else "Marketplace (Shopee/ML)")
            seg.pack(fill="x")

        # cor
        ctk.CTkLabel(sc, text="COR", text_color=FG_LABEL, font=F(11, True)
                     ).pack(anchor="w", pady=(10, 2))
        cor_var = tk.StringVar(value=data.get("color", GROUP_COLORS[0]))
        cor_row = ctk.CTkFrame(sc, fg_color="transparent")
        cor_row.pack(anchor="w")
        cor_btns = {}

        def _pick(c):
            cor_var.set(c)
            for cc, b in cor_btns.items():
                b.configure(text="✓" if cc == c else "")
        for c in GROUP_COLORS:
            b = ctk.CTkButton(cor_row, text="", width=34, height=34,
                              corner_radius=17, fg_color=c,
                              hover_color=darker(c, 0.85), text_color=DARK_TXT,
                              font=F(13, True), command=lambda c=c: _pick(c))
            b.pack(side="left", padx=3)
            cor_btns[c] = b
        _pick(cor_var.get())

        base_var = campo("PASTA BASE (onde tudo será criado)",
                         data.get("base_path", ""), browse=True)

        # campos de marketplace
        mp_frame = ctk.CTkFrame(sc, fg_color="transparent")
        dest_var   = tk.StringVar(value=data.get("dest_pattern", ""))
        prefix_var = tk.StringVar(value=data.get("prefix", ""))
        board_var  = tk.StringVar(value=data.get("board_id", ""))
        aguard_var = tk.StringVar(value=data.get("list_aguardando", ""))
        dev_var    = tk.StringVar(value=data.get("list_dev", ""))

        def _mp_campo(rotulo, sv, hint=""):
            ctk.CTkLabel(mp_frame, text=rotulo, text_color=FG_LABEL,
                         font=F(11, True)).pack(anchor="w", pady=(8, 2))
            if hint:
                ctk.CTkLabel(mp_frame, text=hint, text_color=FG_DIM, font=F(10)
                             ).pack(anchor="w")
            ctk.CTkEntry(mp_frame, textvariable=sv, fg_color=BG_INPUT,
                         border_color=BG_HOVER, text_color=FG_MAIN, font=F(12),
                         height=34).pack(fill="x")

        _mp_campo("SUBPASTA DE DESTINO", dest_var,
                  "Ex.: Shopee {ano}/{mes} - SHOPEE   (variáveis: {ano} {mes} {mes_num})")
        _mp_campo("PREFIXO DO CÓDIGO", prefix_var, "Ex.: A (Mercado Livre) — pode ficar vazio")
        _mp_campo("TRELLO — BOARD ID", board_var)
        _mp_campo("TRELLO — LISTA 'AGUARDANDO APROVAÇÃO' ID", aguard_var)
        _mp_campo("TRELLO — LISTA 'DESENVOLVIMENTO' ID (watcher)", dev_var)

        # botões
        btns = ctk.CTkFrame(sc, fg_color="transparent")
        btns.pack(fill="x", pady=(18, 6))

        def _toggle_mp(*_):
            if kind_var.get() == "marketplace":
                mp_frame.pack(fill="x", before=btns)
            else:
                mp_frame.pack_forget()
        kind_var.trace_add("write", _toggle_mp)
        _toggle_mp()

        def salvar():
            nome = nome_var.get().strip()
            if not nome:
                messagebox.showerror("Erro", "Dê um nome ao grupo.", parent=win)
                return
            base = base_var.get().strip()
            data.update({
                "name": nome, "color": cor_var.get(), "kind": kind_var.get(),
                "base_path": os.path.normpath(base) if base else "",
                "dest_pattern": dest_var.get().strip(),
                "prefix": prefix_var.get().strip().upper(),
                "board_id": board_var.get().strip(),
                "list_aguardando": aguard_var.get().strip(),
                "list_dev": dev_var.get().strip(),
            })
            if novo:
                self.config_data["groups"].append(data)
            self.save()
            win.destroy()
            self.show_home()

        ctk.CTkButton(btns, text="Salvar", height=40, corner_radius=20,
                      fg_color=ACCENT, hover_color=ACCENT_H, text_color=DARK_TXT,
                      font=F(13, True), command=salvar
                      ).pack(side="left", fill="x", expand=True)

        if not novo:
            def excluir():
                if not messagebox.askyesno(
                        "Excluir grupo",
                        f"Excluir o grupo '{data['name']}'?\n\n"
                        "As pastas no disco NÃO serão apagadas — só a "
                        "configuração do grupo no app.", parent=win):
                    return
                self.config_data["groups"].remove(data)
                self.save()
                win.destroy()
                self.show_home()
            ctk.CTkButton(btns, text="🗑 Excluir", width=110, height=40,
                          corner_radius=20, fg_color="transparent",
                          hover_color=BG_HOVER, text_color=RED, font=F(12, True),
                          command=excluir).pack(side="left", padx=(8, 0))

    # ═════════════════════════════════════════════════════════════════════════
    # AJUDA (sintaxe do modelo)
    # ═════════════════════════════════════════════════════════════════════════
    def open_help(self):
        win = ctk.CTkToplevel(self, fg_color=BG_MAIN)
        win.title("Sintaxe do modelo")
        win.geometry("620x560")
        win.grab_set()
        tb = ctk.CTkTextbox(win, fg_color=BG_CARD, text_color=FG_MAIN,
                            corner_radius=12,
                            font=ctk.CTkFont(family="Consolas", size=12))
        tb.pack(fill="both", expand=True, padx=16, pady=16)
        tb.insert("1.0", """COMO ESCREVER O MODELO DA ESTRUTURA

PASTAS E ARQUIVOS
  Nome terminando com /     → cria uma PASTA
  Nome com extensão         → cria um ARQUIVO (vazio)
  arquivo.txt = conteúdo    → arquivo com texto dentro
                              (use \\n para quebrar linha)

HIERARQUIA
  A indentação (2 espaços) define o que fica dentro do quê:

  Clientes/
    Ativos/
    Inativos/
  leia-me.txt = Bem-vindo!

REPETIÇÃO EM LOTE
  [N] antes do nome repete o item N vezes:

  [200] Pedido {seq:04d}/
    teste/
    infos.txt = Item número {seq}

  {seq}      → número sequencial (1, 2, 3...)
  {seq:04d}  → com zeros à esquerda (0001, 0002...)
  A numeração CONTINUA da maior já existente na pasta
  (dá pra desligar no botão "Continuar numeração").

  A quantidade pode ser uma variável: [{qtd}] Pasta {seq}/

VARIÁVEIS
  Qualquer {nome} vira um campo preenchível na tela.
  Já vêm prontas:
    {ano}      → ano atual (ex.: 2026)
    {mes_num}  → mês com 2 dígitos (ex.: 09)
    {mes}      → mês por extenso (ex.: 09 - SETEMBRO)
    {data}     → data de hoje (ex.: 08-09-2026)

ANEXOS (copiar arquivos reais)
  copiar: C:\\Modelos\\gabarito.pdf
  copiar: C:\\Modelos\\gabarito.pdf -> arte {seq:03d}.pdf
  Copia o arquivo indicado para dentro da pasta criada —
  ótimo para gabaritos/modelos que precisam existir em
  cada pasta de uma sequência. No modo Visual, use 📎.

COMENTÁRIOS
  Linhas começando com # são ignoradas.

EXEMPLO COMPLETO
  # Estrutura de lojas
  Clientes Loja 1/
  Produtos Loja 2/
    X/
    Y/
      [200] Pasta {seq:04d}/
        teste/
        infos.txt = Informações do item {seq:04d}
    Z/
""")
        tb.configure(state="disabled")

    # ═════════════════════════════════════════════════════════════════════════
    # WATCHER (Trello → renomeia pastas)
    # ═════════════════════════════════════════════════════════════════════════
    def open_watcher(self):
        win = ctk.CTkToplevel(self, fg_color=BG_MAIN)
        win.title("Watcher — Trello")
        win.geometry("560x460")
        win.grab_set()

        wrap = ctk.CTkFrame(win, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=18, pady=14)

        status_lbl = ctk.CTkLabel(wrap, text="", font=F(22, True))
        status_lbl.pack(pady=(4, 8))

        sw_var = tk.BooleanVar(value=self.watcher_active)

        def _refresh():
            if self.watcher_active:
                status_lbl.configure(text="●  ATIVO", text_color=GREEN)
            else:
                status_lbl.configure(text="○  INATIVO", text_color=FG_DIM)
            self._update_watcher_chip()

        def _toggle():
            if sw_var.get():
                self._start_watcher()
            else:
                self._stop_watcher()
            _refresh()

        make_switch(wrap, text="Monitorar cards do Trello e renomear pastas",
                      variable=sw_var, command=_toggle, progress_color=GREEN,
                      text_color=FG_LABEL, font=F(12)).pack(pady=(0, 6))

        interval = self.config_data.get("watcher_interval", 60)
        mp = [g["name"] for g in self.groups()
              if g["kind"] == "marketplace" and g.get("list_dev")]
        info = (f"Verifica a cada {interval}s as listas 'Desenvolvimento' dos "
                f"grupos: {', '.join(mp) if mp else '(nenhum grupo configurado)'}")
        ctk.CTkLabel(wrap, text=info, text_color=FG_LABEL, font=F(11),
                     wraplength=500, justify="left").pack(anchor="w", pady=(0, 8))

        tb = make_textbox(wrap, height=240)
        tb.pack(fill="both", expand=True)
        self._watcher_tb = tb
        for line, tag in self._watcher_lines[-200:]:
            tb_write(tb, line, tag, timestamp=False)

        def _on_close():
            self._watcher_tb = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", _on_close)
        _refresh()

    def _watcher_log(self, msg, tag="dim"):
        line = f"[{datetime.datetime.now():%H:%M:%S}] {msg}"
        self._watcher_lines.append((line, tag))
        del self._watcher_lines[:-500]
        tb = self._watcher_tb
        if tb is not None:
            def _do():
                try:
                    if tb.winfo_exists():
                        tb_write(tb, line, tag, timestamp=False)
                except Exception:
                    pass
            try:
                self.after(0, _do)
            except Exception:
                pass

    def _start_watcher(self):
        if self.watcher_active:
            return
        self.watcher_active = True
        self._watcher_processed.clear()
        self._watcher_log("Watcher iniciado.", "ok")

        def loop():
            while self.watcher_active:
                try:
                    self._watcher_tick()
                except Exception as e:
                    self._watcher_log(f"Erro no watcher: {e}", "erro")
                interval = int(self.config_data.get("watcher_interval", 60))
                for _ in range(interval * 10):
                    if not self.watcher_active:
                        break
                    time.sleep(0.1)
        threading.Thread(target=loop, daemon=True).start()
        self._update_watcher_chip()

    def _stop_watcher(self):
        self.watcher_active = False
        self._watcher_log("Watcher parado.", "dim")
        self._update_watcher_chip()

    def _watcher_tick(self):
        cfg = self.config_data
        if not trello_keys_ok(cfg):
            return
        for g in self.groups():
            if g["kind"] != "marketplace":
                continue
            list_id, base_path = g.get("list_dev"), g.get("base_path")
            if not list_id or not base_path:
                continue
            try:
                cards = trello_get_list_cards(list_id, cfg["trello_key"],
                                              cfg["trello_token"])
            except Exception as e:
                self._watcher_log(f"[{g['name']}] Erro ao buscar cards: {e}", "erro")
                continue
            for card in cards:
                card_id, card_name = card["id"], card.get("name", "")
                if card_id in self._watcher_processed:
                    continue
                m = FOLDER_CODE_RE.match(card_name)
                if not m:
                    continue
                code = m.group(1)
                vazio_name = f"{code} - Vazio"
                found_path = None
                if os.path.exists(base_path):
                    for root, dirs, _ in os.walk(base_path):
                        for d in dirs:
                            if d.upper() == vazio_name.upper():
                                found_path = os.path.join(root, d)
                                break
                        if found_path:
                            break
                if found_path:
                    try:
                        novo_path = os.path.join(os.path.dirname(found_path),
                                                 card_name)
                        os.rename(found_path, novo_path)
                        self._watcher_log(
                            f"[{g['name']}] Renomeado: {vazio_name} → {card_name}",
                            "ok")
                        self._watcher_processed.add(card_id)
                        self.index_data[code] = {
                            "path": novo_path, "nome": card_name,
                            "cliente": m.group(2), "plat": g["name"].upper(),
                        }
                        save_index(self.index_data)
                    except Exception as e:
                        self._watcher_log(
                            f"[{g['name']}] Erro ao renomear {vazio_name}: {e}",
                            "erro")
                else:
                    self._watcher_processed.add(card_id)

    # ═════════════════════════════════════════════════════════════════════════
    # CONFIGURAÇÕES GLOBAIS
    # ═════════════════════════════════════════════════════════════════════════
    def open_settings(self):
        win = ctk.CTkToplevel(self, fg_color=BG_MAIN)
        win.title("Configurações")
        win.geometry("540x520")
        win.grab_set()

        sc = ctk.CTkScrollableFrame(win, fg_color="transparent")
        sc.pack(fill="both", expand=True, padx=18, pady=14)

        ctk.CTkLabel(sc, text="Configurações", text_color=FG_MAIN,
                     font=F(20, True)).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(sc, text="Caminhos e Trello de cada grupo ficam no ✎ do grupo.",
                     text_color=FG_DIM, font=F(11)).pack(anchor="w", pady=(0, 10))

        def secao(txt, cor=CYAN):
            ctk.CTkLabel(sc, text=txt, text_color=cor, font=F(12, True)
                         ).pack(anchor="w", pady=(14, 4))

        def campo(rotulo, valor, senha=False):
            row = ctk.CTkFrame(sc, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=rotulo, text_color=FG_LABEL, font=F(11),
                         width=190, anchor="w").pack(side="left")
            sv = tk.StringVar(value=valor)
            e = ctk.CTkEntry(row, textvariable=sv, fg_color=BG_INPUT,
                             border_color=BG_HOVER, text_color=FG_MAIN,
                             font=F(12), height=32, show="•" if senha else "")
            e.pack(side="left", fill="x", expand=True)
            if senha:
                vis = [False]
                def _t():
                    vis[0] = not vis[0]
                    e.configure(show="" if vis[0] else "•")
                ctk.CTkButton(row, text="👁", width=34, height=32,
                              fg_color="transparent", hover_color=BG_HOVER,
                              text_color=FG_LABEL, command=_t
                              ).pack(side="left", padx=(4, 0))
            return sv

        secao("TRELLO  (chaves globais — https://trello.com/app-key)")
        key_var   = campo("API Key:", self.config_data.get("trello_key", ""))
        token_var = campo("Token:", self.config_data.get("trello_token", ""), senha=True)

        teste_lbl = ctk.CTkLabel(sc, text="", text_color=CYAN, font=F(11))

        def testar():
            key, token = key_var.get().strip(), token_var.get().strip()
            if not key or not token:
                teste_lbl.configure(text="Preencha API Key e Token primeiro.")
                return
            teste_lbl.configure(text="Testando...")

            def task():
                try:
                    boards = trello_get_boards(key, token)
                    nomes = ", ".join(b["name"] for b in boards[:3])
                    teste_lbl.configure(text=f"✅ OK! Boards: {nomes}...")
                except Exception as e:
                    teste_lbl.configure(text=f"❌ Erro: {e}")
            threading.Thread(target=task, daemon=True).start()

        trow = ctk.CTkFrame(sc, fg_color="transparent")
        trow.pack(anchor="w", pady=(4, 0))
        ctk.CTkButton(trow, text="🔌 Testar conexão", height=32, corner_radius=10,
                      fg_color=BG_INPUT, hover_color=BG_HOVER, text_color=FG_MAIN,
                      font=F(12), command=testar).pack(side="left")
        teste_lbl.pack(anchor="w", pady=(4, 0))

        secao("GERAL")
        pause_var = tk.BooleanVar(value=self.config_data.get("pause_onedrive", True))
        make_switch(sc, text="Pausar OneDrive por padrão", variable=pause_var,
                      progress_color=ACCENT, text_color=FG_LABEL, font=F(12)
                      ).pack(anchor="w", pady=2)
        int_var = campo("Watcher — intervalo (s):",
                        str(self.config_data.get("watcher_interval", 60)))

        secao("ATUALIZAÇÃO AUTOMÁTICA (GitHub)", GREEN)
        repo_var = campo("Repositório:", self.config_data.get("github_repo", ""))
        ctk.CTkLabel(sc, text=f"Versão instalada: {APP_VERSION}",
                     text_color=FG_DIM, font=F(11)).pack(anchor="w", pady=(2, 0))

        def salvar():
            try:
                iv = int(int_var.get())
                assert iv >= 10
            except Exception:
                messagebox.showerror("Erro", "Intervalo do watcher deve ser ≥ 10.",
                                     parent=win)
                return
            self.config_data.update({
                "trello_key":       key_var.get().strip(),
                "trello_token":     token_var.get().strip(),
                "pause_onedrive":   pause_var.get(),
                "watcher_interval": iv,
                "github_repo":      repo_var.get().strip(),
            })
            self.save()
            win.destroy()

        ctk.CTkButton(sc, text="Salvar", height=40, corner_radius=20,
                      fg_color=ACCENT, hover_color=ACCENT_H, text_color=DARK_TXT,
                      font=F(13, True), command=salvar).pack(fill="x", pady=(20, 6))

    # ═════════════════════════════════════════════════════════════════════════
    # SOBRE
    # ═════════════════════════════════════════════════════════════════════════
    def open_sobre(self):
        win = ctk.CTkToplevel(self, fg_color=BG_MAIN)
        win.title("Sobre o FolderFlow")
        win.geometry("380x330")
        win.resizable(False, False)
        win.grab_set()

        ctk.CTkFrame(win, fg_color=ACCENT, height=5, corner_radius=0).pack(fill="x")
        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=30, pady=22)

        ctk.CTkLabel(body, text="FolderFlow", text_color=ACCENT,
                     font=F(26, True)).pack(anchor="w")
        ctk.CTkLabel(body, text=f"Versão  {APP_VERSION}", text_color=FG_DIM,
                     font=F(12)).pack(anchor="w", pady=(0, 16))
        ctk.CTkLabel(body, text="Desenvolvido por", text_color=FG_DIM,
                     font=F(11)).pack(anchor="w")
        ctk.CTkLabel(body, text="Italo Bernardo", text_color=FG_MAIN,
                     font=F(16, True)).pack(anchor="w", pady=(0, 16))
        ctk.CTkLabel(body,
                     text="Criação de estruturas de pastas em lote,\n"
                          "grupos configuráveis e integração com Trello.",
                     text_color=FG_DIM, font=F(11), justify="left").pack(anchor="w")
        ctk.CTkButton(body, text="Fechar", height=36, corner_radius=18,
                      fg_color=ACCENT, hover_color=ACCENT_H, text_color=DARK_TXT,
                      font=F(12, True), command=win.destroy
                      ).pack(anchor="e", pady=(20, 0))


# ═══════════════════════════════════════════════════════════════════════════════
# DIÁLOGO: SELECIONAR CARD DO TRELLO
# ═══════════════════════════════════════════════════════════════════════════════
def dialog_selecionar_card(parent, cards, list_names):
    result = [None]
    win = ctk.CTkToplevel(parent, fg_color=BG_MAIN)
    win.title("Selecionar card do Trello")
    win.geometry("520x400")
    win.grab_set()

    ctk.CTkLabel(win, text="Selecionar card do Trello", text_color=FG_MAIN,
                 font=F(16, True)).pack(padx=20, pady=(14, 2), anchor="w")
    ctk.CTkLabel(win, text="Múltiplos cards encontrados. Selecione o correto:",
                 text_color=FG_LABEL, font=F(11)).pack(padx=20, anchor="w")

    lb_frame = ctk.CTkFrame(win, fg_color=BG_CARD, corner_radius=12)
    lb_frame.pack(fill="both", expand=True, padx=20, pady=(10, 0))
    sb = tk.Scrollbar(lb_frame)
    sb.pack(side="right", fill="y", pady=6)
    lb = tk.Listbox(lb_frame, bg=BG_CARD, fg=FG_MAIN, font=MONO,
                    selectbackground=ACCENT, selectforeground=DARK_TXT,
                    relief="flat", bd=0, highlightthickness=0,
                    yscrollcommand=sb.set, activestyle="none")
    lb.pack(fill="both", expand=True, padx=8, pady=6)
    sb.config(command=lb.yview)

    for c in cards:
        list_name = list_names.get(c.get("idList", ""), c.get("idList", ""))
        lb.insert("end", f"  [LISTA: {list_name}] {c['name']}")

    desc_lbl = ctk.CTkLabel(win, text="", text_color=FG_LABEL, font=F(10),
                            wraplength=470, justify="left")
    desc_lbl.pack(padx=20, pady=(6, 0), anchor="w")

    def on_select(event=None):
        sel = lb.curselection()
        if sel:
            desc = cards[sel[0]].get("desc", "")
            desc_lbl.configure(text=desc[:120] if desc else "(sem descrição)")
    lb.bind("<<ListboxSelect>>", on_select)

    def confirmar():
        sel = lb.curselection()
        if not sel:
            return
        result[0] = cards[sel[0]]
        win.destroy()

    ctk.CTkButton(win, text="Confirmar", height=38, corner_radius=19,
                  fg_color=ACCENT, hover_color=ACCENT_H, text_color=DARK_TXT,
                  font=F(13, True), command=confirmar).pack(pady=12)

    win.wait_window()
    return result[0]


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = App()
    app.mainloop()
