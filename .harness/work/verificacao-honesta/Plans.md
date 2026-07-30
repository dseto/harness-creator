# Plans: verificacao-honesta

A correção da issue #61 nas tarefas T-01/T-02, e a documentação que ela torna
falsa em T-05.

As tarefas T-03 e T-04, que endereçavam a issue #59, foram **descartadas em
execução** por decisão humana de 2026-07-30, depois de a medição derrubar a
premissa das duas. O registro do que se mediu e do porquê está no `spec.md`,
seção "Parte A — descartada". Os ids não foram reaproveitados: T-05 continua
T-05, para que a evidência e o histórico desta demanda não fiquem ambíguos.

## [T-01] O comando de auditoria deixa de reprovar repositório saudável
- files: `src/harness/compiler.py`, `tests/test_compiler.py`, `tests/test_audit.py`, `tests/test_hook_launcher.py`
- verify: `python -m pytest tests/test_compiler.py tests/test_audit.py -q`

Remove do render do compilador a entrada de registro de `guard_tests.py`
(`compiler.py:176`), que o instalador do `boundary_guard` apaga logo depois no
mesmo comando e que portanto nenhuma instalação conserva. Reescreve os dois
asserts que afirmam o contrário no nível unitário (`tests/test_compiler.py:86`
e `:177`) e adiciona o teste de dogfooding: auditar ESTE repositório não devolve
nenhum finding `critical`.

## [T-02] A auditoria continua acusando hook que realmente não está registrado
- files: `tests/test_audit.py`
- verify: `python -m pytest tests/test_audit.py -q`
- depends: T-01

Cobertura nova, não regressão: `hook_not_registered` tem hoje zero ocorrências
em `tests/`, então o detector do caso legítimo não está protegido por nada. Sem
isto, a correção da T-01 é indistinguível de "silenciaram o achado" — e trocar
um falso vermelho por um falso verde permanente é pior, porque é invisível.

## [T-05] A documentação para de prometer um portão de proteção que não roda
- files: `docs/plugin/GUIDE.md`, `docs/plugin/ARCHITECTURE.md`, `docs/plugin/TUTORIAL.md`, `docs/plugin/arquitetura-visual.html`, `tests/test_docs_enforcement_claims.py`, `skills/plan/references/contract-templates.md`, `tests/e2e/test_boundary_flow.py`, `tests/e2e/test_fase2_outcomes.py`
- verify: `python -m pytest tests/test_docs_enforcement_claims.py -q`
- depends: T-01

Quatro documentos descrevem `guard_tests.py` como hook de enforcement ativo —
`GUIDE.md:96` chega a prometer que editar um arquivo de teste dispara aquele
hook. É falso desde antes desta demanda: quem entrega esse gate é o
`boundary_guard`. Passa a atribuir a proteção a quem a executa, e um teste novo
trava as afirmações removidas para que não voltem por copiar-e-colar.
