# Fase 0 — Etapa A: gravador passivo

A Fase 0 mapeia o Medicina Direta (MD) antes de qualquer automação. O mapeamento cobre telas, estrutura do DOM, estados do laudo e as operações de gravação do ScriptCase que a guarda precisa bloquear.

- **Etapa A** (este documento): a ferramenta. O perfil Chrome dedicado e o gravador passivo. A Etapa A não acessa o MD.
- **Etapa B:** o mapeamento real, em 2 pacientes de teste, com o Ivson presente e com autorização explícita (checklist no fim).

## 1. Perfil Chrome dedicado

O projeto usa um perfil próprio do Chrome, em `%LOCALAPPDATA%\FluxoExames\chrome-profile`. **Nunca use o perfil pessoal do Ivson**, por três motivos:

- desde o Chrome 136, a porta de depuração não funciona no perfil padrão;
- a automação não pode disputar abas e foco com o navegador de trabalho;
- o perfil dedicado isola a sessão do MD de tudo o mais (extensões, outras contas).

Criar a pasta do perfil (uma vez só; PowerShell):

```powershell
New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\FluxoExames\chrome-profile" | Out-Null
```

Na primeira abertura (item 2), o Chrome cria o perfil vazio. O Ivson faz o login no MD **à mão** nesse perfil. Nenhum agente vê nem guarda a senha. Não instale extensões nem entre em outros sites ou contas nesse perfil.

## 2. Abrir o Chrome do projeto com a porta de depuração

Feche antes qualquer janela que já use esse perfil. O Chrome pessoal pode continuar aberto, porque é outra instância.

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
    --user-data-dir="$env:LOCALAPPDATA\FluxoExames\chrome-profile" `
    --remote-debugging-port=9222 `
    --no-first-run --no-default-browser-check
```

Para conferir, abra `http://127.0.0.1:9222/json/version` em outro navegador ou rode `curl http://127.0.0.1:9222/json/version`. A resposta deve ser um JSON com `"Browser": "Chrome/..."`.

**Cuidado:** enquanto a porta 9222 está aberta, qualquer programa do notebook pode controlar esse Chrome e, com ele, a sessão logada no MD. A porta só escuta em `127.0.0.1`. Abra o Chrome com a porta **apenas durante a sessão de gravação** e feche-o ao terminar.

## 3. Rodar o gravador

Na raiz do repositório:

```powershell
python -m pip install -r requirements.txt   # uma vez
python scripts\gravador_passivo.py
```

Opções: `--porta 9222` (padrão), `--saida PASTA` (padrão `%LOCALAPPDATA%\FluxoExames\captures`) e `--espera 1.5`. A espera é o número de segundos sem novos eventos antes de tirar o snapshot, o que agrupa navegações em rajada.

Se o Chrome não estiver com a porta aberta, o gravador sai com código 2 e mostra onde está a instrução.

## 4. O que é capturado

A cada navegação em qualquer aba, o gravador salva:

| Onde | Conteúdo |
|---|---|
| `captures\sessao.log` | Uma linha JSON por evento: `INICIO`, `CONECTADO`, `CAPTURA` (horário, motivo, aba, URL completa, título, arquivos), `ERRO`, `DESCONECTADO`, `FIM` |
| `captures\AAAA-MM-DD\HHMMSS-<slug>.html` | outerHTML do documento principal da aba |
| `captures\AAAA-MM-DD\HHMMSS-<slug>.qNN-<slug>.html` | outerHTML de cada iframe do mesmo site, em ordem de documento. Iframes de outro site viram um alvo próprio, ligado à aba pelo campo `alvo_pai` |

Todos os arquivos ficam dentro de `%LOCALAPPDATA%\FluxoExames\captures`.

Detalhes que importam no ScriptCase:

- **Navegação só em iframe:** no ScriptCase, a URL principal não muda e o conteúdo troca dentro dos iframes. A navegação de um iframe também dispara um snapshot da aba inteira, com todos os quadros.
- **Snapshot sem mudança:** se o conteúdo for idêntico ao anterior da mesma aba, nada é gravado.
- **Nomes de arquivo:** o `<slug>` vem de host e caminho da URL, sem query. Assim, nome de arquivo e console não carregam título nem parâmetros. A URL completa e o título ficam só no `sessao.log`.

O gravador **não** captura:

- valores digitados em campos (o outerHTML só guarda atributos);
- rede, cabeçalhos ou corpo de POST;
- PDFs;
- conteúdo de shadow DOM.

Para mapear as requisições, use o DevTools (item 6, passo 7).

**Garantias de passividade:**

- usa só `websocket-client` puro, porque o Playwright injeta scripts de apoio ao conectar;
- aceita só os comandos CDP `Page.enable`, `DOM.getDocument`, `DOM.getOuterHTML` e `DOM.disable`, e recusa qualquer outro antes de enviar;
- não roda JavaScript na página, não clica, não digita e não navega;
- não abre nem fecha abas: usa só `GET /json/version` e `GET /json/list`.

O comportamento foi testado com páginas sintéticas locais, incluindo iframes aninhados, iframe de outro site, navegação só em iframe e `pushState`. O servidor de teste recebeu apenas os GETs das navegações simuladas. O gravador não gerou nenhuma requisição.

**Privacidade:** as capturas da Etapa B terão dados reais de paciente (nome, CPF, laudos).

- Elas ficam em `%LOCALAPPDATA%\FluxoExames`. Não copie para o OneDrive, para o repositório nem para a Sala.
- Nenhuma captura entra no repositório sem ter sido anonimizada antes. `captures/` também está no `.gitignore`, como segunda barreira.
- Pré-requisito: BitLocker ativo no C: antes da Etapa B.

## 5. Parar

Aperte **Ctrl+C** (ou Ctrl+Break) no terminal do gravador. Ele fecha as conexões, grava `FIM` no log e mostra o total de capturas e erros. Depois feche o Chrome do projeto, para fechar a porta 9222.

## 6. Checklist da Etapa B — mapeamento com o Ivson presente

**Antes**

- [ ] Autorização explícita do Ivson para esta sessão, registrada na Sala: data, hora e escopo.
- [ ] Só os **2 pacientes de teste** definidos na ATA da Sala (titular e cônjuge). Os identificadores não entram neste repositório.
- [ ] BitLocker ativo no C: (`manage-bde -status C:` como administrador).
- [ ] As capturas antigas com CPF já saíram do OneDrive.
- [ ] Chrome do projeto aberto conforme o item 2. O Ivson faz o login no MD à mão.
- [ ] Gravador rodando (item 3) e mostrando `Conectado`.

**Durante** — quem navega é o **Ivson**. O agente só observa.

1. Agenda do dia, e de outro dia, para ver a navegação por data.
2. Ficha Clínica do paciente de teste: cabeçalho com prontuário, nome, sexo, DN e CPF.
3. SOAP → Subjetivo → Questionário, onde deve ficar o questionário pré-exame.
4. Exames → Laudo, no 1º nível (atendimentos, "Registros em Aberto x de y", "PDF Assinado x de y", cadeado) e no 2º nível (laudos individuais).
5. Abrir um laudo **assinado** e sair por "Voltar". Depois, "Imprimir" com "LAUDO (PDF)", para ver se o PDF entregue é o original assinado ou uma nova impressão.
6. Exames → Resultado e Anexo.
7. Para mapear requisições: DevTools (F12) → Network → "Preserve log". Ao final, exportar o HAR para `%LOCALAPPDATA%\FluxoExames\captures\AAAA-MM-DD\`. É a fonte para separar os POSTs de leitura das operações de gravação (`nmgp_opcao` e similares).
8. Teste de **sessão simultânea**: com o perfil dedicado logado, o Ivson usa o MD no Chrome pessoal. Anotar se alguma das sessões cai.

- [ ] **Nunca** clicar em Assinar, ASSINAR PDF, Finalizar e Assinar, Salvar, Excluir, Criar, Enviar/Enviar Por, Solicitar ou Ações. Isso vale também para o Ivson durante a gravação.

**Depois**

- [ ] Ctrl+C no gravador e fechar o Chrome do projeto.
- [ ] `git status` limpo neste repositório: nenhuma captura dentro dele.
- [ ] Produzir, **sem dado de paciente**:
  - mapa de telas e seletores;
  - lista dos POSTs demonstrados como leitura (vira `POSTS_PERMITIDOS` em `fluxo_exames/guard.py`);
  - lista das operações de gravação (vira `OPERACOES_SCRIPTCASE_BLOQUEADAS`);
  - textos de botão encontrados;
  - significado de cadeado, "PDF Assinado x de y" e "Registros em Aberto";
  - resultado do teste de sessão simultânea;
  - proveniência do PDF de "Imprimir".
- [ ] Snapshots que forem virar fixture de teste: só depois de anonimizados.
- [ ] Nota na Sala com o resultado e a passagem de bastão.
