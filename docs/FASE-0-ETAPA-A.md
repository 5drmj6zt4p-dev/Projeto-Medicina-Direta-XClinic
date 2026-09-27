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

Opções: `--porta 9222` (padrão), `--saida PASTA` (padrão `%LOCALAPPDATA%\FluxoExames\captures`), `--espera 1.5` e `--rede` (desligada por padrão; ver item 4.1). A espera é o número de segundos sem novos eventos antes de tirar o snapshot, o que agrupa navegações em rajada.

Se o Chrome não estiver com a porta aberta, o gravador sai com código 2 e mostra onde está a instrução.

## 4. O que é capturado

A cada navegação em qualquer aba, o gravador salva:

| Onde | Conteúdo |
|---|---|
| `captures\sessao.log` | Uma linha JSON por evento: `INICIO`, `CONECTADO` (aba, tipo, `pausado`, `aberta_por` quando a aba foi aberta por outra), `CAPTURA` (horário, motivo, aba, URL completa, título, arquivos), `ERRO`, `DESCONECTADO`, `FIM` |
| `captures\AAAA-MM-DD\HHMMSS-<slug>.html` | outerHTML do documento principal da aba |
| `captures\AAAA-MM-DD\HHMMSS-<slug>.qNN-<slug>.html` | outerHTML de cada iframe do mesmo site, em ordem de documento. Iframes de outro site viram um alvo próprio, ligado à aba pelo campo `alvo_pai` |

Todos os arquivos ficam dentro de `%LOCALAPPDATA%\FluxoExames\captures`.

Detalhes que importam no ScriptCase:

- **Navegação só em iframe:** no ScriptCase, a URL principal não muda e o conteúdo troca dentro dos iframes. A navegação de um iframe também dispara um snapshot da aba inteira, com todos os quadros.
- **Snapshot sem mudança:** se o conteúdo for idêntico ao anterior da mesma aba, nada é gravado.
- **Nomes de arquivo:** o `<slug>` vem de host e caminho da URL, sem query. Assim, nome de arquivo e console não carregam título nem parâmetros. A URL completa e o título ficam só no `sessao.log`.

O gravador **não** captura:

- valores digitados em campos (o outerHTML só guarda atributos);
- cabeçalhos, nem corpo de requisição ou de resposta;
- requisições de rede, a menos que se use `--rede` (item 4.1);
- PDFs;
- conteúdo de shadow DOM.

**Garantias de passividade:**

- usa só `websocket-client` puro, porque o Playwright injeta scripts de apoio ao conectar;
- aceita só os comandos CDP `Page.enable`, `DOM.getDocument`, `DOM.getOuterHTML` e `DOM.disable`, mais `Target.setAutoAttach` e `Runtime.runIfWaitingForDebugger` para anexar as abas novas (item 4.2) e `Network.enable` quando `--rede` está ligada. Recusa qualquer outro antes de enviar, inclusive `Runtime.evaluate`, `Target.attachToTarget`, `Target.createTarget` e `Target.closeTarget`;
- não roda JavaScript na página, não clica, não digita e não navega;
- não abre nem fecha abas. Por HTTP, usa só `GET /json/version`, para achar o websocket do navegador.

O comportamento foi testado com páginas sintéticas locais, incluindo iframes aninhados, iframe de outro site, navegação só em iframe e `pushState`. O servidor de teste recebeu apenas os GETs das navegações simuladas. O gravador não gerou nenhuma requisição.

### 4.2 Abas novas: registro desde a primeira requisição (Etapa D)

**O problema.** Até a Etapa C, o gravador descobria as abas lendo `/json/list` a cada 2 s e abria uma conexão para cada uma. Uma aba nova já tinha começado a carregar quando o gravador chegava, e as primeiras requisições dela se perdiam. Na sessão de 27/09, isso atingiu o Imprimir: o POST do F1 não foi registrado em nenhuma das 3 abas, e o `POST /blank_laudo_pdf/` foi registrado em só 1 delas (`FASE-0-ETAPA-B.md` §9.9). **Essa limitação não existe mais**; as observações de B §9.9 e C §5 valem para as gravações feitas até a Etapa C.

**Como funciona agora.**

1. O gravador abre uma única conexão, no websocket do navegador (o `webSocketDebuggerUrl` de `/json/version`), e envia `Target.setAutoAttach` com `waitForDebuggerOnStart` e `flatten`, filtrando só abas (`page`) e iframes de outro site (`iframe`). Workers, service workers e o próprio navegador ficam de fora e não são pausados.
2. O Chrome anexa o gravador às abas que já existem. Daí em diante, anexa cada aba nova no momento em que ela nasce, **pausada antes da primeira requisição**. Isso vale para qualquer aba nova; `target="_blank"` e `window.open` estão testados.
3. Na sessão da aba pausada, o gravador envia num lote `Network.enable` (com `--rede`), `Page.enable`, o mesmo `Target.setAutoAttach` (para os iframes de outro site dessa aba, que nascem pausados do mesmo jeito) e, por último, `Runtime.runIfWaitingForDebugger`, que solta a aba. O Chrome aplica os comandos de uma sessão na ordem em que chegam. Por isso a rede já está sendo observada quando a aba sai da pausa. O lote é necessário porque a aba pausada só responde depois de solta.
4. `Runtime.runIfWaitingForDebugger` **não executa JavaScript**: só libera o carregamento que o Chrome segurou. É o único comando que desfaz essa pausa, e por isso entrou na lista de permitidos junto com `Target.setAutoAttach`.

**A aba do Ivson nunca fica presa.** A pausa dura o tempo de ida e volta desses comandos, alguns milissegundos. A soltura sai no mesmo lote da preparação, mesmo que um comando anterior dê erro. Se a conexão cair ou o gravador morrer, o Chrome solta sozinho as abas pausadas. O teste confere que abas novas carregam normalmente depois de um Ctrl+Break e depois de um kill do gravador. Se o Chrome fechar, o gravador tenta reconectar a cada 5 s até o Ctrl+C.

No `sessao.log`, o evento `CONECTADO` de uma aba nova vem com `pausado: true` e `aberta_por` (a aba que a abriu). Isso liga a aba do Imprimir à ficha de origem. O campo `alvo` do `rede-*.jsonl` é o mesmo da aba.

**Teste** (`tests/test_gravador.py`, Chrome descartável e servidor sintético local):

- **Imprimir simulado:** um F1 multipart com `target="_blank"` abre uma aba nova. A 1ª requisição dessa aba no jsonl é o POST do F1, com `nmgp_opcao` da query. Em seguida vêm o `POST /blank_laudo_pdf/`, com `nmgp_opcao` e `funcao` do corpo, e os recursos da página.
- **Redirecionamento em cadeia na aba nova:** POST → 302 → 303 → GET, no mesmo `requestId`, com `status_redirecionamento`.
- **POST de navegação acima de 64 KB** como 1ª requisição da aba.
- **`window.open` de página com iframes:** iframes do mesmo site aninhados, um iframe de outro site e fetches disparados na carga, um deles acima de 64 KB.
- **Não regressão:** aba e iframe de outro site já abertos, navegação só em iframe, `pushState`, resumo com a chave de 4+1 elementos, execução sem `--rede` e encerramento por Ctrl+Break.
- **Conferências:** toda requisição recebida pelo servidor durante a gravação está no jsonl, e nenhum marcador dos corpos de requisição ou de resposta aparece em arquivo gravado. Os comandos que saíram pelo websocket foram interceptados: só os da lista, no navegador só `Target.setAutoAttach`, e em cada aba nova `Network.enable` antes da soltura.
- **Contraprova:** o gravador anterior perdeu as 7 requisições das abas novas nesse mesmo cenário.

**Observação:** em POSTs de navegação (formulário, tipo `Document`), o Chrome 154 entrega o corpo inteiro no evento mesmo acima de 64 KB. Nesses casos, o gravador extrai `nmgp_opcao` e `funcao` normalmente. `corpo_fora_do_evento` aparece nos XHR/fetch acima de 64 KB.

**Privacidade:** as capturas da Etapa B terão dados reais de paciente (nome, CPF, laudos).

- Elas ficam em `%LOCALAPPDATA%\FluxoExames`. Não copie para o OneDrive, para o repositório nem para a Sala.
- Nenhuma captura entra no repositório sem ter sido anonimizada antes. `captures/` também está no `.gitignore`, como segunda barreira.
- Pré-requisito: BitLocker ativo no C: antes da Etapa B.

### 4.1 Opção `--rede`: mapa de operações do ScriptCase

```powershell
python scripts\gravador_passivo.py --rede
```

**Para que serve.** A guarda de `fluxo_exames/guard.py` nega todo POST que não esteja em `POSTS_PERMITIDOS` e bloqueia as operações de gravação em `OPERACOES_SCRIPTCASE_BLOQUEADAS`. No ScriptCase, o que diferencia uma leitura de uma gravação costuma ser o parâmetro `nmgp_opcao`. Nos endpoints `blank_*_funcoes`, que são mistos (o mesmo caminho lê ou grava), a operação vai no campo `funcao`. Com `--rede`, o gravador observa as requisições enquanto o Ivson navega e produz o mapa (método, caminho, `nmgp_opcao`, `funcao`) que alimenta essas listas.

**Como funciona.** Em cada aba ou iframe observado, o gravador envia `Network.enable` (nas abas novas, antes da primeira requisição; ver item 4.2) e processa só três eventos: `Network.requestWillBeSent`, `Network.responseReceived` e `Network.loadingFailed`. Os demais eventos de rede são ignorados, inclusive os que trazem cookies e cabeçalhos extras. Ao ligar o domínio, o gravador zera os buffers de conteúdo do Chrome para essa conexão. É só observação: nenhuma requisição é alterada, bloqueada ou repetida.

**O que grava**, em `captures\rede-AAAA-MM-DD.jsonl` (uma linha JSON por evento):

| Evento | Campos |
|---|---|
| `requisicao` | horário, aba, `requestId`, método, URL completa, tipo do recurso (`Document`, `XHR`, `Fetch`…), `status_redirecionamento` se veio de um redirecionamento, `nmgp_opcao_url`, `nmgp_opcao_corpo`, `funcao_url` e `funcao_corpo` se houver, `tipo_corpo` (só o MIME) quando há corpo, `corpo_fora_do_evento` e `funcao_fora_do_evento` quando o corpo não veio no evento |
| `resposta` | horário, `requestId`, método, URL, tipo, status HTTP |
| `falha` | horário, `requestId`, método, URL, tipo, erro de rede (`net::…`), se foi cancelada |

Os valores de `nmgp_opcao` e de `funcao` são lidos da query string da URL e do corpo de POST `application/x-www-form-urlencoded` que já vem no próprio evento, todos do mesmo `requestWillBeSent`. Do corpo, **só os valores dessas duas chaves** são guardados; o resto é descartado na memória. Corpo JSON, multipart ou outro formato não é analisado: aparece só `tipo_corpo`. Um corpo form-urlencoded grande demais para vir no evento (XHR/fetch acima de 64 KB; nos POSTs de navegação o Chrome manda o corpo inteiro, ver item 4.2) aparece com `corpo_fora_do_evento: true` e `funcao_fora_do_evento: true`: os valores do corpo ficam desconhecidos, e o gravador não vai buscá-lo. Em URLs `data:` fica só o tipo, sem o conteúdo.

**O que NUNCA grava:** corpo de requisição (fora os valores de `nmgp_opcao` e `funcao`), corpo de resposta, cabeçalhos, cookies. O gravador não envia `Network.getResponseBody`, `Network.getRequestPostData` nem qualquer outro comando que busque conteúdo. Todos são recusados pela lista de comandos permitidos.

**Resumo ao parar.** No Ctrl+C, o gravador imprime as tuplas distintas **(método, caminho, `nmgp_opcao`, `funcao`)** desta sessão, com contagem, e soma a sessão ao `captures\rede-resumo.json`. Esse arquivo acumula todas as sessões gravadas com `--rede` na mesma pasta; para recomeçar do zero, apague-o. Cada tupla traz ainda os status HTTP observados (`falha` para erro de rede) e as origens (`https://host`). O caminho não inclui query.

- Em cada tupla, `nmgp_opcao` e `funcao` são o valor do corpo form-urlencoded ou, se o corpo não tem a chave, o da query.
- `funcao: ""` quer dizer ausente, vazio ou não registrado. Um resumo gravado antes da extração de `funcao` (como o da sessão de 26/09) é lido com `funcao = ""` em todas as tuplas e continua somando normalmente. Uma tupla com `funcao: ""` não é evidência de nenhum valor de `funcao`.
- Requisições com `corpo_fora_do_evento` ficam em tuplas à parte, marcadas `corpo_fora_do_evento: true`. Nelas, os valores são só os da query, e o do corpo é desconhecido.

O resumo não decide nada: só evidencia o que foi observado. **Ele é a matéria-prima de `POSTS_PERMITIDOS`, `OPERACOES_SCRIPTCASE_BLOQUEADAS` e `FUNCOES_AJAX_BLOQUEADAS`.** Com `funcao` gravado, a guarda v2 poderá liberar os endpoints `blank_*_funcoes` por (caminho, `funcao`) direto da evidência gravada, sem deduzir o valor do JS das páginas.

**Privacidade.** No MD, URLs podem conter identificadores de paciente ou de atendimento (na query). Por isso o `rede-*.jsonl` recebe a mesma proteção das capturas HTML: fica só em `%LOCALAPPDATA%\FluxoExames\captures` e nunca vai para o repositório, a Sala ou a nuvem. O `rede-resumo.json` não tem query, mas deve ser revisado antes de qualquer trecho dele ser copiado para `guard.py`.

O comportamento foi testado com Chrome descartável e servidor sintético local. O teste cobriu um formulário POST com `nmgp_opcao` na query e no corpo, fetch urlencoded, JSON e multipart, corpo acima de 64 KB, 404, redirecionamento 302 e conexão recusada. Na extensão para `funcao` (Etapa B.2), cobriu também POSTs com `funcao` na query, no corpo e nos dois, `funcao` vazio, corpo acima de 64 KB com `funcao` e a leitura de um resumo antigo sem `funcao`. Nenhum marcador colocado nos corpos de requisição ou de resposta apareceu nos arquivos gravados. O servidor recebeu só as requisições da própria página; nenhuma veio do gravador.

## 5. Parar

Aperte **Ctrl+C** (ou Ctrl+Break) no terminal do gravador. Ele fecha as conexões, grava `FIM` no log e mostra o total de capturas e erros. Com `--rede`, antes disso ele imprime o resumo de rede e salva `rede-resumo.json`. Depois feche o Chrome do projeto, para fechar a porta 9222.

## 6. Checklist da Etapa B — mapeamento com o Ivson presente

**Antes**

- [ ] Autorização explícita do Ivson para esta sessão, registrada na Sala: data, hora e escopo.
- [ ] Só os **2 pacientes de teste** definidos na ATA da Sala (titular e cônjuge). Os identificadores não entram neste repositório.
- [ ] BitLocker ativo no C: (`manage-bde -status C:` como administrador).
- [ ] As capturas antigas com CPF já saíram do OneDrive.
- [ ] Chrome do projeto aberto conforme o item 2. O Ivson faz o login no MD à mão.
- [ ] Gravador rodando **com `--rede`** (itens 3 e 4.1) e mostrando `Conectado`.

**Durante** — quem navega é o **Ivson**. O agente só observa.

1. Agenda do dia, e de outro dia, para ver a navegação por data.
2. Ficha Clínica do paciente de teste: cabeçalho com prontuário, nome, sexo, DN e CPF.
3. SOAP → Subjetivo → Questionário, onde deve ficar o questionário pré-exame.
4. Exames → Laudo, no 1º nível (atendimentos, "Registros em Aberto x de y", "PDF Assinado x de y", cadeado) e no 2º nível (laudos individuais).
5. Abrir um laudo **assinado** e sair por "Voltar". Depois, "Imprimir" com "LAUDO (PDF)", para ver se o PDF entregue é o original assinado ou uma nova impressão.
6. Exames → Resultado e Anexo.
7. Mapa de requisições: a **fonte primária** é o `rede-resumo.json` do gravador com `--rede` (item 4.1), que separa os POSTs por (método, caminho, `nmgp_opcao`, `funcao`).
   - **Encerre o gravador com Ctrl+C, nunca por kill.** Só o Ctrl+C grava o resumo com o status de cada tupla associado pelo `requestId`. Na sessão de 26/09 houve kill, e o resumo reconstruído a partir do jsonl ficou com contagens dobradas e com o status das tuplas `igual` e `ajax_save_ancor` numa tupla gêmea vazia (ver `FASE-0-ETAPA-B.md`, item 1).
   - A ação de tela que gerou cada tupla **não precisa ser anotada à mão**. Ela sai do cruzamento do horário (`ts`) do `rede-AAAA-MM-DD.jsonl` com as linhas `CAPTURA` do `sessao.log` e os quadros de cada snapshot. Basta o Ivson dizer em voz alta, ou na Sala, a sequência que vai seguir.
   - Nos endpoints `blank_*_funcoes`, a operação real vai no campo `funcao`. Na sessão de 26/09 ele foi inferido do JS das capturas; desde a Etapa B.2 o gravador também registra `funcao` (item 4.1).
   - O HAR manual fica **opcional**, só para investigar uma requisição que o resumo não explique (por exemplo, `corpo_fora_do_evento`, parâmetro de operação com outro nome ou o valor de `funcao`): DevTools (F12) → Network → "Preserve log", exportar para `%LOCALAPPDATA%\FluxoExames\captures\AAAA-MM-DD\`. O HAR contém corpos e cookies. Trate-o como captura com PHI e apague-o depois de usar.

   Na sessão de 26/09, os itens 3 (Questionário), 5 (laudo assinado e Imprimir), 6 (Resultado e Anexo) e 8 (sessão simultânea) não foram executados. Eles ficam para a próxima sessão da Fase 0, junto com a validação de `nmgp_opcao=igual` (`FASE-0-ETAPA-B.md`, itens 6.2 e 7).
8. Teste de **sessão simultânea**: com o perfil dedicado logado, o Ivson usa o MD no Chrome pessoal. Anotar se alguma das sessões cai.

- [ ] **Nunca** clicar em Assinar, ASSINAR PDF, Finalizar e Assinar, Salvar, Excluir, Criar, Enviar/Enviar Por, Solicitar ou Ações. Isso vale também para o Ivson durante a gravação.

**Depois**

- [ ] Ctrl+C no gravador e fechar o Chrome do projeto.
- [ ] `git status` limpo neste repositório: nenhuma captura dentro dele.
- [ ] Produzir, **sem dado de paciente**:
  - mapa de telas e seletores;
  - lista dos POSTs demonstrados como leitura, a partir do `rede-resumo.json` (vira `POSTS_PERMITIDOS` em `fluxo_exames/guard.py`);
  - lista das operações de gravação, a partir do `rede-resumo.json` (vira `OPERACOES_SCRIPTCASE_BLOQUEADAS`);
  - textos de botão encontrados;
  - significado de cadeado, "PDF Assinado x de y" e "Registros em Aberto";
  - resultado do teste de sessão simultânea;
  - proveniência do PDF de "Imprimir".
- [ ] Snapshots que forem virar fixture de teste: só depois de anonimizados.
- [ ] Nota na Sala com o resultado e a passagem de bastão.
