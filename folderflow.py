import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import json
import re
import subprocess
import datetime
import time
import threading
import urllib.request
import urllib.parse
import sys

# ═══════════════════════════════════════════════════════════════════════════════
# VERSÃO E ARQUIVOS DE SUPORTE
# ═══════════════════════════════════════════════════════════════════════════════
APP_NAME    = "FolderFlow"
APP_VERSION = "1.1.0"

# Quando rodando como .exe (PyInstaller), salva config ao lado do .exe
# Quando rodando como .py, salva ao lado do script
if getattr(sys, "frozen", False):
    _DIR = os.path.dirname(sys.executable)
else:
    _DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(_DIR, "folderflow_config.json")
INDEX_FILE  = os.path.join(_DIR, "folderflow_index.json")

DEFAULT_CONFIG = {
    "shopee_base":           "",
    "ml_base":               "",
    "pause_onedrive":        True,
    "trello_key":            "",
    "trello_token":          "",
    "shopee_board_id":       "",
    "ml_board_id":           "",
    "shopee_list_aguardando": "",
    "ml_list_aguardando":    "",
    "shopee_list_dev_id":    "",
    "ml_list_dev_id":        "",
    "watcher_interval":      60,
    # Auto-update via GitHub Releases (formato: "usuario/FolderFlow")
    "github_repo":           "",
}

MESES = [
    "01 - JANEIRO", "02 - FEVEREIRO", "03 - MARÇO",
    "04 - ABRIL",   "05 - MAIO",      "06 - JUNHO",
    "07 - JULHO",   "08 - AGOSTO",    "09 - SETEMBRO",
    "10 - OUTUBRO", "11 - NOVEMBRO",  "12 - DEZEMBRO",
]

FOLDER_CODE_RE = re.compile(r'^(A?\d{6}[A-Z]+) - (.+)$')


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    return DEFAULT_CONFIG.copy()


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
# LÓGICA DE NEGÓCIO: PASTAS
# ═══════════════════════════════════════════════════════════════════════════════
def maior_numero_no_mes(pasta_mes: str, prefixo: str, mes_num: str) -> int:
    """Retorna o maior número sequencial já usado no mês, considerando apenas
    pastas no formato novo: [prefixo] + mes_num(2) + dígitos + iniciais.
    Pastas no formato antigo (sem prefixo de mês) são ignoradas para não
    contaminar o contador com valores de 5 dígitos do sistema legado."""
    maior = 0
    if not os.path.exists(pasta_mes):
        return 0
    # Extrai N dígitos entre o prefixo de mês e as iniciais finais
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


def _paths(plat, ano, mes, config):
    if plat == "shopee":
        base    = config["shopee_base"]
        destino = os.path.join(base, f"Shopee {ano}", f"{mes} - SHOPEE")
        prefixo = ""
    else:
        base    = config["ml_base"]
        destino = os.path.join(base, f"ML - {ano}", mes)
        prefixo = "A"
    return base, destino, prefixo


def criar_lote(plat, ano, mes, itens, config, log_fn, pause_od):
    base, destino, prefixo = _paths(plat, ano, mes, config)
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
                # Verifica se QUALQUER pasta com esse código já existe,
                # incluindo pastas que já foram renomeadas (não só "- Vazio")
                ja_existe = any(
                    f.split(" - ")[0].upper() == codigo.upper()
                    for f in os.listdir(destino)
                    if os.path.isdir(os.path.join(destino, f))
                )
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


def buscar_pasta_por_codigo(bases: list, codigo: str):
    codigo = codigo.strip().upper()
    for base in bases:
        if not os.path.exists(base):
            continue
        for root, dirs, _ in os.walk(base):
            for d in dirs:
                cod_pasta = d.split(" - ")[0].upper()
                if cod_pasta == codigo:
                    return os.path.join(root, d), d
    return None, None


def renomear_pasta(path_atual: str, nome_cliente: str) -> str:
    dir_pai    = os.path.dirname(path_atual)
    nome_atual = os.path.basename(path_atual)
    codigo     = nome_atual.split(" - ")[0]
    novo_nome  = f"{codigo} - {nome_cliente.strip()}"
    novo_path  = os.path.join(dir_pai, novo_nome)
    os.rename(path_atual, novo_path)
    return novo_path


# ═══════════════════════════════════════════════════════════════════════════════
# ÍNDICE LOCAL
# ═══════════════════════════════════════════════════════════════════════════════
def build_index(shopee_base: str, ml_base: str, progress_fn=None) -> dict:
    index = {}
    for plat, base in [("SHOPEE", shopee_base), ("ML", ml_base)]:
        if not os.path.exists(base):
            continue
        for root, dirs, _ in os.walk(base):
            for d in dirs:
                if " - " not in d:
                    continue
                codigo  = d.split(" - ")[0].upper()
                cliente = d.split(" - ", 1)[1] if " - " in d else ""
                index[codigo] = {
                    "path":    os.path.join(root, d),
                    "nome":    d,
                    "plat":    plat,
                    "cliente": cliente,
                }
                if progress_fn:
                    progress_fn(d)
    return index


def load_index() -> dict:
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_index(index: dict):
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# RELATÓRIO MENSAL
# ═══════════════════════════════════════════════════════════════════════════════
def gerar_relatorio(plat: str, ano: str, mes: str, config: dict) -> dict:
    _, destino, prefixo = _paths(plat, ano, mes, config)
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
        if is_vazio:
            resultado["vazio"] += 1
        else:
            resultado["com_cliente"] += 1
        if tem_arquivo:
            resultado["com_arquivo"] += 1
        else:
            resultado["sem_arquivo"] += 1
        if iniciais:
            resultado["por_pessoa"][iniciais] = resultado["por_pessoa"].get(iniciais, 0) + 1
        resultado["lista"].append({
            "codigo": codigo, "cliente": cliente,
            "vazio": is_vazio, "tem_arquivo": tem_arquivo,
        })
    return resultado


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


def trello_get_lists(board_id, key, token):
    return _trello_get(f"/boards/{board_id}/lists", key, token, {"fields": "name,id"})


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


def trello_configurado(cfg):
    return all(cfg.get(k) for k in ("trello_key", "trello_token",
                                    "shopee_board_id", "ml_board_id"))


# ═══════════════════════════════════════════════════════════════════════════════
# PALETA DE CORES E FONTES
# ═══════════════════════════════════════════════════════════════════════════════
BG_MAIN  = "#0d0d12"
BG_SIDE  = "#09090e"
BG_CARD  = "#13131c"
BG_INPUT = "#1a1a26"
YELLOW   = "#f5c518"
BLUE     = "#4f8fff"
RED      = "#ff4455"
GREEN    = "#22dd77"
CYAN     = "#00ccdd"
FG_MAIN  = "#eeeef5"
FG_DIM   = "#44445a"
FG_LABEL = "#7788aa"
SHOPEE_C = "#ff6b35"

FONT     = ("Segoe UI", 10)
FONT_SM  = ("Segoe UI", 9)
FONT_XS  = ("Segoe UI", 8)
FONT_B   = ("Segoe UI", 10, "bold")
FONT_H   = ("Segoe UI", 12, "bold")
FONT_NAV = ("Segoe UI", 10, "bold")
MONO     = ("Consolas", 9)


# ═══════════════════════════════════════════════════════════════════════════════
# AUTO-UPDATE via GitHub
# ═══════════════════════════════════════════════════════════════════════════════
def check_update(cfg, root):
    """Roda em background. Consulta a última Release do repositório no GitHub.
    Se houver versão nova, pergunta ao usuário (um clique) e atualiza sozinho."""
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
        if not latest or latest == APP_VERSION:
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
    """Baixa e aplica a atualização. Modo .exe: baixa o novo .exe da Release,
    troca os arquivos com um .bat auxiliar e reabre o programa. Modo .py:
    baixa o script direto do branch main."""
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
            # .bat que espera o app fechar, troca o .exe e reabre
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
# DIÁLOGO: SELECIONAR CARD DO TRELLO
# ═══════════════════════════════════════════════════════════════════════════════
def dialog_selecionar_card(parent, cards, list_names):
    """Mostra janela para selecionar card quando múltiplos são encontrados.
    Retorna o card selecionado ou None."""
    result = [None]

    win = tk.Toplevel(parent)
    win.title("Selecionar card do Trello")
    win.geometry("500x380")
    win.configure(bg=BG_MAIN)
    win.grab_set()
    win.resizable(False, False)

    tk.Label(win, text="Selecionar card do Trello",
             bg=BG_MAIN, fg=FG_MAIN, font=FONT_H).pack(padx=20, pady=(16, 4), anchor="w")
    tk.Label(win, text="Múltiplos cards encontrados. Selecione o correto:",
             bg=BG_MAIN, fg=FG_LABEL, font=FONT_SM).pack(padx=20, anchor="w")

    lb_frame = tk.Frame(win, bg=BG_CARD)
    lb_frame.pack(fill="both", expand=True, padx=20, pady=(10, 0))

    sb = tk.Scrollbar(lb_frame)
    sb.pack(side="right", fill="y")
    lb = tk.Listbox(lb_frame, bg=BG_CARD, fg=FG_MAIN, font=MONO,
                    selectbackground=YELLOW, selectforeground=BG_MAIN,
                    relief="flat", bd=0, yscrollcommand=sb.set, activestyle="none")
    lb.pack(fill="both", expand=True)
    sb.config(command=lb.yview)

    for c in cards:
        list_name = list_names.get(c.get("idList", ""), c.get("idList", ""))
        lb.insert("end", f"  [LISTA: {list_name}] {c['name']}")

    desc_var = tk.StringVar()
    desc_lbl = tk.Label(win, textvariable=desc_var, bg=BG_MAIN, fg=FG_LABEL,
                        font=FONT_XS, wraplength=460, justify="left", anchor="w")
    desc_lbl.pack(padx=20, pady=(6, 0), anchor="w")

    def on_select(event=None):
        sel = lb.curselection()
        if sel:
            desc = cards[sel[0]].get("desc", "")
            desc_var.set(desc[:120] if desc else "(sem descrição)")

    lb.bind("<<ListboxSelect>>", on_select)

    def confirmar():
        sel = lb.curselection()
        if not sel:
            return
        result[0] = cards[sel[0]]
        win.destroy()

    tk.Button(win, text="Confirmar", bg=YELLOW, fg=BG_MAIN, font=FONT_B,
              relief="flat", bd=0, padx=20, pady=8, cursor="hand2",
              command=confirmar).pack(pady=12)

    win.wait_window()
    return result[0]


# ═══════════════════════════════════════════════════════════════════════════════
# CLASSE PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.config_data    = load_config()
        self.index_data     = load_index()
        self.watcher_active = False
        self.watcher_thread = None
        self._watcher_processed = set()

        self.title(f"{APP_NAME} v{APP_VERSION}")
        # Verifica atualizações em background após 3 segundos
        self.after(3000, lambda: threading.Thread(
            target=check_update, args=(self.config_data, self), daemon=True
        ).start())
        self.geometry("720x780")
        self.resizable(False, False)
        self.configure(bg=BG_MAIN)

        self._setup_styles()
        self._build_ui()

        # Primeiro uso: pede para configurar os caminhos das pastas
        if not self.config_data.get("shopee_base") and not self.config_data.get("ml_base"):
            self.after(400, self._primeiro_uso)

    def _primeiro_uso(self):
        messagebox.showinfo(
            "Bem-vindo ao FolderFlow!",
            "Primeiro uso detectado.\n\n"
            "Configure os caminhos das pastas base\n"
            "(Shopee e Mercado Livre) para começar.")
        self._open_config()

    # ── Estilos ttk ──────────────────────────────────────────────────────────
    def _setup_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TCombobox",
                    fieldbackground=BG_INPUT, background=BG_INPUT,
                    foreground=FG_MAIN, selectbackground=YELLOW, arrowcolor=FG_LABEL)
        s.map("TCombobox", fieldbackground=[("readonly", BG_INPUT)])

    # ── Layout raiz ──────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        self._build_header()

        # Corpo: sidebar + conteúdo
        body = tk.Frame(self, bg=BG_MAIN)
        body.pack(fill="both", expand=True)

        sidebar = tk.Frame(body, bg=BG_SIDE, width=170)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        self._content = tk.Frame(body, bg=BG_MAIN)
        self._content.pack(side="left", fill="both", expand=True)

        self._nav_items   = {}
        self._nav_buttons = {}
        self._panels      = {}
        self._active_nav  = [None]

        nav_defs = [
            ("criar",     "＋ CRIAR",    "Shopee / Mercado Livre"),
            ("renomear",  "✎ RENOMEAR",  "Pasta + Trello"),
            ("buscar",    "⊙ BUSCAR",    "Índice local"),
            ("relatorio", "≡ RELATÓRIO", "Estatísticas do mês"),
        ]

        for key, title, subtitle in nav_defs:
            self._build_nav_item(sidebar, key, title, subtitle)
            panel = tk.Frame(self._content, bg=BG_MAIN)
            self._panels[key] = panel

        self._build_criar(self._panels["criar"])
        self._build_renomear(self._panels["renomear"])
        self._build_buscar(self._panels["buscar"])
        self._build_relatorio(self._panels["relatorio"])

        self._nav_switch("criar")

    # ── Header ───────────────────────────────────────────────────────────────
    def _build_header(self):
        hdr = tk.Frame(self, bg=BG_CARD, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        left = tk.Frame(hdr, bg=BG_CARD)
        left.pack(side="left", padx=16, pady=10)
        tk.Label(left, text=APP_NAME.upper(), bg=BG_CARD, fg=YELLOW,
                 font=FONT_B).pack(side="left")
        tk.Label(left, text=" // ", bg=BG_CARD, fg=FG_DIM,
                 font=FONT_B).pack(side="left")
        tk.Label(left, text="GESTÃO DE PASTAS", bg=BG_CARD, fg=FG_MAIN,
                 font=FONT).pack(side="left")
        tk.Label(left, text=f"  v{APP_VERSION}", bg=BG_CARD, fg=FG_DIM,
                 font=FONT_XS).pack(side="left")

        right = tk.Frame(hdr, bg=BG_CARD)
        right.pack(side="right", padx=12, pady=8)

        tk.Button(right, text="⚙", bg=BG_CARD, fg=FG_LABEL, font=FONT_B,
                  bd=0, cursor="hand2", activebackground=BG_CARD,
                  activeforeground=FG_MAIN,
                  command=self._open_config).pack(side="right", padx=(6, 0))

        tk.Button(right, text="ⓘ", bg=BG_CARD, fg=FG_LABEL, font=FONT_B,
                  bd=0, cursor="hand2", activebackground=BG_CARD,
                  activeforeground=FG_MAIN,
                  command=self._open_sobre).pack(side="right", padx=(0, 4))

    def _update_watcher_header(self):
        if self.watcher_active:
            self._watcher_btn_var.set("● ATIVO")
            self._watcher_btn.configure(fg=GREEN)
        else:
            self._watcher_btn_var.set("○ OFF")
            self._watcher_btn.configure(fg=FG_DIM)

    def _toggle_watcher_header(self):
        if self.watcher_active:
            self._stop_watcher()
        else:
            self._start_watcher()
        self._update_watcher_header()
        self._refresh_watcher_panel()

    # ── Navegação lateral ─────────────────────────────────────────────────────
    def _build_nav_item(self, sidebar, key, title, subtitle):
        item = tk.Frame(sidebar, bg=BG_SIDE, cursor="hand2")
        item.pack(fill="x")

        border = tk.Frame(item, bg=BG_SIDE, width=4)
        border.pack(side="left", fill="y")

        inner = tk.Frame(item, bg=BG_SIDE)
        inner.pack(side="left", fill="x", expand=True, padx=(10, 12), pady=10)

        lbl_title = tk.Label(inner, text=title, bg=BG_SIDE, fg=FG_MAIN,
                             font=(FONT_NAV[0], 11, "bold"), anchor="w")
        lbl_title.pack(fill="x")
        lbl_sub = tk.Label(inner, text=subtitle, bg=BG_SIDE, fg=FG_DIM,
                           font=FONT_XS, anchor="w")
        lbl_sub.pack(fill="x")

        sep = tk.Frame(sidebar, bg=FG_DIM, height=1)
        sep.pack(fill="x")

        self._nav_buttons[key] = {"border": border, "item": item,
                                  "lbl_title": lbl_title, "lbl_sub": lbl_sub}

        for widget in (item, inner, lbl_title, lbl_sub):
            widget.bind("<Button-1>", lambda e, k=key: self._nav_switch(k))

    def _nav_switch(self, key):
        prev = self._active_nav[0]
        if prev and prev in self._panels:
            self._panels[prev].pack_forget()
            btn = self._nav_buttons[prev]
            btn["border"].configure(bg=BG_SIDE)
            btn["item"].configure(bg=BG_SIDE)
            btn["lbl_title"].configure(bg=BG_SIDE, fg=FG_MAIN)
            btn["lbl_sub"].configure(bg=BG_SIDE, fg=FG_DIM)

        self._active_nav[0] = key
        self._panels[key].pack(fill="both", expand=True)
        btn = self._nav_buttons[key]
        btn["border"].configure(bg=YELLOW)
        btn["item"].configure(bg=BG_CARD)
        btn["lbl_title"].configure(bg=BG_CARD, fg=YELLOW)
        btn["lbl_sub"].configure(bg=BG_CARD, fg=FG_LABEL)

    # ═════════════════════════════════════════════════════════════════════════
    # PAINEL: CRIAR PASTAS
    # ═════════════════════════════════════════════════════════════════════════
    def _build_criar(self, parent):
        wrap = tk.Frame(parent, bg=BG_MAIN)
        wrap.pack(fill="both", expand=True, padx=20, pady=14)

        # Seletor de plataforma (pill buttons)
        plat_state = {"active": "shopee"}

        pill_frame = tk.Frame(wrap, bg=BG_MAIN)
        pill_frame.pack(anchor="w", pady=(0, 2))

        btn_shopee = tk.Button(pill_frame, text="🟠 SHOPEE", font=FONT_B,
                               relief="flat", bd=0, padx=16, pady=7, cursor="hand2")
        btn_shopee.pack(side="left", padx=(0, 4))
        btn_ml = tk.Button(pill_frame, text="🔵 MERCADO LIVRE", font=FONT_B,
                           relief="flat", bd=0, padx=16, pady=7, cursor="hand2")
        btn_ml.pack(side="left")

        bar = tk.Frame(wrap, height=3)
        bar.pack(fill="x", pady=(0, 12))

        def set_plat(p):
            plat_state["active"] = p
            if p == "shopee":
                btn_shopee.configure(bg=SHOPEE_C, fg="white")
                btn_ml.configure(bg=BG_INPUT, fg=FG_LABEL)
                bar.configure(bg=SHOPEE_C)
            else:
                btn_shopee.configure(bg=BG_INPUT, fg=FG_LABEL)
                btn_ml.configure(bg=BLUE, fg="white")
                bar.configure(bg=BLUE)

        btn_shopee.configure(command=lambda: set_plat("shopee"))
        btn_ml.configure(command=lambda: set_plat("ml"))
        set_plat("shopee")

        # Ano + Mês
        date_row = tk.Frame(wrap, bg=BG_MAIN)
        date_row.pack(fill="x", pady=(0, 10))

        ano_f = tk.Frame(date_row, bg=BG_MAIN)
        ano_f.pack(side="left", padx=(0, 20))
        tk.Label(ano_f, text="ANO", bg=BG_MAIN, fg=FG_LABEL, font=FONT_SM).pack(anchor="w", pady=(0, 3))
        ano_var = tk.StringVar(value=str(datetime.datetime.now().year))
        ttk.Combobox(ano_f, textvariable=ano_var,
                     values=[str(y) for y in range(2024, 2032)],
                     state="readonly", width=9, font=FONT).pack(anchor="w")

        mes_f = tk.Frame(date_row, bg=BG_MAIN)
        mes_f.pack(side="left")
        tk.Label(mes_f, text="MÊS", bg=BG_MAIN, fg=FG_LABEL, font=FONT_SM).pack(anchor="w", pady=(0, 3))
        mes_var = tk.StringVar(value=MESES[datetime.datetime.now().month - 1])
        ttk.Combobox(mes_f, textvariable=mes_var, values=MESES,
                     state="readonly", width=22, font=FONT).pack(anchor="w")

        tk.Frame(wrap, bg=FG_DIM, height=1).pack(fill="x", pady=(6, 10))

        # Cabeçalho das colunas
        hdr_row = tk.Frame(wrap, bg=BG_MAIN)
        hdr_row.pack(fill="x", pady=(0, 4))
        tk.Label(hdr_row, text="RESPONSÁVEL", bg=BG_MAIN, fg=FG_LABEL,
                 font=FONT_SM, width=14, anchor="w").pack(side="left")
        tk.Label(hdr_row, text="QUANTIDADE", bg=BG_MAIN, fg=FG_LABEL,
                 font=FONT_SM, width=10, anchor="w").pack(side="left")

        linhas_frame = tk.Frame(wrap, bg=BG_MAIN)
        linhas_frame.pack(fill="x")
        pessoas = []

        def add_linha(resp="", qtd="1"):
            row     = tk.Frame(linhas_frame, bg=BG_MAIN, pady=3)
            row.pack(fill="x")
            rv      = tk.StringVar(value=resp)
            qv      = tk.StringVar(value=qtd)
            re_w    = tk.Entry(row, textvariable=rv, width=12,
                               bg=BG_INPUT, fg=FG_MAIN, insertbackground=FG_MAIN,
                               font=FONT, relief="flat", bd=5)
            re_w.pack(side="left", padx=(0, 8))
            tk.Entry(row, textvariable=qv, width=8,
                     bg=BG_INPUT, fg=FG_MAIN, insertbackground=FG_MAIN,
                     font=FONT, relief="flat", bd=5).pack(side="left", padx=(0, 8))
            item = {"resp": rv, "qtd": qv, "frame": row}

            def remover(i=item):
                if len(pessoas) > 1:
                    i["frame"].destroy()
                    pessoas.remove(i)

            tk.Button(row, text="✕", command=remover, bg=BG_MAIN, fg=RED,
                      font=("Segoe UI", 9, "bold"), bd=0, cursor="hand2",
                      activebackground=BG_MAIN, activeforeground="#ff6060").pack(side="left")
            pessoas.append(item)
            re_w.focus_set()

        add_linha()

        tk.Button(wrap, text="＋ Adicionar pessoa", command=add_linha,
                  bg=BG_MAIN, fg=YELLOW, font=FONT_SM, bd=0, cursor="hand2",
                  activebackground=BG_MAIN, activeforeground=FG_MAIN
                  ).pack(anchor="w", pady=(6, 0))

        tk.Frame(wrap, bg=FG_DIM, height=1).pack(fill="x", pady=(10, 8))

        pause_var = tk.BooleanVar(value=self.config_data.get("pause_onedrive", True))
        tk.Checkbutton(wrap, text="Pausar OneDrive durante criação (mais rápido)",
                       variable=pause_var, bg=BG_MAIN, fg=FG_LABEL,
                       selectcolor=BG_INPUT, activebackground=BG_MAIN,
                       font=FONT_SM).pack(anchor="w")

        tk.Label(wrap, text="LOG", bg=BG_MAIN, fg=FG_LABEL, font=FONT_SM
                 ).pack(anchor="w", pady=(10, 3))
        log_box = tk.Text(wrap, height=6, bg=BG_CARD, fg=CYAN,
                          font=MONO, state="disabled", relief="flat", bd=0)
        log_box.pack(fill="x")
        log_box.tag_config("ok",    foreground=GREEN)
        log_box.tag_config("aviso", foreground=YELLOW)
        log_box.tag_config("erro",  foreground=RED)
        log_box.tag_config("dim",   foreground=FG_LABEL)

        def log_criar(msg, erro=False, aviso=False, ok=False):
            log_box.configure(state="normal")
            tag = "erro" if erro else "aviso" if aviso else "ok" if ok else "dim"
            log_box.insert("end", f"[{datetime.datetime.now():%H:%M:%S}] {msg}\n", tag)
            log_box.see("end")
            log_box.configure(state="disabled")
            log_box.update()

        btn_criar = tk.Button(wrap, text="✅  CRIAR PASTAS",
                              font=("Segoe UI", 11, "bold"),
                              relief="flat", bd=0, pady=12, cursor="hand2")
        btn_criar.pack(fill="x", pady=(10, 2))

        def _atualizar_cor_btn():
            p = plat_state["active"]
            if p == "shopee":
                btn_criar.configure(bg=SHOPEE_C, fg="white")
            else:
                btn_criar.configure(bg=BLUE, fg="white")

        _atualizar_cor_btn()

        # Reconfigura botão ao trocar plataforma
        orig_shopee = btn_shopee["command"]
        orig_ml     = btn_ml["command"]
        btn_shopee.configure(command=lambda: [set_plat("shopee"), _atualizar_cor_btn()])
        btn_ml.configure(command=lambda: [set_plat("ml"), _atualizar_cor_btn()])

        def _iniciar():
            plat = plat_state["active"]
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
            if not messagebox.askyesno("Confirmar criação",
                                       f"Plataforma: {plat.upper()}\n"
                                       f"Mês: {mes_var.get()} / {ano_var.get()}\n\n"
                                       f"{resumo}\n\nTotal: {total} pasta(s). Confirma?"):
                return

            btn_criar.configure(state="disabled", text="Criando...",
                                bg=FG_DIM, fg=FG_MAIN)

            def task():
                try:
                    n = criar_lote(plat=plat, ano=ano_var.get(), mes=mes_var.get(),
                                   itens=itens, config=self.config_data,
                                   log_fn=log_criar, pause_od=pause_var.get())
                    log_criar(f"{n} pasta(s) criada(s) com sucesso!", ok=True)
                except Exception as e:
                    log_criar(f"ERRO: {e}", erro=True)
                finally:
                    btn_criar.configure(state="normal", text="✅  CRIAR PASTAS")
                    _atualizar_cor_btn()

            threading.Thread(target=task, daemon=True).start()

        btn_criar.configure(command=_iniciar)

    # ═════════════════════════════════════════════════════════════════════════
    # PAINEL: RENOMEAR
    # ═════════════════════════════════════════════════════════════════════════
    def _build_renomear(self, parent):
        wrap = tk.Frame(parent, bg=BG_MAIN)
        wrap.pack(fill="both", expand=True, padx=24, pady=16)

        # ── Código ───────────────────────────────────────────────────────────
        tk.Label(wrap, text="CÓDIGO DA PASTA", bg=BG_MAIN, fg=FG_LABEL,
                 font=FONT_SM).pack(anchor="w", pady=(0, 3))
        cod_row = tk.Frame(wrap, bg=BG_MAIN)
        cod_row.pack(fill="x")
        cod_var = tk.StringVar()
        tk.Entry(cod_row, textvariable=cod_var, width=16,
                 bg=BG_INPUT, fg=FG_MAIN, insertbackground=FG_MAIN,
                 font=FONT, relief="flat", bd=5).pack(side="left", padx=(0, 8))
        btn_localizar = tk.Button(cod_row, text="🔍 Localizar", bg=BG_INPUT, fg=FG_MAIN,
                                  font=FONT_SM, relief="flat", bd=0, padx=10, pady=5,
                                  cursor="hand2")
        btn_localizar.pack(side="left")

        status_loc_var = tk.StringVar()
        lbl_loc = tk.Label(wrap, textvariable=status_loc_var,
                           bg=BG_MAIN, fg=FG_DIM, font=FONT_SM,
                           wraplength=500, justify="left")
        lbl_loc.pack(anchor="w", pady=(6, 0))

        tk.Frame(wrap, bg=FG_DIM, height=1).pack(fill="x", pady=(12, 12))

        # ── Nome do cliente ───────────────────────────────────────────────────
        tk.Label(wrap, text="NOME DO CLIENTE", bg=BG_MAIN, fg=FG_LABEL,
                 font=FONT_SM).pack(anchor="w", pady=(0, 3))
        nome_var = tk.StringVar()
        nome_entry = tk.Entry(wrap, textvariable=nome_var, width=34,
                              bg=BG_INPUT, fg=FG_MAIN, insertbackground=FG_MAIN,
                              font=FONT, relief="flat", bd=5)
        nome_entry.pack(anchor="w")

        tk.Frame(wrap, bg=FG_DIM, height=1).pack(fill="x", pady=(12, 8))

        # ── Trello ────────────────────────────────────────────────────────────
        trello_ok = trello_configurado(self.config_data)

        usar_trello = tk.BooleanVar(value=trello_ok)
        tk.Checkbutton(wrap, text="Atualizar card no Trello",
                       variable=usar_trello,
                       state="normal" if trello_ok else "disabled",
                       bg=BG_MAIN, fg=FG_LABEL if trello_ok else FG_DIM,
                       selectcolor=BG_INPUT, activebackground=BG_MAIN,
                       font=FONT_SM).pack(anchor="w")

        mover_var = tk.BooleanVar(value=trello_ok)
        tk.Checkbutton(wrap, text="Mover para Aguardando Aprovação",
                       variable=mover_var,
                       state="normal" if trello_ok else "disabled",
                       bg=BG_MAIN, fg=FG_LABEL if trello_ok else FG_DIM,
                       selectcolor=BG_INPUT, activebackground=BG_MAIN,
                       font=FONT_SM).pack(anchor="w", pady=(2, 0))

        if not trello_ok:
            tk.Label(wrap, text="Configure a API do Trello em ⚙ Config para ativar.",
                     bg=BG_MAIN, fg=FG_DIM, font=FONT_XS).pack(anchor="w", padx=4)

        card_info_var = tk.StringVar()
        card_lbl = tk.Label(wrap, textvariable=card_info_var,
                            bg=BG_MAIN, fg=FG_DIM, font=FONT_SM, justify="left")
        card_lbl.pack(anchor="w", pady=(4, 0))

        # ── Botão + Status ────────────────────────────────────────────────────
        btn_renomear = tk.Button(wrap, text="✏ RENOMEAR",
                                 bg=YELLOW, fg=BG_MAIN, font=FONT_B,
                                 relief="flat", bd=0, pady=10, cursor="hand2",
                                 state="disabled")
        btn_renomear.pack(fill="x", pady=(14, 0))

        status_ren_var = tk.StringVar()
        lbl_ren_status = tk.Label(wrap, textvariable=status_ren_var,
                                  bg=BG_MAIN, font=FONT_SM,
                                  wraplength=500, justify="left")
        lbl_ren_status.pack(anchor="w", pady=(6, 0))

        # Aviso OneDrive
        aviso_frame = tk.Frame(wrap, bg="#1a1200")
        aviso_frame.pack(fill="x", pady=(14, 0))
        tk.Label(aviso_frame,
                 text="⚠ Se não sincronizar entre PCs, use o site do OneDrive",
                 bg="#1a1200", fg=YELLOW, font=FONT_XS
                 ).pack(padx=10, pady=6, anchor="w")

        # ── Estado interno ─────────────────────────────────────────────────
        path_encontrado  = [None]
        cards_encontrados = [[]]
        card_selecionado  = [None]

        def localizar():
            codigo = cod_var.get().strip().upper()
            if not codigo:
                messagebox.showwarning("Atenção", "Digite o código da pasta.")
                return
            status_loc_var.set("Buscando pasta...")
            lbl_loc.configure(fg=FG_DIM)
            btn_localizar.configure(state="disabled")
            btn_renomear.configure(state="disabled")
            path_encontrado[0]  = None
            card_info_var.set("")
            card_selecionado[0] = None

            bases = [self.config_data["shopee_base"], self.config_data["ml_base"]]

            def task():
                # Tenta o índice local primeiro (instantâneo); se não achar
                # ou o caminho tiver mudado, faz a varredura completa
                path, nome = None, None
                info = self.index_data.get(codigo)
                if info and os.path.exists(info["path"]):
                    path, nome = info["path"], info["nome"]
                else:
                    path, nome = buscar_pasta_por_codigo(bases, codigo)
                if path:
                    path_encontrado[0] = path
                    status_loc_var.set(f"Encontrada: {nome}")
                    lbl_loc.configure(fg=GREEN)
                    btn_renomear.configure(state="normal")
                else:
                    status_loc_var.set(f"Pasta '{codigo}' não encontrada.")
                    lbl_loc.configure(fg=RED)
                btn_localizar.configure(state="normal")

            threading.Thread(target=task, daemon=True).start()

        def buscar_card_async(nome_cliente):
            if not usar_trello.get() or not trello_configurado(self.config_data):
                return
            cfg  = self.config_data
            path = path_encontrado[0] or ""
            board_id = (cfg["shopee_board_id"]
                        if cfg["shopee_base"] in path else cfg["ml_board_id"])
            if not board_id:
                return
            card_info_var.set("buscando...")
            card_lbl.configure(fg=FG_DIM)
            cards_encontrados[0] = []
            card_selecionado[0]  = None

            def task():
                try:
                    cards = trello_search_cards(nome_cliente, board_id,
                                                cfg["trello_key"], cfg["trello_token"])
                    cards_encontrados[0] = cards
                    if len(cards) == 1:
                        card_selecionado[0] = cards[0]
                        card_info_var.set(f"Card: {cards[0]['name']}")
                        card_lbl.configure(fg=GREEN)
                    elif len(cards) > 1:
                        card_info_var.set(f"{len(cards)} cards encontrados — clique para selecionar")
                        card_lbl.configure(fg=YELLOW, cursor="hand2")
                        card_lbl.bind("<Button-1>", lambda e: _selecionar_card_ui())
                    else:
                        card_info_var.set("Nenhum card encontrado com esse nome.")
                        card_lbl.configure(fg=YELLOW)
                except Exception as ex:
                    card_info_var.set(f"Erro Trello: {ex}")
                    card_lbl.configure(fg=RED)

            threading.Thread(target=task, daemon=True).start()

        def _selecionar_card_ui():
            cards = cards_encontrados[0]
            if not cards:
                return
            cfg = self.config_data
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
                card_selecionado[0] = chosen
                card_info_var.set(f"Card: {chosen['name']}")
                card_lbl.configure(fg=GREEN)

        nome_var.trace_add("write", lambda *_: (
            buscar_card_async(nome_var.get().strip())
            if usar_trello.get() and len(nome_var.get().strip()) >= 3
            else None
        ))

        def renomear():
            nome = nome_var.get().strip()
            if not nome:
                messagebox.showwarning("Atenção", "Digite o nome do cliente.")
                return
            if not path_encontrado[0]:
                messagebox.showerror("Erro", "Localize a pasta primeiro.")
                return

            nome_atual   = os.path.basename(path_encontrado[0])
            codigo_pasta = nome_atual.split(" - ")[0]

            confirmacao = (f"Renomear:\n  {nome_atual}\npara:\n  {codigo_pasta} - {nome}")
            if not messagebox.askyesno("Confirmar", confirmacao + "\n\nConfirma?"):
                return

            btn_renomear.configure(state="disabled", text="Processando...")

            def task():
                erros = []
                try:
                    novo_path = renomear_pasta(path_encontrado[0], nome)
                    path_encontrado[0] = novo_path
                    status_loc_var.set(f"Pasta: {os.path.basename(novo_path)}")
                    lbl_loc.configure(fg=GREEN)
                    k = os.path.basename(novo_path).split(" - ")[0].upper()
                    self.index_data[k] = {
                        "path": novo_path, "nome": os.path.basename(novo_path),
                        "cliente": nome,
                        "plat": ("SHOPEE" if self.config_data["shopee_base"] in novo_path
                                 else "ML"),
                    }
                    save_index(self.index_data)
                except Exception as e:
                    erros.append(f"Pasta: {e}")

                if usar_trello.get() and trello_configurado(self.config_data):
                    cfg  = self.config_data
                    card = card_selecionado[0]
                    if card:
                        try:
                            novo_titulo = f"{codigo_pasta} - {card['name']}"
                            trello_update_card_name(card["id"], novo_titulo,
                                                    cfg["trello_key"], cfg["trello_token"])
                            card_info_var.set(f"Trello atualizado: {novo_titulo}")
                            card_lbl.configure(fg=GREEN)
                        except Exception as e:
                            erros.append(f"Trello (título): {e}")

                        if mover_var.get():
                            path_atual = path_encontrado[0] or ""
                            list_id = (cfg["shopee_list_aguardando"]
                                       if cfg["shopee_base"] in path_atual
                                       else cfg["ml_list_aguardando"])
                            if list_id:
                                try:
                                    trello_move_card(card["id"], list_id,
                                                     cfg["trello_key"], cfg["trello_token"])
                                except Exception as e:
                                    erros.append(f"Trello (mover): {e}")
                            else:
                                erros.append("ID da lista Aguardando não configurado.")
                    else:
                        erros.append("Card do Trello não identificado — atualize manualmente.")

                if erros:
                    status_ren_var.set("⚠ " + " | ".join(erros))
                    lbl_ren_status.configure(fg=YELLOW)
                else:
                    status_ren_var.set("Concluído com sucesso!")
                    lbl_ren_status.configure(fg=GREEN)

                btn_renomear.configure(state="normal", text="✏ RENOMEAR")

            threading.Thread(target=task, daemon=True).start()

        btn_localizar.configure(command=localizar)
        btn_renomear.configure(command=renomear)

    # ═════════════════════════════════════════════════════════════════════════
    # PAINEL: BUSCAR
    # ═════════════════════════════════════════════════════════════════════════
    def _build_buscar(self, parent):
        wrap = tk.Frame(parent, bg=BG_MAIN)
        wrap.pack(fill="both", expand=True, padx=20, pady=14)

        idx_count = len(self.index_data)
        idx_var   = tk.StringVar(
            value=(f"Índice local: {idx_count} pastas indexadas"
                   if idx_count else "Índice não gerado. Clique em 'Atualizar Índice'."))

        top_row = tk.Frame(wrap, bg=BG_MAIN)
        top_row.pack(fill="x", pady=(0, 4))
        tk.Label(top_row, textvariable=idx_var, bg=BG_MAIN, fg=FG_DIM,
                 font=FONT_SM).pack(side="left")
        btn_idx = tk.Button(top_row, text="🔄 Atualizar Índice",
                            bg=BG_INPUT, fg=FG_MAIN, font=FONT_SM,
                            relief="flat", bd=0, padx=12, pady=4, cursor="hand2")
        btn_idx.pack(side="right")

        tk.Frame(wrap, bg=FG_DIM, height=1).pack(fill="x", pady=(6, 10))

        tk.Label(wrap, text="BUSCAR POR CÓDIGO OU NOME", bg=BG_MAIN, fg=FG_LABEL,
                 font=FONT_SM).pack(anchor="w", pady=(0, 3))
        busca_row = tk.Frame(wrap, bg=BG_MAIN)
        busca_row.pack(fill="x")
        busca_var   = tk.StringVar()
        busca_entry = tk.Entry(busca_row, textvariable=busca_var, width=26,
                               bg=BG_INPUT, fg=FG_MAIN, insertbackground=FG_MAIN,
                               font=FONT, relief="flat", bd=5)
        busca_entry.pack(side="left", padx=(0, 8))
        tk.Button(busca_row, text="Buscar", bg=BLUE, fg=FG_MAIN,
                  font=FONT_SM, relief="flat", bd=0, padx=12, pady=5,
                  cursor="hand2", command=lambda: _buscar()
                  ).pack(side="left")

        res_frame = tk.Frame(wrap, bg=BG_CARD)
        res_frame.pack(fill="both", expand=True, pady=(10, 0))
        sb = tk.Scrollbar(res_frame)
        sb.pack(side="right", fill="y")
        listbox = tk.Listbox(res_frame, bg=BG_CARD, fg=FG_MAIN, font=MONO,
                             selectbackground=BLUE, selectforeground=FG_MAIN,
                             relief="flat", bd=0, yscrollcommand=sb.set,
                             activestyle="none")
        listbox.pack(fill="both", expand=True)
        sb.config(command=listbox.yview)

        resultados_paths = []
        res_count_var = tk.StringVar()
        tk.Label(wrap, textvariable=res_count_var, bg=BG_MAIN, fg=FG_DIM,
                 font=FONT_XS).pack(anchor="w", pady=(3, 0))

        def _buscar():
            termo = busca_var.get().strip().upper()
            listbox.delete(0, "end")
            resultados_paths.clear()
            res_count_var.set("")
            if not termo:
                return
            if not self.index_data:
                listbox.insert("end", "  Índice vazio. Clique em 'Atualizar Índice'.")
                return
            for cod, info in self.index_data.items():
                if termo in cod or termo in info.get("cliente", "").upper():
                    listbox.insert("end", f"  [{info['plat']}]  {info['nome']}")
                    resultados_paths.append(info["path"])
            if not resultados_paths:
                listbox.insert("end", "  Nenhum resultado encontrado.")
            else:
                res_count_var.set(f"{len(resultados_paths)} resultado(s)")

        # Busca automática enquanto digita (a partir de 2 caracteres)
        _busca_after = [None]
        def _busca_live(*_):
            if _busca_after[0]:
                self.after_cancel(_busca_after[0])
            termo = busca_var.get().strip()
            if len(termo) >= 2:
                _busca_after[0] = self.after(300, _buscar)

        # Opção: mesma janela ou nova janela
        opcao_row = tk.Frame(wrap, bg=BG_MAIN)
        opcao_row.pack(anchor="w", pady=(4, 2))
        mesma_janela = tk.BooleanVar(value=True)
        tk.Checkbutton(opcao_row,
                       text="Abrir na mesma janela do Explorador",
                       variable=mesma_janela,
                       bg=BG_MAIN, fg=FG_LABEL, selectcolor=BG_INPUT,
                       activebackground=BG_MAIN, activeforeground=FG_MAIN,
                       font=FONT_SM).pack(side="left")

        def _abrir(event=None):
            sel = listbox.curselection()
            if not sel or sel[0] >= len(resultados_paths):
                return
            path = resultados_paths[sel[0]]
            if not os.path.exists(path):
                messagebox.showwarning("Pasta não encontrada",
                                       f"O caminho não existe mais:\n{path}\n\nAtualize o índice.")
                return
            if mesma_janela.get():
                # Navega a janela do Explorador já aberta via COM (PowerShell)
                # Se não houver janela aberta, abre uma nova automaticamente
                ps = (
                    f'$path = "{path}";'
                    f'$shell = New-Object -ComObject Shell.Application;'
                    f'$wins = @($shell.Windows());'
                    f'if ($wins.Count -gt 0) {{ $wins[0].Navigate($path) }}'
                    f'else {{ explorer $path }}'
                )
                subprocess.Popen(
                    ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            else:
                # Abre sempre em nova janela
                subprocess.Popen(["explorer", path])

        listbox.bind("<Double-Button-1>", _abrir)
        busca_entry.bind("<Return>", lambda e: _buscar())
        busca_var.trace_add("write", _busca_live)

        tk.Button(wrap, text="📂 Abrir pasta", bg=BG_INPUT, fg=FG_MAIN,
                  font=FONT_SM, relief="flat", bd=0, padx=12, pady=5,
                  cursor="hand2", command=_abrir).pack(anchor="w", pady=(4, 0))

        def _atualizar_indice():
            btn_idx.configure(state="disabled", text="Indexando...")
            idx_var.set("Indexando pastas... aguarde.")

            def task():
                try:
                    idx = build_index(
                        self.config_data["shopee_base"],
                        self.config_data["ml_base"],
                        progress_fn=lambda d: idx_var.set(f"Indexando: {d[:38]}...")
                    )
                    save_index(idx)
                    self.index_data = idx
                    idx_var.set(f"Índice atualizado: {len(idx)} pastas indexadas.")
                except Exception as e:
                    idx_var.set(f"ERRO ao indexar: {e}")
                finally:
                    btn_idx.configure(state="normal", text="🔄 Atualizar Índice")

            threading.Thread(target=task, daemon=True).start()

        btn_idx.configure(command=_atualizar_indice)

    # ═════════════════════════════════════════════════════════════════════════
    # PAINEL: RELATÓRIO
    # ═════════════════════════════════════════════════════════════════════════
    def _build_relatorio(self, parent):
        wrap = tk.Frame(parent, bg=BG_MAIN)
        wrap.pack(fill="both", expand=True, padx=20, pady=14)

        # Linha de seleção
        sel_row = tk.Frame(wrap, bg=BG_MAIN)
        sel_row.pack(fill="x", pady=(0, 10))

        # Pill buttons plataforma
        plat_state = {"active": "shopee"}
        pb_shopee  = tk.Button(sel_row, text="SHOPEE", font=FONT_SM,
                               relief="flat", bd=0, padx=12, pady=5, cursor="hand2")
        pb_shopee.pack(side="left", padx=(0, 4))
        pb_ml = tk.Button(sel_row, text="MERCADO LIVRE", font=FONT_SM,
                          relief="flat", bd=0, padx=12, pady=5, cursor="hand2")
        pb_ml.pack(side="left", padx=(0, 16))

        def set_rel_plat(p):
            plat_state["active"] = p
            if p == "shopee":
                pb_shopee.configure(bg=SHOPEE_C, fg=FG_MAIN)
                pb_ml.configure(bg=BG_INPUT, fg=FG_LABEL)
            else:
                pb_shopee.configure(bg=BG_INPUT, fg=FG_LABEL)
                pb_ml.configure(bg=BLUE, fg=FG_MAIN)

        pb_shopee.configure(command=lambda: set_rel_plat("shopee"))
        pb_ml.configure(command=lambda: set_rel_plat("ml"))
        set_rel_plat("shopee")

        ano_var = tk.StringVar(value=str(datetime.datetime.now().year))
        ttk.Combobox(sel_row, textvariable=ano_var,
                     values=[str(y) for y in range(2024, 2032)],
                     state="readonly", width=8, font=FONT).pack(side="left", padx=(0, 8))

        mes_var = tk.StringVar(value=MESES[datetime.datetime.now().month - 1])
        ttk.Combobox(sel_row, textvariable=mes_var, values=MESES,
                     state="readonly", width=18, font=FONT).pack(side="left")

        btn_gerar = tk.Button(wrap, text="📊 GERAR RELATÓRIO",
                              bg=BLUE, fg=FG_MAIN, font=FONT_B,
                              relief="flat", bd=0, pady=8, cursor="hand2")
        btn_gerar.pack(fill="x", pady=(0, 8))

        result_box = tk.Text(wrap, bg=BG_CARD, fg=FG_MAIN, font=MONO,
                             state="disabled", relief="flat", bd=0)
        result_box.pack(fill="both", expand=True)
        result_box.tag_config("titulo", foreground=YELLOW,  font=("Consolas", 10, "bold"))
        result_box.tag_config("ok",     foreground=GREEN)
        result_box.tag_config("aviso",  foreground=YELLOW)
        result_box.tag_config("erro",   foreground=RED)
        result_box.tag_config("pessoa", foreground=CYAN)
        result_box.tag_config("dim",    foreground=FG_DIM)

        def escrever(txt, tag=""):
            result_box.configure(state="normal")
            result_box.insert("end", txt, tag)
            result_box.configure(state="disabled")

        def gerar():
            result_box.configure(state="normal")
            result_box.delete("1.0", "end")
            result_box.configure(state="disabled")
            btn_gerar.configure(state="disabled", text="Gerando...")

            def task():
                r = gerar_relatorio(plat_state["active"], ano_var.get(),
                                    mes_var.get(), self.config_data)
                pnome = "SHOPEE" if plat_state["active"] == "shopee" else "MERCADO LIVRE"
                escrever(f"\n  RELATÓRIO — {pnome}  |  {mes_var.get()} / {ano_var.get()}\n",
                         "titulo")
                escrever(f"  {'─' * 46}\n", "dim")
                if r["total"] == 0:
                    escrever(f"\n  Nenhuma pasta encontrada em:\n  {r['destino']}\n", "aviso")
                    btn_gerar.configure(state="normal", text="📊 GERAR RELATÓRIO")
                    return
                escrever(f"\n  Total de pastas:     {r['total']}\n", "ok")
                escrever(f"  Com nome de cliente: {r['com_cliente']}\n")
                escrever(f"  Ainda como 'Vazio':  {r['vazio']}\n",
                         "aviso" if r["vazio"] else "ok")
                escrever(f"  Com arquivo #ENVIAR: {r['com_arquivo']}\n", "ok")
                escrever(f"  Sem arquivo #ENVIAR: {r['sem_arquivo']}\n",
                         "aviso" if r["sem_arquivo"] else "ok")
                escrever(f"\n  {'─' * 46}\n", "dim")
                escrever("  POR RESPONSÁVEL:\n", "titulo")
                for pessoa, qtd in sorted(r["por_pessoa"].items()):
                    escrever(f"    {pessoa:<6} → {qtd} pasta(s)\n", "pessoa")
                sem_arq = [p for p in r["lista"] if not p["tem_arquivo"] and not p["vazio"]]
                if sem_arq:
                    escrever(f"\n  {'─' * 46}\n", "dim")
                    escrever("  ⚠  Pastas com cliente mas sem arquivo em #ENVIAR:\n", "aviso")
                    for p in sem_arq:
                        escrever(f"    {p['codigo']} - {p['cliente']}\n", "aviso")
                btn_gerar.configure(state="normal", text="📊 GERAR RELATÓRIO")

            threading.Thread(target=task, daemon=True).start()

        btn_gerar.configure(command=gerar)

    # ═════════════════════════════════════════════════════════════════════════
    # PAINEL: WATCHER
    # ═════════════════════════════════════════════════════════════════════════
    def _build_watcher(self, parent):
        self._watcher_panel = parent

        wrap = tk.Frame(parent, bg=BG_MAIN)
        wrap.pack(fill="both", expand=True, padx=20, pady=14)

        # Card de status
        status_card = tk.Frame(wrap, bg=BG_CARD, pady=18)
        status_card.pack(fill="x", pady=(0, 12))

        self._watcher_status_var = tk.StringVar(value="○ INATIVO")
        self._watcher_status_lbl = tk.Label(
            status_card, textvariable=self._watcher_status_var,
            bg=BG_CARD, fg=FG_DIM, font=("Segoe UI", 18, "bold"))
        self._watcher_status_lbl.pack()

        self._watcher_toggle_var = tk.StringVar(value="Iniciar Watcher")
        self._watcher_toggle_btn = tk.Button(
            wrap, textvariable=self._watcher_toggle_var,
            bg=GREEN, fg=BG_MAIN, font=FONT_B,
            relief="flat", bd=0, pady=8, cursor="hand2",
            command=self._toggle_watcher_panel)
        self._watcher_toggle_btn.pack(fill="x", pady=(0, 10))

        intervalo = self.config_data.get("watcher_interval", 60)
        info_txt  = (f"Polling a cada {intervalo} segundos. Detecta quando card do Trello "
                     "recebe código no título e renomeia a pasta automaticamente.")
        tk.Label(wrap, text=info_txt, bg=BG_MAIN, fg=FG_LABEL, font=FONT_XS,
                 wraplength=480, justify="left").pack(anchor="w", pady=(0, 10))

        tk.Label(wrap, text="LOG DO WATCHER", bg=BG_MAIN, fg=FG_LABEL,
                 font=FONT_SM).pack(anchor="w", pady=(0, 3))

        self._watcher_log = tk.Text(wrap, bg=BG_CARD, fg=CYAN, font=MONO,
                                    state="disabled", relief="flat", bd=0)
        self._watcher_log.pack(fill="both", expand=True)
        self._watcher_log.tag_config("ok",   foreground=GREEN)
        self._watcher_log.tag_config("erro", foreground=RED)
        self._watcher_log.tag_config("info", foreground=CYAN)
        self._watcher_log.tag_config("dim",  foreground=FG_DIM)

        tk.Button(wrap, text="Limpar log", bg=BG_INPUT, fg=FG_LABEL,
                  font=FONT_XS, relief="flat", bd=0, padx=8, pady=3,
                  cursor="hand2", command=self._clear_watcher_log
                  ).pack(anchor="e", pady=(4, 0))

    def _refresh_watcher_panel(self):
        if self.watcher_active:
            self._watcher_status_var.set("● ATIVO")
            self._watcher_status_lbl.configure(fg=GREEN)
            self._watcher_toggle_var.set("Parar Watcher")
            self._watcher_toggle_btn.configure(bg=RED, fg=FG_MAIN)
        else:
            self._watcher_status_var.set("○ INATIVO")
            self._watcher_status_lbl.configure(fg=FG_DIM)
            self._watcher_toggle_var.set("Iniciar Watcher")
            self._watcher_toggle_btn.configure(bg=GREEN, fg=BG_MAIN)

    def _toggle_watcher_panel(self):
        if self.watcher_active:
            self._stop_watcher()
        else:
            self._start_watcher()
        self._refresh_watcher_panel()
        self._update_watcher_header()

    def _watcher_log_append(self, msg, tag="info"):
        def _do():
            self._watcher_log.configure(state="normal")
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self._watcher_log.insert("end", f"[{ts}] {msg}\n", tag)
            self._watcher_log.see("end")
            self._watcher_log.configure(state="disabled")
        self.after(0, _do)

    def _clear_watcher_log(self):
        self._watcher_log.configure(state="normal")
        self._watcher_log.delete("1.0", "end")
        self._watcher_log.configure(state="disabled")

    def _start_watcher(self):
        if self.watcher_active:
            return
        self.watcher_active = True
        self._watcher_processed.clear()
        self._watcher_log_append("Watcher iniciado.", "ok")

        def loop():
            while self.watcher_active:
                try:
                    self._watcher_tick()
                except Exception as e:
                    self._watcher_log_append(f"Erro no watcher: {e}", "erro")
                interval = int(self.config_data.get("watcher_interval", 60))
                for _ in range(interval * 10):
                    if not self.watcher_active:
                        break
                    time.sleep(0.1)

        self.watcher_thread = threading.Thread(target=loop, daemon=True)
        self.watcher_thread.start()

    def _stop_watcher(self):
        self.watcher_active = False
        self._watcher_log_append("Watcher parado.", "dim")

    def _watcher_tick(self):
        cfg = self.config_data
        if not trello_configurado(cfg):
            return

        pairs = [
            ("shopee", cfg.get("shopee_list_dev_id", ""), cfg["shopee_base"]),
            ("ml",     cfg.get("ml_list_dev_id", ""),     cfg["ml_base"]),
        ]

        for plat, list_id, base_path in pairs:
            if not list_id or not base_path:
                continue
            try:
                cards = trello_get_list_cards(list_id, cfg["trello_key"], cfg["trello_token"])
            except Exception as e:
                self._watcher_log_append(f"[{plat.upper()}] Erro ao buscar cards: {e}", "erro")
                continue

            for card in cards:
                card_id   = card["id"]
                card_name = card.get("name", "")
                if card_id in self._watcher_processed:
                    continue
                m = FOLDER_CODE_RE.match(card_name)
                if not m:
                    continue
                code, _ = m.group(1), m.group(2)
                # Procura pasta "CODE - Vazio" na base
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
                        novo_nome  = card_name
                        dir_pai    = os.path.dirname(found_path)
                        novo_path  = os.path.join(dir_pai, novo_nome)
                        os.rename(found_path, novo_path)
                        self._watcher_log_append(
                            f"[{plat.upper()}] Renomeado: {vazio_name} → {novo_nome}", "ok")
                        self._watcher_processed.add(card_id)
                        # Atualiza índice
                        self.index_data[code] = {
                            "path": novo_path, "nome": novo_nome,
                            "cliente": m.group(2),
                            "plat": plat.upper(),
                        }
                        save_index(self.index_data)
                    except Exception as e:
                        self._watcher_log_append(
                            f"[{plat.upper()}] Erro ao renomear {vazio_name}: {e}", "erro")
                else:
                    # Já renomeado ou não existe: marca como processado
                    self._watcher_processed.add(card_id)

    # ═════════════════════════════════════════════════════════════════════════
    # CONFIG
    # ═════════════════════════════════════════════════════════════════════════
    def _open_sobre(self):
        win = tk.Toplevel(self)
        win.title("Sobre o FolderFlow")
        win.geometry("380x320")
        win.resizable(False, False)
        win.configure(bg=BG_MAIN)
        win.grab_set()

        # Faixa amarela no topo
        tk.Frame(win, bg=YELLOW, height=4).pack(fill="x")

        body = tk.Frame(win, bg=BG_MAIN)
        body.pack(fill="both", expand=True, padx=32, pady=24)

        tk.Label(body, text="FolderFlow", bg=BG_MAIN, fg=YELLOW,
                 font=("Segoe UI", 22, "bold")).pack(anchor="w")

        tk.Label(body, text=f"Versão  {APP_VERSION}", bg=BG_MAIN, fg=FG_DIM,
                 font=FONT_SM).pack(anchor="w", pady=(0, 20))

        tk.Frame(body, bg=BG_CARD, height=1).pack(fill="x", pady=(0, 20))

        tk.Label(body, text="Desenvolvido por", bg=BG_MAIN, fg=FG_DIM,
                 font=FONT_SM).pack(anchor="w")
        tk.Label(body, text="Italo Bernardo", bg=BG_MAIN, fg=FG_MAIN,
                 font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(2, 20))

        tk.Frame(body, bg=BG_CARD, height=1).pack(fill="x", pady=(0, 16))

        tk.Label(body,
                 text="Gestão de pastas para Shopee e Mercado Livre\n"
                      "com integração ao Trello.",
                 bg=BG_MAIN, fg=FG_DIM, font=FONT_SM, justify="left").pack(anchor="w")

        tk.Button(body, text="Fechar", bg=YELLOW, fg=BG_MAIN, font=FONT_B,
                  relief="flat", bd=0, padx=24, pady=7, cursor="hand2",
                  command=win.destroy).pack(anchor="e", pady=(24, 0))

    def _open_config(self):
        win = tk.Toplevel(self)
        win.title("Configurações")
        win.geometry("580x640")
        win.configure(bg=BG_MAIN)
        win.grab_set()
        win.resizable(False, False)

        canvas = tk.Canvas(win, bg=BG_MAIN, highlightthickness=0)
        sb_c   = tk.Scrollbar(win, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb_c.set)
        sb_c.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG_MAIN)
        canvas.create_window((0, 0), window=inner, anchor="nw", width=558)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        def secao(titulo, cor=CYAN):
            tk.Frame(inner, bg=BG_MAIN, height=8).pack(fill="x")
            lbl = tk.Label(inner, text=f"  {titulo}", bg=BG_CARD, fg=cor, font=FONT_B,
                           anchor="w")
            lbl.pack(fill="x", padx=0)
            tk.Frame(inner, bg=FG_DIM, height=1).pack(fill="x", pady=(0, 8))

        def campo(label, var, browse=False, senha=False):
            f = tk.Frame(inner, bg=BG_MAIN)
            f.pack(fill="x", padx=24, pady=3)
            tk.Label(f, text=label, bg=BG_MAIN, fg=FG_LABEL, font=FONT_SM,
                     width=28, anchor="w").pack(side="left")
            show = "*" if senha else ""
            e = tk.Entry(f, textvariable=var, bg=BG_INPUT, fg=FG_MAIN,
                         insertbackground=FG_MAIN, font=FONT_SM,
                         relief="flat", bd=4, width=22, show=show)
            e.pack(side="left", padx=(4, 4))
            if senha:
                vis = [False]
                def toggle_vis(v=var, widget=e, state=vis):
                    state[0] = not state[0]
                    widget.configure(show="" if state[0] else "*")
                tk.Button(f, text="👁", bg=BG_MAIN, fg=FG_LABEL, font=FONT_XS,
                          bd=0, cursor="hand2", command=toggle_vis).pack(side="left")
            if browse:
                tk.Button(f, text="...", bg=BG_INPUT, fg=FG_MAIN, font=FONT_SM,
                          bd=0, cursor="hand2",
                          command=lambda v=var: v.set(filedialog.askdirectory() or v.get())
                          ).pack(side="left")

        # 1. PASTAS
        secao("PASTAS")
        shopee_var = tk.StringVar(value=self.config_data["shopee_base"])
        ml_var     = tk.StringVar(value=self.config_data["ml_base"])
        pause_var  = tk.BooleanVar(value=self.config_data["pause_onedrive"])
        campo("Pasta base SHOPEE:", shopee_var, browse=True)
        campo("Pasta base ML:", ml_var, browse=True)
        tk.Checkbutton(inner, text="Pausar OneDrive por padrão",
                       variable=pause_var, bg=BG_MAIN, fg=FG_LABEL,
                       selectcolor=BG_INPUT, activebackground=BG_MAIN,
                       font=FONT_SM).pack(anchor="w", padx=24, pady=4)

        # 2. TRELLO
        secao("TRELLO")
        tk.Label(inner, text="  API Key e Token: https://trello.com/app-key",
                 bg=BG_MAIN, fg=FG_DIM, font=FONT_XS).pack(anchor="w", padx=24, pady=(0, 4))
        trello_key_var   = tk.StringVar(value=self.config_data.get("trello_key", ""))
        trello_token_var = tk.StringVar(value=self.config_data.get("trello_token", ""))
        campo("API Key:", trello_key_var)
        campo("Token:", trello_token_var, senha=True)

        teste_var = tk.StringVar()
        def testar_trello():
            key   = trello_key_var.get().strip()
            token = trello_token_var.get().strip()
            if not key or not token:
                teste_var.set("Preencha API Key e Token primeiro.")
                return
            teste_var.set("Testando...")
            def task():
                try:
                    boards = trello_get_boards(key, token)
                    nomes  = ", ".join(b["name"] for b in boards[:3])
                    teste_var.set(f"✅ OK! Boards: {nomes}...")
                except Exception as e:
                    teste_var.set(f"❌ Erro: {e}")
            threading.Thread(target=task, daemon=True).start()

        tf = tk.Frame(inner, bg=BG_MAIN)
        tf.pack(anchor="w", padx=24, pady=(6, 0))
        tk.Button(tf, text="🔌 Testar conexão", bg=BG_INPUT, fg=FG_MAIN,
                  font=FONT_SM, relief="flat", bd=0, padx=10, pady=5,
                  cursor="hand2", command=testar_trello).pack(side="left")
        tk.Label(tf, textvariable=teste_var, bg=BG_MAIN, fg=CYAN,
                 font=FONT_SM).pack(side="left", padx=10)

        # 3. SHOPEE — LISTAS
        secao("SHOPEE — LISTAS", SHOPEE_C)
        shopee_board_var       = tk.StringVar(value=self.config_data.get("shopee_board_id", ""))
        shopee_aguard_var      = tk.StringVar(value=self.config_data.get("shopee_list_aguardando", ""))
        shopee_dev_var         = tk.StringVar(value=self.config_data.get("shopee_list_dev_id", ""))
        campo("Board ID:", shopee_board_var)
        campo("Lista Aguardando Aprovação ID:", shopee_aguard_var)
        campo("Lista Desenvolvimento ID:", shopee_dev_var)

        # 4. MERCADO LIVRE — LISTAS
        secao("MERCADO LIVRE — LISTAS", BLUE)
        ml_board_var  = tk.StringVar(value=self.config_data.get("ml_board_id", ""))
        ml_aguard_var = tk.StringVar(value=self.config_data.get("ml_list_aguardando", ""))
        ml_dev_var    = tk.StringVar(value=self.config_data.get("ml_list_dev_id", ""))
        campo("Board ID:", ml_board_var)
        campo("Lista Aguardando Aprovação ID:", ml_aguard_var)
        campo("Lista Desenvolvimento ID:", ml_dev_var)

        # 5. ATUALIZAÇÃO AUTOMÁTICA
        secao("ATUALIZAÇÃO AUTOMÁTICA (GitHub)", GREEN)
        tk.Label(inner,
                 text="  Repositório no formato usuario/FolderFlow. O app avisa quando\n"
                      "  sair versão nova e atualiza sozinho com um clique.",
                 bg=BG_MAIN, fg=FG_DIM, font=FONT_XS, justify="left"
                 ).pack(anchor="w", padx=24, pady=(0, 4))
        repo_var = tk.StringVar(value=self.config_data.get("github_repo", ""))
        campo("Repositório GitHub:", repo_var)
        tk.Label(inner,
                 text=f"  Versão instalada atualmente: {APP_VERSION}",
                 bg=BG_MAIN, fg=FG_DIM, font=FONT_XS).pack(anchor="w", padx=24, pady=(4, 0))

        # 6. WATCHER
        secao("WATCHER", FG_DIM)
        watcher_int_var = tk.StringVar(value=str(self.config_data.get("watcher_interval", 60)))
        wf = tk.Frame(inner, bg=BG_MAIN)
        wf.pack(fill="x", padx=24, pady=3)
        tk.Label(wf, text="Intervalo de polling (segundos):", bg=BG_MAIN,
                 fg=FG_LABEL, font=FONT_SM, width=28, anchor="w").pack(side="left")
        tk.Entry(wf, textvariable=watcher_int_var, bg=BG_INPUT, fg=FG_MAIN,
                 insertbackground=FG_MAIN, font=FONT_SM, relief="flat", bd=4,
                 width=8).pack(side="left", padx=(4, 8))
        tk.Label(wf, text="(padrão: 60)", bg=BG_MAIN, fg=FG_DIM,
                 font=FONT_XS).pack(side="left")

        # Salvar
        def salvar():
            try:
                intervalo = int(watcher_int_var.get())
                assert intervalo >= 10
            except Exception:
                messagebox.showerror("Erro", "Intervalo do watcher deve ser >= 10.", parent=win)
                return

            self.config_data["shopee_base"]            = shopee_var.get()
            self.config_data["ml_base"]                = ml_var.get()
            self.config_data["pause_onedrive"]         = pause_var.get()
            self.config_data["trello_key"]             = trello_key_var.get().strip()
            self.config_data["trello_token"]           = trello_token_var.get().strip()
            self.config_data["shopee_board_id"]        = shopee_board_var.get().strip()
            self.config_data["ml_board_id"]            = ml_board_var.get().strip()
            self.config_data["shopee_list_aguardando"] = shopee_aguard_var.get().strip()
            self.config_data["ml_list_aguardando"]     = ml_aguard_var.get().strip()
            self.config_data["shopee_list_dev_id"]     = shopee_dev_var.get().strip()
            self.config_data["ml_list_dev_id"]         = ml_dev_var.get().strip()
            self.config_data["watcher_interval"]       = intervalo
            self.config_data["github_repo"]            = repo_var.get().strip()
            save_config(self.config_data)
            messagebox.showinfo("Salvo", "Configurações salvas!", parent=win)
            win.destroy()

        tk.Frame(inner, bg=BG_MAIN, height=10).pack(fill="x")
        tk.Button(inner, text="Salvar", bg=YELLOW, fg=BG_MAIN, font=FONT_B,
                  relief="flat", bd=0, padx=32, pady=10, cursor="hand2",
                  command=salvar).pack(pady=(0, 20))


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = App()
    app.mainloop()
