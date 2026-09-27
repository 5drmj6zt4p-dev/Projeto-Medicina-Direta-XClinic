# Fase 0 — Etapa B: mapa de leitura do MD

Mapa do caminho de leitura do Medicina Direta (MD), montado a partir de duas sessões gravadas: a da Etapa B (26/09/2026) e a da Etapa C (27/09/2026). Serve de base para o coletor da F2 e para a guarda de `fluxo_exames/guard.py` (versão 2 desde a Etapa C). O relatório da segunda sessão, por lacuna, está em `FASE-0-ETAPA-C.md`.

Este documento não contém dado de paciente. Os dois pacientes de teste aparecem como **paciente A** e **paciente B**. Valores de `script_case_init`, ids internos e hashes aparecem como `<n>`, `<id>` e `<md5>`. As seções 1 a 8 descrevem a sessão B, com notas da sessão C onde ela mudou a conclusão; a seção 9 traz o que a sessão C acrescentou.

## 1. Sessões e material

| Item | Sessão B | Sessão C |
|---|---|---|
| Quando | 26/09/2026, 19:44–19:49 | 27/09/2026, 10:09–10:17 |
| Quem navegou | Ivson, no Chrome dedicado, com `gravador_passivo.py --rede` | Idem; encerramento por Ctrl+C |
| Escopo | login → agenda (dia atual e outro dia) → ficha do paciente A → Exames → Laudo (1º e 2º nível, 3 laudos abertos) → ficha do paciente B → o mesmo caminho | login → agenda → ficha do paciente A → Questionário → Exames → Laudo (3 laudos, cada um aberto 2 vezes; ASSINAR PDF visualizado; Imprimir 3 vezes) → Exames → Resultado (2 aberturas) → Anexo (documentos e imagens) → Evolução (1 registro aberto e impresso) |
| Capturas HTML | 588 arquivos em 31 snapshots | 927 arquivos em 41 snapshots |
| Rede | `rede-2026-09-26.jsonl`: 4.093 eventos (2.022 requisições, 2.068 respostas, 3 falhas) | `rede-2026-09-27.jsonl`: 5.141 eventos (2.570 requisições, 2.569 respostas, 2 falhas) |
| Resumo | 436 tuplas, reconstruído pelo Hermes (sessão encerrada por kill); arquivado como `rede-resumo-sessao1-B.json` | `rede-resumo.json` nativo: 597 tuplas, `sessoes=1`, chave (método, caminho, `nmgp_opcao`, `funcao`) |

A análise foi feita só sobre esses arquivos. Ninguém acessou o MD.

**O resumo reconstruído tem dois artefatos.** O gravador, no Ctrl+C, associa cada resposta à tupla da requisição pelo `requestId`. A reconstrução contou requisições e respostas como linhas independentes. Por isso:

- a `contagem` de cada tupla é o dobro do número de requisições;
- as tuplas com `nmgp_opcao` (`igual` e `ajax_save_ancor`) ficaram **sem status**, e o status foi parar numa tupla gêmea com `nmgp_opcao` vazio.

Conferido no jsonl: as 20 tuplas POST do resumo são 18 tuplas reais e **66 requisições POST**. Todas receberam 200 (ou 204, nas de terceiros), inclusive as 6 com `nmgp_opcao=igual` e as 6 com `ajax_save_ancor`. Nenhum POST falhou. As 3 falhas foram GETs: um favicon bloqueado por ORB e duas recargas de widget canceladas pelo próprio navegador.

## 2. Sequência navegada → endpoints

Horários aproximados (hh:mm:ss), tirados do jsonl e do `sessao.log`.

| Hora | Ação na tela | Requisições | Resultado |
|---|---|---|---|
| 19:45:22–34 | Login | `POST /login_sha/login_sha.php` ×7 (XHR); `POST /login_autenticar/login_autenticar.php` ×1 | `GET /menu_inicial/?script_case_init=<n>&nmgp_url_saida=/login_autenticar/` (aba principal) |
| 19:45:36–37 | Carga do menu | GET dos iframes `blank_notificacao_icon`, `_div` e `_card`; `GET /home/home.php?nm_run_menu=1&nm_apl_menu=menu_inicial&script_case_init=1`; `GET blank_funcoes_atendimento.php?funcao=login_pendencia`; POSTs `blank_notificacao_funcoes` ×5, `blank_menu_inicial_funcoes` ×1, `blank_home_funcoes` ×4 | Home e notificações |
| 19:46:33 | Menu → Agendamento | `GET /menu_inicial/menu_inicial_form_php.php?sc_item_menu=item_31&sc_apl_menu=blank_div&…` → `POST /blank_div/` | Contêiner da agenda |
| 19:46:35–42 | Agenda do dia | `GET blank_calendario_agenda.php?dia&mes&ano`, `GET ctr_calendario.php`, `GET grid_agenda_md_calendario.php` ×2 (XHR) | Grade da agenda dentro de `div#campotabela` |
| 19:46:46 | Outro dia no calendário | `GET blank_calendario_agenda.php?…&atualiza_dia_clicado=S`; `GET grid_agenda_md_calendario.php?p_zerar_id_paciente=S&vg_redir_form=N&dt=<aaaa-mm-dd>&diaClicado=…&vg_data_ini=…&vg_data_fim=…&vg_limpar_filtro_calendario=S` | Grade do outro dia |
| 19:46:54 | Clique no nome do paciente A | `GET /treemenu_paciente/?nmgp_parms=@SC_par@<n>@SC_par@grid_agenda_md_calendario@SC_par@<md5>&nm_run_menu=1&nmgp_opcao=&script_case_init=<n>`; `POST blank_sessao_funcoes`; `GET treemenu_paciente_form_php.php?sc_item_menu=treemenu_paciente&sc_apl_menu=blank_treemenu_paciente&…`; `POST blank_notifica_lembrete`; `POST /blank_treemenu_paciente/`; GETs `menu_info_comp.php`, `form_paciente_sbis.php`, `grid_historico_evolucao.php`, `grid_paciente_completo_foto.php`; `POST blank_treemenu_paciente_funcoes`; `GET blank_aviso.php?tipo=atualiza_aviso` | Ficha Clínica com cabeçalho, árvore de menus, Dados Gerais e histórico |
| 19:47:13 | Exames → Laudo | `GET treemenu_paciente_form_php.php?sc_item_menu=item_165&sc_apl_menu=grid_exames_laudo&…` → `POST /grid_exames_laudo/`; 7 × `GET NM_Blank_Page.htm` (iframes de ligação vazios) | Laudo, 1º nível |
| 19:47:19–26 | Lápis de um atendimento | `POST /cont_exame_resultado_laudo/` (`nmgp_opcao` vazio) → `GET /grid_paciente_exames_laudos_resultado/?script_case_init=<n>&under_dashboard=1&dashboard_app=cont_exame_resultado_laudo&own_widget=dbifrm_widget3&…` e `GET /grid_exames_resultados_laudo/?…&own_widget=dbifrm_widget5&…`. O widget 3 é recarregado com um parâmetro de maximizar; a primeira carga é cancelada (`ERR_ABORTED`) | Laudo, 2º nível |
| 19:47:32 → 19:48:20 | Abrir laudo e Voltar (×3) | `POST …/grid_paciente_exames_laudos_resultado/index.php` `nmgp_opcao=ajax_save_ancor` (XHR) → `POST /form_paciente_exames_laudos_resultado/` `nmgp_opcao=igual`; no Voltar, `POST …/form_paciente_exames_laudos_resultado_fim.php` → `POST /grid_paciente_exames_laudos_resultado/` | Form do laudo e volta para o 2º nível |
| 19:48:22 | Voltar no 2º nível | `GET /grid_exames_laudo/grid_exames_laudo.php` (`window.open(…, '_parent')`) | 1º nível |
| 19:48:45 | Ficha do paciente B | As mesmas requisições das 19:46:54, **mais `GET /blank_fecha_atendimento/blank_fecha_atendimento.php?tipo=t`**, emitido pelo HTML do treemenu | Ficha do paciente B |
| 19:48:58 → 19:49:43 | Laudo, 1º e 2º nível, 3 laudos | As mesmas requisições das 19:47:13 às 19:48:22 | Igual ao paciente A |

## 3. Estrutura do ScriptCase

### 3.1 Árvore de quadros

A URL da aba principal fica em `/menu_inicial/` a sessão inteira. Todo o conteúdo troca dentro de iframes:

```
aba /menu_inicial/
├─ iframe#iframe_menu_inicial   name=menu_inicial_iframe           → /home/home.php
├─ iframe#iframe_item_31        name=menu_inicial_item_31_iframe   → /blank_div/  (agenda; grade em div#campotabela)
├─ iframe#iframe_notificacao, #iframe_icon_notificacao, #iframe_card   (notificações)
└─ iframe#iframe_treemenu_paciente  name=menu_inicial_treemenu_paciente_iframe → /treemenu_paciente/?nmgp_parms=…  (Ficha Clínica)
   ├─ iframe#iframe_treemenu_paciente name=treemenu_paciente_iframe          → form_paciente_sbis.php  (Dados Gerais)
   ├─ iframe#iframe_item_165          name=treemenu_paciente_item_165_iframe → /grid_exames_laudo/  (1º nível)
   │                                                                          → /cont_exame_resultado_laudo/  (2º nível)
   │   ├─ iframe#id-iframe-0 name=dbifrm_widget3 → /grid_paciente_exames_laudos_resultado/ → /form_paciente_exames_laudos_resultado/
   │   └─ iframe#id-iframe-1 name=dbifrm_widget5 → /grid_exames_resultados_laudo/  (Resultado)
   └─ iframe#frame_historico_prontuario → menu_info_comp.php → grid_historico_evolucao.php
```

O id `iframe_treemenu_paciente` aparece em dois níveis. O coletor deve localizar os quadros pelo `name` ou pela URL, nunca só pelo id.

Cada item de menu segue o mesmo padrão: uma âncora com `item-href="<menu>_form_php.php?sc_item_menu=item_N&sc_apl_menu=<app>&sc_apl_link=/&sc_usa_grupo="` e `item-target="<nome do iframe>"`. O GET desse endereço devolve uma página que faz o POST automático para `/<app>/`. Por isso há POSTs de navegação pura (`blank_div`, `blank_treemenu_paciente`, `grid_exames_laudo`).

### 3.2 Parâmetros

| Parâmetro | Papel observado |
|---|---|
| `nmgp_parms` | Parâmetros da ligação entre aplicações. Apareceu em três formatos:<br>**(a)** `@SC_par@<n>@SC_par@<app de origem>@SC_par@<md5>`, na agenda → ficha e nos links do 2º nível → form. O `<md5>` só aponta para parâmetros guardados na sessão do servidor, e o id do paciente não viaja na URL. O primeiro número foi o mesmo nos dois pacientes, mas o `<md5>` mudou. **Consequência:** o coletor não consegue montar essas URLs. Precisa clicar no link que a grade gerou na mesma sessão.<br>**(b)** `var?#?valor?@?var?#?valor?@?`, no 1º nível → contêiner (`OrScLink?#?1?@?vg_exames_resultados?#?<id>?@?vg_id_exame?#?<id>?@?`, ids internos em claro). É também o formato em que os botões PHP escondem a operação: `nmgp_opcao?#?formphp?@?nm_call_php?#?email?@?`.<br>**(c)** `var*scinvalor*scout`, na mensagem do cadeado. |
| `script_case_init` | Id da instância da aplicação na sessão do ScriptCase. Cada app aberto ganha um número (a home sempre recebe `1`; os widgets do contêiner ganham números novos a cada abertura). Vai na query dos GETs e em campos ocultos dos formulários F1–F6. O contêiner repassa o número aos widgets por `parent.scIframeSCInit`. |
| `nm_run_menu=1`, `nm_apl_menu=<menu>` | Indicam que o app foi aberto por um menu (`home.php`, `grid_historico_evolucao.php`, `treemenu_paciente`). O ScriptCase usa isso para decidir para onde sair. |
| `nmgp_opcao` | Operação pedida ao app. Na sessão só apareceram três valores: vazio, `igual` (form do laudo) e `ajax_save_ancor` (grade do 2º nível). |
| `nmgp_url_saida` | Para onde o app volta ao sair. É preenchido pelo link de origem. |
| `csrf_token` | Campo oculto em F1/F3/F4 das grades e dos forms. |
| `rs`, `rst`, `rsargs[]` | Chamadas sajax do form (`validate_*`, `event_*_onchange`, `event_scajaxbutton_finalizar_assinar_onclick`, `submit_form`, `navigate_form`), feitas para a própria URL do form, por GET ou POST. Nenhuma ocorreu na sessão. |

Os formulários ocultos das páginas ScriptCase têm papéis fixos:

- nos forms: F1 é o formulário principal (campos e `csrf_token`), F2 é a navegação (`nm_move`), F3 são os links, F5 recarrega com `igual` e F6 é a saída (`…_fim.php`);
- nas grades: F3 são os links, F4 é a paginação (`nmgp_opcao=rec`), F5 é a pesquisa e Fprint é a impressão.

## 4. Telas-chave

### 4.1 Agenda

- **Quadro:** `name=menu_inicial_item_31_iframe`, URL `/blank_div/`. A grade vem por `$('#campotabela').load("../grid_agenda_md_calendario/grid_agenda_md_calendario.php?…")`, com datas `aaaa-mm-dd` em `dt`, `diaClicado`, `vg_data_ini` e `vg_data_fim`.
- **Linhas:** cada campo tem id `id_sc_field_<campo>_<n>`. Campos: `cmp_hora_ini` (Hora), `c_nome` (Nome), `cmp_img` (Pront), `c_celular`, `cmp_atendimento`, `a_titulo` (Título), `cmp_status_email`, `cmp_status_sms`, `cmp_observacao`, `e_ds_agenda_status` (Status), `cmp_chegada` (Chegou), `cmp_espera`, `cmp_atendido` (Atendido) e colunas sem rótulo (orçamento, tratamento, pagamento, log).
- **Link para a ficha:** `a#id_sc_field_c_nome_<n>`, com `href="javascript:nm_gp_submit5('/treemenu_paciente/', '/grid_agenda_md_calendario/', '@SC_par@…', '_blank', …)"`. O menu intercepta o link e abre a ficha no iframe `menu_inicial_treemenu_paciente_iframe`.
- **Perigo:** as colunas de status e chegada e as ações da linha chamam `blank_notificacao_funcoes` com `funcao=alteracao_agenda`, `blank_status`, `blank_desmarcar` e `blank_videochamada_funcoes`. O coletor não clica nelas.

### 4.2 Ficha Clínica (`treemenu_paciente`)

- **Quadro:** `name=menu_inicial_treemenu_paciente_iframe`, URL `/treemenu_paciente/?nmgp_parms=@SC_par@…`.
- **Identidade do paciente (cabeçalho):** fica em `.cabecalho .cabecalho__grupo-info`. Cada grupo tem um par `a.cabecalho__campo-nome` (rótulo) + `a.cabecalho__campo-valor` (valor). Rótulos: `Prontuário:`, `Nome:`, `Sexo:`, `Data de Nascimento:`, `Idade:`, `CPF:`, `Convênio:`, `Nº Carteirinha:`, `Validade:`, `E-mail:`, `CEL.:`, `Endereço:`.
  - Formatos: DN em `dd/mm/aaaa`, CPF com 11 dígitos sem pontuação, prontuário numérico.
  - Ler **pelo rótulo**, não pela posição. No paciente B, o rótulo do e-mail veio vazio.
  - Três valores (convênio, carteirinha, validade) repetem `id="id_titulo_atend"`. Não use esse id.
- **Alternativa:** `form_paciente_sbis.php` (Dados Gerais), no iframe `treemenu_paciente_iframe`. É um form **em modo de edição** (`id_sc_field_cpf`, `id_sc_field_datadenascimento`…), com o CPF pontuado. Prefira o cabeçalho.
- **Árvore de menus (jstree):** âncoras `id="item_N"` com `item-href="treemenu_paciente_form_php.php?sc_item_menu=item_N&sc_apl_menu=<app>…"`.
  - Itens desta conta: Dados Gerais (17), Linha do Tempo (142), Dashboard (146), Atendimento (127), Painel Clínico (107), Formulário Dinâmico (119), Evolução (19), Alergias (71), Medicamento em Uso (99), Problemas (70), Dor (151), Receitas (45), Formulários (86), Mevo (144), Contestação (200), Imprimir SOAP (139) e Restrição de Acesso (105).
  - Subitens do SOAP: Subjetivo (128), Objetivo (199), Avaliação (130) e Plano (131).
  - Subitens de Exames: Solicitação (163), Resultado (164) e **Laudo (165)**.
  - Localize o item pelo texto e pelo `sc_apl_menu`. O número do item é configuração e pode mudar.

### 4.3 Laudo, 1º nível (`grid_exames_laudo`)

- **Quadro:** `name=treemenu_paciente_item_165_iframe`. A URL é `/grid_exames_laudo/` (POST do menu) ou `/grid_exames_laudo/grid_exames_laudo.php` (GET, na volta). O `<title>` é "Laudo".
- **Uma linha por atendimento.** Campos `id_sc_field_<campo>_<n>`:
  - `cmp_ligacao`: lápis, com o link para o 2º nível;
  - `id`;
  - `cmp_atendimento_versao` (Atend., com tooltip "Versão: n");
  - `cmp_data_evento` (Data Evento, `dd/mm/aaaa hh:mm UTC-3`);
  - `cmp_receituario_hint` (Título);
  - `cmp_status` (Status; link GET `grid_exames_laudos_fase.php?vg_id_exames_laudos=<id>`);
  - `cmp_usuario` (Profissional);
  - `qtd_aberto` (**Registros em Aberto**, "x de y");
  - `qtd_assinado_pdf` (**PDF Assinado**, "x de y");
  - `cmp_editavel` (cadeado);
  - `cmp_status_assinatura`.
- **Link para o 2º nível:** `a#id_sc_field_cmp_ligacao_<n>` → `nm_gp_submit5('/cont_exame_resultado_laudo/', '/grid_exames_laudo/', 'OrScLink?#?1?@?vg_exames_resultados?#?<id>?@?vg_id_exame?#?<id>?@?', '_self', …)`. O link não tem texto nem `title`. O aviso "Editar o Registro" existe só no `onmouseover`.
- **Barra:** "Vincular Solicitação" abre `form_visualizar_exames_resultados` em modal. Não clicar.
- **O que se observou:**
  - Em "x de y", y é o número de laudos do atendimento. Todos os atendimentos dos dois pacientes estavam "0 de n" nas duas colunas: nenhum registro aberto e nenhum PDF assinado.
  - O link do cadeado abre um aviso ("Apenas o profissional que gerou o registro pode fechá-lo") quando o registro é de outro profissional.
  - No código da página, o cadeado chama `fn_js_editavel` → `POST ../blank_editavel/blank_editavel.php`, que troca o ícone entre aberto e fechado. Isso é **escrita**.
  - O significado exato de cadeado aberto no 1º nível com "0 de n" em aberto fica **a confirmar**.

### 4.4 Laudo, 2º nível (`cont_exame_resultado_laudo`)

- **Contêiner:** substitui o 1º nível no mesmo iframe `treemenu_paciente_item_165_iframe` e carrega dois widgets por GET.
  - `iframe#id-iframe-0` (`name=dbifrm_widget3`) → `grid_paciente_exames_laudos_resultado`, com o `<title>` "Consulta - tbl_paciente_exames_laudos". É a **lista de laudos**.
  - `iframe#id-iframe-1` (`name=dbifrm_widget5`) → `grid_exames_resultados_laudo`, com o `<title>` "Resultado". Campos: `descricao`, `data_evento`, `resultado_arq`, `realizado`, `id_laboratorio` e `cmp_exame`.
- **Colunas da lista de laudos:**
  - `id` (ID `nn.nnn`), `cmp_descricao` (Título), `realizado`, `data`, `profissional`;
  - `cmp_dados_titulo` e `cmp_dados_profissional` (versões agrupadas);
  - `id_laboratorio` e `laudo_arq` (Documento);
  - `cmp_assinar` ("ASSINAR PDF", que chama `fn_js_assinatura_pdf_lc`, ou "Registro de outro profissional");
  - `cmp_pdf` (tooltip "Aguardando assinatura!");
  - `cmp_status_assinatura`;
  - `cmp_editavel` (`img#imagem<id>`: cadeado fechado, com tooltip "Abertura do Registro" e data e hora).
- **Abrir um laudo:** o link da linha chama `nm_gp_submit4('/form_paciente_exames_laudos_resultado/', '/grid_paciente_exames_laudos_resultado/', '@SC_par@…', '_self', '', 'form_paciente_exames_laudos_resultado', '<âncora>')`. A função faz `ajax_save_ancor` e depois submete F3 com `nmgp_opcao=igual`.
- **Barra:**
  - "Voltar" (`sc_btn_voltar_js_top`) abre `grid_exames_laudo.php` no `_parent`, ou `grid_controle_registro_aberto.php` se a aba ativa for a de registros em aberto.
  - "Criar Laudo" → "Interno - Em Branco" faz `POST /form_paciente_exames_laudos_resultado/index.php` com `nmgp_opcao` vazio. "Interno - Utilizar Modelo" abre `grid_laudo_utilizar_modelo_resultado`.
  - "Enviar por" → "COPIAR LINK".
- **Estado na sessão:** 3 laudos por paciente, todos "Aguardando assinatura!", sem documento anexado e com o cadeado fechado. Os do paciente B mostravam "Registro de outro profissional".
- **O texto do laudo não está nesta grade.** Ela tem só título, datas, profissional e estado.

### 4.5 Formulário do laudo (`form_paciente_exames_laudos_resultado`)

- **Quadro:** `name=dbifrm_widget3`, no lugar da lista. Chega por `POST …/form_paciente_exames_laudos_resultado/` com `nmgp_opcao=igual`. O `<title>` é "Atualização - tbl_paciente_exames_laudos".
- **Campos (F1):**
  - `id` (só leitura), `descricao` (Título), `data`, `hora`, `utc`;
  - `cmp_id_receitas_config`/`id_receitas_config` (Configuração de Impressão), `tipo_impressao`;
  - `cmp_modelo` (Modelo, desabilitado);
  - **`receituario` (rótulo "Descrição")**;
  - `id_laboratorio`, `laudo_arq_nome`, `laudo_arq` (upload);
  - `laudo_obs` (Descrição / Observação, TinyMCE);
  - `realizado`, `profissional`.
- **Texto do laudo:** está em `textarea#id_sc_field_receituario` (`name=receituario`), editado pelo TinyMCE `receituario_ifr`. O outerHTML traz o HTML do laudo escapado dentro do textarea, então dá para ler o valor do textarea sem tocar no editor. O início do texto repete a identificação do paciente, o que serve para conferir a identidade.
- **O form abre em modo de edição,** mesmo para laudo fechado e de outro profissional: os spans `id_read_on_*` ficam ocultos e os inputs, visíveis.
  - Botões visíveis: "Voltar", "Imprimir" (`imprimir_normal`: F1 com `nmgp_parms=nmgp_opcao?#?formphp?@?nm_call_php?#?imprimir_normal?@?`, alvo `_blank`), "Enviar Por" → "E-MAIL" (o mesmo mecanismo, com `email`) e **"Finalizar e Assinar"** (sajax `event_scajaxbutton_finalizar_assinar_onclick`).
  - Botões ocultos: "Salvar" (`nm_atualiza('alterar')`), "Excluir" (`nm_atualiza('excluir')`), "Novo" (`nm_move('novo')`), "SMS", "COPIAR LINK" (`blank_receita_funcoes`, `funcao=copiar_link`) e o "Imprimir" do assinado.
- **Voltar:** `scFormClose_F6('form_paciente_exames_laudos_resultado_fim.php')`. F6 leva só o `script_case_init`.

### 4.6 Questionário

**Sessão B: não capturado.** **Sessão C: tela mapeada, respostas encontradas na Evolução** (ver 9.2 e 9.6).

## 5. Mapa REQUEST → RESPOSTA dos POSTs

Contagens reais (requisições), todas com status 200, salvo onde indicado. O tipo de resposta foi confirmado pelo snapshot, para os documentos, ou pelo tratamento no JS da página, para os XHR. O gravador não guarda `Content-Type` nem corpo de resposta.

| POST | Operação no corpo | Nº | Tipo | Resposta | Classificação |
|---|---|---|---|---|---|
| `/login_sha/login_sha.php` | (form de login) | 7 | XHR | Validação e envio do login | Fora da lista: o login é manual, antes de instalar a guarda |
| `/login_autenticar/login_autenticar.php` | — | 1 | XHR | Autenticação; em seguida, GET `/menu_inicial/` | Fora da lista, idem |
| `/blank_notificacao_funcoes/…php` | `funcao` = `qtd_novo`, `cards_novos`, `cards_visualizados`, `cards_favoritos` (inferido do JS; **gravado na sessão C**, mais `buscar_sala_usuario`) | 5 | XHR | Número e fragmentos HTML (`innerHTML`); JSON de salas | **Liberado por valor de `funcao`** |
| `/blank_home_funcoes/…php` | `funcao` = `m_botoes_suporte`, `m_frases`, `m_noticias` (inferido; **gravado na sessão C**) | 4 | XHR | JSON | **Liberado por valor** |
| `/blank_menu_inicial_funcoes/…php` | v1 inferiu `m_obter_favoritos`; **a sessão C gravou `m_token_sessao`** | 1 | XHR | JSON do estado da sessão | **ALTERADO v1→v2:** liberado só `m_token_sessao` com `acao=consultar`; `m_obter_favoritos` saiu |
| `/blank_div/` | — | 1 | Document | Contêiner da agenda (HTML) | **Liberado** |
| `/blank_sessao_funcoes/…php` | `funcao=limpar_sessao_aplicacoes` | 2 | XHR | Ignorada pelo JS | **Liberado** (estado de sessão) |
| `/blank_notifica_lembrete/…php` | ids de organização, usuário e paciente | 2 | XHR | JSON que vira notificação na tela | **Fora da lista** (efeito no servidor desconhecido; não é necessário) |
| `/blank_treemenu_paciente/` | — | 2 | Document | Página transitória que carrega Dados Gerais | **Liberado** |
| `/blank_treemenu_paciente_funcoes/…php` | `funcao=config_itens_historico` | 2 | XHR | JSON de configuração | **Liberado** |
| `/grid_exames_laudo/` | — | 2 | Document | Grade do 1º nível (HTML) | **Liberado** |
| `/cont_exame_resultado_laudo/` | `nmgp_opcao` vazio | 2 | Document | Contêiner com 2 widgets (HTML) | **Liberado** |
| `/grid_paciente_exames_laudos_resultado/index.php` | `nmgp_opcao=ajax_save_ancor` | 6 | XHR | Resposta curta; no retorno, o JS submete F3 | **Liberado** (ver 6.1) |
| `/form_paciente_exames_laudos_resultado/` | `nmgp_opcao=igual` | 6 | Document | Form do laudo em modo Atualização (HTML) | v1: bloqueado, pendente. **ALTERADO v1→v2: liberado só nesse caminho** (ver 6.2) |
| `…/form_paciente_exames_laudos_resultado_fim.php` | — (F6) | 6 | Document | Página de saída que devolve para a grade | **Liberado** |
| `/grid_paciente_exames_laudos_resultado/` | — | 6 | Document | Grade do 2º nível recarregada (HTML) | **Liberado** |
| `h.clarity.ms/collect` | — | 8 | Other | 204 | Fora da lista (telemetria de terceiro) |
| `api.etternum.com.br/online/negotiate` | — | 3 | XHR | Negociação do chat de terceiro | Fora da lista |

"Inferido do JS" quer dizer que o gravador guardou o POST sem o valor de `funcao`, porque só extrai `nmgp_opcao`. O valor foi deduzido das chamadas `$.post` automáticas presentes nas capturas. O mesmo endpoint também recebe valores de escrita, então a guarda libera **por valor de `funcao`**, e nunca o endpoint inteiro.

Desde a Etapa B.2, o gravador registra `funcao` (`funcao_url` e `funcao_corpo` no jsonl) e o `rede-resumo.json` passou a separar as tuplas por (método, caminho, `nmgp_opcao`, `funcao`); ver `FASE-0-ETAPA-A.md`, item 4.1. **Na sessão C os valores foram gravados** e a guarda v2 libera (caminho, `funcao`) a partir deles. Duas deduções da v1 estavam erradas ou incompletas: o 5º POST de notificações era `buscar_sala_usuario`, e o POST de `blank_menu_inicial_funcoes` era `m_token_sessao`, não `m_obter_favoritos`. Os POSTs novos da sessão C estão na seção 9.1.

## 6. Classificação das operações duvidosas

### 6.1 `ajax_save_ancor` — benigno, liberado

- Em `nm_gp_submit3` e `nm_gp_submit4` da grade, quando há âncora e o alvo é `_self`, o JS chama `ajax_save_ancor("F3", ancora)` em vez de `document.F3.submit()`. A função está no JS externo da grade, que não foi capturado. No retorno, ela submete F3.
- A âncora é só o índice da linha clicada (1, 2 ou 3). Serve para a grade rolar de volta até ela.
- As grades de 1º e 2º nível ficaram idênticas antes e depois das 6 chamadas. A comparação cobriu contagens "x de y", status, cadeados e tooltips de abertura; só mudou o overlay "Processando".
- Conclusão: é estado de interface na sessão. Liberado, mas só nesse caminho e com esse valor.

### 6.2 `nmgp_opcao=igual` no form do laudo — ALTERADO v1→v2: liberado só no form do laudo

**Decisão da v1 (sessão B): bloqueado, pendente de validação.** O texto abaixo, até "Validação proposta", registra a análise da v1. A validação foi feita na sessão C; o resultado está no fim desta seção.

A favor de leitura:

- No ScriptCase, `igual` é a opção que o link da grade usa por padrão para abrir o registro pela chave. `nm_gp_submit4` usa `igual` quando o link não traz opção; `nm_move('apl_detalhe')` e `modal_igual` também caem em `igual`.
- As gravações do form usam outros valores (`incluir`, `alterar`, `excluir`, via `nm_atualiza`) ou sajax.
- Depois das 6 aberturas (3 por paciente), com saída por Voltar, nenhuma coluna das grades mudou.

Contra, e por isso a dúvida é razoável:

- o form abre em modo **Atualização**, com campos editáveis e "Finalizar e Assinar" visível, inclusive em laudo fechado e de outro profissional;
- o evento de carga do lado do servidor não é observável pelo gravador (log de acesso, trava de edição etc.);
- o mesmo endpoint recebe as gravações.

Decisão: **bloqueado** em `OPERACOES_SCRIPTCASE_BLOQUEADAS` e registrado em `OPERACOES_PENDENTES_VALIDACAO`. Consequência: com a guarda v1, **o coletor não chega ao texto do laudo.**

Validação proposta para a próxima sessão:

1. abrir 1 laudo do paciente A e comparar, antes e depois, as grades e o histórico de alterações do registro, se o MD tiver um;
2. procurar uma via só de leitura para o texto: `form_visualizar_exames_resultados`, "Imprimir" ou o próprio histórico.

**Resultado da validação (sessão C) e decisão v2.** Os 3 laudos do paciente A foram abertos 2 vezes cada (6 `igual`, todos 200), com Voltar entre as aberturas:

- o texto do laudo (`textarea` `receituario`) saiu **idêntico byte a byte** entre a 1ª e a 2ª abertura de cada laudo; os demais campos de F1 só diferiram em `script_case_init`, `param_seq` e ids aleatórios do TinyMCE;
- as grades de 1º e 2º nível ficaram **idênticas campo a campo** antes e depois de todas as aberturas: "Registros em Aberto 0 de n", "PDF Assinado 0 de n", versão do atendimento, status, cadeado e a data e hora do tooltip "Abertura do Registro". Abrir o form não conta como registro em aberto nem muda a abertura do registro;
- a carga do form não dispara nenhuma requisição XHR ou POST;
- o item 2 também foi feito: "Imprimir" não é via só de leitura (seção 9.3).

O que resta sem observação é um efeito só do lado do servidor que não apareça em nenhum campo, grade ou tooltip, como um log de acesso. Nenhuma sessão gravada consegue ver isso; só o suporte do MD pode responder. A guarda segue bloqueando tudo o que o form pode fazer (`alterar`, `incluir`, `excluir`, `rs`, `nm_call_php`, `formphp`, corpo multipart, cliques de Salvar/Finalizar/Imprimir).

Decisão v2: **`igual` liberado só em `POST /form_paciente_exames_laudos_resultado/`** (entrada `laudo_form_abrir`, com `libera`). Em qualquer outro caminho, por GET ou embutido em `nmgp_parms`, `igual` continua bloqueado. Com isso o coletor lê o texto do laudo no `textarea`.

### 6.3 `blank_fecha_atendimento` — bloqueado, pendente

- É um GET automático (`?tipo=t`) na abertura da ficha do paciente B, gerado pelo HTML do treemenu.
- O menu também tem uma variante `tipo=f` quando um atendimento iniciado fica sem a aba da ficha.
- O coletor nunca inicia atendimento. Fechar um atendimento do Ivson aberto em outra sessão seria efeito colateral.
- Está em `ENDPOINTS_BLOQUEADOS`, que vale também para GET.

### 6.4 Outros bloqueios por endpoint (qualquer método)

São endpoints de assinatura, PDF, cadeado, status da agenda, envio, integração e log vistos no DOM, alguns chamados por GET. Exemplos: `blank_editavel`, `blank_assinatura_digital`, `blank_assinar_pdf`, `blank_laudo_pdf`, `blank_desmarcar`, `blank_status` e `blank_log_personalizado`, que grava log por GET. A lista completa está em `ENDPOINTS_BLOQUEADOS`.

## 7. O que NÃO foi capturado na sessão B

Os itens marcados **(C)** foram cobertos, total ou parcialmente, na sessão C; o detalhe está na seção 9 e em `FASE-0-ETAPA-C.md`.

- **Questionário** (SOAP → Subjetivo): não foi aberto (item 3 do checklist). **(C)** tela mapeada; respostas encontradas num registro de Evolução.
- **Laudo assinado:** os 6 laudos estavam "Aguardando assinatura!" ("PDF Assinado 0 de n"), então não houve laudo assinado para abrir. Continua em aberto na sessão C: os laudos também estavam todos "0 de n".
- **Imprimir → LAUDO (PDF):** não foi clicado. **(C)** clicado 3 vezes; mecanismo em 9.3.
- **Exames → Resultado e Anexo** (item 164 e anexos): não foram abertos. **(C)** abertos (9.4 e 9.5).
- **Teste de sessão simultânea** (item 8): não há registro nas capturas. **(C)** observado pelo Ivson (9.8).
- **Paginação e ordenação de grade:** não foram exercitadas, porque as grades tinham no máximo 3 linhas. `nmgp_opcao=rec`, `ordem` etc. continuam fora da lista branca. **(C)** também não (9.7).
- **Corpos dos POSTs `blank_*_funcoes`:** nesta sessão o gravador não gravava `funcao`, e os valores da seção 5 são inferidos. Resolvido para as próximas sessões na Etapa B.2: o gravador extrai também o valor de `funcao` da query e do corpo urlencoded, com a mesma regra usada para `nmgp_opcao`, e o resumo o inclui na chave.
- **JS externo** (`*_ajax.js` das grades, onde fica `ajax_save_ancor`): não é capturado, porque o gravador só grava HTML.
- **Encerramento:** a sessão foi encerrada por kill, sem Ctrl+C, e o resumo teve de ser reconstruído (ver item 1).

## 8. Uso pelo coletor (F2), com a guarda v2

1. O Ivson faz o login à mão. Só depois a guarda é instalada (`guard.instalar`), porque `login_sha` e `login_autenticar` estão fora da lista branca. A tela de login tem reCAPTCHA v3 invisível (visto na sessão C), mais um motivo para o login ser manual.
2. Agenda: menu "Agendamento" → ler as linhas de `div#campotabela` no iframe `menu_inicial_item_31_iframe`.
3. Ficha: clicar em `a#id_sc_field_c_nome_<n>` → ler o cabeçalho `.cabecalho__grupo-info` pelo rótulo.
4. Exames → Laudo (item com `sc_apl_menu=grid_exames_laudo`) → ler as linhas do 1º nível.
5. Lápis `a#id_sc_field_cmp_ligacao_<n>` → ler a lista de laudos em `dbifrm_widget3`.
6. Abrir o laudo pelo link da linha (`ajax_save_ancor` + `igual`, **liberado na v2**) → ler `textarea#id_sc_field_receituario` → sair por "Voltar" (`…_fim.php`). Nunca clicar em Imprimir, Enviar Por ou Finalizar e Assinar.
7. O PDF do laudo **não** é obtido pelo MD nesta versão (9.3). O dossiê usa o texto lido no passo 6.

## 9. Acréscimos da sessão C (27/09/2026)

Sessão de um paciente só (paciente A). Linha do tempo resumida:

| Hora | Ação | Requisições principais |
|---|---|---|
| 10:09:29–48 | Login | `login_sha` ×3, `login_autenticar`; reCAPTCHA v3 na página |
| 10:09:49–51 | Carga do menu | `blank_notificacao_funcoes` (`buscar_sala_usuario`, `qtd_novo`, `cards_*`), `blank_menu_inicial_funcoes` (`m_token_sessao`), `blank_home_funcoes` ×4 |
| 10:10:49 | Agendamento | `POST /blank_div/` |
| 10:11:06 | Ficha do paciente A | as mesmas da sessão B |
| 10:11:36 | Questionário (item_218) | `POST /ctr_quest_rel_acompanhar/` → `GET blank_quest_rel_acompanhar.php` |
| 10:12:04–10:13:01 | Exames → Laudo; abre L1, L2, L3 | `grid_exames_laudo`, `cont_exame_resultado_laudo`, 3 × (`ajax_save_ancor` + `igual` + `_fim.php`) |
| 10:13:20 | **ASSINAR PDF** no L1 (2º nível) | `POST blank_assinatura_digital.php` (XHR) → `GET blank_laudo_pdf.php?vg_id_receita_livre_pdf=<id>&assinar=S` (XHR) |
| 10:13:25–45 | Voltar ao 1º nível e de novo ao 2º | `GET grid_exames_laudo.php`, `POST cont_exame_resultado_laudo` |
| 10:13:51–10:14:30 | Reabre L1, L2, L3; **Imprimir** em cada um | 3 × `igual`; 3 abas novas terminando em `/blank_laudo_pdf/` |
| 10:14:50–10:15:07 | Exames → Resultado (item_164); abre 2 vezes | `POST grid_exames_resultados`, 2 × `POST form_exames_resultados` (`nmgp_opcao` vazio) + `_fim.php` |
| 10:15:17–25 | Anexo → Documentos (item_26) e Imagens (item_106) | `POST grid_tbl_paciente_crm_anexo_doc`, `…_img` |
| 10:15:32–49 | Evolução (item_19); abre 1 registro; Imprimir | `POST grid_tbl_pacientes_crm`, `POST form_tbl_pacientes_crm_editavel` (vazio), `POST grid_evolucao_imp` (`grid` e `print`), `GET blank_log_personalizado.php?…&p_action=print`, `GET form_tbl_pacientes_crm_editavel.php` |

Todos os 64 POSTs receberam 200 (ou 204, os de terceiros). As 2 falhas foram GETs cancelados pelo navegador.

### 9.1 POSTs novos e classificação v2

| POST | Operação | Nº | Resposta | Classificação v2 |
|---|---|---|---|---|
| `/blank_notificacao_funcoes/…php` | `funcao=buscar_sala_usuario` | 1 | JSON de salas para o WebSocket de notificações | **Liberado** (`notificacao_sala`) |
| `/blank_menu_inicial_funcoes/…php` | `funcao=m_token_sessao` | 1 | JSON `SESSAO_ATIVA` | **Liberado só com `acao=consultar`** (ALTERADO v1→v2) |
| `/ctr_quest_rel_acompanhar/` | — | 1 | Controle "Questionário - Acompanhar" | **Liberado** (só a tela) |
| `/grid_exames_resultados/` | — | 3 | Grade "Relatório de tbl_exames_resultados" | **Liberado** |
| `/form_exames_resultados/` | `nmgp_opcao` vazio | 2 | Form "Atualização de tbl_exames_resultados" (Salvar, Excluir) | **Pendente** (`ENDPOINTS_PENDENTES_VALIDACAO`) |
| `/form_exames_resultados/…_fim.php` | — | 2 | Saída do form | Pendente (prefixo do form) |
| `/grid_tbl_paciente_crm_anexo_doc/` | — | 1 | Grade "Anexo - Documentos" | **Liberado** |
| `/grid_tbl_paciente_crm_anexo_img/` | — | 1 | Grade "Anexo - Imagens" | **Liberado** |
| `/grid_tbl_pacientes_crm/` | — | 1 | Grade "Andamento" (Evolução) | **Liberado** |
| `/form_tbl_pacientes_crm_editavel/` | `nmgp_opcao` vazio | 1 | Form "Atualização - form_tbl_pacientes" (registro de Evolução) | **Pendente** (9.6) |
| `/grid_evolucao_imp/` | `nmgp_opcao=grid` e `print` | 2 | Impressão da Evolução; a página chama `blank_log_personalizado` com `p_action=print` e `window.print()` | **Bloqueado** (endpoint; `print` e exportações também como operação) |
| `/blank_assinatura_digital/…php` | — | 1 | JSON de validação ("Validando impressão") | **Bloqueado** (1º passo da assinatura) |
| `/blank_laudo_pdf/` | ? | 1 gravado (3 ocorridos) | Página "Validade da assinatura" com o PDF em `data:` URI, ou JSON do arquivo para assinatura | **Bloqueado** (9.3) |

### 9.2 Questionário ("Questionário - Acompanhar")

- **Caminho:** item de menu da ficha com `sc_apl_menu=ctr_quest_rel_acompanhar` (item_218 nesta conta) → `POST /ctr_quest_rel_acompanhar/` → iframe `GET /blank_quest_rel_acompanhar/blank_quest_rel_acompanhar.php` (tabela DataTables vazia até pesquisar).
- **Tela:** filtros `cmp_questionario` (select com os questionários configurados na conta: triagem de mamografia, pré-ultrassom de tireoide e triagem de densitometria), `cmp_data_ini`, `cmp_data_fim`, `cmp_exibir_sessao`, `cmp_exibir_pontuacao`; botões Pesquisar e Imprimir.
- **Pesquisar** (`m_js_pesquisar`) faz `POST ../blank_quest_config_funcoes/blank_quest_config_funcoes.php` com `funcao=rel_dados_acompanhar`, `id_questionario`, `data_ini`, `data_fim`, `exibir_sessao`, `exibir_pontuacao`, e recebe JSON (`dados.questionarios`, `dados.filtro`). **Não foi clicado:** nenhum dado de questionário trafegou por essa tela. `blank_quest_config_funcoes` segue bloqueado (também serve à configuração de questionários).
- **Imprimir** (`m_js_imprimir`) abre `blank_quest_acompanhar_pdf.php`. Bloqueado.
- As respostas do paciente foram encontradas por outro caminho, a Evolução (9.6).

### 9.3 PDF do laudo: Imprimir e ASSINAR PDF

**Imprimir (form do laudo).** `sc_btn_imprimir_normal_ok()` põe `nmgp_parms = "nmgp_opcao?#?formphp?@?nm_call_php?#?imprimir_normal?@?"` no F1 e o submete para `./` com `target="_blank"`. O F1 é `multipart/form-data` e leva o form inteiro, inclusive o texto do laudo. O servidor roda o código PHP do botão e a aba nova termina em `POST /blank_laudo_pdf/`.

- **POST, não GET; PDF inline, não download.** A resposta é uma página HTML de título "Assinatura" ("Validade da assinatura": "PDF / Banco de Dados: Não assinado", "O documento contém 0 assinatura(s)", data de verificação) com o PDF inteiro em `<object data="data:application/pdf;base64,…" type="application/pdf">`. O visualizador de PDF do Chrome renderiza o `data:` URI; não há requisição separada para baixar o arquivo.
- **Resposta dependente de estado.** Nas aberturas de L2 e L3 veio a página acima. Na de L1, logo depois do ASSINAR PDF do mesmo laudo, a aba terminou em `/blank_laudo_pdf/` com um JSON `{"arquivo": "sc_<hash><aaaammddhhmmss>.pdf", "data_assinatura": "<data hora>", "name": "<pasta tmp do servidor>"}`, que é o formato do modo de assinatura.
- **Gravador:** as abas novas nascem antes de o gravador se conectar a elas. Do POST do F1 para o form não há registro nas 3 abas. O `POST /blank_laudo_pdf/` foi registrado em 1 das 3, e sem corpo analisável (as chaves não são `nmgp_opcao` nem `funcao`).

**ASSINAR PDF (2º nível).** `fn_js_assinatura_pdf_lc` faz, em sequência:

1. `POST ../blank_assinatura_digital/blank_assinatura_digital.php` (`requisito`, `receitaId`, `clinica`, `usr`), com aviso "Validando impressão". A resposta JSON diz o tipo de documento, a posição do carimbo e o carimbo;
2. para laudo, `GET ../blank_laudo_pdf/blank_laudo_pdf.php?vg_id_receita_livre_pdf=<id>&assinar=S`, com aviso "Gerando PDF". A resposta JSON traz o nome de um arquivo gerado na pasta temporária do servidor;
3. `mdPepOpenCertificates(...)` abre o modal do certificado em `_lib/libraries/grp/assinatura_receita/php/plain/public/certified/index.php?params=<base64>`.

Na sessão C, os passos 1 e 2 ocorreram (status 200). O passo 3 **não** gerou requisição: o modal do certificado não foi carregado e nada foi assinado. As grades continuaram "PDF Assinado 0 de n", sem mudança em nenhum campo. **O "só visualizar" do diálogo já gera um PDF no servidor e deixa estado de sessão** que mudou a resposta do Imprimir seguinte.

**Decisão v2:** `blank_laudo_pdf`, `blank_assinatura_digital` e a chave `assinar` ficam bloqueados. O PDF só seria alcançável por `formphp` (código PHP do botão, com o form inteiro no corpo) e o mesmo endpoint serve à preparação da assinatura, com resposta que depende do estado da sessão. O texto do laudo já vem do form (6.2).

### 9.4 Exames → Resultado

- **1º nível:** `POST /grid_exames_resultados/` (item_164), título "Relatório de tbl_exames_resultados". Campos `id`, `cmp_atendimento_versao`, `cmp_data_evento`, `descricao` (Título), `id_exame` (Solicitação Vinculada), `exames_solicitados`, `resultado_arq` (Arquivo), `cmp_status`, `cmp_usuario`, `cmp_status_assinatura`, `cmp_editavel`, `cmp_ligacao`. Barra: Novo e Vincular Solicitação.
- **Linha:** abre `POST /form_exames_resultados/` com `nmgp_opcao` **vazio** (não `igual`), título "Atualização de tbl_exames_resultados", com **Salvar e Excluir visíveis**. Campos `data_evento`, `data_realizacao`, `descricao`, `id_laboratorio`, `realizado` (Local: interno/externo), `resultado_arq` (upload), `justifica_retroativo`. Abaixo, a grade `grid_paciente_exames_resultados_mestre` ("Últimos Resultados": nenhum).
- A grade ficou idêntica campo a campo antes e depois das 2 aberturas. O mesmo resultado não foi reaberto, e nenhum Arquivo foi clicado. **Pendente.** O coletor não precisa do form: título, data e arquivo estão na grade.

### 9.5 Anexos

- `POST /grid_tbl_paciente_crm_anexo_doc/` ("Anexo - Documentos") e `POST /grid_tbl_paciente_crm_anexo_img/` ("Anexo - Imagens"), itens 26 e 106. As duas grades estavam vazias para o paciente A.
- Botões de escrita: Novo Documento, Upload Imagem e Excluir Selecionados, bloqueados na camada 2. Ver Slide, Ver Scroll e Comparar são de visualização.
- **Nenhum anexo foi aberto**, então não se sabe como o arquivo de um anexo é entregue.

### 9.6 Evolução e o questionário respondido

- `POST /grid_tbl_pacientes_crm/` (item 19, "Evolução (n)"), título "Andamento". Campos `cmp_atendimento_versao`, `cmp_id_versao`, `cmp_data_hora`, `cmp_usuario`, `local_agenda`, `cmp_status_assinatura`, `cmp_insercao_ia`, `cmp_copiar` ("Copiar", que chama `blank_copiar_dados`), `cmp_ligacao`. Barra: Novo.
- **O questionário pré-exame respondido pelo paciente é um registro de Evolução.** Aberto (`POST /form_tbl_pacientes_crm_editavel/`, `nmgp_opcao` vazio), o registro mostra num quadro interno as perguntas e respostas em HTML, com "Preenchido por: Paciente".
- O form é "Atualização - form_tbl_pacientes". Salvar fica oculto, mas **Excluir** (`sc_btn_inativar` → `/form_log_inativar/`), **Refazer** (`sc_btn_refazer` → `/ctr_editar_item_soap/`) e **Imprimir** ficam visíveis.
- **Não é edição do cadastro do paciente**, apesar do nome: `tbl_paciente_crm` guarda os itens da Evolução/SOAP. Mesmo assim é um form de edição aberto num registro clínico.
- Evidência: o conteúdo do registro, a versão e as datas ficaram idênticos antes e depois do Imprimir. Houve **1 abertura só**, e a grade "Andamento" não foi recarregada depois. Não dá para comparar como no laudo.
- **Imprimir** (`sc_btn_btn_imprimir` → `POST /grid_evolucao_imp/`, `nmgp_opcao=grid` e `print`) monta a página "Evolução", que chama `window.print()` e **grava log** por `GET blank_log_personalizado.php?p_application=form_tbl_pacientes_crm_edit&p_creator=Manual&p_action=print`.
- **Decisão v2:** o form fica pendente (bloqueado em qualquer método). `grid_evolucao_imp`, `form_log_inativar`, `ctr_editar_item_soap` e `blank_copiar_dados` ficam bloqueados.

### 9.7 Paginação das grades

Não foi exercitada. As grades do paciente A tinham no máximo 3 linhas (laudo 1º e 2º nível, resultado, evolução) e nenhuma mostrou barra de paginação. A grade da agenda trouxe dezenas de linhas numa página só, sem controles de paginação (`nm_gp_move`, `sc_b_avc_*`) no HTML. `nmgp_opcao=rec` continua fora da lista branca.

### 9.8 Sessão simultânea

Observação empírica do Ivson na sessão C: ele ficou logado no MD **ao mesmo tempo** no Chrome (perfil dedicado) e no Edge, com o mesmo usuário. As duas sessões funcionaram normalmente, e uma não derrubou a outra. O gravador só observa o Chrome, então não há registro de rede do Edge. Isso responde, por experiência, a pergunta 3 do e-mail ao suporte (limite de sessão simultânea). A confirmação definitiva, inclusive sobre limites de política, continua sendo com o suporte.

### 9.9 Limitação do gravador vista na sessão C

O gravador se conecta a uma aba nova só depois que ela aparece em `/json/list`. As primeiras requisições da aba se perdem. Nas 3 abas do Imprimir, o POST do form nunca foi registrado; o `POST /blank_laudo_pdf/` foi registrado em 1 das 3. Por isso o `rede-resumo.json` subconta requisições de abas novas. Proposta para a próxima sessão: descobrir alvos com `Target.setDiscoverTargets` e conectar pelo evento `targetCreated`. Isso reduz a janela, mas não a elimina sem pausar a aba, o que exigiria sair do modo passivo.
