# fluxo-exames

App local e determinístico que prepara, na véspera e no próprio dia, os exames de imagem da agenda do Dr. Ivson.

Para cada exame da agenda do Medicina Direta (MD), o app:

1. identifica o paciente;
2. levanta os laudos anteriores no MD e, quando precisa, no XClinic;
3. gera um briefing de antecedentes;
4. monta o dossiê das séries de mamas e tireoide;
5. quando o laudo do dia fica pronto, dispara as skills de controle evolutivo.

As saídas são sempre **rascunhos para revisão médica**. O app não escreve nada no MD nem envia nada ao paciente.

A arquitetura foi aprovada na Sala de Reunião (Hermes, Claude e Codex) e selada pelo Ivson em 26/09/2026. As decisões e os motivos estão na `ATA.md` da Sala.

## Componentes (visão do modelo aprovado)

| Componente | Função |
|---|---|
| Coletor MD | Playwright num perfil Chrome **dedicado**. Lê o DOM, com a guarda de somente leitura descrita abaixo. Lê o texto do laudo no formulário e registra a proveniência. O PDF por "Imprimir" está bloqueado desde a Etapa C (ver `docs/FASE-0-ETAPA-C.md`). |
| Coletor XClinic | Só SELECTs parametrizados, com login SQL somente leitura. Se o XClinic estiver inacessível, a consulta entra numa fila offline. |
| Estado | SQLite com uma máquina de estados por item (`fluxo_exames/state.py`), checkpoints por documento e cache por versão/hash. |
| Taxonomia | YAML versionado que classifica os títulos de exame. Título desconhecido não exclui antecedente. |
| Síntese | LLM via assinatura (`claude -p`; `codex exec` como alternativa), com verificador determinístico de medidas e lateralidade. |
| Dossiê | Séries de mamas e tireoide com as duas fontes (MD + XClinic), manifesto e proveniência por documento. |
| Validador do laudo do dia | Confere identidade, exame, data, texto integral e condição de pronto, e então dispara o evolutivo (formato B por padrão; A por comando). |
| Painel | HTML estático local e toast do Windows, sem dado de paciente. |

## Fases

| Fase | Marco |
|---|---|
| F0 | Mapear o MD em modo passivo: telas, DOM e operações de gravação do ScriptCase. Etapa A é a ferramenta (este commit); Etapa B é o mapeamento com o Ivson presente. |
| F1 | Esqueleto do app, `estado.sqlite` e taxonomia, com testes sobre os títulos vistos. |
| F2 | Coletor MD com a guarda de somente leitura (agenda, ficha, laudos nos 2 níveis, PDF). |
| F3 | Síntese, verificador e painel, seguidos de **modo sombra de pelo menos 10 dias úteis** antes de qualquer uso clínico. |
| F4 | Dossiê multiorigem e manifesto. |
| F5 | Coletor XClinic e mapeamento de identidade por nome + DN (só na clínica). |
| F6 | Vigia do laudo do dia e evolutivo em modo lote. |
| F7 | Agendamento no Windows, retenção e manual de operação. |

A construção segue em série, Claude → Codex → Hermes, com passagem de bastão documentada na Sala.

## Regra da guarda de somente leitura (3 camadas)

No MD, o caminho de leitura passa ao lado de ações de escrita e de assinatura. O formulário do laudo tem "Finalizar e Assinar" e a lista de laudos tem "ASSINAR PDF". Por isso o somente leitura é garantido por **mecanismo**, não por instrução. A política é negar por padrão: tudo o que não foi demonstrado como leitura fica bloqueado.

1. **Métodos HTTP:** toda requisição com método de escrita (`PUT`, `PATCH`, `DELETE` etc.) é abortada antes de sair do navegador.
2. **Textos de botão:** o coletor nunca clica em elemento cujo texto case com a lista negra (Assinar, Finalizar, Salvar, Excluir, Enviar…).
3. **POST:** todo `POST` é bloqueado, salvo os que estão numa lista branca explícita. Cada item dessa lista foi observado e demonstrado como leitura na Fase 0.

As listas ficam em `fluxo_exames/guard.py` (versão 2, preenchida com as sessões das Etapas B e C; evidências em `docs/FASE-0-ETAPA-B.md` e `docs/FASE-0-ETAPA-C.md`). Além das 3 camadas, a guarda bloqueia, em qualquer método, endpoints de escrita, assinatura, impressão e log e parâmetros de operação do ScriptCase. Abrir o formulário do laudo (`nmgp_opcao=igual`) foi validado na Etapa C e está liberado só nesse caminho. O PDF do laudo ("Imprimir") e os formulários de Resultado e de Evolução continuam bloqueados.

## Coletor (F1)

`fluxo_exames/coletor.py` lê o MD **só por CDP**, no Chrome dedicado já aberto e logado (`http://localhost:9222`). Não abre navegador próprio e não usa o perfil pessoal. As operações são as do mapa: `ler_agenda`, `localizar_paciente`, `abrir_ficha`, `identidade`, `listar_atendimentos`, `listar_laudos` e `abrir_texto_laudo`. A guarda é integrada nas 3 camadas:

1. operação e clique precisam estar nas listas do mapa;
2. uma rota de rede aborta o que `guard.py` nega; um canário prova que ela está ativa;
3. há interdição dos textos de escrita e assinatura.

Qualquer verificação que falhe levanta `ColetorBloqueado`, e nada é tentado no lugar. `fluxo_exames/fila.py` guarda a fila de itens em `%LOCALAPPDATA%\FluxoExames\fila.db`, com a máquina de estados de `state.py`, checkpoints por documento e idempotência por (paciente, exame, data).

**Testes (offline):** `python -m pytest`. Os testes do coletor abrem um Chrome descartável (perfil temporário, headless) contra um servidor sintético local (`tests/md_sintetico.py`) e conferem do lado do servidor que nenhuma requisição negada pela guarda chegou. Nada acessa o MD. Se não houver Chrome, esses testes são pulados; `FLUXO_CHROME` aponta outro executável.

**Validação ao vivo:** sessão separada com o Ivson, com o gravador passivo como testemunha. Roteiro, premissas a confirmar e riscos residuais em `docs/FASE-1-ETAPA-A.md`, seções 4 e 5.

## Privacidade

- **Nenhum dado de paciente entra neste repositório:** nem nomes, prontuários, laudos, capturas ou HTML real. Testes usam apenas fixtures sintéticas ou anonimizadas.
- Os dados ficam em `%LOCALAPPDATA%\FluxoExames`, fora do OneDrive, do Google Drive e do repositório. Lá ficam as capturas, o estado, o perfil Chrome dedicado e as pastas do dia.
- O `.gitignore` bloqueia `captures/`, `*.db`, `chrome-profile/` e `.env` como segunda barreira.
- Nada do fluxo clínico vai para o Telegram. Os avisos locais levam só contagens.
- Pré-requisito antes do primeiro dado real: BitLocker ativo no C:.

## Estrutura

```
fluxo_exames/        pacote do app
  guard.py           guarda de somente leitura (versão 2)
  coletor.py         coletor do MD por CDP, com a guarda integrada (F1, validado só offline)
  fila.py            fila persistente em SQLite, checkpoints por documento
  state.py           estados e transições da máquina de estados por item
scripts/
  gravador_passivo.py  Fase 0: grava passivamente as navegações do Chrome dedicado
                       (--rede: mapa de requisições por método, caminho, nmgp_opcao e funcao)
  repassar_rede.py     repassa um rede-*.jsonl gravado pela guarda (sem acessar o MD)
tests/
  test_guard.py      testes da guarda (dados sintéticos)
  test_coletor.py    coletor contra o servidor sintético, num Chrome descartável
  test_fila.py       fila e máquina de estados, inclusive retomada após queda
  md_sintetico.py    servidor local que imita a estrutura do MD (sem PHI)
docs/
  FASE-0-ETAPA-A.md  perfil dedicado, uso do gravador e checklist da Etapa B
  FASE-0-ETAPA-B.md  mapa de leitura do MD e classificação dos POSTs (sessões B e C)
  FASE-0-ETAPA-C.md  relatório da sessão 2: lacunas, guarda v2, pendências e recomendações
  FASE-1-ETAPA-A.md  coletor e fila: desenho, testes, riscos e roteiro da validação ao vivo
```

Testes: `python -m pytest`.

## Instalação

```powershell
python -m pip install -r requirements.txt
```

O gravador da Fase 0 usa apenas `websocket-client`. O coletor usa o `playwright` só para conectar por CDP; o Chromium do Playwright não é necessário (`playwright install` é opcional, só como alternativa ao Chrome instalado nos testes).
