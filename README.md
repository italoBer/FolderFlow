# FolderFlow

Aplicativo desktop para **criar e organizar estruturas de pastas em lote** — para qualquer pessoa ou empresa.

Você define **grupos**, cada um com uma pasta base e um **modelo de estrutura** (pastas, subpastas, arquivos, repetição numerada). O app cria tudo de uma vez, com pré-visualização antes. Inclui um preset **Marketplace** (Shopee / Mercado Livre) com integração ao Trello, usado em produção por uma gráfica que gerencia milhares de pastas de arte por mês num OneDrive compartilhado.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![CustomTkinter](https://img.shields.io/badge/GUI-CustomTkinter-yellow)
![Windows](https://img.shields.io/badge/Plataforma-Windows-0078D6?logo=windows)

## ✨ Funcionalidades

### Grupos com modelos de estrutura
- **Tela inicial com grupos** — cada grupo é um card colorido: uma pasta base + um modelo
- **Modelo em texto simples** — você escreve a estrutura e o app cria:
  ```
  Clientes Loja 1/
  Produtos Loja 2/
    X/
    Y/
      [200] Pasta {seq:04d}/
        teste/
        infos.txt = Informações do item {seq:04d}
    Z/
  ```
- **Repetição em lote** — `[200]` cria 200 pastas numeradas; a numeração **continua da maior já existente** (nunca duplica)
- **Arquivos com conteúdo** — `infos.txt = texto` cria o arquivo já preenchido
- **Variáveis** — qualquer `{nome}` vira um campo na tela; `{ano}`, `{mes}`, `{mes_num}` e `{data}` já vêm prontas
- **Pré-visualização** — veja o que será criado (e o que já existe) antes de confirmar

### Preset Marketplace (Shopee / Mercado Livre)
- **Criação em lote por responsável** — código `MM0001X` (mês + sequencial + iniciais), subpasta `#ENVIAR`
- **Renomear + Trello** — localiza a pasta pelo código, renomeia com o nome do cliente, atualiza o card no Trello e move para a lista de aprovação
- **Relatório mensal** — estatísticas por responsável, pastas vazias, pastas sem arquivo
- **Watcher** — monitora listas do Trello e renomeia pastas automaticamente

### Geral
- **Busca instantânea** — índice local; encontra qualquer pasta por código ou nome enquanto digita e abre no Explorer
- **Pausa do OneDrive** — pausa a sincronização durante criação em massa e retoma depois
- **Atualização automática** — detecta novas versões nas Releases do GitHub e se atualiza com um clique (no `.exe`)

## 🖥️ Instalação

**Opção 1 — Executável (recomendado):**
Baixe o `FolderFlow.exe` da [última release](../../releases/latest) e execute. Não precisa de Python instalado.

**Opção 2 — Código-fonte:**
```bash
git clone https://github.com/SEU_USUARIO/FolderFlow.git
cd FolderFlow
pip install customtkinter
python folderflow.py
```

As configurações ficam em `folderflow_config.json`, ao lado do executável. Quem vinha da versão 1.x (Shopee/ML fixos) é **migrado automaticamente**: os dois fluxos viram grupos "Shopee" e "Mercado Livre" sem perder nenhuma configuração.

## ⚙️ Gerando o .exe

```bash
pip install pyinstaller customtkinter
pyinstaller FolderFlow.spec
```

## 🔧 Integração com Trello (opcional)

Em **⚙ Configurações**, informe sua API Key e Token ([trello.com/app-key](https://trello.com/app-key)). Os IDs de board/listas ficam no **✎ do grupo** marketplace. Com isso, ao renomear uma pasta o app atualiza o card correspondente automaticamente.

## 🧑‍💻 Autor

Desenvolvido por **Italo Bernardo**.
