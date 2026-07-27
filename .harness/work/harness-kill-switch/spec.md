---
slug: harness-kill-switch
approved_by: Daniel Seto
approved_at: 2026-07-23T13:05:00Z
stop_conditions:
  - "3 falhas consecutivas da mesma suíte de teste (verify_cmd) sem progresso — pare e devolva ao humano"
  - "Uma tentativa de tornar o floor anti-auto-desativação genérico o suficiente para quebrar um teste e2e existente (ex.: test_extra_allowed_commands_e2e, que prova de propósito que a superfície de COMANDO continua enforçada) — pare, não relaxe o teste, devolva ao humano"
  - "Necessidade de tocar qualquer arquivo fora da superfície declarada em files[] — pare e replaneje via /harness-creator:plan ou harness task add-file, nunca amplie a superfície por conta própria"
---

# Spec: Kill-switch externo do harness

## Escopo

Adicionar um comando `harness disable` / `harness enable` / `harness status`,
rodável **apenas pelo usuário no seu próprio terminal** (fora do Claude Code,
onde nenhum hook `PreToolUse` intercepta), que desativa **completamente** o
harness — todos os hooks gerados (`boundary_guard`, `session_start`,
`stop_hook`, `guard_tests`, `guard_test_runner`) passam a no-op enquanto
desativado. Objetivo: destravar processos legítimos que o harness bloqueia,
sem cirurgia manual em `.claude/settings.json`.

O invariante de segurança: o **agente** rodando dentro do Claude Code **não
pode** se auto-desativar. A proteção é uma regra de nível *floor* no
`boundary_guard` (incondicional, precede a checagem de contrato) que nega,
enquanto o harness está ativo:
- rodar `harness disable` (ou `python -m harness.cli disable`) via Bash/PowerShell;
- criar/escrever o arquivo-sentinela via Edit/Write/MultiEdit/NotebookEdit,
  cmdlets de escrita do PowerShell, ou redirecionamento/`tee` no Bash.

O usuário, no terminal próprio, não passa por hook nenhum — o comando funciona
livremente. Assimetria já comprovada: o `boundary_guard` só dispara dentro de
sessão do Claude Code.

**Estado = arquivo-sentinela** `.harness/harness.disabled` (JSON com
`disabled_at`/`note`), machine-local e gitignored (mesma filosofia de
`.claude/settings.json` e dos hooks — estado operacional de máquina, não
versionado; um clone novo nasce ativo). Presença do arquivo = harness off.

**Sem paradoxo de recursão:**
- sentinel ausente → harness ativo → floor protege a criação do sentinel e o
  comando `disable` → agente preso;
- sentinel presente → harness desativado → cada hook faz no-op no topo do
  `main()` → nada dispara (estado terminal que só o usuário alcança).

O agente só alcançaria a transição ativo→desativado criando o sentinel, e é
exatamente essa criação que o floor nega enquanto ativo.

**Ancoragem por `__file__`:** cada hook gerado mora em
`<repo>/.harness/hooks/<hook>.py`; a checagem de "estou desativado?" resolve o
sentinel como `Path(__file__).resolve().parent.parent / "harness.disabled"`
(= `<repo>/.harness/harness.disabled`), independente do `cwd` do payload
(que pode derivar) — mesmo racional do `_resolve_repo_root_anchor` já existente.

## Escopo do floor (mesmo residual já assumido pelo floor de segredo)

A proteção cobre os vetores comuns e observáveis (nome do comando + escrita
direta do sentinel via redirecionamento/cmdlet/tool de escrita). Bypass via
interpretador (`python -c "open('.harness/harness.disabled','w')"`, `node -e`)
**não** é perseguido — mesmo limite deliberado, documentado e aceito do floor
de segredo (`is_floor_bash_secret_redirect`, docstring do módulo
`boundary_guard`). Deploy single-user interno; a ameaça é auto-desativação
acidental/agêntica, não um adversário determinado ofuscando o alvo.

## Critérios de aceitação

- Módulo core (`is_disabled`/`disable`/`enable`/`status` + snippet de checagem
  para os hooks): `pytest tests/test_killswitch.py -q`
- CLI `harness disable|enable|status`: `pytest tests/test_cli.py -q`
- `boundary_guard`: short-circuit quando sentinel presente + floor que nega
  criar o sentinel e rodar `harness disable` quando ausente (Bash, PowerShell,
  Edit/Write) + `.harness/.gitignore` do sentinel por `install_boundary_guard`:
  `pytest tests/test_boundary_guard.py -q`
- Hooks `session_start` e `stop_hook` no-op quando sentinel presente:
  `pytest tests/test_session_start.py tests/test_stop_hook.py -q`
- Hooks de plugin (`guard_tests`, `guard_test_runner`) no-op quando sentinel
  presente: `pytest tests/test_compiler.py -q`
- Regressão completa verde: `pytest tests -q`
- Lint limpo: `ruff check .`

## Não-objetivos

- Proteger contra bypass via interpretador (`python -c open(...)`) — fora de
  escopo por design (ver "Escopo do floor").
- Proteger `enable` — re-ativar é inofensivo (só re-liga a proteção); e com o
  harness desativado não há hook rodando para negar coisa alguma.
- Cirurgia em `.claude/settings.json` (remover/mover o bloco de hooks) — o
  sentinel torna isso desnecessário; os hooks continuam instalados e apenas
  no-op.
- Sub-caso 3 do achado B (empilhamento `boundary_guard` × `guard_tests` como
  dois mecanismos coexistindo) — segue como follow-up independente; aqui só
  garantimos que AMBOS respeitam o sentinel.
- Versionar o sentinel / desativar o harness para outros clones.

## Unknowns

- `package_manager`: nenhum lockfile detectado (`analyze` reportou como
  unknown). **Não confirmado e não relevante** para esta demanda — nenhuma
  tarefa instala dependências; `pytest`/`ruff` vêm do extra `dev` do
  `pyproject.toml`. Permanece unknown explícito, não promovido a fato.
