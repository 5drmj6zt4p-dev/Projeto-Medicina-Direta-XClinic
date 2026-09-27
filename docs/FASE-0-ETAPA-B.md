# Fase 0 — Etapa B: mapa de leitura do MD

Mapa do caminho de leitura do Medicina Direta (MD), montado a partir da sessão gravada em 26/09/2026. Serve de base para o coletor da F2 e para a guarda de `fluxo_exames/guard.py` (versão 1).

Este documento não contém dado de paciente. Os dois pacientes de teste aparecem como **paciente A** e **paciente B**. Valores de `script_case_init`, ids internos e hashes aparecem como `<n>`, `<id>` e `<md5>`.

## 1. Sessão e material

| Item | Valor |
|---|---|
| Quando | 26/09/2026, 19:44–19:49 |
| Quem navegou | Ivson, no Chrome dedicado, com `gravador_passivo.py --rede` |
| Escopo | login → agenda (dia atual e outro dia) → ficha do paciente A → Exames → Laudo (1º e 2º nível, 3 laudos abertos) → ficha do paciente B → o mesmo caminho |
| Capturas HTML | 588 arquivos em 31 snapshots (`sessao.log`) |
| Rede | `rede-2026-09-26.jsonl`: 4.093 eventos, sendo 2.022 requisições, 2.068 respostas e 3 falhas |
| Resumo | `rede-resumo.json`: 436 tuplas, reconstruído pelo Hermes a partir do jsonl porque a sessão foi encerrada por kill |

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

### 4.6 Questionário (SOAP → Subjetivo)

**Não capturado.** O item Subjetivo (128) não foi aberto em nenhum dos dois pacientes. Não há requisição nem snapshot dele.

## 5. Mapa REQUEST → RESPOSTA dos POSTs

Contagens reais (requisições), todas com status 200, salvo onde indicado. O tipo de resposta foi confirmado pelo snapshot, para os documentos, ou pelo tratamento no JS da página, para os XHR. O gravador não guarda `Content-Type` nem corpo de resposta.

| POST | Operação no corpo | Nº | Tipo | Resposta | Classificação |
|---|---|---|---|---|---|
| `/login_sha/login_sha.php` | (form de login) | 7 | XHR | Validação e envio do login | Fora da lista: o login é manual, antes de instalar a guarda |
| `/login_autenticar/login_autenticar.php` | — | 1 | XHR | Autenticação; em seguida, GET `/menu_inicial/` | Fora da lista, idem |
| `/blank_notificacao_funcoes/…php` | `funcao` = `qtd_novo`, `cards_novos`, `cards_visualizados`, `cards_favoritos` (inferido do JS) | 5 | XHR | Número e fragmentos HTML (`innerHTML`) | **Liberado por valor de `funcao`** |
| `/blank_home_funcoes/…php` | `funcao` = `m_botoes_suporte`, `m_frases`, `m_noticias` (inferido) | 4 | XHR | JSON | **Liberado por valor** |
| `/blank_menu_inicial_funcoes/…php` | `funcao=m_obter_favoritos` (inferido) | 1 | XHR | Lista CSV | **Liberado por valor** |
| `/blank_div/` | — | 1 | Document | Contêiner da agenda (HTML) | **Liberado** |
| `/blank_sessao_funcoes/…php` | `funcao=limpar_sessao_aplicacoes` | 2 | XHR | Ignorada pelo JS | **Liberado** (estado de sessão) |
| `/blank_notifica_lembrete/…php` | ids de organização, usuário e paciente | 2 | XHR | JSON que vira notificação na tela | **Fora da lista** (efeito no servidor desconhecido; não é necessário) |
| `/blank_treemenu_paciente/` | — | 2 | Document | Página transitória que carrega Dados Gerais | **Liberado** |
| `/blank_treemenu_paciente_funcoes/…php` | `funcao=config_itens_historico` | 2 | XHR | JSON de configuração | **Liberado** |
| `/grid_exames_laudo/` | — | 2 | Document | Grade do 1º nível (HTML) | **Liberado** |
| `/cont_exame_resultado_laudo/` | `nmgp_opcao` vazio | 2 | Document | Contêiner com 2 widgets (HTML) | **Liberado** |
| `/grid_paciente_exames_laudos_resultado/index.php` | `nmgp_opcao=ajax_save_ancor` | 6 | XHR | Resposta curta; no retorno, o JS submete F3 | **Liberado** (ver 6.1) |
| `/form_paciente_exames_laudos_resultado/` | `nmgp_opcao=igual` | 6 | Document | Form do laudo em modo Atualização (HTML) | **Bloqueado, pendente de validação** (ver 6.2) |
| `…/form_paciente_exames_laudos_resultado_fim.php` | — (F6) | 6 | Document | Página de saída que devolve para a grade | **Liberado** (só é alcançável depois de `igual`) |
| `/grid_paciente_exames_laudos_resultado/` | — | 6 | Document | Grade do 2º nível recarregada (HTML) | **Liberado** |
| `h.clarity.ms/collect` | — | 8 | Other | 204 | Fora da lista (telemetria de terceiro) |
| `api.etternum.com.br/online/negotiate` | — | 3 | XHR | Negociação do chat de terceiro | Fora da lista |

"Inferido do JS" quer dizer que o gravador guardou o POST sem o valor de `funcao`, porque só extrai `nmgp_opcao`. O valor foi deduzido das chamadas `$.post` automáticas presentes nas capturas. O mesmo endpoint também recebe valores de escrita, então a guarda libera **por valor de `funcao`**, e nunca o endpoint inteiro.

Desde a Etapa B.2, o gravador registra `funcao` (`funcao_url` e `funcao_corpo` no jsonl) e o `rede-resumo.json` passou a separar as tuplas por (método, caminho, `nmgp_opcao`, `funcao`); ver `FASE-0-ETAPA-A.md`, item 4.1. Na próxima sessão gravada, os valores desta tabela deixam de depender de dedução: a guarda v2 poderá liberar (caminho, `funcao`) direto da evidência gravada. As tuplas da sessão de 26/09 continuam no resumo com `funcao: ""` (não registrado). Até lá, as listas da v1 ficam como estão.

## 6. Classificação das operações duvidosas

### 6.1 `ajax_save_ancor` — benigno, liberado

- Em `nm_gp_submit3` e `nm_gp_submit4` da grade, quando há âncora e o alvo é `_self`, o JS chama `ajax_save_ancor("F3", ancora)` em vez de `document.F3.submit()`. A função está no JS externo da grade, que não foi capturado. No retorno, ela submete F3.
- A âncora é só o índice da linha clicada (1, 2 ou 3). Serve para a grade rolar de volta até ela.
- As grades de 1º e 2º nível ficaram idênticas antes e depois das 6 chamadas. A comparação cobriu contagens "x de y", status, cadeados e tooltips de abertura; só mudou o overlay "Processando".
- Conclusão: é estado de interface na sessão. Liberado, mas só nesse caminho e com esse valor.

### 6.2 `nmgp_opcao=igual` no form do laudo — bloqueado, pendente de validação

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

### 6.3 `blank_fecha_atendimento` — bloqueado, pendente

- É um GET automático (`?tipo=t`) na abertura da ficha do paciente B, gerado pelo HTML do treemenu.
- O menu também tem uma variante `tipo=f` quando um atendimento iniciado fica sem a aba da ficha.
- O coletor nunca inicia atendimento. Fechar um atendimento do Ivson aberto em outra sessão seria efeito colateral.
- Está em `ENDPOINTS_BLOQUEADOS`, que vale também para GET.

### 6.4 Outros bloqueios por endpoint (qualquer método)

São endpoints de assinatura, PDF, cadeado, status da agenda, envio, integração e log vistos no DOM, alguns chamados por GET. Exemplos: `blank_editavel`, `blank_assinatura_digital`, `blank_assinar_pdf`, `blank_laudo_pdf`, `blank_desmarcar`, `blank_status` e `blank_log_personalizado`, que grava log por GET. A lista completa está em `ENDPOINTS_BLOQUEADOS`.

## 7. O que NÃO foi capturado nesta sessão

- **Questionário** (SOAP → Subjetivo): não foi aberto (item 3 do checklist).
- **Laudo assinado:** os 6 laudos estavam "Aguardando assinatura!" ("PDF Assinado 0 de n"), então não houve laudo assinado para abrir.
- **Imprimir → LAUDO (PDF):** não foi clicado. A proveniência do PDF segue desconhecida e o botão "Imprimir" continua bloqueado na camada 2 (item 5).
- **Exames → Resultado e Anexo** (item 164 e anexos): não foram abertos. Só apareceu o widget "Resultado" dentro do contêiner do laudo (item 6).
- **Teste de sessão simultânea** (item 8): não há registro nas capturas.
- **Paginação e ordenação de grade:** não foram exercitadas, porque as grades tinham no máximo 3 linhas. `nmgp_opcao=rec`, `ordem` etc. continuam fora da lista branca.
- **Corpos dos POSTs `blank_*_funcoes`:** nesta sessão o gravador não gravava `funcao`, e os valores da seção 5 são inferidos. Resolvido para as próximas sessões na Etapa B.2: o gravador extrai também o valor de `funcao` da query e do corpo urlencoded, com a mesma regra usada para `nmgp_opcao`, e o resumo o inclui na chave.
- **JS externo** (`*_ajax.js` das grades, onde fica `ajax_save_ancor`): não é capturado, porque o gravador só grava HTML.
- **Encerramento:** a sessão foi encerrada por kill, sem Ctrl+C, e o resumo teve de ser reconstruído (ver item 1).

## 8. Uso pelo coletor (F2), com a guarda v1

1. O Ivson faz o login à mão. Só depois a guarda é instalada (`guard.instalar`), porque `login_sha` e `login_autenticar` estão fora da lista branca.
2. Agenda: menu "Agendamento" → ler as linhas de `div#campotabela` no iframe `menu_inicial_item_31_iframe`.
3. Ficha: clicar em `a#id_sc_field_c_nome_<n>` → ler o cabeçalho `.cabecalho__grupo-info` pelo rótulo.
4. Exames → Laudo (item com `sc_apl_menu=grid_exames_laudo`) → ler as linhas do 1º nível.
5. Lápis `a#id_sc_field_cmp_ligacao_<n>` → ler a lista de laudos em `dbifrm_widget3`.
6. Abrir o laudo (`igual`) **fica bloqueado** até a validação do item 6.2.
