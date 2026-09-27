# Fase 1 — Etapa A: coletor do MD e fila (offline)

Coletor somente leitura do Medicina Direta (`fluxo_exames/coletor.py`) e fila persistente (`fluxo_exames/fila.py`), desenvolvidos e testados **sem acessar o MD**: os testes rodam contra um servidor sintético local que reproduz a estrutura do mapa (`FASE-0-ETAPA-B.md`). A validação ao vivo é uma sessão separada, com o Ivson presente (seção 5).

Nenhum dado de paciente aparece aqui nem nos testes. Os pacientes sintéticos são "Paciente A" e "Paciente B", com prontuários 900001 e 900002, DN 01/01/1900 e CPF de zeros.

## 1. Coletor

### 1.1 Conexão

- `Coletor(cdp_url="http://localhost:9222")` conecta por `connect_over_cdp` ao Chrome **dedicado** (perfil `%LOCALAPPDATA%\FluxoExames\chrome-profile`, aberto como em `FASE-0-ETAPA-A.md`). Endereço CDP que não seja `localhost`/`127.0.0.1` é recusado.
- Não abre navegador, não cria contexto e não abre aba. Usa o contexto padrão e a **única** aba do MD em `/menu_inicial/`. Se não houver aba do MD, ou houver mais de uma em `/menu_inicial/`, para.
- `desconectar()` solta o Chrome sem fechá-lo (testado).
- Ordem na conexão: localizar a aba → recusar se houver service worker do MD (a rota não vê as requisições dele) → instalar a rota de rede → **canário** → conferir que a aba está em `/menu_inicial/` (sessão logada).
- **Canário:** a página faz um `POST` para `https://coletor-canario.invalid/`. Se a rota não o intercepta, o coletor para com `guarda_de_rede_inativa`. O host `.invalid` não resolve, então, mesmo com a rota inativa, nada sai para lugar nenhum.

### 1.2 Operações (camada 1)

| Operação | O que faz | Cliques do mapa usados |
|---|---|---|
| `ler_agenda(data)` | Abre "Agendamento" se preciso e carrega o dia com o mesmo GET do calendário (`$('#campotabela').load(grid_agenda_md_calendario.php?dt=…)`, B §2 e §4.1). Lê hora, nome, prontuário, atendimento, título e status. Não lê celular nem observação. | `menu_agendamento` |
| `localizar_paciente(chave)` | Procura na agenda lida por prontuário (só dígitos) ou nome. Nomes iguais com prontuários diferentes: `paciente_ambiguo`. | — |
| `abrir_ficha(linha)` | Volta à agenda pelo menu se ela estiver escondida (recarregando o dia lido), clica no nome e lê a identidade. Prontuário da ficha diferente do da agenda: `ficha_divergente`. | `menu_agendamento`, `agenda_nome` |
| `identidade()` | Prontuário, nome, DN e CPF de `.cabecalho__grupo-info`, **pelo rótulo**. Falta de campo ou formato inesperado: `identidade_incompleta`. | — |
| `listar_atendimentos()` | Exames → Laudo (item localizado pelo texto e por `sc_apl_menu=grid_exames_laudo`), 1º nível, com "Registros em Aberto" e "PDF Assinado" como `(x, y)`. | `menu_laudo` |
| `listar_laudos(atendimento)` | Lápis da linha → `cont_exame_resultado_laudo` → widget `dbifrm_widget3`. Espera o widget estabilizar (o MD o recarrega logo após a 1ª carga). Estado: `aguardando_assinatura` ou `a_confirmar` (laudo assinado ainda não foi observado; C §4). | `menu_laudo`, `laudo_lapis` |
| `abrir_texto_laudo(laudo)` | Link da linha (`ajax_save_ancor` + `igual`) → lê `textarea[name=receituario]` (`defaultValue`, sem tocar no TinyMCE) → confere o id do form com o da linha → **Voltar** (`scFormClose_F6`). Devolve texto, `sha256` e origem `md:laudo:<id>`. | `menu_laudo`, `laudo_lapis`, `laudo_abrir`, `laudo_voltar` |

- Operação fora de `OPERACOES_PERMITIDAS` → `operacao_nao_permitida`. As de `OPERACOES_PENDENTES_VALIDACAO` (paginar, Resultado, Evolução/questionário, pesquisa do questionário, PDF do laudo) → `operacao_pendente`.
- Cada clique precisa de uma operação em curso, de uma chave de `CLIQUES` válida para essa operação e de um alvo único cujo código (`href`, `onclick` ou `item-href`) case com o caminho do mapa. Voltar só é aceito se o `onclick` for **exatamente** `scFormClose_F6('form_paciente_exames_laudos_resultado_fim.php')`.
- **Paginação:** se uma grade tiver controles de paginação (`sc_b_avc*`, `nm_gp_move`…), o coletor para com `paginacao_pendente`, em vez de devolver só a 1ª página. `nmgp_opcao=rec` não está na lista branca (B §9.7).

### 1.3 Rede (camada 2)

- `context.route("**/*")` (Fetch do CDP) passa **toda** requisição da aba, dos iframes e de abas novas por `guard.avaliar_requisicao` (guarda v2, sem alteração) e aborta o que ela nega.
- Bloqueio registrado em `coletor.bloqueios` (método, host, caminho, motivo e operação; nunca query nem corpo).
- Um bloqueio **interrompe** a coleta (`ColetorBloqueado("rede")`, no fim da operação ou antes do próximo clique), salvo:
  - os automáticos do mapa em `BLOQUEIOS_TOLERADOS`: `blank_notifica_lembrete` (POST ao abrir a ficha) e `blank_fecha_atendimento` (GET ao abrir a 2ª ficha). Continuam abortados, mas não param a coleta;
  - hosts de terceiros (telemetria, chat), também abortados.
- Nos testes, `origem_md` aponta para o servidor sintético. A guarda avalia essas URLs como se fossem do MD, e qualquer requisição a `*.medicinadireta.com.br` é abortada (`md_real_em_modo_sintetico`).

### 1.4 Texto (camada 3)

Antes de clicar, o texto visível, `value`, `title`, `aria-label`, `id` e o código do alvo **e do ancestral clicável** passam por `guard.clique_permitido`. Assim, Finalizar e Assinar, Salvar, Excluir, Enviar, ASSINAR PDF, Imprimir, E-MAIL e os demais termos da guarda nunca são clicados.

### 1.5 Riscos residuais (conhecidos)

1. **API síncrona:** a rota só é atendida durante chamadas ao Playwright. Uma requisição que a página dispare enquanto o Python está parado fica **retida** até a próxima chamada; não sai. `desconectar()` drena as pendentes antes de soltar. O que o Chrome faz com uma requisição retida se o processo Python morrer (continua ou falha) **não foi verificado**.
2. **WebSocket** não passa pela rota (notificações e chat do MD). É só leitura de avisos, mas fica registrado.
3. **CSP do MD:** se a política da página bloquear o `fetch` do canário, o coletor não inicia (`guarda_de_rede_inativa`). A falha é segura, mas exige ajuste do canário.
4. **Nomes com termo bloqueado:** um nome como "… Novo" ou "… Sim" na agenda faz `abrir_ficha` parar com `clique_interditado`. A falha é segura; o paciente fica para a coleta manual.
5. **Estado "assinado"** não é reconhecido até a lacuna 1 da Etapa C ser fechada: tudo o que não for "Aguardando assinatura!" sai como `a_confirmar`.

## 2. Fila

`Fila(caminho=None)` abre `%LOCALAPPDATA%\FluxoExames\fila.db` (SQLite, WAL, `synchronous=FULL`).

- **`itens`:** chave natural única (paciente, exame, data), comparada sem acento, sem caixa e com espaços juntos; estado; `retorno`, que é o estado de onde o item entrou em `IDENTIDADE_PENDENTE`.
- **`historico`:** toda transição (de, para, quando).
- **`checkpoints`:** por (item, documento), com `sha256` e situação. `registrar_checkpoint` devolve `False` quando nada mudou, e é isso que permite pular o documento na retomada.
- **Funções:**
  - `inserir` é idempotente e devolve `(item, criado)`;
  - `obter_proximo` pega o mais antigo com trabalho, pulando finais e pausados;
  - `atualizar_estado(item, novo, esperado=None)` valida a transição em `state.py` e faz compare-and-set.
- **Máquina de estados** (`state.py`): a sequência principal, o atalho `LAUDO_DO_DIA_PENDENTE → REVISAO_MEDICA` (exame sem série evolutiva) e o desvio de identidade, que volta só ao estado de origem.
- A fila **não guarda texto de laudo** nem dado clínico, só chave, estado e hashes.

## 3. Testes

```powershell
python -m pip install -r requirements.txt
python -m pytest
```

- `tests/test_coletor.py` precisa de um Chrome ou Chromium. Ele usa o Chrome instalado, ou o caminho em `FLUXO_CHROME`, ou o Chromium do Playwright. Sem nenhum deles, esses testes são pulados.
- Cada teste abre um Chrome **descartável** (headless, perfil temporário, porta de depuração aleatória) e o coletor conecta por CDP, como no uso real. O perfil dedicado e o MD não são tocados.
- **Servidor sintético** (`tests/md_sintetico.py`):
  - menu com iframes, agenda carregada por `$.load` e ficha com cabeçalho, árvore e POSTs automáticos (inclusive os dois tolerados);
  - 1º nível com lápis e cadeado; contêiner com widget recarregado; 2º nível com ASSINAR PDF, Criar Laudo e Voltar;
  - form do laudo com `textarea`, Voltar, Imprimir, E-MAIL, **Finalizar e Assinar** visível e Salvar/Excluir ocultos.
- **Asserção do lado do servidor:** nenhuma requisição recebida pode ser negada pela guarda (`violacoes()`), nem ter assinatura de escrita (`escritas()`: endpoints de escrita, `nmgp_opcao` de gravação, `rs`, `nm_call_php`, `formphp`, multipart, métodos que não sejam GET/POST).

Resultado desta etapa: **183 passed** (128 da guarda, 22 da fila e 33 do coletor).

| Grupo | O que cobre |
|---|---|
| Leitura | Agenda, localização, identidade, 1º nível com contadores e 2º nível com estado. O texto de 3 laudos sai idêntico ao do servidor, com `sha256`. A 2ª ficha exige voltar à agenda pelo menu. `blank_notifica_lembrete` e `blank_fecha_atendimento` são bloqueados e tolerados. |
| Camada 1 | Operações proibidas e pendentes; clique fora de operação; clique de outra operação; chave inexistente. |
| Camada 3 | Finalizar e Assinar, Imprimir, E-MAIL e Enviar Por no form; ASSINAR PDF na lista; armadilha (botão na posição do Voltar que chama Finalizar e Assinar). Em todos, `clique_interditado` e nenhuma requisição nova no servidor. |
| Camada 2 | A página dispara por fora do coletor: `rs` (Finalizar), `alterar` urlencoded e multipart, `PUT`, `blank_laudo_pdf?assinar=S`, cadeado, ASSINAR PDF, Criar Laudo e status da agenda. Tudo é abortado, nada chega ao servidor, e a operação seguinte para com `rede`. |
| Conexão | Canário ativo; CDP não local recusado; sem aba do MD; desconectar não fecha o Chrome. |
| Paginação | A grade com controles para a coleta. |
| Fila | Ciclo completo com histórico, transição inválida, compare-and-set, desvio de identidade, idempotência, checkpoints e retomada. A retomada usa um processo que morre com `os._exit` **no meio de uma transação**: a transação é desfeita, nada duplica e a fila retoma do estado confirmado. |

## 4. O que só a sessão ao vivo confirma

Premissas do mapa que o servidor sintético reproduz, mas que só o MD real confirma:

1. **Menu "Agendamento":** a âncora com `item-href` `sc_apl_menu=blank_div` precisa estar **visível e clicável**. Se estiver dentro de um menu recolhido, o clique falha (`clique_falhou`). Plano B: o Ivson abre a agenda à mão antes, e o coletor usa o quadro existente.
2. **Agenda:** `window.jQuery` existe no quadro `/blank_div/`, e o GET com `dt`, `diaClicado`, `vg_data_ini` e `vg_data_fim` em `aaaa-mm-dd` traz o dia pedido. O formato de `diaClicado` foi inferido.
3. **Volta à agenda:** clicar de novo em "Agendamento" com a ficha aberta mostra a agenda (recarregada ou não).
4. **Árvore da ficha:** o item "Laudo" fica visível sem expandir "Exames".
5. **2º nível:** o link que chama `nm_gp_submit4('/form_paciente_exames_laudos_resultado/'…)` está na mesma `<tr>` do campo `id_sc_field_id_<n>`.
6. **Form do laudo:**
   - o Voltar visível tem `onclick` exatamente `scFormClose_F6('form_paciente_exames_laudos_resultado_fim.php')`;
   - existe `#id_sc_field_id` ou `#id_read_on_id`, com o mesmo número da grade (a grade mostra `nn.nnn`; o coletor compara só dígitos).
7. **Canário e CSP; service worker;** uma única aba do MD em `/menu_inicial/`.
8. **Paginação:** as grades normais não trazem `sc_b_avc*`/`nm_gp_move` escondidos. Se trouxerem, `paginacao_pendente` aparece em todo paciente e o detector precisa considerar só a barra visível.

## 5. Roteiro da validação ao vivo (sessão com o Ivson, ~20 min)

**Antes:**

- BitLocker ativo no C: (pré-requisito do README para o primeiro dado real);
- `python -m pytest` verde;
- Chrome dedicado aberto com `--remote-debugging-port=9222` (`FASE-0-ETAPA-A.md`, item 2);
- **gravador passivo com `--rede`** rodando em paralelo, como testemunha independente da rede.

**Passos.** O Claude opera o REPL e o Ivson confere na tela. Em qualquer `ColetorBloqueado` inesperado, **parar**: não tentar de novo nem contornar, e anotar o motivo.

1. **Ivson:** login manual. Deixar só uma aba do MD, na Home (`/menu_inicial/`). Fechar abas de Imprimir ou PDF, se houver.
2. **Conectar:**
   ```python
   from fluxo_exames.coletor import Coletor
   c = Coletor(); c.conectar(); c.guarda_ativa   # espera True
   ```
   Falhas possíveis: `guarda_de_rede_inativa` (CSP; item 4.7), `aba_md_ambigua` ou `service_worker_md`.
3. **Agenda:** `ag = c.ler_agenda("AAAA-MM-DD")`, num dia com o paciente A. Conferir a quantidade de linhas e a data exibida (itens 4.1 e 4.2). Imprimir só `len(ag)` e horários.
4. **Ficha A:** `c.abrir_ficha(c.localizar_paciente("<prontuário A>"))`. O Ivson confere nome, DN e CPF com o cabeçalho.
5. **1º nível:** `ats = c.listar_atendimentos()`. Conferir a quantidade e os contadores "x de y" com a grade.
6. **2º nível e texto:**
   ```python
   ls = c.listar_laudos(ats[0])
   r = c.abrir_texto_laudo(ls[0])
   ```
   Conferir que a tela voltou à lista e que `len(r["texto"])` bate com o texto visível. Rodar de novo e comparar o `sha256` (deve ser idêntico, como na sessão C).
7. **Ficha B (2ª ficha seguida):** `c.abrir_ficha(c.localizar_paciente("<prontuário B>"))`. Valida a volta à agenda (4.3) e fecha a lacuna 6 da Etapa C: com `blank_fecha_atendimento` bloqueado, a ficha B abre normalmente?
8. **Bloqueios:** `c.bloqueios` só pode ter os tolerados e terceiros. Depois, `c.desconectar()`.
9. **Depois:**
   - Ctrl+C no gravador e `python scripts/repassar_rede.py <rede-AAAA-MM-DD.jsonl>`. Nenhum POST do período do coletor pode ser negado; se algum foi, a rota falhou;
   - o Ivson confere nas grades que "Registros em Aberto", "PDF Assinado" e "Abertura do Registro" não mudaram.

**Resultado esperado:** um relatório `FASE-1-ETAPA-B.md` com o que se confirmou nos itens 4.1–4.8 e os ajustes de seletor, se algum for necessário. Qualquer ajuste que afrouxe um bloqueio segue a regra da guarda: evidência gravada primeiro.
