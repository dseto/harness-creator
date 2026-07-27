## [T-01] Converter pyproject.toml para dynamic version via hatchling
- files: `pyproject.toml`
- verify: `python -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); assert 'version' not in d['project']"`

## [T-02] Guard test: marketplace.json e plugin.json batem com harness.__version__
- files: `tests/test_version_sync.py`
- verify: `pytest tests/test_version_sync.py -q`
- depends: T-01

## [T-03] Confirmar que a fiacao dynamic-version aponta pro arquivo certo e bate com harness.__version__
- files: `pyproject.toml`
- verify: `python -c "import tomllib, pathlib, harness; d = tomllib.load(open('pyproject.toml', 'rb')); path = d['tool']['hatch']['version']['path']; assert path == 'src/harness/__init__.py'; lines = pathlib.Path(path).read_text().splitlines(); value = next(l.split('=', 1)[1].strip().strip('\"') for l in lines if l.strip().startswith('__version__')); assert value == harness.__version__, (value, harness.__version__)"`
- depends: T-01

## [T-04] Rodar suite completa para confirmar ausencia de regressao
- files: `pyproject.toml`, `tests/test_version_sync.py`
- verify: `pytest -q`
- depends: T-02, T-03
