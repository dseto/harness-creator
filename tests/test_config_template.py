"""T-07: `.harness/harness.yaml` nasce POR CÓDIGO a partir de
`harness.config.HarnessConfig`, não de um template em prosa mantido à parte
em `skills/init/SKILL.md`. Toda chave do schema sai no arquivo gerado, com
comentário — campo novo em `config.py` que esqueça a `description` derruba
este teste em vez de gerar um YAML com uma chave muda."""

from __future__ import annotations

import yaml

from harness.config import BudgetConfig, GovernanceConfig, HarnessConfig, VerificationConfig
from harness.templates import render_harness_yaml


def _all_field_names() -> set[str]:
    """Todo nome de campo do schema, recursivamente — a MESMA introspecção
    que o gerador usa, não uma lista copiada à mão (senão o teste só provaria
    que duas listas escritas por mim concordam entre si)."""
    names: set[str] = set()
    for model in (GovernanceConfig, BudgetConfig, VerificationConfig):
        names.update(model.model_fields.keys())
    return names


def test_every_schema_field_appears_in_the_rendered_yaml() -> None:
    rendered = render_harness_yaml()

    missing = [name for name in _all_field_names() if name not in rendered]
    assert not missing, f"campo(s) do schema ausente(s) do harness.yaml gerado: {missing}"


def test_every_scalar_field_carries_its_description_as_a_comment() -> None:
    rendered = render_harness_yaml()

    for model in (GovernanceConfig, BudgetConfig, VerificationConfig):
        for name, field in model.model_fields.items():
            if isinstance(field.default, list):
                continue
            if hasattr(field.annotation, "model_fields"):
                continue  # container aninhado (ex.: GovernanceConfig.budget) — suas próprias chaves são cobertas à parte
            assert field.description, f"{model.__name__}.{name} não tem description — geração deveria falhar"
            # Ao menos um trecho reconhecível do comentário chega ao arquivo.
            snippet = field.description.split(".")[0][:20]
            assert snippet in rendered, f"comentário de {name} não apareceu no yaml gerado"


def test_default_config_round_trips_through_the_rendered_yaml() -> None:
    rendered = render_harness_yaml()

    parsed = yaml.safe_load(rendered)
    reconstructed = HarnessConfig.model_validate(parsed)

    assert reconstructed == HarnessConfig()


def test_a_non_default_config_renders_its_actual_values_not_the_schema_defaults() -> None:
    cfg = HarnessConfig(
        governance=GovernanceConfig(approval_policy="paranoid", extra_allowed_commands=["docker build"]),
        verification=VerificationConfig(test_command="npm test", allowed_skips=["fixture externa"]),
    )

    rendered = render_harness_yaml(cfg)
    parsed = yaml.safe_load(rendered)
    reconstructed = HarnessConfig.model_validate(parsed)

    assert reconstructed == cfg
    assert "paranoid" in rendered
    assert "npm test" in rendered
    assert "docker build" in rendered
    assert "fixture externa" in rendered


def test_empty_list_fields_are_commented_out_with_an_example_not_rendered_as_empty_brackets() -> None:
    rendered = render_harness_yaml()

    assert "extra_allowed_commands: []" not in rendered
    assert "allowed_skips: []" not in rendered
    assert "# extra_allowed_commands:" in rendered
    assert "# allowed_skips:" in rendered


def test_non_empty_list_fields_render_active_not_commented() -> None:
    cfg = HarnessConfig(governance=GovernanceConfig(extra_allowed_commands=["docker build"]))

    rendered = render_harness_yaml(cfg)

    assert "  extra_allowed_commands:" in rendered
    assert "# extra_allowed_commands:" not in rendered
    assert "docker build" in rendered


def test_rendered_yaml_is_valid_yaml_with_governance_and_verification_top_level_keys() -> None:
    rendered = render_harness_yaml()

    parsed = yaml.safe_load(rendered)
    assert set(parsed.keys()) == {"governance", "verification"}
    assert parsed["governance"]["approval_policy"] == "balanced"
    assert parsed["verification"]["test_command"] == "pytest -x --tb=short"
