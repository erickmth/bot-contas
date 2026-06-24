#!/usr/bin/env bash

echo "🚀 Iniciando build do Render..."

# Atualizar pip
pip install --upgrade pip

# Instalar dependências Python
pip install -r requirements.txt

# Instalar Chrome e ChromeDriver
echo "📦 Instalando Chrome..."
apt-get update
apt-get install -y wget gnupg unzip

# Instalar Chrome
wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add -
echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list
apt-get update
apt-get install -y google-chrome-stable

# Instalar ChromeDriver
echo "📦 Instalando ChromeDriver..."
CHROME_VERSION=$(google-chrome --version | awk '{print $3}')
CHROME_MAJOR_VERSION=${CHROME_VERSION%.*.*}
wget "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_$CHROME_MAJOR_VERSION" -O chromedriver_version
CHROMEDRIVER_VERSION=$(cat chromedriver_version)
wget "https://chromedriver.storage.googleapis.com/$CHROMEDRIVER_VERSION/chromedriver_linux64.zip"
unzip chromedriver_linux64.zip
mv chromedriver /usr/local/bin/
chmod +x /usr/local/bin/chromedriver

echo "✅ Build concluído com sucesso!"
