# FolderFlow

Aplicativo desktop para gestão de pastas de clientes em operações de e-commerce (Shopee e Mercado Livre), com integração ao Trello e atualização automática via GitHub Releases.

Criado para resolver um problema real de uma gráfica que gerencia milhares de pastas de arte por mês em um OneDrive compartilhado entre vários funcionários.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![Tkinter](https://img.shields.io/badge/GUI-Tkinter-green)
![Windows](https://img.shields.io/badge/Plataforma-Windows-0078D6?logo=windows)

## ✨ Funcionalidades

- **Criação em lote** — cria dezenas de pastas numeradas de uma vez, com subpasta `#ENVIAR`, para múltiplos responsáveis
- **Numeração inteligente** — código no formato `MM0001X` (mês + sequencial + iniciais do responsável), com reset mensal automático; varre as pastas existentes para nunca duplicar, mesmo com vários usuários criando ao mesmo tempo
- **Pausa do OneDrive** — pausa a sincronização durante a criação em massa e retoma depois (muito mais rápido)
- **Renomear + Trello** — localiza a pasta pelo código, renomeia com o nome do cliente e, na mesma ação, atualiza o título do card no Trello e move para a lista de aprovação
- **Busca instantânea** — índice local em JSON; encontra qualquer pasta por código ou nome do cliente enquanto digita, sem esperar o OneDrive
- **Relatório mensal** — estatísticas por responsável, pastas vazias, pastas sem arquivo
- **Atualização automática** — detecta novas versões nas Releases do GitHub e se atualiza com um clique (funciona no `.exe`)

## 🖥️ Instalação

**Opção 1 — Executável (recomendado):**
Baixe o `FolderFlow.exe` da [última release](../../releases/latest) e execute. Não precisa de Python instalado.

**Opção 2 — Código-fonte:**
```bash
git clone https://github.com/SEU_USUARIO/FolderFlow.git
cd FolderFlow
python folderflow.py
```
Requer apenas Python 3.10+ (usa somente a biblioteca padrão — zero dependências).

No primeiro uso, o app pede para configurar os caminhos das pastas base. As configurações ficam em `folderflow_config.json`, ao lado do executável.

## ⚙️ Gerando o .exe

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "FolderFlow" folderflow.py
```

## 🔧 Integração com Trello (opcional)

Em **⚙ Configurações**, informe sua API Key e Token ([trello.com/app-key](https://trello.com/app-key)) e os IDs dos boards/listas. Com isso, ao renomear uma pasta o app atualiza o card correspondente automaticamente.

## 🧑‍💻 Autor

Desenvolvido por **Italo Bernardo**.
