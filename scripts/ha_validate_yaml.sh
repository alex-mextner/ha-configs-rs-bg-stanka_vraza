#!/usr/bin/env bash
set -euo pipefail

CONTAINER="${HA_CONTAINER:-homeassistant-homeassistant-1}"

usage() {
    cat <<'EOF'
Usage: scripts/ha_validate_yaml.sh [YAML_FILE ...]

Validate Home Assistant YAML syntax with the PyYAML version available inside
the running HA container. Unknown HA tags such as !include, !secret, and !input
are parsed as plain YAML nodes so syntax errors are still caught.

With no files, validates active repo-level HA YAML files:
  configuration.yaml, automations.yaml, scripts.yaml, scenes.yaml,
  templates.yaml, known_devices.yaml, packages/*.yaml, blueprints/**/*.yaml,
  ui-*.yaml

Set HA_CONTAINER to override the container name.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
    echo "ERROR: HA container '$CONTAINER' is not available" >&2
    exit 2
fi

if [[ "$#" -eq 0 ]]; then
    shopt -s nullglob globstar
    files=(
        configuration.yaml
        automations.yaml
        scripts.yaml
        scenes.yaml
        templates.yaml
        known_devices.yaml
        packages/*.yaml
        blueprints/**/*.yaml
        ui-*.yaml
    )
    shopt -u nullglob globstar
else
    files=("$@")
fi

if [[ "${#files[@]}" -eq 0 ]]; then
    echo "No YAML files to validate."
    exit 0
fi

PY_CODE='
import sys
import yaml

path = sys.argv[1]


class HALoader(yaml.SafeLoader):
    pass


def construct_ha_tag(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


HALoader.add_multi_constructor("!", construct_ha_tag)

try:
    with open(path, encoding="utf-8") as handle:
        list(yaml.load_all(handle, Loader=HALoader))
except Exception as err:
    print(f"{type(err).__name__}: {err}", file=sys.stderr)
    sys.exit(1)
'

invalid=0
for input_file in "${files[@]}"; do
    file="${input_file#./}"

    if [[ "$file" == /* ]]; then
        case "$file" in
            "$REPO_ROOT"/*) file="${file#"$REPO_ROOT"/}" ;;
            *)
                echo "ERROR: $input_file is outside repo root" >&2
                invalid=1
                continue
                ;;
        esac
    fi

    if [[ ! "$file" =~ \.ya?ml$ ]]; then
        echo "SKIP: $file is not a YAML file"
        continue
    fi

    if [[ ! -e "$file" ]]; then
        echo "ERROR: $file does not exist" >&2
        invalid=1
        continue
    fi

    if docker exec "$CONTAINER" python3 -c "$PY_CODE" "/config/$file" >/dev/null; then
        echo "OK: $file"
    else
        echo "ERROR: $file" >&2
        invalid=1
    fi
done

exit "$invalid"
