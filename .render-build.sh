#!/usr/bin/env bash

echo "🚀 Iniciando build do Render..."

# Atualizar pip
pip install --upgrade pip

# Instalar dependências Python
pip install -r requirements.txt

# Instalar Chrome e ChromeDriver (versão para Render)
echo "📦 Instalando Chrome e ChromeDriver..."

# Baixar e instalar Chrome diretamente
wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
dpkg -i /tmp/chrome.deb || apt-get -f install -y
rm /tmp/chrome.deb

# Instalar ChromeDriver via webdriver-manager (já está no requirements)
echo "✅ Chrome e ChromeDriver instalados via webdriver-manager"

echo "✅ Build concluído com sucesso!"
