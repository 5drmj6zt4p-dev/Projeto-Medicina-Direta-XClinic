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
| Coletor MD | Playwright num perfil Chrome **dedicado**. Lê o DOM, com a guarda de somente leitura descrita abaixo. Obtém o PDF por "Imprimir" e registra a proveniência. |
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

As listas ficam em `fluxo_exames/guard.py`. Hoje são **PLACEHOLDER**; os valores reais saem da Fase 0, Etapa B.

## Privacidade

- **Nenhum dado de paciente entra neste repositório:** nem nomes, prontuários, laudos, capturas ou HTML real. Testes usam apenas fixtures sintéticas ou anonimizadas.
- Os dados ficam em `%LOCALAPPDATA%\FluxoExames`, fora do OneDrive, do Google Drive e do repositório. Lá ficam as capturas, o estado, o perfil Chrome dedicado e as pastas do dia.
- O `.gitignore` bloqueia `captures/`, `*.db`, `chrome-profile/` e `.env` como segunda barreira.
- Nada do fluxo clínico vai para o Telegram. Os avisos locais levam só contagens.
- Pré-requisito antes do primeiro dado real: BitLocker ativo no C:.

## Estrutura

```
fluxo_exames/        pacote do app (esqueleto)
  guard.py           guarda de somente leitura (listas PLACEHOLDER)
  state.py           estados da máquina de estados por item
scripts/
  gravador_passivo.py  Fase 0: grava passivamente as navegações do Chrome dedicado
                       (--rede: mapa de requisições por método, caminho e nmgp_opcao)
docs/
  FASE-0-ETAPA-A.md  perfil dedicado, uso do gravador e checklist da Etapa B
```

## Instalação

```powershell
python -m pip install -r requirements.txt
```

O gravador da Fase 0 usa apenas `websocket-client`. O `playwright` entra a partir da F2.
