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
import queue
import shutil
import unicodedata
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
from tkinter import font as tkfont

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


def resource_path(rel):
    """Caminho de um recurso empacotado (funciona no .py e dentro do .exe)."""
    base = getattr(sys, "_MEIPASS", _DIR)
    return os.path.join(base, rel)


LOGO_PNG = resource_path(os.path.join("assets", "logo.png"))
LOGO_ICO = resource_path(os.path.join("assets", "logo.ico"))

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
    # respondidas no assistente da primeira abertura; escondem o que não se usa
    "usa_trello":      None,      # None = ainda não perguntou
    "usa_onedrive":    None,
    "onboarding_ok":   False,
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


CONFIG_LOAD_WARNING = []   # preenchido quando a config não pôde ser lida


def _read_config_file(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("conteúdo não é um objeto JSON")
    return data


def load_config():
    """Lê a config. Se o arquivo estiver corrompido, tenta o backup antes de
    cair no padrão — nunca descarta os grupos do usuário em silêncio."""
    cfg = DEFAULT_CONFIG.copy()
    CONFIG_LOAD_WARNING.clear()
    if os.path.exists(CONFIG_FILE):
        try:
            cfg = {**DEFAULT_CONFIG, **_read_config_file(CONFIG_FILE)}
        except Exception as e:
            bak = CONFIG_FILE + ".bak"
            try:
                cfg = {**DEFAULT_CONFIG, **_read_config_file(bak)}
                CONFIG_LOAD_WARNING.append(
                    f"O arquivo de configuração estava corrompido ({e}).\n"
                    f"Os dados foram recuperados do backup automático.")
            except Exception:
                # guarda o arquivo ilegível para perícia em vez de sobrescrever
                try:
                    os.replace(CONFIG_FILE, CONFIG_FILE + ".corrompido")
                except Exception:
                    pass
                CONFIG_LOAD_WARNING.append(
                    f"O arquivo de configuração não pôde ser lido ({e}) e não\n"
                    f"havia backup. Ele foi renomeado para "
                    f"'{os.path.basename(CONFIG_FILE)}.corrompido' e o app\n"
                    f"começou com a configuração padrão.")
    cfg, migrated = migrate_config(cfg)
    if migrated and os.path.exists(CONFIG_FILE):
        save_config(cfg)
    return cfg


def save_config(cfg):
    """Gravação atômica com backup: escreve num temporário, guarda o arquivo
    bom como .bak e só então troca. Um travamento no meio não perde os grupos."""
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(CONFIG_FILE):
        try:
            os.replace(CONFIG_FILE, CONFIG_FILE + ".bak")
        except Exception:
            pass
    os.replace(tmp, CONFIG_FILE)


# ═══════════════════════════════════════════════════════════════════════════════
# ONEDRIVE
# ═══════════════════════════════════════════════════════════════════════════════
def _onedrive_exe():
    """OneDrive.exe — instalação por usuário (padrão) ou por máquina."""
    candidatos = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     "Microsoft", "OneDrive", "OneDrive.exe"),
        os.path.join(os.environ.get("PROGRAMFILES", ""),
                     "Microsoft OneDrive", "OneDrive.exe"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""),
                     "Microsoft OneDrive", "OneDrive.exe"),
    ]
    for c in candidatos:
        if c and os.path.exists(c):
            return c
    return candidatos[0]


def onedrive_roots():
    """Pastas raiz de OneDrive sincronizadas nesta máquina.
    Junta as variáveis de ambiente com as contas registradas."""
    roots = []

    def _add(p):
        if p and os.path.isdir(p):
            n = os.path.normcase(os.path.normpath(p))
            if n not in roots:
                roots.append(n)

    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        _add(os.environ.get(var, ""))

    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\OneDrive\Accounts") as k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                try:
                    with winreg.OpenKey(k, winreg.EnumKey(k, i)) as sub:
                        _add(winreg.QueryValueEx(sub, "UserFolder")[0])
                except Exception:
                    continue
    except Exception:
        pass   # sem OneDrive instalado, ou registro indisponível
    return roots


def path_no_onedrive(path):
    """A pasta está dentro de algum OneDrive sincronizado?
    Devolve a raiz correspondente, ou None."""
    if not path:
        return None
    try:
        alvo = os.path.normcase(os.path.abspath(path))
    except Exception:
        return None
    for root in onedrive_roots():
        if alvo == root or alvo.startswith(root + os.sep):
            return root
    return None


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


def _iter_nodes(nodes):
    """Percorre a árvore inteira, em profundidade."""
    for n in nodes:
        yield n
        yield from _iter_nodes(n["children"])


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
        "mes_nome": MESES[now.month - 1].split(" - ", 1)[1],
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


# ═══════════════════════════════════════════════════════════════════════════════
# ORGANIZAÇÃO POR ANO / MÊS
# ═══════════════════════════════════════════════════════════════════════════════
MES_NOMES = [m.split(" - ", 1)[1] for m in MESES]
MES_ABREV = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN",
             "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]


def _norm(s):
    """Maiúsculas e sem acento, caractere a caractere — o comprimento não
    muda, então as posições batem com o nome original."""
    out = []
    for ch in s or "":
        d = unicodedata.normalize("NFKD", ch)
        c = d[0] if d else ch
        u = c.upper()
        out.append(u if len(u) == 1 else c)
    return "".join(out)


_NOMES_NORM = [_norm(n) for n in MES_NOMES]
_MES_ALT = "|".join(sorted(set(_NOMES_NORM + MES_ABREV), key=len, reverse=True))


def _idx_nome_mes(nome_norm):
    if nome_norm in _NOMES_NORM:
        return _NOMES_NORM.index(nome_norm) + 1
    if nome_norm in MES_ABREV:
        return MES_ABREV.index(nome_norm) + 1
    return None


def _aplica_estilo(texto, estilo):
    estilo = estilo or {}
    if estilo.get("acento") is False:
        texto = "".join(unicodedata.normalize("NFKD", c)[0] for c in texto)
    caixa = estilo.get("caixa", "upper")
    if caixa == "title":
        return texto.title()
    if caixa == "lower":
        return texto.lower()
    return texto.upper()


def mp_vars(group, ano, mes):
    """Variáveis de caminho do mês, respeitando o jeito que o grupo escreve
    os meses (MARÇO / Março / MARCO) para não criar pasta duplicada."""
    i = int(str(mes)[:2])
    est = (group or {}).get("mes_estilo") or {}
    nome = _aplica_estilo(MES_NOMES[i - 1], est)
    abrev = _aplica_estilo(MES_ABREV[i - 1], est)
    return {"ano": str(ano), "mes": f"{i:02d} - {nome}", "mes_num": f"{i:02d}",
            "mes_nome": nome, "mes_abrev": abrev}


def mp_destino(group, ano, mes):
    sub = fmt(group.get("dest_pattern") or "", mp_vars(group, ano, mes))
    destino = os.path.join(group["base_path"], sub) if sub else group["base_path"]
    return os.path.normpath(destino) if destino else destino


def _vars_do_padrao(p):
    return {m.group(1) for m in _VAR_RE.finditer(p or "")}


def padrao_tem_mes(p):
    return bool(_vars_do_padrao(p) & {"mes", "mes_num", "mes_nome", "mes_abrev"})


def padrao_tem_ano(p):
    return "ano" in _vars_do_padrao(p)


def _comp_regex(comp):
    """Regex de UM nível do padrão, aplicada sobre o nome normalizado."""
    partes, usados, pos = [], set(), 0
    for m in _VAR_RE.finditer(comp):
        partes.append(re.escape(_norm(comp[pos:m.start()])))
        nome, bruto = m.group(1), m.group(0)
        if nome == "ano":
            partes.append("(?P=ano)" if "ano" in usados else r"(?P<ano>20\d{2})")
            usados.add("ano")
        elif nome == "mes":
            partes.append(r"(?P<mn>0[1-9]|1[0-2])\ \-\ " +
                          f"(?P<nm>{_MES_ALT})")
            usados.update({"mn", "nm"})
        elif nome == "mes_num":
            rx = r"[1-9]|1[0-2]" if ":d" in bruto else r"0[1-9]|1[0-2]"
            partes.append("(?P=mn)" if "mn" in usados else f"(?P<mn>{rx})")
            usados.add("mn")
        elif nome in ("mes_nome", "mes_abrev"):
            partes.append("(?P=nm)" if "nm" in usados else f"(?P<nm>{_MES_ALT})")
            usados.add("nm")
        else:
            partes.append(".+?")
        pos = m.end()
    partes.append(re.escape(_norm(comp[pos:])))
    return re.compile("^" + "".join(partes) + "$")


def analisar_padrao(base, pattern, limite=400):
    """Quantos meses/anos existentes o padrão reconhece na base.
    Desce nível a nível entrando SÓ nas pastas que casaram — não varre as
    milhares de pastas de cliente."""
    res = {"meses": set(), "anos": set(), "fora": 0, "exemplo": ""}
    comps = [c for c in re.split(r"[\\/]", pattern or "") if c]
    if not comps or not base or not os.path.isdir(base):
        return res
    regs = [_comp_regex(c) for c in comps]
    frente = [(base, {})]
    for k, rx in enumerate(regs):
        prox = []
        for pasta, caps in frente:
            try:
                ents = [e for e in os.scandir(pasta) if e.is_dir()]
            except OSError:
                continue
            for e in ents:
                m = rx.match(_norm(e.name))
                if not m:
                    if k == len(regs) - 1 and k > 0:
                        res["fora"] += 1
                    continue
                gd = m.groupdict()
                c2 = dict(caps)
                idx = int(gd["mn"]) if gd.get("mn") else None
                if gd.get("nm"):
                    i2 = _idx_nome_mes(gd["nm"])
                    if idx and i2 and idx != i2:
                        continue             # "09 - OUTUBRO": incoerente
                    idx = idx or i2
                if gd.get("ano"):
                    if c2.get("ano") and c2["ano"] != gd["ano"]:
                        continue
                    c2["ano"] = gd["ano"]
                if idx:
                    if c2.get("mes") and c2["mes"] != idx:
                        continue
                    c2["mes"] = idx
                prox.append((e.path, c2))
                if len(prox) >= limite:
                    break
        frente = prox
        if not frente:
            break
    for _p, c in frente:
        if c.get("mes"):
            res["meses"].add((c.get("ano"), c["mes"]))
            if c.get("ano"):
                res["anos"].add(c["ano"])
    if frente:
        melhor = max(frente, key=lambda pc: (pc[1].get("ano") or "",
                                              pc[1].get("mes") or 0))
        res["exemplo"] = os.path.relpath(melhor[0], base)
    return res


def _molde(nome):
    """Troca ano/mês por tokens mantendo o resto literal.
    '09 - SETEMBRO - SHOPEE' → '{mes_num} - {mes_nome} - SHOPEE'."""
    n = _norm(nome)
    spans, ano, mes_idx, nome_mes = [], None, None, ""
    ma = re.search(r"(?<![A-Z0-9])(20\d{2})(?![A-Z0-9])", n)   # "2019R" é código, não ano
    if ma:
        spans.append((ma.start(), ma.end(), "{ano}"))
        ano = int(ma.group(1))
    mm = re.search(rf"(?<![A-Z])({_MES_ALT})(?![A-Z])", n)
    if mm:
        tok = mm.group(1)
        mes_idx = _idx_nome_mes(tok)
        nome_mes = nome[mm.start():mm.end()]
        spans.append((mm.start(), mm.end(),
                       "{mes_nome}" if tok in _NOMES_NORM else "{mes_abrev}"))
    for md in re.finditer(r"(?<!\d)(\d{1,2})(?!\d)", n):
        v = int(md.group(1))
        if not 1 <= v <= 12:
            continue
        s, e = md.start(), md.end()
        if any(a <= s < b for a, b, _t in spans):
            continue
        antes, depois = n[:s], n[e:]
        colado_nome = mm is not None and (
            (0 <= mm.start() - e <= 4 and not re.search(r"[A-Z0-9]",
                                                         n[e:mm.start()]))
            or (0 <= s - mm.end() <= 4 and not re.search(r"[A-Z0-9]",
                                                         n[mm.end():s])))
        inteiro = (s == 0 and e == len(n))
        inicio_sep = (s == 0 and depois[:1] in (" ", "-", "_", "."))
        apos_ano = (ma is not None and 0 < s - ma.end() <= 3
                    and not re.search(r"[A-Z0-9]", n[ma.end():s]))
        if not (colado_nome or inteiro or inicio_sep or apos_ano):
            continue
        if mes_idx and v != mes_idx:
            continue
        mes_idx = mes_idx or v
        spans.append((s, e, "{mes_num}" if len(md.group(1)) == 2
                      else "{mes_num:d}"))
        break
    if not spans:
        return None
    spans.sort()
    molde, pos = "", 0
    for s, e, tok in spans:
        molde += nome[pos:s] + tok
        pos = e
    molde += nome[pos:]
    return {"molde": molde, "ano": ano, "mes": mes_idx, "nome_mes": nome_mes}


def _canoniza(p):
    return p.replace("{mes_num} - {mes_nome}", "{mes}")


def _estilo_dos_nomes(nomes):
    nomes = [x for x in nomes if x]
    if not nomes:
        return {"caixa": "upper", "acento": True}
    up = sum(1 for x in nomes if x.isupper())
    ti = sum(1 for x in nomes if x.istitle())
    lo = sum(1 for x in nomes if x.islower())
    caixa = max((up, "upper"), (ti, "title"), (lo, "lower"))[1]
    acento = True
    for x in nomes:
        if _norm(x) == "MARCO":
            acento = "Ç" in x.upper()
    return {"caixa": caixa, "acento": acento}


def detectar_padrao_mes(base, limite=500):
    """Descobre como o grupo organiza ano/mês olhando as pastas existentes.
    Devolve candidatos do melhor para o pior:
    {pattern, base, meses, anos, ultimo, confianca, fora, estilo, exemplo}."""
    if not base or not os.path.isdir(base):
        return []
    brutos = []     # (molde_relativo, ano, mes, nome_mes_original, base_usada)
    try:
        nivel1 = [e for e in os.scandir(base) if e.is_dir()][:limite * 6]
    except OSError:
        return []
    anos_abertos = 0
    for e in nivel1:
        r1 = _molde(e.name)
        if not r1:
            continue
        if r1["mes"]:
            brutos.append((r1["molde"], r1["ano"], r1["mes"], r1["nome_mes"],
                           base))
            continue
        if r1["ano"]:
            anos_abertos += 1
            if anos_abertos > 40:        # trava de segurança
                continue
            try:
                filhos = [f for f in os.scandir(e.path) if f.is_dir()][:limite]
            except OSError:
                continue
            for f in filhos:
                r2 = _molde(f.name)
                if r2 and r2["mes"] and not r2["ano"]:
                    brutos.append((r1["molde"] + "/" + r2["molde"], r1["ano"],
                                   r2["mes"], r2["nome_mes"], base))

    # a própria base tem ano no nome ("Shopee 2026") e os meses estão dentro:
    # o padrão certo mora um nível acima
    nb = os.path.basename(os.path.normpath(base))
    rb = _molde(nb)
    if rb and rb["ano"] and not rb["mes"]:
        pai = os.path.dirname(os.path.normpath(base))
        for m, a, ms, nm, _b in list(brutos):
            if "/" not in m and not a:
                brutos.append((rb["molde"] + "/" + m, rb["ano"], ms, nm, pai))

    grupos = {}
    for m, a, ms, nm, b in brutos:
        chave = (_norm(_canoniza(m)), b)
        grupos.setdefault(chave, []).append((m, a, ms, nm, b))

    cands = []
    for (_k, b), itens in grupos.items():
        recente = max(itens, key=lambda x: (x[1] or 0, x[2] or 0))
        pattern = _canoniza(recente[0])
        so_numero = not ({"mes", "mes_nome", "mes_abrev"} &
                         _vars_do_padrao(pattern))
        distintos = {x[2] for x in itens}
        if so_numero and len(distintos) < 2:
            continue           # um "1" solto não prova nada ("Loja 1")
        an = analisar_padrao(b, pattern)
        n = len(an["meses"])
        if n == 0:
            continue
        conf = "alta" if n >= 3 else "media"
        ultimo = max(an["meses"], key=lambda x: (x[0] or "", x[1]))
        cands.append({
            "pattern": pattern, "base": b, "meses": n,
            "anos": sorted(an["anos"]), "ultimo": ultimo,
            "confianca": conf, "fora": an["fora"],
            "estilo": _estilo_dos_nomes([x[3] for x in itens]),
            "exemplo": an["exemplo"],
            "base_diferente": os.path.normcase(b) != os.path.normcase(base),
        })
    cands.sort(key=lambda c: (c["confianca"] == "alta",
                              not c["base_diferente"],
                              (c["ultimo"][0] or "", c["ultimo"][1]),
                              c["meses"], -c["fora"]), reverse=True)
    return cands


PRESETS_PADRAO = [
    ("{ano}/{mes}", "Ano › Mês"),
    ("{nome} {ano}/{mes} - {NOME}", "Nome Ano › Mês - NOME"),
    ("{nome} - {ano}/{mes}", "Nome - Ano › Mês"),
    ("{ano}/{mes_nome}", "Ano › NOME DO MÊS"),
    ("{ano}/{mes_num}", "Ano › número do mês"),
    ("", "Sem pasta de ano/mês (clientes direto na base)"),
]


def preset_para_grupo(p, nome_grupo):
    return p.replace("{nome}", nome_grupo).replace("{NOME}", nome_grupo.upper())


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

        # lê os códigos existentes UMA vez; antes isso era refeito a cada pasta
        # criada (200 pastas num mês cheio = dezenas de milhares de leituras)
        try:
            existentes = {
                e.name.split(" - ")[0].upper()
                for e in os.scandir(destino) if e.is_dir()
            }
        except OSError:
            existentes = set()

        for responsavel, qtd in itens:
            log_fn(f"── {responsavel}: {qtd} pasta(s)")
            for _ in range(qtd):
                num += 1
                codigo     = f"{prefixo}{mes_num}{num:04d}{responsavel}"
                nome_pasta = f"{codigo} - Vazio"
                path_pasta = os.path.join(destino, nome_pasta)
                if codigo.upper() not in existentes:
                    os.makedirs(path_pasta)
                    os.makedirs(os.path.join(path_pasta, "#ENVIAR"))
                    existentes.add(codigo.upper())
                    log_fn(f"  Criado: {nome_pasta}")
                    total += 1
                else:
                    log_fn(f"  Já existe, pulando: {codigo}", aviso=True)
        return total
    finally:
        if pause_od:
            log_fn("Retomando OneDrive...")
            resume_onedrive()


# ═══════════════════════════════════════════════════════════════════════════════
# OPERAÇÕES SOBRE PASTAS EXISTENTES (renomear em massa, excluir)
# ═══════════════════════════════════════════════════════════════════════════════
def _sanitiza_nome(nome):
    """Nome utilizável no Windows, ou None se não sobrar nada."""
    nome = _BAD_CHARS.sub("", (nome or "").strip()).rstrip(" .")
    return nome or None


def preview_rename(nomes, op, **kw):
    """Calcula os novos nomes SEM tocar no disco.
    Devolve [(antigo, novo, problema_ou_None), ...] — `problema` explica por
    que aquele item não pode ser renomeado."""
    saida = []
    for i, antigo in enumerate(nomes):
        novo = antigo
        if op == "substituir":
            de, para = kw.get("de", ""), kw.get("para", "")
            if de:
                if kw.get("ignorar_caso", True):
                    novo = re.sub(re.escape(de), lambda _m: para, antigo,
                                  flags=re.IGNORECASE)
                else:
                    novo = antigo.replace(de, para)
        elif op == "afixo":
            base = antigo
            rp, rs = kw.get("remover_prefixo", ""), kw.get("remover_sufixo", "")
            if rp and base.lower().startswith(rp.lower()):
                base = base[len(rp):]
            if rs and base.lower().endswith(rs.lower()):
                base = base[:-len(rs)] if rs else base
            novo = f"{kw.get('prefixo', '')}{base}{kw.get('sufixo', '')}"
        elif op == "renumerar":
            fmt_tok = kw.get("formato", "{seq:03d}")
            inicio  = int(kw.get("inicio", 1))
            padrao  = kw.get("padrao", "{seq} {nome}")
            n = _SEQ_RE.sub("", antigo).strip()
            try:
                novo = padrao.format(seq=inicio + i, nome=n).strip()
            except Exception:
                novo = antigo
            else:
                # aplica o formato escolhido ao número
                num = fmt_tok.format(seq=inicio + i) if "{" in fmt_tok else fmt_tok
                novo = padrao.replace("{seq}", num).replace("{nome}", n).strip()
        elif op == "cliente":
            cli = kw.get("novo", "").strip()
            if " - " in antigo:
                novo = f"{antigo.split(' - ')[0]} - {cli}" if cli else antigo
            else:
                novo = f"{antigo} - {cli}" if cli else antigo

        if i in kw.get("manter", ()):
            novo = antigo                  # desmarcado pelo usuário: fica igual
        problema = None
        limpo = _sanitiza_nome(novo)
        if limpo is None:
            problema = "nome vazio ou inválido"
        elif limpo != novo:
            novo, problema = limpo, "caracteres inválidos removidos"
        saida.append([antigo, novo, problema])

    # colisões: compara TODOS os nomes finais, inclusive os que não mudaram
    # (renomear "a"→"b" quando já existe um "b" parado também é conflito)
    contagem = {}
    for antigo, novo, _p in saida:
        contagem.setdefault(novo.lower(), []).append(antigo)
    for linha in saida:
        antigo, novo, problema = linha
        # só é problema para quem está MUDANDO: quem fica parado não tem culpa
        if problema is not None or novo == antigo:
            continue
        donos = contagem.get(novo.lower(), [])
        if len(donos) > 1:
            outro = next((d for d in donos if d != antigo), donos[0])
            linha[2] = f"nome repetido (conflita com '{outro}')"
    return [tuple(l) for l in saida]


def aplicar_rename(dir_pai, pares):
    """Renomeia de fato. Usa nomes temporários quando há troca circular
    (A→B e B→A), que o os.rename sozinho não resolve.
    Devolve (quantos_ok, [erros])."""
    reais = [(a, n) for a, n, p in pares if n != a and p is None]
    if not reais:
        return 0, []
    existentes = set()
    try:
        existentes = {e.name.lower() for e in os.scandir(dir_pai)}
    except OSError:
        pass
    origens = {a.lower() for a, _ in reais}
    erros, feitos = [], 0
    tmp_map = []
    for antigo, novo in reais:
        alvo = novo.lower()
        # colide com algo que também vai ser renomeado → passa pelo temporário
        if alvo in existentes and alvo not in origens:
            erros.append(f"'{novo}' já existe")
            continue
        try:
            if alvo in origens and alvo != antigo.lower():
                tmp = os.path.join(dir_pai, f"__ff_tmp_{uuid.uuid4().hex[:8]}")
                os.rename(os.path.join(dir_pai, antigo), tmp)
                tmp_map.append((tmp, novo))
            else:
                os.rename(os.path.join(dir_pai, antigo),
                          os.path.join(dir_pai, novo))
                feitos += 1
        except OSError as e:
            erros.append(f"'{antigo}': {e.strerror or e}")
    for tmp, novo in tmp_map:
        try:
            os.rename(tmp, os.path.join(dir_pai, novo))
            feitos += 1
        except OSError as e:
            erros.append(f"'{novo}': {e.strerror or e}")
    return feitos, erros


def mandar_para_lixeira(caminhos):
    """Exclui mandando para a Lixeira do Windows (dá para restaurar).
    Devolve (quantos_ok, [erros])."""
    try:
        from send2trash import send2trash
    except ImportError:
        return 0, ["A biblioteca 'send2trash' não está instalada — "
                   "não é possível excluir com segurança."]
    ok, erros = 0, []
    for c in caminhos:
        try:
            send2trash(os.path.abspath(c))
            ok += 1
        except Exception as e:
            erros.append(f"'{os.path.basename(c)}': {e}")
    return ok, erros


def pasta_protegida(caminho):
    """Motivo para NÃO deixar apagar esta pasta inteira, ou None."""
    if not caminho:
        return "sem pasta base"
    try:
        p = os.path.normcase(os.path.abspath(caminho)).rstrip("\\/")
    except Exception:
        return "caminho inválido"
    if len(p) <= 3:                               # "c:" ou "c:\"
        return "é a raiz de um disco"
    casa = os.path.normcase(os.path.expanduser("~")).rstrip("\\/")
    if p == casa:
        return "é a sua pasta de usuário"
    especiais = [os.environ.get(v, "") for v in
                 ("WINDIR", "PROGRAMFILES", "PROGRAMFILES(X86)", "APPDATA",
                  "LOCALAPPDATA")]
    especiais += [os.path.join(casa, n) for n in
                  ("desktop", "documents", "downloads", "documentos",
                   "área de trabalho")]
    for e in especiais:
        if e and p == os.path.normcase(e).rstrip("\\/"):
            return "é uma pasta do sistema"
    for r in onedrive_roots():
        if p == r.rstrip("\\/"):
            return "é a raiz do OneDrive"
    return None


def tamanho_de(caminho):
    """Tamanho total em bytes (percorre subpastas). Best-effort."""
    if os.path.isfile(caminho):
        try:
            return os.path.getsize(caminho)
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(caminho):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def fmt_tamanho(b):
    for u in ("B", "KB", "MB", "GB"):
        if b < 1024 or u == "GB":
            return f"{b:.0f} {u}" if u == "B" else f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} GB"


def buscar_pastas(base, termo, limite=100, profundidade=6):
    """Pastas da base cujo código é o termo (primeiro) ou cujo nome contém o
    termo, ignorando maiúsculas e acentos. Não entra em pastas '#...'."""
    t = _norm((termo or "").strip())
    if not t or not base or not os.path.isdir(base):
        return []
    exatos, parecidos = [], []
    base_n = os.path.normpath(base)
    for root, dirs, _files in os.walk(base_n):
        nivel = root[len(base_n):].count(os.sep)
        dirs[:] = [d for d in dirs if not d.startswith("#")]
        for d in dirs:
            n = _norm(d)
            caminho = os.path.join(root, d)
            if n.split(" - ")[0] == t:
                exatos.append(caminho)
            elif t in n:
                parecidos.append(caminho)
        if len(exatos) + len(parecidos) >= limite:
            break
        if nivel + 1 >= profundidade:
            dirs[:] = []
    return (exatos + parecidos)[:limite]


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


# ═══════════════════════════════════════════════════════════════════════════════
# CONFERÊNCIA DE PASTAS
# Resolve um problema real da operação: às vezes o OneDrive não aplica o
# rename e a pasta continua "A090001M - Vazio" mesmo com a arte pronta dentro.
# Aqui detectamos esse caso e sugerimos o nome do cliente a partir dos
# arquivos (o .cdr costuma ser salvo com o nome do cliente).
# ═══════════════════════════════════════════════════════════════════════════════
EXT_PRIORIDADE = [".cdr", ".ai", ".psd", ".pdf", ".eps",
                  ".jpg", ".jpeg", ".png", ".tif", ".tiff"]

_LIXO_NOME = re.compile(
    r"\b(final|finalizado|ok|aprovad[oa]|arte|artes|novo|nova|copy|copia|cópia|"
    r"v\d+|versao\d*|versão\d*|rev\d*|corrigid[oa]|alterad[oa]|editad[oa]|"
    r"print|impressao|impressão|frente|verso|teste)\b",
    re.IGNORECASE)


def _limpa_nome_cliente(bruto, codigo=""):
    """Do nome do arquivo para um nome de cliente apresentável."""
    nome = os.path.splitext(bruto)[0]
    if codigo:
        nome = re.sub(re.escape(codigo), " ", nome, flags=re.IGNORECASE)
    # separadores viram espaço ANTES de caçar palavras-lixo: "_" conta como
    # letra para o regex, então "\bFINAL\b" não casaria em "_FINAL_"
    nome = re.sub(r"[_\-–—.]+", " ", nome)
    nome = re.sub(r"\d{6,}", " ", nome)          # códigos soltos
    nome = _LIXO_NOME.sub(" ", nome)
    nome = re.sub(r"\s{2,}", " ", nome).strip(" -–—_.")
    if len(nome) < 2:
        return ""
    if nome.isupper() or nome.islower():
        nome = " ".join(p.capitalize() if len(p) > 2 else p
                        for p in nome.split())
    return nome


def arquivos_da_pasta(path, limite=200):
    """Arquivos dentro da pasta (incluindo subpastas), do mais relevante
    para o menos, segundo a extensão."""
    achados = []
    for root, _dirs, files in os.walk(path):
        for f in files:
            if f.startswith("~$") or f.lower() == "thumbs.db":
                continue
            achados.append(os.path.join(root, f))
            if len(achados) >= limite:
                break
        if len(achados) >= limite:
            break

    def peso(p):
        ext = os.path.splitext(p)[1].lower()
        return EXT_PRIORIDADE.index(ext) if ext in EXT_PRIORIDADE else 99
    achados.sort(key=peso)
    return achados


def sugerir_cliente(path, codigo=""):
    """Melhor palpite de nome do cliente a partir dos arquivos de dentro."""
    for arq in arquivos_da_pasta(path):
        nome = _limpa_nome_cliente(os.path.basename(arq), codigo)
        if nome:
            return nome, os.path.basename(arq)
    return "", ""


def iniciais_do_codigo(codigo, prefixo=""):
    cod = codigo[len(prefixo):] if prefixo and codigo.startswith(prefixo) else codigo
    ini = ""
    for ch in reversed(cod):
        if ch.isalpha():
            ini = ch + ini
        else:
            break
    return ini


PROVISORIOS_PADRAO = ["Vazio"]


def _eh_provisorio(texto, provisorios):
    """'Vazio', 'vazio 0001', 'VAZIO-12' contam como nome provisório."""
    t = re.sub(r"[\s\-_.]*\d+$", "", _norm(texto or "")).strip()
    t = re.sub(r"^\d+[\s\-_.]*", "", t).strip()
    return bool(t) and t in {_norm(p).strip() for p in provisorios}


def nome_corrigido(item, cliente):
    """Nome final de uma pasta provisória depois de receber o cliente."""
    cliente = (cliente or "").strip()
    if item.get("tem_codigo"):
        return f"{item['codigo']} - {cliente}"
    padroes = "|".join(re.escape(p) for p in
                       item.get("provisorios", ["Vazio"]))
    resto = re.sub(r"(?i)\b(" + padroes + r")\b", "",
                   item["nome"]).strip(" -_.")
    return f"{resto} - {cliente}" if resto else cliente


def conferir_pasta(pai, provisorios=None, usa_enviar=True, prefixo="",
                   filtro_mes=None):
    """Classifica as subpastas de `pai`. Estados:
       ok            — tem entrega (arquivo em #ENVIAR, ou qualquer arquivo)
       sem_arquivo   — já tem nome definitivo, mas nada entregue
       vazia         — nome provisório ("Vazio") e realmente sem nada
       nao_renomeada — nome provisório MAS com arquivos (o OneDrive falhou)"""
    provisorios = provisorios or PROVISORIOS_PADRAO
    itens = []
    if not pai or not os.path.isdir(pai):
        return {"destino": pai, "itens": [], "por_pessoa": {}}
    for nome in sorted(os.listdir(pai)):
        caminho = os.path.join(pai, nome)
        if not os.path.isdir(caminho) or nome.startswith("#"):
            continue
        if filtro_mes and _cod_mes(nome, prefixo) != filtro_mes:
            continue
        tem_codigo = " - " in nome
        if tem_codigo:
            codigo, cliente = nome.split(" - ", 1)
        else:
            codigo, cliente = nome, ""
        prov = _eh_provisorio(cliente if tem_codigo else nome, provisorios)
        arquivos = arquivos_da_pasta(caminho)
        if usa_enviar:
            enviar = os.path.join(caminho, "#ENVIAR")
            try:
                entregue = os.path.isdir(enviar) and any(
                    os.path.isfile(os.path.join(enviar, f))
                    for f in os.listdir(enviar))
            except OSError:
                entregue = False
        else:
            entregue = bool(arquivos)

        if prov and arquivos:
            estado = "nao_renomeada"
        elif prov:
            estado = "vazia"
        elif entregue:
            estado = "ok"
        else:
            estado = "sem_arquivo"

        sugestao = fonte = ""
        if estado == "nao_renomeada":
            sugestao, fonte = sugerir_cliente(caminho,
                                              codigo if tem_codigo else "")
        itens.append({
            "codigo": codigo, "cliente": cliente, "nome": nome,
            "path": caminho, "estado": estado, "tem_codigo": tem_codigo,
            "iniciais": iniciais_do_codigo(codigo, prefixo) if tem_codigo else "",
            "n_arquivos": len(arquivos), "sugestao": sugestao, "fonte": fonte,
            "tem_enviar": entregue, "provisorios": list(provisorios),
        })

    por_pessoa = {}
    for it in itens:
        p = por_pessoa.setdefault(
            it["iniciais"] or "?",
            {"total": 0, "ok": 0, "sem_arquivo": 0, "vazia": 0,
             "nao_renomeada": 0})
        p["total"] += 1
        p[it["estado"]] += 1
    return {"destino": pai, "itens": itens, "por_pessoa": por_pessoa}


def conferir_pastas(group, ano, mes):
    """Conferência do mês de um grupo marketplace. Se o grupo não tem pasta
    por mês, todos os meses dividem a mesma pasta: filtra pelo código."""
    padrao = group.get("dest_pattern") or ""
    return conferir_pasta(
        mp_destino(group, ano, mes),
        provisorios=group.get("provisorios") or PROVISORIOS_PADRAO,
        usa_enviar=group.get("usa_enviar", group.get("kind") == "marketplace"),
        prefixo=group.get("prefix", ""),
        filtro_mes=None if padrao_tem_mes(padrao) else str(mes)[:2])


def distribuir_total(total, pessoas):
    """Divide um total entre pessoas, distribuindo o resto de um em um.
    Ex.: 100 entre 3 → 34, 33, 33."""
    n = len(pessoas)
    if n <= 0 or total <= 0:
        return {p: 0 for p in pessoas}
    base, resto = divmod(int(total), n)
    return {p: base + (1 if i < resto else 0) for i, p in enumerate(pessoas)}


# ═══════════════════════════════════════════════════════════════════════════════
# HISTÓRICO DE LOTES
# ═══════════════════════════════════════════════════════════════════════════════
HISTORY_FILE = os.path.join(_DIR, "folderflow_history.json")


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                return d if isinstance(d, list) else []
        except Exception:
            return []
    return []


def registrar_lote(grupo_nome, ano, mes, itens, codigos=None):
    """Guarda um lote criado, para sugerir pessoas/quantidades depois."""
    hist = load_history()
    hist.append({
        "quando": datetime.datetime.now().isoformat(timespec="seconds"),
        "grupo": grupo_nome, "ano": ano, "mes": mes,
        "itens": [{"pessoa": p, "qtd": q} for p, q in itens],
        "codigos": codigos or [],
    })
    del hist[:-500]
    tmp = HISTORY_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=2)
        os.replace(tmp, HISTORY_FILE)
    except OSError:
        pass
    return hist


def sugestoes_de_pessoas(grupo_nome, limite=8):
    """Pessoas mais usadas neste grupo, com a quantidade típica (mediana)."""
    hist = [h for h in load_history() if h.get("grupo") == grupo_nome]
    freq, quantidades = {}, {}
    for h in hist:
        for it in h.get("itens", []):
            p = (it.get("pessoa") or "").upper()
            if not p:
                continue
            freq[p] = freq.get(p, 0) + 1
            quantidades.setdefault(p, []).append(int(it.get("qtd") or 0))
    saida = []
    for p, n in sorted(freq.items(), key=lambda kv: -kv[1])[:limite]:
        qs = sorted(quantidades[p])
        saida.append((p, qs[len(qs) // 2] if qs else 1, n))
    return saida


def ultimo_lote(grupo_nome):
    for h in reversed(load_history()):
        if h.get("grupo") == grupo_nome and h.get("itens"):
            return h
    return None


def _cod_mes(nome, prefixo):
    """'A090012IB - Cliente' → '09' (mês que o código carrega)."""
    cod = nome.split(" - ")[0]
    if prefixo and cod.upper().startswith(prefixo.upper()):
        cod = cod[len(prefixo):]
    return cod[:2] if len(cod) >= 2 and cod[:2].isdigit() else None


def meses_existentes(group, ano):
    """Quais meses já têm pastas, para colorir a fita de meses.
    Com pasta por mês no padrão, olha se a pasta do mês existe. Sem ela,
    todos os meses caem na mesma pasta — então conta pelo CÓDIGO, que é
    como a numeração do mês já funciona."""
    saida = {}
    padrao = group.get("dest_pattern") or ""
    if padrao_tem_mes(padrao):
        for m in MESES:
            d = mp_destino(group, ano, m)
            try:
                existe = os.path.isdir(d)
                n = len([e for e in os.scandir(d) if e.is_dir()]) if existe else 0
            except OSError:
                existe, n = False, 0
            saida[m] = {"existe": existe, "pastas": n, "por_codigo": False}
        return saida
    destino = mp_destino(group, ano, MESES[0])
    prefixo = group.get("prefix", "")
    cont = {m[:2]: 0 for m in MESES}
    try:
        for e in os.scandir(destino):
            if e.is_dir():
                mm = _cod_mes(e.name, prefixo)
                if mm in cont:
                    cont[mm] += 1
    except OSError:
        pass
    for m in MESES:
        n = cont[m[:2]]
        saida[m] = {"existe": n > 0, "pastas": n, "por_codigo": True}
    return saida


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
                caminho = os.path.join(root, d)
                if " - " in d:
                    codigo  = d.split(" - ")[0].upper()
                    cliente = d.split(" - ", 1)[1]
                else:
                    # pastas sem o padrão "CÓDIGO - Cliente" também entram,
                    # senão grupos de estrutura genérica somem da busca
                    codigo, cliente = d.upper(), ""
                chave = codigo
                if chave in index:
                    # dois lugares com o mesmo nome não podem se sobrescrever
                    chave = f"{codigo}\x00{caminho.upper()}"
                index[chave] = {
                    "path":    caminho,
                    "nome":    d,
                    "plat":    label,
                    "cliente": cliente,
                    "codigo":  codigo,
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
    # respeita a resposta do assistente: quem disse que não usa Trello
    # não vê nem a interface nem tem chamadas disparadas
    if cfg.get("usa_trello") is False:
        return False
    return trello_keys_ok(cfg) and bool(group.get("board_id"))


def codigo_re_do_grupo(group):
    """Regex do código considerando o prefixo do grupo (antes o 'A' do
    Mercado Livre estava fixo, e outros prefixos ficavam invisíveis)."""
    pref = re.escape((group or {}).get("prefix", "") or "")
    return re.compile(rf'^({pref}\d{{6}}[A-Z]+) - (.+)$')


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
TREE_HOVER = "#1e1e22"   # realce discreto da linha sob o mouse
TREE_SEL   = "#2b331d"   # seleção: lime bem escuro, legível sem berrar
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
        # aspas simples do PowerShell: escapa duplicando, e assim nem "$" nem
        # aspas no nome da pasta quebram ou injetam comando
        ps_literal = "'" + path.replace("'", "''") + "'"
        ps = (
            f'$path = {ps_literal};'
            f'$shell = New-Object -ComObject Shell.Application;'
            f'$wins = @($shell.Windows());'
            f'if ($wins.Count -gt 0) {{ $wins[0].Navigate($path) }}'
            f'else {{ explorer $path }}')
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        subprocess.Popen(["explorer", path])


# ═══════════════════════════════════════════════════════════════════════════════
# ÁRVORE ESTILO IDE (canvas único e virtualizado)
#
# Por que canvas em vez de widgets por linha: cada linha feita de widgets tem
# ~20 componentes, e o mouse atravessando a linha dispara Enter/Leave uma vez
# por fronteira — é isso que fazia o hover piscar e "não pegar". Aqui a árvore
# inteira é um widget só: o hover vira (y ÷ altura da linha), recolher/expandir
# é um splice de lista, e só as ~45 linhas visíveis são desenhadas — então a
# árvore do disco aguenta dezenas de milhares de itens.
# ═══════════════════════════════════════════════════════════════════════════════
class TreeRow:
    __slots__ = ("key", "depth", "label", "icon", "badge", "kind", "payload",
                 "expandable", "expanded", "loaded", "state")

    def __init__(self, key, depth, label, icon="", badge="", kind="folder",
                 payload=None, expandable=False, state="normal"):
        self.key        = key
        self.depth      = depth
        self.label      = label
        self.icon       = icon
        self.badge      = badge
        self.kind       = kind
        self.payload    = payload
        self.expandable = expandable
        self.expanded   = False
        self.loaded     = False
        self.state      = state


class ContextMenu:
    """Menu nativo do Windows pintado com a paleta do app.
    Uma instância reusada — criar um tk.Menu por clique vaza objetos Tcl."""

    def __init__(self, parent):
        self.m = tk.Menu(parent, tearoff=0, bg=BG_CARD, fg=FG_MAIN,
                         activebackground=ACCENT_DK, activeforeground=FG_MAIN,
                         disabledforeground=FG_DIM, bd=0, relief="flat",
                         activeborderwidth=0, font=("Segoe UI", 10))

    def show(self, items, x_root, y_root):
        """items: lista de (rótulo, callback, habilitado) ou None (separador)."""
        self.m.delete(0, "end")
        for it in items:
            if it is None:
                self.m.add_separator()
                continue
            label, cmd, enabled = it
            self.m.add_command(label=label, command=cmd,
                               state="normal" if enabled else "disabled")
        try:
            self.m.tk_popup(int(x_root), int(y_root))
        finally:
            self.m.grab_release()


class IconeRecolher(tk.Canvas):
    """Botão desenhado de "recolher/expandir tudo".
    Duas setas apontando uma para a outra = recolher; de costas = expandir."""

    def __init__(self, parent, command=None, bg=BG_MAIN):
        try:
            s = ctk.ScalingTracker.get_widget_scaling(parent)
        except Exception:
            s = 1.0
        self.tam = max(22, int(28 * s))
        super().__init__(parent, width=self.tam, height=self.tam, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._bg = bg
        self.command = command
        self.recolher = True           # o que o próximo clique vai fazer
        self._hover = False
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Button-1>", lambda e: self.command and self.command())
        self._desenha()

    def set_modo(self, recolher):
        if bool(recolher) != self.recolher:
            self.recolher = bool(recolher)
            self._desenha()

    def _set_hover(self, on):
        self._hover = on
        self._desenha()

    def _desenha(self):
        self.delete("all")
        t = self.tam
        if self._hover:
            r = t * 0.18
            self.create_rectangle(1, 1, t - 1, t - 1, fill=BG_HOVER, width=0)
            for x, y in ((1, 1), (t - 1 - 2 * r, 1), (1, t - 1 - 2 * r),
                         (t - 1 - 2 * r, t - 1 - 2 * r)):
                self.create_oval(x, y, x + 2 * r, y + 2 * r, fill=BG_HOVER,
                                 width=0)
        cor = FG_MAIN if self._hover else FG_LABEL
        cx, w = t / 2, t * 0.22
        a, b = t * 0.22, t * 0.40            # faixa de cada seta
        lw = max(2, int(t / 14))
        if self.recolher:     # apontando uma para a outra: ▼ em cima, ▲ embaixo
            setas = [(cx - w, a, cx, b, cx + w, a),
                     (cx - w, t - a, cx, t - b, cx + w, t - a)]
        else:                 # de costas: ▲ em cima, ▼ embaixo
            setas = [(cx - w, b, cx, a, cx + w, b),
                     (cx - w, t - b, cx, t - a, cx + w, t - b)]
        for pts in setas:
            self.create_line(*pts, fill=cor, width=lw, capstyle="round",
                             joinstyle="round")


class TreeCanvas(tk.Frame):
    """Árvore virtualizada. Recebe as linhas de um `provider` e avisa o dono
    por callbacks. Não conhece modelo nem disco — só desenha e responde."""

    def __init__(self, parent, provider=None, *, on_select=None,
                 on_activate=None, on_context=None, on_rename=None,
                 on_action=None, multi=False, **kw):
        super().__init__(parent, bg=BG_PANEL, highlightthickness=0, bd=0, **kw)
        self.provider    = provider
        self.on_select   = on_select
        self.on_activate = on_activate
        self.on_context  = on_context
        self.on_rename   = on_rename
        self.on_action   = on_action
        self.multi       = multi

        # o canvas não acompanha a escala do Windows como os widgets do CTk
        try:
            s = ctk.ScalingTracker.get_widget_scaling(self)
        except Exception:
            s = 1.0
        self.s        = s
        self.ROW_H    = max(20, int(26 * s))
        self.INDENT   = max(12, int(18 * s))
        self.PAD      = max(4, int(8 * s))
        self.font     = tkfont.Font(family="Segoe UI", size=max(8, int(10 * s)))
        self.font_b   = tkfont.Font(family="Segoe UI", size=max(7, int(9 * s)),
                                    weight="bold")

        self._flat     = []
        self._expanded = set()
        self._sel      = []
        self._anchor   = None
        self._hover    = -1
        self._bg_ids   = {}
        self._gen      = 0

        self.canvas = tk.Canvas(self, bg=BG_PANEL, bd=0, highlightthickness=0,
                                takefocus=True, yscrollincrement=self.ROW_H)
        self.vsb = ctk.CTkScrollbar(self, command=self.canvas.yview,
                                    width=12, button_color=BG_HOVER,
                                    button_hover_color=FG_DIM,
                                    fg_color="transparent")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y", padx=(0, 2), pady=2)
        self.canvas.pack(side="left", fill="both", expand=True)

        self.menu = ContextMenu(self)

        # único Entry reaproveitado para renomear no lugar
        self._edit_idx = -1
        self.entry = tk.Entry(self.canvas, bd=0, relief="flat",
                              bg=BG_INPUT, fg=FG_MAIN, insertbackground=FG_MAIN,
                              highlightthickness=1, highlightbackground=ACCENT,
                              highlightcolor=ACCENT,
                              font=("Segoe UI", max(8, int(10 * s))))
        self.entry.bind("<Return>",   lambda e: self._commit_edit())
        self.entry.bind("<Escape>",   lambda e: self._cancel_edit())
        self.entry.bind("<FocusOut>", lambda e: self._commit_edit())

        c = self.canvas
        c.bind("<Motion>",           self._on_motion)
        c.bind("<Leave>",            lambda e: self._set_hover(-1))
        c.bind("<Button-1>",         self._on_click)
        c.bind("<Double-Button-1>",  self._on_double)
        c.bind("<Button-3>",         self._on_right)
        c.bind("<MouseWheel>",       self._on_wheel)
        c.bind("<Configure>",        lambda e: self.after_idle(self._redraw))
        c.bind("<Key-F2>",           lambda e: self.begin_edit())
        c.bind("<Delete>",           lambda e: self._fire_action("delete"))
        c.bind("<Control-d>",        lambda e: self._fire_action("duplicate"))
        c.bind("<Up>",               lambda e: self._move_sel(-1))
        c.bind("<Down>",             lambda e: self._move_sel(1))
        c.bind("<Left>",             lambda e: self._arrow_collapse())
        c.bind("<Right>",            lambda e: self._arrow_expand())

    # ── dados ────────────────────────────────────────────────────────────────
    def set_provider(self, provider):
        self.provider = provider
        self.reload()

    def reload(self, keep=True):
        """Reconstrói a lista visível preservando expansão e seleção."""
        self._cancel_edit()
        if not keep:
            self._expanded.clear()
            self._sel.clear()
        flat = []
        if self.provider is not None:
            def walk(rows, depth):
                for r in rows:
                    r.depth = depth
                    flat.append(r)
                    if r.expandable and r.key in self._expanded:
                        r.expanded = True
                        walk(self.provider.children(r), depth + 1)
                    else:
                        r.expanded = False
            try:
                walk(self.provider.roots(), 0)
            except Exception:
                flat = []
        self._flat = flat
        vivos = {r.key for r in flat}
        self._sel = [k for k in self._sel if k in vivos]
        self._redraw()

    def rows(self):
        return list(self._flat)

    def selection(self):
        by = {r.key: r for r in self._flat}
        return [by[k] for k in self._sel if k in by]

    def selected_row(self):
        s = self.selection()
        return s[0] if s else None

    def select_key(self, key, notify=True):
        self._sel = [key] if key is not None else []
        self._anchor = key
        self._redraw()
        if notify and self.on_select:
            self.on_select(self.selection())

    # ── expandir / recolher ──────────────────────────────────────────────────
    def toggle(self, i):
        if not (0 <= i < len(self._flat)):
            return
        r = self._flat[i]
        if not r.expandable:
            return
        if r.key in self._expanded:
            self._expanded.discard(r.key)
        else:
            self._expanded.add(r.key)
        self.reload()

    def set_all_expanded(self, expandir):
        if expandir:
            # expande em passadas até estabilizar (filhos revelam netos)
            for _ in range(40):
                antes = len(self._expanded)
                for r in self._flat:
                    if r.expandable:
                        self._expanded.add(r.key)
                self.reload()
                if len(self._expanded) == antes:
                    break
        else:
            self._expanded.clear()
            self.reload()

    def all_expanded(self):
        exp = [r for r in self._flat if r.expandable]
        return bool(exp) and all(r.key in self._expanded for r in exp)

    # ── geometria ────────────────────────────────────────────────────────────
    def _x_chevron(self, depth):
        return self.PAD + depth * self.INDENT

    def _x_icon(self, depth):
        return self._x_chevron(depth) + int(15 * self.s)

    def _x_label(self, r):
        x = self._x_icon(r.depth) + int(20 * self.s)
        if r.badge:
            x += self.font_b.measure(r.badge) + int(16 * self.s)
        return x

    # ── desenho ──────────────────────────────────────────────────────────────
    def _visible_range(self):
        try:
            top = self.canvas.canvasy(0)
            h   = self.canvas.winfo_height()
        except Exception:
            return 0, 0
        i0 = max(0, int(top // self.ROW_H) - 1)
        i1 = min(len(self._flat), int((top + h) // self.ROW_H) + 2)
        return i0, i1

    def _bg_color(self, i):
        r = self._flat[i]
        if r.key in self._sel:
            return TREE_SEL
        if i == self._hover:
            return TREE_HOVER
        return BG_PANEL

    def _region_h(self):
        # a área rolável nunca pode ser menor que a janela: se for, a roda do
        # mouse leva a vista para um espaço vazio acima do conteúdo
        total = len(self._flat) * self.ROW_H
        h = self.canvas.winfo_height()
        return max(total, h if h > 1 else 0, 1)

    def _redraw(self):
        c = self.canvas
        c.delete("row")
        self._bg_ids.clear()
        w = max(c.winfo_width(), 10)
        total = len(self._flat) * self.ROW_H
        c.configure(scrollregion=(0, 0, w, self._region_h()))
        if total <= c.winfo_height() and c.canvasy(0) != 0:
            c.yview_moveto(0)

        i0, i1 = self._visible_range()
        for i in range(i0, i1):
            self._draw_row(i, w)

    def _draw_row(self, i, w):
        c = self.canvas
        r = self._flat[i]
        y = i * self.ROW_H
        tag = ("row", f"r{i}")

        bg = c.create_rectangle(0, y, w, y + self.ROW_H, width=0,
                                fill=self._bg_color(i), tags=tag)
        self._bg_ids[i] = bg

        # guias de indentação
        for d in range(r.depth):
            gx = self._x_chevron(d) + int(6 * self.s)
            c.create_line(gx, y, gx, y + self.ROW_H, fill=BORDER, tags=tag)

        cy = y + self.ROW_H // 2
        if r.expandable:
            c.create_text(self._x_chevron(r.depth) + int(6 * self.s), cy,
                          text="▾" if r.expanded else "▸", fill=FG_LABEL,
                          font=self.font, anchor="center",
                          tags=tag + ("chev",))

        cor_txt = FG_DIM if r.state == "exists" else FG_MAIN
        if r.kind in ("file", "copy"):
            cor_txt = FG_DIM if r.state == "exists" else FG_LABEL
        if r.state == "loading":
            cor_txt = FG_DIM

        c.create_text(self._x_icon(r.depth), cy, text=r.icon, fill=cor_txt,
                      font=self.font, anchor="w", tags=tag)

        if r.badge:
            bx = self._x_icon(r.depth) + int(20 * self.s)
            bw = self.font_b.measure(r.badge) + int(12 * self.s)
            bh = int(16 * self.s)
            c.create_rectangle(bx, cy - bh // 2, bx + bw, cy + bh // 2,
                               fill=SEQ_BG, outline=SEQ_BD,
                               tags=tag + ("badge",))
            c.create_text(bx + bw // 2, cy, text=r.badge, fill=SEQ_FG,
                          font=self.font_b, anchor="center",
                          tags=tag + ("badge",))

        # rótulo, cortado com reticências se não couber
        lx = self._x_label(r)
        limite = w - lx - int(60 * self.s)
        txt = r.label
        if limite > 20 and self.font.measure(txt) > limite:
            while txt and self.font.measure(txt + "…") > limite:
                txt = txt[:-1]
            txt += "…"
        c.create_text(lx, cy, text=txt, fill=cor_txt, font=self.font,
                      anchor="w", tags=tag + ("label",))

        # glifos de ação: só na linha sob o mouse (2 itens no canvas inteiro)
        if i == self._hover and r.state != "loading":
            c.create_text(w - int(16 * self.s), cy, text="⋯", fill=FG_LABEL,
                          font=self.font, anchor="center",
                          tags=tag + ("act:menu",))
            c.create_text(w - int(36 * self.s), cy, text="🗑", fill=RED,
                          font=self.font, anchor="center",
                          tags=tag + ("act:delete",))

    def refresh_row(self, key):
        for i, r in enumerate(self._flat):
            if r.key == key:
                self._redraw()
                return

    # ── interação ────────────────────────────────────────────────────────────
    def _index_at(self, ev_y):
        y = self.canvas.canvasy(ev_y)
        i = int(y // self.ROW_H)
        return i if 0 <= i < len(self._flat) else -1

    def _zone_at(self, ev):
        x, y = self.canvas.canvasx(ev.x), self.canvas.canvasy(ev.y)
        for item in reversed(self.canvas.find_overlapping(x, y, x, y)):
            for t in self.canvas.gettags(item):
                if t in ("chev", "label", "badge") or t.startswith("act:"):
                    return t
        return ""

    def _set_hover(self, i):
        if i == self._hover:
            return
        antigo = self._hover
        self._hover = i
        # repinta só os dois fundos afetados; os glifos exigem redesenhar a linha
        for idx in (antigo, i):
            if 0 <= idx < len(self._flat):
                self._draw_row_refresh(idx)

    def _draw_row_refresh(self, i):
        self.canvas.delete(f"r{i}")
        self._draw_row(i, max(self.canvas.winfo_width(), 10))

    def _on_motion(self, ev):
        self._set_hover(self._index_at(ev.y))

    def _on_wheel(self, ev):
        if not self._flat:
            return "break"
        if len(self._flat) * self.ROW_H <= self.canvas.winfo_height():
            return "break"                    # tudo cabe: nada a rolar
        # touchpads mandam deltas pequenos (30, 60); acumula até dar um passo
        self._wheel_acc = getattr(self, "_wheel_acc", 0) + ev.delta
        passos = int(self._wheel_acc / 120)
        if passos == 0:
            return "break"
        self._wheel_acc -= passos * 120
        self.canvas.yview_scroll(-passos * 3, "units")   # 3 linhas por clique
        self._cancel_edit()
        self._redraw()
        self._set_hover(self._index_at(ev.y))
        return "break"

    def _on_click(self, ev):
        self.canvas.focus_set()
        i = self._index_at(ev.y)
        if i < 0:
            self._sel.clear()
            self._redraw()
            if self.on_select:
                self.on_select([])
            return
        zona = self._zone_at(ev)
        r = self._flat[i]
        if zona == "chev":
            self.toggle(i)
            return
        if zona == "act:delete":
            self.select_key(r.key)
            self._fire_action("delete")
            return
        if zona == "act:menu":
            self.select_key(r.key)
            self._popup_menu(i, ev.x_root, ev.y_root)
            return
        if zona == "badge":
            self.select_key(r.key)
            self._fire_action("badge")
            return
        # seleção (com Ctrl/Shift quando multi está ligado)
        if self.multi and (ev.state & 0x0004):        # Ctrl
            if r.key in self._sel:
                self._sel.remove(r.key)
            else:
                self._sel.append(r.key)
            self._anchor = r.key
        elif self.multi and (ev.state & 0x0001) and self._anchor is not None:
            keys = [x.key for x in self._flat]
            try:
                a, b = keys.index(self._anchor), i
                lo, hi = min(a, b), max(a, b)
                self._sel = keys[lo:hi + 1]
            except ValueError:
                self._sel = [r.key]
        else:
            self._sel = [r.key]
            self._anchor = r.key
        self._redraw()
        if self.on_select:
            self.on_select(self.selection())

    def _on_double(self, ev):
        i = self._index_at(ev.y)
        if i < 0:
            return
        zona = self._zone_at(ev)
        if zona == "chev":
            return
        r = self._flat[i]
        if zona == "label" and self.on_rename:
            self.begin_edit(i)
        elif r.expandable:
            self.toggle(i)
        elif self.on_activate:
            self.on_activate(r)

    def _on_right(self, ev):
        self.canvas.focus_set()
        i = self._index_at(ev.y)
        if i >= 0 and self._flat[i].key not in self._sel:
            self.select_key(self._flat[i].key)
        elif i < 0:
            self._sel.clear()
            self._redraw()
        self._popup_menu(i, ev.x_root, ev.y_root)

    def _popup_menu(self, i, xr, yr):
        if self.on_context:
            row = self._flat[i] if 0 <= i < len(self._flat) else None
            itens = self.on_context(row, self.selection())
            if itens:
                self.menu.show(itens, xr, yr)

    def _fire_action(self, action):
        if self.on_action:
            r = self.selected_row()
            if r is not None:
                self.on_action(r, action)

    def _move_sel(self, delta):
        if not self._flat:
            return
        keys = [r.key for r in self._flat]
        if self._sel:
            try:
                i = keys.index(self._sel[-1])
            except ValueError:
                i = 0
        else:
            i = -1 if delta > 0 else 0
        i = max(0, min(len(keys) - 1, i + delta))
        self.select_key(keys[i])
        self.scroll_to(keys[i])

    def _arrow_expand(self):
        r = self.selected_row()
        if r and r.expandable and r.key not in self._expanded:
            self._expanded.add(r.key)
            self.reload()

    def _arrow_collapse(self):
        r = self.selected_row()
        if r and r.expandable and r.key in self._expanded:
            self._expanded.discard(r.key)
            self.reload()

    def scroll_to(self, key):
        for i, r in enumerate(self._flat):
            if r.key == key:
                total = self._region_h()
                topo = self.canvas.canvasy(0)
                alt  = self.canvas.winfo_height()
                y    = i * self.ROW_H
                if y < topo:
                    self.canvas.yview_moveto(y / total)
                elif y + self.ROW_H > topo + alt:
                    self.canvas.yview_moveto((y - alt + self.ROW_H) / total)
                self._redraw()
                return

    # ── renomear no lugar ────────────────────────────────────────────────────
    def begin_edit(self, i=None):
        if self.on_rename is None:
            return
        if i is None:
            r = self.selected_row()
            if r is None:
                return
            i = self._flat.index(r)
        if not (0 <= i < len(self._flat)):
            return
        r = self._flat[i]
        y = i * self.ROW_H - self.canvas.canvasy(0)
        x = self._x_label(r)
        w = max(80, self.canvas.winfo_width() - x - int(60 * self.s))
        self._edit_idx = i
        self.entry.delete(0, "end")
        self.entry.insert(0, r.label)
        self.entry.select_range(0, "end")
        self.entry.place(x=x, y=y + 2, width=w, height=self.ROW_H - 4)
        self.entry.lift()
        self.entry.focus_set()

    def _commit_edit(self):
        if self._edit_idx < 0:
            return
        i, self._edit_idx = self._edit_idx, -1
        novo = self.entry.get().strip()
        self.entry.place_forget()
        if 0 <= i < len(self._flat) and novo and novo != self._flat[i].label:
            if self.on_rename:
                self.on_rename(self._flat[i], novo)

    def _cancel_edit(self):
        if self._edit_idx >= 0:
            self._edit_idx = -1
            self.entry.place_forget()


class TemplateTreeProvider:
    """Alimenta a árvore com os nós do modelo em memória."""

    ICONES = {"folder": "📁", "file": "📄", "copy": "📎"}

    def __init__(self, nodes_ref):
        self.nodes = nodes_ref
        self._seq = [0]

    def _uid(self, n):
        # identidade estável: id() do dict é reciclado pelo CPython após GC
        if "_uid" not in n:
            self._seq[0] += 1
            n["_uid"] = f"n{self._seq[0]}"
        return n["_uid"]

    def _row(self, n, depth=0):
        return TreeRow(
            key=self._uid(n), depth=depth,
            label=_SEQ_RE.sub("", n["name"]).strip() if n.get("repeat")
                  else n["name"],
            icon=self.ICONES.get(n["type"], "📄"),
            badge=f"×{n['repeat']}" if n.get("repeat") else "",
            kind=n["type"], payload=n,
            expandable=bool(n["children"]))

    def roots(self):
        return [self._row(n) for n in self.nodes]

    def children(self, row):
        return [self._row(c) for c in row.payload["children"]]


class DiskTreeProvider:
    """Alimenta a árvore com pastas e arquivos reais do disco.
    Lê sob demanda (só o que for expandido) e guarda o resultado em cache."""

    MAX_ITENS = 5000

    def __init__(self, base=None, on_ready=None, after=None):
        self.base = base
        self._cache = {}
        self.on_ready = on_ready        # avisa a UI quando a leitura terminar
        self._after = after            # `after` da janela (thread da UI)
        self._carregando = set()
        self._gen = 0
        # a thread só ENTREGA aqui; quem mexe na interface é sempre a thread
        # principal, drenando esta fila (chamar `after` do Tk de outra thread
        # não é confiável)
        self._fila = queue.Queue()
        self._bombeando = False

    def _key(self, path):
        return os.path.normcase(os.path.abspath(path))

    def _row_de(self, path, is_dir, depth=0):
        return TreeRow(
            key=self._key(path), depth=depth,
            label=os.path.basename(path) or path,
            icon="📁" if is_dir else "📄",
            kind="folder" if is_dir else "file",
            payload=path, expandable=is_dir)

    def roots(self):
        if self.base and os.path.isdir(self.base):
            return [self._row_de(self.base, True)]
        # sem base definida: as unidades da máquina
        out = []
        for letra in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            d = f"{letra}:\\"
            if os.path.isdir(d):
                out.append(TreeRow(key=self._key(d), depth=0, label=d,
                                   icon="💽", kind="folder", payload=d,
                                   expandable=True))
        return out

    def _ler(self, path):
        """Leitura de verdade do disco. Roda na thread de fundo."""
        k = self._key(path)
        pastas, arquivos = [], []
        try:
            with os.scandir(path) as it:
                for i, e in enumerate(it):
                    if i >= self.MAX_ITENS:
                        pastas.append(TreeRow(
                            key=k + "|mais", depth=0,
                            label=f"… mais itens (limite de {self.MAX_ITENS})",
                            icon="⋯", kind="file", payload=None, state="exists"))
                        break
                    try:
                        if e.is_dir(follow_symlinks=False):
                            pastas.append(self._row_de(e.path, True))
                        else:
                            arquivos.append(self._row_de(e.path, False))
                    except OSError:
                        continue
        except (OSError, PermissionError):
            return [TreeRow(key=k + "|err", depth=0, label="(sem acesso)",
                            icon="⚠", kind="file", payload=None, state="exists")]
        pastas.sort(key=lambda r: r.label.lower())
        arquivos.sort(key=lambda r: r.label.lower())
        return pastas + arquivos

    def children(self, row):
        """Devolve na hora: do cache, ou um marcador enquanto lê em segundo
        plano (uma pasta no OneDrive pode demorar segundos para responder)."""
        path = row.payload
        k = self._key(path)
        if k in self._cache:
            return [self._clone(r) for r in self._cache[k]]
        if self._after is None:            # sem UI: leitura direta
            self._cache[k] = self._ler(path)
            return [self._clone(r) for r in self._cache[k]]
        if k not in self._carregando:
            self._carregando.add(k)
            gen = self._gen

            def tarefa():
                try:
                    filhos = self._ler(path)
                except Exception:
                    filhos = []
                self._fila.put((gen, k, path, filhos))
            threading.Thread(target=tarefa, daemon=True).start()
            self._inicia_bomba()
        return [TreeRow(key=k + "|load", depth=0, label="carregando…",
                        icon="⏳", kind="file", payload=None, state="loading")]

    def _inicia_bomba(self):
        """Agenda a drenagem da fila. Chamado sempre da thread da interface."""
        if self._bombeando or self._after is None:
            return
        self._bombeando = True
        self._after(60, self._bombear)

    def _bombear(self):
        prontos = []
        while True:
            try:
                gen, k, path, filhos = self._fila.get_nowait()
            except queue.Empty:
                break
            self._carregando.discard(k)
            if gen == self._gen:        # descarta leitura obsoleta
                self._cache[k] = filhos
                prontos.append(path)
        if prontos and self.on_ready:
            try:
                self.on_ready(prontos[-1])
            except Exception:
                pass
        if self._carregando:
            self._after(60, self._bombear)
        else:
            self._bombeando = False

    def _clone(self, r):
        n = TreeRow(key=r.key, depth=r.depth, label=r.label, icon=r.icon,
                    kind=r.kind, payload=r.payload, expandable=r.expandable)
        return n

    def invalidate(self, path=None):
        self._gen += 1
        self._carregando.clear()
        if path is None:
            self._cache.clear()
        else:
            self._cache.pop(self._key(path), None)


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

        # ícone da janela (o CustomTkinter agenda o dele — reaplicamos o nosso)
        self._apply_icon()
        self.after(400, self._apply_icon)

        self.after(3000, lambda: threading.Thread(
            target=check_update, args=(self.config_data, self), daemon=True
        ).start())

        self._build_header()
        self.container = ctk.CTkFrame(self, fg_color=BG_MAIN, corner_radius=0)
        self.container.pack(fill="both", expand=True)
        self.show_home()

        if CONFIG_LOAD_WARNING:
            self.after(600, lambda: messagebox.showwarning(
                "Configuração", CONFIG_LOAD_WARNING[0]))
        elif not self.config_data.get("onboarding_ok"):
            if self.groups():
                # quem já tem grupos (ex.: veio da v1 da Flag) não precisa de
                # assistente — herda o que já usava e segue direto
                self.config_data["onboarding_ok"] = True
                self.config_data.setdefault(
                    "usa_trello", bool(self.config_data.get("trello_key")))
                self.config_data.setdefault("usa_onedrive", True)
                if self.config_data.get("usa_trello") is None:
                    self.config_data["usa_trello"] = bool(
                        self.config_data.get("trello_key"))
                if self.config_data.get("usa_onedrive") is None:
                    self.config_data["usa_onedrive"] = True
                self.save()
                self.aplica_preferencias()
            else:
                self.after(500, self.abrir_assistente)

    # ═════════════════════════════════════════════════════════════════════════
    # ASSISTENTE DE PRIMEIRA ABERTURA
    # ═════════════════════════════════════════════════════════════════════════
    def em_segundo_plano(self, tarefa, quando_pronto, ao_progredir=None):
        """Roda `tarefa()` fora da interface e entrega o resultado a
        `quando_pronto` na thread principal. Usa fila porque chamar `after()`
        de dentro de uma thread não é confiável no Tk.
        Com `ao_progredir`, a tarefa recebe `avisa(x)` para mandar progresso,
        que chega em `ao_progredir(x)` também na thread principal."""
        fila = queue.Queue()

        def _worker():
            try:
                if ao_progredir is not None:
                    r = tarefa(lambda x: fila.put(("prog", x)))
                else:
                    r = tarefa()
                fila.put(("ok", r))
            except Exception as e:
                fila.put(("erro", e))

        def _drena():
            while True:
                try:
                    tipo, valor = fila.get_nowait()
                except queue.Empty:
                    self.after(60, _drena)
                    return
                if tipo == "prog":
                    try:
                        ao_progredir(valor)
                    except Exception:
                        pass
                    continue
                quando_pronto(valor if tipo == "ok" else {"erro": str(valor)})
                return

        threading.Thread(target=_worker, daemon=True).start()
        self.after(60, _drena)

    def usa(self, recurso):
        """Trello/OneDrive só aparecem para quem disse que usa."""
        v = self.config_data.get(f"usa_{recurso}")
        return True if v is None else bool(v)

    def abrir_assistente(self):
        win = ctk.CTkToplevel(self, fg_color=BG_MAIN)
        win.title("Bem-vindo ao FolderFlow")
        win.geometry("620x520")
        win.resizable(False, False)
        win.grab_set()
        try:
            win.after(300, lambda: win.iconbitmap(LOGO_ICO)
                      if os.path.exists(LOGO_ICO) else None)
        except Exception:
            pass

        passo = [0]
        resp = {"onedrive": bool(onedrive_roots()), "trello": False,
                "modelo": None, "base": ""}

        corpo = ctk.CTkFrame(win, fg_color="transparent")
        corpo.pack(fill="both", expand=True, padx=28, pady=(24, 8))
        rodape = ctk.CTkFrame(win, fg_color="transparent")
        rodape.pack(fill="x", padx=28, pady=(0, 20))

        pontos = ctk.CTkLabel(rodape, text="", text_color=FG_DIM, font=F(11))
        pontos.pack(side="left")

        def _limpa():
            for w in corpo.winfo_children():
                w.destroy()

        def _titulo(t, s=""):
            ctk.CTkLabel(corpo, text=t, text_color=FG_MAIN, font=F(20, True)
                         ).pack(anchor="w")
            if s:
                ctk.CTkLabel(corpo, text=s, text_color=FG_LABEL, font=F(12),
                             wraplength=540, justify="left"
                             ).pack(anchor="w", pady=(4, 16))

        def _opcao(texto, sub, valor, chave):
            sel = resp[chave] == valor
            c = ctk.CTkFrame(corpo, fg_color=BG_NODE, corner_radius=10,
                             border_width=2 if sel else 1,
                             border_color=ACCENT if sel else BORDER)
            c.pack(fill="x", pady=4)
            ctk.CTkLabel(c, text=texto, text_color=FG_MAIN, font=F(13, True),
                         anchor="w").pack(fill="x", padx=14, pady=(10, 0))
            ctk.CTkLabel(c, text=sub, text_color=FG_LABEL, font=F(11),
                         anchor="w", wraplength=500, justify="left"
                         ).pack(fill="x", padx=14, pady=(2, 10))

            def _clica(_e=None):
                resp[chave] = valor
                _desenha()
            for w in (c, *c.winfo_children()):
                w.bind("<Button-1>", _clica)

        def _desenha():
            _limpa()
            i = passo[0]
            pontos.configure(text=f"passo {i + 1} de 4")
            if i == 0:
                raizes = onedrive_roots()
                _titulo("Suas pastas ficam no OneDrive?",
                        "Se ficarem, o FolderFlow pausa a sincronização "
                        "enquanto cria muitas pastas — fica bem mais rápido e "
                        "evita conflito. Se não, ele nunca mexe no OneDrive.")
                _opcao("Sim, uso OneDrive",
                       (f"Detectei: {os.environ.get('OneDrive') or raizes[0]}" if raizes
                        else "Não achei OneDrive nesta máquina, mas você pode "
                             "marcar assim mesmo."),
                       True, "onedrive")
                _opcao("Não uso", "As pastas ficam só neste computador ou "
                                  "noutro lugar.", False, "onedrive")
            elif i == 1:
                _titulo("Você usa Trello junto com as pastas?",
                        "Se usar, o FolderFlow pode renomear o card e movê-lo "
                        "de lista quando você renomeia a pasta. Se não usar, "
                        "toda a parte de Trello some da tela.")
                _opcao("Sim, uso Trello",
                       "Vou pedir a chave de acesso depois, em Configurações.",
                       True, "trello")
                _opcao("Não uso", "Some tudo de Trello — menos coisa na tela.",
                       False, "trello")
            elif i == 2:
                _titulo("Como você quer começar?",
                        "Dá para mudar tudo depois; isso é só o ponto de "
                        "partida.")
                _opcao("Do zero",
                       "Um grupo vazio para você montar a estrutura do seu "
                       "jeito, com botões e clique direito.", "zero", "modelo")
                for nome in list(READY_TEMPLATES)[:3]:
                    _opcao(f"Modelo: {nome}",
                           "Começa com uma estrutura pronta que você ajusta.",
                           nome, "modelo")
                _opcao("Marketplace (Shopee + Mercado Livre)",
                       "O fluxo de pastas por mês com código e responsável.",
                       "marketplace", "modelo")
            else:
                _titulo("Onde ficam suas pastas?",
                        "Escolha a pasta principal. Tudo que o FolderFlow "
                        "criar vai para dentro dela.")
                lbl = ctk.CTkLabel(corpo, text=resp["base"] or "(nenhuma "
                                   "pasta escolhida ainda)",
                                   text_color=FG_LABEL if resp["base"] else FG_DIM,
                                   font=F(11), wraplength=520, justify="left")

                def _escolher():
                    p = filedialog.askdirectory(parent=win)
                    if p:
                        resp["base"] = os.path.normpath(p)
                        _desenha()
                ctk.CTkButton(corpo, text="📂  Escolher pasta…", height=40,
                              corner_radius=10, fg_color=BG_INPUT,
                              hover_color=BG_HOVER, text_color=FG_MAIN,
                              font=F(13), command=_escolher).pack(fill="x",
                                                                  pady=(0, 8))
                lbl.pack(anchor="w")
                ctk.CTkLabel(corpo, text="Pode pular e definir depois.",
                             text_color=FG_DIM, font=F(10)).pack(anchor="w",
                                                                 pady=(12, 0))
            b_volta.configure(state="normal" if i > 0 else "disabled")
            b_seg.configure(text="Concluir" if i == 3 else "Continuar")

        def _proximo():
            if passo[0] < 3:
                passo[0] += 1
                _desenha()
            else:
                _finaliza(win, resp)

        def _volta():
            if passo[0] > 0:
                passo[0] -= 1
                _desenha()

        b_seg = ctk.CTkButton(rodape, text="Continuar", height=38, width=130,
                              corner_radius=10, fg_color=ACCENT,
                              hover_color=ACCENT_H, text_color=DARK_TXT,
                              font=F(13, True), command=_proximo)
        b_seg.pack(side="right")
        b_volta = ctk.CTkButton(rodape, text="Voltar", height=38, width=90,
                                corner_radius=10, fg_color="transparent",
                                border_width=1, border_color=BORDER,
                                hover_color=BG_HOVER, text_color=FG_LABEL,
                                font=F(12), command=_volta)
        b_volta.pack(side="right", padx=(0, 8))

        _desenha()
        return win

    def _finaliza(self, win, resp):
        cfg = self.config_data
        cfg["usa_onedrive"] = bool(resp["onedrive"])
        cfg["usa_trello"] = bool(resp["trello"])
        cfg["pause_onedrive"] = bool(resp["onedrive"])
        cfg["onboarding_ok"] = True

        escolha = resp.get("modelo")
        if escolha == "marketplace":
            novos = preset_marketplace_groups()
            if resp["base"]:
                for gg in novos:
                    gg["base_path"] = resp["base"]
            cfg["groups"].extend(novos)
        elif escolha:
            gg = default_group("template")
            gg.update({
                "name": "Meu primeiro grupo",
                "base_path": resp["base"],
                "template": (DEFAULT_TEMPLATE if escolha == "zero"
                             else READY_TEMPLATES.get(escolha, DEFAULT_TEMPLATE)),
            })
            cfg["groups"].append(gg)
        self.save()
        self.aplica_preferencias()
        win.destroy()
        self.show_home()

    # ── helpers ──────────────────────────────────────────────────────────────
    def _apply_icon(self):
        try:
            if os.path.exists(LOGO_ICO):
                self.iconbitmap(default=LOGO_ICO)
                self.iconbitmap(LOGO_ICO)
        except Exception:
            pass

    def _clear(self):
        # atalhos globais são religados por cada tela; sem isso o Ctrl+K da
        # home continuava ativo (e apontando para um campo destruído)
        try:
            self.unbind_all("<Control-k>")
        except Exception:
            pass
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
        # logo (imagem real; fallback em emoji se o arquivo faltar)
        logo_img = None
        try:
            from PIL import Image as _PILImage
            if os.path.exists(LOGO_PNG):
                logo_img = ctk.CTkImage(_PILImage.open(LOGO_PNG), size=(28, 28))
        except Exception:
            logo_img = None
        if logo_img is not None:
            self._logo_ref = logo_img   # evita garbage collection da imagem
            logo_w = ctk.CTkLabel(left, image=logo_img, text="")
        else:
            logo_w = ctk.CTkLabel(left, text="🗂", width=32, height=32,
                                  fg_color=ACCENT_DK, corner_radius=8,
                                  font=F(14))
        logo_w.pack(side="left", padx=(0, 10))
        nome_w = ctk.CTkLabel(left, text=APP_NAME, text_color=FG_MAIN,
                              font=F(15, True))
        nome_w.pack(side="left")
        # clicar no logo ou no nome volta ao início, como em qualquer site
        for w in (logo_w, nome_w):
            w.configure(cursor="hand2")
            w.bind("<Button-1>", lambda e: self.show_home())
        Tooltip(nome_w, "Voltar ao início")
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
        # o watcher é uma engrenagem do Trello: some para quem não usa
        self._watcher_chip = hbtn("○ watcher", self.open_watcher, width=90)
        if self.usa("trello"):
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

    def aplica_preferencias(self):
        """Reflete no cabeçalho quem usa Trello ou não (o assistente e as
        configurações mudam isso depois da janela já montada)."""
        try:
            if self.usa("trello"):
                if not self._watcher_chip.winfo_ismapped():
                    self._watcher_chip.pack(side="right", padx=2)
            else:
                if self.watcher_active:
                    self._stop_watcher()
                self._watcher_chip.pack_forget()
        except Exception:
            pass

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
        """Excluir grupo: por padrão só tira do app; opcionalmente apaga a
        pasta base de verdade (para a Lixeira), com alerta e confirmação
        digitando o nome do grupo."""
        win = ctk.CTkToplevel(self, fg_color=BG_MAIN)
        win.title("Excluir grupo")
        win.geometry("520x470")
        win.resizable(False, False)
        win.grab_set()

        box = ctk.CTkFrame(win, fg_color="transparent")
        box.pack(fill="both", expand=True, padx=22, pady=18)
        ctk.CTkLabel(box, text=f"Excluir o grupo “{g['name']}”",
                     text_color=FG_MAIN, font=F(17, True)).pack(anchor="w")

        modo = tk.StringVar(value="app")
        base = g.get("base_path", "")
        motivo_bloqueio = pasta_protegida(base)
        outros = [x["name"] for x in self.groups()
                  if x is not g and x.get("base_path") and base and
                  os.path.normcase(os.path.normpath(x["base_path"])) ==
                  os.path.normcase(os.path.normpath(base))]

        def opcao(valor, titulo, sub, cor_borda=BORDER):
            f = ctk.CTkFrame(box, fg_color=BG_NODE, corner_radius=10,
                             border_width=1, border_color=cor_borda)
            f.pack(fill="x", pady=(10, 0))
            rb = ctk.CTkRadioButton(f, text=titulo, variable=modo, value=valor,
                                    text_color=FG_MAIN, font=F(12, True),
                                    fg_color=ACCENT, hover_color=ACCENT_H,
                                    command=lambda: _atualiza())
            rb.pack(anchor="w", padx=12, pady=(10, 0))
            ctk.CTkLabel(f, text=sub, text_color=FG_LABEL, font=F(11),
                         justify="left", wraplength=400, anchor="w"
                         ).pack(anchor="w", padx=38, pady=(0, 10))
            return rb

        opcao("app", "Remover só do FolderFlow",
              "As pastas continuam no disco, do jeito que estão. "
              "Dá para criar o grupo de novo depois apontando para a mesma pasta.")
        rb_disco = opcao("disco", "Remover e apagar a pasta base",
                         f"Manda para a Lixeira a pasta inteira:\n{base or '(sem pasta base)'}",
                         cor_borda="#5a1f24")

        alerta = ctk.CTkFrame(box, fg_color="#2a1215", corner_radius=10,
                              border_width=1, border_color=RED)
        alerta_lbl = ctk.CTkLabel(alerta, text="", text_color="#ffb3b8",
                                  font=F(11), justify="left", wraplength=440,
                                  anchor="w")
        alerta_lbl.pack(anchor="w", padx=12, pady=(10, 6))
        confirma_var = tk.StringVar()
        ent = ctk.CTkEntry(alerta, textvariable=confirma_var, height=30,
                           placeholder_text=f"digite: {g['name']}",
                           fg_color=BG_INPUT, border_color=RED,
                           text_color=FG_MAIN, font=F(12))
        ent.pack(fill="x", padx=12, pady=(0, 12))

        if motivo_bloqueio or not base or not os.path.isdir(base):
            rb_disco.configure(state="disabled")
            aviso = motivo_bloqueio or "a pasta base não existe"
            ctk.CTkLabel(box, text=f"Apagar a pasta não está disponível: {aviso}.",
                         text_color=FG_DIM, font=F(10)).pack(anchor="w",
                                                             pady=(4, 0))

        rodape = ctk.CTkFrame(win, fg_color="transparent")
        rodape.pack(side="bottom", fill="x", padx=22, pady=(0, 18))
        btn_ok = ctk.CTkButton(rodape, text="Remover do FolderFlow", height=38,
                               width=200, corner_radius=10, fg_color=ACCENT,
                               hover_color=ACCENT_H, text_color=DARK_TXT,
                               font=F(12, True))
        btn_ok.pack(side="right")
        ctk.CTkButton(rodape, text="Cancelar", height=38, width=100,
                      corner_radius=10, fg_color="transparent", border_width=1,
                      border_color=BORDER, hover_color=BG_HOVER,
                      text_color=FG_LABEL, font=F(12),
                      command=win.destroy).pack(side="right", padx=(0, 8))

        medida = {"txt": "calculando o tamanho…"}

        def _atualiza(*_a):
            if modo.get() == "disco":
                alerta.pack(fill="x", pady=(12, 0))
                partes = [f"⚠ ATENÇÃO: a pasta e TUDO dentro dela vão para a "
                          f"Lixeira ({medida['txt']})."]
                if outros:
                    partes.append("Esta pasta também é usada pelo(s) grupo(s): "
                                  + ", ".join(outros) + ".")
                partes.append(f"Para confirmar, digite o nome do grupo: "
                              f"{g['name']}")
                alerta_lbl.configure(text="\n".join(partes))
                libera = confirma_var.get().strip() == g["name"].strip()
                btn_ok.configure(text="Apagar pasta e remover",
                                 fg_color=RED if libera else "#5a1f24",
                                 hover_color="#ff6b76", text_color=FG_MAIN,
                                 state="normal" if libera else "disabled")
            else:
                alerta.pack_forget()
                btn_ok.configure(text="Remover do FolderFlow", fg_color=ACCENT,
                                 hover_color=ACCENT_H, text_color=DARK_TXT,
                                 state="normal")
        confirma_var.trace_add("write", _atualiza)

        def _medir():
            def conta():
                n, tam = 0, 0
                for root, dirs, files in os.walk(base):
                    n += len(dirs) + len(files)
                    for f in files:
                        try:
                            tam += os.path.getsize(os.path.join(root, f))
                        except OSError:
                            pass
                return n, tam

            def pronto(r):
                if isinstance(r, tuple) and win.winfo_exists():
                    medida["txt"] = f"{r[0]} itens, {fmt_tamanho(r[1])}"
                    _atualiza()
            self.em_segundo_plano(conta, pronto)
        if base and os.path.isdir(base) and not motivo_bloqueio:
            _medir()

        def _confirmar():
            if modo.get() == "disco":
                if confirma_var.get().strip() != g["name"].strip():
                    return
                n_ok, erros = mandar_para_lixeira([base])
                if erros:
                    messagebox.showerror("Excluir", "Não consegui apagar a pasta:\n"
                                         + "\n".join(erros), parent=win)
                    return
            if g in self.config_data["groups"]:
                self.config_data["groups"].remove(g)
            self.save()
            win.destroy()
            self.show_home()
        btn_ok.configure(command=_confirmar)
        _atualiza()
        return win

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
        # só mexe no OneDrive se a pasta realmente estiver dentro de um
        pause = (self.config_data.get("pause_onedrive", True)
                 and path_no_onedrive(base) is not None)
        extra = "\n\nO OneDrive será pausado durante a criação." if pause else ""
        if not messagebox.askyesno(
                "⚡ Criar agora",
                f"Grupo: {g['name']}\nDestino: {base}\n\n"
                f"Criar {st['folders']} pasta(s) e {st['files']} arquivo(s)?\n"
                f"({st['skipped']} itens já existem e serão pulados)" + extra):
            return

        def tarefa():
            if pause:
                pause_onedrive()
            try:
                return execute_template(nodes, base, vars_, dry=False)
            finally:
                if pause:
                    resume_onedrive()

        def pronto(r):
            if isinstance(r, dict) and "erro" in r:
                messagebox.showerror("Erro", r["erro"])
                return
            self._concluido(f"✓ {r['folders']} pasta(s) e {r['files']} "
                            f"arquivo(s) criados em:\n{base}", base)
        self.em_segundo_plano(tarefa, pronto)

    def dialog_renomear_massa(self, dir_pai, nomes, depois=None, escopo=None,
                              provisorios=None):
        """Renomear vários de uma vez, com prévia antes/depois.
        Clicar numa linha da prévia inclui ou tira aquele item."""
        win = ctk.CTkToplevel(self, fg_color=BG_MAIN)
        win.title("Renomear em massa")
        win.geometry("740x680")
        win.grab_set()

        topo = ctk.CTkFrame(win, fg_color="transparent")
        topo.pack(fill="x", padx=18, pady=(16, 4))
        ctk.CTkLabel(topo, text="Renomear em massa", text_color=FG_MAIN,
                     font=F(18, True)).pack(anchor="w")
        ctk.CTkLabel(topo, text=escopo or f"{len(nomes)} item(ns) em {dir_pai}",
                     text_color=FG_LABEL if escopo else FG_DIM, font=F(11),
                     wraplength=680, justify="left").pack(anchor="w")
        if escopo:
            ctk.CTkLabel(topo, text=dir_pai, text_color=FG_DIM, font=F(10),
                         wraplength=680, justify="left").pack(anchor="w")
        excluidos = set()
        provisorios = provisorios or PROVISORIOS_PADRAO

        OPS = [("Localizar e substituir", "substituir"),
               ("Adicionar/remover prefixo ou sufixo", "afixo"),
               ("Renumerar em sequência", "renumerar"),
               ("Trocar só o nome do cliente", "cliente")]
        op_var = tk.StringVar(value=OPS[0][0])
        ctk.CTkOptionMenu(win, variable=op_var, values=[o[0] for o in OPS],
                          height=32, fg_color=BG_INPUT, button_color=BG_HOVER,
                          text_color=FG_MAIN, font=F(12),
                          dropdown_fg_color=BG_CARD,
                          command=lambda _v: _troca_op()
                          ).pack(fill="x", padx=18, pady=(8, 8))

        campos = ctk.CTkFrame(win, fg_color=BG_CARD, corner_radius=10)
        campos.pack(fill="x", padx=18)

        v = {k: tk.StringVar() for k in
             ("de", "para", "prefixo", "sufixo", "rem_pre", "rem_suf",
              "inicio", "padrao", "cliente")}
        v["inicio"].set("1")
        v["padrao"].set("{seq} - {nome}")
        fmt_var = tk.StringVar(value=SEQ_FORMATS[1][0])
        caso_var = tk.BooleanVar(value=True)

        def campo(rot, var, dica=""):
            f = ctk.CTkFrame(campos, fg_color="transparent")
            ctk.CTkLabel(f, text=rot, text_color=FG_LABEL, font=F(11),
                         width=190, anchor="w").pack(side="left")
            e = ctk.CTkEntry(f, textvariable=var, fg_color=BG_INPUT,
                             border_color=BORDER, text_color=FG_MAIN,
                             font=F(12), height=30)
            e.pack(side="left", fill="x", expand=True)
            var.trace_add("write", lambda *_: _atualiza())
            if dica:
                Tooltip(e, dica)
            return f

        f_de      = campo("Localizar:", v["de"])
        f_para    = campo("Substituir por:", v["para"])
        f_caso    = ctk.CTkFrame(campos, fg_color="transparent")
        make_switch(f_caso, text="Ignorar maiúsculas/minúsculas",
                    variable=caso_var, command=lambda: _atualiza(),
                    progress_color=ACCENT, text_color=FG_LABEL,
                    font=F(11)).pack(side="left", padx=(190, 0))
        f_pre     = campo("Adicionar no início:", v["prefixo"])
        f_suf     = campo("Adicionar no fim:", v["sufixo"])
        f_rpre    = campo("Remover do início:", v["rem_pre"])
        f_rsuf    = campo("Remover do fim:", v["rem_suf"])
        f_ini     = campo("Começar em:", v["inicio"])
        f_pad     = campo("Padrão do nome:", v["padrao"],
                          "{seq} vira o número e {nome} o nome atual.\n"
                          "Ex.: '{seq} - {nome}' ou 'Pasta {seq}'")
        f_fmt = ctk.CTkFrame(campos, fg_color="transparent")
        ctk.CTkLabel(f_fmt, text="Formato do número:", text_color=FG_LABEL,
                     font=F(11), width=190, anchor="w").pack(side="left")
        ctk.CTkOptionMenu(f_fmt, variable=fmt_var,
                          values=[r for r, _ in SEQ_FORMATS], height=30,
                          fg_color=BG_INPUT, button_color=BG_HOVER,
                          text_color=FG_MAIN, font=F(12),
                          dropdown_fg_color=BG_CARD,
                          command=lambda _v: _atualiza()).pack(side="left")
        f_cli     = campo("Novo nome do cliente:", v["cliente"],
                          "O código antes do ' - ' é preservado.")

        POR_OP = {
            "substituir": [f_de, f_para, f_caso],
            "afixo":      [f_pre, f_suf, f_rpre, f_rsuf],
            "renumerar":  [f_ini, f_fmt, f_pad],
            "cliente":    [f_cli],
        }

        # rodapé e resumo ancorados embaixo ANTES da prévia, senão a caixa
        # expansível os empurra para fora da janela
        rodape = ctk.CTkFrame(win, fg_color="transparent")
        rodape.pack(side="bottom", fill="x", padx=18, pady=14)
        resumo = ctk.CTkLabel(win, text="", text_color=FG_LABEL, font=F(11))
        resumo.pack(side="bottom", anchor="w", padx=18)

        cab_prev = ctk.CTkFrame(win, fg_color="transparent")
        cab_prev.pack(fill="x", padx=18, pady=(12, 2))
        ctk.CTkLabel(cab_prev, text="PRÉVIA", text_color=FG_LABEL,
                     font=F(11, True)).pack(side="left")
        ctk.CTkLabel(cab_prev, text="  clique numa linha para incluir ou tirar",
                     text_color=FG_DIM, font=F(10)).pack(side="left")

        def _marca(modo):
            excluidos.clear()
            if modo == "nenhum":
                excluidos.update(range(len(nomes)))
            elif modo == "prov":
                for i, n in enumerate(nomes):
                    cli = n.split(" - ", 1)[1] if " - " in n else n
                    if not _eh_provisorio(cli, provisorios):
                        excluidos.add(i)
            _atualiza()

        for rot, modo, dica in (
                ("Só os provisórios", "prov",
                 f"Mantém marcados só os que ainda se chamam "
                 f"'{provisorios[0]}'"),
                ("Nenhum", "nenhum", "Desmarca todos"),
                ("Todos", "todos", "Marca todos")):
            b = ctk.CTkButton(cab_prev, text=rot, height=22, width=10,
                              corner_radius=6, fg_color="transparent",
                              border_width=1, border_color=BORDER,
                              hover_color=BG_HOVER, text_color=FG_LABEL,
                              font=F(10), command=lambda m=modo: _marca(m))
            b.pack(side="right", padx=(4, 0))
            Tooltip(b, dica)

        prev_box = ctk.CTkFrame(win, fg_color=BG_PANEL, corner_radius=10,
                                border_width=1, border_color=BORDER_S)
        prev_box.pack(fill="both", expand=True, padx=18)
        txt = tk.Text(prev_box, bg=BG_PANEL, fg=FG_MAIN, bd=0, wrap="none",
                      highlightthickness=0, font=("Consolas", 10),
                      state="disabled", cursor="hand2")

        def _clique_linha(ev):
            linha = int(txt.index(f"@{ev.x},{ev.y}").split(".")[0]) - 1
            if 0 <= linha < len(nomes):
                if linha in excluidos:
                    excluidos.discard(linha)
                else:
                    excluidos.add(linha)
                _atualiza()
            return "break"
        txt.bind("<Button-1>", _clique_linha)
        sb = ctk.CTkScrollbar(prev_box, command=txt.yview)
        sb.pack(side="right", fill="y", pady=6)
        txt.pack(side="left", fill="both", expand=True, padx=10, pady=6)
        txt.configure(yscrollcommand=sb.set)
        txt.tag_configure("igual", foreground=FG_DIM)
        txt.tag_configure("novo", foreground=ACCENT)
        txt.tag_configure("erro", foreground=RED)
        txt.tag_configure("seta", foreground=FG_DIM)

        pares_atuais = [[]]

        def _op():
            return dict(OPS)[op_var.get()]

        def _kwargs():
            o = _op()
            if o == "substituir":
                return {"de": v["de"].get(), "para": v["para"].get(),
                        "ignorar_caso": caso_var.get()}
            if o == "afixo":
                return {"prefixo": v["prefixo"].get(),
                        "sufixo": v["sufixo"].get(),
                        "remover_prefixo": v["rem_pre"].get(),
                        "remover_sufixo": v["rem_suf"].get()}
            if o == "renumerar":
                try:
                    ini = int(v["inicio"].get() or 1)
                except ValueError:
                    ini = 1
                return {"formato": dict(SEQ_FORMATS)[fmt_var.get()],
                        "inicio": ini, "padrao": v["padrao"].get()}
            return {"novo": v["cliente"].get()}

        def _atualiza(*_a):
            pares = preview_rename(nomes, _op(), manter=excluidos, **_kwargs())
            pares_atuais[0] = pares
            try:
                ypos = txt.yview()[0]
            except Exception:
                ypos = 0.0
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            larg = max((len(a) for a, _n, _p in pares), default=10)
            larg = min(larg, 44)
            n_mud = n_prob = 0
            for i, (antigo, novo, prob) in enumerate(pares):
                fora = i in excluidos
                txt.insert("end", "☐ " if fora else "☑ ",
                           "igual" if fora else "novo")
                a_txt = (antigo[:larg - 1] + "…") if len(antigo) > larg else antigo
                txt.insert("end", a_txt.ljust(larg + 2),
                           "erro" if prob else "igual")
                txt.insert("end", "→  ", "seta")
                if fora:
                    txt.insert("end", "(fica como está)\n", "igual")
                elif prob:
                    txt.insert("end", f"{novo}   ⚠ {prob}\n", "erro")
                    n_prob += 1
                elif novo == antigo:
                    txt.insert("end", "(sem mudança)\n", "igual")
                else:
                    txt.insert("end", novo + "\n", "novo")
                    n_mud += 1
            txt.configure(state="disabled")
            txt.yview_moveto(ypos)
            partes = [f"{n_mud} serão renomeados"]
            if excluidos:
                partes.append(f"{len(excluidos)} desmarcado(s)")
            if n_prob:
                partes.append(f"{n_prob} com problema (serão pulados)")
            resumo.configure(
                text=" · ".join(partes),
                text_color=YELLOW if n_prob else (ACCENT if n_mud else FG_DIM))
            btn_ok.configure(state="normal" if n_mud else "disabled")

        def _troca_op():
            for fs in POR_OP.values():
                for f in fs:
                    f.pack_forget()
            for f in POR_OP[_op()]:
                f.pack(fill="x", padx=12, pady=4)
            _atualiza()

        def _aplicar():
            feitos, erros = aplicar_rename(dir_pai, pares_atuais[0])
            win.destroy()
            if depois:
                depois()
            if erros:
                messagebox.showwarning(
                    "Renomear",
                    f"{feitos} item(ns) renomeado(s).\n\nProblemas:\n" +
                    "\n".join(erros[:8]))
            else:
                messagebox.showinfo("Renomear",
                                    f"✓ {feitos} item(ns) renomeado(s).")

        ctk.CTkButton(rodape, text="Cancelar", height=36, width=110,
                      corner_radius=8, fg_color="transparent", border_width=1,
                      border_color=BORDER, hover_color=BG_HOVER,
                      text_color=FG_LABEL, font=F(12),
                      command=win.destroy).pack(side="right", padx=(8, 0))
        btn_ok = ctk.CTkButton(rodape, text="Renomear", height=36, width=140,
                               corner_radius=8, fg_color=ACCENT,
                               hover_color=ACCENT_H, text_color=DARK_TXT,
                               font=F(12, True), command=_aplicar)
        btn_ok.pack(side="right")

        _troca_op()
        return win

    def _concluido(self, msg, pasta):
        """Avisa que terminou e oferece abrir a pasta ONDE foi criado."""
        if messagebox.askyesno("Concluído", msg + "\n\nAbrir a pasta agora?"):
            try:
                abrir_no_explorer(pasta, mesma_janela=False)
            except Exception as e:
                messagebox.showerror("Erro ao abrir", str(e))

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

        self._build_group_tabs(wrap, g)

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

        # um único botão que alterna entre expandir e recolher tudo
        btn_colapso = IconeRecolher(vis_tools, bg=BG_CARD)
        btn_colapso.pack(side="left", padx=1)
        dica_colapso = Tooltip(btn_colapso, "Recolher tudo")

        def _atualiza_botao_recolher():
            tudo = tree.all_expanded()
            btn_colapso.set_modo(recolher=tudo)
            dica_colapso.text = "Recolher tudo" if tudo else "Expandir tudo"

        def _alterna_colapso():
            tree.set_all_expanded(not tree.all_expanded())
            _atualiza_botao_recolher()

        btn_colapso.command = _alterna_colapso

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

        # ═══ ESQUERDA — CONSTRUTOR VISUAL (árvore estilo IDE) ═══
        vis_container = ctk.CTkFrame(left, fg_color=BG_PANEL, corner_radius=12,
                                     border_width=1, border_color=BORDER_S)

        acoes = ctk.CTkFrame(vis_container, fg_color="transparent")
        acoes.pack(fill="x", padx=8, pady=(8, 4))

        tree = TreeCanvas(vis_container)
        tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        def _find_parent_list(alvo):
            """Lista que contém este nó (comparando por identidade)."""
            if any(n is alvo for n in state_nodes):
                return state_nodes
            for n in _iter_nodes(state_nodes):
                if any(c is alvo for c in n["children"]):
                    return n["children"]
            return state_nodes

        def _destino_para_novos():
            """Onde adicionar: dentro da pasta selecionada, ou na raiz."""
            r = tree.selected_row()
            if r is not None and r.kind == "folder":
                return r.payload["children"]
            if r is not None:
                return _find_parent_list(r.payload)
            return state_nodes

        def _sel_node():
            r = tree.selected_row()
            return r.payload if r is not None else None

        def _acao(nome):
            n = _sel_node()
            if nome == "folder":
                _add_node(_destino_para_novos(), "folder")
            elif nome == "file":
                _add_node(_destino_para_novos(), "file")
            elif nome == "seq":
                _seq_popover(add_to=_destino_para_novos())
            elif nome == "anexo":
                _add_copy(_destino_para_novos())
            elif nome == "rename":
                tree.begin_edit()
            elif nome == "delete" and n is not None:
                _del_node(n, _find_parent_list(n))
            elif nome == "duplicate" and n is not None:
                lista = _find_parent_list(n)
                copia = json.loads(json.dumps(
                    {k: v for k, v in n.items() if not k.startswith("_")}))
                lista.insert(lista.index(n) + 1
                             if n in lista else len(lista), copia)
                _sync_visual()
                _schedule_refresh()
            elif nome == "badge" and n is not None and n["type"] == "folder":
                _seq_popover(node=n)
            elif nome == "content" and n is not None and n["type"] == "file":
                _content_popover(n)
            elif nome == "src" and n is not None and n["type"] == "copy":
                _change_copy_src(n)

        def abtn(texto, acao, dica, largura=92):
            b = ctk.CTkButton(acoes, text=texto, width=largura, height=28,
                              corner_radius=8, fg_color=BG_INPUT,
                              hover_color=BG_HOVER, text_color=FG_LABEL,
                              font=F(11), command=lambda: _acao(acao))
            b.pack(side="left", padx=(0, 6))
            Tooltip(b, dica)
            return b

        abtn("📁 Pasta", "folder", "Nova pasta dentro do item selecionado\n"
                                   "(ou na raiz, se nada estiver selecionado)", 78)
        abtn("📄 Arquivo", "file",
             "Novo arquivo de texto dentro do selecionado", 86)
        abtn("🔁 Sequência", "seq", "Várias pastas numeradas de uma vez\n"
                                    "(ex.: Pasta 0001 … Pasta 0200)", 98)
        abtn("📎 Anexo", "anexo", "Copiar um arquivo real (ex.: PDF gabarito)\n"
                                  "para dentro do que for criado", 78)
        btn_ren = abtn("✎", "rename", "Renomear o item selecionado (F2)", 32)
        btn_del = abtn("🗑", "delete", "Excluir o item selecionado (Del)", 32)
        btn_del.configure(text_color=RED)

        def _on_sel(rows):
            tem = bool(rows)
            for b in (btn_ren, btn_del):
                b.configure(state="normal" if tem else "disabled")
        tree.on_select = _on_sel
        _on_sel([])

        def _on_rename(row, novo):
            n = row.payload
            token = _SEQ_RE.search(n["name"])
            tok = token.group(0) if (token and n.get("repeat")) else ""
            n["name"] = (novo.rstrip() + (" " + tok if tok else "")).strip() or novo
            _sync_visual()
            _schedule_refresh()
        tree.on_rename = _on_rename

        def _on_context(row, sel):
            if row is None:
                return [
                    ("＋ Nova pasta na raiz",
                     lambda: _add_node(state_nodes, "folder"), True),
                    ("＋ Novo arquivo na raiz",
                     lambda: _add_node(state_nodes, "file"), True),
                    ("🔁 Nova sequência na raiz",
                     lambda: _seq_popover(add_to=state_nodes), True),
                    ("📎 Anexar arquivo na raiz",
                     lambda: _add_copy(state_nodes), True),
                ]
            n = row.payload
            é_pasta = n["type"] == "folder"
            itens = [
                ("✎  Renomear                    F2",
                 lambda: tree.begin_edit(), True),
                ("⧉  Duplicar                   Ctrl+D",
                 lambda: _acao("duplicate"), True),
            ]
            if é_pasta:
                itens += [
                    None,
                    ("＋ 📁  Nova pasta dentro",
                     lambda: _add_node(n["children"], "folder"), True),
                    ("＋ 📄  Novo arquivo dentro",
                     lambda: _add_node(n["children"], "file"), True),
                    ("📎  Anexar arquivo dentro",
                     lambda: _add_copy(n["children"]), True),
                    (("🔁  Editar sequência" if n.get("repeat")
                      else "🔁  Transformar em sequência"),
                     lambda: _seq_popover(node=n), True),
                ]
            elif n["type"] == "file":
                itens += [None, ("✎  Editar conteúdo do arquivo",
                                 lambda: _content_popover(n), True)]
            elif n["type"] == "copy":
                itens += [None, ("📂  Trocar arquivo de origem",
                                 lambda: _change_copy_src(n), True)]
            itens += [
                None,
                ("🗑  Excluir                      Del",
                 lambda: _acao("delete"), True),
                None,
                ("Expandir tudo", lambda: tree.set_all_expanded(True), True),
                ("Recolher tudo", lambda: tree.set_all_expanded(False), True),
            ]
            return itens
        tree.on_context = _on_context

        def _on_action(row, acao_id):
            tree.select_key(row.key, notify=False)
            _acao({"delete": "delete", "duplicate": "duplicate",
                   "badge": "badge"}.get(acao_id, acao_id))
        tree.on_action = _on_action

        def _on_activate(row):
            n = row.payload
            if n["type"] == "file":
                _content_popover(n)
            elif n["type"] == "copy":
                _change_copy_src(n)
        tree.on_activate = _on_activate

        _prov = TemplateTreeProvider(state_nodes)

        def _sync_visual():
            """Nome mantido: os ~10 pontos que chamavam isso não mudaram."""
            _prov.nodes = state_nodes
            tree.set_provider(_prov) if tree.provider is not _prov else tree.reload()
            _atualiza_botao_recolher()

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

        # o switch do OneDrive só existe se a pasta base estiver mesmo num
        # OneDrive — antes o app derrubava o OneDrive de quem nem usa
        od_root = (path_no_onedrive(g.get("base_path", ""))
                   if self.usa("onedrive") else None)
        pause_var = tk.BooleanVar(
            value=self.config_data.get("pause_onedrive", True) and bool(od_root))
        if od_root:
            sw1 = make_switch(opt_row, text="Pausar OneDrive", variable=pause_var,
                              progress_color=ACCENT, text_color=FG_LABEL,
                              font=F(11))
            sw1.pack(side="left", padx=(0, 16))
            Tooltip(sw1, "Esta pasta fica dentro do OneDrive:\n"
                         f"{od_root}\n\n"
                         "Fecha o OneDrive durante a criação e reabre no fim,\n"
                         "evitando travamentos ao criar muitas pastas.")
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


        ctk.CTkLabel(head, text="PRÉVIA", text_color=FG_LABEL,
                     font=F(11, True)).pack(side="left")
        count_lbl = ctk.CTkLabel(head, text="", text_color=FG_LABEL, font=F(11))
        count_lbl.pack(side="left", padx=(12, 0))
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
        prev.tag_configure("marca", foreground=FG_DIM)
        # configurada DEPOIS de folder/file para vencer na ordem de empilhamento
        prev.tag_configure("existe", foreground=FG_DIM)
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

            # cada linha reserva 2 caracteres de margem para o marcador "✓"
            pendentes = []          # (nº da linha, pasta, nome) a conferir
            linha = [1]

            def emit(depth, texto, tag, alvo=None, nome=None):
                prev.insert("end", "  ", ("marca",))
                if depth:
                    prev.insert("end", "│  " * depth, ("guide",))
                prev.insert("end", texto + "\n", (tag,))
                if alvo and nome:
                    pendentes.append((linha[0], alvo, nome))
                linha[0] += 1

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
                            # com "continuar numeração", _seq_start já pulou o
                            # que existe: por construção estes são todos novos
                            checar = dest if not seq_var.get() else ""
                            emit(depth, icon + name, tag, checar, name)
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
                        emit(depth, icon + name, tag, dest, name)
                        add(n["children"], vars2,
                            os.path.join(dest, name) if dest else "", depth + 1)

            add(nodes, dict(vars_), base if base_ok else "", 0)
            prev.configure(state="disabled")
            try:
                prev.yview_moveto(ypos)
            except Exception:
                pass
            if base_ok and pendentes:
                _marca_existentes(pendentes)

        _marca_gen = [0]
        _marca_fila = queue.Queue()

        def _marca_existentes(pendentes):
            """Marca com ✓ o que já existe no disco. Faz UMA leitura por pasta
            (não uma por linha) e fora da thread da interface, senão a prévia
            engasgaria numa pasta do OneDrive. A thread só entrega na fila —
            quem mexe no widget é sempre a thread principal."""
            _marca_gen[0] += 1
            gen = _marca_gen[0]

            def tarefa():
                cache, achados = {}, []
                for ln, pasta, nome in pendentes:
                    chave = os.path.normcase(pasta)
                    if chave not in cache:
                        try:
                            cache[chave] = {e.name.lower()
                                            for e in os.scandir(pasta)}
                        except OSError:
                            cache[chave] = set()
                    if nome.lower() in cache[chave]:
                        achados.append(ln)
                _marca_fila.put((gen, achados))

            threading.Thread(target=tarefa, daemon=True).start()
            self.after(50, _drena_marcas)

        def _drena_marcas():
            achados = None
            gen = None
            while True:
                try:
                    gen, achados = _marca_fila.get_nowait()
                except queue.Empty:
                    break
            if achados is None:
                self.after(60, _drena_marcas)      # ainda lendo
                return
            if gen != _marca_gen[0] or not prev.winfo_exists():
                return
            prev.configure(state="normal")
            for ln in achados:
                try:
                    prev.replace(f"{ln}.0", f"{ln}.2", "✓ ", ("existe",))
                    prev.tag_add("existe", f"{ln}.2", f"{ln}.end")
                except Exception:
                    pass
            prev.configure(state="disabled")

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
                txt = (f"📁 {st['folders']} pastas · 📄 {st['files']} arquivos"
                       " novos")
                if st["skipped"]:
                    txt += f" · ✓ {st['skipped']} já existem"
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
            aviso = ""
            # avisa quando a numeração vai recomeçar do 1 (pedido do usuário)
            if not seq_var.get() and any(
                    _SEQ_RE.search(n["name"]) for n in _iter_nodes(nodes)):
                aviso = ("\n\n⚠ 'Continuar numeração' está DESLIGADA:\n"
                         "a contagem recomeça do 1 e o que já existir com esse\n"
                         "nome será pulado, não sobrescrito.")
            if pause_var.get():
                aviso += "\n\nO OneDrive será pausado durante a criação."
            if not messagebox.askyesno(
                    "Confirmar criação",
                    f"Destino: {base}\n\n"
                    f"Criar {st['folders']} pasta(s) e {st['files']} arquivo(s)?\n"
                    f"({st['skipped']} itens já existem e serão pulados)" + aviso):
                return
            btn_criar.configure(state="disabled", text="Criando...")
            pausar = pause_var.get()
            if pausar:
                log_lbl.configure(text="Pausando OneDrive...", text_color=FG_DIM)
            continuar = seq_var.get()

            def tarefa():
                if pausar:
                    pause_onedrive()
                try:
                    return execute_template(nodes, base, vars_, dry=False,
                                            continue_seq=continuar)
                finally:
                    if pausar:
                        resume_onedrive()

            def pronto(r):
                if btn_criar.winfo_exists():
                    btn_criar.configure(state="normal", text="✚  Criar estrutura")
                if isinstance(r, dict) and "erro" in r:
                    if log_lbl.winfo_exists():
                        log_lbl.configure(text=f"✗ ERRO: {r['erro']}",
                                          text_color=RED)
                    return
                txt = (f"✓ Criado: {r['folders']} pasta(s), "
                       f"{r['files']} arquivo(s).")
                if r["skipped"]:
                    txt += f" Pulados: {r['skipped']}."
                if log_lbl.winfo_exists():
                    log_lbl.configure(text=txt, text_color=GREEN)
                    _schedule_refresh()
                self._concluido(txt, base)

            self.em_segundo_plano(tarefa, pronto)

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
            # o modelo é pequeno: abrir expandido mostra a estrutura de cara
            tree.set_all_expanded(True)
            _atualiza_botao_recolher()
            vis_tools.pack(side="left", padx=(8, 0))
            vis_container.pack(fill="both", expand=True, pady=(8, 0))
        else:
            seg.set("⌨ Texto")
            text_container.pack(fill="both", expand=True, pady=(8, 0))
        _refresh()

    # ── Grupo tipo "marketplace" ─────────────────────────────────────────────
    # ═════════════════════════════════════════════════════════════════════════
    # TELA DO GRUPO — as mesmas abas para todo grupo
    # ═════════════════════════════════════════════════════════════════════════
    ABA_PASTAS, ABA_MODELO, ABA_CRIAR = "  Pastas  ", "  Modelo  ", "  Criar  "
    ABA_REN, ABA_CONF, ABA_REL = "  Renomear  ", "  Conferir  ", "  Relatório  "

    def _build_group_tabs(self, wrap, g):
        cor = g.get("color", ACCENT)
        tabs = ctk.CTkTabview(wrap, fg_color=BG_CARD, corner_radius=14,
                              segmented_button_fg_color=BG_INPUT,
                              segmented_button_selected_color=darker(cor, 0.45),
                              segmented_button_selected_hover_color=darker(cor, 0.35),
                              segmented_button_unselected_color=BG_INPUT,
                              segmented_button_unselected_hover_color=BG_HOVER,
                              text_color=FG_MAIN)
        tabs.pack(fill="both", expand=True)
        mp = g["kind"] == "marketplace"
        construtores = [
            (self.ABA_PASTAS, lambda t: self._aba_pastas(t, g)),
            ((self.ABA_CRIAR if mp else self.ABA_MODELO),
             (lambda t: self._mp_tab_criar(t, g, cor)) if mp else
             (lambda t: self._build_template_view(
                 ctk.CTkFrame(t, fg_color="transparent"), g))),
            (self.ABA_REN, lambda t: self._mp_tab_renomear(t, g, cor)),
            (self.ABA_CONF, lambda t: self._mp_tab_conferir(t, g, cor)),
            (self.ABA_REL, lambda t: self._mp_tab_relatorio(t, g, cor)),
        ]
        feitos = set()
        mapa = dict(construtores)

        def _garante(nome):
            # cada aba só é montada na primeira vez que é aberta:
            # a tela do grupo abre rápido mesmo com cinco abas
            if nome in feitos or nome not in mapa:
                return
            feitos.add(nome)
            aba = tabs.tab(nome)
            mapa[nome](aba)
            for w in aba.winfo_children():
                if not w.winfo_manager():
                    w.pack(fill="both", expand=True)

        for nome, _f in construtores:
            tabs.add(nome)
        orig_set = tabs.set

        def _set(nome):
            _garante(nome)
            orig_set(nome)
        tabs.set = _set
        tabs.configure(command=lambda: _garante(tabs.get()))
        inicial = self.ABA_PASTAS if g.get("base_path") else (
            self.ABA_CRIAR if mp else self.ABA_MODELO)
        tabs.set(inicial)
        self._tabs_grupo = tabs
        return tabs

    def _aba_pastas(self, tab, g):
        """Explorador das pastas reais do grupo, em largura total."""
        wrap = ctk.CTkFrame(tab, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=8, pady=4)
        base_g = g.get("base_path", "")
        if not base_g or not os.path.isdir(base_g):
            ctk.CTkLabel(wrap, text="Defina a pasta base do grupo (✎ Editar) para "
                                    "ver e organizar as pastas reais aqui.",
                         text_color=FG_DIM, font=F(12)).pack(pady=40)
            return

        barra = ctk.CTkFrame(wrap, fg_color="transparent")
        barra.pack(fill="x", pady=(0, 6))
        caixa = ctk.CTkFrame(wrap, fg_color=BG_PANEL, corner_radius=12,
                             border_width=1, border_color=BORDER_S)
        caixa.pack(fill="both", expand=True)
        disco = TreeCanvas(caixa, multi=True)
        disco.pack(fill="both", expand=True, padx=10, pady=10)
        status = ctk.CTkLabel(wrap, text="", text_color=FG_DIM, font=F(11),
                              anchor="w", justify="left")
        status.pack(fill="x", pady=(4, 0))
        prov = [None]

        def recarrega(_path=None):
            if disco.winfo_exists():
                disco.reload()
                _atualiza_icone()

        def monta():
            p = DiskTreeProvider(base_g, on_ready=recarrega, after=self.after)
            prov[0] = p
            disco.set_provider(p)
            disco.set_all_expanded(False)
            if disco.rows():
                disco.toggle(0)                # abre a pasta base

        def sel_paths():
            return [r.payload for r in disco.selection() if r.payload]

        def atualizar(*paths):
            if prov[0]:
                if paths:
                    for p in paths:
                        prov[0].invalidate(p)
                else:
                    prov[0].invalidate()
            recarrega()

        def pasta_alvo():
            sel = disco.selected_row()
            if sel is not None and sel.kind == "folder":
                return sel.payload
            if sel is not None and sel.payload:
                return os.path.dirname(sel.payload)
            return base_g

        def abrir():
            p = sel_paths()
            alvo = p[0] if p else base_g
            if alvo and os.path.exists(alvo):
                abrir_no_explorer(alvo if os.path.isdir(alvo)
                                  else os.path.dirname(alvo), mesma_janela=False)

        def excluir():
            paths = sel_paths()
            if not paths:
                return
            n_p = sum(1 for p in paths if os.path.isdir(p))
            partes = ([f"{n_p} pasta(s)"] if n_p else []) + \
                     ([f"{len(paths) - n_p} arquivo(s)"] if len(paths) - n_p else [])
            amostra = "\n".join("  • " + os.path.basename(p) for p in paths[:8])
            if len(paths) > 8:
                amostra += f"\n  … e mais {len(paths) - 8}"
            if not messagebox.askyesno(
                    "Excluir", f"Mandar {' e '.join(partes)} para a Lixeira?\n\n"
                               f"{amostra}\n\nDá para restaurar pela Lixeira do "
                               "Windows."):
                return
            ok_n, erros = mandar_para_lixeira(paths)
            atualizar(*{os.path.dirname(p) for p in paths})
            if erros:
                messagebox.showwarning("Excluir", f"{ok_n} item(ns) na Lixeira."
                                       "\n\nProblemas:\n" + "\n".join(erros[:6]))
            else:
                status.configure(text=f"✓ {ok_n} item(ns) na Lixeira.",
                                 text_color=GREEN)

        def renomear_um():
            if disco.selection():
                disco.begin_edit()

        def on_rename(row, novo):
            limpo = _sanitiza_nome(novo)
            if not limpo:
                messagebox.showerror("Renomear", "Nome inválido.")
                return
            antigo = row.payload
            alvo = os.path.join(os.path.dirname(antigo), limpo)
            if os.path.normcase(alvo) != os.path.normcase(antigo) \
                    and os.path.exists(alvo):
                messagebox.showerror("Renomear",
                                     f"Já existe algo chamado '{limpo}' aqui.")
                return
            try:
                os.rename(antigo, alvo)
            except OSError as e:
                messagebox.showerror("Renomear", str(e))
                return
            atualizar(os.path.dirname(antigo))
            status.configure(text=f"✓ Renomeado para '{limpo}'.",
                             text_color=GREEN)
        disco.on_rename = on_rename

        def nova(tipo):
            pai = pasta_alvo()
            if not pai or not os.path.isdir(pai):
                return
            nome = "Nova pasta" if tipo == "folder" else "novo arquivo.txt"
            destino, i = os.path.join(pai, nome), 2
            while os.path.exists(destino):
                destino = os.path.join(pai, f"Nova pasta ({i})" if tipo == "folder"
                                       else f"novo arquivo ({i}).txt")
                i += 1
            try:
                if tipo == "folder":
                    os.makedirs(destino)
                else:
                    open(destino, "w", encoding="utf-8").close()
            except OSError as e:
                messagebox.showerror("Criar", str(e))
                return
            disco._expanded.add(os.path.normcase(os.path.abspath(pai)))
            atualizar(pai)
            chave = os.path.normcase(os.path.abspath(destino))
            self.after(350, lambda: (disco.select_key(chave),
                                     disco.scroll_to(chave),
                                     disco.begin_edit()))

        def renomear_massa():
            rows = disco.selection()
            if not rows:
                messagebox.showinfo(
                    "Renomear em massa",
                    "Selecione uma pasta para renomear o que está DENTRO dela,\n"
                    "ou vários itens (Ctrl+clique / Shift) para renomear eles.")
                return
            provs = g.get("provisorios") or PROVISORIOS_PADRAO
            if len(rows) == 1 and rows[0].kind == "folder":
                pai = rows[0].payload
                try:
                    nomes = sorted((e.name for e in os.scandir(pai)),
                                   key=str.lower)
                except OSError as e:
                    messagebox.showerror("Renomear", str(e))
                    return
                if not nomes:
                    messagebox.showinfo("Renomear em massa",
                                        "Essa pasta está vazia.")
                    return
                self.dialog_renomear_massa(
                    pai, nomes, depois=lambda: atualizar(pai),
                    escopo=f"Renomeando o que está dentro de "
                           f"“{os.path.basename(pai)}” ({len(nomes)} itens)",
                    provisorios=provs)
                return
            pais = {os.path.dirname(r.payload) for r in rows}
            if len(pais) > 1:
                messagebox.showinfo(
                    "Renomear em massa",
                    "Selecione itens de uma pasta só — assim dá para conferir "
                    "os nomes antes de aplicar.")
                return
            pai = pais.pop()
            self.dialog_renomear_massa(
                pai, [os.path.basename(r.payload) for r in rows],
                depois=lambda: atualizar(pai),
                escopo=f"Renomeando {len(rows)} item(ns) selecionado(s)",
                provisorios=provs)

        def definir_base():
            r = disco.selected_row()
            if r is None or r.kind != "folder":
                return
            if messagebox.askyesno(
                    "Pasta base", f"Usar esta pasta como base do grupo "
                                  f"'{g['name']}'?\n\n{r.payload}"):
                g["base_path"] = os.path.normpath(r.payload)
                self.save()
                self.show_group(g)

        def copiar_caminho():
            p = sel_paths()
            if p:
                self.clipboard_clear()
                self.clipboard_append("\n".join(p))
                status.configure(text="✓ Caminho copiado.", text_color=GREEN)

        def dbtn(texto, cmd, dica, largura=34):
            b = ctk.CTkButton(barra, text=texto, width=largura, height=28,
                              corner_radius=8, fg_color=BG_INPUT,
                              hover_color=BG_HOVER, text_color=FG_LABEL,
                              font=F(11), command=cmd)
            b.pack(side="left", padx=(0, 5))
            Tooltip(b, dica)
            return b

        dbtn("📁 Nova pasta", lambda: nova("folder"), "Nova pasta (Ctrl+N)", 104)
        dbtn("📄 Arquivo", lambda: nova("file"), "Novo arquivo", 86)
        dbtn("✎", renomear_um, "Renomear o selecionado (F2)")
        dbtn("✎✎ Em massa", renomear_massa,
             "Uma pasta selecionada: renomeia o que está dentro dela.\n"
             "Vários itens selecionados: renomeia esses itens.", 104)
        dbtn("🗑", excluir, "Mandar para a Lixeira (Del)").configure(text_color=RED)
        dbtn("📂", abrir, "Abrir no Explorador")
        dbtn("🔄", lambda: atualizar(), "Reler o disco (F5)")
        icone = IconeRecolher(barra, bg=BG_CARD)
        icone.pack(side="left", padx=(6, 0))
        dica_ic = Tooltip(icone, "Recolher tudo")

        def _atualiza_icone():
            tudo = disco.all_expanded()
            icone.set_modo(recolher=tudo)
            dica_ic.text = "Recolher tudo" if tudo else "Expandir tudo"

        def _alterna():
            if disco.all_expanded():
                disco.set_all_expanded(False)
                if disco.rows():
                    disco.toggle(0)
            else:
                # expandir tudo no disco real só abre o que já foi lido,
                # para não disparar leitura de milhares de pastas de uma vez
                for r in disco.rows():
                    if r.expandable:
                        disco._expanded.add(r.key)
                disco.reload()
            _atualiza_icone()
        icone.command = _alterna
        ctk.CTkLabel(barra, text=base_g, text_color=FG_DIM, font=F(10)
                     ).pack(side="right")

        def ctx(row, sel):
            itens = [
                ("📂  Abrir no Explorador", abrir, bool(sel)),
                ("📋  Copiar caminho", copiar_caminho, bool(sel)),
                None,
                ("＋ 📁  Nova pasta aqui", lambda: nova("folder"), True),
                ("＋ 📄  Novo arquivo aqui", lambda: nova("file"), True),
            ]
            if g["kind"] != "marketplace" and (g.get("template") or "").strip():
                itens.append(("🧩  Criar estrutura do modelo aqui",
                              lambda: self._criar_modelo_em(
                                  g, pasta_alvo(), depois=lambda: atualizar()),
                              True))
            um_pasta = len(sel) == 1 and sel[0].kind == "folder"
            itens += [
                None,
                ("✎  Renomear                    F2", renomear_um, len(sel) == 1),
                (("✎✎  Renomear o conteúdo desta pasta" if um_pasta else
                  f"✎✎  Renomear em massa ({len(sel)})"), renomear_massa,
                 bool(sel)),
                None,
                ("🗑  Mandar para a Lixeira      Del", excluir, bool(sel)),
                None,
                ("🏠  Definir como pasta base", definir_base, um_pasta),
                ("🔄  Atualizar", lambda: atualizar(), True),
            ]
            return itens
        disco.on_context = ctx
        disco.on_action = lambda r, a: excluir() if a == "delete" else None

        def ativar(r):
            if r.kind == "folder" or not r.payload:
                return
            try:
                os.startfile(r.payload)       # abre no programa padrão
            except OSError as e:
                messagebox.showerror("Abrir", str(e))
        disco.on_activate = ativar
        disco.canvas.bind("<F5>", lambda e: atualizar())
        disco.canvas.bind("<Control-n>", lambda e: nova("folder"))

        def _sel(rows):
            if not rows:
                status.configure(text="", text_color=FG_DIM)
            elif len(rows) == 1:
                status.configure(text=rows[0].payload or "", text_color=FG_DIM)
            else:
                status.configure(text=f"{len(rows)} itens selecionados",
                                 text_color=FG_LABEL)
        disco.on_select = _sel
        monta()
        _atualiza_icone()

    def _escopo_row(self, parent, g):
        """O que conferir: um mês (marketplace) ou uma pasta (estrutura).
        Devolve uma função que diz o escopo escolhido no momento."""
        if g["kind"] == "marketplace":
            ano_var, mes_var = self._ano_mes_row(parent, g)
            return lambda: {"tipo": "mes", "ano": ano_var.get(),
                            "mes": mes_var.get(),
                            "rotulo": f"{mes_var.get()[:2]}_{ano_var.get()}"}
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(4, 8))
        ctk.CTkLabel(row, text="PASTA A CONFERIR", text_color=FG_LABEL,
                     font=F(11, True)).pack(side="left", padx=(0, 8))
        pasta_var = tk.StringVar(value=g.get("base_path", ""))
        ctk.CTkEntry(row, textvariable=pasta_var, height=30, fg_color=BG_INPUT,
                     border_color=BORDER, text_color=FG_MAIN, font=F(11)
                     ).pack(side="left", fill="x", expand=True)

        def _escolher():
            p = filedialog.askdirectory(parent=self,
                                        initialdir=pasta_var.get() or None)
            if p:
                pasta_var.set(os.path.normpath(p))
        ctk.CTkButton(row, text="…", width=36, height=30, corner_radius=8,
                      fg_color=BG_INPUT, hover_color=BG_HOVER,
                      text_color=FG_MAIN, command=_escolher
                      ).pack(side="left", padx=(6, 0))
        ctk.CTkLabel(parent, text="Confere as subpastas desta pasta: vazias, sem "
                                  "arquivo e as que ainda têm nome provisório ("
                                  + ", ".join(g.get("provisorios")
                                              or PROVISORIOS_PADRAO) + ").",
                     text_color=FG_DIM, font=F(10)).pack(anchor="w",
                                                         pady=(0, 6))
        return lambda: {"tipo": "pasta", "path": pasta_var.get().strip(),
                        "rotulo": os.path.basename(pasta_var.get().strip())
                        or "pasta"}

    def _roda_conferencia(self, g, esc):
        if esc["tipo"] == "mes":
            return conferir_pastas(g, esc["ano"], esc["mes"])
        return conferir_pasta(
            esc["path"],
            provisorios=g.get("provisorios") or PROVISORIOS_PADRAO,
            usa_enviar=g.get("usa_enviar", g.get("kind") == "marketplace"),
            prefixo=g.get("prefix", ""))

    def _criar_modelo_em(self, g, destino, depois=None):
        """Aplica o modelo do grupo dentro de uma pasta qualquer."""
        if not destino or not os.path.isdir(destino):
            messagebox.showinfo("Criar estrutura", "Escolha uma pasta de destino.")
            return
        try:
            nodes = parse_template(g.get("template") or "")
            wanted = collect_variables(nodes)
            builtin = builtin_vars()
            faltam = [v for v in wanted if v not in builtin]
            if faltam:
                messagebox.showinfo(
                    "Criar estrutura",
                    "Este modelo tem campos para preencher ("
                    + ", ".join("{" + f + "}" for f in faltam) + ").\n"
                    "Use a aba Modelo para preencher e criar.")
                try:
                    self._tabs_grupo.set(self.ABA_MODELO)
                except Exception:
                    pass
                return
            vars_ = {k: builtin[k] for k in wanted}
            st = execute_template(nodes, destino, vars_, dry=True)
        except TemplateError as e:
            messagebox.showerror("Modelo", str(e))
            return
        if st["folders"] + st["files"] == 0:
            messagebox.showinfo("Criar estrutura",
                                "Tudo do modelo já existe nessa pasta.")
            return
        pause = (self.config_data.get("pause_onedrive", True)
                 and self.usa("onedrive")
                 and path_no_onedrive(destino) is not None)
        if not messagebox.askyesno(
                "Criar estrutura do modelo aqui",
                f"Destino: {destino}\n\nCriar {st['folders']} pasta(s) e "
                f"{st['files']} arquivo(s)?\n({st['skipped']} já existem e "
                "serão pulados)" + ("\n\nO OneDrive será pausado durante a "
                                    "criação." if pause else "")):
            return

        def tarefa():
            if pause:
                pause_onedrive()
            try:
                return execute_template(nodes, destino, vars_, dry=False)
            finally:
                if pause:
                    resume_onedrive()

        def pronto(r):
            if depois:
                depois()
            if isinstance(r, dict) and "erro" in r:
                messagebox.showerror("Erro", r["erro"])
                return
            self._concluido(f"✓ {r['folders']} pasta(s) e {r['files']} "
                            f"arquivo(s) criados em:\n{destino}", destino)
        self.em_segundo_plano(tarefa, pronto)

    # ═════════════════════════════════════════════════════════════════════════
    # ABA CONFERIR — acha as pastas que o OneDrive não renomeou e corrige
    # ═════════════════════════════════════════════════════════════════════════
    def _mp_tab_conferir(self, tab, g, cor):
        wrap = ctk.CTkFrame(tab, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=10, pady=4)

        escopo = self._escopo_row(wrap, g)
        rot_btn = ("🔍  CONFERIR MÊS" if g["kind"] == "marketplace"
                   else "🔍  CONFERIR PASTA")

        topo = ctk.CTkFrame(wrap, fg_color="transparent")
        topo.pack(fill="x", pady=(0, 8))
        btn_conf = ctk.CTkButton(topo, text=rot_btn, height=36,
                                 corner_radius=10, fg_color=ACCENT,
                                 hover_color=ACCENT_H, text_color=DARK_TXT,
                                 font=F(12, True))
        btn_conf.pack(side="left")
        btn_corrigir = ctk.CTkButton(topo, text="✔ Corrigir todas", height=36,
                                     width=140, corner_radius=10,
                                     fg_color=SEQ_BG, border_width=1,
                                     border_color=SEQ_BD, text_color=SEQ_FG,
                                     hover_color=SEQ_BD, font=F(12, True),
                                     state="disabled")
        btn_corrigir.pack(side="left", padx=(8, 0))
        Tooltip(btn_corrigir,
                "Renomeia de uma vez todas as pastas que ficaram como 'Vazio'\n"
                "mas têm arquivo dentro, usando o nome sugerido.")

        resumo = ctk.CTkFrame(wrap, fg_color="transparent")
        resumo.pack(fill="x", pady=(0, 8))

        corpo = ctk.CTkScrollableFrame(wrap, fg_color=BG_PANEL,
                                       corner_radius=10)
        corpo.pack(fill="both", expand=True)

        estado = {"itens": [], "linhas": []}

        CORES = {"ok": GREEN, "sem_arquivo": YELLOW,
                 "vazia": FG_DIM, "nao_renomeada": "#ff9f43"}
        ROTULOS = {"ok": "✅ entregue", "sem_arquivo": "⚠ sem arte",
                   "vazia": "🔴 vazia", "nao_renomeada": "🟡 não renomeada"}

        def _cartao(pai, titulo, valor, cor_v):
            c = ctk.CTkFrame(pai, fg_color=BG_NODE, corner_radius=10,
                             border_width=1, border_color=BORDER)
            c.pack(side="left", fill="x", expand=True, padx=3)
            ctk.CTkLabel(c, text=str(valor), text_color=cor_v,
                         font=F(20, True)).pack(pady=(8, 0))
            ctk.CTkLabel(c, text=titulo, text_color=FG_LABEL,
                         font=F(10)).pack(pady=(0, 8))

        def _limpa():
            for w in corpo.winfo_children():
                w.destroy()
            for w in resumo.winfo_children():
                w.destroy()
            estado["linhas"].clear()

        def _conferir():
            _limpa()
            btn_conf.configure(state="disabled", text="Conferindo...")
            esc = escopo()
            self.em_segundo_plano(lambda: self._roda_conferencia(g, esc),
                                  _mostrar)

        def _mostrar(r):
            btn_conf.configure(state="normal", text=rot_btn)
            if r.get("erro"):
                messagebox.showerror("Conferir", r["erro"])
                return
            itens = r["itens"]
            estado["itens"] = itens
            if not itens:
                ctk.CTkLabel(corpo, text="Nenhuma pasta encontrada aqui.\n"
                                         f"{r['destino']}",
                             text_color=FG_DIM, font=F(12),
                             justify="center").pack(pady=30)
                btn_corrigir.configure(state="disabled")
                return

            cont = {k: 0 for k in CORES}
            for it in itens:
                cont[it["estado"]] += 1
            _cartao(resumo, "entregues", cont["ok"], GREEN)
            _cartao(resumo, "sem arte", cont["sem_arquivo"], YELLOW)
            _cartao(resumo, "vazias", cont["vazia"], FG_DIM)
            _cartao(resumo, "não renomeadas", cont["nao_renomeada"],
                    CORES["nao_renomeada"])

            pend = [i for i in itens if i["estado"] == "nao_renomeada"]
            btn_corrigir.configure(
                state="normal" if pend else "disabled",
                text=f"✔ Corrigir todas ({len(pend)})" if pend
                     else "✔ Corrigir todas")

            if pend:
                ctk.CTkLabel(
                    corpo,
                    text="Estas ficaram como “Vazio” mas têm arquivo dentro — "
                         "provavelmente o OneDrive não aplicou o rename.\n"
                         "O nome sugerido veio do arquivo; confira e ajuste "
                         "antes de corrigir.",
                    text_color=FG_LABEL, font=F(11), justify="left",
                    wraplength=760).pack(anchor="w", padx=10, pady=(8, 6))
                for it in pend:
                    _linha_corrigir(it)

            outras = [i for i in itens if i["estado"] != "nao_renomeada"]
            if outras:
                ctk.CTkLabel(corpo, text="  DEMAIS PASTAS", text_color=FG_LABEL,
                             font=F(11, True)).pack(anchor="w", padx=10,
                                                    pady=(14, 4))
                for it in outras:
                    ln = ctk.CTkFrame(corpo, fg_color="transparent")
                    ln.pack(fill="x", padx=10, pady=1)
                    ctk.CTkLabel(ln, text=ROTULOS[it["estado"]],
                                 text_color=CORES[it["estado"]], font=F(11),
                                 width=130, anchor="w").pack(side="left")
                    ctk.CTkLabel(ln, text=it["nome"], text_color=FG_MAIN,
                                 font=F(11), anchor="w").pack(side="left")

            # resumo por pessoa
            if r["por_pessoa"]:
                ctk.CTkLabel(corpo, text="  POR RESPONSÁVEL",
                             text_color=FG_LABEL, font=F(11, True)
                             ).pack(anchor="w", padx=10, pady=(16, 4))
                cab = ctk.CTkFrame(corpo, fg_color="transparent")
                cab.pack(fill="x", padx=10)
                for t, w in (("pessoa", 90), ("total", 60), ("entregues", 80),
                             ("sem arte", 80), ("vazias", 70),
                             ("não renomeadas", 120)):
                    ctk.CTkLabel(cab, text=t, text_color=FG_DIM, font=F(10),
                                 width=w, anchor="w").pack(side="left")
                for pessoa, d in sorted(r["por_pessoa"].items()):
                    ln = ctk.CTkFrame(corpo, fg_color="transparent")
                    ln.pack(fill="x", padx=10, pady=1)
                    for val, w, c in ((pessoa, 90, FG_MAIN),
                                      (d["total"], 60, FG_LABEL),
                                      (d["ok"], 80, GREEN),
                                      (d["sem_arquivo"], 80, YELLOW),
                                      (d["vazia"], 70, FG_DIM),
                                      (d["nao_renomeada"], 120,
                                       CORES["nao_renomeada"])):
                        ctk.CTkLabel(ln, text=str(val), text_color=c,
                                     font=F(11), width=w,
                                     anchor="w").pack(side="left")

        def _linha_corrigir(it):
            ln = ctk.CTkFrame(corpo, fg_color=BG_NODE, corner_radius=8,
                              border_width=1, border_color=BORDER)
            ln.pack(fill="x", padx=10, pady=3)
            info = ctk.CTkFrame(ln, fg_color="transparent")
            info.pack(fill="x", padx=10, pady=(8, 2))
            ctk.CTkLabel(info, text=it["codigo"], text_color=CORES["nao_renomeada"],
                         font=F(12, True), width=90, anchor="w").pack(side="left")
            det = f"{it['n_arquivos']} arquivo(s)"
            if it["fonte"]:
                det += f"  ·  de: {it['fonte']}"
            ctk.CTkLabel(info, text=det, text_color=FG_DIM, font=F(10),
                         anchor="w").pack(side="left")

            linha2 = ctk.CTkFrame(ln, fg_color="transparent")
            linha2.pack(fill="x", padx=10, pady=(0, 8))
            sv = tk.StringVar(value=it["sugestao"])
            ent = ctk.CTkEntry(linha2, textvariable=sv, height=30,
                               placeholder_text="nome do cliente",
                               fg_color=BG_INPUT, border_color=BORDER,
                               text_color=FG_MAIN, font=F(12))
            ent.pack(side="left", fill="x", expand=True, padx=(0, 8))
            ctk.CTkButton(linha2, text="📂", width=34, height=30,
                          corner_radius=8, fg_color=BG_INPUT,
                          hover_color=BG_HOVER, text_color=FG_LABEL,
                          font=F(11),
                          command=lambda p=it["path"]: abrir_no_explorer(
                              p, mesma_janela=False)).pack(side="left",
                                                           padx=(0, 6))
            b = ctk.CTkButton(linha2, text="✔ Corrigir", width=100, height=30,
                              corner_radius=8, fg_color=ACCENT,
                              hover_color=ACCENT_H, text_color=DARK_TXT,
                              font=F(11, True))
            b.pack(side="left")
            b.configure(command=lambda: _corrigir_um(it, sv, ln, b))
            estado["linhas"].append((it, sv, ln, b))

        def _corrigir_um(it, sv, ln, btn, silencioso=False):
            nome = _sanitiza_nome(sv.get())
            if not nome:
                if not silencioso:
                    messagebox.showwarning(
                        "Corrigir", "Digite o nome do cliente para esta pasta.")
                return False
            novo = os.path.join(os.path.dirname(it["path"]),
                                _sanitiza_nome(nome_corrigido(it, nome)) or nome)
            try:
                mesmo = os.path.normcase(novo) == os.path.normcase(it["path"])
                if not mesmo and os.path.exists(novo):
                    raise OSError(f"já existe '{os.path.basename(novo)}'")
                os.rename(it["path"], novo)
            except OSError as e:
                if not silencioso:
                    messagebox.showerror("Corrigir", str(e))
                return False
            it["path"], it["estado"] = novo, "ok"
            try:
                btn.configure(text="✓ pronto", state="disabled",
                              fg_color=SEQ_BG, text_color=SEQ_FG)
                ln.configure(border_color=SEQ_BD)
            except Exception:
                pass
            # mantém o índice e o Trello em dia, como no fluxo de renomear
            k = os.path.basename(novo).split(" - ")[0].upper()
            self.index_data[k] = {
                "path": novo, "nome": os.path.basename(novo),
                "cliente": nome, "plat": g["name"].upper(), "codigo": k}
            save_index(self.index_data)
            if g["kind"] == "marketplace":
                self._trello_renomeia_card(g, it["codigo"], nome)
            return True

        def _corrigir_todas():
            alvos = [(it, sv, ln, b) for it, sv, ln, b in estado["linhas"]
                     if it["estado"] == "nao_renomeada" and sv.get().strip()]
            if not alvos:
                messagebox.showinfo(
                    "Corrigir",
                    "Nenhuma pasta com nome preenchido para corrigir.")
                return
            if not messagebox.askyesno(
                    "Corrigir todas",
                    f"Renomear {len(alvos)} pasta(s) com os nomes sugeridos?\n\n"
                    "As que estiverem em branco são ignoradas."):
                return
            feitos = sum(1 for it, sv, ln, b in alvos
                         if _corrigir_um(it, sv, ln, b, silencioso=True))
            btn_corrigir.configure(state="disabled")
            messagebox.showinfo("Corrigir",
                                f"✓ {feitos} pasta(s) corrigida(s).")

        btn_conf.configure(command=_conferir)
        btn_corrigir.configure(command=_corrigir_todas)

    def _trello_renomeia_card(self, g, codigo, nome_cliente):
        """Best-effort: se o Trello estiver ligado, atualiza o card junto."""
        cfg = self.config_data
        if not (cfg.get("usa_trello", True) and group_trello_ok(cfg, g)):
            return

        def tarefa():
            try:
                cards = trello_search_cards(nome_cliente, g["board_id"],
                                            cfg["trello_key"], cfg["trello_token"])
                if len(cards) == 1:
                    trello_update_card_name(
                        cards[0]["id"], f"{codigo} - {cards[0]['name']}",
                        cfg["trello_key"], cfg["trello_token"])
            except Exception:
                pass
        threading.Thread(target=tarefa, daemon=True).start()

    def _ano_mes_row(self, parent, g=None):
        agora = datetime.datetime.now()
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(4, 6))
        ano_var = tk.StringVar(value=str(agora.year))
        mes_var = tk.StringVar(value=MESES[agora.month - 1])
        # janela de anos acompanha o relógio (antes era fixa e venceria em 2032)
        anos = [str(y) for y in range(agora.year - 2, agora.year + 4)]
        ctk.CTkLabel(row, text="ANO", text_color=FG_LABEL, font=F(11, True)
                     ).pack(side="left", padx=(0, 6))
        ctk.CTkOptionMenu(row, variable=ano_var, width=90, values=anos,
                          fg_color=BG_INPUT, button_color=BG_HOVER,
                          text_color=FG_MAIN, font=F(12),
                          dropdown_fg_color=BG_CARD,
                          command=lambda _v: _pinta_meses()
                          ).pack(side="left", padx=(0, 16))
        ctk.CTkLabel(row, text="MÊS", text_color=FG_LABEL, font=F(11, True)
                     ).pack(side="left", padx=(0, 6))
        ctk.CTkOptionMenu(row, variable=mes_var, width=180, values=MESES,
                          fg_color=BG_INPUT, button_color=BG_HOVER,
                          text_color=FG_MAIN, font=F(12),
                          dropdown_fg_color=BG_CARD,
                          command=lambda _v: _pinta_meses()
                          ).pack(side="left")

        if g is None:
            return ano_var, mes_var

        # fita de meses: mostra de relance o que já existe, o que passou e o atual
        fita = ctk.CTkFrame(parent, fg_color="transparent")
        fita.pack(fill="x", pady=(0, 4))
        chips, dicas = {}, {}
        for m in MESES:
            b = ctk.CTkButton(fita, text=m[:2], width=30, height=22,
                              corner_radius=6, fg_color="transparent",
                              border_width=1, border_color=BORDER,
                              text_color=FG_DIM, font=F(10),
                              command=lambda m=m: mes_var.set(m))
            b.pack(side="left", padx=1)
            chips[m] = b
            dicas[m] = Tooltip(b, m)          # UMA dica por mês, reaproveitada
        leg_f = ctk.CTkFrame(parent, fg_color="transparent")
        leg_f.pack(fill="x", pady=(0, 6))
        legenda = ctk.CTkLabel(leg_f, text="", text_color=FG_DIM, font=F(10),
                               anchor="w", justify="left")
        legenda.pack(side="left")
        link = ctk.CTkButton(leg_f, text="Detectar organização", width=10,
                             height=20, corner_radius=6, fg_color="transparent",
                             hover_color=BG_HOVER, text_color=ACCENT,
                             font=F(10), command=lambda: self.open_group_editor(g))

        estado = {"info": {}, "gen": 0}

        def _cores():
            info = estado["info"]
            ano_atual = agora.year
            try:
                ano_sel = int(ano_var.get())
            except ValueError:
                ano_sel = ano_atual
            n_exist = 0
            por_codigo = False
            for m, b in chips.items():
                d = info.get(m, {})
                existe = d.get("existe")
                por_codigo = por_codigo or d.get("por_codigo", False)
                n_exist += 1 if existe else 0
                num = int(m[:2])
                atual = (ano_sel == ano_atual and num == agora.month)
                futuro = (ano_sel, num) > (ano_atual, agora.month)
                if atual:
                    fg, br, tx = SEQ_BG, ACCENT, ACCENT
                elif existe and futuro:
                    fg, br, tx = "transparent", BLUE, BLUE
                elif existe:
                    fg, br, tx = BG_INPUT, BORDER, FG_LABEL
                else:
                    fg, br, tx = "transparent", BORDER, FG_DIM
                if m == mes_var.get():
                    br = ACCENT_H
                b.configure(fg_color=fg, border_color=br, text_color=tx)
                if existe:
                    unid = ("pasta(s) com código " + m[:2]
                            if d.get("por_codigo") else "pasta(s)")
                    dicas[m].text = f"{m} — {d.get('pastas', 0)} {unid}"
                else:
                    dicas[m].text = f"{m} — ainda não existe"
            if not info:
                legenda.configure(text="lendo as pastas…")
                link.pack_forget()
            elif por_codigo:
                sem_ano = not padrao_tem_ano(g.get("dest_pattern") or "")
                legenda.configure(
                    text="Este grupo não tem pasta por mês — contagem pelo código "
                         "das pastas" + (" (todos os anos juntos)" if sem_ano
                                         else "") + "   ·")
                link.pack(side="left", padx=(4, 0))
            else:
                legenda.configure(
                    text=f"{n_exist} de 12 meses já criados em {ano_var.get()}   ·   "
                         "verde = mês atual · cinza = já existe · "
                         "azul = existe e ainda vai chegar · vazio = não existe")
                link.pack_forget()

        def _pinta_meses():
            # lê o disco fora da tela; quem chegar atrasado é descartado
            estado["gen"] += 1
            gen, ano = estado["gen"], ano_var.get()

            def pronto(info):
                if gen != estado["gen"] or not fita.winfo_exists():
                    return
                ok_info = isinstance(info, dict) and "erro" not in info
                estado["info"] = info if ok_info else {}
                _cores()
            self.em_segundo_plano(lambda: meses_existentes(g, ano), pronto)

        # trocar o mês só repinta; trocar o ano relê o disco
        mes_var.trace_add("write", lambda *_: _cores())
        ano_var.trace_add("write", lambda *_: _pinta_meses())
        _cores()
        _pinta_meses()
        return ano_var, mes_var

    def _mp_tab_criar(self, tab, g, cor):
        wrap = ctk.CTkFrame(tab, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=10, pady=4)

        ano_var, mes_var = self._ano_mes_row(wrap, g)

        hdr = ctk.CTkFrame(wrap, fg_color="transparent")
        hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="RESPONSÁVEL (iniciais)", text_color=FG_LABEL,
                     font=F(11, True), width=160, anchor="w").pack(side="left")
        ctk.CTkLabel(hdr, text="QUANTIDADE", text_color=FG_LABEL,
                     font=F(11, True), anchor="w").pack(side="left")

        linhas = ctk.CTkFrame(wrap, fg_color="transparent")
        linhas.pack(fill="x")
        pessoas = []

        def add_linha(resp="", qtd="1", focar=True):
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
                    _atualiza_total()
            ctk.CTkButton(row, text="✕", width=30, height=28, corner_radius=8,
                          fg_color="transparent", hover_color=BG_HOVER,
                          text_color=RED, font=F(12, True), command=remover
                          ).pack(side="left")
            pessoas.append(item)
            qv.trace_add("write", lambda *_: _atualiza_total())
            if focar:
                e1.focus_set()
            _atualiza_total()
            return item

        rodape_p = ctk.CTkFrame(wrap, fg_color="transparent")
        rodape_p.pack(fill="x", pady=(4, 6))
        ctk.CTkButton(rodape_p, text="＋ Adicionar pessoa", height=30,
                      corner_radius=10, fg_color="transparent",
                      hover_color=BG_HOVER, text_color=ACCENT, font=F(12),
                      command=add_linha).pack(side="left")
        lbl_total = ctk.CTkLabel(rodape_p, text="", text_color=FG_LABEL,
                                 font=F(11))
        lbl_total.pack(side="right")

        def _atualiza_total():
            t = 0
            for p in pessoas:
                try:
                    t += max(0, int(p["qtd"].get()))
                except ValueError:
                    pass
            lbl_total.configure(text=f"total: {t} pasta(s)")

        add_linha(focar=False)   # só agora: add_linha usa _atualiza_total

        # ── distribuir um total entre a equipe ───────────────────────────────
        dist = ctk.CTkFrame(wrap, fg_color=BG_NODE, corner_radius=10,
                            border_width=1, border_color=BORDER)
        dist.pack(fill="x", pady=(0, 8))
        dl = ctk.CTkFrame(dist, fg_color="transparent")
        dl.pack(fill="x", padx=10, pady=8)
        ctk.CTkLabel(dl, text="Dividir um total:", text_color=FG_LABEL,
                     font=F(11)).pack(side="left", padx=(0, 8))
        total_var = tk.StringVar()
        ctk.CTkEntry(dl, textvariable=total_var, width=70, height=28,
                     placeholder_text="ex: 100", fg_color=BG_INPUT,
                     border_color=BORDER, text_color=FG_MAIN,
                     font=F(12)).pack(side="left", padx=(0, 8))

        def _dividir():
            try:
                total = int(total_var.get())
                assert total > 0
            except Exception:
                messagebox.showwarning("Dividir",
                                       "Digite um total maior que zero.")
                return
            nomes = [p["resp"].get().strip().upper() for p in pessoas
                     if p["resp"].get().strip()]
            if not nomes:
                messagebox.showwarning(
                    "Dividir", "Preencha as iniciais das pessoas primeiro.")
                return
            d = distribuir_total(total, nomes)
            for p in pessoas:
                r = p["resp"].get().strip().upper()
                if r in d:
                    p["qtd"].set(str(d[r]))
            _atualiza_total()

        b_div = ctk.CTkButton(dl, text="Dividir igualmente", height=28,
                              width=140, corner_radius=8, fg_color=BG_INPUT,
                              hover_color=BG_HOVER, text_color=FG_LABEL,
                              font=F(11), command=_dividir)
        b_div.pack(side="left")
        Tooltip(b_div, "Divide o total entre as pessoas preenchidas.\n"
                       "O resto vai de um em um (100 ÷ 3 = 34, 33, 33).\n"
                       "Depois dá para ajustar cada um na mão.")

        # ── histórico: pessoas usadas antes e repetir o último lote ─────────
        sugs = sugestoes_de_pessoas(g["name"])
        ult = ultimo_lote(g["name"])
        if sugs or ult:
            hist_f = ctk.CTkFrame(wrap, fg_color="transparent")
            hist_f.pack(fill="x", pady=(0, 8))
            ctk.CTkLabel(hist_f, text="Usados antes:", text_color=FG_DIM,
                         font=F(10)).pack(side="left", padx=(0, 6))

            def _usa(pessoa, qtd):
                for p in pessoas:
                    if p["resp"].get().strip().upper() == pessoa:
                        p["qtd"].set(str(qtd))
                        return
                vazia = next((p for p in pessoas
                              if not p["resp"].get().strip()), None)
                if vazia:
                    vazia["resp"].set(pessoa)
                    vazia["qtd"].set(str(qtd))
                else:
                    add_linha(pessoa, str(qtd), focar=False)
                _atualiza_total()

            for pessoa, qtd, _n in sugs:
                b = ctk.CTkButton(hist_f, text=f"{pessoa} ({qtd})", height=24,
                                  width=76, corner_radius=12,
                                  fg_color="transparent", border_width=1,
                                  border_color=BORDER_S, hover_color=BG_HOVER,
                                  text_color=FG_LABEL, font=F(10),
                                  command=lambda p=pessoa, q=qtd: _usa(p, q))
                b.pack(side="left", padx=2)
                Tooltip(b, f"Adiciona {pessoa} com a quantidade que você "
                           f"costuma dar ({qtd}).")

            if ult:
                def _repetir():
                    for p in list(pessoas[1:]):
                        p["frame"].destroy()
                        pessoas.remove(p)
                    itens_u = ult.get("itens", [])
                    if itens_u:
                        pessoas[0]["resp"].set(itens_u[0]["pessoa"])
                        pessoas[0]["qtd"].set(str(itens_u[0]["qtd"]))
                        for it in itens_u[1:]:
                            add_linha(it["pessoa"], str(it["qtd"]), focar=False)
                    _atualiza_total()

                b = ctk.CTkButton(hist_f, text="↺ repetir último", height=24,
                                  width=118, corner_radius=12,
                                  fg_color="transparent", border_width=1,
                                  border_color=SEQ_BD, hover_color=BG_HOVER,
                                  text_color=SEQ_FG, font=F(10),
                                  command=_repetir)
                b.pack(side="left", padx=(8, 2))
                resumo_u = ", ".join(f"{i['pessoa']}:{i['qtd']}"
                                     for i in ult.get("itens", [])[:5])
                Tooltip(b, f"Repete a distribuição do lote de "
                           f"{ult.get('mes', '?')}:\n{resumo_u}")

        od_root = (path_no_onedrive(g.get("base_path", ""))
                   if self.usa("onedrive") else None)
        pause_var = tk.BooleanVar(
            value=self.config_data.get("pause_onedrive", True) and bool(od_root))
        if od_root:
            sw_od = make_switch(wrap, text="Pausar OneDrive durante criação",
                                variable=pause_var, progress_color=ACCENT,
                                text_color=FG_LABEL, font=F(12))
            sw_od.pack(anchor="w", pady=(0, 8))
            Tooltip(sw_od, "Esta pasta fica dentro do OneDrive:\n"
                           f"{od_root}\n\nFecha o OneDrive durante a criação "
                           "e reabre no fim.")

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
                # só letras: um dígito ou acento aqui quebra a numeração do
                # mês seguinte, porque o código vira ilegível para o contador
                if not resp.isascii() or not resp.isalpha():
                    erros.append(
                        f"Linha {i} ({resp}): as iniciais devem ter só letras "
                        "de A a Z, sem números, espaços ou acentos.")
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
            destino = mp_destino(g, ano_var.get(), mes_var.get())
            extra = ("\n\nO OneDrive será pausado durante a criação."
                     if pause_var.get() else "")
            if not os.path.isdir(destino):
                extra = (f"\n\n📁 A pasta “{os.path.basename(destino)}” ainda "
                         "não existe e será criada agora.") + extra
            if not messagebox.askyesno(
                    "Confirmar criação",
                    f"Grupo: {g['name']}\nMês: {mes_var.get()} / {ano_var.get()}\n"
                    f"Destino: {destino}\n\n"
                    f"{resumo}\n\nTotal: {total} pasta(s). Confirma?" + extra):
                return
            btn.configure(state="disabled", text="Criando...")
            ano, mes, pausar = ano_var.get(), mes_var.get(), pause_var.get()

            def tarefa(avisa):
                # o log vai pela fila: quem escreve na tela é a thread principal
                def log_seguro(msg, erro=False, aviso=False, ok=False):
                    avisa((msg, erro, aviso, ok))
                n = criar_lote(g, ano, mes, itens, log_seguro, pausar)
                if n:
                    registrar_lote(g["name"], ano, mes, itens)
                return n

            def progresso(p):
                if out.winfo_exists():
                    msg, erro, aviso, ok = p
                    log_fn(msg, erro=erro, aviso=aviso, ok=ok)

            def pronto(n):
                if btn.winfo_exists():
                    btn.configure(state="normal", text="✚  CRIAR PASTAS")
                if isinstance(n, dict):
                    if out.winfo_exists():
                        log_fn(f"ERRO: {n.get('erro')}", erro=True)
                    return
                if out.winfo_exists():
                    log_fn(f"{n} pasta(s) criada(s) com sucesso!", ok=True)
                if n:
                    self._concluido(f"✓ {n} pasta(s) criada(s) em:\n{destino}",
                                    destino)
            self.em_segundo_plano(tarefa, pronto, ao_progredir=progresso)

        btn = ctk.CTkButton(wrap, text="✚  CRIAR PASTAS", height=42, corner_radius=21,
                            fg_color=ACCENT, hover_color=ACCENT_H,
                            text_color=DARK_TXT, font=F(13, True), command=iniciar)
        btn.pack(fill="x", pady=(0, 8))
        out.pack(fill="both", expand=True)

    def _mp_tab_renomear(self, tab, g, cor):
        """Localiza uma pasta do grupo por código ou por parte do nome e troca
        o nome do cliente (ou o nome inteiro). Vale para qualquer grupo."""
        wrap = ctk.CTkFrame(tab, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=10, pady=4)
        cfg = self.config_data
        mp = g["kind"] == "marketplace"

        ctk.CTkLabel(wrap, text="CÓDIGO OU PARTE DO NOME", text_color=FG_LABEL,
                     font=F(11, True)).pack(anchor="w", pady=(2, 3))
        busca_row = ctk.CTkFrame(wrap, fg_color="transparent")
        busca_row.pack(fill="x")
        termo_var = tk.StringVar()
        ent_busca = ctk.CTkEntry(busca_row, textvariable=termo_var, height=34,
                                 placeholder_text="ex.: 090012IB  ou  padaria",
                                 fg_color=BG_INPUT, border_color=BORDER,
                                 text_color=FG_MAIN, font=F(12))
        ent_busca.pack(side="left", fill="x", expand=True, padx=(0, 8))
        btn_loc = ctk.CTkButton(busca_row, text="🔍 Localizar", width=120,
                                height=34, corner_radius=10, fg_color=BG_INPUT,
                                hover_color=BG_HOVER, text_color=FG_MAIN,
                                font=F(12))
        btn_loc.pack(side="left")

        lista = ctk.CTkScrollableFrame(wrap, fg_color=BG_PANEL, corner_radius=10,
                                       height=170)
        lista.pack(fill="x", pady=(8, 8))
        lbl_loc = ctk.CTkLabel(lista, text="Digite e aperte Enter para procurar "
                                           "nas pastas do grupo.",
                               text_color=FG_DIM, font=F(11))
        lbl_loc.pack(pady=14)

        sel_lbl = ctk.CTkLabel(wrap, text="", text_color=FG_DIM, font=F(11),
                               justify="left", anchor="w", wraplength=700)
        sel_lbl.pack(fill="x")

        rot_nome = ctk.CTkLabel(wrap, text="NOVO NOME DO CLIENTE",
                                text_color=FG_LABEL, font=F(11, True))
        rot_nome.pack(anchor="w", pady=(8, 3))
        nome_var = tk.StringVar()
        ctk.CTkEntry(wrap, textvariable=nome_var, height=34, fg_color=BG_INPUT,
                     border_color=BORDER, text_color=FG_MAIN, font=F(12)
                     ).pack(fill="x", pady=(0, 4))
        inteiro_var = tk.BooleanVar(value=False)
        sw_int = make_switch(wrap, text="Trocar o nome inteiro (não manter o "
                                        "código)", variable=inteiro_var,
                             progress_color=ACCENT, text_color=FG_LABEL,
                             font=F(11), command=lambda: _prev_nome())
        sw_int.pack(anchor="w")
        prev_nome = ctk.CTkLabel(wrap, text="", text_color=FG_DIM, font=F(11),
                                 anchor="w")
        prev_nome.pack(fill="x", pady=(2, 0))

        usa_tr = mp and self.usa("trello")
        trello_ok = usa_tr and group_trello_ok(cfg, g)
        usar_trello = tk.BooleanVar(value=trello_ok)
        mover_var = tk.BooleanVar(value=trello_ok)
        card_lbl = ctk.CTkLabel(wrap, text="", text_color=FG_DIM, font=F(11),
                                justify="left")
        if usa_tr:
            tf = ctk.CTkFrame(wrap, fg_color="transparent")
            tf.pack(fill="x", pady=(8, 0))
            sw1 = make_switch(tf, text="Atualizar card no Trello",
                              variable=usar_trello, progress_color=ACCENT,
                              text_color=FG_LABEL, font=F(11))
            sw1.pack(side="left", padx=(0, 16))
            sw2 = make_switch(tf, text="Mover para Aguardando Aprovação",
                              variable=mover_var, progress_color=ACCENT,
                              text_color=FG_LABEL, font=F(11))
            sw2.pack(side="left")
            if not trello_ok:
                sw1.configure(state="disabled")
                sw2.configure(state="disabled")
                ctk.CTkLabel(wrap, text="Configure a chave do Trello (⚙) e o "
                                        "Board ID do grupo (✎) para ativar.",
                             text_color=FG_DIM, font=F(10)).pack(anchor="w")
            card_lbl.pack(anchor="w", pady=(4, 0))

        btn_ren = ctk.CTkButton(wrap, text="✏  RENOMEAR", height=40,
                                corner_radius=10, fg_color=ACCENT,
                                hover_color=ACCENT_H, text_color=DARK_TXT,
                                font=F(13, True), state="disabled")
        btn_ren.pack(fill="x", pady=(12, 0))
        status = ctk.CTkLabel(wrap, text="", font=F(12), wraplength=700,
                              justify="left")
        status.pack(anchor="w", pady=(8, 0))

        est = {"path": None, "cards": [], "card": None, "busca": 0}

        def _novo_nome():
            if not est["path"]:
                return ""
            atual = os.path.basename(est["path"])
            nome = nome_var.get().strip()
            if not nome:
                return ""
            if inteiro_var.get() or " - " not in atual:
                return nome
            return f"{atual.split(' - ')[0]} - {nome}"

        def _prev_nome(*_a):
            n = _novo_nome()
            prev_nome.configure(text=f"→ ficará: {n}" if n else "")
            btn_ren.configure(state="normal" if (n and est["path"])
                              else "disabled")

        def _seleciona(path):
            est["path"] = path
            atual = os.path.basename(path)
            tem_cod = " - " in atual
            sel_lbl.configure(text=f"Selecionada: {atual}\n{path}",
                              text_color=GREEN)
            rot_nome.configure(text="NOVO NOME DO CLIENTE" if tem_cod
                               else "NOVO NOME DA PASTA")
            inteiro_var.set(not tem_cod)
            _prev_nome()

        def _mostra_resultados(paths):
            btn_loc.configure(state="normal", text="🔍 Localizar")
            for w in lista.winfo_children():
                w.destroy()
            if isinstance(paths, dict):
                paths = []
            if not paths:
                ctk.CTkLabel(lista, text="Nada encontrado com esse termo.",
                             text_color=YELLOW, font=F(11)).pack(pady=14)
                return
            base = g.get("base_path", "")
            for p in paths:
                rel = os.path.relpath(os.path.dirname(p), base) if base else ""
                b = ctk.CTkButton(
                    lista, text=f"{os.path.basename(p)}      {rel}",
                    anchor="w", height=28, corner_radius=6,
                    fg_color="transparent", hover_color=BG_HOVER,
                    text_color=FG_MAIN, font=F(11),
                    command=lambda p=p: _seleciona(p))
                b.pack(fill="x", pady=1)
            if len(paths) == 1:
                _seleciona(paths[0])

        def localizar(_e=None):
            termo = termo_var.get().strip()
            if not termo:
                return
            if not g.get("base_path") or not os.path.isdir(g["base_path"]):
                messagebox.showinfo("Renomear", "Defina a pasta base do grupo.")
                return
            btn_loc.configure(state="disabled", text="Procurando…")
            est["path"] = None
            _prev_nome()
            self.em_segundo_plano(
                lambda: buscar_pastas(g["base_path"], termo), _mostra_resultados)
        ent_busca.bind("<Return>", localizar)
        btn_loc.configure(command=localizar)

        _card_job = [None]

        def _busca_card():
            nome = nome_var.get().strip()
            if not (usar_trello.get() and trello_ok) or len(nome) < 3:
                return
            card_lbl.configure(text="buscando card…", text_color=FG_DIM)
            est["busca"] += 1
            n_busca = est["busca"]

            def pronto(cards):
                if n_busca != est["busca"] or not card_lbl.winfo_exists():
                    return
                if isinstance(cards, dict):
                    card_lbl.configure(text=f"Erro Trello: {cards.get('erro')}",
                                       text_color=RED)
                    return
                est["cards"], est["card"] = cards, None
                if len(cards) == 1:
                    est["card"] = cards[0]
                    card_lbl.configure(text=f"Card: {cards[0]['name']}",
                                       text_color=GREEN)
                elif cards:
                    card_lbl.configure(text=f"{len(cards)} cards — clique para "
                                            "escolher", text_color=YELLOW)
                    card_lbl.bind("<Button-1>", lambda e: _escolhe_card())
                else:
                    card_lbl.configure(text="Nenhum card encontrado.",
                                       text_color=YELLOW)
            self.em_segundo_plano(
                lambda: trello_search_cards(nome, g["board_id"],
                                            cfg["trello_key"],
                                            cfg["trello_token"]), pronto)

        def _escolhe_card():
            cards = est["cards"]
            if not cards:
                return
            nomes_listas = {}
            try:
                for c in cards:
                    lid = c.get("idList", "")
                    if lid and lid not in nomes_listas:
                        nomes_listas[lid] = trello_get_list_name(
                            lid, cfg["trello_key"], cfg["trello_token"])
            except Exception:
                pass
            escolhido = dialog_selecionar_card(self, cards, nomes_listas)
            if escolhido:
                est["card"] = escolhido
                card_lbl.configure(text=f"Card: {escolhido['name']}",
                                   text_color=GREEN)

        def _nome_mudou(*_a):
            _prev_nome()
            if _card_job[0]:
                try:
                    self.after_cancel(_card_job[0])
                except Exception:
                    pass
            _card_job[0] = self.after(500, _busca_card)   # sem martelar a API
        nome_var.trace_add("write", _nome_mudou)

        def renomear():
            novo_nome = _sanitiza_nome(_novo_nome())
            if not est["path"] or not novo_nome:
                return
            antigo = est["path"]
            atual = os.path.basename(antigo)
            if not messagebox.askyesno("Confirmar",
                                       f"Renomear:\n  {atual}\npara:\n  "
                                       f"{novo_nome}\n\nConfirma?"):
                return
            novo = os.path.join(os.path.dirname(antigo), novo_nome)
            mesmo = os.path.normcase(novo) == os.path.normcase(antigo)
            if not mesmo and os.path.exists(novo):
                messagebox.showerror("Renomear",
                                     f"Já existe '{novo_nome}' nessa pasta.")
                return
            try:
                os.rename(antigo, novo)
            except OSError as e:
                messagebox.showerror("Renomear", str(e))
                return
            est["path"] = novo
            k = novo_nome.split(" - ")[0].upper()
            self.index_data[k] = {"path": novo, "nome": novo_nome,
                                  "cliente": nome_var.get().strip(),
                                  "plat": g["name"].upper(), "codigo": k}
            save_index(self.index_data)
            sel_lbl.configure(text=f"Renomeada: {novo_nome}\n{novo}",
                              text_color=GREEN)
            status.configure(text="✓ Pasta renomeada.", text_color=GREEN)

            card = est["card"]
            if not (usa_tr and usar_trello.get() and trello_ok):
                return
            if not card:
                status.configure(text="✓ Pasta renomeada. ⚠ Card do Trello não "
                                      "identificado — atualize manualmente.",
                                 text_color=YELLOW)
                return
            codigo_pasta = atual.split(" - ")[0]

            def tarefa():
                erros = []
                try:
                    trello_update_card_name(card["id"],
                                            f"{codigo_pasta} - {card['name']}",
                                            cfg["trello_key"], cfg["trello_token"])
                except Exception as e:
                    erros.append(f"título: {e}")
                if mover_var.get():
                    if g.get("list_aguardando"):
                        try:
                            trello_move_card(card["id"], g["list_aguardando"],
                                             cfg["trello_key"],
                                             cfg["trello_token"])
                        except Exception as e:
                            erros.append(f"mover: {e}")
                    else:
                        erros.append("ID da lista Aguardando não configurado")
                return erros

            def pronto(erros):
                if not status.winfo_exists():
                    return
                if isinstance(erros, dict) or erros:
                    txt = erros.get("erro") if isinstance(erros, dict) \
                        else " | ".join(erros)
                    status.configure(text=f"✓ Pasta renomeada. ⚠ Trello: {txt}",
                                     text_color=YELLOW)
                else:
                    status.configure(text="✓ Pasta renomeada e card atualizado.",
                                     text_color=GREEN)
            self.em_segundo_plano(tarefa, pronto)
        btn_ren.configure(command=renomear)

    def _mp_tab_relatorio(self, tab, g, cor):
        wrap = ctk.CTkFrame(tab, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=10, pady=4)

        escopo = self._escopo_row(wrap, g)

        topo = ctk.CTkFrame(wrap, fg_color="transparent")
        topo.pack(fill="x", pady=(0, 8))
        btn = ctk.CTkButton(topo, text="📊  GERAR RELATÓRIO", height=36,
                            corner_radius=10, fg_color=ACCENT,
                            hover_color=ACCENT_H, text_color=DARK_TXT,
                            font=F(12, True))
        btn.pack(side="left")
        btn_csv = ctk.CTkButton(topo, text="⤓ Exportar CSV", height=36,
                                width=130, corner_radius=10, fg_color=BG_INPUT,
                                hover_color=BG_HOVER, text_color=FG_LABEL,
                                font=F(11), state="disabled")
        btn_csv.pack(side="left", padx=(8, 0))
        Tooltip(btn_csv, "Salva a tabela num arquivo .csv, que abre no Excel.")

        cartoes = ctk.CTkFrame(wrap, fg_color="transparent")
        cartoes.pack(fill="x", pady=(0, 8))

        tabela = ctk.CTkScrollableFrame(wrap, fg_color=BG_PANEL,
                                        corner_radius=10)
        tabela.pack(fill="both", expand=True)

        dados = {"linhas": [], "ordem": ("codigo", False)}
        COLS = [("codigo", "CÓDIGO", 110), ("cliente", "CLIENTE", 240),
                ("iniciais", "RESP.", 70), ("estado", "SITUAÇÃO", 130),
                ("n_arquivos", "ARQUIVOS", 80)]
        ROT = {"ok": "✅ entregue", "sem_arquivo": "⚠ sem arte",
               "vazia": "🔴 vazia", "nao_renomeada": "🟡 não renomeada"}
        CORES = {"ok": GREEN, "sem_arquivo": YELLOW, "vazia": FG_DIM,
                 "nao_renomeada": "#ff9f43"}

        def _cartao(titulo, valor, cor_v):
            c = ctk.CTkFrame(cartoes, fg_color=BG_NODE, corner_radius=10,
                             border_width=1, border_color=BORDER)
            c.pack(side="left", fill="x", expand=True, padx=3)
            ctk.CTkLabel(c, text=str(valor), text_color=cor_v,
                         font=F(20, True)).pack(pady=(8, 0))
            ctk.CTkLabel(c, text=titulo, text_color=FG_LABEL,
                         font=F(10)).pack(pady=(0, 8))

        def _ordena(campo):
            atual, inv = dados["ordem"]
            dados["ordem"] = (campo, not inv if campo == atual else False)
            _desenha()

        def _desenha():
            for w in tabela.winfo_children():
                w.destroy()
            campo, inv = dados["ordem"]
            linhas = sorted(dados["linhas"],
                            key=lambda d: (str(d.get(campo, "")).lower()
                                           if not isinstance(d.get(campo), int)
                                           else d.get(campo)),
                            reverse=inv)
            cab = ctk.CTkFrame(tabela, fg_color="transparent")
            cab.pack(fill="x", pady=(2, 4))
            for chave, rot, larg in COLS:
                seta = ""
                if chave == campo:
                    seta = " ▾" if inv else " ▴"
                ctk.CTkButton(cab, text=rot + seta, width=larg, height=24,
                              corner_radius=6, fg_color="transparent",
                              hover_color=BG_HOVER, anchor="w",
                              text_color=ACCENT if chave == campo else FG_DIM,
                              font=F(10, True),
                              command=lambda c=chave: _ordena(c)
                              ).pack(side="left", padx=1)
            for d in linhas:
                ln = ctk.CTkFrame(tabela, fg_color="transparent")
                ln.pack(fill="x", pady=1)
                for chave, _rot, larg in COLS:
                    val = d.get(chave, "")
                    cor = FG_MAIN
                    if chave == "estado":
                        cor = CORES.get(val, FG_MAIN)
                        val = ROT.get(val, val)
                    elif chave in ("iniciais", "n_arquivos"):
                        cor = FG_LABEL
                    ctk.CTkLabel(ln, text=str(val), text_color=cor, font=F(11),
                                 width=larg, anchor="w").pack(side="left",
                                                              padx=1)

        def _exportar():
            caminho = filedialog.asksaveasfilename(
                parent=self, defaultextension=".csv",
                initialfile=f"relatorio_{g['name']}_{escopo()['rotulo']}.csv",
                filetypes=[("CSV (Excel)", "*.csv")])
            if not caminho:
                return
            try:
                import csv
                with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
                    w = csv.writer(f, delimiter=";")
                    w.writerow([r for _c, r, _l in COLS])
                    campo, inv = dados["ordem"]
                    for d in sorted(dados["linhas"],
                                    key=lambda x: str(x.get(campo, "")),
                                    reverse=inv):
                        w.writerow([ROT.get(d.get(c), d.get(c, ""))
                                    if c == "estado" else d.get(c, "")
                                    for c, _r, _l in COLS])
            except OSError as e:
                messagebox.showerror("Exportar", str(e))
                return
            if messagebox.askyesno(
                    "Exportar",
                    f"Salvo em:\n{caminho}\n\nAbrir a pasta?"):
                abrir_no_explorer(os.path.dirname(caminho), mesma_janela=False)

        def gerar():
            for w in cartoes.winfo_children():
                w.destroy()
            for w in tabela.winfo_children():
                w.destroy()
            btn.configure(state="disabled", text="Gerando...")
            esc = escopo()
            self.em_segundo_plano(lambda: self._roda_conferencia(g, esc),
                                  _mostrar)

        def _mostrar(r):
            btn.configure(state="normal", text="📊  GERAR RELATÓRIO")
            if r.get("erro"):
                messagebox.showerror("Relatório", r["erro"])
                return
            itens = r["itens"]
            dados["linhas"] = itens
            btn_csv.configure(state="normal" if itens else "disabled")
            if not itens:
                ctk.CTkLabel(tabela,
                             text="Nenhuma pasta aqui.\n"
                                  f"{r.get('destino', '')}",
                             text_color=FG_DIM, font=F(12),
                             justify="center").pack(pady=30)
                return
            cont = {"ok": 0, "sem_arquivo": 0, "vazia": 0, "nao_renomeada": 0}
            for it in itens:
                cont[it["estado"]] += 1
            _cartao("total", len(itens), FG_MAIN)
            _cartao("entregues", cont["ok"], GREEN)
            _cartao("sem arte", cont["sem_arquivo"], YELLOW)
            _cartao("vazias", cont["vazia"], FG_DIM)
            _cartao("não renomeadas", cont["nao_renomeada"],
                    CORES["nao_renomeada"])
            _desenha()

        btn.configure(command=gerar)
        btn_csv.configure(command=_exportar)


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
                # a chave pode ser composta (código + caminho) quando há
                # nomes repetidos; a busca olha o código e o nome de verdade
                alvo = (info.get("codigo") or cod.split("\x00")[0]).upper()
                if (termo in alvo
                        or termo in info.get("cliente", "").upper()
                        or termo in info.get("nome", "").upper()):
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

            ultimo = [0.0]

            def tarefa(avisa):
                def prog(d):
                    agora = time.time()
                    if agora - ultimo[0] > 0.15:     # não inunda a fila
                        ultimo[0] = agora
                        avisa(d)
                idx = build_index(self.groups(), progress_fn=prog)
                save_index(idx)
                return idx

            def progresso(d):
                idx_var.set(f"Indexando: {d[:40]}...")

            def pronto(idx):
                if btn_idx.winfo_exists():
                    btn_idx.configure(state="normal", text="🔄 Atualizar índice")
                if isinstance(idx, dict) and "erro" in idx and len(idx) == 1:
                    idx_var.set(f"ERRO ao indexar: {idx['erro']}")
                    return
                self.index_data = idx
                idx_var.set(f"Índice atualizado: {len(idx)} pastas indexadas.")
            self.em_segundo_plano(tarefa, pronto, ao_progredir=progresso)
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
                sc, values=["Estrutura personalizada", "Marketplace"],
                fg_color=BG_INPUT, selected_color=ACCENT_DK,
                selected_hover_color=ACCENT_DK_H, unselected_color=BG_INPUT,
                unselected_hover_color=BG_HOVER, text_color=FG_MAIN, font=F(12),
                command=lambda v: kind_var.set(
                    "template" if v.startswith("Estrutura") else "marketplace"))
            seg.set("Estrutura personalizada" if data["kind"] == "template"
                    else "Marketplace")
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

        estilo_mes = [dict(data.get("mes_estilo") or {})]

        _mp_campo(
            "ORGANIZAÇÃO POR ANO / MÊS",
            dest_var,
            "Como as pastas de ano e mês ficam dentro da base. Elas são criadas\n"
            "sozinhas quando não existem. Variáveis: {ano}  {mes} (09 - SETEMBRO)\n"
            "{mes_num} (09)  {mes_nome} (SETEMBRO). Vazio = clientes direto na base.")

        det_row = ctk.CTkFrame(mp_frame, fg_color="transparent")
        det_row.pack(fill="x", pady=(6, 0))
        btn_det = ctk.CTkButton(det_row, text="🔎 Detectar pelas pastas", height=28,
                                width=170, corner_radius=8, fg_color=BG_INPUT,
                                hover_color=BG_HOVER, text_color=FG_MAIN,
                                font=F(11))
        btn_det.pack(side="left")
        Tooltip(btn_det, "Olha as pastas que já existem na base e descobre\n"
                         "como você organiza ano e mês.")
        ctk.CTkLabel(det_row, text="ou use um modelo:", text_color=FG_DIM,
                     font=F(10)).pack(side="left", padx=(10, 4))
        preset_menu = ctk.CTkOptionMenu(
            det_row, values=[r for _p, r in PRESETS_PADRAO], width=210,
            height=28, fg_color=BG_INPUT, button_color=BG_HOVER,
            text_color=FG_LABEL, font=F(10), dropdown_fg_color=BG_CARD,
            command=lambda rot: _usa_preset(rot))
        preset_menu.set("Modelos de organização")
        preset_menu.pack(side="left")

        det_box = ctk.CTkFrame(mp_frame, fg_color="transparent")
        det_box.pack(fill="x")

        # prévia do caminho real, atualizada enquanto digita
        prev_dest = ctk.CTkLabel(mp_frame, text="", text_color=FG_DIM,
                                 font=F(10), justify="left", anchor="w",
                                 wraplength=470)
        prev_dest.pack(fill="x", pady=(4, 0))
        valida_lbl = ctk.CTkLabel(mp_frame, text="", text_color=FG_DIM,
                                  font=F(10), justify="left", anchor="w")
        valida_lbl.pack(fill="x")

        def _usa_preset(rotulo):
            preset_menu.set("Modelos de organização")
            for p, r in PRESETS_PADRAO:
                if r == rotulo:
                    dest_var.set(preset_para_grupo(
                        p, nome_var.get().strip() or "Grupo"))
                    estilo_mes[0] = {}

        def _usa_candidato(c):
            if c.get("base_diferente"):
                base_var.set(os.path.normpath(c["base"]))
            dest_var.set(c["pattern"])
            estilo_mes[0] = dict(c.get("estilo") or {})
            for w in det_box.winfo_children():
                w.destroy()

        def _mostra_candidatos(cands):
            btn_det.configure(state="normal", text="🔎 Detectar pelas pastas")
            for w in det_box.winfo_children():
                w.destroy()
            if isinstance(cands, dict) and cands.get("erro"):
                cands = []
            if not cands:
                ctk.CTkLabel(det_box, text="Não achei pastas de ano/mês na base. "
                                           "Escolha um modelo ao lado.",
                             text_color=FG_DIM, font=F(10)).pack(anchor="w",
                                                                 pady=(4, 0))
                return
            for c in cands[:3]:
                card = ctk.CTkFrame(det_box, fg_color=BG_NODE, corner_radius=8,
                                    border_width=1,
                                    border_color=SEQ_BD if c is cands[0]
                                    else BORDER)
                card.pack(fill="x", pady=(4, 0))
                anos = "–".join([c["anos"][0], c["anos"][-1]]) \
                    if len(c["anos"]) > 1 else (c["anos"][0] if c["anos"] else "")
                txt = (f"{c['pattern']}\n reconhece {c['meses']} mês(es)"
                       + (f" em {anos}" if anos else "")
                       + (f" · {c['fora']} pasta(s) fora do padrão"
                          if c["fora"] else ""))
                if c.get("base_diferente"):
                    txt += f"\n usando a pasta de cima: {c['base']}"
                ctk.CTkLabel(card, text=txt, text_color=FG_MAIN, font=F(11),
                             justify="left", anchor="w"
                             ).pack(side="left", padx=10, pady=6)
                ctk.CTkButton(card, text="Usar este", width=84, height=26,
                              corner_radius=8, fg_color=ACCENT,
                              hover_color=ACCENT_H, text_color=DARK_TXT,
                              font=F(11, True),
                              command=lambda c=c: _usa_candidato(c)
                              ).pack(side="right", padx=8)

        def _detectar(auto=False):
            base = base_var.get().strip()
            if not base or not os.path.isdir(base):
                if not auto:
                    messagebox.showinfo("Detectar",
                                        "Escolha a pasta base primeiro.",
                                        parent=win)
                return
            btn_det.configure(state="disabled", text="Lendo as pastas…")
            self.em_segundo_plano(lambda: detectar_padrao_mes(base),
                                  _mostra_candidatos)
        btn_det.configure(command=_detectar)

        _val_job = [None]

        def _valida():
            base, p = base_var.get().strip(), dest_var.get().strip()
            if not p or not base or not os.path.isdir(base):
                valida_lbl.configure(text="")
                return

            def pronto(r):
                if not valida_lbl.winfo_exists():
                    return
                if isinstance(r, dict) and "meses" in r:
                    n = len(r["meses"])
                    valida_lbl.configure(
                        text=(f"✓ reconhece {n} mês(es) que já existem"
                              if n else "nenhuma pasta existente segue este "
                                        "padrão ainda (tudo bem num grupo novo)"),
                        text_color=GREEN if n else FG_DIM)
            self.em_segundo_plano(lambda: analisar_padrao(base, p), pronto)

        def _upd_prev(*_a):
            b = (base_var.get() or "…").rstrip("\\/")
            agora = datetime.datetime.now()
            g_tmp = {"base_path": b, "dest_pattern": dest_var.get().strip(),
                     "mes_estilo": estilo_mes[0]}
            try:
                alvo = mp_destino(g_tmp, str(agora.year), MESES[agora.month - 1])
            except TemplateError:
                prev_dest.configure(
                    text="⚠ variável desconhecida — use {ano}, {mes}, {mes_num} "
                         "ou {mes_nome}", text_color=YELLOW)
                return
            prev_dest.configure(
                text=f"Neste mês, as pastas de cliente vão para:\n{alvo}",
                text_color=FG_LABEL)
            if _val_job[0]:
                try:
                    win.after_cancel(_val_job[0])
                except Exception:
                    pass
            _val_job[0] = win.after(600, _valida)
        dest_var.trace_add("write", _upd_prev)
        base_var.trace_add("write", _upd_prev)
        _upd_prev()

        _det_job = [None]

        def _base_mudou(*_a):
            # base nova e padrão vazio: tenta descobrir sozinho
            if kind_var.get() != "marketplace" or dest_var.get().strip():
                return
            if _det_job[0]:
                try:
                    win.after_cancel(_det_job[0])
                except Exception:
                    pass
            _det_job[0] = win.after(600, lambda: _detectar(auto=True))
        base_var.trace_add("write", _base_mudou)

        _mp_campo("PREFIXO DO CÓDIGO", prefix_var, "Ex.: A (Mercado Livre) — pode ficar vazio")
        _mp_campo("TRELLO — BOARD ID", board_var)
        _mp_campo("TRELLO — LISTA 'AGUARDANDO APROVAÇÃO' ID", aguard_var)
        _mp_campo("TRELLO — LISTA 'DESENVOLVIMENTO' ID (watcher)", dev_var)

        # nome provisório: vale para qualquer grupo (é o que a Conferência
        # usa para achar pastas que ainda não receberam o nome do cliente)
        prov_var = campo("NOME PROVISÓRIO DAS PASTAS (separe por vírgula)",
                         ", ".join(data.get("provisorios") or PROVISORIOS_PADRAO))

        # botões
        btns = ctk.CTkFrame(sc, fg_color="transparent")
        btns.pack(fill="x", pady=(18, 6))

        def _toggle_mp(*_):
            if kind_var.get() == "marketplace":
                mp_frame.pack(fill="x", before=btns)
                if novo and not dest_var.get().strip():
                    dest_var.set("{ano}/{mes}")     # já nasce organizado
                    _base_mudou()
            else:
                mp_frame.pack_forget()
        kind_var.trace_add("write", _toggle_mp)
        _toggle_mp()
        # grupo que já existe sem organização por ano/mês: sugere sozinho
        if (not novo and kind_var.get() == "marketplace"
                and not dest_var.get().strip()):
            win.after(400, lambda: _detectar(auto=True))

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
                "mes_estilo": estilo_mes[0],
                "prefix": prefix_var.get().strip().upper(),
                "board_id": board_var.get().strip(),
                "list_aguardando": aguard_var.get().strip(),
                "list_dev": dev_var.get().strip(),
                "provisorios": [p.strip() for p in prov_var.get().split(",")
                                if p.strip()] or list(PROVISORIOS_PADRAO),
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
                win.grab_release()
                win.destroy()
                self._delete_group(data)
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
                m = codigo_re_do_grupo(g).match(card_name)
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

            def pronto(boards):
                if not teste_lbl.winfo_exists():
                    return
                if isinstance(boards, dict):
                    teste_lbl.configure(text=f"❌ Erro: {boards.get('erro')}")
                    return
                nomes = ", ".join(b["name"] for b in boards[:3])
                teste_lbl.configure(text=f"✅ OK! Boards: {nomes}...")
            self.em_segundo_plano(lambda: trello_get_boards(key, token), pronto)

        trow = ctk.CTkFrame(sc, fg_color="transparent")
        trow.pack(anchor="w", pady=(4, 0))
        ctk.CTkButton(trow, text="🔌 Testar conexão", height=32, corner_radius=10,
                      fg_color=BG_INPUT, hover_color=BG_HOVER, text_color=FG_MAIN,
                      font=F(12), command=testar).pack(side="left")
        teste_lbl.pack(anchor="w", pady=(4, 0))

        secao("O QUE VOCÊ USA")
        usa_od_var = tk.BooleanVar(value=self.usa("onedrive"))
        usa_tr_var = tk.BooleanVar(value=self.usa("trello"))
        sw_a = make_switch(sc, text="Minhas pastas ficam no OneDrive",
                           variable=usa_od_var, progress_color=ACCENT,
                           text_color=FG_LABEL, font=F(12))
        sw_a.pack(anchor="w", pady=2)
        sw_b = make_switch(sc, text="Uso Trello junto com as pastas",
                           variable=usa_tr_var, progress_color=ACCENT,
                           text_color=FG_LABEL, font=F(12))
        sw_b.pack(anchor="w", pady=2)
        Tooltip(sw_b, "Desligado, some tudo de Trello da interface.\n"
                      "A mudança aparece ao reabrir a tela.")

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
                "usa_onedrive":     usa_od_var.get(),
                "usa_trello":       usa_tr_var.get(),
                "watcher_interval": iv,
                "github_repo":      repo_var.get().strip(),
            })
            self.save()
            self.aplica_preferencias()
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
def _tree_demo():
    """Banco de provas do componente de árvore, isolado do resto do app:
       python folderflow.py --tree-demo"""
    ctk.set_appearance_mode("dark")
    win = ctk.CTk(fg_color=BG_MAIN)
    win.title("TreeCanvas — banco de provas")
    win.geometry("900x640")

    # modelo sintético grande: 20 raízes × 20 filhos × 12 netos = 5.020 nós
    raizes = []
    for a in range(20):
        filhos = []
        for b in range(20):
            netos = [new_node("file", f"arquivo {c}.txt") for c in range(12)]
            f = new_node("folder", f"Pasta {a}-{b}")
            f["children"] = netos
            filhos.append(f)
        r = new_node("folder", f"Raiz {a}")
        r["children"] = filhos
        if a % 3 == 0:
            r["repeat"] = "200"
            r["name"] = f"Raiz {a} {{seq:04d}}"
        raizes.append(r)

    barra = ctk.CTkFrame(win, fg_color="transparent")
    barra.pack(fill="x", padx=12, pady=8)
    info = ctk.CTkLabel(barra, text="", text_color=FG_LABEL, font=F(11))
    info.pack(side="right")

    tree = TreeCanvas(win, multi=True)
    tree.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    tree.set_provider(TemplateTreeProvider(raizes))

    def _sel(rows):
        info.configure(text=f"{len(rows)} selecionado(s): "
                            f"{rows[0].label if rows else '—'}")

    def _ctx(row, sel):
        if row is None:
            return [("Nova pasta na raiz", lambda: None, True)]
        return [(f"Renomear '{row.label}'", lambda: tree.begin_edit(), True),
                None,
                ("Excluir", lambda: None, True)]

    def _ren(row, novo):
        row.payload["name"] = novo
        tree.reload()

    tree.on_select, tree.on_context, tree.on_rename = _sel, _ctx, _ren
    tree.on_action = lambda r, a: info.configure(text=f"ação '{a}' em {r.label}")

    def btn(txt, cmd):
        ctk.CTkButton(barra, text=txt, height=28, width=110, corner_radius=8,
                      fg_color=BG_INPUT, hover_color=BG_HOVER,
                      text_color=FG_LABEL, font=F(11), command=cmd
                      ).pack(side="left", padx=(0, 6))

    btn("Expandir tudo", lambda: tree.set_all_expanded(True))
    btn("Recolher tudo", lambda: tree.set_all_expanded(False))
    btn("Disco (C:\\)", lambda: tree.set_provider(DiskTreeProvider()))
    btn("Modelo", lambda: tree.set_provider(TemplateTreeProvider(raizes)))
    win.mainloop()


if __name__ == "__main__":
    if "--tree-demo" in sys.argv:
        _tree_demo()
    else:
        app = App()
        app.mainloop()
