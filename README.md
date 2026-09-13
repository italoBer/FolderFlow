# FolderFlow

Aplicativo desktop para Windows que **cria, organiza e confere estruturas de pastas em lote**.

Você cria **grupos**. Cada grupo tem uma pasta base e um jeito de organizar: um **modelo de estrutura** ou o fluxo **Marketplace** (Shopee / Mercado Livre), que tem código por mês, responsável e integração com o Trello. O app cria tudo de uma vez e mostra antes o que vai ser criado. Depois ele deixa você explorar, renomear, conferir e gerar relatórios das pastas de verdade.

Nasceu para uma gráfica que gerencia milhares de pastas de arte por mês num OneDrive compartilhado, e hoje serve para qualquer pessoa ou empresa.

![Python](https://img.shields.io/badge/Python-3.14-blue?logo=python&logoColor=white)
![CustomTkinter](https://img.shields.io/badge/GUI-CustomTkinter-84cc16)
![Windows](https://img.shields.io/badge/Plataforma-Windows-0078D6?logo=windows)

## ✨ Funcionalidades

### Grupos
- **Tela inicial com cards.** Cada card mostra o grupo, a pasta base e o que está pendente no mês, por exemplo "🟡 3 para corrigir · 2 sem arte". Clicar na pendência abre a conferência.
- **Mesmas abas em todo grupo:** Pastas · Modelo/Criar · Renomear · Conferir · Relatório.
- **Exportar e importar grupo** (`.json`), para levar a configuração para outro PC.

### Pastas: explorador das pastas reais
- **Relê o disco sozinho.** O que muda pelo Explorador do Windows aparece em segundos, sem piscar e sem perder a posição.
- **Ctrl+C / Ctrl+X / Ctrl+V integrados ao Windows.** Dá para copiar aqui e colar no Explorador, e vice-versa.
- **Renomear:** um item com F2, ou vários de uma vez. Com uma pasta selecionada, renomeia o que está dentro dela.
- **Ctrl+Z** desfaz renomear, colar, mover e criar. A exclusão vai sempre para a **Lixeira**.
- **Filtro (Ctrl+F)** e **barra de status** com caminho e tamanho da seleção.

### Modelo de estrutura
- **Construtor visual estilo IDE**, com botão direito, F2, copiar e colar partes com Ctrl+C/V e pré-visualização. Também existe o **modo texto**:
  ```
  Clientes/
    [200] Cliente {seq:04d}/
      Artes/
      Aprovação/
      infos.txt = Dados do cliente {seq:04d}
  ```
- **`[200]`** cria 200 pastas numeradas. A numeração **continua da maior já existente**.
- **Arquivos com conteúdo** (`infos.txt = texto`) e **anexos**, que copiam um arquivo real (ex.: PDF gabarito) para dentro de cada pasta.
- **Variáveis:** qualquer `{nome}` vira um campo. `{ano}`, `{mes}`, `{mes_num}`, `{mes_nome}` e `{data}` já vêm prontas.

### Marketplace (Shopee / Mercado Livre)
- **Criação em lote por responsável.** O código é `MM0001XX` (mês + sequencial + iniciais), com a subpasta `#ENVIAR`. A tela divide um total entre as pessoas e lembra quem costuma receber.
- **Organização por ano/mês detectada sozinha** a partir das pastas que já existem.
- **Renomear + Trello.** Localiza pelo código ou pelo nome, renomeia com o nome do cliente, atualiza o card e move para a lista de aprovação.
- **Watcher:** acompanha a lista "Desenvolvimento" do Trello e renomeia as pastas automaticamente.
- **Conferir:** acha as pastas que continuaram como "Vazio" mas já têm arquivo, e sugere o nome do cliente pelo arquivo `.cdr`. Mostra a lista para revisar antes de corrigir e avisa quando há número repetido no mês.
- **Relatório** em tabela, com cards que filtram e exportação para CSV.

### Geral
- **Paleta de comandos (Ctrl+K)** em qualquer tela: grupos, ações e pastas pelo código.
- **Busca** em todos os grupos, que ignora acento e maiúsculas. O índice se atualiza sozinho.
- **Pausa do OneDrive** durante a criação em massa.
- **Tour "Conhecer o app"** (ⓘ no topo) e **tela de atalhos (F1)**.
- **Atualização automática** pelas Releases do GitHub, no `.exe`.

## ⌨️ Atalhos principais

| Tecla | Ação |
|---|---|
| `Ctrl+K` | Paleta de comandos |
| `Ctrl+F` | Filtrar a lista da tela |
| `Ctrl+C` / `Ctrl+X` / `Ctrl+V` | Copiar, recortar e colar (vale no Explorador) |
| `Ctrl+Z` | Desfazer |
| `F2` / `Del` | Renomear / mandar para a Lixeira |
| `Ctrl+N` / `Ctrl+Shift+N` | Nova pasta / novo arquivo |
| `Ctrl+1` … `Ctrl+5` | Trocar de aba dentro do grupo |
| `Alt+←` | Voltar ao início |
| `F1` | Todos os atalhos |

## 🖥️ Instalação

**Opção 1 — Executável (recomendado):**
baixe o `FolderFlow.exe` da [última release](../../releases/latest) e execute. Não precisa de Python.

**Opção 2 — Código-fonte:**
```bash
git clone https://github.com/italoBer/FolderFlow.git
cd FolderFlow
pip install customtkinter pillow send2trash
python folderflow.py
```

### Onde ficam os dados
Ao lado do executável ficam três arquivos:

| Arquivo | Conteúdo |
|---|---|
| `folderflow_config.json` | Grupos e configurações. É gravado com backup automático (`.bak`) |
| `folderflow_index.json` | Índice da busca, que pode ser apagado e é refeito sozinho |
| `folderflow_history.json` | Histórico dos lotes criados |

### Vindo da versão 1.x
A migração é **automática**. Na primeira abertura, os fluxos fixos de Shopee e Mercado Livre viram os grupos "Shopee" e "Mercado Livre". Pastas base, chave e listas do Trello e intervalo do watcher são mantidos. As chaves antigas continuam no arquivo, então dá para voltar à 1.1.0 se precisar.

## 🔧 Integração com Trello (opcional)

1. Em **⚙ Configurações**, informe a API Key e o Token ([trello.com/app-key](https://trello.com/app-key)).
2. No **✎ do grupo** marketplace, informe o Board ID e os IDs das listas "Aguardando Aprovação" e "Desenvolvimento".

Quem não usa Trello pode desligá-lo nas Configurações, e toda a parte de Trello some da tela.

## ⚙️ Gerando o .exe

```bash
pip install pyinstaller customtkinter pillow send2trash
pyinstaller FolderFlow.spec --noconfirm
```
O executável sai em `dist\FolderFlow.exe`.

## 🧪 Testes

Os testes ficam em `tests\` e cada arquivo roda sozinho:
```bash
python tests\test_engine.py
```
- `test_compat_v1.py` — **certificação contra a v1.1.0 de produção.** Tira essa versão do git e compara as duas lado a lado: migração, caminhos, criação de lote, renomear com Trello, watcher, índice e atualização.
- `smoke_exe_update.py` — roda o **`.exe` gerado** numa pasta com a config da v1 e confere a atualização de ponta a ponta. Rode depois de cada build.
- `test_clipboard.py` e parte do `test_etapaB2.py` usam a área de transferência real, e só rodam com a variável `FF_CLIP=1`.

## 🚀 Publicando uma nova versão

> ⚠️ Publicar uma Release **atualiza todos os PCs** que usam o app. Commit e push sozinhos não afetam ninguém.

1. Aumente `APP_VERSION` no `folderflow.py` (ex.: `2.0.1`) e commite.
2. Gere o `.exe`, rode os testes e o `smoke_exe_update.py`.
3. No GitHub, abra **Releases → Draft a new release** e crie a tag **igual à versão** (ex.: `v2.0.1`).
4. Anexe o `dist\FolderFlow.exe` e deixe **desmarcado** o "pre-release".
5. Clique em **Publish release**.

Cada PC mostra o aviso de atualização alguns segundos depois de abrir o app, e reinicia sozinho na versão nova.

**Tag e `APP_VERSION` precisam ser iguais**, senão o app pede para atualizar toda vez que abre. O app nunca volta para uma versão mais antiga. Para desfazer uma versão ruim, publique uma correção com número maior.

## 🧑‍💻 Autor

Desenvolvido por **Italo Bernardo**.
