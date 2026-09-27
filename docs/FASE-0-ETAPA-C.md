# Fase 0 — Etapa C: relatório da sessão 2

Segunda sessão gravada no MD, para fechar as lacunas da Etapa B. O mapa completo, com seletores e requisições, está em `FASE-0-ETAPA-B.md` (seção 9 e notas "sessão C"). A guarda passou à versão 2 (`fluxo_exames/guard.py`).

Sem dado de paciente neste documento. Paciente A é o primeiro paciente de teste; L1, L2 e L3 são os três laudos dele.

## 1. Sessão

- **Quando:** 27/09/2026, 10:09–10:17. O gravador rodou com `--rede` e foi encerrado por Ctrl+C, então o resumo é nativo. A instrução da etapa fala em 26/09 ~21:4x e em 72 eventos CAPTURA; o `sessao.log` e o jsonl mostram 27/09 e 41 eventos CAPTURA.
- **Paciente:** um só (A).
- **Material:** 927 capturas HTML; `rede-2026-09-27.jsonl` com 2.570 requisições; `rede-resumo.json` com 597 tuplas, `sessoes=1`. A pasta foi zerada antes; o resumo da sessão B está arquivado como `rede-resumo-sessao1-B.json`.

## 2. Lacunas da Etapa B: o que foi capturado

| Lacuna | Resultado | Onde |
|---|---|---|
| Questionário | **Parcial.** A tela "Questionário - Acompanhar" foi mapeada, mas Pesquisar não foi clicado. As **respostas do paciente** foram encontradas num registro de **Evolução** ("Preenchido por: Paciente"), num form que abre em modo de edição (pendente) | B §9.2, §9.6 |
| Laudo assinado | **Não.** Os 3 laudos estavam "Aguardando assinatura!" ("PDF Assinado 0 de n") | — |
| PDF do laudo | **Sim, o mecanismo.** Imprimir → F1 multipart `formphp`/`imprimir_normal` numa aba nova → `POST /blank_laudo_pdf/` → HTML "Validade da assinatura" com o PDF em `data:application/pdf;base64` num `<object>`. É POST, com PDF inline e sem download. A resposta mudou para JSON do modo de assinatura depois de um ASSINAR PDF no mesmo laudo | B §9.3 |
| Assinatura digital | **Visualizada, nada assinado.** ASSINAR PDF chamou `blank_assinatura_digital` e `blank_laudo_pdf.php?assinar=S`, que gera um PDF temporário no servidor. O modal do certificado não carregou, e as grades seguiram "0 de n" | B §9.3 |
| Resultado | **Sim.** Grade de 1º nível e form (abre em "Atualização", com Salvar e Excluir). Nenhum arquivo aberto | B §9.4 |
| Anexo | **Parcial.** As grades de documentos e imagens abriram vazias; nenhum anexo foi aberto | B §9.5 |
| Paginação | **Não exercitada.** As grades tinham no máximo 3 linhas; a agenda veio numa página só | B §9.7 |
| Sessão simultânea | **Sim, por observação do Ivson.** Chrome dedicado e Edge logados ao mesmo tempo, sem queda de nenhuma das sessões. A confirmação definitiva continua com o suporte | B §9.8 |
| Validação de `igual` | **Sim.** 3 laudos abertos 2 vezes cada: texto idêntico, grades idênticas campo a campo (inclusive "Registros em Aberto" e a data de "Abertura do Registro"), nenhuma requisição automática | B §6.2 |
| `funcao` gravada | **Sim.** Corrigiu duas deduções da v1 (`m_obter_favoritos` → `m_token_sessao`; 5º POST de notificação = `buscar_sala_usuario`) | B §5, §9.1 |
| `blank_fecha_atendimento` | **Não reproduzido.** Só uma ficha foi aberta | — |

## 3. Guarda v2

Decisões **ALTERADO v1→v2**, cada uma com a evidência anotada em `guard.py`:

1. `nmgp_opcao=igual`: de pendente para **liberado só em `POST /form_paciente_exames_laudos_resultado/`**. Com isso o coletor lê o texto do laudo. Em outros caminhos, por GET ou dentro de `nmgp_parms`, continua bloqueado.
2. `m_obter_favoritos` saiu da lista branca, porque nunca foi gravado.
3. `m_token_sessao` saiu de `FUNCOES_AJAX_BLOQUEADAS` e foi **liberado só com `acao=consultar`**. `acao=alterar_sessao_ativa` entrou em `ACOES_AJAX_BLOQUEADAS`.

Novidades classificadas:

| Novidade | Decisão | Motivo |
|---|---|---|
| `blank_laudo_pdf` | Bloqueado (mantido) | Só é alcançável por `formphp` com o form inteiro; o endpoint também prepara a assinatura; a resposta depende do estado da sessão |
| `blank_assinatura_digital`, chave `assinar` | Bloqueados, mesmo para só abrir o diálogo | 1º e 2º passos da assinatura; o "só visualizar" já gera PDF no servidor e muda o estado da sessão |
| `grid_evolucao_imp` (`grid`/`print`) | Bloqueado (endpoint; `print` e exportações também como operação) | A impressão grava log `p_action=print` e chama `window.print()`; o conteúdo já está no DOM |
| `form_exames_resultados` | Pendente | Form em edição; só 2 aberturas de registros diferentes |
| `ctr_quest_rel_acompanhar` | Liberado (só a tela) | Controle de filtros; a pesquisa (`blank_quest_config_funcoes`) segue bloqueada |
| `form_tbl_pacientes_crm_editavel` | Pendente | Não é cadastro: é o registro de Evolução, com Excluir e Refazer visíveis; 1 abertura, sem recarga da grade |
| Grades de Resultado, Anexos e Evolução; `buscar_sala_usuario` | Liberados | Navegação e leitura, sem efeito observado |

Também entraram na camada 2 os textos UPLOAD, REFAZER, INATIVAR e COPIAR, os ids de Excluir Selecionados, Novo Documento, Refazer, Inativar e Imprimir da Evolução, e as funções `mdPepOpenCertificates`, `m_js_imprimir` e `sc_btn_btn_imprimir`.

**Testes:** `python -m pytest` → 128 passed.

**Repasse das sessões reais** (`python scripts/repassar_rede.py`; o corpo é remontado só com `nmgp_opcao` e `funcao` gravados):

- **Sessão C:**
  - passam **45 POSTs**: todo o caminho de leitura, inclusive os 6 `igual`, os 11 `blank_*_funcoes` com `funcao` gravada, Resultado, Questionário, Anexos e Evolução (grades);
  - são negados **19 POSTs**:
    - login ×4;
    - terceiros ×4;
    - `blank_notifica_lembrete`;
    - `blank_assinatura_digital` e `blank_laudo_pdf`;
    - `grid_evolucao_imp` ×2;
    - os forms pendentes ×5;
    - `m_token_sessao` ×1, negado só porque o gravador não registra `acao`;
  - são negados **8 GETs**: `blank_laudo_pdf.php?assinar=S`, `blank_log_personalizado`, `grid_evolucao_imp_iframe_prt`, o recarregamento do form da Evolução e 4 CSS dos forms pendentes;
  - passam 2.481 GETs de leitura.
- **Sessão B:** os 6 `igual` e os 6 `_fim.php` agora passam. Os `blank_*_funcoes` continuam negados no repasse porque aquela sessão não gravava `funcao`. O único GET negado é `blank_fecha_atendimento`.

## 4. O que permanece aberto

1. **Laudo assinado:** abrir um laudo com "PDF Assinado 1 de 1" e confirmar que o texto do form é o do PDF assinado e como o cadeado e o status aparecem. Sem isso, o vigia não tem sinal validado de "laudo pronto".
2. **Questionário:**
   - abrir o mesmo registro de Evolução 2 vezes, com a grade recarregada, para validar `form_tbl_pacientes_crm_editavel`;
   - ou clicar Pesquisar em "Questionário - Acompanhar" e gravar `rel_dados_acompanhar`.
3. **PDF original do laudo:** gravar Imprimir de um laudo sem ASSINAR PDF antes na sessão, com o gravador pegando a 1ª requisição de abas novas (B §9.9). Enquanto isso não for feito, o dossiê usa o texto.
4. **Resultado com arquivo e anexo aberto:** como o arquivo é entregue (GET de download ou outro `blank_*`).
5. **Paginação:** paciente com mais linhas que a página de uma grade.
6. **`blank_fecha_atendimento`:** abrir 2 fichas seguidas.
7. **Suporte do MD:** API oficial, automação permitida, sessão simultânea (confirmação) e distinção oficial rascunho/assinado/retificado.

## 5. Recomendações para a F1

- **Começar a F1 já.** Esqueleto do app, `estado.sqlite` e taxonomia de títulos não dependem de nenhuma lacuna aberta. Os títulos vistos nas duas sessões (compostos com "/" no 1º nível, únicos no 2º nível e no Resultado) servem de casos de teste.
- **A unidade documental do MD é o laudo do 2º nível, lido no form por `igual`.** O modelo de dados da F1 deve guardar a origem (`md:laudo:<id>`), o título, a data, o profissional, o estado de assinatura da grade e o hash do texto. Não precisa guardar o PDF.
- **Tratar "Resultado" e "Evolução/questionário" como fontes separadas**, com estado próprio de cobertura ("não consultado", "pendente de validação"). Até a validação, o briefing deve dizer que o questionário não foi lido, e não que ele não existe.
- **Levar para a F2 o registro de bloqueios da guarda como métrica do modo sombra** e rodar `scripts/repassar_rede.py` contra toda sessão gravada nova antes de mudar a lista branca.
- **Sessão simultânea funciona na prática:** o coletor pode rodar com o Ivson logado em outro navegador. Manter a detecção de tela de login/"SESSÃO BLOQUEADA" (inatividade), com aviso para reautenticar.
