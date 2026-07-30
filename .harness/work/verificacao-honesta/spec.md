---
slug: verificacao-honesta
approved_by: Daniel Seto
approved_at: 2026-07-30T00:12:24Z
stop_conditions:
  - "3 falhas consecutivas do mesmo verify_cmd sem mudança no diagnóstico — devolva ao humano em vez de tentar a quarta variação"
  - "A tabela de sinal de runner precisar de um marcador que não foi observado num run REAL — pare e peça a medição, não invente o padrão de saída (DISPAROU: ver Parte A — descartada)"
  - "Qualquer correção exigir apagar cobertura de teste existente sem substituto que cubra o mesmo invariante"
  - "A correção do #61 exigir tocar `audit.py` ou `doctor.py` — isso é sinal de que a rota escolhida virou a Direção 1, que este contrato descartou"
descope:
  - "2026-07-30, aprovado por Daniel Seto: T-03 e T-04 (issue #59) removidas em execução. Motivo medido em Parte A — descartada. A issue #59 permanece aberta."
---

# Spec: o portão de auditoria volta a reprovar só o que está errado

## Resumo executivo

O comando de auditoria do produto dá **vermelho para projeto saudável**: ele
reprova qualquer repositório que use o harness, e a correção que ele sugere é
justamente a ação que causou o problema. Como a documentação indica esse
comando como portão de CI, quem o colocar num pipeline vai desligá-lo na
primeira execução. Ao fim desta demanda ele volta a reprovar só o que está
realmente errado, sem perder a capacidade de acusar o problema de verdade — e
a documentação para de descrever um mecanismo de proteção que não roda mais.

A demanda começou com **duas** correções. A outra, o falso verde da issue #59,
foi descartada em execução depois que a medição derrubou a premissa dela: ver
"Parte A — descartada" abaixo. O registro fica aqui porque uma demanda que
encolhe sem explicação é indistinguível de uma demanda entregue pela metade.

## Escopo

Uma correção no código, mais a documentação que ficou descrevendo um mecanismo
que não existe mais.

**Parte A — descartada (issue #59, o falso verde).** A demanda previa detectar
o "verde vazio" — runner que sai com `exit code 0` sem ter executado teste —
por **sinal do runner no output**, com tabela de fonte única no molde do
`_POLICY_MATRIX`: para cada runner conhecido, o marcador que prova
positivamente que teste rodou. Foi implementada, revisada a frio duas vezes, e
descartada por decisão humana de 2026-07-30. O que a medição mostrou, em ordem:

1. O marcador óbvio (`Passed!`) é **traduzido**. Medido contra .NET 10.0.101:
   a mesma execução imprime `Aprovado!` em pt-BR.
2. Trocado por marcadores que pareciam literais — o TFM entre parênteses
   (`(.NETCoreApp,Version=v10.0)`) e o rodapé `<nome>.dll (net10.0)` —, a
   revisão fria mostrou que os dois saem do **banner de descoberta**, impresso
   antes de qualquer teste rodar. Três cenários reais passavam como prova:
   projeto de teste que compila com zero `[Fact]`, `--filter` que não casa
   nada (sai 0, não 1), e `--list-tests`.
3. Reduzido ao contador do sumário (`Total: N` com `N > 0`), a segunda revisão
   fria mediu **9 locales**: `gesamt:` (de-DE), `total :` com espaço antes do
   dois-pontos (fr-FR), `Totale:` (it-IT), `合計:` (ja-JP), `总计:` (zh-CN) e
   `всего` sem dois-pontos nenhum (ru-RU). Falha em 6 de 9 — e falha para o
   lado do **falso-deny**, que é pior: a evidência sai marcada, o feature-lock
   passa a recusá-la, e re-rodar o verify só reescreve a mesma prova
   envenenada. Numa máquina alemã, uma tarefa .NET nunca fecharia.

A conclusão é sobre o método, não sobre o runner: **a saída de `dotnet test` é
prosa para humano em 9 idiomas, e não serve de sinal de máquina.** Português e
inglês escrevem "Total" igual, e foi essa coincidência léxica que passou por
invariante nas duas primeiras rodadas.

O falho fica registrado na issue #59, que permanece **aberta**, apontando para
o item 5 da Fase 5 do `docs/roadmap-autonomous.md`: o par red→green exige uma
evidência `.red.json` com `exit != 0`, e um runner que sempre sai 0 nunca
produz red. Aquele mecanismo cobre o mesmo furo sem ler uma linha de saída — e
por isso é o caminho certo, embora cubra só tarefas `tdd: true`.

**Parte B — o falso vermelho (issue #61).** `harness audit` emite
`critical hook_not_registered` para `guard_tests.py` em todo repositório
compilado. Reproduzido agora: `audit --dir .` devolve score 45 com esse
critical. A causa é que `cli.py:263` chama `compile_project()`, que registra o
hook, e `cli.py:267` chama `install_boundary_guard()`, que o remove por design
— e `audit.py` não tem uma única menção a `boundary_guard`
(`grep -c` = 0).

A pergunta de escopo que a issue condicionava está **respondida com
evidência**: não existe caminho que mantenha o registro. `compile_project` tem
um único call site (`cli.py:263`), seguido de `install_boundary_guard`
incondicional; `compile-session` chama o mesmo instalador (`cli.py:470`); o
kill-switch não toca settings (`killswitch.py:38-47`). Mais forte: o estado
desregistrado é **travado por dois testes e2e** —
`tests/e2e/test_boundary_flow.py:154` e `tests/e2e/test_fase2_outcomes.py:790`
afirmam que `guard_tests.py` NÃO está no `PreToolUse` depois de
`harness compile`. Logo `compiler.py:176` emite uma entrada que nenhuma
instalação conserva.

A correção é remover essa entrada do render. É a Direção 2 da issue, e a única
alinhada com o princípio em `ARCHITECTURE.md:352` — "o `audit` não reimplementa
as regras do compilador — ele **é** o compilador". A Direção 1 criaria uma
segunda definição de "certo" dentro do audit, que é exatamente o que aquele
parágrafo existe para impedir.

**Parte C — a documentação.** Quatro documentos descrevem `guard_tests.py`
como guard de enforcement ativo. As afirmações já são falsas hoje, antes desta
demanda: quem entrega o gate de edição de teste é o `boundary_guard`. Deixar
assim mantém o leitor acreditando num portão que não roda.

## Critérios de aceitação

- `audit_project` sobre um repositório que passou pela sequência REAL de
  `harness compile` (`compile_project` **e** `install_boundary_guard`, as duas
  chamadas que `cli.py` faz no mesmo comando) não emite nenhum finding
  `critical` —
  prova: `python -m pytest tests/test_audit.py -q`
- O audit continua emitindo `critical` quando um hook está REALMENTE ausente do
  `settings.local.json` — cobertura **nova**, porque `hook_not_registered` tem
  hoje zero ocorrências em `tests/` — prova: mesma suíte
- Nenhum documento de `docs/plugin/` atribui a `guard_tests.py` o gate de
  edição de teste nem o lista como hook ativo — prova:
  `python -m pytest tests/test_docs_enforcement_claims.py -q`
- Suíte inteira verde e lint limpo — prova: `python -m pytest -q` e
  `ruff check .`

## Não-objetivos

- **Remover a geração de `guard_tests.py`** (`compiler.py:167`), o drift-check
  em `audit.py:91-104` e as menções em `doctor.py:75-78`. A própria issue #61
  chama isso de "escopo maior que o deste bug": vira remove-feature, não
  bugfix. Fica issue de follow-up para o script órfão.
- **Ensinar o `audit` a conhecer o `boundary_guard`** (Direção 1 da #61) —
  colide com `ARCHITECTURE.md:352`.
- **Qualquer detecção de verde-vazio** (issue #59) — descartada em execução, ver
  "Parte A — descartada". Inclui as três rotas avaliadas: sinal no output do
  runner, condição pelo `test_glob`, e casamento textual
  `verify_cmd == test_command`. As três foram medidas quebradas, cada uma por
  um motivo diferente.
- **Reescrever o `fix` de outros findings do audit** além do que a remoção da
  entrada já resolve.
- Mexer nos documentos de `docs/project/` que citam `guard_tests.py` — são
  registro histórico datado (auditorias e handoffs), e reescrever registro
  histórico é falsificá-lo.
- **Corrigir o default-deny na narrativa da seção 3 do `GUIDE.md`** além da
  tabela que esta demanda já tocou. A revisão fria mediu que três linhas
  vizinhas àquela que corrigimos também eram falsas — descreviam prompts `ask`
  onde o mecanismo hoje dá `allow` ou `deny` direto, porque a seção foi escrita
  antes do default-deny da v0.22.0. A tabela foi corrigida junto (deixar uma
  seção que acabei de editar em estado medido-falso seria pior), mas auditar o
  resto do documento contra o default-deny é escopo próprio.

## Unknowns

- **Como detectar verde-vazio sem ler prosa** — segue sem resposta, e é o
  conteúdo vivo da issue #59. Duas pistas medidas nesta demanda, para quem
  pegar o assunto: (a) o token de duração `ms` sobreviveu à tradução nos 9
  locales testados, mas não foi verificado contra as saídas de zero teste;
  (b) o Microsoft.Testing.Platform devolve **exit 8** para "zero testes
  executados", enquanto o VSTest devolve 0 — sinal de máquina de verdade, que
  cobre um dos dois caminhos do `dotnet test`.
- **`pytest` não é afetado**: sai **5** (`NO_TESTS_COLLECTED`) sem teste
  coletado, então `exit_code != 0` já o barra. É por isso que este repositório
  não reproduz a issue #59 com o próprio runner — o dogfood não alcança esse
  bug, e foi isso que obrigou toda a validação a depender de medição externa.
