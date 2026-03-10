#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update
sudo apt-get install -y python3 python3-gi gir1.2-gtk-3.0 libgtk-3-0 libx11-6 libxtst6
