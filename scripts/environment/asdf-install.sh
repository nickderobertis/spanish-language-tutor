#!/bin/bash

# Note: Must be run through direnv source

if ! which asdf >/dev/null 2>&1; then
  echo "asdf not found. Please install asdf first: https://asdf-vm.com/guide/getting-started.html"
  exit 1
fi

# Install asdf plugins
plugin_list=$(asdf plugin list)
plugins=("python" "nodejs" "pnpm" "uv" "just")

for plugin in "${plugins[@]}"; do
  if ! echo $plugin_list | grep -q " $plugin "; then
    asdf plugin add $plugin
    echo "Added asdf plugin $plugin"
  fi
done

# Install necessary versions
asdf install
